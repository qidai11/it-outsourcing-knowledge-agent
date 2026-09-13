from __future__ import annotations

from uuid import UUID

from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.prompt_config import PromptConfigService


async def load_prompt_snapshot_node(
    state: AgentState,
    *,
    prompt_config: PromptConfigService,
    store: QAGraphStorePort,
    model_alias: str,
    config_key: str = "prompt.qa.answer",
) -> AgentState:
    run_id = UUID(state["run_id"])
    snapshot = await prompt_config.get_snapshot(config_key)
    artifact_id = await store.record_prompt_snapshot(
        run_id=run_id,
        model_alias=model_alias,
        snapshot=snapshot,
    )
    return {"prompt_snapshot_id": str(artifact_id)}
