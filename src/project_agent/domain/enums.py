from __future__ import annotations

from enum import StrEnum


class ClientStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ProjectRole(StrEnum):
    PROJECT_MANAGER = "project_manager"
    DEVELOPER = "developer"
    QA = "qa"
    IMPLEMENTATION = "implementation"
    SUPPORT = "support"
    VIEWER = "viewer"


class ProjectDeliveryMode(StrEnum):
    INTERNAL_ONLY = "internal_only"
    CUSTOMER_READONLY = "customer_readonly"


class ProjectLifecycleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"
    DELETION_PENDING = "DELETION_PENDING"
    DELETED = "DELETED"


class DocumentVisibility(StrEnum):
    INTERNAL_ONLY = "internal_only"
    CUSTOMER_VISIBLE = "customer_visible"
    RESTRICTED = "restricted"


class DocumentLifecycleStatus(StrEnum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"

    @property
    def is_online_retrievable(self) -> bool:
        return self is DocumentLifecycleStatus.PUBLISHED


class IssueType(StrEnum):
    BUG = "bug"
    TASK = "task"
    SUPPORT = "support"


class IssuePriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class DocumentCategory(StrEnum):
    REQUIREMENT_BASELINE = "requirement_baseline"
    APPROVED_DESIGN = "approved_design"
    API_SPECIFICATION = "api_specification"
    DATABASE_DESIGN = "database_design"
    APPROVED_TEST_SPEC = "approved_test_spec"
    RELEASE_RUNBOOK = "release_runbook"
    APPROVED_MEETING_MINUTES = "approved_meeting_minutes"
    ISSUE_RECORD = "issue_record"


class AuthorityLevel(StrEnum):
    SIGNED_SCOPE = "signed_scope"
    APPROVED_CHANGE = "approved_change"
    REQUIREMENT_BASELINE = "requirement_baseline"
    APPROVED_MEETING_MINUTES = "approved_meeting_minutes"
    APPROVED_DESIGN = "approved_design"
    APPROVED_TEST_SPEC = "approved_test_spec"
    RELEASE_RUNBOOK = "release_runbook"
    ISSUE_RECORD = "issue_record"
    INFORMAL_NOTE = "informal_note"
