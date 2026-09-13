from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationService,
)
from project_agent.infrastructure.auth.jwt import JwtIdentityError
from project_agent.infrastructure.db.repositories.authorization import (
    SqlAlchemyProjectAuthorizationRepository,
)
from project_agent.runtime.api import ApiRuntime

_bearer = HTTPBearer(auto_error=False)


def get_api_runtime(request: Request) -> ApiRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, ApiRuntime):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API runtime is not configured",
        )
    return runtime


async def get_db_session(
    runtime: Annotated[ApiRuntime, Depends(get_api_runtime)],
) -> AsyncIterator[AsyncSession]:
    async with runtime.session_factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        else:
            await session.commit()


def _authentication_failed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing Bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_authenticated_identity(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_bearer),
    ],
    runtime: Annotated[ApiRuntime, Depends(get_api_runtime)],
) -> AuthenticatedIdentity:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _authentication_failed()
    try:
        return runtime.jwt_verifier.verify(credentials.credentials)
    except JwtIdentityError as exc:
        raise _authentication_failed() from exc


def get_authorization_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthorizationService:
    return AuthorizationService(SqlAlchemyProjectAuthorizationRepository(session))
