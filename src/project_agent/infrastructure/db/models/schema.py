from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from project_agent.domain.enums import (
    ClientStatus,
    DocumentLifecycleStatus,
    DocumentVisibility,
    ProjectDeliveryMode,
    ProjectLifecycleStatus,
)
from project_agent.infrastructure.db.base import Base


UUID_PK = Uuid(as_uuid=True)
UUID_FK = Uuid(as_uuid=True)
TIMESTAMP = DateTime(timezone=True)


class ClientModel(Base):
    __tablename__ = "clients"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ClientStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class ProjectModel(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_projects_company_code"),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False, index=True)
    client_id: Mapped[UUID] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phase: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    manager_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    delivery_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProjectDeliveryMode.INTERNAL_ONLY.value,
        server_default=text("'internal_only'"),
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProjectLifecycleStatus.ACTIVE.value,
        server_default=text("'ACTIVE'"),
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class ProjectMembershipModel(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", "valid_from", name="uq_memberships_project_user_from"
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class ProjectKnowledgeSpaceModel(Base):
    __tablename__ = "project_knowledge_spaces"
    __table_args__ = (
        UniqueConstraint("project_id", "provider", name="uq_knowledge_space_project_provider"),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="ragflow")
    external_space_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DocumentVisibility.INTERNAL_ONLY.value,
        server_default=text("'internal_only'"),
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(UUID_FK)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class DocumentVersionModel(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_document_versions_document_no"),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    version_label: Mapped[str] = mapped_column(String(128), nullable=False)
    authority_level: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DocumentLifecycleStatus.DRAFT.value, index=True
    )
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    supersedes_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    source_uri: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_by: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class DocumentAclBindingModel(Base):
    __tablename__ = "document_acl_bindings"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "principal_type", "principal_id", "permission",
            name="uq_document_acl_binding",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    permission: Mapped[str] = mapped_column(String(32), nullable=False, default="read")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class DocumentIdentifierModel(Base):
    __tablename__ = "document_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "identifier_type",
            "normalized_value",
            "document_version_id",
            name="uq_document_identifier_version",
        ),
        Index(
            "idx_identifier_exact",
            "project_id",
            "identifier_type",
            "normalized_value",
        ),
        Index(
            "idx_identifier_trgm",
            "normalized_value",
            postgresql_using="gin",
            postgresql_ops={"normalized_value": "gin_trgm_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    identifier_type: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class IngestionJobModel(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ragflow_task_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)


class IngestionAuditModel(Base):
    __tablename__ = "ingestion_audits"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    ingestion_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class BackgroundJobModel(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index(
            "idx_background_jobs_claim",
            "status",
            "available_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "idx_background_jobs_reaper",
            "status",
            "lease_expires_at",
            postgresql_where=text("status = 'RUNNING'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    heartbeat_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class ThreadModel(Base):
    __tablename__ = "threads"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class AgentRunModel(Base):
    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RUNNING", index=True)
    model_alias: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    prompt_content_hash: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    retrieval_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ocr_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_microunits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)


class AgentEventModel(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence_no", name="uq_agent_events_run_sequence"),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class EvidenceBundleModel(Base):
    __tablename__ = "evidence_bundles"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class EvidenceSnapshotModel(Base):
    __tablename__ = "evidence_snapshots"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    bundle_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_bundles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class AnswerModel(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("run_id", name="uq_answers_run"),)

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class CitationModel(Base):
    __tablename__ = "citations"
    __table_args__ = (
        UniqueConstraint("answer_id", "citation_no", name="uq_citations_answer_no"),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    answer_id: Mapped[UUID] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"), nullable=False)
    evidence_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    citation_no: Mapped[int] = mapped_column(Integer, nullable=False)
    quoted_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class IssueDraftModel(Base):
    __tablename__ = "issue_drafts"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_priority: Mapped[str] = mapped_column(String(32), nullable=False)
    module: Mapped[str | None] = mapped_column(String(128))
    environment: Mapped[str | None] = mapped_column(String(64))
    reproduction_steps_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expected_behavior: Mapped[str | None] = mapped_column(Text)
    actual_behavior: Mapped[str | None] = mapped_column(Text)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class SandboxProjectModel(Base):
    __tablename__ = "sandbox_projects"
    __table_args__ = (UniqueConstraint("project_id", name="uq_sandbox_project_project"),)

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    external_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class SandboxIssueModel(Base):
    __tablename__ = "sandbox_issues"
    __table_args__ = (
        UniqueConstraint("project_id", "issue_key", name="uq_sandbox_issues_project_key"),
        Index(
            "uq_sandbox_issues_project_request",
            "project_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    sandbox_project_id: Mapped[UUID] = mapped_column(
        ForeignKey("sandbox_projects.id", ondelete="CASCADE"), nullable=False
    )
    issue_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)
    module: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64), index=True)
    environment: Mapped[str | None] = mapped_column(String(64))
    reporter_id: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    assignee_id: Mapped[UUID | None] = mapped_column(UUID_FK)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="sandbox")
    client_request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class IssueCandidateModel(Base):
    __tablename__ = "issue_candidates"
    __table_args__ = (
        UniqueConstraint("issue_draft_id", "sandbox_issue_id", name="uq_issue_candidate_pair"),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    issue_draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("issue_drafts.id", ondelete="CASCADE"), nullable=False
    )
    sandbox_issue_id: Mapped[UUID] = mapped_column(
        ForeignKey("sandbox_issues.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class SandboxIssueEventModel(Base):
    __tablename__ = "sandbox_issue_events"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    sandbox_issue_id: Mapped[UUID] = mapped_column(
        ForeignKey("sandbox_issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(UUID_FK)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class ToolConfirmationModel(Base):
    __tablename__ = "tool_confirmations"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    request_payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    confirmed_by: Mapped[UUID | None] = mapped_column(UUID_FK)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("namespace", "request_id", name="uq_idempotency_namespace_request"),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="IN_PROGRESS")
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    company_id: Mapped[UUID | None] = mapped_column(UUID_FK)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    user_id: Mapped[UUID | None] = mapped_column(UUID_FK)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class SystemConfigModel(Base):
    __tablename__ = "system_configs"
    __table_args__ = (
        UniqueConstraint("config_key", "version", name="uq_system_config_key_version"),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    config_key: Mapped[str] = mapped_column(String(255), nullable=False)
    config_value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    updated_by: Mapped[UUID] = mapped_column(UUID_FK, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())


class DataRetentionPolicyModel(Base):
    __tablename__ = "data_retention_policies"
    __table_args__ = (
        UniqueConstraint(
            "scope_type", "scope_id", "resource_type", "policy_version",
            name="uq_retention_scope_resource_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_PK, primary_key=True, default=uuid4)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(UUID_FK)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    retain_days: Mapped[int] = mapped_column(Integer, nullable=False)
    archive_before_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
