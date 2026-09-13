"""make background jobs aggregate-only and lease aware

Revision ID: 0003_background_job_leases
Revises: 0002_identifier_trigram
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_background_job_leases"
down_revision: str | None = "0002_identifier_trigram"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("aggregate_id", sa.String(length=255), nullable=True))
    op.add_column("background_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("background_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE background_jobs
        SET aggregate_id = COALESCE(NULLIF(payload_json ->> 'aggregate_id', ''), id::text)
        WHERE aggregate_id IS NULL
        """
    )
    op.alter_column("background_jobs", "aggregate_id", nullable=False)
    op.drop_column("background_jobs", "payload_json")
    op.create_index(
        "idx_background_jobs_claim",
        "background_jobs",
        ["status", "available_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "idx_background_jobs_reaper",
        "background_jobs",
        ["status", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'RUNNING'"),
    )


def downgrade() -> None:
    op.drop_index("idx_background_jobs_reaper", table_name="background_jobs")
    op.drop_index("idx_background_jobs_claim", table_name="background_jobs")
    op.add_column(
        "background_jobs",
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.execute(
        "UPDATE background_jobs SET payload_json = json_build_object('aggregate_id', aggregate_id)"
    )
    op.drop_column("background_jobs", "lease_expires_at")
    op.drop_column("background_jobs", "heartbeat_at")
    op.drop_column("background_jobs", "aggregate_id")
