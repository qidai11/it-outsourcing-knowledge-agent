from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from project_agent.agent.state import AgentState
from project_agent.application.services.issue_confirmation import (
    ConfirmationExpired,
    ConfirmationPayloadMismatch,
    IssueConfirmationService,
)
from project_agent.domain.issues import ConfirmationAction


def _langgraph_interrupt(value: dict[str, object]) -> Any:
    try:
        from langgraph.types import interrupt
    except ImportError as exc:  # pragma: no cover - synchronized runtime dependency
        raise RuntimeError("langgraph is required for issue confirmation interrupts") from exc
    return interrupt(value)


async def confirm_issue_create_node(
    state: AgentState,
    *,
    confirmations: IssueConfirmationService,
    interrupt_fn: Callable[[dict[str, object]], Any] | None = None,
) -> AgentState:
    draft_id_raw = state.get("issue_draft_id")
    if not draft_id_raw:
        return {"route": "refusal", "last_error_code": "ISSUE_DRAFT_REQUIRED"}
    draft_id = UUID(draft_id_raw)
    prepared = await confirmations.prepare(draft_id)

    # IMPORTANT: interrupt is the first effectful action in this node. LangGraph
    # restarts the node from the beginning when resumed, so persistence must only
    # happen after the resume value is returned.
    resume = (interrupt_fn or _langgraph_interrupt)(prepared.model_dump(mode="json"))
    if not isinstance(resume, dict):
        return {"route": "refusal", "last_error_code": "INVALID_CONFIRMATION_RESPONSE"}
    try:
        action = ConfirmationAction(str(resume.get("action", "")))
    except ValueError:
        return {"route": "refusal", "last_error_code": "INVALID_CONFIRMATION_ACTION"}
    response_hash = resume.get("request_payload_hash")
    if not isinstance(response_hash, str):
        return {"route": "refusal", "last_error_code": "CONFIRMATION_HASH_REQUIRED"}
    try:
        receipt = await confirmations.record_decision(
            draft_id=draft_id,
            actor_id=UUID(state["user_id"]),
            action=action,
            request_payload_hash=response_hash,
        )
    except ConfirmationPayloadMismatch:
        return {"route": "refusal", "last_error_code": "CONFIRMATION_PAYLOAD_MISMATCH"}
    except ConfirmationExpired:
        return {"route": "refusal", "last_error_code": "CONFIRMATION_EXPIRED"}
    if action is ConfirmationAction.CANCEL:
        return {
            "tool_confirmation_id": str(receipt.id),
            "route": "cancelled",
            "last_error_code": None,
        }
    return {
        "tool_confirmation_id": str(receipt.id),
        "route": "execute_issue_create",
        "last_error_code": None,
    }
