# WS2 Run API + Agent Event + SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the authorized, durable V1 Run HTTP envelope: create/read Runs, persist ordered Agent Events, stream reconnectable SSE, durably record resume input, and atomically enqueue the corresponding PostgreSQL jobs without executing LangGraph.

**Architecture:** Reuse WS1's FastAPI lifespan, request-scoped `AsyncSession`, JWT identity dependency, and current-membership `AuthorizationService`. Add a focused Run domain/application boundary plus a SQLAlchemy Run repository; write Run/Event/Job records through the same request session so the request-level commit/rollback is the transaction boundary. SSE reads persisted `agent_events` ordered by per-run `sequence_no`; `/resume` only validates/persists compatible resume input and enqueues `RESUME_AGENT_RUN`, leaving LangGraph execution to WS3.

**Tech Stack:** Python 3.12, FastAPI 0.141.x from `uv.lock`, Pydantic, SQLAlchemy asyncio + asyncpg, PostgreSQL + Alembic, existing PostgreSQL Job Queue tables, existing JWT/authorization services, pytest/pytest-asyncio, Ruff, MyPy.

**Spec:** `docs/superpowers/specs/2026-09-12-v1-completion-design.md`

## Completion Status

**Status:** ✅ **WS2 COMPLETE**

**Completed:** 2026-09-16

All seven original WS2 implementation tasks have been completed and verified. The implementation was executed in five delivery stages (Task A = original Tasks 1+2, Task B = original Tasks 3+4, Task C = original Task 5, Task D = original Task 6, Task E = original Task 7). The final live PostgreSQL acceptance gate executed successfully on the real server environment.

Final server evidence:

```text
ruff check src tests
→ All checks passed!

mypy src
→ Success: no issues found in 116 source files

full pytest with PostgreSQL live integration enabled
→ 268 passed, 1 skipped
→ the only remaining skip is tests/integration/ragflow/test_project_isolation.py
→ no WS2 PostgreSQL acceptance test is skipped
```

The single remaining RAGFlow skip is outside the WS2 Run API / Agent Event / SSE acceptance boundary and does not block WS2 completion.

## Global Constraints

- Keep the V1 architecture locked to FastAPI + LangGraph + PostgreSQL + PostgreSQL Job Queue + RAGFlow + `LocalFileObjectStoreAdapter` + `SandboxProjectTrackerAdapter`.
- Do not add Redis, ARQ, Celery, MinIO, a second vector database, multi-Agent orchestration, production Jira/禅道/飞书 writes, SaaS multi-tenancy, Kubernetes, GraphRAG, or RAPTOR.
- Do not rewrite Task 0–13. WS2 adds the Run Runtime Envelope around existing modules and makes only narrowly-scoped compatibility changes needed by the approved V1 Completion Design.
- The Run API requires explicit `project_id`; do not make `threads.project_id` or `agent_runs.project_id` nullable.
- JWT establishes identity only. Current `ProjectMembership` from PostgreSQL remains the authorization source for every protected Run operation.
- A forged JWT `role`, `project_ids`, company/project identifier, or similar claim must never grant Run access.
- Preserve WS1 `create_app()` testability, `runtime_factory`, FastAPI dependency overrides, and one request-scoped `AsyncSession`.
- Queue payloads remain aggregate-only. `background_jobs` stores the `run_id` in `aggregate_id`; query text and resume input stay in durable application tables/events.
- WS2 creates/enqueues `EXECUTE_AGENT_RUN` and `RESUME_AGENT_RUN` jobs but does not register or execute those handlers.
- WS2 does not implement real Structured LLM, QA retrieval grading, Issue Evidence-chain completion, observability, Docker/Compose completion, evaluation, or any WS3–WS8 responsibility.
- `agent_events` remain append-only and ordered by persisted per-run `sequence_no`.
- SSE is a projection of durable `agent_events`, not a second event store.
- Do not persist raw JWTs, API keys, provider response bodies, or other secrets in Run/Event payloads.
- A skipped PostgreSQL test is not a live PostgreSQL PASS.

---

## Source-of-Truth Preflight and WS1 Dependency Check

### Observed Git state in the reviewed WS1 ZIP

The reviewed archive contains `.git/` and reports:

```text
branch: fix/ws1-ruff-cleanup
HEAD:   8e36bdf chore: clean Ruff diagnostics
```

`git status --short --branch` is not clean: it contains the post-HEAD Ruff/type cleanup working tree plus the untracked WS1 completion document. This is **not a WS2 architecture blocker for planning**, because the reviewed working tree is the current code source of truth and the WS1 implementation capabilities below are present. It **is an execution preflight gate**: before Task 1 is implemented in the real server worktree, preserve/commit the verified WS1 state and begin WS2 from a clean branch/worktree so WS1 cleanup is not mixed into WS2 commits.

Before WS2 coding starts, run in `/home1/ckx/workspace/it-outsourcing-knowledge-agent`:

```bash
git status --short --branch
git log --oneline -15
```

Expected execution precondition:

```text
- the verified WS1 changes are preserved;
- WS1 documentation close-out is either committed or explicitly separated;
- WS2 implementation starts from a clean worktree or an isolated WS2 worktree;
- no unreviewed WS1 diff is accidentally included in a WS2 commit.
```

### WS1 capabilities WS2 may rely on

Current code plus `docs/superpowers/plans/2026-09-12-ws1-production-bootstrap-auth-completed.md` confirm the following foundation is implemented:

```text
production composition root                         : available
FastAPI lifespan                                    : available
request-scoped PostgreSQL AsyncSession              : available
Bearer JWT verification                             : available
JWT identity only (authorization claims discarded) : available
current ProjectMembership authorization             : available
server-derived authorization context                : available
runtime_factory/dependency override testability     : available
membership revocation checked on next request       : available
```

The WS1 completion evidence records:

```text
ruff check src tests                                : PASS
mypy src                                            : PASS
python -m pytest -q                                 : PASS
live PostgreSQL authorization/revocation gate       : 2 passed / 0 failed / 0 skipped
```

The completion document also records documentation/repository close-out items that were not yet folded into a clean final Git state in the reviewed ZIP. Those are operational preflight items, not a missing WS1 capability needed to plan WS2.

---

## Current State and Plan/Code Drift Review

### Reusable code already present

- `src/project_agent/infrastructure/db/models/schema.py`
  - `ThreadModel`
  - `AgentRunModel`
  - `AgentEventModel`
  - `BackgroundJobModel`
  - `ToolConfirmationModel`
- `agent_events` already has `UNIQUE(run_id, sequence_no)`, which supplies the persistence invariant required for reconnectable ordering.
- `background_jobs` already stores `job_type` + `aggregate_id` and deliberately has no arbitrary payload column.
- `src/project_agent/infrastructure/jobs/postgres.py` already supplies worker-side claim/lease/retry/reaper queue behavior.
- `src/project_agent/infrastructure/db/repositories/qa_graph.py` already demonstrates the correct per-run event sequencing primitive: lock the Run row, compute `max(sequence_no) + 1`, append the event.
- `src/project_agent/workers/handlers.py` already defines the string vocabulary `EXECUTE_AGENT_RUN` and `RESUME_AGENT_RUN`, but no production execute/resume handlers are wired; that remains WS3.
- `src/project_agent/agent/nodes/confirm_issue_create.py` already expects resume input containing `action` and `request_payload_hash`, and Task 13 binds confirmation to the original graph `user_id`.

### Drift that WS2 must resolve without changing the approved design

1. **No Run repository/application/API boundary exists.** The tables exist, but no production `POST /runs`, Run read, SSE, or resume path exists.
2. **`AgentRunModel` currently defaults to `RUNNING`.** A newly accepted asynchronous Run must begin as `QUEUED`; WS3 owns the transition to `RUNNING` when execution actually starts.
3. **`AgentRunModel.started_at` is currently non-null with a server `now()` default.** That makes a queued Run look started before a Worker executes it. WS2 needs a narrow migration making `started_at` nullable and removing that server default.
4. **`agent_runs` has no durable business-mode field.** The approved runtime must dispatch `qa`, `issue_lookup`, or `issue_create`. Add a nullable-on-migration `business_mode` column for legacy-row compatibility, while making it required for every WS2-created Run at the application boundary.
5. **`PostgresJobQueue.enqueue()` owns a new session and immediately commits.** It cannot participate in WS2's required `Run + initial event + BackgroundJob` request transaction. Add a same-session enqueue adapter; do not change worker claim/lease semantics.
6. **`SqlAlchemyQAGraphStore.load_query()` currently loads only a `USER_QUERY` event.** WS2 will make `RUN_QUEUED` the durable initial Run/input event, so the loader must accept `RUN_QUEUED` while retaining `USER_QUERY` compatibility for existing tests/data.
7. **FastAPI currently includes only health and document routers.** WS2 adds a Run router and reuses WS1 authentication/session dependencies.

### Blocker decision

No change to ADR-0004 or the approved V1 Completion Design is required. There is **no architecture/design blocker** to WS2 planning.

---

## Approved WS2 Architecture Boundary

WS2 implements only this path:

```text
Bearer JWT
  ↓
current ProjectMembership authorization
  ↓
Run application service
  ↓
Thread / AgentRun / AgentEvent
  ↓
same PostgreSQL transaction
  ↓
BackgroundJob(EXECUTE_AGENT_RUN or RESUME_AGENT_RUN, aggregate_id=run_id)
  ↓
HTTP Run read / reconnectable SSE
```

WS2 explicitly stops before:

```text
BackgroundJob
  ↓
Worker EXECUTE_AGENT_RUN / RESUME_AGENT_RUN handler
  ↓
LangGraph invoke / Command(resume=...)
```

### HTTP contract used by this Plan

```text
POST /api/v1/runs                         -> 201 Created
GET  /api/v1/runs/{run_id}               -> 200 OK
GET  /api/v1/runs/{run_id}/events        -> text/event-stream
POST /api/v1/runs/{run_id}/resume        -> 202 Accepted
```

`POST /api/v1/runs` request:

```json
{
  "project_id": "<uuid>",
  "business_mode": "qa | issue_lookup | issue_create",
  "query": "non-empty user input",
  "thread_id": "<optional existing uuid>"
}
```

`POST /api/v1/runs/{run_id}/resume` request for the V1 Issue confirmation interrupt:

```json
{
  "action": "confirm | cancel",
  "request_payload_hash": "<64-character sha256 hex>"
}
```

The API does not accept role/project authorization claims, a worker payload, a LangGraph command, or a Sandbox write request.

### Stable Run status vocabulary

```text
QUEUED
RUNNING
WAITING_CONFIRMATION
SUCCEEDED
REFUSED
CANCELLED
FAILED
```

### Stable Agent Event vocabulary introduced as the WS2 runtime contract

```text
RUN_QUEUED
RUN_STARTED
RUN_PROGRESS
ARTIFACT_AVAILABLE
WAITING_CONFIRMATION
RUN_RESUME_QUEUED
RUN_RESUMED
RUN_SUCCEEDED
RUN_REFUSED
RUN_CANCELLED
RUN_FAILED
```

WS2 itself emits `RUN_QUEUED` and `RUN_RESUME_QUEUED`. WS3+ may emit the remaining approved lifecycle events without changing the API/SSE vocabulary.

### SSE behavior

- `id:` is the persisted decimal `sequence_no`.
- `event:` is the persisted stable `event_type`.
- `data:` is JSON from the sanitized application event payload.
- Missing `Last-Event-ID` means `after_sequence = 0`.
- Valid `Last-Event-ID: N` replays only rows with `sequence_no > N`.
- Malformed or negative `Last-Event-ID` returns HTTP `400` before streaming begins.
- Events are emitted in ascending sequence order.
- A terminal event (`RUN_SUCCEEDED`, `RUN_REFUSED`, `RUN_CANCELLED`, `RUN_FAILED`) is emitted and then the stream closes.
- If reconnect begins after the terminal event has already been acknowledged, the stream closes without hanging.
- Correct cursor use prevents duplicate delivery. Across an ambiguous network disconnect before the client durably records the last ID, at-least-once replay is allowed; clients deduplicate by SSE `id`/`sequence_no`.
- Closing the HTTP connection only closes the stream/session; it never cancels or mutates the Run/BackgroundJob.

---

## File Map Locked for WS2

### Create

- `src/project_agent/domain/runs.py` — Run business modes, statuses, event types, durable Run/Thread/Event records, terminal helpers, and Run job-type constants.
- `src/project_agent/application/ports/run_repository.py` — repository contract for project-bound Threads, Runs, ordered Events, status transitions, waiting-confirmation lookup, and terminal-result projection.
- `src/project_agent/application/services/runs.py` — current-membership Run creation/read/resume application service; no LangGraph execution.
- `src/project_agent/infrastructure/db/repositories/runs.py` — SQLAlchemy implementation using one injected `AsyncSession` and run-row locking for event sequence allocation/state transitions.
- `src/project_agent/api/v1/runs.py` — Pydantic HTTP models, service dependencies, create/read/resume routes, SSE projection, cursor parsing, and controlled error mapping.
- `migrations/versions/0005_run_runtime_envelope.py` — add `agent_runs.business_mode`; make `agent_runs.started_at` nullable and remove its server default.
- `tests/fakes/run_repository.py` — deterministic in-memory repository used by application/SSE tests.
- `tests/unit/runtime/test_run_service.py` — application-service TDD for authorization, thread validation, creation, read, and resume semantics.
- `tests/unit/runtime/test_run_sse.py` — event ordering/cursor/terminal/disconnect generator tests.
- `tests/integration/api/test_run_api.py` — offline FastAPI contract/security tests with dependency overrides.
- `tests/integration/api/test_run_api_postgres.py` — opt-in real PostgreSQL transaction, authorization, revocation, and resume durability gate.

### Modify

- `src/project_agent/infrastructure/db/models/schema.py:400-450` — correct Run defaults/nullability and add `business_mode` mapping.
- `src/project_agent/application/ports/job_queue.py:9-45` — add a narrow enqueue-only protocol used by request transactions without changing the worker queue contract.
- `src/project_agent/infrastructure/jobs/postgres.py:55-95,219+` — add a same-session enqueue adapter/helper; retain `PostgresJobQueue` worker behavior.
- `src/project_agent/infrastructure/db/repositories/qa_graph.py:38-53` — accept the WS2 `RUN_QUEUED` durable initial-input event while retaining legacy `USER_QUERY` support.
- `src/project_agent/infrastructure/db/repositories/__init__.py` — export `SqlAlchemyRunRepository` if repository exports remain centralized.
- `src/project_agent/main.py:8-50` — include the new Run router; do not change runtime lifespan semantics.
- `tests/integration/db/test_schema.py` — assert new Run schema contract.
- `tests/integration/db/test_postgres_schema.py` — assert the migrated PostgreSQL Run columns/nullability.
- `tests/fakes/job_queue.py` — retain full fake queue behavior and add deterministic enqueue recording/failure injection only if needed by `test_run_service.py`.
- `tests/contract/test_job_queue_port.py` — verify `FakeJobQueue` still satisfies the full queue contract and the enqueue-only protocol.

### Explicitly Do Not Touch in WS2

```text
src/project_agent/workers/main.py
src/project_agent/workers/issue_reconciliation.py
src/project_agent/workers/retention.py
src/project_agent/agent/graph.py
src/project_agent/agent/issue_graph.py
src/project_agent/agent/nodes/execute_issue_create.py
src/project_agent/application/ports/llm.py
src/project_agent/application/services/issue_creation.py
src/project_agent/infrastructure/ragflow/**
compose.yaml
evaluation/**
```

`src/project_agent/agent/nodes/confirm_issue_create.py` is a read-only compatibility source for the resume payload contract in WS2; do not modify it in this workstream.

---

### Task 1: Freeze the Run/Event Domain Contract and Correct the Run Schema — ✅ COMPLETE

**Goal:** Establish the exact WS2 Run/status/event vocabulary and make the database capable of representing a queued-but-not-started Run with a durable business mode.

**Why:** The current tables exist, but `RUNNING` + non-null `started_at=now()` cannot represent the approved asynchronous Run lifecycle accurately, and the business mode is not persisted on the Run.

**Files:**
- Create: `src/project_agent/domain/runs.py`
- Create: `migrations/versions/0005_run_runtime_envelope.py`
- Modify: `src/project_agent/infrastructure/db/models/schema.py:400-450`
- Modify: `tests/integration/db/test_schema.py`
- Modify: `tests/integration/db/test_postgres_schema.py`
- Test: `tests/integration/db/test_schema.py`
- Test: `tests/integration/db/test_postgres_schema.py`
- Do not touch: Worker handlers, LangGraph graphs, API routes

**Interfaces:**
- Produces:

```python
class RunBusinessMode(StrEnum):
    QA = "qa"
    ISSUE_LOOKUP = "issue_lookup"
    ISSUE_CREATE = "issue_create"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    SUCCEEDED = "SUCCEEDED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class AgentEventType(StrEnum):
    RUN_QUEUED = "RUN_QUEUED"
    RUN_STARTED = "RUN_STARTED"
    RUN_PROGRESS = "RUN_PROGRESS"
    ARTIFACT_AVAILABLE = "ARTIFACT_AVAILABLE"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    RUN_RESUME_QUEUED = "RUN_RESUME_QUEUED"
    RUN_RESUMED = "RUN_RESUMED"
    RUN_SUCCEEDED = "RUN_SUCCEEDED"
    RUN_REFUSED = "RUN_REFUSED"
    RUN_CANCELLED = "RUN_CANCELLED"
    RUN_FAILED = "RUN_FAILED"


class RunJobType(StrEnum):
    EXECUTE = "EXECUTE_AGENT_RUN"
    RESUME = "RESUME_AGENT_RUN"
```

Also define frozen slot dataclasses in `domain/runs.py`:

```python
@dataclass(frozen=True, slots=True)
class ThreadRecord:
    id: UUID
    company_id: UUID
    project_id: UUID
    user_id: UUID
    title: str | None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: UUID
    thread_id: UUID
    company_id: UUID
    project_id: UUID
    user_id: UUID
    business_mode: RunBusinessMode
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    result_ref: str | None = None
    result_summary: str | None = None


@dataclass(frozen=True, slots=True)
class AgentEventRecord:
    id: UUID
    run_id: UUID
    sequence_no: int
    event_type: AgentEventType
    payload: dict[str, object]
    created_at: datetime | None = None
```

Define:

```python
TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.REFUSED, RunStatus.CANCELLED, RunStatus.FAILED}
)
TERMINAL_EVENT_TYPES = frozenset(
    {
        AgentEventType.RUN_SUCCEEDED,
        AgentEventType.RUN_REFUSED,
        AgentEventType.RUN_CANCELLED,
        AgentEventType.RUN_FAILED,
    }
)
```

- Consumes: existing UUID/datetime conventions and current SQLAlchemy models.

- [ ] **Step 1: Write the schema tests first**

Add to `tests/integration/db/test_schema.py`:

```python
def test_agent_runs_supports_ws2_runtime_envelope() -> None:
    table = Base.metadata.tables["agent_runs"]
    assert "business_mode" in table.columns
    assert table.columns["business_mode"].nullable is True
    assert table.columns["started_at"].nullable is True
```

Extend `tests/integration/db/test_postgres_schema.py` so the live inspector also returns column metadata for `agent_runs` and asserts:

```text
business_mode exists
started_at nullable == True
alembic_version == 0005_run_runtime_envelope after `alembic upgrade head`
```

Do not require legacy rows to have a non-null `business_mode`; the WS2 application service is the boundary that guarantees it for all new API-created Runs.

- [ ] **Step 2: Run the new schema tests and verify RED**

Run:

```bash
python -m pytest tests/integration/db/test_schema.py -v
```

Expected RED:

```text
FAIL because `agent_runs.business_mode` is absent and `started_at` is currently non-null.
```

If PostgreSQL is available, also run the live test before migration:

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
python -m pytest tests/integration/db/test_postgres_schema.py -v
```

Expected: FAIL against migration head `0004_issue_create_idempotency`. A skip is not live RED evidence.

- [ ] **Step 3: Implement the domain vocabulary**

Create `src/project_agent/domain/runs.py` with the exact enum values/dataclasses above. Validate persisted `business_mode`, `status`, and `event_type` by constructing the enums when mapping database rows; do not silently coerce unknown strings.

- [ ] **Step 4: Modify the ORM model**

Change `AgentRunModel` to:

```python
business_mode: Mapped[str | None] = mapped_column(String(32))
status: Mapped[str] = mapped_column(
    String(32),
    nullable=False,
    default=RunStatus.QUEUED.value,
    index=True,
)
started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
```

Import `RunStatus` from `project_agent.domain.runs`. Do not alter `project_id` nullability.

- [ ] **Step 5: Add migration `0005_run_runtime_envelope.py`**

Migration behavior:

```python
def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("business_mode", sa.String(length=32), nullable=True),
    )
    op.alter_column(
        "agent_runs",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE agent_runs SET started_at = CURRENT_TIMESTAMP WHERE started_at IS NULL"
    )
    op.alter_column(
        "agent_runs",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    op.drop_column("agent_runs", "business_mode")
```

Set:

```python
revision = "0005_run_runtime_envelope"
down_revision = "0004_issue_create_idempotency"
```

The downgrade backfill exists only so the old non-null schema can be restored safely; it does not change the WS2 upgrade semantics.

- [ ] **Step 6: Run Task 1 GREEN/static gates**

```bash
python -m pytest tests/integration/db/test_schema.py -v
ruff check \
  src/project_agent/domain/runs.py \
  src/project_agent/infrastructure/db/models/schema.py \
  migrations/versions/0005_run_runtime_envelope.py \
  tests/integration/db/test_schema.py \
  tests/integration/db/test_postgres_schema.py
mypy src/project_agent/domain/runs.py src/project_agent/infrastructure/db/models/schema.py
```

Expected: PASS.

When PostgreSQL is available:

```bash
alembic upgrade head
python -m pytest tests/integration/db/test_postgres_schema.py -v
```

Expected: PASS with `0 skipped`.

- [ ] **Step 7: Run regression and commit**

```bash
python -m pytest tests/integration/db tests/integration/evidence/test_citation_persistence.py -q
git diff --check
git add \
  src/project_agent/domain/runs.py \
  src/project_agent/infrastructure/db/models/schema.py \
  migrations/versions/0005_run_runtime_envelope.py \
  tests/integration/db/test_schema.py \
  tests/integration/db/test_postgres_schema.py
git commit -m "feat(runtime): define durable run event contract"
```

**Task 1 acceptance:** PostgreSQL can represent a queued Run without claiming it has started, every WS2-created Run can persist its business mode, and stable status/event/job vocabularies are available without adding a Worker handler.

---

### Task 2: Add the Run Repository and Same-Session Job Enqueue Boundary — ✅ COMPLETE

**Goal:** Provide a persistence boundary that can create/read/lock Runs and append ordered Events while enqueuing a job through the same request `AsyncSession` without committing internally.

**Why:** The current `PostgresJobQueue.enqueue()` creates and commits its own transaction, so it cannot satisfy the approved atomic Run/Event/Job boundary.

**Files:**
- Create: `src/project_agent/application/ports/run_repository.py`
- Create: `src/project_agent/infrastructure/db/repositories/runs.py`
- Create: `tests/fakes/run_repository.py`
- Modify: `src/project_agent/application/ports/job_queue.py`
- Modify: `src/project_agent/infrastructure/jobs/postgres.py`
- Modify: `src/project_agent/infrastructure/db/repositories/__init__.py`
- Modify: `tests/fakes/job_queue.py`
- Modify: `tests/contract/test_job_queue_port.py`
- Create: `tests/unit/runtime/test_run_service.py` for repository-facing fake contract scaffolding in this task
- Do not touch: `BackgroundWorker`, HandlerRegistry registrations, LangGraph

**Interfaces:**
- Consumes: Task 1 `ThreadRecord`, `RunRecord`, `AgentEventRecord`, `RunBusinessMode`, `RunStatus`, `AgentEventType`; existing `EnqueueJobRequest`/`QueuedJob`.
- Produces:

```python
@runtime_checkable
class JobEnqueuePort(Protocol):
    async def enqueue(self, request: EnqueueJobRequest) -> QueuedJob: ...


@runtime_checkable
class JobQueuePort(JobEnqueuePort, Protocol):
    async def claim(self, worker_id: str, limit: int = 1) -> list[QueuedJob]: ...
    async def heartbeat(self, job_id: str, worker_id: str) -> None: ...
    async def complete(self, job_id: str, worker_id: str) -> None: ...
    async def fail(self, job_id: str, worker_id: str, error_code: str) -> None: ...
    async def get(self, job_id: str) -> QueuedJob | None: ...
```

`RunRepository`:

```python
class RunRepository(Protocol):
    async def get_thread(self, thread_id: UUID) -> ThreadRecord | None: ...

    async def create_thread(
        self,
        *,
        company_id: UUID,
        project_id: UUID,
        user_id: UUID,
        title: str | None = None,
    ) -> ThreadRecord: ...

    async def create_run(
        self,
        *,
        thread_id: UUID,
        company_id: UUID,
        project_id: UUID,
        user_id: UUID,
        business_mode: RunBusinessMode,
    ) -> RunRecord: ...

    async def get_run(
        self,
        run_id: UUID,
        *,
        for_update: bool = False,
    ) -> RunRecord | None: ...

    async def append_event(
        self,
        *,
        run_id: UUID,
        event_type: AgentEventType,
        payload: dict[str, object],
    ) -> AgentEventRecord: ...

    async def list_events_after(
        self,
        *,
        run_id: UUID,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[AgentEventRecord, ...]: ...

    async def latest_event_of_type(
        self,
        *,
        run_id: UUID,
        event_type: AgentEventType,
    ) -> AgentEventRecord | None: ...

    async def set_status(
        self,
        *,
        run_id: UUID,
        status: RunStatus,
    ) -> RunRecord: ...
```

`SqlAlchemySessionJobEnqueuer(session, namespace="project-agent")` implements only `JobEnqueuePort` and calls `session.add(...)`, `flush()`, and `refresh()`; it never calls `commit()` or opens another session.

- [ ] **Step 1: Write the enqueue-only contract test RED**

Extend `tests/contract/test_job_queue_port.py`:

```python
@pytest.mark.asyncio
async def test_fake_queue_satisfies_enqueue_only_port() -> None:
    queue = FakeJobQueue()
    assert isinstance(queue, JobEnqueuePort)
    created = await queue.enqueue(
        EnqueueJobRequest(job_type="EXECUTE_AGENT_RUN", aggregate_id="run-1")
    )
    assert created.aggregate_id == "run-1"
```

Add a unit test for the fake Run repository proving `append_event()` allocates `1, 2, 3` per run and `list_events_after(after_sequence=1)` returns only `2, 3` in order.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/contract/test_job_queue_port.py tests/unit/runtime/test_run_service.py -v
```

Expected: FAIL because `JobEnqueuePort`, `RunRepository`, and `FakeRunRepository` do not exist yet.

- [ ] **Step 3: Add `JobEnqueuePort` without weakening the worker contract**

Modify `src/project_agent/application/ports/job_queue.py` so the existing worker `JobQueuePort` extends the enqueue-only protocol. Existing `PostgresJobQueue` and `FakeJobQueue` must still satisfy `JobQueuePort` unchanged.

- [ ] **Step 4: Add the same-session PostgreSQL enqueuer**

In `src/project_agent/infrastructure/jobs/postgres.py`, factor common request validation/model mapping into private helpers used by both queue writers. The same-session adapter must be equivalent to:

```python
class SqlAlchemySessionJobEnqueuer:
    def __init__(self, session: AsyncSession, *, namespace: str = "project-agent") -> None:
        self._session = session
        self._namespace = namespace

    async def enqueue(self, request: EnqueueJobRequest) -> QueuedJob:
        _validate_enqueue_request(request)
        row = _build_job_model(request, namespace=self._namespace)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return _to_job(row)
```

`PostgresJobQueue.enqueue()` may reuse the same helpers but must retain its existing worker-side own-session commit behavior. Do not change claim/lease/retry/reaper code.

- [ ] **Step 5: Implement `SqlAlchemyRunRepository`**

Required persistence rules:

```text
create_thread       -> add + flush; no commit
create_run          -> status=QUEUED, business_mode required, started_at=None; add + flush; no commit
get_run(for_update) -> SELECT/Session.get with FOR UPDATE when requested
append_event        -> lock agent_runs row; max(sequence_no)+1; add + flush; no commit
list_events_after   -> run_id match AND sequence_no > cursor; ORDER BY sequence_no ASC
latest_event        -> exact run + event type; ORDER BY sequence_no DESC LIMIT 1
set_status          -> lock row; assign status; flush; no commit
```

For `get_run()`, project only safe terminal result fields from the latest terminal event payload:

```python
result_ref = payload.get("result_ref") if isinstance(payload.get("result_ref"), str) else None
result_summary = payload.get("summary") if isinstance(payload.get("summary"), str) else None
```

Do not expose arbitrary provider payload fields through `RunRecord`.

- [ ] **Step 6: Implement the deterministic fake repository**

`tests/fakes/run_repository.py` must keep:

```text
threads: dict[UUID, ThreadRecord]
runs: dict[UUID, RunRecord]
events: dict[UUID, list[AgentEventRecord]]
```

It must support `for_update` as a no-op contract flag, deterministic ascending sequence allocation, event listing by cursor, and `set_status()` using `dataclasses.replace`.

Extend `FakeJobQueue` with public read-only test observability:

```python
@property
def jobs(self) -> tuple[QueuedJob, ...]: ...
```

and optional deterministic failure injection:

```python
self.enqueue_error: Exception | None = None
```

`enqueue()` raises `enqueue_error` before storing a job when configured.

- [ ] **Step 7: Run GREEN/static/regression**

```bash
python -m pytest \
  tests/contract/test_job_queue_port.py \
  tests/integration/jobs/test_claim.py \
  tests/unit/workers/test_worker.py \
  tests/unit/runtime/test_run_service.py \
  -q
ruff check \
  src/project_agent/application/ports/job_queue.py \
  src/project_agent/application/ports/run_repository.py \
  src/project_agent/infrastructure/jobs/postgres.py \
  src/project_agent/infrastructure/db/repositories/runs.py \
  tests/fakes/job_queue.py \
  tests/fakes/run_repository.py \
  tests/contract/test_job_queue_port.py
mypy \
  src/project_agent/application/ports/job_queue.py \
  src/project_agent/application/ports/run_repository.py \
  src/project_agent/infrastructure/jobs/postgres.py \
  src/project_agent/infrastructure/db/repositories/runs.py
git diff --check
```

Expected: PASS. Environment-gated live queue tests may skip here unless explicitly enabled; that skip is not reported as a live gate.

- [ ] **Step 8: Commit**

```bash
git add \
  src/project_agent/application/ports/job_queue.py \
  src/project_agent/application/ports/run_repository.py \
  src/project_agent/infrastructure/jobs/postgres.py \
  src/project_agent/infrastructure/db/repositories/runs.py \
  src/project_agent/infrastructure/db/repositories/__init__.py \
  tests/fakes/job_queue.py \
  tests/fakes/run_repository.py \
  tests/contract/test_job_queue_port.py \
  tests/unit/runtime/test_run_service.py
git commit -m "feat(runtime): add run persistence transaction boundary"
```

**Task 2 acceptance:** The API layer can write Thread/Run/Event/BackgroundJob rows using one injected `AsyncSession`, while the existing worker queue retains its independent committed operations.

---

### Task 3: Implement Authorized Run Creation and Durable Initial Input — ✅ COMPLETE

**Goal:** Implement the application service that authorizes an explicit project, creates/validates a project-bound thread, creates a queued Run, persists the initial input event, and enqueues `EXECUTE_AGENT_RUN` without committing inside the service.

**Why:** This is the approved WS2 business transaction; HTTP routing should remain thin and WS3 must be able to reload the query from durable state using only `run_id`.

**Files:**
- Create: `src/project_agent/application/services/runs.py`
- Modify: `src/project_agent/infrastructure/db/repositories/qa_graph.py:38-53`
- Modify: `tests/unit/runtime/test_run_service.py`
- Test: `tests/unit/runtime/test_run_service.py`
- Test: existing QA node/store tests that depend on `load_query`
- Do not touch: worker execution, graph invocation, issue creation side effects

**Interfaces:**
- Consumes:
  - `AuthorizationService.authorize_identity(identity, project_id)`
  - `RunRepository`
  - `JobEnqueuePort`
  - Task 1 Run/Event enums/records
- Produces:

```python
@dataclass(frozen=True, slots=True)
class CreateRunCommand:
    project_id: UUID
    business_mode: RunBusinessMode
    query_text: str
    thread_id: UUID | None = None


class RunNotFound(LookupError): ...
class ThreadNotFound(LookupError): ...
class RunAccessDenied(PermissionError): ...


class RunApplicationService:
    def __init__(
        self,
        *,
        authorization: AuthorizationService,
        repository: RunRepository,
        jobs: JobEnqueuePort,
    ) -> None: ...

    async def create_run(
        self,
        *,
        identity: AuthenticatedIdentity,
        command: CreateRunCommand,
    ) -> RunRecord: ...

    async def get_run(
        self,
        *,
        identity: AuthenticatedIdentity,
        run_id: UUID,
    ) -> RunRecord: ...
```

Task 3 implements only `create_run()` and `get_run()`. Resume-specific commands, exceptions, and `resume_run()` are introduced in Task 6 so Task 3 does not leave an unimplemented application interface behind.

- [ ] **Step 1: Write creation/read tests first**

Add tests equivalent to:

```python
@pytest.mark.asyncio
async def test_create_run_persists_project_bound_thread_run_event_and_execute_job() -> None:
    auth_repo = FakeProjectAuthorizationRepository()
    auth_repo.memberships[(USER, PROJECT)] = membership(ProjectRole.DEVELOPER)
    runs = FakeRunRepository()
    jobs = FakeJobQueue()
    service = RunApplicationService(
        authorization=AuthorizationService(auth_repo, clock=lambda: NOW),
        repository=runs,
        jobs=jobs,
    )

    created = await service.create_run(
        identity=AuthenticatedIdentity(user_id=USER),
        command=CreateRunCommand(
            project_id=PROJECT,
            business_mode=RunBusinessMode.QA,
            query_text="REQ-3.2.1 deployment window?",
        ),
    )

    assert created.project_id == PROJECT
    assert created.company_id == COMPANY
    assert created.user_id == USER
    assert created.status is RunStatus.QUEUED
    assert created.business_mode is RunBusinessMode.QA
    assert created.started_at is None
    assert runs.events[created.id][0].event_type is AgentEventType.RUN_QUEUED
    assert runs.events[created.id][0].payload == {
        "query_text": "REQ-3.2.1 deployment window?"
    }
    assert len(jobs.jobs) == 1
    assert jobs.jobs[0].job_type == RunJobType.EXECUTE.value
    assert jobs.jobs[0].aggregate_id == str(created.id)
```

Also cover exactly:

```text
blank query -> ValueError before any persistence
authenticated non-member -> AuthorizationDenied; no thread/run/event/job
revoked membership at current clock -> AuthorizationDenied; no side effects
new thread derives company_id/project_id/user_id from authorization + identity
existing thread with another project -> RunAccessDenied
existing thread with another company -> RunAccessDenied
existing thread owned by another user -> RunAccessDenied
missing supplied thread -> ThreadNotFound
get_run missing id -> RunNotFound
get_run re-authorizes current membership from run.project_id
get_run by user who belongs only to another project -> AuthorizationDenied
get_run after membership revocation -> AuthorizationDenied
```

Requiring the same authenticated user for an existing thread is not a new product feature: the existing `threads.user_id` and Task 13 graph state bind the conversation/confirmation identity to that user. Allowing another project member to take over the thread would require a separate approved collaboration/impersonation design.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/unit/runtime/test_run_service.py -v
```

Expected: FAIL because `RunApplicationService` and commands do not exist.

- [ ] **Step 3: Implement `create_run()` with no commit**

Required order:

```text
1. strip/validate query text
2. authorization.authorize_identity(identity, explicit project_id)
3. create a new Thread or load/validate the supplied Thread
4. create AgentRun(status=QUEUED, business_mode=..., started_at=None)
5. append RUN_QUEUED with payload {"query_text": clean_query}
6. enqueue EXECUTE_AGENT_RUN with aggregate_id=str(run.id)
7. return RunRecord
```

Every persistence call uses the injected repository/jobs objects. `RunApplicationService` must not call `commit()`.

Thread validation must compare all three durable ownership fields:

```python
thread.project_id == command.project_id
thread.company_id == authorized.scope.company_id
thread.user_id == identity.user_id
```

- [ ] **Step 4: Implement `get_run()` current-membership authorization**

Required order:

```text
load Run by id
if absent -> RunNotFound
authorize current identity against run.project_id
verify authorized company_id == run.company_id
return safe RunRecord
```

Do not authorize from `run.user_id`, JWT role, or request claims. Read access is project-membership based as required by the Design; run-user identity is enforced only on operations whose Task 13 semantics require the original actor, such as resume.

- [ ] **Step 5: Make existing QA persistence reload the WS2 durable initial input**

Change `SqlAlchemyQAGraphStore.load_query()` to accept the new event while retaining existing data compatibility:

```python
.where(
    AgentEventModel.run_id == run_id,
    AgentEventModel.event_type.in_([AgentEventType.RUN_QUEUED.value, "USER_QUERY"]),
)
.order_by(AgentEventModel.sequence_no)
.limit(1)
```

Continue reading `query_text` first and legacy `query` second. Do not change graph node behavior.

- [ ] **Step 6: Run GREEN/static/regression**

```bash
python -m pytest \
  tests/unit/runtime/test_run_service.py \
  tests/unit/agent \
  tests/integration/evidence/test_citation_persistence.py \
  -q
ruff check \
  src/project_agent/application/services/runs.py \
  src/project_agent/infrastructure/db/repositories/qa_graph.py \
  tests/unit/runtime/test_run_service.py
mypy \
  src/project_agent/application/services/runs.py \
  src/project_agent/infrastructure/db/repositories/qa_graph.py
git diff --check
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  src/project_agent/application/services/runs.py \
  src/project_agent/infrastructure/db/repositories/qa_graph.py \
  tests/unit/runtime/test_run_service.py
git commit -m "feat(runtime): add authorized run creation service"
```

**Task 3 acceptance:** An authorized Run can be constructed entirely from server-derived membership context and durable input, with an aggregate-only execute job ready for WS3 and no graph execution.

---

### Task 4: Add `POST /runs` and Run Read HTTP APIs with Current-Membership Security — ✅ COMPLETE

**Goal:** Expose the Run creation/read contract through FastAPI while preserving WS1 authentication, dependency injection, and authorization semantics.

**Why:** WS2 requires an actual protected HTTP entry point; the API must never accept authorization scope from request/JWT claims.

**Files:**
- Create: `src/project_agent/api/v1/runs.py`
- Create: `tests/integration/api/test_run_api.py`
- Modify: `src/project_agent/main.py:8-50`
- Test: `tests/integration/api/test_run_api.py`
- Reuse: `src/project_agent/api/dependencies.py`
- Reuse: `tests/helpers/jwt.py`
- Do not touch: WS1 document-route behavior, runtime lifespan resource construction

**Interfaces:**

Pydantic request/response models in `src/project_agent/api/v1/runs.py`:

```python
class CreateRunRequest(BaseModel):
    project_id: UUID
    business_mode: RunBusinessMode
    query: str = Field(min_length=1)
    thread_id: UUID | None = None


class RunResponse(BaseModel):
    run_id: UUID
    thread_id: UUID
    project_id: UUID
    business_mode: RunBusinessMode
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    result_ref: str | None = None
    summary: str | None = None
```

Production dependency:

```python
@dataclass(frozen=True, slots=True)
class RunApiServices:
    runs: RunApplicationService
    repository: RunRepository


def get_run_api_services(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> RunApiServices:
    repository = SqlAlchemyRunRepository(session)
    jobs = SqlAlchemySessionJobEnqueuer(session)
    return RunApiServices(
        runs=RunApplicationService(
            authorization=authorization,
            repository=repository,
            jobs=jobs,
        ),
        repository=repository,
    )
```

The repository is included in the service bundle for Task 5 SSE reads from the same request session; routes must not expose it to clients.

- [ ] **Step 1: Write the FastAPI RED tests**

`tests/integration/api/test_run_api.py` must use `create_app(settings, runtime_factory=fake_runtime_factory)` and FastAPI dependency overrides. It must not require live PostgreSQL or RAGFlow.

Cover:

```text
POST /api/v1/runs without Authorization -> 401 + WWW-Authenticate: Bearer
POST with invalid JWT -> 401 + Bearer challenge
POST with valid identity and active membership -> 201
response contains run_id/thread_id/project_id/business_mode/QUEUED
request does not accept/echo role/project_ids authorization claims
valid JWT with forged role=project_manager/project_ids but no real membership -> 403
valid JWT non-member -> 403
revoked fake membership on next request -> 403
existing thread from another project/user -> 403
GET own-project Run -> 200
GET cross-project Run without membership -> 403
GET unknown Run -> 404
```

Use the real `get_authenticated_identity` dependency with the WS1 fake runtime/JWT verifier. Override `get_run_api_services` with a service built from `FakeProjectAuthorizationRepository`, `FakeRunRepository`, and `FakeJobQueue`.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/integration/api/test_run_api.py -v
```

Expected: 404 for `/api/v1/runs` because the router/endpoints do not exist.

- [ ] **Step 3: Implement route dependency and controlled exception mapping**

Use this mapping only:

```text
AuthorizationDenied / RunAccessDenied -> 403
RunNotFound / ThreadNotFound          -> 404
Pydantic body validation              -> 422
unexpected exception                  -> propagate; request dependency rolls back
```

Do not catch generic `Exception` and convert it to a success or 4xx.

- [ ] **Step 4: Implement `POST /api/v1/runs`**

Call only `RunApplicationService.create_run()` and return `201`. Do not call a Worker or LangGraph.

The route must not manually call `session.commit()`; WS1 `get_db_session()` commits exactly once after a successful request and rolls back when service/enqueue raises.

- [ ] **Step 5: Implement `GET /api/v1/runs/{run_id}`**

Call only `RunApplicationService.get_run()`. Return the safe Run projection. Do not return raw `payload_json`, provider errors, JWT claims, or secrets.

- [ ] **Step 6: Include the Run router**

Modify `src/project_agent/main.py`:

```python
from project_agent.api.v1.runs import router as runs_router
...
app.include_router(runs_router)
```

Preserve the existing health and document router order/behavior and lifespan code.

- [ ] **Step 7: Run GREEN/security/static/regression**

```bash
python -m pytest \
  tests/integration/api/test_run_api.py \
  tests/integration/api/test_authentication.py \
  tests/integration/api/test_document_authorization.py \
  tests/security/test_non_member.py \
  tests/security/test_cross_client.py \
  -q
ruff check \
  src/project_agent/api/v1/runs.py \
  src/project_agent/main.py \
  tests/integration/api/test_run_api.py
mypy src/project_agent/api/v1/runs.py src/project_agent/main.py
git diff --check
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  src/project_agent/api/v1/runs.py \
  src/project_agent/main.py \
  tests/integration/api/test_run_api.py
git commit -m "feat(api): add authorized run create and read endpoints"
```

**Task 4 acceptance:** Protected Run create/read HTTP endpoints exist, explicit `project_id` is mandatory on create, and all authorization is reconstructed from current membership rather than trusted JWT claims.

---

### Task 5: Add Durable Agent Event SSE with Ordering and Reconnect — ✅ COMPLETE

**Goal:** Stream persisted Run events through `GET /api/v1/runs/{run_id}/events` with deterministic sequence IDs, `Last-Event-ID` replay, terminal close behavior, and no coupling to Worker cancellation.

**Why:** The approved Design makes PostgreSQL `agent_events` the durable source of truth and requires reconnectable SSE.

**Files:**
- Modify: `src/project_agent/api/v1/runs.py`
- Create: `tests/unit/runtime/test_run_sse.py`
- Modify: `tests/integration/api/test_run_api.py`
- Test: `tests/unit/runtime/test_run_sse.py`
- Test: `tests/integration/api/test_run_api.py`
- Do not touch: Worker lifecycle, Run cancellation semantics, WebSocket infrastructure

**Interfaces:**

Add a testable async generator helper in `src/project_agent/api/v1/runs.py`:

```python
type SleepFn = Callable[[float], Awaitable[None]]


async def iter_sse_events(
    *,
    repository: RunRepository,
    run_id: UUID,
    after_sequence: int,
    poll_seconds: float = 0.25,
    sleep: SleepFn = asyncio.sleep,
) -> AsyncIterator[str]: ...
```

Add:

```python
def parse_last_event_id(value: str | None) -> int: ...
def encode_sse_event(event: AgentEventRecord) -> str: ...
```

Encoding is exactly:

```text
id: <sequence_no>\n
event: <event_type>\n
data: <compact-json-payload>\n
\n
```

Use `json.dumps(event.payload, ensure_ascii=False, separators=(",", ":"))` so each event remains a single SSE data line.

- [ ] **Step 1: Write pure SSE RED tests**

`tests/unit/runtime/test_run_sse.py` must cover:

```python
def test_last_event_id_defaults_to_zero() -> None:
    assert parse_last_event_id(None) == 0


def test_last_event_id_rejects_malformed_or_negative() -> None:
    with pytest.raises(ValueError):
        parse_last_event_id("not-an-int")
    with pytest.raises(ValueError):
        parse_last_event_id("-1")
```

Async generator coverage must prove:

```text
repository events 1,2,3 -> emitted as ids 1,2,3
cursor 1 -> only 2,3
cursor 3 -> no replay of 1,2,3
terminal event is emitted exactly once then generator stops
already-terminal Run + cursor at terminal sequence -> generator stops without waiting forever
non-terminal empty poll calls injected sleep and can be cancelled without any repository mutation
```

The fake repository should expose counters for read calls only; there is no cancel/update call in the SSE path.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/unit/runtime/test_run_sse.py -v
```

Expected: FAIL because the SSE helpers do not exist.

- [ ] **Step 3: Implement cursor parsing and event encoding**

`parse_last_event_id()`:

```text
None/empty -> 0
decimal integer >= 0 -> that integer
anything else -> ValueError
```

The HTTP route catches only this `ValueError` before constructing `StreamingResponse` and returns HTTP `400` with `detail="invalid Last-Event-ID"`.

- [ ] **Step 4: Implement `iter_sse_events()` from durable rows**

Loop behavior:

```text
cursor = after_sequence
list_events_after(run_id, cursor, limit=100)
for each event in ascending order:
    yield encoded event
    cursor = event.sequence_no
    if terminal event -> return
if no events:
    get_run(run_id)
    if missing -> return
    if run.status is terminal -> return
    await sleep(poll_seconds)
```

Do not insert heartbeat AgentEvents. Do not change Run state when the generator is closed/cancelled.

- [ ] **Step 5: Implement protected SSE route**

Before returning `StreamingResponse`, call:

```python
await services.runs.get_run(identity=identity, run_id=run_id)
```

This performs current membership authorization using the Run's durable `project_id`.

Then return:

```python
StreamingResponse(
    iter_sse_events(...),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    },
)
```

Do not attach the background Worker task to the HTTP request or generator. Disconnect therefore ends only the stream.

- [ ] **Step 6: Add HTTP SSE security/reconnect tests**

Extend `tests/integration/api/test_run_api.py` to prove:

```text
no JWT -> 401
invalid JWT -> 401
cross-project/non-member -> 403
forged JWT project/role claim without membership -> 403
active member -> text/event-stream
persisted sequence 1,2,3 appears in ascending SSE id order
Last-Event-ID: 1 returns only ids 2,3
malformed Last-Event-ID -> 400
terminal event closes response
reconnect after terminal with terminal id does not replay or hang
disconnecting/closing stream leaves Run status and queued BackgroundJob unchanged in fakes
```

For finite TestClient HTTP tests, seed a terminal event before opening the stream so the response closes deterministically. Use the pure generator test for the non-terminal disconnect/cancellation path.

- [ ] **Step 7: Run GREEN/static/regression**

```bash
python -m pytest \
  tests/unit/runtime/test_run_sse.py \
  tests/integration/api/test_run_api.py \
  -q
ruff check src/project_agent/api/v1/runs.py tests/unit/runtime/test_run_sse.py tests/integration/api/test_run_api.py
mypy src/project_agent/api/v1/runs.py
git diff --check
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  src/project_agent/api/v1/runs.py \
  tests/unit/runtime/test_run_sse.py \
  tests/integration/api/test_run_api.py
git commit -m "feat(api): stream reconnectable run events"
```

**Task 5 acceptance:** SSE is a durable ordered projection with explicit replay semantics, current-membership authorization, terminal closure, and no ability for an HTTP disconnect to cancel background execution.

---

### Task 6: Add Durable Resume Input and `POST /runs/{run_id}/resume` — ✅ COMPLETE

**Goal:** Let the original authorized Run actor submit payload-bound Issue confirmation input, persist it durably, transition the Run back to queued work, and atomically enqueue `RESUME_AGENT_RUN` without executing LangGraph.

**Why:** The approved V1 Design requires durable resume input and replay-safe state checks while preserving Task 13's confirmation binding and moving actual `Command(resume=...)` execution to WS3.

**Files:**
- Modify: `src/project_agent/application/services/runs.py`
- Modify: `src/project_agent/api/v1/runs.py`
- Modify: `tests/unit/runtime/test_run_service.py`
- Modify: `tests/integration/api/test_run_api.py`
- Test: `tests/unit/runtime/test_run_service.py`
- Test: `tests/integration/api/test_run_api.py`
- Do not touch: `confirm_issue_create_node`, `IssueConfirmationService`, Sandbox write services, Worker handlers

**Interfaces:**

Task 6 adds these application interfaces to `src/project_agent/application/services/runs.py`:

```python
@dataclass(frozen=True, slots=True)
class ResumeRunCommand:
    action: ConfirmationAction
    request_payload_hash: str


class RunStateConflict(RuntimeError): ...
class ResumeInputMismatch(RunStateConflict): ...


class RunApplicationService:
    async def resume_run(
        self,
        *,
        identity: AuthenticatedIdentity,
        run_id: UUID,
        command: ResumeRunCommand,
    ) -> RunRecord: ...
```

`ResumeRunRequest`:

```python
class ResumeRunRequest(BaseModel):
    action: ConfirmationAction
    request_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
```

The prerequisite durable waiting event is:

```text
event_type = WAITING_CONFIRMATION
payload contains at least:
  request_payload_hash: <64-char sha256>
```

WS3 must persist the actual interrupt as this event contract when it is implemented; WS2 tests seed it directly.

- [ ] **Step 1: Write resume-service RED tests**

Add tests equivalent to:

```python
@pytest.mark.asyncio
async def test_resume_waiting_run_persists_input_and_enqueues_resume_job() -> None:
    service, runs, jobs = build_service_with_member()
    run = seed_run(
        runs,
        user_id=USER,
        project_id=PROJECT,
        status=RunStatus.WAITING_CONFIRMATION,
        business_mode=RunBusinessMode.ISSUE_CREATE,
    )
    await runs.append_event(
        run_id=run.id,
        event_type=AgentEventType.WAITING_CONFIRMATION,
        payload={"request_payload_hash": HASH},
    )

    updated = await service.resume_run(
        identity=AuthenticatedIdentity(user_id=USER),
        run_id=run.id,
        command=ResumeRunCommand(
            action=ConfirmationAction.CONFIRM,
            request_payload_hash=HASH,
        ),
    )

    assert updated.status is RunStatus.QUEUED
    resume_event = runs.events[run.id][-1]
    assert resume_event.event_type is AgentEventType.RUN_RESUME_QUEUED
    assert resume_event.payload == {
        "action": "confirm",
        "request_payload_hash": HASH,
        "actor_id": str(USER),
    }
    assert jobs.jobs[-1].job_type == RunJobType.RESUME.value
    assert jobs.jobs[-1].aggregate_id == str(run.id)
```

Also cover exactly:

```text
missing Run -> RunNotFound
current non-member/revoked member -> AuthorizationDenied
project member who is not run.user_id -> RunAccessDenied
Run not WAITING_CONFIRMATION -> RunStateConflict; no event/job
business_mode != issue_create -> RunStateConflict; no event/job
missing WAITING_CONFIRMATION event -> RunStateConflict
hash differs from latest waiting event -> ResumeInputMismatch; no event/job
confirm and cancel are both accepted when hash matches
a second/replayed resume after first transition -> RunStateConflict; no second event/job
```

The same-user requirement preserves the current Task 13 graph state's `user_id` / confirmation actor binding; allowing another project member to resume would change the approved confirmation identity semantics.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/unit/runtime/test_run_service.py -k resume -v
```

Expected: FAIL because `resume_run()` is not implemented.

- [ ] **Step 3: Implement resume state/idempotency checks under Run row lock**

Required order:

```text
1. repository.get_run(run_id, for_update=True)
2. RunNotFound if absent
3. current membership authorization against run.project_id
4. company_id consistency check
5. require identity.user_id == run.user_id
6. require business_mode == issue_create
7. require status == WAITING_CONFIRMATION
8. load latest WAITING_CONFIRMATION event
9. compare request_payload_hash exactly
10. append RUN_RESUME_QUEUED durable input event
11. set Run status to QUEUED
12. enqueue RESUME_AGENT_RUN aggregate_id=run_id
13. return updated Run
```

The row lock + state transition is the duplicate/replay barrier. Concurrent requests serialize; after the first successful request changes the status to `QUEUED`, the second sees a state conflict and cannot append a second resume event or job.

Do not call `IssueConfirmationService.record_decision()` here. The existing graph node must still consume the resume value and perform Task 13 payload/expiry semantics when WS3 invokes `Command(resume=...)`.

- [ ] **Step 4: Write API RED tests**

Extend `tests/integration/api/test_run_api.py`:

```text
POST /resume no JWT -> 401
invalid JWT -> 401
cross-project/non-member -> 403
forged role/project claims do not grant resume -> 403
wrong authenticated user in same project -> 403
valid waiting issue_create Run + matching hash -> 202
response reports run_id + QUEUED
wrong hash -> 409
non-waiting Run -> 409
invalid action/hash format -> 422
replayed identical resume -> 409 and exactly one RESUME_AGENT_RUN job
```

- [ ] **Step 5: Implement `POST /resume` route**

Map:

```text
ResumeInputMismatch / RunStateConflict -> 409
AuthorizationDenied / RunAccessDenied  -> 403
RunNotFound                            -> 404
```

Return `202 Accepted`. Do not run LangGraph, do not create a `ToolConfirmationModel`, and do not execute the Sandbox tool.

- [ ] **Step 6: Run GREEN/static/security regression**

```bash
python -m pytest \
  tests/unit/runtime/test_run_service.py \
  tests/integration/api/test_run_api.py \
  tests/unit/issues/test_confirmation.py \
  tests/unit/issues/test_interrupt_node.py \
  tests/security/test_confirmation_payload_binding.py \
  tests/security/test_unconfirmed_issue_create.py \
  -q
ruff check \
  src/project_agent/application/services/runs.py \
  src/project_agent/api/v1/runs.py \
  tests/unit/runtime/test_run_service.py \
  tests/integration/api/test_run_api.py
mypy src/project_agent/application/services/runs.py src/project_agent/api/v1/runs.py
git diff --check
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  src/project_agent/application/services/runs.py \
  src/project_agent/api/v1/runs.py \
  tests/unit/runtime/test_run_service.py \
  tests/integration/api/test_run_api.py
git commit -m "feat(api): persist and enqueue run resume input"
```

**Task 6 acceptance:** `/resume` is a pure authorization/persistence/enqueue boundary with durable payload-bound input and duplicate-safe state transition; no Issue write or LangGraph execution occurs in WS2.

---

### Task 7: Prove PostgreSQL Atomicity, Project Security, Revocation, and End-to-End WS2 Persistence — ✅ COMPLETE

**Goal:** Add an opt-in live PostgreSQL gate that proves the actual FastAPI/request-session path atomically persists Run/Event/Job state and enforces current membership for create/read/SSE/resume.

**Why:** Offline fakes verify application logic, but the approved Design requires a live `run/event transaction path`; WS2 cannot call the durability boundary complete when PostgreSQL tests are skipped.

**Files:**
- Create: `tests/integration/api/test_run_api_postgres.py`
- Modify: none; Task 7 is a live verification-only task. Any defect it exposes must be fixed in the owning Task 1–6 change before this gate is marked complete.
- Test: `tests/integration/api/test_run_api_postgres.py`
- Reuse: `tests/helpers/jwt.py`
- Reuse: migration head `0005_run_runtime_envelope`
- Do not touch: Worker handler implementation, real LLM/RAGFlow execution

**Live test setup:**

Use:

```python
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL Run API integration",
)
```

Seed two projects with distinct IDs plus memberships needed for positive/cross-project tests. Use the real `create_app(settings)` production path, real `JwtIdentityVerifier`, real `get_db_session`, real `SqlAlchemyProjectAuthorizationRepository`, real `SqlAlchemyRunRepository`, and real same-session job enqueuer. RAGFlow/LLM URLs may remain non-routable because WS2 routes must not contact them.

- [ ] **Step 1: Write the live PostgreSQL tests before relying on the gate**

At minimum implement these tests:

#### A. Atomic successful creation

```text
POST /api/v1/runs -> 201
one Thread row for returned thread_id
one AgentRun row: project/user/company correct, business_mode=qa, status=QUEUED, started_at IS NULL
sequence 1 AgentEvent = RUN_QUEUED and query_text persisted
one BackgroundJob = EXECUTE_AGENT_RUN, aggregate_id == run_id
BackgroundJob contains no query/resume payload column
```

#### B. Enqueue failure rolls back the complete request transaction

Override only the enqueue dependency with a `FailingJobEnqueuer` that raises `RuntimeError("forced enqueue failure")` while the Run repository remains the real session-backed repository. Create the TestClient with `raise_server_exceptions=False`.

Expected:

```text
HTTP 500
0 new Thread rows for the attempted request
0 new AgentRun rows
0 new AgentEvent rows
0 new BackgroundJob rows
```

This proves the commit boundary is WS1's request-scoped session, not an internal repository/enqueuer commit.

#### C. Current membership and cross-project security

```text
member creates Run in Project A -> 201
same valid JWT after Project A membership valid_to is set in the past -> GET Run 403
user with membership only in Project B -> GET Project-A Run 403
same Project-B-only JWT with forged role=project_manager/project_ids=[Project A] -> 403
GET /events for Project-A Run under Project-B-only identity -> 403
```

#### D. Resume atomicity and replay safety

Seed/update the Run using real PostgreSQL state:

```text
business_mode=issue_create
status=WAITING_CONFIRMATION
append WAITING_CONFIRMATION event with request_payload_hash
```

Then:

```text
first POST /resume matching hash -> 202
exactly one RUN_RESUME_QUEUED event
exactly one RESUME_AGENT_RUN job
Run status -> QUEUED
second identical POST /resume -> 409
counts remain one event + one resume job
```

#### E. SSE ordering/reconnect from real rows

Append finite events including a terminal event, then verify through the actual HTTP route:

```text
SSE ids are strictly ascending persisted sequence_no
Last-Event-ID skips acknowledged rows
terminal event is delivered and response closes
```

- [ ] **Step 2: Run the new live test without the flag and confirm it is explicitly skipped**

```bash
python -m pytest tests/integration/api/test_run_api_postgres.py -v
```

Expected: explicit SKIP due to `RUN_POSTGRES_INTEGRATION`, not PASS. This is only a test registration check.

- [ ] **Step 3: Apply migration and run the real live gate**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

alembic upgrade head
python -m pytest \
  tests/integration/db/test_postgres_schema.py \
  tests/integration/auth/test_authorization_repository.py \
  tests/integration/api/test_document_auth_postgres.py \
  tests/integration/api/test_run_api_postgres.py \
  -v
```

Expected:

```text
all selected tests PASS
0 skipped
```

If any selected test skips, the WS2 live PostgreSQL gate remains `PENDING`.

- [ ] **Step 4: Run the WS2 offline acceptance set**

```bash
python -m pytest \
  tests/unit/runtime/test_run_service.py \
  tests/unit/runtime/test_run_sse.py \
  tests/integration/api/test_run_api.py \
  tests/contract/test_job_queue_port.py \
  tests/integration/jobs/test_claim.py \
  tests/unit/workers/test_worker.py \
  tests/unit/issues/test_confirmation.py \
  tests/unit/issues/test_interrupt_node.py \
  tests/security/test_confirmation_payload_binding.py \
  tests/security/test_unconfirmed_issue_create.py \
  -q
```

Expected: all non-environment-gated tests PASS. If `tests/integration/jobs/test_claim.py` skips because the live flag is absent, that skip is not counted as the WS2 PostgreSQL gate; Step 3 is the live evidence.

- [ ] **Step 5: Run repository-wide static/regression gates**

```bash
ruff check src tests
mypy src
python -m pytest -q
python scripts/run_checks.py
git diff --check
```

Expected: PASS. Environment-gated tests in the unflagged full suite may report their documented skips; those skips do not replace Step 3.

- [ ] **Step 6: Verify WS2 scope isolation**

```bash
git status --short
git diff --name-only HEAD~6..HEAD
rg -n "EXECUTE_AGENT_RUN|RESUME_AGENT_RUN" src/project_agent/workers
```

Review manually:

```text
- no EXECUTE_AGENT_RUN/RESUME_AGENT_RUN production handler was added;
- no Worker starts LangGraph;
- no real LLM adapter/retrieval-grade/Evidence-chain/metrics/Docker/evaluation code was introduced;
- `background_jobs` still carries only aggregate identity;
- no JWT authorization claims are consumed by Run routes;
- all new Run/Event writes occur through PostgreSQL-backed durable state.
```

- [ ] **Step 7: Commit the live gate**

```bash
git add tests/integration/api/test_run_api_postgres.py
git commit -m "test(runtime): prove run api postgres durability"
```

**Task 7 acceptance:** The real migrated PostgreSQL path proves successful atomic create, full rollback on enqueue failure, current-membership/cross-project security, durable replay-safe resume enqueue, and reconnectable ordered SSE without executing WS3.

---

## Security Test Matrix

WS2 is not accepted unless the following are explicitly covered by the offline and/or live tests above:

| Case | Expected result | Primary test location |
|---|---|---|
| no JWT | `401` + `WWW-Authenticate: Bearer` | `tests/integration/api/test_run_api.py` |
| invalid JWT | `401` + Bearer challenge | `tests/integration/api/test_run_api.py` |
| authenticated non-member | `403` | offline + live Run API tests |
| revoked membership | next request `403` | fake service + live PostgreSQL test |
| forged JWT role/project claims | no elevation; `403` without real membership | offline + live PostgreSQL test |
| cross-project Run read | `403` | offline + live PostgreSQL test |
| cross-project Event/SSE access | `403` | offline + live PostgreSQL test |
| cross-project/thread continuation | `403` | service/API tests |
| same-project different user resume | `403` | resume service/API tests |
| resume wrong payload hash | `409` | resume service/API tests |
| resume duplicate/replay | `409`; no second event/job | offline + live PostgreSQL test |

The Run read/SSE contract follows the approved Design's project-membership access rule. Resume is stricter because the existing Task 13 confirmation graph binds the confirmation actor to the Run's original `user_id`.

---

## Transaction / Durability Contract

### Run creation transaction

All of the following belong to **one request-scoped PostgreSQL transaction**:

```text
create/validate Thread
+
create AgentRun(status=QUEUED, business_mode=..., started_at=NULL)
+
append RUN_QUEUED AgentEvent(sequence_no=1, query_text=...)
+
insert BackgroundJob(job_type=EXECUTE_AGENT_RUN, aggregate_id=run_id)
```

Commit boundary:

```text
FastAPI route returns successfully
→ WS1 get_db_session() dependency commits once
```

Rollback boundary:

```text
any exception before successful dependency exit
→ WS1 get_db_session() rolls back
```

Enqueue failure expected state:

```text
Thread      : absent if newly created by this failed request
AgentRun    : absent
AgentEvent  : absent
BackgroundJob: absent
```

No repository/service/job-enqueuer method in this transaction may call `commit()`.

### Resume transaction

One transaction contains:

```text
SELECT AgentRun FOR UPDATE
+
current membership/state/hash checks
+
append RUN_RESUME_QUEUED(action/hash/actor)
+
set Run status QUEUED
+
insert BackgroundJob(job_type=RESUME_AGENT_RUN, aggregate_id=run_id)
```

If enqueue fails, the event and status transition roll back with the job insert. If a second concurrent/replayed resume waits on the Run row lock, it observes the first transaction's `QUEUED` status after commit and returns state conflict without adding another event/job.

---

## SSE Acceptance Matrix

| Behavior | Required assertion |
|---|---|
| ordering | emitted SSE ids follow persisted `sequence_no ASC` |
| reconnect | `Last-Event-ID=N` returns only sequence `> N` |
| replay | all unacknowledged durable events are replayed |
| duplicate semantics | exact cursor prevents duplicates; ambiguous disconnect permits at-least-once replay, dedupe by id |
| disconnect | generator/session closes; Run/Job state is unchanged |
| authorization | run project is authorized before streaming starts |
| cross-project | `403` before stream headers/body |
| terminal event | terminal event is emitted once, then stream closes |
| reconnect after terminal | if terminal id already acknowledged, stream closes without hanging |
| malformed cursor | `400 invalid Last-Event-ID` before stream starts |

---

## WS2 Acceptance Boundary

WS2 is complete only when all are true:

```text
[x] WS1 runtime/auth/session foundation remains intact.
[x] POST /api/v1/runs requires explicit project_id and current membership.
[x] Run business mode is durably stored for every new WS2 Run.
[x] New Runs begin QUEUED with started_at NULL.
[x] New or supplied Thread is validated against durable project/company/user ownership.
[x] Run + initial RUN_QUEUED event + EXECUTE_AGENT_RUN job commit atomically.
[x] Query text is durable outside background_jobs.
[x] GET /api/v1/runs/{run_id} re-authorizes current project membership.
[x] Safe result_ref/summary projection never returns arbitrary provider payloads.
[x] Agent Events are append-only and have unique per-run sequence numbers.
[x] SSE uses sequence_no as id and supports Last-Event-ID replay.
[x] SSE ordering/reconnect/terminal/disconnect semantics are tested.
[x] SSE cross-project access is denied.
[x] Resume requires current project membership plus original Run actor identity.
[x] Resume requires WAITING_CONFIRMATION + matching payload hash.
[x] Resume input is durable in RUN_RESUME_QUEUED event.
[x] Resume transition + RESUME_AGENT_RUN enqueue is one transaction.
[x] Duplicate/replayed resume cannot create a second event/job.
[x] No WS3 Worker execute/resume handler is implemented.
[x] No LangGraph execution occurs from an API request.
[x] No real LLM/retrieval/Issue Evidence/observability/Docker/evaluation scope is pulled into WS2.
[x] Offline WS2 gate passes.
[x] Live PostgreSQL WS2 gate passes with 0 skipped tests before live durability is claimed.
[x] ruff check src tests passes.
[x] mypy src passes.
[x] python -m pytest -q passes.
[x] git diff --check passes.
```

---

## WS2 Completion Evidence

The implementation and acceptance sequence is closed as follows:

```text
Task 1 — Run/Event domain + schema                    ✅ COMPLETE
Task 2 — Run repository + same-session enqueue        ✅ COMPLETE
Task 3 — Authorized Run creation                      ✅ COMPLETE
Task 4 — Run create/read HTTP API                     ✅ COMPLETE
Task 5 — AgentEvent + reconnectable SSE               ✅ COMPLETE
Task 6 — Durable Resume boundary                      ✅ COMPLETE
Task 7 — Live PostgreSQL acceptance                   ✅ COMPLETE

WS2 — Run API + Agent Event + SSE                     ✅ COMPLETE
```

Final verification on the real project environment:

```text
Environment: conda `it-agent`, Python 3.12.14
Ruff:        PASS
MyPy:        PASS (116 source files)
Pytest:      268 passed, 1 skipped
PostgreSQL:  live WS2 acceptance executed; 0 WS2 PostgreSQL skips
Remaining skip: real RAGFlow project-isolation integration only
```

The WS2 completion decision therefore no longer depends on skipped PostgreSQL tests. WS3 may use the completed WS2 durable Run/Event/Job and Resume boundaries as its execution substrate.

---

## Final Verification Commands

### 1. Source-of-truth / Git preflight

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent

git status --short --branch
git log --oneline -15
```

Do not start Task 1 implementation with unrelated dirty WS1 changes mixed into the WS2 branch/worktree.

### 2. WS2 offline gate

```bash
python -m pytest \
  tests/unit/runtime/test_run_service.py \
  tests/unit/runtime/test_run_sse.py \
  tests/integration/api/test_run_api.py \
  tests/contract/test_job_queue_port.py \
  tests/unit/issues/test_confirmation.py \
  tests/unit/issues/test_interrupt_node.py \
  tests/security/test_confirmation_payload_binding.py \
  tests/security/test_unconfirmed_issue_create.py \
  -q
```

Expected: PASS.

### 3. Static/full repository gate

```bash
ruff check src tests
mypy src
python -m pytest -q
python scripts/run_checks.py
git diff --check
```

Expected: PASS subject only to existing documented environment-gated skips in the unflagged full suite. Those skips do not count as live evidence.

### 4. WS2 live PostgreSQL gate

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

alembic upgrade head
python -m pytest \
  tests/integration/db/test_postgres_schema.py \
  tests/integration/auth/test_authorization_repository.py \
  tests/integration/api/test_document_auth_postgres.py \
  tests/integration/api/test_run_api_postgres.py \
  -v
```

Expected: all selected tests PASS with **0 skipped**.

### 5. Scope-isolation check

```bash
git status --short
git log --oneline -10
rg -n "EXECUTE_AGENT_RUN|RESUME_AGENT_RUN" src/project_agent/workers
```

The existing string constants may remain in `workers/handlers.py`; there must be no new production execution/resume handler implementation from WS2.

---

## Commit Sequence

The intended review gates are one commit per WS2 Task:

```text
1. feat(runtime): define durable run event contract
2. feat(runtime): add run persistence transaction boundary
3. feat(runtime): add authorized run creation service
4. feat(api): add authorized run create and read endpoints
5. feat(api): stream reconnectable run events
6. feat(api): persist and enqueue run resume input
7. test(runtime): prove run api postgres durability
```

Do not squash during plan execution; each Task is independently reviewable and supplies the dependency required by the next Task.

---

## WS2 Plan Self-Review — ✅ COMPLETE

### Scope

PASS. The Plan stops at HTTP/application persistence/job enqueue. It does not implement `EXECUTE_AGENT_RUN`/`RESUME_AGENT_RUN` Worker handlers, graph execution, Structured LLM, retrieval-grade, Issue Evidence-chain completion, observability, Docker, or evaluation.

### Completeness

PASS. The approved WS2 requirements map to Tasks as follows:

```text
Run/thread application + repository boundary : Tasks 1-3
POST /runs                                   : Task 4
Run read                                     : Tasks 3-4
AgentEvent persistence/order                 : Tasks 1-2
SSE + Last-Event-ID replay                   : Task 5
Resume HTTP/persistence                      : Task 6
explicit project_id                          : Tasks 3-4
authorization/cross-project security         : Tasks 3-7
Run + event + job atomicity                  : Tasks 2-3 + live Task 7
resume event + status + job atomicity        : Task 6 + live Task 7
live PostgreSQL durability gate              : Task 7
```

### Executability

PASS. Every implementation Task has exact files, a RED condition, minimal implementation boundary, targeted tests, Ruff/MyPy commands, regression checks, and a commit message.

### Dependency Order

PASS. Schema/domain contract precedes persistence; persistence precedes application transaction; application transaction precedes HTTP; HTTP/read precede SSE; waiting-event semantics precede resume; live PostgreSQL proof closes the workstream.

### Testability

PASS. WS1 `runtime_factory`/FastAPI dependency overrides remain intact. Application tests use fake authorization/Run repository/job queue. The live gate uses the real request-scoped PostgreSQL transaction and can override only the enqueue seam to prove rollback.

### Architecture Lock

PASS. The Plan adds no infrastructure stack and uses only PostgreSQL, FastAPI, existing authorization, and the existing PostgreSQL Job Queue tables allowed by ADR-0004. The only migration is a narrow Run persistence correction/addition permitted by the Architecture Lock's PostgreSQL field/index allowance.

