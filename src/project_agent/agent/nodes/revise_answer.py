from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.generate_answer import _generate_draft
from project_agent.agent.state import AgentState
from project_agent.application.ports.llm import StructuredLLMPort, StructuredLLMUsagePort
from project_agent.application.ports.qa_graph import QAGraphStorePort


async def revise_answer_node(
    state: AgentState,
    *,
    llm: StructuredLLMPort,
    llm_usage: StructuredLLMUsagePort,
    store: QAGraphStorePort,
    model_alias: str,
) -> AgentState:
    revision_count = int(state.get("revision_count", 0))
    if revision_count >= 1:
        return {"route": "refusal", "last_error_code": "CITATION_GUARD_FAILED"}
    guard_payload = await store.load_artifact(UUID(state["citation_guard_id"]))
    raw_errors = guard_payload.get("errors", [])
    errors = tuple(str(value) for value in raw_errors) if isinstance(raw_errors, list) else ()
    next_state = dict(state)
    next_state["revision_count"] = revision_count + 1
    draft_id, _ = await _generate_draft(
        next_state,
        llm=llm,
        llm_usage=llm_usage,
        store=store,
        model_alias=model_alias,
        revision_errors=errors,
    )
    return {
        "answer_draft_id": str(draft_id),
        "revision_count": revision_count + 1,
        "route": "citation_guard",
        "last_error_code": None,
    }
