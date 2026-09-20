from __future__ import annotations

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from project_agent.agent.nodes.resolve_identifiers import IdentifierResolution
from project_agent.domain.evidence import ConflictDisclosure as ConflictDisclosure
from project_agent.domain.evidence import GroundedAnswerClaim as GroundedAnswerClaim
from project_agent.domain.evidence import GroundedAnswerDraft as GroundedAnswerDraft


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


class RetrievalGradeReason(StrEnum):
    ADEQUATE = "ADEQUATE"
    EMPTY_EVIDENCE = "EMPTY_EVIDENCE"
    INSUFFICIENT_RELEVANCE = "INSUFFICIENT_RELEVANCE"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"


class RetrievalGrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    adequate: bool
    reason: RetrievalGradeReason
    second_round_justified: bool = False
    refined_query: str | None = None

    @model_validator(mode="after")
    def validate_consistent_shape(self) -> Self:
        refined = self.refined_query.strip() if isinstance(self.refined_query, str) else None
        if self.adequate:
            if (
                self.reason is not RetrievalGradeReason.ADEQUATE
                or self.second_round_justified
                or refined is not None
            ):
                raise ValueError("adequate retrieval grade cannot request refinement")
            return self
        if self.reason is RetrievalGradeReason.ADEQUATE:
            raise ValueError("inadequate retrieval grade requires an inadequate reason")
        if self.second_round_justified and not refined:
            raise ValueError("justified second retrieval requires a refined query")
        if not self.second_round_justified and refined is not None:
            raise ValueError("refined query requires justified second retrieval")
        return self


class QAModelAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer_text: str = Field(min_length=1)

