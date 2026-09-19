# WS6 Observability + Run Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument the frozen WS1–WS5 runtime with safe JSON structured logging, bounded Prometheus telemetry, process-local API/Worker metrics endpoints, durable Run token/cost telemetry, and executable sanitization/live-acceptance proof without changing business semantics.

**Architecture:** Add a thin `project_agent.observability` package and instrument only authoritative runtime seams. API and Worker each own an isolated Prometheus registry; request/job execution binds the process registry into a context variable so deep RAGFlow/LLM/Citation/Auth/Issue code can record telemetry without redesigning existing service interfaces. Durable cost remains in `agent_runs` and is recomputed atomically with cumulative token updates using an explicit integer microunit price policy. The frozen WS4 branch is integrated first; WS6 never reimplements its Structured LLM adapter or QA behavior.

**Tech Stack:** Python 3.12.14, FastAPI, structlog 25.x, the official Prometheus Python client (resolver-selected and locked by `uv.lock` in Task 2), SQLAlchemy asyncio + asyncpg, PostgreSQL, LangGraph 1.2.x, RAGFlow HTTP adapter, pytest/pytest-asyncio, Ruff, MyPy.

**Spec:** `docs/superpowers/specs/2026-09-19-ws6-observability-run-telemetry-design.md`

## Verified Starting State

```text
worktree = /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws6-observability-run-telemetry
branch = feat/ws6-observability-run-telemetry
WS6_START_HEAD = 5123efbaa3821f34a6198cdebadd4631f8bceeef
WS4_FROZEN_HEAD = ed6add6
WS4_FROZEN_BRANCH = feat/ws4-real-structured-llm-qa
Python = 3.12.14
Alembic current/head = 0005_run_runtime_envelope
offline baseline = 328 passed, 26 skipped
ruff = GREEN
mypy = GREEN
working tree = clean
```

The start package does not contain the WS4 branch tree, so this plan does not invent provider-adapter file names. LLM observability is attached to the already-present stable application ports in `src/project_agent/application/ports/llm.py` and the already-present QA graph composition in `src/project_agent/agent/graph.py`. Task 0 integrates the exact frozen WS4 commit before any LLM live acceptance.

## Global Constraints

- Real implementation target is `/home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws6-observability-run-telemetry` on branch `feat/ws6-observability-run-telemetry`.
- Preserve the frozen WS2 Run API, persistence, SSE, resume, and ordered `AgentEvent` contracts.
- Preserve the frozen WS3 PostgreSQL queue claim/lease/heartbeat/retry/reaper/checkpoint/execute-resume contracts and transaction boundaries.
- Preserve the frozen WS4 retrieval, real Structured LLM, answer-generation, max-two-round retrieval, citation, and refusal semantics.
- Preserve the frozen WS5 Issue evidence, confirmation, permission re-check, idempotency, create, response-lost, and reconciliation semantics.
- Do not introduce Redis, Celery, ARQ, MinIO, a second vector DB, a new multi-agent runtime, a unified LangGraph rewrite, Kubernetes, production Jira/SaaS integration, OpenTelemetry, StatsD, Sentry, Grafana, or a Prometheus server.
- No Alembic migration is planned. `0005_run_runtime_envelope` remains current/head unless an approved RED test proves the existing schema cannot satisfy the frozen WS6 design.
- Structured logs may contain contextual IDs when applicable, but must not contain raw JWTs, API keys, passwords, secrets, provider credentials, full query text, full Evidence text, full answer text, full prompts, raw request/response bodies, or raw provider error bodies.
- Prometheus labels must never contain `run_id`, `job_id`, `user_id`, `project_id`, query text, issue key, document/document-version IDs, RAGFlow dataset/document IDs, raw dynamic URL paths, or arbitrary error/provider bodies.
- API and Worker metrics are process-local operational telemetry, not durable audit truth. Durable Run/Event records remain authoritative.
- Provider pricing is never inferred from model/provider knowledge. Cost uses only explicit configured integer microunit rates per one million tokens.
- When token prices are omitted, persist `estimated_cost_microunits = 0` and emit `cost_estimate_configured=false` in structured telemetry.
- `ocr_pages` remains `0` when no genuine OCR producer exists; do not infer it from PDF page count or metadata.
- Every implementation task follows `RED -> confirm missing behavior -> minimal GREEN -> targeted regression -> broader regression -> commit`.
- Any unexpected test/runtime failure triggers `superpowers:systematic-debugging` before proposing a fix.
- Before declaring WS6 complete, use `superpowers:verification-before-completion`; required live PostgreSQL/RAGFlow/LLM skips do not count as a pass.

## Locked File Map

### Create

- `src/project_agent/observability/__init__.py` — public observability exports only.
- `src/project_agent/observability/logging.py` — structlog JSON configuration, context binding/cleanup, duration helper.
- `src/project_agent/observability/sanitization.py` — recursive sensitive-key redaction and safe exception metadata.
- `src/project_agent/observability/metrics.py` — isolated registry, all WS6 metric families, context binding, Structured LLM decorator, metrics rendering/server helper.
- `src/project_agent/observability/cost.py` — explicit integer token-price policy, cost estimate result, current-policy context.
- `tests/unit/observability/__init__.py`
- `tests/unit/observability/test_logging.py`
- `tests/unit/observability/test_sanitization.py`
- `tests/unit/observability/test_metrics.py`
- `tests/unit/observability/test_cost.py`
- `tests/integration/observability/__init__.py`
- `tests/integration/observability/test_api_metrics.py`
- `tests/integration/observability/test_run_telemetry_postgres.py`
- `tests/integration/observability/test_queue_metrics_postgres.py`
- `tests/integration/observability/test_ragflow_telemetry.py`
- `tests/integration/observability/test_llm_telemetry.py`
- `tests/security/test_observability_sanitization.py`

### Modify

- `pyproject.toml` — add official Prometheus client dependency only.
- `uv.lock` — synchronize the dependency lock.
- `.env.example` — document WS6 non-secret settings only; do not copy `.env`.
- `src/project_agent/config.py` — add/validate logging, Worker metrics, and explicit cost settings.
- `src/project_agent/main.py` — API process registry, structlog setup, request middleware, `/metrics`.
- `src/project_agent/api/dependencies.py` — bind authenticated user context only after successful JWT verification.
- `src/project_agent/api/v1/runs.py` — bind bounded Run/project/business-mode context; never bind query text.
- `src/project_agent/runtime/worker.py` — construct Worker registry/cost policy and own Worker metrics-server lifecycle.
- `src/project_agent/workers/main.py` — bind/clear job context and preserve handler/heartbeat semantics.
- `src/project_agent/infrastructure/jobs/postgres.py` — queue claim/age/completion/retry/final-failure/reaper observations after authoritative decisions.
- `src/project_agent/application/services/run_execution.py` — Run context plus waiting/terminal logs and exactly-once terminal metrics.
- `src/project_agent/infrastructure/db/repositories/qa_graph.py` — cumulative token/cost persistence and retrieval-round metric at the existing durable seams.
- `src/project_agent/infrastructure/ragflow/client.py` — logical-request RAGFlow timing/error metrics and safe logs.
- `src/project_agent/agent/graph.py` — wrap frozen WS4 LLM ports with the WS6 observer without touching provider semantics.
- `src/project_agent/agent/nodes/citation_guard.py` — pass/revision/refusal observations at the authoritative routing point.
- `src/project_agent/application/services/authorization.py` — bounded `no_active_membership` denial observation.
- `src/project_agent/application/services/runs.py` — bounded Run ownership denial observations (`scope_mismatch`, `actor_mismatch`).
- `src/project_agent/application/services/issue_confirmation.py` — confirmed/cancelled/expired/payload-mismatch observations.
- `src/project_agent/application/services/issue_creation.py` — denied/create/reconciliation observations without moving safety barriers.
- Existing tests in `tests/unit/runtime/`, `tests/unit/workers/`, `tests/unit/issues/`, `tests/integration/api/`, `tests/integration/jobs/`, `tests/contract/ragflow/`, `tests/security/`, and `tests/reliability/` only where extending an existing frozen invariant is clearer than duplicating it.

### Explicitly Not Modified

- `alembic/versions/*` under the approved design.
- WS2 external Run request/response/SSE schema.
- queue payload shape or lease/retry formulas.
- WS4 provider request/response schema, model selection, structured-response validation, retrieval grading, or answer semantics.
- WS5 provider payload hash, confirmation/idempotency barrier, or project-tracker side-effect semantics.
- Compose/Kubernetes/Prometheus server/Grafana topology.

## Public WS6 Interfaces Locked by This Plan

The implementation tasks below use these names consistently.

```python
# project_agent.observability.cost
@dataclass(frozen=True, slots=True)
class CostEstimate:
    microunits: int
    currency: str
    configured: bool

@dataclass(frozen=True, slots=True)
class TokenCostPolicy:
    input_microunits_per_million_tokens: int | None
    output_microunits_per_million_tokens: int | None
    currency: str = "USD"

    @classmethod
    def unconfigured(cls, currency: str = "USD") -> "TokenCostPolicy": ...
    def estimate(self, *, input_tokens: int, output_tokens: int) -> CostEstimate: ...

@contextmanager
def cost_policy_context(policy: TokenCostPolicy) -> Iterator[None]: ...
def current_cost_policy() -> TokenCostPolicy: ...
```

```python
# project_agent.observability.logging
def configure_structured_logging(*, log_level: str) -> None: ...
def get_logger() -> structlog.stdlib.BoundLogger: ...
def bind_log_context(**fields: object) -> None: ...
def clear_log_context() -> None: ...
def elapsed_ms(start_ns: int) -> float: ...
```

```python
# project_agent.observability.sanitization
REDACTED = "[REDACTED]"
def sanitize_event_dict(
    logger: object,
    method_name: str,
    event_dict: dict[str, object],
) -> dict[str, object]: ...
def safe_error_fields(exc: BaseException) -> dict[str, object]: ...
```

```python
# project_agent.observability.metrics
class ObservabilityMetrics:
    registry: CollectorRegistry
    def render_latest(self) -> bytes: ...
    def observe_http(self, *, method: str, route: str, status_code: int, duration_seconds: float) -> None: ...
    def observe_run(self, *, business_mode: str, outcome: str, duration_seconds: float) -> None: ...
    def observe_queue_claim(self, *, job_type: str, age_seconds: float) -> None: ...
    def observe_queue_completion(self, *, job_type: str) -> None: ...
    def observe_queue_failure(self, *, job_type: str, outcome: Literal["retry", "failed"]) -> None: ...
    def observe_queue_reaped(self, *, job_type: str, outcome: Literal["retry", "failed"], count: int = 1) -> None: ...
    def increment_retrieval_round(self) -> None: ...
    def observe_ragflow(self, *, operation: str, outcome: Literal["success", "error"], duration_seconds: float) -> None: ...
    def observe_llm_request(self, *, model_alias: str, outcome: Literal["success", "error"], duration_seconds: float) -> None: ...
    def observe_llm_tokens(self, *, model_alias: str, input_tokens: int, output_tokens: int) -> None: ...
    def observe_citation(self, *, outcome: Literal["pass", "revision", "refusal"]) -> None: ...
    def observe_authorization_denial(self, *, reason: Literal["no_active_membership", "scope_mismatch", "actor_mismatch", "role_denied"]) -> None: ...
    def observe_issue_confirmation(self, *, outcome: Literal["confirmed", "cancelled", "expired", "payload_mismatch"]) -> None: ...
    def observe_issue_create(self, *, outcome: Literal["created", "already_created", "pending_reconciliation", "reconciled", "denied"]) -> None: ...

@contextmanager
def metrics_context(metrics: ObservabilityMetrics) -> Iterator[None]: ...
def current_metrics() -> ObservabilityMetrics | None: ...

@dataclass(slots=True)
class MetricsHttpServerHandle:
    server: socketserver.BaseServer
    thread: threading.Thread
    def close(self) -> None: ...

def start_metrics_http_server(*, metrics: ObservabilityMetrics, host: str, port: int) -> MetricsHttpServerHandle: ...

class ObservedStructuredLLM(StructuredLLMPort, StructuredLLMUsagePort):
    def __init__(self, llm: StructuredLLMPort, usage: StructuredLLMUsagePort) -> None: ...
    async def generate(self, request: StructuredLLMRequest, response_model: type[TStructured]) -> TStructured: ...
    async def get_usage(self, request_id: str) -> LLMTokenUsage: ...
```

`ObservedStructuredLLM` treats `generate + get_usage` as one logical LLM request: generation failure records one error immediately; generation success remains pending until usage is fetched; usage success records one success plus input/output/total token counters; usage failure records one error. It re-raises the original exception unchanged and never logs prompt/response/provider-body content.

## Review Focus

These five failure modes are easy to miss and each is explicitly pinned to a task test below:

1. **Concurrent request/job context leakage:** one request/job must never inherit another request/job IDs or user context. Task 1 and Task 4 add concurrent context-isolation tests.
2. **Dynamic label cardinality:** UUID paths, issue keys, user IDs, document IDs, and provider bodies must not appear as Prometheus label values. Task 2/3/8 render actual metrics and search for sentinels.
3. **Duplicate Run terminal counting:** replaying a terminal Run transition must return the existing terminal state without incrementing `project_agent_runs_total` twice. Task 5 pins the existing idempotent early-return behavior.
4. **Cumulative cost rounding across multiple LLM calls/revision:** cost floors once after cumulative-token numerator calculation, not per call. Task 2 and Task 5 verify the exact arithmetic and persistence.
5. **Provider failure sanitization:** RAGFlow/LLM exceptions containing a unique provider-body sentinel must preserve exception type/propagation while the sentinel is absent from logs and metrics. Task 6 and Task 8 verify this end to end.

---

# Pre-Implementation Gate

This gate happens before Task 0 or any production change.

- [ ] **Step 1: Enter the exact WS6 worktree/environment**

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws6-observability-run-telemetry
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate it-agent
export PYTHONPATH="$PWD/src"
set -a
source .env
set +a

python --version
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected:

```text
Python 3.12.14
feat/ws6-observability-run-telemetry
5123efbaa3821f34a6198cdebadd4631f8bceeef
<empty status>
```

- [ ] **Step 2: Verify the Design document is committed before plan execution**

```bash
git log -5 --oneline -- docs/superpowers/specs/2026-09-19-ws6-observability-run-telemetry-design.md
git status --short
```

Expected: the frozen Design appears in history and the worktree is clean. If the Design is present but uncommitted, commit only that document before proceeding.

- [ ] **Step 3: Re-run the non-live baseline immediately before execution**

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest -q -rs
alembic current
alembic heads
```

Expected: Ruff/MyPy/diff check PASS; pytest has zero failures; `alembic current` and `alembic heads` both resolve to `0005_run_runtime_envelope`. Any unexpected failure stops execution and invokes `superpowers:systematic-debugging`.

**Gate judgment:**

```text
需求完成：⏳ precondition only
测试闭环：✅ only when all baseline commands above are GREEN
新 bug：未发现 / 已发现：<report the exact failing baseline command without starting WS6 code>
```

---

## Task 0: Integrate the Exact Frozen WS4 Commit and Re-establish the Baseline

**Files:**
- Git integration only; do not intentionally edit production files beyond conflict resolution required by the exact frozen merge.
- Review references: `docs/superpowers/specs/2026-09-19-ws6-observability-run-telemetry-design.md`, WS4 frozen branch `feat/ws4-real-structured-llm-qa`, WS5 completed documents.

**Interfaces:**
- Consumes: `feat/ws4-real-structured-llm-qa@ed6add6` exactly.
- Produces: one WS6 branch state containing frozen WS4 + frozen WS5 behavior with a GREEN baseline. No WS6 telemetry behavior is implemented in this task.

- [ ] **Step 1: Inspect ancestry and exact WS4 delta without modifying the worktree**

```bash
git merge-base HEAD feat/ws4-real-structured-llm-qa
git log --oneline --left-right HEAD...feat/ws4-real-structured-llm-qa
git diff --stat HEAD...feat/ws4-real-structured-llm-qa
git show --stat --oneline ed6add6
```

Expected: `ed6add6` is the frozen WS4 completion commit identified during Design Freeze. Do not substitute another branch tip.

- [ ] **Step 2: Merge the exact frozen WS4 commit**

```bash
git merge --no-ff ed6add6 -m "merge: integrate frozen ws4 structured llm qa runtime"
```

Expected: merge succeeds without altering WS4/WS5 semantics. If Git reports conflicts, stop the task before editing conflict markers, invoke `superpowers:systematic-debugging`, and resolve only by comparing the frozen WS4 and WS5 contracts; do not use the merge as a reason to redesign either workstream.

- [ ] **Step 3: Verify the frozen LLM ports still exist unchanged as the WS6 instrumentation target**

```bash
rg -n "class StructuredLLMPort|class StructuredLLMUsagePort|class StructuredLLMRequest|class LLMTokenUsage" \
  src/project_agent/application/ports/llm.py
rg -n "QAGraphDependencies|build_project_qa_graph" src/project_agent/agent/graph.py
```

Expected: the stable port names and QA graph composition remain present.

- [ ] **Step 4: Run post-merge static and full offline regression**

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest -q -rs
```

Expected: zero failures. The exact pass count may increase because WS4 tests are now present; only explicit environment-gated skips are acceptable.

- [ ] **Step 5: Run the existing live PostgreSQL/Worker regression relevant to WS2–WS5**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

python -m pytest \
  tests/integration/db/test_postgres_schema.py \
  tests/integration/api/test_run_api_postgres.py \
  tests/integration/workers/test_run_worker_postgres.py \
  tests/integration/workers/test_run_resume_postgres.py \
  tests/integration/issues/test_issue_run_runtime_postgres.py \
  -v -rs
```

Expected: all selected tests PASS with zero selected-test skips. If a required selected test skips, Task 0 is not closed.

- [ ] **Step 6: Record the Task 0 gate**

```bash
git status --short
git log --oneline --decorate -5
```

Expected: only the WS4 merge commit is new; no unrelated working-tree changes.

**Stage report:**

```text
需求完成：✅ only if exact WS4 frozen commit is integrated
测试闭环：✅ only if offline + selected PostgreSQL regression are GREEN with zero selected live skips
新 bug：未发现 / 已发现：<exact integration regression>
```

---

## Task 1: JSON Logging, Context Isolation, and Sanitization Foundation

**Files:**
- Create: `src/project_agent/observability/__init__.py`
- Create: `src/project_agent/observability/logging.py`
- Create: `src/project_agent/observability/sanitization.py`
- Create: `tests/unit/observability/__init__.py`
- Create: `tests/unit/observability/test_logging.py`
- Create: `tests/unit/observability/test_sanitization.py`
- Modify: `src/project_agent/config.py`
- Modify: `.env.example`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: existing `structlog>=25.4,<26.0`, `Settings`.
- Produces: `configure_structured_logging`, `get_logger`, `bind_log_context`, `clear_log_context`, `elapsed_ms`, `sanitize_event_dict`, `safe_error_fields`, and `Settings.log_level`.

- [ ] **Step 1: Write RED tests for log shape and context cleanup**

Add `tests/unit/observability/test_logging.py` with concrete assertions equivalent to:

```python
import asyncio
import json

from project_agent.observability.logging import (
    bind_log_context,
    clear_log_context,
    configure_structured_logging,
    get_logger,
)


def test_structured_log_has_timestamp_level_event_and_context(capsys):
    configure_structured_logging(log_level="INFO")
    clear_log_context()
    bind_log_context(service="api", run_id="run-safe")
    get_logger().info("run_started", outcome="running")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "run_started"
    assert payload["level"] == "info"
    assert payload["service"] == "api"
    assert payload["run_id"] == "run-safe"
    assert payload["outcome"] == "running"
    assert payload["timestamp"].endswith("Z") or "+00:00" in payload["timestamp"]


async def _capture_context(value: str) -> str:
    clear_log_context()
    bind_log_context(run_id=value)
    await asyncio.sleep(0)
    from structlog.contextvars import get_contextvars
    return str(get_contextvars()["run_id"])


@pytest.mark.asyncio
async def test_concurrent_contexts_do_not_leak():
    left, right = await asyncio.gather(
        _capture_context("run-left"),
        _capture_context("run-right"),
    )
    assert {left, right} == {"run-left", "run-right"}
```

Add `import pytest` to the test module. The test must run as an async pytest test so both tasks execute concurrently in one event loop while retaining independent context variables.

- [ ] **Step 2: Run the RED logging tests and confirm the failure is feature absence**

```bash
python -m pytest tests/unit/observability/test_logging.py -v
```

Expected: import failure because `project_agent.observability.logging` does not exist yet.

- [ ] **Step 3: Write RED sanitizer tests with unique sentinels**

Add `tests/unit/observability/test_sanitization.py`:

```python
from project_agent.observability.sanitization import REDACTED, sanitize_event_dict


def test_sanitizer_redacts_sensitive_keys_recursively():
    event = {
        "event": "provider_failed",
        "authorization": "Bearer JWT-SENTINEL-4b03",
        "ragflow_api_key": "RAGFLOW-KEY-SENTINEL-91de",
        "query": "QUERY-SENTINEL-0be9",
        "nested": {
            "answer_text": "ANSWER-SENTINEL-ea24",
            "safe_count": 3,
        },
    }
    sanitized = sanitize_event_dict(None, "error", event)
    assert sanitized["authorization"] == REDACTED
    assert sanitized["ragflow_api_key"] == REDACTED
    assert sanitized["query"] == REDACTED
    assert sanitized["nested"]["answer_text"] == REDACTED
    assert sanitized["nested"]["safe_count"] == 3
    assert sanitized["event"] == "provider_failed"
```

Also assert `safe_error_fields(RuntimeError("PROVIDER-BODY-SENTINEL-6dca"))` contains `error_type="RuntimeError"` but not the exception message.

- [ ] **Step 4: Add `Settings.log_level` RED validation**

Extend `tests/unit/test_config.py` with:

```python
def test_settings_default_log_level_is_info(valid_settings_kwargs):
    settings = Settings(**valid_settings_kwargs)
    assert settings.log_level == "INFO"


def test_settings_rejects_unknown_log_level(valid_settings_kwargs):
    with pytest.raises(ValidationError):
        Settings(**valid_settings_kwargs, log_level="TRACE")
```

Adapt `valid_settings_kwargs` to the test file's existing fixture/helper style rather than introducing a second Settings factory.

- [ ] **Step 5: Implement the minimal logging/sanitization foundation**

In `sanitization.py`, use an explicit normalized-key deny set covering at least:

```python
SENSITIVE_KEYS = frozenset({
    "authorization", "cookie", "jwt", "token", "api_key", "password", "secret",
    "credentials", "query", "query_text", "evidence", "evidence_text", "answer",
    "answer_text", "system_prompt", "user_prompt", "prompt", "request_body",
    "response_body", "provider_body", "provider_error_body",
})
```

Recursively sanitize mappings and sequences. Preserve safe scalar operational values. `safe_error_fields()` returns only the exception class plus explicitly safe typed fields such as integer `status_code` or bounded API `code`; it never includes `str(exc)` or `.message`.

In `logging.py`, configure structlog with:

```python
[
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
    sanitize_event_dict,
    structlog.processors.JSONRenderer(),
]
```

Use `structlog.PrintLoggerFactory(file=sys.stdout)`, normalize the configured level through `structlog.make_filtering_bound_logger`, and make repeated `configure_structured_logging()` calls safe for tests/app factories.

In `config.py`, add:

```python
log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
```

In `.env.example`, add only:

```text
LOG_LEVEL=INFO
```

- [ ] **Step 6: Run targeted GREEN tests**

```bash
python -m pytest \
  tests/unit/observability/test_logging.py \
  tests/unit/observability/test_sanitization.py \
  tests/unit/test_config.py \
  -v
```

Expected: PASS.

- [ ] **Step 7: Run static + broader regression**

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest tests/unit -q -rs
```

Expected: GREEN.

- [ ] **Step 8: Commit Task 1**

```bash
git add \
  .env.example \
  src/project_agent/config.py \
  src/project_agent/observability/__init__.py \
  src/project_agent/observability/logging.py \
  src/project_agent/observability/sanitization.py \
  tests/unit/observability/__init__.py \
  tests/unit/observability/test_logging.py \
  tests/unit/observability/test_sanitization.py \
  tests/unit/test_config.py

git commit -m "feat(ws6): add structured logging foundation"
```

**Stage report:**

```text
需求完成：✅ / ❌ / ⏳
测试闭环：✅ / ❌ / ⚠️
新 bug：未发现 / 已发现：...
```

---

## Task 2: Prometheus Registry, Explicit Cost Policy, and WS6 Settings

**Files:**
- Create: `src/project_agent/observability/metrics.py`
- Create: `src/project_agent/observability/cost.py`
- Create: `tests/unit/observability/test_metrics.py`
- Create: `tests/unit/observability/test_cost.py`
- Modify: `src/project_agent/observability/__init__.py`
- Modify: `src/project_agent/config.py`
- Modify: `.env.example`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: Task 1 logging/sanitization helpers.
- Produces: `ObservabilityMetrics`, metrics context, all frozen metric families, `MetricsHttpServerHandle`, `start_metrics_http_server`, `TokenCostPolicy`, cost-policy context, and validated Worker metrics/cost Settings.

- [ ] **Step 1: Add the official Prometheus client dependency before writing metric imports**

Use the project package manager rather than inventing a provider/version from memory:

```bash
uv add prometheus-client
```

Then inspect the dependency-only diff:

```bash
git diff -- pyproject.toml uv.lock
```

Expected: `pyproject.toml` gains exactly one direct `prometheus-client` dependency, `uv.lock` records the resolver-selected compatible version, and no unrelated direct dependency family is introduced. Do not hand-edit a guessed current Prometheus version.

- [ ] **Step 2: Write RED cost-policy tests**

Add `tests/unit/observability/test_cost.py`:

```python
import pytest

from project_agent.observability.cost import TokenCostPolicy


def test_unconfigured_cost_is_zero_and_explicitly_unconfigured():
    estimate = TokenCostPolicy.unconfigured("USD").estimate(
        input_tokens=1234,
        output_tokens=567,
    )
    assert estimate.microunits == 0
    assert estimate.currency == "USD"
    assert estimate.configured is False


def test_cost_floors_once_after_cumulative_numerator():
    policy = TokenCostPolicy(333_333, 777_777, "USD")
    estimate = policy.estimate(input_tokens=3, output_tokens=2)
    assert estimate.microunits == (3 * 333_333 + 2 * 777_777) // 1_000_000
    assert estimate.configured is True


def test_price_pair_must_be_both_present_or_both_absent():
    with pytest.raises(ValueError):
        TokenCostPolicy(100, None, "USD")


def test_negative_tokens_or_prices_are_rejected():
    with pytest.raises(ValueError):
        TokenCostPolicy(-1, 10, "USD")
    with pytest.raises(ValueError):
        TokenCostPolicy(10, 20, "USD").estimate(input_tokens=-1, output_tokens=0)
```

- [ ] **Step 3: Write RED isolated-registry and cardinality tests**

Add `tests/unit/observability/test_metrics.py` with at least:

```python
from prometheus_client import generate_latest

from project_agent.observability.metrics import ObservabilityMetrics


def test_two_metric_instances_have_isolated_registries():
    left = ObservabilityMetrics()
    right = ObservabilityMetrics()
    left.observe_http(method="GET", route="/health", status_code=200, duration_seconds=0.01)

    assert b'project_agent_http_requests_total{method="GET",route="/health",status_code="200"} 1.0' in generate_latest(left.registry)
    assert b'project_agent_http_requests_total{method="GET",route="/health",status_code="200"}' not in generate_latest(right.registry)


def test_metric_surface_has_no_dynamic_id_label_names_or_values():
    metrics = ObservabilityMetrics()
    metrics.observe_run(business_mode="qa", outcome="succeeded", duration_seconds=0.2)
    rendered = metrics.render_latest().decode()

    for forbidden in ("run_id=", "job_id=", "user_id=", "project_id=", "issue_key=", "document_id="):
        assert forbidden not in rendered
```

Also exercise each frozen label enum through its typed recorder method; do not expose a generic `labels: dict[str, str]` recording API.

- [ ] **Step 4: Write RED Settings validation for Worker metrics and cost rates**

Extend `tests/unit/test_config.py` to prove:

```python
settings.worker_metrics_enabled is True
settings.worker_metrics_host == "127.0.0.1"
settings.worker_metrics_port == 9101
settings.llm_input_cost_microunits_per_million_tokens is None
settings.llm_output_cost_microunits_per_million_tokens is None
settings.cost_currency == "USD"
```

Add failures for one-sided rate configuration, negative rates, port outside `1..65535`, and a currency that is not exactly three ASCII letters after normalization.

- [ ] **Step 5: Implement `TokenCostPolicy` and current-policy context**

Use integer arithmetic only:

```python
numerator = (
    input_tokens * self.input_microunits_per_million_tokens
    + output_tokens * self.output_microunits_per_million_tokens
)
microunits = numerator // 1_000_000
```

`TokenCostPolicy.unconfigured()` returns both rates `None`. `current_cost_policy()` returns an explicit unconfigured policy when no Worker context has bound one; it never imports provider prices.

- [ ] **Step 6: Implement `ObservabilityMetrics` with fixed families and label signatures**

Create exactly these metric families in an isolated `CollectorRegistry` owned by each `ObservabilityMetrics` instance:

```text
project_agent_http_requests_total{method,route,status_code}
project_agent_http_request_duration_seconds{method,route}
project_agent_runs_total{business_mode,outcome}
project_agent_run_duration_seconds{business_mode,outcome}
project_agent_queue_claims_total{job_type}
project_agent_queue_completions_total{job_type}
project_agent_queue_failures_total{job_type,outcome}
project_agent_queue_reaped_total{job_type,outcome}
project_agent_queue_age_seconds{job_type}
project_agent_retrieval_rounds_total
project_agent_ragflow_requests_total{operation,outcome}
project_agent_ragflow_request_duration_seconds{operation}
project_agent_llm_requests_total{model_alias,outcome}
project_agent_llm_request_duration_seconds{model_alias}
project_agent_llm_tokens_total{model_alias,direction}
project_agent_citation_guard_total{outcome}
project_agent_authorization_denials_total{reason}
project_agent_issue_confirmation_total{outcome}
project_agent_issue_create_total{outcome}
```

Use `Counter` and `Histogram`; do not add a per-job or pending-count gauge. `render_latest()` calls `prometheus_client.generate_latest(self.registry)`.

Implement `metrics_context()` with `contextvars.ContextVar` and a `None` default so deep instrumentation can be a no-op when no API/Worker runtime has bound a registry.

Implement `start_metrics_http_server()` with `prometheus_client.start_http_server(port, addr=host, registry=metrics.registry)` and a handle whose `close()` calls `shutdown()`, `server_close()`, then joins the thread.

- [ ] **Step 7: Add WS6 settings and environment example**

In `Settings`, add:

```python
worker_metrics_enabled: bool = True
worker_metrics_host: str = "127.0.0.1"
worker_metrics_port: int = Field(default=9101, ge=1, le=65535)
llm_input_cost_microunits_per_million_tokens: int | None = Field(default=None, ge=0)
llm_output_cost_microunits_per_million_tokens: int | None = Field(default=None, ge=0)
cost_currency: str = "USD"
```

Extend the existing `model_validator` so the two prices are both present or both absent and normalize/validate currency as exactly three ASCII letters. Do not change `SecretStr` fields.

Add to `.env.example`:

```text
WORKER_METRICS_ENABLED=true
WORKER_METRICS_HOST=127.0.0.1
WORKER_METRICS_PORT=9101
# LLM_INPUT_COST_MICROUNITS_PER_MILLION_TOKENS=
# LLM_OUTPUT_COST_MICROUNITS_PER_MILLION_TOKENS=
COST_CURRENCY=USD
```

Blank commented prices mean “not configured”; do not supply sample provider prices.

- [ ] **Step 8: Run targeted GREEN tests**

```bash
python -m pytest \
  tests/unit/observability/test_metrics.py \
  tests/unit/observability/test_cost.py \
  tests/unit/test_config.py \
  -v
```

Expected: PASS.

- [ ] **Step 9: Static + broader regression**

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest tests/unit -q -rs
```

Expected: GREEN.

- [ ] **Step 10: Commit Task 2**

```bash
git add \
  .env.example pyproject.toml uv.lock \
  src/project_agent/config.py \
  src/project_agent/observability/__init__.py \
  src/project_agent/observability/metrics.py \
  src/project_agent/observability/cost.py \
  tests/unit/observability/test_metrics.py \
  tests/unit/observability/test_cost.py \
  tests/unit/test_config.py

git commit -m "feat(ws6): add metrics and cost policy"
```

---

## Task 3: API Structured Request Logs, Route-Template Metrics, and `/metrics`

**Files:**
- Modify: `src/project_agent/main.py`
- Modify: `src/project_agent/api/dependencies.py`
- Modify: `src/project_agent/api/v1/runs.py`
- Create: `tests/integration/observability/__init__.py`
- Create: `tests/integration/observability/test_api_metrics.py`
- Regression: `tests/integration/api/test_authentication.py`
- Regression: `tests/integration/api/test_health.py`
- Regression: `tests/integration/api/test_run_api.py`

**Interfaces:**
- Consumes: `ObservabilityMetrics`, `metrics_context`, Task 1 log helpers.
- Produces: one isolated API registry per `create_app()` instance, unauthenticated `GET /metrics`, bounded HTTP metrics, JSON completion/failure logs, and request-scoped context cleanup.

- [ ] **Step 1: Write RED API metrics tests**

Create `tests/integration/observability/test_api_metrics.py` using the existing fake `ApiRuntimeFactory` style. Prove:

```python
def test_metrics_endpoint_exposes_aggregated_http_metrics_without_auth():
    app = create_app(test_settings, runtime_factory=fake_factory)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "project_agent_http_requests_total" in metrics.text


def test_run_uuid_is_not_used_as_http_metric_route_label():
    run_id = uuid4()
    app = create_app(test_settings, runtime_factory=fake_factory)
    with TestClient(app) as client:
        client.get(f"/api/v1/runs/{run_id}", headers=valid_auth_header)
        rendered = client.get("/metrics").text
    assert f'/api/v1/runs/{run_id}' not in rendered
    assert '/api/v1/runs/{run_id}' in rendered
```

Use the actual health path from `src/project_agent/api/v1/health.py`; do not invent a second health route.

- [ ] **Step 2: Add RED tests for app-registry isolation and exception status**

Instantiate two separate apps and prove a request against app A does not increment app B. Add a route/test path that causes an existing unhandled exception and verify middleware records status `500` while FastAPI exception behavior is unchanged.

- [ ] **Step 3: Run RED tests**

```bash
python -m pytest tests/integration/observability/test_api_metrics.py -v
```

Expected: failures because `/metrics` and WS6 middleware do not yet exist.

- [ ] **Step 4: Implement API registry/middleware in `create_app()`**

Extend `create_app()` with a keyword-only test seam:

```python
def create_app(
    settings: Settings | None = None,
    *,
    runtime_factory: ApiRuntimeFactory = build_api_runtime,
    metrics: ObservabilityMetrics | None = None,
) -> FastAPI:
```

Create `api_metrics = metrics or ObservabilityMetrics()` once per app and store it on `app.state.metrics`.

During lifespan after Settings resolves, call:

```python
configure_structured_logging(log_level=resolved_settings.log_level)
```

Add HTTP middleware with this semantic order:

```text
clear_log_context()
bind service=api
bind metrics_context(api_metrics)
start monotonic timer
call_next(request)
resolve request.scope["route"].path after routing; fallback "unmatched"
record method/route/status + latency
emit http_request_completed or http_request_failed
clear_log_context() in finally
re-raise original exception unchanged
```

Never log headers, body, query text, or exception message.

- [ ] **Step 5: Add `/metrics` without authentication or business payloads**

Register `GET /metrics` with `include_in_schema=False` and return:

```python
Response(
    content=api_metrics.render_latest(),
    media_type=CONTENT_TYPE_LATEST,
)
```

The request itself may be counted as route `/metrics`; this is bounded and allowed.

- [ ] **Step 6: Bind known user/Run/project context without logging protected text**

In `get_authenticated_identity()`, after successful verification only:

```python
identity = runtime.jwt_verifier.verify(credentials.credentials)
bind_log_context(user_id=str(identity.user_id))
return identity
```

In Run routes, bind only already-known bounded context:

```python
bind_log_context(project_id=str(payload.project_id), business_mode=payload.business_mode.value)
```

for create, and `run_id=str(run_id)` for ID routes. Never bind `payload.query` or `request_payload_hash`.

- [ ] **Step 7: Run targeted API GREEN tests plus existing API regression**

```bash
python -m pytest \
  tests/integration/observability/test_api_metrics.py \
  tests/integration/api/test_authentication.py \
  tests/integration/api/test_health.py \
  tests/integration/api/test_run_api.py \
  -v
```

Expected: PASS.

- [ ] **Step 8: Static + broader regression**

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest tests/integration/api tests/unit/runtime/test_api_runtime.py -q -rs
```

Expected: GREEN with only explicit environment-gated skips.

- [ ] **Step 9: Commit Task 3**

```bash
git add \
  src/project_agent/main.py \
  src/project_agent/api/dependencies.py \
  src/project_agent/api/v1/runs.py \
  tests/integration/observability/__init__.py \
  tests/integration/observability/test_api_metrics.py

git commit -m "feat(ws6): instrument api requests"
```

---

## Task 4: Worker Context, Process-Local Metrics Server, and Queue Telemetry

**Files:**
- Modify: `src/project_agent/runtime/worker.py`
- Modify: `src/project_agent/workers/main.py`
- Modify: `src/project_agent/infrastructure/jobs/postgres.py`
- Modify: `src/project_agent/observability/metrics.py`
- Test: `tests/unit/runtime/test_worker_runtime.py`
- Test: `tests/unit/workers/test_worker.py`
- Create: `tests/integration/observability/test_queue_metrics_postgres.py`
- Regression: `tests/integration/jobs/test_claim.py`
- Regression: `tests/reliability/test_worker_crash.py`

**Interfaces:**
- Consumes: Task 2 `ObservabilityMetrics`, Worker metrics settings, `TokenCostPolicy`.
- Produces: Worker registry/server lifecycle, job context isolation, queue claim/age/completion/retry/final-failure/reaper metrics and safe queue events.

- [ ] **Step 1: Write RED Worker context/server lifecycle tests**

Extend `tests/unit/runtime/test_worker_runtime.py` so test Settings use `worker_metrics_enabled=False` unless the test is explicitly about the server. Add `test_worker_runtime_owns_metrics_server_lifecycle`: keep the valid configured port (for example `9101`), monkeypatch `project_agent.runtime.worker.start_metrics_http_server` with a fake factory returning a fake `MetricsHttpServerHandle`, build the runtime through the existing `build_worker_runtime()` factory using the test graph-executor factory, assert the factory received the Worker registry/host/port exactly once, and assert the fake handle's `close()` was called when the runtime context exits. This proves lifecycle ownership without opening a real socket or weakening the Settings constraint to allow port `0`.

Add a `BackgroundWorker` test that concurrently processes two fake jobs and captures structlog context inside handlers; assert each handler sees its own `job_id`, `job_type`, and `attempt_count` and neither value leaks after `_process` returns.

- [ ] **Step 2: Write RED PostgreSQL queue-observation tests**

Create `tests/integration/observability/test_queue_metrics_postgres.py` under the existing `RUN_POSTGRES_INTEGRATION=1` gate. With an isolated `ObservabilityMetrics`, construct `PostgresJobQueue(..., metrics=metrics)` and prove:

```text
claim -> queue_claims_total + queue_age_seconds
complete -> queue_completions_total
first failing attempt with attempts remaining -> queue_failures_total{outcome="retry"}
last failing attempt -> queue_failures_total{outcome="failed"}
expired lease with attempts remaining -> queue_reaped_total{outcome="retry"}
expired lease at max attempts -> queue_reaped_total{outcome="failed"}
```

Assert job IDs and `aggregate_id` values are absent from rendered metric labels.

- [ ] **Step 3: Run RED Worker + queue tests**

```bash
python -m pytest \
  tests/unit/runtime/test_worker_runtime.py \
  tests/unit/workers/test_worker.py \
  -v

export RUN_POSTGRES_INTEGRATION=1
python -m pytest tests/integration/observability/test_queue_metrics_postgres.py -v -rs
```

Expected: WS6-specific assertions fail because Worker/queue instrumentation is absent. The selected PostgreSQL test must not skip.

- [ ] **Step 4: Extend `PostgresJobQueue` with an optional metrics dependency without changing the port**

Add to the concrete constructor only:

```python
metrics: ObservabilityMetrics | None = None
```

Do not change `JobQueuePort` method signatures.

After `claim()` commits, for each claimed row record:

```python
age_seconds = max(0.0, (now - row.created_at).total_seconds())
metrics.observe_queue_claim(job_type=row.job_type, age_seconds=age_seconds)
```

After `complete()` commits, record completion using `row.job_type`.

In `fail()`, use the queue's already-decided post-update state to choose exactly one bounded outcome:

```text
PENDING -> retry
FAILED  -> failed
```

Record only after commit. Do not recalculate retry policy in observability code.

In `reap_expired()`, accumulate `(job_type, outcome)` counts while applying the existing row logic, commit once, then increment metrics by those counts. Do not change the returned integer count.

- [ ] **Step 5: Bind/clear Worker job context without assuming every aggregate is a Run**

Extend `BackgroundWorker.__init__()` with optional:

```python
metrics: ObservabilityMetrics | None = None
cost_policy: TokenCostPolicy | None = None
```

For each `_process(job)`:

```text
clear log context
bind service=worker, job_id, job_type, attempt_count
if job_type is EXECUTE_AGENT_RUN or RESUME_AGENT_RUN: bind run_id=aggregate_id
enter metrics_context when metrics exists
enter cost_policy_context(explicit policy or unconfigured policy)
run existing heartbeat + handler + fail/complete flow unchanged
clear log context in finally
```

Emit `job_claimed` at process start and `job_completed` after successful queue completion. Queue code emits `job_retry_scheduled`, `job_failed`, and `job_reaped` because only the queue owns those decisions. Error logs contain `error_type=type(exc).__name__`, never `str(exc)`.

- [ ] **Step 6: Own Worker logging/metrics-server lifecycle in `build_worker_runtime()`**

Call `configure_structured_logging(log_level=settings.log_level)` before the Worker emits WS6 lifecycle logs. Construct one Worker `ObservabilityMetrics()` and one `TokenCostPolicy` from Settings. Pass the same metrics object to `PostgresJobQueue` and `BackgroundWorker`.

If `worker_metrics_enabled` is true:

```python
metrics_server = start_metrics_http_server(
    metrics=metrics,
    host=settings.worker_metrics_host,
    port=settings.worker_metrics_port,
)
```

Extend `WorkerRuntime` with `metrics: ObservabilityMetrics` and `metrics_server: MetricsHttpServerHandle | None`. In the existing `finally`, stop Worker first, close graph executor as today, close metrics server, then dispose engine. Do not alter polling/heartbeat/lease timing.

- [ ] **Step 7: Run targeted GREEN tests**

```bash
python -m pytest \
  tests/unit/runtime/test_worker_runtime.py \
  tests/unit/workers/test_worker.py \
  tests/reliability/test_worker_crash.py \
  -v

export RUN_POSTGRES_INTEGRATION=1
python -m pytest \
  tests/integration/observability/test_queue_metrics_postgres.py \
  tests/integration/jobs/test_claim.py \
  -v -rs
```

Expected: all selected tests PASS with zero selected PostgreSQL skips.

- [ ] **Step 8: Static + broader Worker regression**

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest tests/unit/workers tests/unit/runtime/test_worker_runtime.py tests/reliability -q -rs
```

Expected: GREEN.

- [ ] **Step 9: Commit Task 4**

```bash
git add \
  src/project_agent/runtime/worker.py \
  src/project_agent/workers/main.py \
  src/project_agent/infrastructure/jobs/postgres.py \
  src/project_agent/observability/metrics.py \
  tests/unit/runtime/test_worker_runtime.py \
  tests/unit/workers/test_worker.py \
  tests/integration/observability/test_queue_metrics_postgres.py

git commit -m "feat(ws6): instrument worker and queue"
```

---

## Task 5: Run Lifecycle Metrics and Atomic Durable Cost Telemetry

**Files:**
- Modify: `src/project_agent/application/services/run_execution.py`
- Modify: `src/project_agent/infrastructure/db/repositories/qa_graph.py`
- Test: `tests/unit/runtime/test_run_execution_service.py`
- Test: `tests/unit/runtime/test_qa_graph_store_query.py`
- Create: `tests/integration/observability/test_run_telemetry_postgres.py`
- Regression: `tests/integration/workers/test_run_worker_postgres.py`
- Regression: `tests/integration/workers/test_run_resume_postgres.py`

**Interfaces:**
- Consumes: current metrics/cost-policy contexts bound by Task 4.
- Produces: Run start/wait/terminal structured events, exactly-once terminal Run metrics, cumulative token/cost persistence, retrieval-round counter at the existing durable increment seam.

- [ ] **Step 1: Write RED exactly-once Run terminal metric tests**

Extend `tests/unit/runtime/test_run_execution_service.py` using the existing fake repository and a bound `ObservabilityMetrics` context. Prove:

```python
with metrics_context(metrics):
    first = await service.persist_outcome(run_id, succeeded_outcome)
    second = await service.persist_outcome(run_id, succeeded_outcome)

assert first.status is RunStatus.SUCCEEDED
assert second.status is RunStatus.SUCCEEDED
# rendered counter for business_mode="qa", outcome="succeeded" is exactly 1
```

Also cover `refused`, `cancelled`, `mark_final_failure`, and prove `WAITING_CONFIRMATION` emits a log but does not increment terminal Run count.

- [ ] **Step 2: Write RED PostgreSQL cumulative token/cost test**

Create `tests/integration/observability/test_run_telemetry_postgres.py`. Seed a Run using existing repository helpers, bind:

```python
TokenCostPolicy(
    input_microunits_per_million_tokens=333_333,
    output_microunits_per_million_tokens=777_777,
    currency="USD",
)
```

Call `SqlAlchemyQAGraphStore.record_llm_usage()` twice in the same Run, commit, then query `AgentRunModel` and assert:

```text
input_tokens = first_input + second_input
output_tokens = first_output + second_output
total_tokens = input + output
estimated_cost_microunits = (
    cumulative_input * 333_333 + cumulative_output * 777_777
) // 1_000_000
cost_currency = USD
```

Add a second Run under `TokenCostPolicy.unconfigured("USD")` and prove estimate remains zero.

- [ ] **Step 3: Run RED tests**

```bash
python -m pytest tests/unit/runtime/test_run_execution_service.py -v

export RUN_POSTGRES_INTEGRATION=1
python -m pytest tests/integration/observability/test_run_telemetry_postgres.py -v -rs
```

Expected: WS6 metric/cost assertions fail; selected PostgreSQL test does not skip.

- [ ] **Step 4: Instrument Run lifecycle only after authoritative state transitions**

In `_require_run()`, after loading the durable Run, bind:

```python
run_id=str(run.id)
project_id=str(run.project_id)
user_id=str(run.user_id)
business_mode=run.business_mode.value
```

In `prepare_execute()` emit `run_started` only when the method actually performs the `QUEUED -> RUNNING` lifecycle transition. Resume does not create a second start timestamp.

In `persist_outcome()`:

- keep the existing early return for terminal/WAITING Runs before any terminal metric;
- emit `run_waiting_confirmation` after durable WAITING state/event writes;
- for terminal outcomes, persist lifecycle + event exactly as today, then compute duration from durable `started_at` and new `finished_at`, record one metric, and emit exactly one of `run_succeeded`, `run_refused`, `run_cancelled`.

In `mark_final_failure()`, preserve the terminal early return, then after durable failure state/event writes record `outcome="failed"` once and emit `run_failed` with bounded `error_type`/`error_code`, never an arbitrary provider body.

- [ ] **Step 5: Recompute cost atomically with cumulative token totals**

In `SqlAlchemyQAGraphStore.record_llm_usage()` after validating input and locking `AgentRunModel`:

```python
run.input_tokens += input_tokens
run.output_tokens += output_tokens
run.total_tokens += input_tokens + output_tokens
estimate = current_cost_policy().estimate(
    input_tokens=run.input_tokens,
    output_tokens=run.output_tokens,
)
run.estimated_cost_microunits = estimate.microunits
run.cost_currency = estimate.currency
```

Emit `llm_usage_recorded` with counts, `estimated_cost_microunits`, `currency`, and `cost_estimate_configured`; do not log prompt/response text.

Keep all changes in the same existing SQLAlchemy session/transaction; do not add a commit inside the repository method.

- [ ] **Step 6: Add retrieval-round metric at the existing durable seam**

Immediately after:

```python
run.retrieval_rounds += 1
```

record `current_metrics().increment_retrieval_round()` when a metrics context exists. Do not add Run/project labels.

- [ ] **Step 7: Run targeted GREEN + PostgreSQL regression**

```bash
python -m pytest \
  tests/unit/runtime/test_run_execution_service.py \
  tests/unit/runtime/test_qa_graph_store_query.py \
  -v

export RUN_POSTGRES_INTEGRATION=1
python -m pytest \
  tests/integration/observability/test_run_telemetry_postgres.py \
  tests/integration/workers/test_run_worker_postgres.py \
  tests/integration/workers/test_run_resume_postgres.py \
  -v -rs
```

Expected: all selected tests PASS with zero selected PostgreSQL skips.

- [ ] **Step 8: Static + broader regression**

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest tests/unit/runtime tests/integration/workers -q -rs
```

Expected: GREEN; environment-gated tests outside the explicitly enabled PostgreSQL set may skip.

- [ ] **Step 9: Commit Task 5**

```bash
git add \
  src/project_agent/application/services/run_execution.py \
  src/project_agent/infrastructure/db/repositories/qa_graph.py \
  tests/unit/runtime/test_run_execution_service.py \
  tests/unit/runtime/test_qa_graph_store_query.py \
  tests/integration/observability/test_run_telemetry_postgres.py

git commit -m "feat(ws6): persist run cost telemetry"
```

---

## Task 6: RAGFlow, Retrieval, and Frozen-WS4 Structured LLM Telemetry

**Files:**
- Modify: `src/project_agent/infrastructure/ragflow/client.py`
- Modify: `src/project_agent/observability/metrics.py`
- Modify: `src/project_agent/agent/graph.py`
- Test: `tests/contract/ragflow/test_http_client.py`
- Create: `tests/integration/observability/test_ragflow_telemetry.py`
- Create: `tests/integration/observability/test_llm_telemetry.py`
- Regression: frozen WS4 QA/LLM tests introduced by `ed6add6`.

**Interfaces:**
- Consumes: stable `StructuredLLMPort`, `StructuredLLMUsagePort`, `StructuredLLMRequest`, `LLMTokenUsage`; Task 2 metrics context.
- Produces: safe logical RAGFlow request telemetry, finite RAGFlow operation normalization, `ObservedStructuredLLM`, LLM request/token metrics and safe logs without provider-adapter changes.

- [ ] **Step 1: Write RED RAGFlow logical-request tests with deterministic `httpx.MockTransport`**

Extend `tests/contract/ragflow/test_http_client.py` to bind an `ObservabilityMetrics` and prove:

```text
GET /api/v1/datasets -> operation=dataset_list
POST /api/v1/datasets -> dataset_create
POST /api/v1/datasets/<dynamic>/documents -> document_upload
PUT /api/v1/datasets/<dynamic>/documents/<dynamic> -> document_metadata_update
POST /api/v1/datasets/<dynamic>/chunks -> parse_start
GET /api/v1/datasets/<dynamic>/documents -> document_list
DELETE /api/v1/datasets/<dynamic>/documents -> document_delete
POST /api/v1/retrieval -> retrieve
unknown path -> other
```

A request that gets a transient 500 then succeeds after retry increments one logical success, not one sample per HTTP attempt.

A terminal `RagflowHttpError`/`RagflowApiError` increments one error. Use a response body sentinel such as `RAGFLOW-PROVIDER-BODY-SENTINEL-b483` and assert it is absent from captured logs/metrics.

- [ ] **Step 2: Write RED Structured LLM decorator tests using existing fake ports**

In `tests/integration/observability/test_llm_telemetry.py` (offline by default; live test in the same file is environment-gated), construct `ObservedStructuredLLM(FakeStructuredLLM, FakeUsagePort)` and prove:

```python
response = await observed.generate(request, ResponseModel)
usage = await observed.get_usage(request.request_id)
```

produces exactly one `project_agent_llm_requests_total{model_alias="...",outcome="success"}` and token increments for `input`, `output`, `total`.

Add generation-failure and usage-failure tests. The original exception object/type must propagate unchanged and `LLM-PROVIDER-BODY-SENTINEL-17af` must not appear in logs or metrics.

- [ ] **Step 3: Run RED provider tests**

```bash
python -m pytest \
  tests/contract/ragflow/test_http_client.py \
  tests/integration/observability/test_llm_telemetry.py \
  -v -rs
```

Expected: WS6 telemetry assertions fail before implementation; offline LLM tests run without requiring provider credentials.

- [ ] **Step 4: Instrument `RagflowHttpClient.request_data()` as one logical provider request**

Add a finite `_ragflow_operation(method: str, path: str) -> str` matcher in `client.py` using method + path shape only. Never expose the raw path as a label or log field.

Wrap the entire existing `request_data()` behavior, including `_request()` retries and API-envelope validation:

```text
start monotonic timer
try existing request + envelope parsing
except BaseException:
    observe operation/error/full logical latency
    log ragflow_request_failed with provider=ragflow, operation, safe_error_fields
    re-raise same exception
else:
    observe operation/success/full logical latency
    log ragflow_request_completed
    return original data
```

Do not move or duplicate retry logic and do not log `_api_key`, payload, raw URL, response text, `.message`, or `str(exc)`.

- [ ] **Step 5: Implement `ObservedStructuredLLM` in `observability/metrics.py`**

Store pending logical requests by `request_id` with only:

```text
model_alias
start_ns
```

On `generate()`:

- validate/delegate exactly as the frozen port does;
- on exception: pop pending state, record one error + latency, emit safe `llm_request_failed`, re-raise unchanged;
- on success: leave pending state for the immediately-following usage call and return the exact structured result unchanged.

On `get_usage()`:

- delegate to the frozen usage port;
- on error: pop pending state, record one error + latency, emit safe failure, re-raise unchanged;
- on success: pop pending state, record one success + full latency, increment input/output/total token counters, emit `llm_request_completed` and `llm_usage_recorded`, return the exact usage unchanged.

Do not store prompt/response content in pending observation state.

- [ ] **Step 6: Wrap the stable WS4 ports in `build_project_qa_graph()`**

At graph construction time create one wrapper:

```python
observed_llm = ObservedStructuredLLM(deps.llm, deps.llm_usage)
```

Pass `observed_llm` as both `llm` and `llm_usage` to `generate_answer_node()` and `revise_answer_node()`. Do not change `QAGraphDependencies`, provider adapter construction, request IDs, model alias selection, prompt composition, revision count, or response validation.

- [ ] **Step 7: Run targeted GREEN provider/QA regression**

```bash
python -m pytest \
  tests/contract/ragflow/test_http_client.py \
  tests/integration/observability/test_llm_telemetry.py \
  tests/unit/agent \
  -v -rs
```

Also run the WS4 tests identified by:

```bash
git show --name-only --format='' ed6add6 | grep '^tests/' | sort -u
```

Then execute those existing WS4 test files with `python -m pytest <paths> -v -rs`. Expected: frozen WS4 behavior remains GREEN.

- [ ] **Step 8: Run real RAGFlow success-path telemetry gate**

```bash
export RUN_RAGFLOW_INTEGRATION=1
python -m pytest \
  tests/integration/ragflow/test_project_isolation.py \
  tests/integration/issues/test_issue_evidence_ragflow.py \
  tests/integration/observability/test_ragflow_telemetry.py \
  -v -rs
```

Expected: all selected RAGFlow tests PASS with zero selected skips. The WS6 test asserts a real successful provider call increments only bounded operation/outcome metrics; it does not intentionally destabilize RAGFlow to test failure behavior.

- [ ] **Step 9: Run real Structured LLM telemetry gate**

Use the WS4 branch's existing live-integration environment flag and existing live Structured LLM test as the source of truth for provider configuration. Discover the exact existing flag/test with:

```bash
rg -n "RUN_.*LLM|LLM.*INTEGRATION|skip.*LLM|structured.*llm" tests src/project_agent | head -80
```

Run the existing WS4 live test together with the live-marked case in `tests/integration/observability/test_llm_telemetry.py`. Expected: a real structured call records bounded latency/request metrics and provider-returned token usage. Explicit WS6 token-price env values may be set for cost testing; no provider price is inferred. A skip means the LLM live gate remains incomplete.

- [ ] **Step 10: Static + broader regression**

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest tests/contract/ragflow tests/unit/agent tests/integration/observability/test_llm_telemetry.py -q -rs
```

Expected: GREEN.

- [ ] **Step 11: Commit Task 6**

```bash
git add \
  src/project_agent/infrastructure/ragflow/client.py \
  src/project_agent/observability/metrics.py \
  src/project_agent/agent/graph.py \
  tests/contract/ragflow/test_http_client.py \
  tests/integration/observability/test_ragflow_telemetry.py \
  tests/integration/observability/test_llm_telemetry.py

git commit -m "feat(ws6): instrument ragflow and llm"
```

---

## Task 7: Citation, Authorization, and Issue Safety/Outcome Telemetry

**Files:**
- Modify: `src/project_agent/agent/nodes/citation_guard.py`
- Modify: `src/project_agent/application/services/authorization.py`
- Modify: `src/project_agent/application/services/runs.py`
- Modify: `src/project_agent/application/services/issue_confirmation.py`
- Modify: `src/project_agent/application/services/issue_creation.py`
- Test: `tests/unit/agent/test_citation_guard.py`
- Test: `tests/unit/issues/test_confirmation.py`
- Test: `tests/unit/issues/test_idempotent_create.py`
- Test: `tests/security/test_issue_permission_recheck.py`
- Test: `tests/security/test_cancelled_issue_create.py`
- Test: `tests/security/test_unconfirmed_issue_create.py`

**Interfaces:**
- Consumes: `current_metrics()`, safe log helpers, existing domain decisions only.
- Produces: citation `pass/revision/refusal`, authorization bounded reasons, Issue confirmation and create/reconciliation outcomes.

- [ ] **Step 1: Write RED Citation Guard route-observation tests**

Extend `tests/unit/agent/test_citation_guard.py` at node level, not only `CitationGuard.validate()`. Bind metrics and prove:

```text
valid -> citation_guard_total{outcome="pass"}
first invalid with revision_count=0 -> outcome="revision"
invalid with revision_count=1 -> outcome="refusal"
```

The result state's existing `route` and `last_error_code` must be unchanged.

- [ ] **Step 2: Write RED authorization-reason tests**

Extend existing authorization/Run service tests to prove only these bounded reasons are emitted:

```text
no_active_membership
scope_mismatch
actor_mismatch
role_denied
```

At minimum cover:

- `AuthorizationService.authorize_project()` missing membership -> `no_active_membership`;
- Run company/thread scope mismatch -> `scope_mismatch`;
- resume by a different actor -> `actor_mismatch`;
- Issue role rejected by `IssueWritePolicy` -> `role_denied`.

Do not derive `reason` from `str(exc)`.

- [ ] **Step 3: Write RED Issue confirmation/create outcome tests**

Extend `tests/unit/issues/test_confirmation.py` for:

```text
CONFIRM -> confirmed
CANCEL -> cancelled
expired -> expired
payload mismatch -> payload_mismatch
```

Extend `tests/unit/issues/test_idempotent_create.py` and reliability/security tests for:

```text
CREATED -> created
ALREADY_CREATED -> already_created
PENDING_RECONCILIATION -> pending_reconciliation
RECONCILED -> reconciled
permission/confirmation/write-policy denial -> denied
```

Assert provider `issue_key`, request ID, payload hash, and exception message do not become metric labels.

- [ ] **Step 4: Run RED tests**

```bash
python -m pytest \
  tests/unit/agent/test_citation_guard.py \
  tests/unit/issues/test_confirmation.py \
  tests/unit/issues/test_idempotent_create.py \
  tests/security/test_issue_permission_recheck.py \
  tests/security/test_cancelled_issue_create.py \
  tests/security/test_unconfirmed_issue_create.py \
  -v
```

Expected: only new telemetry assertions fail.

- [ ] **Step 5: Instrument Citation Guard at the routing point**

In `citation_guard_node()` after the existing guard result and before each return:

```text
valid -> observe_citation(pass) + citation_guard_passed
first invalid -> observe_citation(revision) + citation_guard_revision
final invalid -> observe_citation(refusal) + citation_guard_refused
```

Do not log draft text, Evidence content, citations, or validation error strings; counts/route/error code are sufficient.

- [ ] **Step 6: Instrument authorization at the exact decision branches**

Before existing raises only:

```text
AuthorizationService membership None -> no_active_membership
RunApplicationService company/thread scope mismatch -> scope_mismatch
RunApplicationService resume actor mismatch -> actor_mismatch
IssueWritePolicy denied -> role_denied
```

Use `current_metrics()` and `authorization_denied` with `reason` only. Keep original exception type/message for business/API behavior; do not serialize the message into observability.

- [ ] **Step 7: Instrument Issue confirmation after/at authoritative decisions**

In `IssueConfirmationService.record_decision()`:

- immediately before raising expired -> record `expired`;
- immediately before raising payload mismatch -> record `payload_mismatch`;
- after confirmation and draft status persistence completes -> record `confirmed` or `cancelled` and emit `issue_confirmation_recorded`.

Do not record `confirmed/cancelled` before persistence succeeds.

- [ ] **Step 8: Instrument Issue create/reconcile without moving the safety barriers**

Keep the existing confirmation, actor, hash, draft-state, authorization, role, idempotency, provider, and reconciliation order exactly unchanged.

Use one helper local to `issue_creation.py` that records/logs an `IssueCreationOutcome.status` after each successful outcome is known:

```text
CREATED -> created
ALREADY_CREATED -> already_created
PENDING_RECONCILIATION -> pending_reconciliation
RECONCILED -> reconciled
```

For `IssueCreationDenied` paths, record `denied` immediately before the existing raise or in a narrow wrapper that catches only `IssueCreationDenied`, records once, and re-raises the same exception. Do not count provider `TimeoutError/OSError` as denied; those already become `pending_reconciliation` under frozen WS5 semantics.

- [ ] **Step 9: Run targeted GREEN + frozen security regression**

```bash
python -m pytest \
  tests/unit/agent/test_citation_guard.py \
  tests/unit/issues/test_confirmation.py \
  tests/unit/issues/test_idempotent_create.py \
  tests/security/test_issue_permission_recheck.py \
  tests/security/test_cancelled_issue_create.py \
  tests/security/test_unconfirmed_issue_create.py \
  tests/reliability/test_issue_response_lost.py \
  -v
```

Expected: PASS and all existing WS5 side-effect counts remain unchanged.

- [ ] **Step 10: Static + broader regression**

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest tests/unit/agent tests/unit/issues tests/security tests/reliability -q -rs
```

Expected: GREEN.

- [ ] **Step 11: Commit Task 7**

```bash
git add \
  src/project_agent/agent/nodes/citation_guard.py \
  src/project_agent/application/services/authorization.py \
  src/project_agent/application/services/runs.py \
  src/project_agent/application/services/issue_confirmation.py \
  src/project_agent/application/services/issue_creation.py \
  tests/unit/agent/test_citation_guard.py \
  tests/unit/issues/test_confirmation.py \
  tests/unit/issues/test_idempotent_create.py \
  tests/security/test_issue_permission_recheck.py \
  tests/security/test_cancelled_issue_create.py \
  tests/security/test_unconfirmed_issue_create.py

git commit -m "feat(ws6): instrument safety and issue outcomes"
```

---

## Task 8: End-to-End Sanitization, Live Acceptance, and WS6 Completion Evidence

**Files:**
- Create: `tests/security/test_observability_sanitization.py`
- Modify only if a failing approved assertion identifies a WS6 implementation defect in files already owned by Tasks 1–7.
- Create after all gates pass: `docs/superpowers/plans/2026-09-19-ws6-observability-run-telemetry-completed.md`

**Interfaces:**
- Consumes: complete WS6 implementation and all live environments.
- Produces: executable proof that observability is safe/bounded and a completion record; no new feature surface.

- [ ] **Step 1: Write the cross-cutting security regression before final closure**

Create `tests/security/test_observability_sanitization.py` with unique sentinels for every frozen sensitive class:

```python
SENTINELS = {
    "jwt": "JWT-SENTINEL-99321",
    "ragflow_api_key": "RAGFLOW-KEY-SENTINEL-44218",
    "llm_api_key": "LLM-KEY-SENTINEL-77103",
    "password": "PASSWORD-SENTINEL-81644",
    "query": "QUERY-SENTINEL-20953",
    "evidence": "EVIDENCE-SENTINEL-54197",
    "answer": "ANSWER-SENTINEL-73510",
    "system_prompt": "SYSTEM-PROMPT-SENTINEL-10422",
    "user_prompt": "USER-PROMPT-SENTINEL-60817",
    "provider_body": "PROVIDER-BODY-SENTINEL-33804",
    "issue_key": "ISSUE-KEY-SENTINEL-44001",
    "document_id": "DOCUMENT-ID-SENTINEL-55002",
    "user_id": "USER-ID-SENTINEL-66003",
    "run_id": "RUN-ID-SENTINEL-77004",
}
```

Required assertions:

- credential/content sentinels do not occur in captured JSON logs;
- provider-body sentinel does not occur in provider-failure logs;
- issue/document/user/run sentinels do not occur as Prometheus label values;
- `run_id`/`user_id` are allowed only in explicitly constructed contextual logs, never metric labels;
- safe fields (`event`, `outcome`, `duration_ms`, `error_type`, bounded reason/operation) remain present so sanitization does not destroy diagnostics.

- [ ] **Step 2: Run the full offline security + test suite**

```bash
python -m pytest tests/security/test_observability_sanitization.py -v
ruff check src tests
mypy src
git diff --check
python -m pytest -q -rs
```

Expected: all tests PASS except explicit live environment gates. If a new failure appears, use `superpowers:systematic-debugging`; do not weaken sanitization assertions to make the suite green.

- [ ] **Step 3: Verify schema remains unchanged**

```bash
alembic current
alembic heads
git diff --name-only 5123efbaa3821f34a6198cdebadd4631f8bceeef -- alembic alembic.ini
```

Expected:

```text
0005_run_runtime_envelope (head)
0005_run_runtime_envelope (head)
```

and no new migration file from WS6.

- [ ] **Step 4: Run the mandatory PostgreSQL WS6 live closure**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

python -m pytest \
  tests/integration/db/test_postgres_schema.py \
  tests/integration/api/test_run_api_postgres.py \
  tests/integration/jobs/test_claim.py \
  tests/integration/workers/test_run_worker_postgres.py \
  tests/integration/workers/test_run_resume_postgres.py \
  tests/integration/issues/test_issue_run_runtime_postgres.py \
  tests/integration/observability/test_queue_metrics_postgres.py \
  tests/integration/observability/test_run_telemetry_postgres.py \
  -v -rs
```

Expected: zero selected skips and zero failures.

- [ ] **Step 5: Run the mandatory RAGFlow WS6 live closure**

```bash
export RUN_RAGFLOW_INTEGRATION=1
python -m pytest \
  tests/integration/ragflow/test_project_isolation.py \
  tests/integration/issues/test_issue_evidence_ragflow.py \
  tests/integration/observability/test_ragflow_telemetry.py \
  -v -rs
```

Expected: zero selected skips and zero failures.

- [ ] **Step 6: Run the mandatory frozen-WS4 Structured LLM live closure**

First locate the exact WS4 live gate already integrated by Task 0:

```bash
rg -n "RUN_.*LLM|LLM.*INTEGRATION|skip.*LLM|structured.*llm" tests src/project_agent | head -80
```

Then run that existing WS4 live test plus `tests/integration/observability/test_llm_telemetry.py` with the same live environment enabled. Expected: zero selected live skips and zero failures; a real provider-returned usage value is reflected in WS6 LLM token metrics and durable Run token/cost telemetry. If provider pricing is needed for the cost assertion, set explicit integer WS6 rates in the environment; never derive them from the provider/model name.

- [ ] **Step 7: Exercise API and Worker scrape surfaces manually without business payloads**

API, using the normal project launch path:

```bash
uv run uvicorn project_agent.main:app --host 127.0.0.1 --port 8000
```

In another shell:

```bash
curl -fsS http://127.0.0.1:8000/metrics | grep '^project_agent_'
```

Expected: WS6 metric families are rendered and no credential/query/Evidence/answer content appears.

For the Worker process-local surface, run the exact runtime-lifecycle acceptance added in Task 4:

```bash
python -m pytest \
  tests/unit/runtime/test_worker_runtime.py::test_worker_runtime_owns_metrics_server_lifecycle \
  -v
```

Expected: PASS. This proves the production Worker runtime owns a separate process-local HTTP metrics server lifecycle without introducing a second Worker CLI. API `/metrics` and the Worker server use distinct registries and scrape surfaces.

- [ ] **Step 8: Run final verification-before-completion commands from a clean shell**

Invoke `superpowers:verification-before-completion`, then execute:

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest -q -rs
alembic current
alembic heads
git status --short
git diff --stat 5123efbaa3821f34a6198cdebadd4631f8bceeef
git diff --name-only 5123efbaa3821f34a6198cdebadd4631f8bceeef
```

Expected: static gates GREEN, full suite has zero failures, schema remains `0005_run_runtime_envelope`, and all required live gates from Steps 4–6 were separately proven with zero selected skips.

- [ ] **Step 9: Write the WS6 completion record only after every required gate is GREEN**

Create `docs/superpowers/plans/2026-09-19-ws6-observability-run-telemetry-completed.md` containing:

```text
WS6 start/final HEAD
Task commit list
Ruff result
MyPy result
full pytest result
PostgreSQL live result
RAGFlow live result
Structured LLM live result
Alembic current/head
sanitization proof summary
metric cardinality proof summary
cost configured/unconfigured proof summary
known limitations (only if still within frozen WS6 acceptance)
```

Do not write `COMPLETE` if PostgreSQL, RAGFlow, or required LLM selected tests skipped.

- [ ] **Step 10: Commit the final WS6 verification artifacts**

```bash
git add \
  tests/security/test_observability_sanitization.py \
  docs/superpowers/plans/2026-09-19-ws6-observability-run-telemetry-completed.md

git commit -m "docs(ws6): record observability acceptance"
```

- [ ] **Step 11: Only after the entire WS6 branch is GREEN, use branch-finishing workflow**

Invoke `superpowers:finishing-a-development-branch`. Do not invoke it when any required live gate is incomplete.

**Final stage report:**

```text
需求完成：✅ only when every frozen WS6 acceptance criterion is implemented
测试闭环：✅ only when offline + PostgreSQL + RAGFlow + required LLM gates are GREEN with zero selected skips
新 bug：未发现 / 已发现：...
```

---

# Task Dependency Graph

```text
Pre-Implementation Gate
        ↓
Task 0 — Frozen WS4 integration + regression
        ↓
Task 1 — JSON logging + sanitization
        ↓
Task 2 — Prometheus registry + cost policy/settings
        ↓
Task 3 — API logging/metrics + /metrics
        ↓
Task 4 — Worker/queue telemetry + Worker metrics server
        ↓
Task 5 — Run lifecycle + durable token/cost telemetry
        ↓
Task 6 — RAGFlow/retrieval + frozen-WS4 LLM telemetry
        ↓
Task 7 — Citation/Auth/Issue outcome telemetry
        ↓
Task 8 — security + live acceptance + completion evidence
```

Tasks 3–7 use the foundation from Tasks 1–2. Task 6 must not execute before Task 0 has integrated frozen WS4. Task 8 is verification/closure and must not be used to hide missing tests from earlier tasks.

# Implementation Discipline per Task

At the start of each coding task, print:

```text
是否需要使用 Superpowers：是
使用 skill：test-driven-development
原因：当前任务开始 production implementation，必须先写并确认 RED。
```

For an unexpected failure, switch before changing code:

```text
是否需要使用 Superpowers：是
使用 skill：systematic-debugging
原因：出现非预期 test/runtime failure，需要先定位根因而不是直接修补。
```

At the end of each task, print:

```text
需求完成：✅ / ❌ / ⏳
测试闭环：✅ / ❌ / ⚠️
新 bug：未发现 / 已发现：...
```

No task is complete merely because production code exists.

# Plan Self-Review Record

## Spec coverage

PASS. The plan maps every frozen Design acceptance area to an owning task:

- JSON/context logging + sanitization -> Tasks 1, 3, 4, 5, 6, 7, 8
- API metrics endpoint/HTTP latency -> Task 3
- Worker process-local endpoint -> Task 4
- queue claim/completion/retry/failure/reaper/age -> Task 4
- Run terminal outcome/duration -> Task 5
- retrieval rounds -> Task 5
- durable token/cost policy -> Tasks 2, 5
- RAGFlow latency/error -> Task 6
- LLM latency/error/tokens -> Task 6
- citation outcomes -> Task 7
- authorization denials -> Task 7
- Issue confirmation/create/reconciliation -> Task 7
- no OCR inference -> Global Constraints + no OCR implementation task
- PostgreSQL/RAGFlow/LLM live closure -> Task 8
- no migration -> Preflight + Task 8 schema check

## Placeholder scan

PASS. The plan contains no unresolved implementation marker. The only runtime discovery command is for the already-existing WS4 live-integration environment flag/test because the uploaded WS6 start package does not contain the WS4 branch tree; the implementation target itself remains the exact frozen ports and graph file already present in the source package.

## Type/interface consistency

PASS. `ObservabilityMetrics`, `TokenCostPolicy`, their contexts, log helpers, and `ObservedStructuredLLM` are defined once in the Public WS6 Interfaces section and reused consistently by later tasks.

## Review-focus coverage

PASS. All five Review Focus failure modes have explicit tests in Tasks 1, 2/3, 5, 6, and 8.

## Frozen-contract collision review

PASS at plan level. No task changes Run API schema, queue policy formulas, WS4 provider semantics, or WS5 confirmation/idempotency/provider payload behavior. Task 0 isolates the only cross-workstream merge risk before WS6 implementation begins.

## Migration review

PASS. No migration is planned. Any attempt to add one must stop execution and return to Design Review with the failing approved requirement as evidence.

# Execution Handoff

Plan complete at:

```text
docs/superpowers/plans/2026-09-19-ws6-observability-run-telemetry.md
```

Do not start Task 0 or production coding until this plan has been reviewed and explicitly approved.

Recommended execution mode: **Native** if this same high-capability coding session will execute all tasks, because Tasks 1–7 share a small set of cross-cutting interfaces (`ObservabilityMetrics`, contexts, logging, cost policy) and preserving those names across tasks reduces integration drift. Use a fresh whole-branch reviewer before Task 8 closure. If a true subagent facility with fresh reviewer gates is available and cost is acceptable, subagent-driven execution is also valid.
