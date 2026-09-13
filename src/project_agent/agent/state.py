from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    """Checkpoint-safe graph state.

    The state deliberately contains only entity/artifact references plus small
    routing controls. Query text, prompt content, Evidence and answer content
    live in PostgreSQL-backed stores rather than checkpoint payloads.
    """

    run_id: str
    thread_id: str
    user_id: str
    project_id: str | None
    prompt_snapshot_id: str | None
    query_analysis_id: str | None
    project_selection_id: str | None
    access_scope_id: str | None
    retrieval_plan_id: str | None
    evidence_bundle_id: str | None
    answer_draft_id: str | None
    citation_guard_id: str | None
    answer_id: str | None
    issue_candidate_id: str | None
    issue_draft_id: str | None
    tool_confirmation_id: str | None
    issue_creation_id: str | None
    revision_count: int
    route: str | None
    last_error_code: str | None


AGENT_STATE_REFERENCE_FIELDS = frozenset(AgentState.__annotations__)
