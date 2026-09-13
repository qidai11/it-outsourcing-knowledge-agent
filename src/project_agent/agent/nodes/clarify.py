from __future__ import annotations

from uuid import UUID

from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort


async def clarify_project_node(state: AgentState, *, store: QAGraphStorePort) -> AgentState:
    run_id = UUID(state["run_id"])
    selection = await store.load_artifact(UUID(state["project_selection_id"]))
    raw_codes = selection.get("candidate_project_codes", [])
    codes = [str(value) for value in raw_codes] if isinstance(raw_codes, list) else []
    suffix = f"可访问项目：{', '.join(codes)}。" if codes else ""
    answer_id = await store.save_answer(
        run_id=run_id,
        answer_text=f"请明确这次问题属于哪个项目。{suffix}",
        refusal_reason="PROJECT_CLARIFICATION_REQUIRED",
    )
    return {"answer_id": str(answer_id), "route": "clarification"}
