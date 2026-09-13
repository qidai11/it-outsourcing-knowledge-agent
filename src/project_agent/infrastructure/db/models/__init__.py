"""SQLAlchemy persistence models.

Importing this module registers all tables in ``Base.metadata``.
"""

from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    AnswerModel,
    AuditLogModel,
    BackgroundJobModel,
    CitationModel,
    ClientModel,
    DataRetentionPolicyModel,
    DocumentAclBindingModel,
    DocumentIdentifierModel,
    DocumentModel,
    DocumentVersionModel,
    EvidenceBundleModel,
    EvidenceSnapshotModel,
    IdempotencyRecordModel,
    IngestionAuditModel,
    IngestionJobModel,
    IssueCandidateModel,
    IssueDraftModel,
    ProjectKnowledgeSpaceModel,
    ProjectMembershipModel,
    ProjectModel,
    SandboxIssueEventModel,
    SandboxIssueModel,
    SandboxProjectModel,
    SystemConfigModel,
    ThreadModel,
    ToolConfirmationModel,
)

__all__ = [name for name in globals() if name.endswith("Model")]
