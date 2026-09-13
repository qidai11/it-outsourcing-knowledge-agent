"""add provider-side sandbox issue request id uniqueness

Revision ID: 0004_issue_create_idempotency
Revises: 0003_background_job_leases
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_issue_create_idempotency"
down_revision: str | None = "0003_background_job_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_sandbox_issues_project_request",
        "sandbox_issues",
        ["project_id", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("client_request_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_sandbox_issues_project_request", table_name="sandbox_issues")
