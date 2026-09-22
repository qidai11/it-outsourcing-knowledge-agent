"""add WS2 run runtime envelope fields

Revision ID: 0005_run_runtime_envelope
Revises: 0004_issue_create_idempotency
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_run_runtime_envelope"
down_revision: str | None = "0004_issue_create_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("business_mode", sa.String(length=32), nullable=True),
    )
    op.alter_column(
        "agent_runs",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    op.execute("UPDATE agent_runs SET started_at = CURRENT_TIMESTAMP WHERE started_at IS NULL")
    op.alter_column(
        "agent_runs",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    op.drop_column("agent_runs", "business_mode")
