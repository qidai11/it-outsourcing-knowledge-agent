from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


def to_psycopg_dsn(database_url: str) -> str:
    """Convert SQLAlchemy asyncpg URLs to the DSN expected by Psycopg/LangGraph."""

    if database_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+asyncpg://")
    if database_url.startswith("postgres+asyncpg://"):
        return "postgresql://" + database_url.removeprefix("postgres+asyncpg://")
    return database_url


@asynccontextmanager
async def async_postgres_saver(database_url: str) -> AsyncIterator[Any]:
    """Create and initialize LangGraph's AsyncPostgresSaver lazily.

    Lazy importing keeps non-Graph unit tests usable before optional runtime
    dependencies are synchronized. Strict msgpack is enabled before the
    checkpointer module is imported, following the package security guidance.
    """

    os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:  # pragma: no cover - exercised in live environment
        raise RuntimeError(
            "langgraph-checkpoint-postgres is required for PostgreSQL checkpoints"
        ) from exc

    async with AsyncPostgresSaver.from_conn_string(to_psycopg_dsn(database_url)) as saver:
        await saver.setup()
        yield saver
