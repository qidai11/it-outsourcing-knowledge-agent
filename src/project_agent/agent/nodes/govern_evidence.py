from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.serialization import deserialize_authorized_context
from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.evidence_governance import EvidenceGovernanceService


async def govern_evidence_node(
    state: AgentState,
    *,
    evidence_governance: EvidenceGovernanceService,
    store: QAGraphStorePort,
) -> AgentState:
    run_id = UUID(state["run_id"])
    project_id = UUID(state["project_id"])
    raw_bundle_id = UUID(state["evidence_bundle_id"])
    context = deserialize_authorized_context(
        await store.load_artifact(UUID(state["access_scope_id"]))
    )
    query = await store.load_query(run_id)
    chunks = await store.load_evidence_bundle(raw_bundle_id)
    pack = await evidence_governance.pack(
        project_id=project_id,
        project_code=context.project_code,
        chunks=chunks,
    )
    if not pack.evidence:
        return {
            "route": "refusal",
            "last_error_code": "NO_GOVERNED_EVIDENCE",
        }
    governed_bundle_id = await store.save_governed_evidence_bundle(
        run_id=run_id,
        project_id=project_id,
        query_text=query,
        pack=pack,
    )
    return {
        "evidence_bundle_id": str(governed_bundle_id),
        "route": "generate_answer",
        "last_error_code": None,
    }
