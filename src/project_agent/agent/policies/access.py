from __future__ import annotations

from project_agent.application.ports.knowledge import KnowledgeChunk, KnowledgeRetrievalRequest
from project_agent.application.services.authorization import (
    AuthorizationDenied,
    AuthorizedProjectContext,
)


class ProjectAccessPolicy:
    """Applies pre-retrieval least-privilege constraints and post-filters Evidence."""

    def constrain_retrieval(
        self,
        request: KnowledgeRetrievalRequest,
        context: AuthorizedProjectContext,
    ) -> KnowledgeRetrievalRequest | None:
        if request.project_id != context.project_code:
            raise AuthorizationDenied("retrieval project does not match authorized project")

        allowed_versions = {str(value) for value in context.scope.allowed_document_version_ids or ()}
        allowed_spaces = set(context.knowledge_space_ids)
        if not allowed_versions or not allowed_spaces:
            return None

        if request.document_version_ids:
            requested_versions = set(request.document_version_ids)
            versions = tuple(sorted(allowed_versions & requested_versions))
        else:
            versions = tuple(sorted(allowed_versions))
        if request.knowledge_space_ids:
            requested_spaces = set(request.knowledge_space_ids)
            spaces = tuple(sorted(allowed_spaces & requested_spaces))
        else:
            spaces = tuple(sorted(allowed_spaces))
        if not versions or not spaces:
            return None

        return KnowledgeRetrievalRequest(
            project_id=context.project_code,
            query=request.query,
            limit=request.limit,
            document_version_ids=versions,
            knowledge_space_ids=spaces,
        )

    def postfilter_evidence(
        self,
        chunks: list[KnowledgeChunk],
        context: AuthorizedProjectContext,
    ) -> list[KnowledgeChunk]:
        allowed_versions = {str(value) for value in context.scope.allowed_document_version_ids or ()}
        allowed_spaces = set(context.knowledge_space_ids)
        if not allowed_versions or not allowed_spaces:
            return []
        return [
            chunk
            for chunk in chunks
            if chunk.project_id == context.project_code
            and chunk.document_version_id in allowed_versions
            and chunk.knowledge_space_id is not None
            and chunk.knowledge_space_id in allowed_spaces
        ]
