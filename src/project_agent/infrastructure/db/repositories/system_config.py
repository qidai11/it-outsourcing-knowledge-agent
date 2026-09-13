from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.application.services.prompt_config import PromptConfigRecord
from project_agent.infrastructure.db.models.schema import SystemConfigModel


class SqlAlchemyPromptConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_enabled(self, config_key: str) -> PromptConfigRecord:
        stmt = (
            select(SystemConfigModel)
            .where(
                SystemConfigModel.config_key == config_key,
                SystemConfigModel.enabled.is_(True),
            )
            .order_by(SystemConfigModel.version.desc())
            .limit(1)
        )
        row = (await self._session.scalars(stmt)).one_or_none()
        if row is None:
            raise LookupError(f"no enabled prompt config: {config_key}")
        content = row.config_value_json.get("content")
        if not isinstance(content, str) or not content:
            raise ValueError(f"prompt config {config_key} is missing string content")
        return PromptConfigRecord(
            config_key=row.config_key,
            content=content,
            version=row.version,
            content_hash=row.content_hash,
        )
