from __future__ import annotations

import socketserver
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    start_http_server,
)

QueueFailureOutcome = Literal["retry", "failed"]
ProviderOutcome = Literal["success", "error"]
CitationOutcome = Literal["pass", "revision", "refusal"]
AuthorizationDenialReason = Literal[
    "no_active_membership",
    "scope_mismatch",
    "actor_mismatch",
    "role_denied",
]
IssueConfirmationOutcome = Literal["confirmed", "cancelled", "expired", "payload_mismatch"]
IssueCreateOutcome = Literal[
    "created",
    "already_created",
    "pending_reconciliation",
    "reconciled",
    "denied",
]


class ObservabilityMetrics:
    """Process-local bounded-cardinality Prometheus metric registry."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self._http_requests = Counter(
            "project_agent_http_requests_total",
            "HTTP requests completed by the API process.",
            ("method", "route", "status_code"),
            registry=self.registry,
        )
        self._http_duration = Histogram(
            "project_agent_http_request_duration_seconds",
            "HTTP request duration in seconds.",
            ("method", "route"),
            registry=self.registry,
        )
        self._runs = Counter(
            "project_agent_runs_total",
            "Terminal Run transitions.",
            ("business_mode", "outcome"),
            registry=self.registry,
        )
        self._run_duration = Histogram(
            "project_agent_run_duration_seconds",
            "Terminal Run duration in seconds.",
            ("business_mode", "outcome"),
            registry=self.registry,
        )
        self._queue_claims = Counter(
            "project_agent_queue_claims_total",
            "Claimed durable jobs.",
            ("job_type",),
            registry=self.registry,
        )
        self._queue_completions = Counter(
            "project_agent_queue_completions_total",
            "Completed durable jobs.",
            ("job_type",),
            registry=self.registry,
        )
        self._queue_failures = Counter(
            "project_agent_queue_failures_total",
            "Queue failure decisions.",
            ("job_type", "outcome"),
            registry=self.registry,
        )
        self._queue_reaped = Counter(
            "project_agent_queue_reaped_total",
            "Expired lease reaper decisions.",
            ("job_type", "outcome"),
            registry=self.registry,
        )
        self._queue_age = Histogram(
            "project_agent_queue_age_seconds",
            "Durable job age at claim time in seconds.",
            ("job_type",),
            registry=self.registry,
        )
        self._retrieval_rounds = Counter(
            "project_agent_retrieval_rounds_total",
            "Successful logical retrieval rounds.",
            registry=self.registry,
        )
        self._ragflow_requests = Counter(
            "project_agent_ragflow_requests_total",
            "Logical RAGFlow requests.",
            ("operation", "outcome"),
            registry=self.registry,
        )
        self._ragflow_duration = Histogram(
            "project_agent_ragflow_request_duration_seconds",
            "Logical RAGFlow request duration in seconds.",
            ("operation",),
            registry=self.registry,
        )
        self._llm_requests = Counter(
            "project_agent_llm_requests_total",
            "Logical structured LLM requests.",
            ("model_alias", "outcome"),
            registry=self.registry,
        )
        self._llm_duration = Histogram(
            "project_agent_llm_request_duration_seconds",
            "Logical structured LLM request duration in seconds.",
            ("model_alias",),
            registry=self.registry,
        )
        self._llm_tokens = Counter(
            "project_agent_llm_tokens_total",
            "Structured LLM token usage.",
            ("model_alias", "direction"),
            registry=self.registry,
        )
        self._citation_guard = Counter(
            "project_agent_citation_guard_total",
            "Citation Guard routing outcomes.",
            ("outcome",),
            registry=self.registry,
        )
        self._authorization_denials = Counter(
            "project_agent_authorization_denials_total",
            "Authorization denials by bounded internal reason.",
            ("reason",),
            registry=self.registry,
        )
        self._issue_confirmation = Counter(
            "project_agent_issue_confirmation_total",
            "Issue confirmation outcomes.",
            ("outcome",),
            registry=self.registry,
        )
        self._issue_create = Counter(
            "project_agent_issue_create_total",
            "Issue create and reconciliation outcomes.",
            ("outcome",),
            registry=self.registry,
        )

    def render_latest(self) -> bytes:
        return generate_latest(self.registry)

    def observe_http(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        self._http_requests.labels(
            method=method,
            route=route,
            status_code=str(status_code),
        ).inc()
        self._http_duration.labels(method=method, route=route).observe(duration_seconds)

    def observe_run(
        self,
        *,
        business_mode: str,
        outcome: str,
        duration_seconds: float,
    ) -> None:
        self._runs.labels(business_mode=business_mode, outcome=outcome).inc()
        self._run_duration.labels(business_mode=business_mode, outcome=outcome).observe(
            duration_seconds
        )

    def observe_queue_claim(self, *, job_type: str, age_seconds: float) -> None:
        self._queue_claims.labels(job_type=job_type).inc()
        self._queue_age.labels(job_type=job_type).observe(age_seconds)

    def observe_queue_completion(self, *, job_type: str) -> None:
        self._queue_completions.labels(job_type=job_type).inc()

    def observe_queue_failure(
        self,
        *,
        job_type: str,
        outcome: QueueFailureOutcome,
    ) -> None:
        self._queue_failures.labels(job_type=job_type, outcome=outcome).inc()

    def observe_queue_reaped(
        self,
        *,
        job_type: str,
        outcome: QueueFailureOutcome,
        count: int = 1,
    ) -> None:
        self._queue_reaped.labels(job_type=job_type, outcome=outcome).inc(count)

    def increment_retrieval_round(self) -> None:
        self._retrieval_rounds.inc()

    def observe_ragflow(
        self,
        *,
        operation: str,
        outcome: ProviderOutcome,
        duration_seconds: float,
    ) -> None:
        self._ragflow_requests.labels(operation=operation, outcome=outcome).inc()
        self._ragflow_duration.labels(operation=operation).observe(duration_seconds)

    def observe_llm_request(
        self,
        *,
        model_alias: str,
        outcome: ProviderOutcome,
        duration_seconds: float,
    ) -> None:
        self._llm_requests.labels(model_alias=model_alias, outcome=outcome).inc()
        self._llm_duration.labels(model_alias=model_alias).observe(duration_seconds)

    def observe_llm_tokens(
        self,
        *,
        model_alias: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self._llm_tokens.labels(model_alias=model_alias, direction="input").inc(input_tokens)
        self._llm_tokens.labels(model_alias=model_alias, direction="output").inc(output_tokens)
        self._llm_tokens.labels(model_alias=model_alias, direction="total").inc(
            input_tokens + output_tokens
        )

    def observe_citation(self, *, outcome: CitationOutcome) -> None:
        self._citation_guard.labels(outcome=outcome).inc()

    def observe_authorization_denial(self, *, reason: AuthorizationDenialReason) -> None:
        self._authorization_denials.labels(reason=reason).inc()

    def observe_issue_confirmation(self, *, outcome: IssueConfirmationOutcome) -> None:
        self._issue_confirmation.labels(outcome=outcome).inc()

    def observe_issue_create(self, *, outcome: IssueCreateOutcome) -> None:
        self._issue_create.labels(outcome=outcome).inc()


_current_metrics: ContextVar[ObservabilityMetrics | None] = ContextVar(
    "project_agent_current_metrics",
    default=None,
)


@contextmanager
def metrics_context(metrics: ObservabilityMetrics) -> Iterator[None]:
    token = _current_metrics.set(metrics)
    try:
        yield
    finally:
        _current_metrics.reset(token)


def current_metrics() -> ObservabilityMetrics | None:
    return _current_metrics.get()


@dataclass(slots=True)
class MetricsHttpServerHandle:
    server: socketserver.BaseServer
    thread: threading.Thread

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def start_metrics_http_server(
    *,
    metrics: ObservabilityMetrics,
    host: str,
    port: int,
) -> MetricsHttpServerHandle:
    server, thread = start_http_server(port, addr=host, registry=metrics.registry)
    return MetricsHttpServerHandle(server=server, thread=thread)
