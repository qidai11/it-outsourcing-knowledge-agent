from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Select, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.application.ports.project_tracker import (
    CreatedIssue,
    CreateIssueRequest,
    ProjectIssue,
    SearchIssuesRequest,
)
from project_agent.infrastructure.db.models.schema import (
    SandboxIssueEventModel,
    SandboxIssueModel,
    SandboxProjectModel,
)


class SandboxProjectTrackerAdapter:
    """PostgreSQL-backed V1 project tracker sandbox.

    Search is always scoped by ``project_id``. Write methods implement the
    ProjectTrackerPort contract but Task 12 nodes never call them; Task 13 adds
    confirmation and durable idempotency before writes are reachable by users.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _project_uuid(project_id: str) -> UUID:
        try:
            return UUID(project_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("project_id must be a UUID string") from exc

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @classmethod
    def build_search_statement(
        cls, request: SearchIssuesRequest
    ) -> Select[tuple[SandboxIssueModel]]:
        if request.limit < 1 or request.limit > 100:
            raise ValueError("limit must be between 1 and 100")
        project_id = cls._project_uuid(request.project_id)
        stmt = select(SandboxIssueModel).where(SandboxIssueModel.project_id == project_id)
        if request.error_code is not None:
            stmt = stmt.where(SandboxIssueModel.error_code == request.error_code.strip().upper())
        if request.module is not None:
            stmt = stmt.where(SandboxIssueModel.module == request.module.strip())
        if request.statuses:
            statuses = tuple(dict.fromkeys(status.strip().upper() for status in request.statuses))
            stmt = stmt.where(SandboxIssueModel.status.in_(statuses))
        if request.query and request.query.strip():
            pattern = f"%{cls._escape_like(request.query.strip())}%"
            stmt = stmt.where(
                or_(
                    SandboxIssueModel.title.ilike(pattern, escape="\\"),
                    SandboxIssueModel.description.ilike(pattern, escape="\\"),
                )
            )
        return stmt.order_by(
            SandboxIssueModel.created_at.desc(),
            SandboxIssueModel.issue_key.asc(),
        ).limit(request.limit)

    async def search_issues(self, request: SearchIssuesRequest) -> list[ProjectIssue]:
        rows = (await self._session.scalars(self.build_search_statement(request))).all()
        return [self.to_project_issue(row) for row in rows]

    async def create_issue(self, request: CreateIssueRequest) -> CreatedIssue:
        """Create a sandbox issue with provider-side request-id uniqueness.

        Task 13 also uses the application ``idempotency_records`` barrier. This
        unique provider key is a second line of defense for retries and concurrent
        writes that reach the adapter.
        """

        existing = await self.get_issue_by_request_id(request.project_id, request.request_id)
        if existing is not None:
            return existing

        project_id = self._project_uuid(request.project_id)
        sandbox_project = (
            await self._session.scalars(
                select(SandboxProjectModel).where(
                    SandboxProjectModel.project_id == project_id,
                    SandboxProjectModel.status == "active",
                )
            )
        ).one_or_none()
        if sandbox_project is None:
            raise LookupError("active sandbox project is required")

        model_id = uuid4()
        numeric_suffix = f"{model_id.int % 1_000_000:06d}"
        issue_key = f"{sandbox_project.external_key}-{numeric_suffix}"
        stmt = (
            pg_insert(SandboxIssueModel)
            .values(
                id=model_id,
                project_id=project_id,
                sandbox_project_id=sandbox_project.id,
                issue_key=issue_key,
                title=request.title,
                description=request.description,
                issue_type=request.issue_type,
                priority=request.priority,
                status="OPEN",
                module=request.module,
                error_code=request.error_code.upper() if request.error_code else None,
                environment=request.environment,
                reporter_id=UUID(request.reporter_id),
                source="sandbox",
                client_request_id=request.request_id,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    SandboxIssueModel.project_id,
                    SandboxIssueModel.client_request_id,
                ],
                index_where=SandboxIssueModel.client_request_id.is_not(None),
            )
            .returning(SandboxIssueModel.id, SandboxIssueModel.issue_key, SandboxIssueModel.status)
        )
        inserted = (await self._session.execute(stmt)).one_or_none()
        if inserted is None:
            existing = await self.get_issue_by_request_id(request.project_id, request.request_id)
            if existing is None:
                raise RuntimeError("sandbox issue request id conflict could not be reconciled")
            return existing
        issue_id, inserted_key, inserted_status = inserted
        self._session.add(
            SandboxIssueEventModel(
                sandbox_issue_id=issue_id,
                event_type="CREATED",
                actor_id=UUID(request.reporter_id),
                payload_json={"client_request_id": request.request_id},
            )
        )
        await self._session.flush()
        return CreatedIssue(
            project_id=request.project_id,
            request_id=request.request_id,
            issue_key=inserted_key,
            status=inserted_status,
        )

    async def get_issue_by_request_id(
        self,
        project_id: str,
        request_id: str,
    ) -> CreatedIssue | None:
        project_uuid = self._project_uuid(project_id)
        stmt = (
            select(SandboxIssueModel)
            .where(
                SandboxIssueModel.project_id == project_uuid,
                SandboxIssueModel.client_request_id == request_id,
            )
            .order_by(SandboxIssueModel.created_at.asc(), SandboxIssueModel.id.asc())
            .limit(1)
        )
        model = (await self._session.scalars(stmt)).one_or_none()
        if model is None:
            return None
        return CreatedIssue(
            project_id=str(model.project_id),
            request_id=request_id,
            issue_key=model.issue_key,
            status=model.status,
        )

    @staticmethod
    def to_project_issue(model: SandboxIssueModel) -> ProjectIssue:
        return ProjectIssue(
            project_id=str(model.project_id),
            issue_key=model.issue_key,
            title=model.title,
            description=model.description,
            status=model.status,
            issue_type=model.issue_type,
            priority=model.priority,
            module=model.module,
            error_code=model.error_code,
            environment=model.environment,
            created_at=model.created_at,
        )
