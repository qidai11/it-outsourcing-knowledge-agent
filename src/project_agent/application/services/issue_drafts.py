from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from project_agent.application.ports.issue_workflow import IssueWorkflowRepository
from project_agent.application.ports.project_tracker import CreateIssueRequest
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.application.services.issue_candidates import IssueCandidateResult
from project_agent.domain.enums import IssuePriority, IssueType
from project_agent.domain.identifiers import IdentifierType
from project_agent.domain.issues import IssueCandidateLink, IssueDraft, IssueDraftCreate

_MODULE_LABEL = re.compile(r"(?:模块|module)\s*[:：=]\s*([A-Za-z0-9_.-]+)", re.IGNORECASE)


class IssueDraftService:
    def __init__(
        self,
        repository: IssueWorkflowRepository,
        *,
        extractor: IdentifierExtractor | None = None,
    ) -> None:
        self._repository = repository
        self._extractor = extractor or IdentifierExtractor()

    async def create_from_text(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        created_by: UUID,
        text: str,
        candidates: IssueCandidateResult | None = None,
    ) -> IssueDraft:
        clean = text.strip()
        if not clean:
            raise ValueError("issue text cannot be blank")
        identifiers = self._extractor.extract(clean)
        has_error_code = any(
            item.identifier_type is IdentifierType.ERROR_CODE for item in identifiers
        )
        module_match = _MODULE_LABEL.search(clean)
        module = module_match.group(1) if module_match else None
        title = next((line.strip() for line in clean.splitlines() if line.strip()), clean)
        title = title[:512]
        draft = await self._repository.create_draft(
            IssueDraftCreate(
                run_id=run_id,
                project_id=project_id,
                created_by=created_by,
                title=title,
                description=clean,
                issue_type=IssueType.BUG.value if has_error_code else IssueType.TASK.value,
                proposed_priority=IssuePriority.MEDIUM.value,
                module=module,
            )
        )
        if candidates is not None:
            links = tuple(
                IssueCandidateLink(
                    issue_key=item.issue_key,
                    rank=rank,
                    score=item.semantic_score,
                    reasons=item.reasons,
                )
                for rank, item in enumerate(candidates.possible_duplicates, start=1)
                if item.project_id == str(project_id)
            )
            if links:
                await self._repository.save_candidate_links(draft.id, links)
        return draft

    def build_create_request(self, draft: IssueDraft) -> CreateIssueRequest:
        error_code = next(
            (
                item.normalized_value
                for item in self._extractor.extract(draft.description)
                if item.identifier_type is IdentifierType.ERROR_CODE
            ),
            None,
        )
        details: list[str] = [draft.description]
        if draft.reproduction_steps:
            details.append(
                "\nReproduction steps:\n"
                + "\n".join(f"- {x}" for x in draft.reproduction_steps)
            )
        if draft.expected_behavior:
            details.append(f"\nExpected behavior:\n{draft.expected_behavior}")
        if draft.actual_behavior:
            details.append(f"\nActual behavior:\n{draft.actual_behavior}")
        return CreateIssueRequest(
            project_id=str(draft.project_id),
            request_id=str(draft.id),
            title=draft.title,
            description="".join(details),
            issue_type=draft.issue_type,
            priority=draft.proposed_priority,
            reporter_id=str(draft.created_by),
            module=draft.module,
            error_code=error_code,
            environment=draft.environment,
        )

    @staticmethod
    def payload_hash(request: CreateIssueRequest) -> str:
        payload = {
            "project_id": request.project_id,
            "request_id": request.request_id,
            "title": request.title,
            "description": request.description,
            "issue_type": request.issue_type,
            "priority": request.priority,
            "reporter_id": request.reporter_id,
            "module": request.module,
            "error_code": request.error_code,
            "environment": request.environment,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
