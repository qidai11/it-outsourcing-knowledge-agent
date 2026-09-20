from __future__ import annotations

import sys
from types import ModuleType
from typing import Any, cast

from project_agent.agent.graph import QAGraphDependencies, build_project_qa_graph


class _FakeStateGraph:
    last: _FakeStateGraph | None = None

    def __init__(self, state_type: object) -> None:
        self.nodes: dict[str, object] = {}
        self.edges: list[tuple[object, object]] = []
        self.conditionals: dict[str, dict[str, object]] = {}
        _FakeStateGraph.last = self

    def add_node(self, name: str, node: object) -> None:
        self.nodes[name] = node

    def add_edge(self, source: object, target: object) -> None:
        self.edges.append((source, target))

    def add_conditional_edges(
        self,
        source: str,
        route: object,
        mapping: dict[str, object],
    ) -> None:
        self.conditionals[source] = mapping

    def compile(self, *, checkpointer: object | None = None) -> _FakeStateGraph:
        return self


def test_qa_graph_wires_bounded_retrieval_grade_loop(monkeypatch) -> None:
    graph_module = ModuleType("langgraph.graph")
    graph_module.START = "__start__"  # type: ignore[attr-defined]
    graph_module.END = "__end__"  # type: ignore[attr-defined]
    graph_module.StateGraph = _FakeStateGraph  # type: ignore[attr-defined]
    package = ModuleType("langgraph")
    monkeypatch.setitem(sys.modules, "langgraph", package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", graph_module)

    deps = cast(QAGraphDependencies, cast(Any, object()))
    build_project_qa_graph(deps)
    builder = _FakeStateGraph.last

    assert builder is not None
    assert "grade_retrieval" in builder.nodes
    assert builder.conditionals["retrieve"] == {
        "grade_retrieval": "grade_retrieval",
        "refuse": "refuse",
    }
    assert builder.conditionals["grade_retrieval"] == {
        "govern_evidence": "govern_evidence",
        "retrieve": "retrieve",
        "refuse": "refuse",
    }
