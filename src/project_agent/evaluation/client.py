"""Bounded, identity-only HTTP transport for WS8's existing production Run API.

Never log raw HTTP responses or Authorization headers. Authz is always resolved
server-side from memberships, not inferred from a client-side fixture role.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from project_agent.evaluation.auth import mint_fixture_identity_jwt

_TERMINAL = frozenset({"SUCCEEDED", "REFUSED", "CANCELLED", "FAILED"})


class EvaluationTimeout(TimeoutError):
    """A bounded HTTP request or Run poll exceeded its configured deadline."""


class EvaluationHttpError(RuntimeError):
    """Transport/HTTP failure without exposing a potentially sensitive body."""

    def __init__(self, status: int | None = None) -> None:
        self.status = status
        super().__init__(f"evaluation HTTP operation failed (status={status})")


@dataclass(frozen=True, slots=True)
class HttpRunResult:
    http_status: int
    run_id: UUID | None
    thread_id: UUID | None
    status: str | None


class EvaluationClient:
    """Only POST runs, GET runs, POST resume; optional events via API later."""

    def __init__(
        self,
        *,
        api_base_url: str,
        fixture_state: Mapping[str, Any],
        jwt_secret: str,
        jwt_issuer: str = "project-agent",
        jwt_audience: str = "project-agent-api",
        http_timeout_seconds: float = 10.0,
        run_timeout_seconds: float = 120.0,
        waiting_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if (
            http_timeout_seconds <= 0
            or run_timeout_seconds <= 0
            or waiting_timeout_seconds <= 0
            or poll_interval_seconds <= 0
        ):
            raise ValueError("evaluation timeouts/poll interval must be positive")
        if not api_base_url.startswith(("http://", "https://")):
            raise ValueError("api_base_url must be HTTP(S)")
        self._state = fixture_state
        self._secret = jwt_secret
        self._issuer = jwt_issuer
        self._audience = jwt_audience
        self._http_timeout = http_timeout_seconds
        self._run_timeout = run_timeout_seconds
        self._waiting_timeout = waiting_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._http = httpx.AsyncClient(
            base_url=api_base_url.rstrip("/"),
            timeout=httpx.Timeout(http_timeout_seconds),
            transport=transport,
            follow_redirects=False,
        )

    async def __aenter__(self) -> EvaluationClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    def _headers(self, user_alias: str) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + mint_fixture_identity_jwt(
                state=self._state,
                user_alias=user_alias,
                secret=self._secret,
                issuer=self._issuer,
                audience=self._audience,
            ),
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        user_alias: str,
        payload: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            return await asyncio.wait_for(
                self._http.request(
                    method, path, headers=self._headers(user_alias), json=payload,
                ),
                timeout=self._http_timeout,
            )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise EvaluationTimeout("evaluation HTTP request deadline reached") from exc
        except httpx.RequestError as exc:
            raise EvaluationHttpError() from exc

    @staticmethod
    def _result(response: httpx.Response) -> HttpRunResult:
        if response.status_code >= 400:
            return HttpRunResult(response.status_code, None, None, None)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("not an object")
            run_id = UUID(str(data["run_id"]))
            thread_id = UUID(str(data["thread_id"]))
            status = str(data["status"])
        except (ValueError, TypeError, KeyError) as exc:
            raise EvaluationHttpError(response.status_code) from exc
        return HttpRunResult(response.status_code, run_id, thread_id, status)

    async def create_run(
        self,
        *,
        user_alias: str,
        project_id: UUID,
        business_mode: str,
        query: str,
        thread_id: UUID | None = None,
        overrides: Mapping[str, Any] | None = None,
        allow_denial: bool = False,
    ) -> HttpRunResult:
        if business_mode not in {"qa", "issue_lookup", "issue_create"}:
            raise ValueError("unknown production business mode")
        if not query:
            raise ValueError("frozen question must not be blank")
        payload: dict[str, Any] = {
            "project_id": str(project_id), "business_mode": business_mode, "query": query,
        }
        if thread_id is not None:
            payload["thread_id"] = str(thread_id)
        if overrides is not None:
            if {"project_id", "business_mode", "query", "thread_id"} & overrides.keys():
                raise ValueError("untrusted overrides may not replace core Run fields")
            payload.update(overrides)
        response = await self._request(
            "POST", "/api/v1/runs", user_alias=user_alias, payload=payload,
        )
        if response.status_code == 201 or (allow_denial and response.status_code in {401, 403}):
            return self._result(response)
        raise EvaluationHttpError(response.status_code)

    async def poll_run(
        self,
        *,
        user_alias: str,
        run_id: UUID,
        until_waiting: bool = False,
    ) -> HttpRunResult:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (
            self._waiting_timeout if until_waiting else self._run_timeout
        )
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise EvaluationTimeout("evaluation Run state deadline reached")
            try:
                response = await asyncio.wait_for(
                    self._request("GET", f"/api/v1/runs/{run_id}", user_alias=user_alias),
                    timeout=remaining,
                )
            except EvaluationTimeout as exc:
                # GET /runs/{id} is idempotent. A per-request timeout must not
                # discard an already-created production Run; keep observing it
                # within the original bounded Run deadline.
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise EvaluationTimeout(
                        "evaluation Run state deadline reached"
                    ) from exc
                await asyncio.sleep(min(self._poll_interval, remaining))
                continue
            except EvaluationHttpError as exc:
                # _request() uses status=None only for transport RequestError.
                # Retry that idempotent observation, but never retry semantic
                # HTTP responses (4xx/5xx) or POST create/resume operations.
                if exc.status is not None:
                    raise
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise EvaluationTimeout("evaluation Run state deadline reached") from exc
                await asyncio.sleep(min(self._poll_interval, remaining))
                continue
            except TimeoutError as exc:
                # This timeout is the outer remaining Run deadline, not the
                # per-request timeout translated by _request().
                raise EvaluationTimeout("evaluation Run state deadline reached") from exc
            if response.status_code == 404:
                # POST /runs returning 201 establishes that this poll is for an
                # accepted Run. The API transaction may become visible to a
                # follow-up GET slightly later, so treat 404 here as a bounded
                # read-after-write visibility race rather than as final absence.
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise EvaluationTimeout(
                        "evaluation Run state deadline reached"
                    )
                await asyncio.sleep(
                    min(self._poll_interval, remaining)
                )
                continue

            if response.status_code != 200:
                raise EvaluationHttpError(response.status_code)
            result = self._result(response)
            if result.run_id != run_id:
                raise EvaluationHttpError(200)
            if result.status in _TERMINAL or (
                until_waiting and result.status == "WAITING_CONFIRMATION"
            ):
                return result
            await asyncio.sleep(min(self._poll_interval, max(0.0, deadline - loop.time())))

    async def resume_run(
        self,
        *,
        user_alias: str,
        run_id: UUID,
        request_payload_hash: str,
    ) -> HttpRunResult:
        response = await self._request(
            "POST", f"/api/v1/runs/{run_id}/resume", user_alias=user_alias,
            payload={"action": "confirm", "request_payload_hash": request_payload_hash},
        )
        if response.status_code != 202:
            raise EvaluationHttpError(response.status_code)
        result = self._result(response)
        if result.run_id != run_id:
            raise EvaluationHttpError(202)
        return result
