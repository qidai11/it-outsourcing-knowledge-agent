from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.models import GroundedAnswerDraft
from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.citation_guard import CitationGuard
from project_agent.domain.evidence import CitationReference
from project_agent.observability.logging import get_logger
from project_agent.observability.metrics import current_metrics


def _render_answer(draft: GroundedAnswerDraft) -> str:
    lines: list[str] = []
    for claim in draft.claims:
        suffix = "".join(f"[{label}]" for label in claim.evidence_ids)
        lines.append(f"{claim.text} {suffix}".rstrip())
    if draft.conflict_disclosure is not None:
        suffix = "".join(f"[{label}]" for label in draft.conflict_disclosure.evidence_ids)
        lines.append(f"冲突说明：{draft.conflict_disclosure.text} {suffix}".rstrip())
    return "\n".join(lines)


async def citation_guard_node(
    state: AgentState,
    *,
    guard: CitationGuard,
    store: QAGraphStorePort,
) -> AgentState:
    run_id = UUID(state["run_id"])
    project_id = UUID(state["project_id"])
    draft = GroundedAnswerDraft.model_validate(
        await store.load_artifact(UUID(state["answer_draft_id"]))
    )
    bundle = await store.load_governed_evidence_bundle(UUID(state["evidence_bundle_id"]))
    result = guard.validate(draft, bundle=bundle, project_id=project_id)
    guard_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="CITATION_GUARD",
        payload={
            "valid": result.valid,
            "coverage": result.coverage,
            "errors": list(result.errors),
            "used_evidence_ids": list(result.used_evidence_ids),
        },
    )
    metrics = current_metrics()
    if result.valid:
        if metrics is not None:
            metrics.observe_citation(outcome="pass")
        get_logger().info("citation_guard_passed", outcome="pass", coverage=result.coverage)
        evidence_by_label = {item.label: item for item in bundle.evidence}
        citations = tuple(
            CitationReference(
                citation_no=int(label[1:]),
                evidence_snapshot_id=evidence_by_label[label].snapshot_id,
            )
            for label in result.used_evidence_ids
        )
        answer_id = await store.save_grounded_answer(
            run_id=run_id,
            answer_text=_render_answer(draft),
            citations=citations,
        )
        return {
            "citation_guard_id": str(guard_id),
            "answer_id": str(answer_id),
            "route": "answered",
            "last_error_code": None,
        }
    if int(state.get("revision_count", 0)) < 1:
        if metrics is not None:
            metrics.observe_citation(outcome="revision")
        get_logger().info("citation_guard_revision", outcome="revision", coverage=result.coverage)
        return {
            "citation_guard_id": str(guard_id),
            "route": "revise_answer",
            "last_error_code": "CITATION_GUARD_RETRY",
        }
    if metrics is not None:
        metrics.observe_citation(outcome="refusal")
    get_logger().info("citation_guard_refused", outcome="refusal", coverage=result.coverage)
    return {
        "citation_guard_id": str(guard_id),
        "route": "refusal",
        "last_error_code": "CITATION_GUARD_FAILED",
    }
