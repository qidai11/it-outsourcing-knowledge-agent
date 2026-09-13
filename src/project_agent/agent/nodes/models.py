from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from project_agent.agent.nodes.resolve_identifiers import IdentifierResolution
from project_agent.domain.evidence import (
    ConflictDisclosure as ConflictDisclosure,
    GroundedAnswerClaim as GroundedAnswerClaim,
    GroundedAnswerDraft as GroundedAnswerDraft,
)


class RetrievalPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_query: str
    standalone_query: str
    exact_identifiers: tuple[str, ...]
    identifier_resolutions: tuple[IdentifierResolution, ...]
    constrained_document_version_ids: tuple[UUID, ...]
    constrained_provider_document_ids: tuple[str, ...] = ()
    allowed_categories: tuple[str, ...] = ()
    allow_second_round: bool = False


class QAModelAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer_text: str = Field(min_length=1)

