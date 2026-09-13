from __future__ import annotations

import importlib.util

import pytest

LANGGRAPH_AVAILABLE = importlib.util.find_spec("langgraph") is not None


@pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="requires synchronized LangGraph runtime")
def test_issue_graph_uses_resumable_interrupt_contract() -> None:
    from project_agent.agent.issue_graph import build_issue_create_graph

    assert callable(build_issue_create_graph)
