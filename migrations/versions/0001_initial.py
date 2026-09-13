"""Initial compact business persistence model.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('background_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('namespace', sa.String(length=64), nullable=False),
    sa.Column('job_type', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('payload_json', sa.JSON(), nullable=False),
    sa.Column('result_json', sa.JSON(), nullable=True),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('locked_by', sa.String(length=128), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_background_jobs_status'), 'background_jobs', ['status'], unique=False)
    op.create_table('clients',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_clients_company_id'), 'clients', ['company_id'], unique=False)
    op.create_table('data_retention_policies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('scope_type', sa.String(length=32), nullable=False),
    sa.Column('scope_id', sa.Uuid(), nullable=True),
    sa.Column('resource_type', sa.String(length=64), nullable=False),
    sa.Column('retain_days', sa.Integer(), nullable=False),
    sa.Column('archive_before_delete', sa.Boolean(), nullable=False),
    sa.Column('legal_hold', sa.Boolean(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('policy_version', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scope_type', 'scope_id', 'resource_type', 'policy_version', name='uq_retention_scope_resource_version')
    )
    op.create_table('system_configs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('config_key', sa.String(length=255), nullable=False),
    sa.Column('config_value_json', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=128), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('config_key', 'version', name='uq_system_config_key_version')
    )
    op.create_table('projects',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('phase', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('manager_id', sa.Uuid(), nullable=False),
    sa.Column('delivery_mode', sa.String(length=32), server_default=sa.text("'internal_only'"), nullable=False),
    sa.Column('lifecycle_status', sa.String(length=32), server_default=sa.text("'ACTIVE'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'code', name='uq_projects_company_code')
    )
    op.create_index(op.f('ix_projects_company_id'), 'projects', ['company_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=True),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=128), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=False),
    sa.Column('resource_id', sa.String(length=128), nullable=True),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.Column('details_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('document_category', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('visibility', sa.String(length=32), server_default=sa.text("'internal_only'"), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_company_id'), 'documents', ['company_id'], unique=False)
    op.create_table('idempotency_records',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('namespace', sa.String(length=64), nullable=False),
    sa.Column('request_id', sa.String(length=128), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=True),
    sa.Column('resource_id', sa.String(length=128), nullable=True),
    sa.Column('response_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('namespace', 'request_id', name='uq_idempotency_namespace_request')
    )
    op.create_table('project_knowledge_spaces',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('external_space_id', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'provider', name='uq_knowledge_space_project_provider')
    )
    op.create_table('project_memberships',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'user_id', 'valid_from', name='uq_memberships_project_user_from')
    )
    op.create_table('sandbox_projects',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('external_key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_key'),
    sa.UniqueConstraint('project_id', name='uq_sandbox_project_project')
    )
    op.create_table('threads',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('agent_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('thread_id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('model_alias', sa.String(length=128), nullable=True),
    sa.Column('prompt_version', sa.String(length=64), nullable=True),
    sa.Column('prompt_content_hash', sa.String(length=128), nullable=True),
    sa.Column('input_tokens', sa.BigInteger(), nullable=False),
    sa.Column('output_tokens', sa.BigInteger(), nullable=False),
    sa.Column('total_tokens', sa.BigInteger(), nullable=False),
    sa.Column('retrieval_rounds', sa.Integer(), nullable=False),
    sa.Column('ocr_pages', sa.Integer(), nullable=False),
    sa.Column('estimated_cost_microunits', sa.BigInteger(), nullable=False),
    sa.Column('cost_currency', sa.String(length=8), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['thread_id'], ['threads.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_runs_status'), 'agent_runs', ['status'], unique=False)
    op.create_table('document_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('version_label', sa.String(length=128), nullable=False),
    sa.Column('authority_level', sa.String(length=64), nullable=False),
    sa.Column('lifecycle_status', sa.String(length=32), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=True),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('supersedes_version_id', sa.Uuid(), nullable=True),
    sa.Column('source_uri', sa.Text(), nullable=True),
    sa.Column('content_hash', sa.String(length=128), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supersedes_version_id'], ['document_versions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'version_no', name='uq_document_versions_document_no')
    )
    op.create_index(op.f('ix_document_versions_lifecycle_status'), 'document_versions', ['lifecycle_status'], unique=False)
    op.create_table('sandbox_issues',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('sandbox_project_id', sa.Uuid(), nullable=False),
    sa.Column('issue_key', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('issue_type', sa.String(length=32), nullable=False),
    sa.Column('priority', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('module', sa.String(length=128), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('environment', sa.String(length=64), nullable=True),
    sa.Column('reporter_id', sa.Uuid(), nullable=False),
    sa.Column('assignee_id', sa.Uuid(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('client_request_id', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sandbox_project_id'], ['sandbox_projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'issue_key', name='uq_sandbox_issues_project_key')
    )
    op.create_index(op.f('ix_sandbox_issues_error_code'), 'sandbox_issues', ['error_code'], unique=False)
    op.create_index(op.f('ix_sandbox_issues_status'), 'sandbox_issues', ['status'], unique=False)
    op.create_table('agent_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('sequence_no', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('payload_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'sequence_no', name='uq_agent_events_run_sequence')
    )
    op.create_table('answers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('answer_text', sa.Text(), nullable=False),
    sa.Column('refusal_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', name='uq_answers_run')
    )
    op.create_table('document_acl_bindings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('document_version_id', sa.Uuid(), nullable=False),
    sa.Column('principal_type', sa.String(length=32), nullable=False),
    sa.Column('principal_id', sa.Uuid(), nullable=False),
    sa.Column('permission', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_version_id', 'principal_type', 'principal_id', 'permission', name='uq_document_acl_binding')
    )
    op.create_table('document_identifiers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('document_version_id', sa.Uuid(), nullable=False),
    sa.Column('identifier_type', sa.String(length=32), nullable=False),
    sa.Column('normalized_value', sa.Text(), nullable=False),
    sa.Column('raw_value', sa.Text(), nullable=False),
    sa.Column('page_no', sa.Integer(), nullable=True),
    sa.Column('section', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'identifier_type', 'normalized_value', 'document_version_id', name='uq_document_identifier_version')
    )
    op.create_index('idx_identifier_exact', 'document_identifiers', ['project_id', 'identifier_type', 'normalized_value'], unique=False)
    op.create_table('evidence_bundles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('query_text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_evidence_bundles_run_id'), 'evidence_bundles', ['run_id'], unique=False)
    op.create_table('ingestion_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('document_version_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('ragflow_task_id', sa.String(length=255), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('requested_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ingestion_jobs_status'), 'ingestion_jobs', ['status'], unique=False)
    op.create_table('issue_drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('issue_type', sa.String(length=32), nullable=False),
    sa.Column('proposed_priority', sa.String(length=32), nullable=False),
    sa.Column('module', sa.String(length=128), nullable=True),
    sa.Column('environment', sa.String(length=64), nullable=True),
    sa.Column('reproduction_steps_json', sa.JSON(), nullable=False),
    sa.Column('expected_behavior', sa.Text(), nullable=True),
    sa.Column('actual_behavior', sa.Text(), nullable=True),
    sa.Column('evidence_ids_json', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sandbox_issue_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('sandbox_issue_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('payload_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['sandbox_issue_id'], ['sandbox_issues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sandbox_issue_events_sandbox_issue_id'), 'sandbox_issue_events', ['sandbox_issue_id'], unique=False)
    op.create_table('tool_confirmations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('tool_name', sa.String(length=128), nullable=False),
    sa.Column('request_payload_hash', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('confirmed_by', sa.Uuid(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('evidence_snapshots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('bundle_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('document_version_id', sa.Uuid(), nullable=True),
    sa.Column('source_type', sa.String(length=32), nullable=False),
    sa.Column('source_ref', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('score', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['bundle_id'], ['evidence_bundles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_evidence_snapshots_bundle_id'), 'evidence_snapshots', ['bundle_id'], unique=False)
    op.create_table('ingestion_audits',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('ingestion_job_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('payload_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['ingestion_job_id'], ['ingestion_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ingestion_audits_ingestion_job_id'), 'ingestion_audits', ['ingestion_job_id'], unique=False)
    op.create_table('issue_candidates',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('issue_draft_id', sa.Uuid(), nullable=False),
    sa.Column('sandbox_issue_id', sa.Uuid(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('score', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('reasons_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['issue_draft_id'], ['issue_drafts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sandbox_issue_id'], ['sandbox_issues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('issue_draft_id', 'sandbox_issue_id', name='uq_issue_candidate_pair')
    )
    op.create_table('citations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('answer_id', sa.Uuid(), nullable=False),
    sa.Column('evidence_snapshot_id', sa.Uuid(), nullable=False),
    sa.Column('citation_no', sa.Integer(), nullable=False),
    sa.Column('quoted_text', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['answer_id'], ['answers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['evidence_snapshot_id'], ['evidence_snapshots.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('answer_id', 'citation_no', name='uq_citations_answer_no')
    )


def downgrade() -> None:
    op.drop_table('citations')
    op.drop_table('issue_candidates')
    op.drop_index(op.f('ix_ingestion_audits_ingestion_job_id'), table_name='ingestion_audits')
    op.drop_table('ingestion_audits')
    op.drop_index(op.f('ix_evidence_snapshots_bundle_id'), table_name='evidence_snapshots')
    op.drop_table('evidence_snapshots')
    op.drop_table('tool_confirmations')
    op.drop_index(op.f('ix_sandbox_issue_events_sandbox_issue_id'), table_name='sandbox_issue_events')
    op.drop_table('sandbox_issue_events')
    op.drop_table('issue_drafts')
    op.drop_index(op.f('ix_ingestion_jobs_status'), table_name='ingestion_jobs')
    op.drop_table('ingestion_jobs')
    op.drop_index(op.f('ix_evidence_bundles_run_id'), table_name='evidence_bundles')
    op.drop_table('evidence_bundles')
    op.drop_index('idx_identifier_exact', table_name='document_identifiers')
    op.drop_table('document_identifiers')
    op.drop_table('document_acl_bindings')
    op.drop_table('answers')
    op.drop_table('agent_events')
    op.drop_index(op.f('ix_sandbox_issues_status'), table_name='sandbox_issues')
    op.drop_index(op.f('ix_sandbox_issues_error_code'), table_name='sandbox_issues')
    op.drop_table('sandbox_issues')
    op.drop_index(op.f('ix_document_versions_lifecycle_status'), table_name='document_versions')
    op.drop_table('document_versions')
    op.drop_index(op.f('ix_agent_runs_status'), table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_table('threads')
    op.drop_table('sandbox_projects')
    op.drop_table('project_memberships')
    op.drop_table('project_knowledge_spaces')
    op.drop_table('idempotency_records')
    op.drop_index(op.f('ix_documents_company_id'), table_name='documents')
    op.drop_table('documents')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_projects_company_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_table('system_configs')
    op.drop_table('data_retention_policies')
    op.drop_index(op.f('ix_clients_company_id'), table_name='clients')
    op.drop_table('clients')
    op.drop_index(op.f('ix_background_jobs_status'), table_name='background_jobs')
    op.drop_table('background_jobs')
