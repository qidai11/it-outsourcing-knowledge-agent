from __future__ import annotations

from uuid import UUID

from project_agent.application.services.authorization import AuthorizedProjectContext
from project_agent.domain.access import ProjectAccessScope


def serialize_authorized_context(context: AuthorizedProjectContext) -> dict[str, object]:
    return {
        "project_code": context.project_code,
        "knowledge_space_ids": list(context.knowledge_space_ids),
        "scope": context.scope.model_dump(mode="json"),
    }


def deserialize_authorized_context(payload: dict[str, object]) -> AuthorizedProjectContext:
    raw_scope = payload.get("scope")
    if not isinstance(raw_scope, dict):
        raise ValueError("access scope artifact is missing scope")
    project_code = payload.get("project_code")
    spaces = payload.get("knowledge_space_ids")
    if not isinstance(project_code, str) or not isinstance(spaces, list):
        raise ValueError("access scope artifact is malformed")
    return AuthorizedProjectContext(
        scope=ProjectAccessScope.model_validate(raw_scope),
        project_code=project_code,
        knowledge_space_ids=tuple(str(value) for value in spaces),
    )


def uuid_tuple(values: object) -> tuple[UUID, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(UUID(str(value)) for value in values)
