"""add pg_trgm spelling suggestion index

Revision ID: 0002_identifier_trigram
Revises: 0001_initial
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_identifier_trigram"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "idx_identifier_trgm",
        "document_identifiers",
        ["normalized_value"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"normalized_value": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("idx_identifier_trgm", table_name="document_identifiers")
    # Do not drop pg_trgm: extensions can be shared by other schemas/features.
