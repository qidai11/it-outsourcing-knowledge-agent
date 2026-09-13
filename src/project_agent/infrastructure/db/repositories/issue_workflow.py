from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_agent.domain.issues import (
    IdempotencyRecord,
    IdempotencyStatus,
    IssueCandidateLink,
    IssueDraft,
    IssueDraftCreate,
    IssueDraftStatus,
    ToolConfirmationReceipt,
    ToolConfirmationStatus,
)
from project_agent.infrastructure.db.models.schema import (
    IdempotencyRecordModel,
    IssueCandidateModel,
    IssueDraftModel,
    SandboxIssueModel,
    ToolConfirmationModel,
)


class SqlAlchemyIssueWorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_draft(self, command: IssueDraftCreate) -> IssueDraft:
        model = IssueDraftModel(
            run_id=command.run_id,
            project_id=command.project_id,
            created_by=command.created_by,
            title=command.title,
            description=command.description,
            issue_type=command.issue_type,
            proposed_priority=command.proposed_priority,
            module=command.module,
            environment=command.environment,
            reproduction_steps_json=list(command.reproduction_steps),
            expected_behavior=command.expected_behavior,
            actual_behavior=command.actual_behavior,
            evidence_ids_json=list(command.evidence_ids),
            status=command.status.value,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_draft(model)

    async def get_draft(self, draft_id: UUID) -> IssueDraft:
        model = await self._session.get(IssueDraftModel, draft_id)
        if model is None:
            raise LookupError(f"issue draft does not exist: {draft_id}")
        return self._to_draft(model)

    async def set_draft_status(self, draft_id: UUID, status: IssueDraftStatus) -> IssueDraft:
        model = await self._session.get(IssueDraftModel, draft_id, with_for_update=True)
        if model is None:
            raise LookupError(f"issue draft does not exist: {draft_id}")
        model.status = status.value
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._to_draft(model)

    async def save_candidate_links(
        self, draft_id: UUID, links: tuple[IssueCandidateLink, ...]
    ) -> None:
        if not links:
            return
        draft = await self._session.get(IssueDraftModel, draft_id)
        if draft is None:
            raise LookupError(f"issue draft does not exist: {draft_id}")
        keys = tuple(dict.fromkeys(item.issue_key for item in links))
        rows = (
            await self._session.scalars(
                select(SandboxIssueModel).where(
                    SandboxIssueModel.project_id == draft.project_id,
                    SandboxIssueModel.issue_key.in_(keys),
                )
            )
        ).all()
        by_key = {row.issue_key: row for row in rows}
        for link in links:
            issue = by_key.get(link.issue_key)
            if issue is None:
                continue
            stmt = pg_insert(IssueCandidateModel).values(
                issue_draft_id=draft_id,
                sandbox_issue_id=issue.id,
                rank=link.rank,
                score=Decimal(str(link.score)) if link.score is not None else None,
                reasons_json=list(link.reasons),
            ).on_conflict_do_nothing(
                index_elements=[
                    IssueCandidateModel.issue_draft_id,
                    IssueCandidateModel.sandbox_issue_id,
                ]
            )
            await self._session.execute(stmt)
        await self._session.flush()

    async def list_candidate_links(self, draft_id: UUID) -> tuple[IssueCandidateLink, ...]:
        stmt = (
            select(IssueCandidateModel, SandboxIssueModel.issue_key)
            .join(SandboxIssueModel, SandboxIssueModel.id == IssueCandidateModel.sandbox_issue_id)
            .where(IssueCandidateModel.issue_draft_id == draft_id)
            .order_by(IssueCandidateModel.rank.asc(), SandboxIssueModel.issue_key.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return tuple(
            IssueCandidateLink(
                issue_key=issue_key,
                rank=model.rank,
                score=float(model.score) if model.score is not None else None,
                reasons=tuple(model.reasons_json),
            )
            for model, issue_key in rows
        )

    async def save_confirmation(
        self, receipt: ToolConfirmationReceipt
    ) -> ToolConfirmationReceipt:
        existing = (
            await self._session.scalars(
                select(ToolConfirmationModel)
                .where(
                    ToolConfirmationModel.run_id == receipt.run_id,
                    ToolConfirmationModel.tool_name == receipt.tool_name,
                    ToolConfirmationModel.request_payload_hash == receipt.request_payload_hash,
                    ToolConfirmationModel.status == receipt.status.value,
                    ToolConfirmationModel.confirmed_by == receipt.confirmed_by,
                )
                .order_by(ToolConfirmationModel.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if existing is not None:
            return self._to_confirmation(existing)
        model = ToolConfirmationModel(
            id=receipt.id,
            run_id=receipt.run_id,
            tool_name=receipt.tool_name,
            request_payload_hash=receipt.request_payload_hash,
            status=receipt.status.value,
            confirmed_by=receipt.confirmed_by,
            confirmed_at=receipt.confirmed_at,
            expires_at=receipt.expires_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_confirmation(model)

    async def get_confirmation(self, confirmation_id: UUID) -> ToolConfirmationReceipt:
        model = await self._session.get(ToolConfirmationModel, confirmation_id)
        if model is None:
            raise LookupError(f"tool confirmation does not exist: {confirmation_id}")
        return self._to_confirmation(model)

    @staticmethod
    def _to_draft(model: IssueDraftModel) -> IssueDraft:
        return IssueDraft(
            id=model.id,
            run_id=model.run_id,
            project_id=model.project_id,
            created_by=model.created_by,
            title=model.title,
            description=model.description,
            issue_type=model.issue_type,
            proposed_priority=model.proposed_priority,
            module=model.module,
            environment=model.environment,
            reproduction_steps=tuple(model.reproduction_steps_json),
            expected_behavior=model.expected_behavior,
            actual_behavior=model.actual_behavior,
            evidence_ids=tuple(model.evidence_ids_json),
            status=IssueDraftStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _to_confirmation(model: ToolConfirmationModel) -> ToolConfirmationReceipt:
        if model.confirmed_by is None or model.confirmed_at is None or model.expires_at is None:
            raise ValueError("persisted tool confirmation is incomplete")
        return ToolConfirmationReceipt(
            id=model.id,
            run_id=model.run_id,
            tool_name=model.tool_name,
            request_payload_hash=model.request_payload_hash,
            status=ToolConfirmationStatus(model.status),
            confirmed_by=model.confirmed_by,
            confirmed_at=model.confirmed_at,
            expires_at=model.expires_at,
        )


class PostgresIdempotencyStore:
    """Durable idempotency barrier using a dedicated transaction per operation.

    ``reserve`` commits IN_PROGRESS before any external side effect. A response-loss
    retry can therefore reconcile by the same request_id without issuing a blind
    duplicate write.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reserve(
        self, *, namespace: str, request_id: str, project_id: UUID
    ) -> tuple[IdempotencyRecord, bool]:
        async with self._session_factory() as session:
            stmt = (
                pg_insert(IdempotencyRecordModel)
                .values(
                    namespace=namespace,
                    request_id=request_id,
                    project_id=project_id,
                    status=IdempotencyStatus.IN_PROGRESS.value,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        IdempotencyRecordModel.namespace,
                        IdempotencyRecordModel.request_id,
                    ]
                )
                .returning(IdempotencyRecordModel.id)
            )
            inserted_id = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            created = inserted_id is not None
        record = await self.get(namespace=namespace, request_id=request_id)
        if record is None:
            raise RuntimeError("idempotency reservation disappeared after commit")
        if record.project_id != project_id:
            raise ValueError("idempotency key is already bound to another project")
        return record, created

    async def get(
        self, *, namespace: str, request_id: str
    ) -> IdempotencyRecord | None:
        async with self._session_factory() as session:
            model = (
                await session.scalars(
                    select(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.namespace == namespace,
                        IdempotencyRecordModel.request_id == request_id,
                    )
                )
            ).one_or_none()
            return self._to_record(model) if model is not None else None

    async def complete(
        self,
        *,
        namespace: str,
        request_id: str,
        resource_type: str,
        resource_id: str,
        response: dict[str, object],
    ) -> IdempotencyRecord:
        async with self._session_factory() as session:
            model = (
                await session.scalars(
                    select(IdempotencyRecordModel)
                    .where(
                        IdempotencyRecordModel.namespace == namespace,
                        IdempotencyRecordModel.request_id == request_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if model is None:
                raise LookupError("idempotency reservation is required before completion")
            model.status = IdempotencyStatus.COMPLETED.value
            model.resource_type = resource_type
            model.resource_id = resource_id
            model.response_json = response
            model.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(model)
            return self._to_record(model)

    @staticmethod
    def _to_record(model: IdempotencyRecordModel) -> IdempotencyRecord:
        if model.project_id is None:
            raise ValueError("issue idempotency record must be project scoped")
        return IdempotencyRecord(
            id=model.id,
            namespace=model.namespace,
            request_id=model.request_id,
            project_id=model.project_id,
            status=IdempotencyStatus(model.status),
            resource_type=model.resource_type,
            resource_id=model.resource_id,
            response=dict(model.response_json) if model.response_json else None,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
