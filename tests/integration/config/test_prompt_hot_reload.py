from __future__ import annotations

from dataclasses import replace

import pytest

from project_agent.application.services.prompt_config import (
    PromptConfigRecord,
    PromptConfigService,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakePromptRepository:
    def __init__(self, record: PromptConfigRecord) -> None:
        self.record = record
        self.calls = 0

    async def latest_enabled(self, config_key: str) -> PromptConfigRecord:
        self.calls += 1
        if self.record.config_key != config_key:
            raise LookupError(config_key)
        return self.record


@pytest.mark.asyncio
async def test_prompt_update_only_affects_new_snapshot_after_short_ttl() -> None:
    clock = FakeClock()
    repo = FakePromptRepository(
        PromptConfigRecord(
            config_key="prompt.answer",
            content="answer-v1",
            version=1,
            content_hash="hash-v1",
        )
    )
    service = PromptConfigService(repo, ttl_seconds=5, clock=clock)

    run_a = await service.get_snapshot("prompt.answer")
    repo.record = replace(repo.record, content="answer-v2", version=2, content_hash="hash-v2")

    # Existing run retains its immutable snapshot and cache shields current TTL window.
    within_ttl = await service.get_snapshot("prompt.answer")
    assert run_a.version == 1
    assert run_a.content == "answer-v1"
    assert within_ttl.version == 1

    clock.now += 6
    run_b = await service.get_snapshot("prompt.answer")

    assert run_a.version == 1
    assert run_b.version == 2
    assert run_b.content_hash == "hash-v2"

@pytest.mark.asyncio
async def test_prompt_hot_reload_reads_latest_enabled_system_config_from_postgres() -> None:
    import os
    from uuid import uuid4

    if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION=1 to run live prompt config gate")

    from sqlalchemy import delete

    from project_agent.infrastructure.db.models.schema import SystemConfigModel
    from project_agent.infrastructure.db.repositories.system_config import (
        SqlAlchemyPromptConfigRepository,
    )
    from project_agent.infrastructure.db.session import create_engine, create_session_factory

    engine = create_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    key = f"prompt.task8.{uuid4()}"
    actor = uuid4()
    try:
        async with factory() as session:
            session.add(
                SystemConfigModel(
                    config_key=key,
                    config_value_json={"content": "v1"},
                    version=1,
                    content_hash="hash-v1",
                    enabled=True,
                    updated_by=actor,
                )
            )
            await session.commit()

        async with factory() as session:
            service = PromptConfigService(
                SqlAlchemyPromptConfigRepository(session), ttl_seconds=30
            )
            run_a = await service.get_snapshot(key)
            assert run_a.version == 1

        async with factory() as session:
            session.add(
                SystemConfigModel(
                    config_key=key,
                    config_value_json={"content": "v2"},
                    version=2,
                    content_hash="hash-v2",
                    enabled=True,
                    updated_by=actor,
                )
            )
            await session.commit()

        async with factory() as session:
            service = PromptConfigService(
                SqlAlchemyPromptConfigRepository(session), ttl_seconds=30
            )
            run_b = await service.get_snapshot(key)
            assert run_a.version == 1
            assert run_a.content == "v1"
            assert run_b.version == 2
            assert run_b.content == "v2"
    finally:
        async with factory() as session:
            await session.execute(delete(SystemConfigModel).where(SystemConfigModel.config_key == key))
            await session.commit()
        await engine.dispose()
