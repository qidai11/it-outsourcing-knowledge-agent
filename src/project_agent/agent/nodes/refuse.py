from __future__ import annotations

from uuid import UUID

from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort


REFUSAL_TEXT = "没有找到足够的已授权证据，无法可靠回答。"


async def refuse_node(state: AgentState, *, store: QAGraphStorePort) -> AgentState:
    run_id = UUID(state["run_id"])
    reason = state.get("last_error_code") or "REFUSED"
    text = REFUSAL_TEXT
    if reason in {"PROJECT_ACCESS_DENIED", "NO_AUTHORIZED_PROJECT"}:
        text = "当前身份没有该项目的有效访问权限。"
    answer_id = await store.save_answer(
        run_id=run_id,
        answer_text=text,
        refusal_reason=reason,
    )
    return {"answer_id": str(answer_id), "route": "refusal"}
