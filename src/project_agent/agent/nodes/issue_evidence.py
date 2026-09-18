from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.serialization import deserialize_authorized_context
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.agent.state import AgentState
from project_agent.application.ports.knowledge import (
    KnowledgeRetrievalPort,
    KnowledgeRetrievalRequest,
)
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.evidence_governance import EvidenceGovernanceService
from project_agent.application.services.issue_evidence import IssueEvidenceSelector
from project_agent.domain.evidence import GovernedEvidencePack


async def retrieve_issue_evidence_node(
    state: AgentState,
    *,
    selector: IssueEvidenceSelector,
    knowledge: KnowledgeRetrievalPort,
    access_policy: ProjectAccessPolicy,
    evidence_governance: EvidenceGovernanceService,
    store: QAGraphStorePort,
) -> AgentState:
    project_raw = state.get("project_id")
    scope_raw = state.get("access_scope_id")
    if not project_raw or not scope_raw:
        return {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}

    run_id = UUID(state["run_id"])
    project_id = UUID(project_raw)
    context = deserialize_authorized_context(await store.load_artifact(UUID(scope_raw)))
    query = await store.load_query(run_id)
    version_ids = await selector.select_document_version_ids(
        project_id=project_id,
        context=context,
    )
    if not version_ids:
        return {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}

    request = KnowledgeRetrievalRequest(
        project_id=context.project_code,
        query=query,
        limit=10,
        document_version_ids=tuple(str(value) for value in version_ids),
    )
    constrained = access_policy.constrain_retrieval(request, context)
    if constrained is None:
        return {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}

    await store.increment_retrieval_rounds(run_id=run_id)
    chunks = access_policy.postfilter_evidence(
        await knowledge.retrieve(constrained),
        context,
    )
    pack = await evidence_governance.pack(
        project_id=project_id,
        project_code=context.project_code,
        chunks=chunks,
    )
    pack = GovernedEvidencePack(
        evidence=tuple(
            item
            for item in pack.evidence
            if item.document_category in IssueEvidenceSelector.ALLOWED_CATEGORIES
        ),
        unresolved_conflicts=dict(pack.unresolved_conflicts),
    )
    if not pack.evidence:
        return {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}

    bundle_id = await store.save_governed_evidence_bundle(
        run_id=run_id,
        project_id=project_id,
        query_text=query,
        pack=pack,
    )
    return {
        "evidence_bundle_id": str(bundle_id),
        "route": "issue_evidence_ready",
        "last_error_code": None,
    }
