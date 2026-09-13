from __future__ import annotations

from project_agent.agent.state import AGENT_STATE_REFERENCE_FIELDS


def test_agent_state_does_not_store_large_payload_fields() -> None:
    forbidden = {
        "query_text",
        "question",
        "messages",
        "evidence",
        "chunks",
        "tool_result",
        "answer_text",
        "prompt_content",
    }
    assert forbidden.isdisjoint(AGENT_STATE_REFERENCE_FIELDS)
    assert {
        "run_id",
        "thread_id",
        "user_id",
        "query_analysis_id",
        "retrieval_plan_id",
        "evidence_bundle_id",
        "answer_id",
    }.issubset(AGENT_STATE_REFERENCE_FIELDS)
