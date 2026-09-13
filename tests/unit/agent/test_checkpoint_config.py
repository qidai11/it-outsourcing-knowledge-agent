from __future__ import annotations

from project_agent.agent.checkpoint import to_psycopg_dsn


def test_asyncpg_sqlalchemy_url_is_converted_for_async_postgres_saver() -> None:
    assert (
        to_psycopg_dsn("postgresql+asyncpg://user:pass@127.0.0.1:5432/project_agent")
        == "postgresql://user:pass@127.0.0.1:5432/project_agent"
    )
