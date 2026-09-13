from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.analyze_query import QueryAnalysisService
from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort


async def analyze_query_node(
    state: AgentState,
    *,
    query_analysis: QueryAnalysisService,
    store: QAGraphStorePort,
) -> AgentState:
    run_id = UUID(state["run_id"])
    query = await store.load_query(run_id)
    analysis = query_analysis.analyze(query)
    artifact_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="QUERY_ANALYSIS",
        payload=analysis.model_dump(mode="json"),
    )
    return {"query_analysis_id": str(artifact_id), "route": "project_knowledge_qa"}
