from __future__ import annotations

from project_agent.application.services.prompt_config import PromptConfigRecord


class FakePromptConfigRepository:
    def __init__(self, record: PromptConfigRecord) -> None:
        self.record = record

    async def latest_enabled(self, config_key: str) -> PromptConfigRecord:
        if config_key != self.record.config_key:
            raise LookupError(config_key)
        return self.record
