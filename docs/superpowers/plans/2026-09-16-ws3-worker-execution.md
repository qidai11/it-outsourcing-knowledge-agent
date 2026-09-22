# WS3 PostgreSQL Worker Runtime + EXECUTE/RESUME Handlers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended when a real subagent facility exists) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consume durable `BackgroundJob` rows with a production Worker, execute or resume a queued Run through an injected LangGraph boundary, and persist idempotent Run/AgentEvent lifecycle transitions without reimplementing WS1/WS2 or pulling WS4/WS5 business completion forward.

**Architecture:** Keep the existing PostgreSQL Job Queue, lease/heartbeat/retry/reaper, `BackgroundWorker`, WS2 Run API, and WS2 durable event vocabulary. Add a small worker-side Run execution layer with two explicit phases: (1) atomically prepare/mark a Run execution intent in PostgreSQL, (2) invoke an injected LangGraph executor outside the Run-row lock, then atomically project the graph outcome back into `agent_runs` + `agent_events`. Retries reuse the same `run_id`, `thread_id`, and checkpoint identity; terminal Runs are no-ops on duplicate jobs, while a final failed queue attempt durably writes exactly one `RUN_FAILED` terminal transition.

**Tech Stack:** Python 3.12, FastAPI codebase contracts from WS1/WS2, SQLAlchemy asyncio + asyncpg, PostgreSQL Job Queue, LangGraph 1.2.x, `langgraph-checkpoint-postgres` 3.1.x, pytest/pytest-asyncio, Ruff, MyPy.

**Spec:** `docs/superpowers/specs/2026-09-12-v1-completion-design.md`

## Global Constraints

- Keep the V1 architecture locked to FastAPI + LangGraph + PostgreSQL + PostgreSQL Job Queue + RAGFlow + `LocalFileObjectStoreAdapter` + `SandboxProjectTrackerAdapter`.
- Do not add Redis, ARQ, Celery, MinIO, a second vector database, multi-Agent orchestration, production Jira/禅道/飞书 writes, SaaS multi-tenancy, Kubernetes, GraphRAG, or RAPTOR.
- Do not rewrite WS1 authentication or WS2 Run API/SSE/resume endpoints.
- WS2 remains the only HTTP producer of `EXECUTE_AGENT_RUN` and `RESUME_AGENT_RUN`; queue payloads remain aggregate-only (`aggregate_id = run_id`).
- JWT and request authorization do not move into the Worker. Worker execution trusts only durable Run ownership/input persisted by the authorized WS2 transaction; Issue write permission is still re-checked by the existing Task 13 service at the side-effect boundary.
- Run status vocabulary remains `QUEUED`, `RUNNING`, `WAITING_CONFIRMATION`, `SUCCEEDED`, `REFUSED`, `CANCELLED`, `FAILED`.
- Agent Event vocabulary remains the WS2 contract: `RUN_QUEUED`, `RUN_STARTED`, `RUN_PROGRESS`, `ARTIFACT_AVAILABLE`, `WAITING_CONFIRMATION`, `RUN_RESUME_QUEUED`, `RUN_RESUMED`, `RUN_SUCCEEDED`, `RUN_REFUSED`, `RUN_CANCELLED`, `RUN_FAILED`.
- Existing PostgreSQL queue claim/lease/heartbeat/retry/reaper behavior is reused rather than redesigned.
- WS3 must not implement the real Structured LLM adapter, QA retrieval grading, the max-two-round QA policy, requirement/test Evidence retrieval, Issue evidence population, Prometheus/observability completion, Docker completion, or evaluation.
- WS3 freezes the **runtime dispatch contract** for all `RunBusinessMode` values but does not production-wire WS4 QA dependencies or WS5 Issue business completion. WS4/WS5 provide those concrete graph dependencies later.
- A skipped live PostgreSQL or LangGraph/checkpointer test is not a WS3 live PASS.
- Do not persist raw provider bodies, API keys, JWTs, or unsafe exception text in `AgentEvent.payload`.


## Goal

Consume the durable WS2 `BackgroundJob` boundary with a production Worker that can execute and resume Runs through an injected LangGraph boundary, while persisting durable, idempotent Run/AgentEvent lifecycle state and preserving the approved PostgreSQL lease/retry/checkpoint architecture.

## Non-Goals

- Do not reimplement or redesign WS1 authentication/authorization or WS2 Run API/SSE/resume persistence.
- Do not implement WS4 real Structured LLM, QA retrieval grading, or max-two-round retrieval behavior.
- Do not implement WS5 production `issue_lookup` / `issue_create` evidence/business completion; WS3 only freezes the injected business-mode dispatch and resume contract those later workstreams consume.
- Do not implement WS6+ observability, Prometheus, Docker completion, or evaluation runner work.
- Do not redesign PostgreSQL Job Queue claim/lease/heartbeat/retry/reaper semantics.
- Do not change ADR-0004 or the approved V1 Completion Design, and do not add an Alembic migration unless execution uncovers a design-blocking schema fact; the reviewed schema already contains the WS3-required fields.

## Current State

WS2 already persists `Run`, ordered `AgentEvent`, and aggregate-only `EXECUTE_AGENT_RUN` / `RESUME_AGENT_RUN` `BackgroundJob` rows transactionally. The repository already contains PostgreSQL queue claiming, leases, heartbeats, retry/backoff, reaping, `BackgroundWorker`, Run repositories, LangGraph graphs, PostgreSQL checkpointer support, and Task 13 interrupt/idempotency primitives. What is missing is the production Worker composition root, retry-aware handler contract, durable Run execution state machine, generic execute/resume graph adapter, and real EXECUTE/RESUME handlers that connect those existing pieces.

## Approved Architecture Boundary

The approved WS3 flow is:

```text
BackgroundJob
    -> BackgroundWorker claim/lease
    -> EXECUTE_AGENT_RUN / RESUME_AGENT_RUN handler
    -> reload durable Run + input/resume intent
    -> invoke injected LangGraph boundary using durable thread/checkpoint identity
    -> persist Run lifecycle + ordered AgentEvent outcome
    -> queue complete/retry/final-fail semantics remain owned by PostgreSQL Job Queue
```

WS3 may define and verify the generic `RunBusinessMode -> injected graph executor` dispatch contract, including `Command(resume=...)` and checkpoint identity. Concrete QA production dependencies belong to WS4; concrete Issue lookup/evidence/create production integration belongs to WS5. This Plan must stop rather than modify ADR-0004 or the approved V1 Completion Design if implementation proves those boundaries insufficient.

---

## Source-of-Truth Review and Preflight Findings

### Reviewed snapshot

The uploaded `it-outsourcing-knowledge-agent-ws2.zip` contains `.git` and reports:

```text
branch: feat/ws2-postgres-acceptance
HEAD:   a948de7f51bdc8b2cd591aa85e10ba24696c959b
```

The uploaded working tree is not clean:

```text
 M tests/unit/runtime/test_run_service.py
?? docs/superpowers/plans/2026-09-14-ws2-run-api-agent-event-sse-completed.md
```

The tracked diff in `tests/unit/runtime/test_run_service.py` is only removal of one extra blank line; the untracked completed document records the verified WS2 close-out. These are WS2 close-out artifacts and must not be mixed into a WS3 implementation commit.

### Mandatory real-server execution gate before Task 1

Run on the actual server, not in the review sandbox:

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent
conda activate it-agent

which python
python --version

git branch --show-current
git rev-parse HEAD
git status --short
git log --oneline -15

alembic current
alembic heads

ruff check src tests
mypy src
python -m pytest -q
```

Expected precondition before implementation:

```text
Python: project it-agent interpreter, Python >=3.12,<3.14
Alembic head: 0005_run_runtime_envelope
WS2 verified changes preserved
no unexplained dirty files
baseline Ruff PASS
baseline MyPy PASS
baseline pytest PASS with only explicitly out-of-scope live skips
```

If the real server is still dirty exactly like the ZIP, preserve the WS2 close-out as its own commit before creating the WS3 worktree. Do not use `git reset --hard`.

### Worktree gate

Use `superpowers:using-git-worktrees` before implementation. The reviewed ZIP is a normal checkout (`git-dir == git-common-dir`), not a linked worktree. Prefer a project-local ignored `.worktrees/` directory and create a dedicated branch such as:

```bash
git check-ignore -q .worktrees || {
  printf '\n.worktrees/\n' >> .gitignore
  git add .gitignore
  git commit -m "chore: ignore local worktrees"
}

git worktree add .worktrees/ws3-worker-execution -b feat/ws3-worker-execution
cd .worktrees/ws3-worker-execution
```

Run the full baseline again in the new worktree before the first RED.

### Current reusable implementation

The reviewed code already provides:

- `BackgroundJobModel` with aggregate-only payload identity, attempts, max attempts, locks, heartbeat, and lease expiry;
- `PostgresJobQueue.claim()` using `FOR UPDATE SKIP LOCKED`;
- queue `heartbeat()`, retry/backoff in `fail()`, and `reap_expired()`;
- `BackgroundWorker.run_once()/serve_forever()` and heartbeat loop;
- `HandlerRegistry` plus job type constants;
- `RunRecord`, `RunBusinessMode`, `RunStatus`, `AgentEventType`, `RunJobType`;
- WS2 `RunApplicationService` that atomically persists Run/input and enqueues `EXECUTE_AGENT_RUN` / `RESUME_AGENT_RUN`;
- `RunRepository` + `SqlAlchemyRunRepository` with row-locking reads, ordered event append, latest-event lookup, and status mutation;
- `SqlAlchemyQAGraphStore.load_query()` compatibility with the WS2 durable input event;
- `AgentState` containing only durable IDs/references;
- `build_project_qa_graph()` and `build_issue_create_graph()`;
- `async_postgres_saver()` for LangGraph PostgreSQL checkpoints;
- Task 13 interrupt node using LangGraph `interrupt()` and resume payload `{action, request_payload_hash}`;
- Task 13 idempotency/reconciliation service and `RECONCILE_ISSUE_CREATE` job type.

### Plan / Code Drift

1. `EXECUTE_AGENT_RUN` and `RESUME_AGENT_RUN` exist only as job vocabulary; no production handler executes them.
2. `BackgroundWorker` currently calls handlers with only `aggregate_id`, so a Run handler cannot see `attempts/max_attempts` and therefore cannot distinguish an intermediate retry from the final failed attempt when deciding whether to persist `RUN_FAILED`.
3. `RunRepository.set_status()` does not update `started_at` / `finished_at`; WS3 requires durable lifecycle timestamps.
4. No application/worker service currently implements idempotent `QUEUED → RUNNING`, retry-from-`RUNNING`, `WAITING_CONFIRMATION`, or terminal event projection.
5. No generic LangGraph worker adapter currently reconstructs the initial checkpoint-safe `AgentState`, reuses `thread_id`, detects an interrupt, or calls `Command(resume=...)`.
6. There is no Worker composition root analogous to `runtime/api.py`.
7. `HandlerRegistry` has no production registration builder.
8. `INGEST_DOCUMENT`, `DELETE_DOCUMENT`, and `RETENTION_SWEEP` have no current producer/production repository path in the reviewed runtime. They must be explicitly disabled or supplied through an injected handler policy; they must never be silently accepted/dropped.
9. `RECONCILE_ISSUE_CREATE` **is** emitted by existing Task 13 code, so WS3 must keep a deterministic real registration path for it without changing Task 13 idempotency semantics.
10. The existing schema already supports WS3. **No Alembic migration is planned for WS3.**

### Scope decision for the apparent §9.1 / WS5 overlap

The Design §9.1 says Worker dispatch is by frozen business mode, while the workstream table assigns concrete `issue_lookup` / `issue_create` business integration to WS5. WS3 therefore owns:

```text
RunBusinessMode → injected graph executor selection contract
checkpoint-safe execute/resume invocation mechanics
Run/Event lifecycle projection
```

WS3 does **not** own:

```text
production construction of the real QA graph dependencies (WS4)
production construction of the Issue lookup/evidence/create graph dependencies (WS5)
```

This keeps the WS3 acceptance boundary exactly as written: a queued Run is consumed by a real Worker handler and dispatched to an **injected graph**; an interrupted Run resumes from durable input/checkpoint without unsafe replay.

---

## Required WS3 Concern Coverage

The following approved planning concerns are explicit gates in this Plan rather than implicit implementation notes:

- **Worker job dispatch:** Tasks 1, 4, and 5 define the claimed-job handler contract, EXECUTE/RESUME dispatch, and production HandlerRegistry composition.
- **EXECUTE_AGENT_RUN:** Tasks 2-6 define durable load/start, graph invocation, outcome projection, retry behavior, and live PostgreSQL proof.
- **RESUME_AGENT_RUN:** Tasks 2-5 and 7 define durable resume-intent loading, same-thread checkpoint resume, `Command(resume=...)`, outcome projection, and process-boundary proof.
- **Run state transitions:** Task 2 owns idempotent lifecycle transitions and timestamps; Task 4 applies them around graph invocation.
- **AgentEvent persistence:** Tasks 2, 4, 6, and 7 enforce ordered durable start/resume/waiting/terminal events with duplicate suppression.
- **Transaction boundary:** Task 4 separates DB preparation and outcome transactions from graph/checkpointer invocation so a Run-row lock is not held during graph work.
- **Lease/retry/crash behavior:** Task 1 preserves queue ownership of lease/heartbeat/retry; Tasks 4 and 6 distinguish intermediate retries from final failure; Task 7 proves restart durability.
- **Idempotency:** Tasks 2, 4, 6, and 7 prevent duplicate start/resume/terminal events and duplicate post-terminal execution while preserving Task 13 side-effect idempotency.
- **Security / project ownership:** Worker trusts only the authorized durable WS2 Run identity; no JWT context is recreated in the Worker, and Task 13 permission checks remain at the write boundary.
- **Testability:** Graph execution, clocks, repositories/session factories, and runtime factories stay injectable; offline unit tests do not require RAGFlow or a live LLM.
- **Offline tests:** Tasks 1-5 establish RED -> GREEN unit/reliability coverage before live gates.
- **Live PostgreSQL gate:** Tasks 6-8 require real PostgreSQL queue, lifecycle, and checkpoint/restart verification with zero relevant skips.

---

## File Map Locked for WS3

### Create

- `src/project_agent/application/ports/run_graph.py` — worker-facing graph execution/resume protocol and normalized graph outcomes.
- `src/project_agent/application/services/run_execution.py` — durable Run execution preparation/outcome/final-failure state machine, independent of SQLAlchemy and LangGraph concrete classes.
- `src/project_agent/workers/run_graph.py` — generic LangGraph adapter that builds checkpoint-safe state, uses persisted `thread_id`, projects interrupts, and uses `Command(resume=...)`.
- `src/project_agent/workers/run_execution.py` — queue job handlers that split DB lifecycle transactions from graph invocation and use attempt metadata for retry/final-failure behavior.
- `src/project_agent/runtime/worker.py` — Worker composition root, handler registration policy, queue/checkpointer lifetime, and injectable graph factory.
- `tests/fakes/run_graph.py` — deterministic fake graph executor for worker lifecycle tests.
- `tests/unit/runtime/test_run_execution_service.py` — RED/GREEN tests for durable state-machine/idempotency rules.
- `tests/unit/workers/test_run_graph.py` — execute/resume LangGraph adapter contract tests.
- `tests/unit/workers/test_run_execution.py` — handler transaction/retry/crash/idempotency tests with fakes.
- `tests/unit/runtime/test_worker_runtime.py` — HandlerRegistry/bootstrap and disabled-job-policy tests.
- `tests/integration/workers/test_run_worker_postgres.py` — live PostgreSQL queue → Worker → injected graph → Run/Event persistence gate.
- `tests/integration/workers/test_run_resume_postgres.py` — live PostgreSQL checkpointer interrupt/restart/resume gate.

### Modify

- `src/project_agent/application/ports/job_queue.py` — expose claimed `QueuedJob` to handlers indirectly through the handler contract; no queue schema change.
- `src/project_agent/application/ports/run_repository.py` — add lifecycle timestamp mutation required by worker transitions.
- `src/project_agent/infrastructure/db/repositories/runs.py` — implement the lifecycle mutation without committing internally.
- `src/project_agent/workers/handlers.py` — change Worker handler contract from bare aggregate ID to the claimed `QueuedJob`; add an aggregate-ID compatibility adapter and explicit disabled-job handler/error.
- `src/project_agent/workers/main.py` — pass the claimed `QueuedJob` to the resolved handler; queue semantics remain unchanged.
- `src/project_agent/workers/issue_reconciliation.py` — adapt existing reconcile handler to the claimed-job contract while preserving aggregate-ID semantics.
- `src/project_agent/workers/retention.py` — adapt handler to the claimed-job contract only; do not redesign retention.
- `src/project_agent/config.py` — add explicit Worker enable/disable switches only where needed to make unsupported legacy job types fail at startup instead of being silently omitted.
- `.env.example` — document those Worker job switches.
- `tests/fakes/job_queue.py` — preserve fake behavior under the claimed-job handler contract.
- `tests/fakes/run_repository.py` — implement lifecycle timestamp mutation for tests.
- `tests/unit/workers/test_worker.py` — verify claimed job context reaches handlers and failure/retry behavior remains queue-owned.
- `tests/unit/runtime/test_run_repository.py` — verify lifecycle timestamps mutate without repository-level commit.
- `tests/reliability/test_retention_safety.py` — only signature adaptation if needed; retention safety assertions remain unchanged.

### Do not touch in WS3

- `src/project_agent/api/v1/runs.py`
- WS1 JWT/authentication flow except imports required by existing reconciliation wiring
- QA retrieval-grade logic
- real Structured LLM implementation
- Issue requirement/test Evidence retrieval/population
- Prometheus/observability implementation
- Docker/Compose completion
- evaluation harness
- ADR-0004
- `docs/superpowers/specs/2026-09-12-v1-completion-design.md`

---

## Task 1: Make Worker handlers retry-aware without changing PostgreSQL queue semantics

**Create:**
- None.

**Modify:**
- `src/project_agent/workers/handlers.py`
- `src/project_agent/workers/main.py`
- `src/project_agent/workers/issue_reconciliation.py`
- `src/project_agent/workers/retention.py`

**Tests:**
- `tests/unit/workers/test_worker.py`
- `tests/reliability/test_retention_safety.py`

**Do not touch:**
- PostgreSQL queue schema/model or Alembic migrations.
- WS2 Run API/SSE/resume persistence.
- Queue claim/lease/heartbeat/retry/backoff semantics.


**Files:**
- Modify: `src/project_agent/workers/handlers.py`
- Modify: `src/project_agent/workers/main.py`
- Modify: `src/project_agent/workers/issue_reconciliation.py`
- Modify: `src/project_agent/workers/retention.py`
- Modify: `tests/unit/workers/test_worker.py`
- Modify: `tests/reliability/test_retention_safety.py`

**Interfaces:**
- Consumes: existing `QueuedJob(job_id, job_type, aggregate_id, state, attempts, max_attempts, ...)`.
- Produces: `JobHandler = Callable[[QueuedJob], Awaitable[Any]]`.
- Produces: `AggregateIdHandlerAdapter` for existing handlers whose real business input remains `aggregate_id`.
- Preserves: `JobQueuePort.claim/heartbeat/complete/fail` behavior and `BackgroundJobModel` schema.

- [ ] **Step 1: Write the failing Worker contract test**

Add to `tests/unit/workers/test_worker.py`:

```python
@pytest.mark.asyncio
async def test_worker_passes_claimed_attempt_metadata_to_handler() -> None:
    queue = FakeJobQueue()
    queued = await queue.enqueue(
        EnqueueJobRequest(job_type="TEST", aggregate_id="agg-ctx", max_attempts=4)
    )
    seen: list[QueuedJob] = []

    async def handler(job: QueuedJob) -> None:
        seen.append(job)

    handlers = HandlerRegistry()
    handlers.register("TEST", handler)
    worker = BackgroundWorker(
        queue,
        handlers,
        worker_id="worker-1",
        settings=WorkerSettings(concurrency=1, heartbeat_seconds=60, poll_seconds=0.01),
    )

    assert await worker.run_once() == 1
    assert len(seen) == 1
    assert seen[0].job_id == queued.job_id
    assert seen[0].aggregate_id == "agg-ctx"
    assert seen[0].attempts == 1
    assert seen[0].max_attempts == 4
```

- [ ] **Step 2: Run the test and confirm the correct RED**

Run:

```bash
python -m pytest tests/unit/workers/test_worker.py::test_worker_passes_claimed_attempt_metadata_to_handler -v
```

Expected RED: current `BackgroundWorker` passes a `str` aggregate ID, so the handler receives no `.attempts`/`.max_attempts`.

- [ ] **Step 3: Implement the minimal handler contract**

In `workers/handlers.py`:

```python
JobHandler = Callable[[QueuedJob], Awaitable[Any]]
AggregateIdHandler = Callable[[str], Awaitable[Any]]

class AggregateIdHandlerAdapter:
    def __init__(self, handler: AggregateIdHandler) -> None:
        self._handler = handler

    async def __call__(self, job: QueuedJob) -> Any:
        return await self._handler(job.aggregate_id)
```

Update `ParseLimitedHandler.__call__` to receive/pass `QueuedJob`. Update `BackgroundWorker._process()` to call:

```python
handler = self._handlers.resolve(job.job_type)
await handler(job)
```

Adapt existing reconciliation/retention registration-facing callables without changing their business behavior.

- [ ] **Step 4: Run targeted Worker/reliability regression**

```bash
python -m pytest \
  tests/unit/workers/test_worker.py \
  tests/unit/workers/test_retry_policy.py \
  tests/reliability/test_worker_crash.py \
  tests/reliability/test_retention_safety.py -v
```

Expected: PASS; queue still owns retry/backoff/reaper behavior.

- [ ] **Step 5: Static checks**

```bash
ruff check src/project_agent/workers tests/unit/workers tests/reliability
mypy src
```

- [ ] **Step 6: Commit Task 1**

```bash
git add \
  src/project_agent/workers/handlers.py \
  src/project_agent/workers/main.py \
  src/project_agent/workers/issue_reconciliation.py \
  src/project_agent/workers/retention.py \
  tests/unit/workers/test_worker.py \
  tests/reliability/test_retention_safety.py
git commit -m "refactor(worker): pass claimed job context to handlers"
```

**Task 1 completion report must state:** requirement complete, RED observed, GREEN observed, retry regression PASS, Ruff/MyPy status, commit SHA.

---

## Task 2: Add durable Run lifecycle transition primitives

**Create:**
- `src/project_agent/application/services/run_execution.py`

**Modify:**
- `src/project_agent/application/ports/run_repository.py`
- `src/project_agent/infrastructure/db/repositories/runs.py`

**Tests:**
- Create `tests/unit/runtime/test_run_execution_service.py`.
- Modify `tests/fakes/run_repository.py`.
- Modify `tests/unit/runtime/test_run_repository.py`.

**Do not touch:**
- WS2 HTTP endpoints or authorization flow.
- LangGraph graph implementations.
- Database schema/migrations.


**Files:**
- Create: `src/project_agent/application/services/run_execution.py`
- Modify: `src/project_agent/application/ports/run_repository.py`
- Modify: `src/project_agent/infrastructure/db/repositories/runs.py`
- Modify: `tests/fakes/run_repository.py`
- Create: `tests/unit/runtime/test_run_execution_service.py`
- Modify: `tests/unit/runtime/test_run_repository.py`

**Interfaces:**
- Consumes: `RunRecord`, `AgentEventRecord`, WS2 lifecycle event vocabulary.
- Produces: `RunExecutionPreparation(run, invoke, resume_payload)`.
- Produces: `RunExecutionService.prepare_execute(run_id)`, `prepare_resume(run_id)`, `persist_outcome(run_id, outcome)`, `mark_final_failure(run_id, error_code)`.
- Produces repository method:

```python
async def set_lifecycle(
    self,
    *,
    run_id: UUID,
    status: RunStatus,
    started_at: datetime | None,
    finished_at: datetime | None,
) -> RunRecord: ...
```

- Preserves: WS2 `set_status()` for API resume transaction.

- [ ] **Step 1: Write RED tests for execute start and duplicate retry**

Core expectations in `tests/unit/runtime/test_run_execution_service.py`:

```python
@pytest.mark.asyncio
async def test_prepare_execute_marks_started_once_and_retry_reuses_running_run() -> None:
    repo, run = await seeded_run(status=RunStatus.QUEUED)
    await repo.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={"query_text": "hello"},
    )
    service = RunExecutionService(repo, clock=lambda: NOW)

    first = await service.prepare_execute(run.id)
    second = await service.prepare_execute(run.id)

    assert first.invoke is True
    assert second.invoke is True
    assert repo.runs[run.id].status is RunStatus.RUNNING
    assert repo.runs[run.id].started_at == NOW
    assert [e.event_type for e in repo.events[run.id]].count(AgentEventType.RUN_STARTED) == 1
```

Also add RED tests for:

```text
terminal execute retry -> invoke=False and no new event
WAITING_CONFIRMATION execute retry -> invoke=False
stale EXECUTE after a newer RUN_RESUME_QUEUED/RUN_RESUMED -> invoke=False
resume requires durable RUN_RESUME_QUEUED
first resume emits exactly one RUN_RESUMED
resume retry from RUNNING reuses existing resume intent without duplicate RUN_RESUMED
resume payload exposed to handler excludes no durable data and remains immutable copy
```

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/unit/runtime/test_run_execution_service.py -v
```

Expected RED: module/service/repository lifecycle method does not exist.

- [ ] **Step 3: Implement lifecycle repository method**

`SqlAlchemyRunRepository.set_lifecycle()` must lock the row with `FOR UPDATE`, set all three explicit lifecycle values, flush, and return `RunRecord`; it must **not commit**.

- [ ] **Step 4: Implement preparation logic using durable event ordering**

Use the sequence numbers of the latest relevant events to distinguish current intent:

```text
EXECUTE current intent:
  latest RUN_QUEUED exists
  and no later RUN_RESUME_QUEUED/RUN_RESUMED supersedes it

RESUME current intent:
  latest RUN_RESUME_QUEUED exists
  and it is later than the last RUN_STARTED intent
```

Preparation rules:

```text
QUEUED + valid EXECUTE intent
  -> RUNNING, started_at = existing or now, append RUN_STARTED once, invoke=True

RUNNING + same EXECUTE intent
  -> no duplicate event, invoke=True

QUEUED + valid RESUME intent
  -> RUNNING, preserve started_at, append RUN_RESUMED once, invoke=True + durable resume payload

RUNNING + same RESUME intent
  -> no duplicate event, invoke=True + same durable resume payload

WAITING_CONFIRMATION / terminal / superseded stale job
  -> invoke=False
```

- [ ] **Step 5: Add normalized graph outcome type before outcome tests**

Create `src/project_agent/application/ports/run_graph.py` with:

```python
class RunGraphOutcomeKind(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"

@dataclass(frozen=True, slots=True)
class RunGraphOutcome:
    kind: RunGraphOutcomeKind
    result_ref: str | None = None
    summary: str | None = None
    waiting_payload: dict[str, object] | None = None

class RunGraphExecutor(Protocol):
    async def execute(self, run: RunRecord) -> RunGraphOutcome: ...
    async def resume(
        self,
        run: RunRecord,
        resume_payload: dict[str, object],
    ) -> RunGraphOutcome: ...
```

- [ ] **Step 6: Write RED tests for outcome projection**

Cover all four normalized outcomes and final failure:

```text
SUCCEEDED -> status SUCCEEDED + finished_at + one RUN_SUCCEEDED
REFUSED -> status REFUSED + finished_at + one RUN_REFUSED
CANCELLED -> status CANCELLED + finished_at + one RUN_CANCELLED
WAITING_CONFIRMATION -> status WAITING_CONFIRMATION + finished_at remains null + one WAITING_CONFIRMATION
final failure -> status FAILED + finished_at + one RUN_FAILED
repeated persistence on an already terminal Run -> no duplicate terminal event
```

`WAITING_CONFIRMATION.waiting_payload` must include a string `request_payload_hash`; missing/invalid hash is a controlled execution error, not a persisted malformed waiting event.

- [ ] **Step 7: Implement minimal outcome projection**

Terminal payload shape:

```python
payload: dict[str, object] = {}
if outcome.result_ref is not None:
    payload["result_ref"] = outcome.result_ref
if outcome.summary is not None:
    payload["summary"] = outcome.summary
```

Failure event stores only stable error metadata:

```python
{"error_code": error_code}
```

Do not store exception messages or stack traces in AgentEvent payloads.

- [ ] **Step 8: GREEN + repository regression**

```bash
python -m pytest \
  tests/unit/runtime/test_run_execution_service.py \
  tests/unit/runtime/test_run_repository.py \
  tests/unit/runtime/test_run_service.py -v
ruff check src/project_agent/application src/project_agent/infrastructure/db/repositories tests/unit/runtime
mypy src
```

- [ ] **Step 9: Commit Task 2**

```bash
git add \
  src/project_agent/application/ports/run_graph.py \
  src/project_agent/application/ports/run_repository.py \
  src/project_agent/application/services/run_execution.py \
  src/project_agent/infrastructure/db/repositories/runs.py \
  tests/fakes/run_repository.py \
  tests/unit/runtime/test_run_execution_service.py \
  tests/unit/runtime/test_run_repository.py
git commit -m "feat(worker): add durable run execution lifecycle"
```

---

## Task 3: Implement the generic LangGraph execute/resume boundary

**Create:**
- `src/project_agent/workers/run_graph.py`
- `tests/fakes/run_graph.py`

**Modify:**
- None.

**Tests:**
- Create `tests/unit/workers/test_run_graph.py`.

**Do not touch:**
- Real Structured LLM/RAGFlow production wiring (WS4).
- Issue evidence/business graph completion (WS5).
- Existing graph business-node semantics except through the injected executor contract.


**Files:**
- Create: `src/project_agent/workers/run_graph.py`
- Create: `tests/fakes/run_graph.py`
- Create: `tests/unit/workers/test_run_graph.py`

**Interfaces:**
- Consumes: an injected mapping `RunBusinessMode -> compiled graph-like object` exposing async `ainvoke`.
- Consumes: `RunRecord` and durable resume payload.
- Produces: `LangGraphRunExecutor` implementing `RunGraphExecutor`.
- Uses checkpoint identity:

```python
config = {"configurable": {"thread_id": str(run.thread_id)}}
```

- Execute input remains checkpoint-safe IDs only:

```python
{
    "run_id": str(run.id),
    "thread_id": str(run.thread_id),
    "user_id": str(run.user_id),
    "project_id": str(run.project_id),
    "route": None,
    "last_error_code": None,
}
```

- Resume input uses LangGraph `Command(resume=...)` with the same `thread_id` config.

- [ ] **Step 1: Write RED test for execute identity**

Use a fake compiled graph that records its `ainvoke(input, config)` calls. Assert exact `run_id`, `thread_id`, `user_id`, explicit `project_id`, and identical `configurable.thread_id`.

- [ ] **Step 2: Write RED test for resume command**

For durable payload:

```python
{
    "action": "confirm",
    "request_payload_hash": "a" * 64,
    "actor_id": str(run.user_id),
}
```

assert the graph receives a real `langgraph.types.Command` whose resume value is only:

```python
{
    "action": "confirm",
    "request_payload_hash": "a" * 64,
}
```

The durable `actor_id` remains an audit field; the graph uses the original durable Run `user_id`, and the Task 13 node still performs the confirmation/write permission checks.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/unit/workers/test_run_graph.py -v
```

Expected RED: `LangGraphRunExecutor` does not exist.

- [ ] **Step 4: Implement graph selection and controlled unavailable-mode error**

```python
class RunGraphUnavailable(RuntimeError):
    pass
```

An absent business-mode graph raises `RunGraphUnavailable(run.business_mode.value)`. This is visible to queue retry/failure; it is never treated as a successful no-op.

- [ ] **Step 5: Implement interrupt/result projection**

Projection rules:

```text
result contains exactly one LangGraph interrupt with a dict value
  -> WAITING_CONFIRMATION, waiting_payload = interrupt.value

route == "refusal"
  -> REFUSED, result_ref = answer_id if present, summary = last_error_code if present

route == "cancelled"
  -> CANCELLED

otherwise
  -> SUCCEEDED, result_ref = first present reference among
     answer_id, issue_candidate_id, issue_creation_id, issue_draft_id
```

Multiple simultaneous interrupts or a non-dict interrupt value raise a controlled `RunGraphContractError` so malformed graph state is not persisted as valid user input.

- [ ] **Step 6: GREEN and checkpoint-safe state regression**

```bash
python -m pytest \
  tests/unit/workers/test_run_graph.py \
  tests/unit/agent/test_state_references.py \
  tests/unit/issues/test_interrupt_node.py -v
ruff check src/project_agent/workers tests/unit/workers tests/unit/agent tests/unit/issues
mypy src
```

- [ ] **Step 7: Commit Task 3**

```bash
git add \
  src/project_agent/workers/run_graph.py \
  tests/fakes/run_graph.py \
  tests/unit/workers/test_run_graph.py
git commit -m "feat(worker): add langgraph execute resume adapter"
```

---

## Task 4: Implement `EXECUTE_AGENT_RUN` and `RESUME_AGENT_RUN` queue handlers

**Create:**
- `src/project_agent/workers/run_execution.py`

**Modify:**
- None unless a preceding Task interface requires a reviewed signature correction.

**Tests:**
- Create `tests/unit/workers/test_run_execution.py`.

**Do not touch:**
- `PostgresJobQueue.fail()` retry ownership or lease semantics.
- WS2 Run/resume HTTP API.
- WS4/WS5 graph business behavior.


**Files:**
- Create: `src/project_agent/workers/run_execution.py`
- Create: `tests/unit/workers/test_run_execution.py`

**Interfaces:**
- Consumes: claimed `QueuedJob`, `async_sessionmaker[AsyncSession]`, `RunGraphExecutor`.
- Produces:

```python
class ExecuteAgentRunHandler:
    async def __call__(self, job: QueuedJob) -> None: ...

class ResumeAgentRunHandler:
    async def __call__(self, job: QueuedJob) -> None: ...
```

- Transaction boundaries:

```text
transaction A: lock Run -> prepare idempotent start/resume -> append start event -> commit
no Run row lock held here: invoke graph/checkpointer
transaction B: lock Run -> persist waiting/terminal outcome -> commit
```

- [ ] **Step 1: Write RED tests for successful execute and resume**

Use `FakeRunRepository` + fake transaction/session harness or an injectable lifecycle-service factory. Assert:

```text
EXECUTE calls graph.execute exactly once for a fresh queued Run
RESUME calls graph.resume with the durable RUN_RESUME_QUEUED payload
successful outcome writes terminal state/event
waiting outcome keeps finished_at null
```

- [ ] **Step 2: Write RED tests for duplicate/retry semantics**

Cover:

```text
job retry after RUN_STARTED -> graph may be invoked again, but RUN_STARTED count stays 1
job retry after RUN_RESUMED -> RUN_RESUMED count stays 1
retry after terminal outcome -> graph is not invoked again
stale EXECUTE after resume intent -> graph is not invoked
```

- [ ] **Step 3: Write RED tests for failure/retry semantics**

Given `QueuedJob(attempts=1, max_attempts=3)` and graph raises `TimeoutError`:

```text
handler re-raises
Run remains non-terminal RUNNING
no RUN_FAILED event yet
```

Given `QueuedJob(attempts=3, max_attempts=3)` and graph raises `TimeoutError`:

```text
handler durably marks Run FAILED + one RUN_FAILED(error_code="TimeoutError")
handler re-raises so PostgresJobQueue.fail() marks the job FAILED
```

A retry after final-failure persistence must not append a second `RUN_FAILED`.

- [ ] **Step 4: Run RED**

```bash
python -m pytest tests/unit/workers/test_run_execution.py -v
```

- [ ] **Step 5: Implement the two-phase handlers**

Use `UUID(job.aggregate_id)` validation. Each DB phase constructs `SqlAlchemyRunRepository(session)` and `RunExecutionService(...)`; each phase commits explicitly after the service method succeeds and rolls back through the session context on exception.

Do **not** hold an SQL transaction open while waiting on LangGraph, RAGFlow, an LLM, or the Sandbox tracker.

- [ ] **Step 6: GREEN + existing Worker regression**

```bash
python -m pytest \
  tests/unit/workers/test_run_execution.py \
  tests/unit/workers/test_worker.py \
  tests/reliability/test_worker_crash.py -v
ruff check src/project_agent/workers tests/unit/workers tests/reliability
mypy src
```

- [ ] **Step 7: Commit Task 4**

```bash
git add \
  src/project_agent/workers/run_execution.py \
  tests/unit/workers/test_run_execution.py
git commit -m "feat(worker): execute and resume durable runs"
```

---

## Task 5: Build the production Worker runtime and deterministic HandlerRegistry policy

**Create:**
- `src/project_agent/runtime/worker.py`

**Modify:**
- `src/project_agent/config.py`
- `.env.example`
- `src/project_agent/workers/issue_reconciliation.py` only for production dependency wiring that preserves Task 13 behavior.

**Tests:**
- Create `tests/unit/runtime/test_worker_runtime.py`.
- Modify `tests/unit/test_config.py`.

**Do not touch:**
- Document API to begin emitting `INGEST_DOCUMENT` / `DELETE_DOCUMENT`.
- Retention business policy/repository design.
- Real QA/Issue graph dependency construction owned by WS4/WS5.


**Files:**
- Create: `src/project_agent/runtime/worker.py`
- Modify: `src/project_agent/config.py`
- Modify: `.env.example`
- Modify: `src/project_agent/workers/issue_reconciliation.py`
- Create: `tests/unit/runtime/test_worker_runtime.py`
- Modify: `tests/unit/test_config.py`

**Interfaces:**
- Produces:

```python
@dataclass(slots=True)
class WorkerRuntime:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    queue: PostgresJobQueue
    handlers: HandlerRegistry
    worker: BackgroundWorker
```

- Produces `build_worker_runtime(settings, *, graph_executor_factory=...)` as an async context manager.
- Production queue settings come directly from existing `Settings.worker_*` values.
- Production worker settings come from the same `Settings.worker_*` values.

### Explicit job registration decisions

```text
EXECUTE_AGENT_RUN        -> enabled, real ExecuteAgentRunHandler
RESUME_AGENT_RUN         -> enabled, real ResumeAgentRunHandler
RECONCILE_ISSUE_CREATE   -> enabled, real existing Task 13 reconciliation path
INGEST_DOCUMENT          -> disabled for WS3; current document API does not enqueue it
DELETE_DOCUMENT          -> disabled for WS3; current document API does not enqueue it
RETENTION_SWEEP          -> controlled by RETENTION_SWEEP_ENABLED; if enabled without an
                            injected concrete RetentionRepository, Worker startup fails visibly
```

This is a deterministic configuration contract, not silent omission. Later work may supply concrete handlers without changing `BackgroundWorker`.

- [ ] **Step 1: Write RED tests for registry contents and startup failures**

`tests/unit/runtime/test_worker_runtime.py` must assert:

```text
run handlers are always registered
reconciliation is registered when its existing dependencies are supplied
unknown job type still raises UnknownJobType
explicitly disabled document jobs are not silently registered
RETENTION_SWEEP_ENABLED=true without retention repository -> WorkerConfigurationError at startup
RETENTION_SWEEP_ENABLED=false -> Worker starts without retention handler
```

- [ ] **Step 2: Write RED test for real settings projection**

Assert the runtime creates:

```python
PostgresJobQueue(
    lease_seconds=settings.worker_lease_seconds,
    retry_base_seconds=settings.worker_retry_base_seconds,
    retry_max_seconds=settings.worker_retry_max_seconds,
)
```

and:

```python
WorkerSettings(
    concurrency=settings.worker_concurrency,
    claim_limit=settings.worker_claim_limit,
    heartbeat_seconds=settings.worker_heartbeat_seconds,
    poll_seconds=settings.worker_poll_seconds,
)
```

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/unit/runtime/test_worker_runtime.py tests/unit/test_config.py -v
```

- [ ] **Step 4: Implement Worker runtime resource lifetime**

The context manager must:

```text
create SQLAlchemy engine/session factory
create PostgresJobQueue
open async_postgres_saver(settings.database_url)
obtain the injected WS3 graph executor/compiled graphs using that saver
build real Run handlers
build deterministic HandlerRegistry
build BackgroundWorker
on exit: stop worker if needed, close checkpointer context, dispose engine
```

Do not create HTTP/RAGFlow/LLM resources in WS3 unless the injected graph factory explicitly supplies them; those are WS4/WS5 concerns.

- [ ] **Step 5: Wire existing reconciliation without changing its safety model**

The production reconciliation handler must create/use the existing:

```text
SqlAlchemyIssueWorkflowRepository
PostgresIdempotencyStore
SandboxProjectTrackerAdapter
SqlAlchemyProjectAuthorizationRepository + AuthorizationService
IssueCreationService.reconcile()
```

through a job-scoped DB session/factory. It must preserve Task 13's prior idempotency barrier requirement and must not perform an unconfirmed blind write.

- [ ] **Step 6: GREEN + safety regression**

```bash
python -m pytest \
  tests/unit/runtime/test_worker_runtime.py \
  tests/unit/test_config.py \
  tests/reliability/test_issue_response_lost.py \
  tests/security/test_reconcile_requires_idempotency_barrier.py \
  tests/security/test_issue_permission_recheck.py \
  tests/security/test_unconfirmed_issue_create.py -v
ruff check src tests
mypy src
```

- [ ] **Step 7: Commit Task 5**

```bash
git add \
  .env.example \
  src/project_agent/config.py \
  src/project_agent/runtime/worker.py \
  src/project_agent/workers/issue_reconciliation.py \
  tests/unit/runtime/test_worker_runtime.py \
  tests/unit/test_config.py
git commit -m "feat(worker): add production runtime and handler registry"
```

---

## Task 6: Prove live PostgreSQL queue → Worker → Run/Event durability

**Create:**
- None in production code.

**Modify:**
- None in production code during the gate itself; any discovered defect starts a separate `systematic-debugging` RED/GREEN cycle against the responsible WS3 file.

**Tests:**
- Create `tests/integration/workers/test_run_worker_postgres.py`.

**Do not touch:**
- RAGFlow/LLM integrations.
- Database schema/migrations merely to make the test easier.
- Existing queue semantics unless a reproduced WS3 defect proves a correction is required.


**Files:**
- Create: `tests/integration/workers/test_run_worker_postgres.py`

**Interfaces:**
- Uses real `PostgresJobQueue`, `BackgroundWorker`, `SqlAlchemyRunRepository`, WS2 tables, and an injected deterministic fake graph executor.
- Does not require RAGFlow or a real LLM.

- [ ] **Step 1: Write live test for `EXECUTE_AGENT_RUN` success**

With `RUN_POSTGRES_INTEGRATION=1`:

1. seed company/client/project/membership/thread/run as needed;
2. persist `RUN_QUEUED(query_text=...)` and a real `EXECUTE_AGENT_RUN` job;
3. run one real `BackgroundWorker.run_once()`;
4. assert queue job `SUCCEEDED`;
5. assert Run `SUCCEEDED`, `started_at != None`, `finished_at != None`;
6. assert ordered events contain exactly one `RUN_STARTED` and one `RUN_SUCCEEDED` after `RUN_QUEUED`.

- [ ] **Step 2: Write live retry test**

Use a graph executor that raises on the first call and succeeds on the second. Configure zero retry delay for the test. Assert:

```text
first claim -> queue returns to PENDING, Run remains RUNNING, one RUN_STARTED
second claim -> queue SUCCEEDED, Run SUCCEEDED, still one RUN_STARTED, one RUN_SUCCEEDED
```

- [ ] **Step 3: Write live final-failure test**

Use `max_attempts=2` and an executor that always raises. Assert after second attempt:

```text
background job FAILED
Run FAILED
finished_at set
exactly one RUN_FAILED with error_code only
```

- [ ] **Step 4: Run the live PostgreSQL gate**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

alembic upgrade head
python -m pytest tests/integration/workers/test_run_worker_postgres.py -v
```

Acceptance: all WS3 PostgreSQL tests PASS, **0 skipped**.

- [ ] **Step 5: Run existing queue live regression**

```bash
python -m pytest tests/integration/jobs/test_claim.py -v
```

Acceptance: claim/lease/reaper tests PASS, **0 skipped** under the live flag.

- [ ] **Step 6: Commit Task 6**

```bash
git add tests/integration/workers/test_run_worker_postgres.py
git commit -m "test(worker): prove postgres run job durability"
```

---

## Task 7: Prove PostgreSQL checkpoint interrupt → process boundary → `RESUME_AGENT_RUN`

**Create:**
- None in production code.

**Modify:**
- `src/project_agent/workers/run_graph.py` only if the live checkpoint test reproduces a real WS3 defect.
- `src/project_agent/workers/run_execution.py` only if the live checkpoint test reproduces a real WS3 defect.

**Tests:**
- Create `tests/integration/workers/test_run_resume_postgres.py`.

**Do not touch:**
- WS2 resume API contract.
- WS5 Issue evidence/business completion.
- Task 13 side-effect/idempotency semantics to bypass the real resume mechanism.


**Files:**
- Create: `tests/integration/workers/test_run_resume_postgres.py`
- Modify only if required by a real discovered defect: `src/project_agent/workers/run_graph.py`, `src/project_agent/workers/run_execution.py`

**Interfaces:**
- Uses `async_postgres_saver()` and a minimal test LangGraph independent of WS5 business dependencies.
- Uses the production `LangGraphRunExecutor` and real Worker handlers.

- [ ] **Step 1: Build the minimal resumable test graph**

The test graph contains an interrupt node and one post-confirmation side-effect counter:

```python
async def await_confirmation(state: dict[str, object]) -> dict[str, object]:
    from langgraph.types import interrupt
    resume = interrupt(
        {
            "request_payload_hash": "a" * 64,
            "tool_name": "create_issue",
        }
    )
    return {"route": "resumed", "resume": resume}
```

A following node increments a test-owned durable/counted marker exactly once and returns a successful terminal route. The graph is compiled with the live PostgreSQL saver.

- [ ] **Step 2: Write live interrupt test**

Drive a real `EXECUTE_AGENT_RUN` job through `BackgroundWorker`. Assert:

```text
Run WAITING_CONFIRMATION
finished_at is null
WAITING_CONFIRMATION event contains request_payload_hash
initial background job SUCCEEDED because reaching a durable interrupt is a successful job outcome
checkpoint exists under configurable.thread_id == Run.thread_id
post-confirmation side effect count == 0
```

- [ ] **Step 3: Simulate a separate Worker/process boundary**

Dispose the first Worker/runtime context completely. Create a new runtime/checkpointer context from the same `DATABASE_URL` and the same persisted Run/Thread.

Persist the WS2-compatible durable resume event/job (either by calling the real WS2 application service with authorized fixtures or by reproducing its exact durable transaction in this integration test):

```json
{
  "action": "confirm",
  "request_payload_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "actor_id": "<original-run-user-id>"
}
```

- [ ] **Step 4: Execute real `RESUME_AGENT_RUN`**

Assert:

```text
new Worker loads the durable Run and latest RUN_RESUME_QUEUED payload
LangGraph receives Command(resume=...)
configurable.thread_id is unchanged
resume continues from the saved interrupt rather than rebuilding unsafe pre-interrupt work
post-confirmation side-effect counter becomes exactly 1
Run becomes SUCCEEDED
exactly one RUN_RESUMED and one terminal event are persisted
```

- [ ] **Step 5: Prove duplicate/retry resume safety**

Re-run the same claimed resume handler after the Run is terminal or simulate recovery after terminal Run persistence before queue completion. Assert:

```text
graph is not invoked again for the terminal Run
post-confirmation side-effect count remains 1
no duplicate RUN_RESUMED
no duplicate terminal AgentEvent
```

This is the WS3 runtime proof. The stronger real Sandbox Issue idempotency/reconciliation proof remains covered by existing Task 13 tests and later WS5 end-to-end integration.

- [ ] **Step 6: Run live checkpoint gates**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

python -m pytest \
  tests/integration/agent/test_postgres_checkpointer.py \
  tests/integration/workers/test_run_resume_postgres.py -v
```

Acceptance: all relevant checkpoint/worker tests PASS, **0 skipped**.

- [ ] **Step 7: Commit Task 7**

```bash
git add tests/integration/workers/test_run_resume_postgres.py
git add src/project_agent/workers/run_graph.py src/project_agent/workers/run_execution.py 2>/dev/null || true
git commit -m "test(worker): prove durable checkpoint resume"
```

Before committing, verify `git diff --cached --name-only` contains only files intentionally changed by this task.

---

## Task 8: Full WS3 verification, scope audit, and completion document

**Create:**
- `docs/superpowers/plans/2026-09-16-ws3-worker-execution-completed.md` only after every required gate passes.

**Modify:**
- None as part of the completion task. A failing gate must start a new `systematic-debugging` cycle before any production modification.

**Tests:**
- No new test file is planned; execute the targeted, static, full-regression, and live PostgreSQL/checkpointer suites defined below and record exact results.

**Do not touch:**
- Production behavior merely to make completion documentation green.
- WS4+ scope.
- ADR-0004 or the approved V1 Completion Design.


**Files:**
- Create only after every gate passes: `docs/superpowers/plans/2026-09-16-ws3-worker-execution-completed.md`
- No production behavior changes are allowed in this task unless a failing gate starts a new `systematic-debugging` cycle.

- [ ] **Step 1: Targeted WS3 offline suite**

```bash
python -m pytest \
  tests/unit/runtime/test_run_execution_service.py \
  tests/unit/runtime/test_worker_runtime.py \
  tests/unit/workers/test_run_graph.py \
  tests/unit/workers/test_run_execution.py \
  tests/unit/workers/test_worker.py \
  tests/reliability/test_worker_crash.py \
  tests/reliability/test_issue_response_lost.py \
  tests/security/test_reconcile_requires_idempotency_barrier.py \
  tests/security/test_issue_permission_recheck.py \
  tests/security/test_unconfirmed_issue_create.py -v
```

- [ ] **Step 2: Static checks**

```bash
ruff check src tests
mypy src
```

- [ ] **Step 3: Full offline regression**

```bash
python -m pytest -q
```

Record the exact pass/skip count. Do not represent optional live skips as PASS.

- [ ] **Step 4: Required live PostgreSQL + checkpointer gate**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

alembic current
alembic heads

python -m pytest \
  tests/integration/jobs/test_claim.py \
  tests/integration/agent/test_postgres_checkpointer.py \
  tests/integration/workers/test_run_worker_postgres.py \
  tests/integration/workers/test_run_resume_postgres.py -v
```

Acceptance:

```text
migration head is current
0 failed
0 relevant skipped
queue claim/lease/retry/reaper PASS
Run execute durability PASS
interrupt/checkpoint restart/resume PASS
```

- [ ] **Step 5: Full regression again with PostgreSQL live flag enabled**

```bash
python -m pytest -q
```

Record exact counts and identify every remaining skip by file/reason. Any skip in the WS3 files above is a blocker. The known RAGFlow project-isolation live skip may remain out of WS3 scope if its prerequisite is not enabled.

- [ ] **Step 6: Scope-creep audit**

```bash
git diff --name-only <WS3_BASE_SHA>..HEAD
git log --oneline <WS3_BASE_SHA>..HEAD
git diff --check <WS3_BASE_SHA>..HEAD
```

Reject the completion claim if the diff contains unplanned WS4–WS8 implementation such as a real LLM provider, retrieval-grade loop, requirement/test Evidence completion, Prometheus, Docker deployment completion, or evaluation runner.

- [ ] **Step 7: Architecture-lock audit**

Confirm no change was needed to:

```text
docs/adr/0004-v1-architecture-lock.md
docs/superpowers/specs/2026-09-12-v1-completion-design.md
```

If implementation actually requires such a change, **do not create the completed document**; report a design blocker instead.

- [ ] **Step 8: Write the completion document only after all gates pass**

The completion document must include:

```text
Status: WS3 COMPLETE
branch + HEAD
base SHA
Task-by-Task commit SHAs
Ruff result
MyPy result
full pytest result
live PostgreSQL/checkpointer commands + exact results
remaining skips and why they are outside WS3
scope audit
git status
```

- [ ] **Step 9: Verify clean expected Git state**

```bash
git status --short
git diff --check
```

The only uncommitted file at completion review should be the newly written completion document, if the team intentionally reviews it before its own docs commit.

- [ ] **Step 10: Commit WS3 close-out**

```bash
git add docs/superpowers/plans/2026-09-16-ws3-worker-execution-completed.md
git commit -m "docs(ws3): record worker execution acceptance"
```

---

## Acceptance Boundary

WS3 is complete only when all of the following are demonstrated with real evidence:

```text
BackgroundJob(EXECUTE_AGENT_RUN)
  -> real Postgres claim/lease
  -> ExecuteAgentRunHandler
  -> durable Run RUNNING + one RUN_STARTED
  -> injected graph using Run.thread_id checkpoint identity
  -> durable WAITING_CONFIRMATION or terminal Run/Event
  -> queue completion/failure
```

and:

```text
WAITING_CONFIRMATION
  -> WS2 durable RUN_RESUME_QUEUED + RESUME_AGENT_RUN
  -> separate/new Worker process context
  -> ResumeAgentRunHandler
  -> Command(resume=...) with same thread_id/checkpoint
  -> one RUN_RESUMED
  -> terminal Run/Event
  -> no unsafe duplicate replay in the WS3 checkpoint test
```

Also required:

```text
final exhausted worker exception -> background job FAILED + Run FAILED + one RUN_FAILED
lease expiry/reaper retry remains functional
terminal duplicate jobs are idempotent no-ops
no new migration
no WS4+ business completion pulled forward
Task 13 permission/idempotency/reconciliation safety regression stays green
```

---

## Final Verification Commands

Offline:

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws3-worker-execution
conda activate it-agent

ruff check src tests
mypy src
python -m pytest -q
```

Live PostgreSQL/checkpointer:

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

alembic current
alembic heads

python -m pytest \
  tests/integration/jobs/test_claim.py \
  tests/integration/agent/test_postgres_checkpointer.py \
  tests/integration/workers/test_run_worker_postgres.py \
  tests/integration/workers/test_run_resume_postgres.py -v

python -m pytest -q
```

Git review:

```bash
git diff --check
git status --short
git log --oneline --decorate -15
```

---

## Plan Self-Review

### 1. Spec coverage

Covered directly:

- Worker production bootstrap -> Task 5.
- real HandlerRegistry -> Task 5.
- `EXECUTE_AGENT_RUN` -> Tasks 2, 4, 6.
- `RESUME_AGENT_RUN` -> Tasks 2, 3, 4, 7.
- deterministic registration decisions for existing job vocabulary -> Task 5.
- Run state/event transitions -> Task 2.
- checkpoint identity and `Command(resume=...)` -> Tasks 3 and 7.
- retry/lease/reaper semantics -> Tasks 1, 4, 6 plus existing queue regression.
- crash/restart durability -> Tasks 6 and 7.
- duplicate execution protection -> Tasks 2, 4, 7.
- fake adapter/DI testability -> Tasks 3–5.
- PostgreSQL live acceptance -> Tasks 6–8.
- no WS4/WS5 scope creep -> Global Constraints, Scope decision, Task 8 scope audit.

No WS3 Design requirement is left without an implementation or verification task.

### 2. Placeholder scan

The Plan contains no implementation `TBD`, `TODO`, “implement later”, or unspecified “add tests/error handling” steps. The only intentionally deferred capabilities are explicitly assigned by the approved Design to WS4/WS5, and WS3 defines the injected runtime contract they will consume.

### 3. Type/interface consistency

Checked:

```text
QueuedJob flows HandlerRegistry -> BackgroundWorker -> all WS3 handlers
RunGraphExecutor returns RunGraphOutcome for both execute and resume
RunExecutionService owns durable lifecycle transitions
Run handlers own transaction boundaries + retry-attempt decision
LangGraphRunExecutor owns thread_id/config + Command(resume)
WorkerRuntime owns resource lifetime/registration only
```

No task requires a function or type with a different name in a later task.

### 4. Migration check

No new persistence field is required by this plan. Existing `agent_runs`, `agent_events`, `background_jobs`, and the WS2 `0005_run_runtime_envelope` migration are sufficient. A new Alembic revision during WS3 would require a specific newly discovered defect and a Plan revision before implementation.

### 5. Design-blocker check

No ADR-0004 or V1 Completion Design change is required for this Plan. The apparent Worker/WS5 overlap is resolved by freezing an injected graph-dispatch contract in WS3 while leaving concrete QA/Issue business dependency wiring to WS4/WS5, consistent with the WS3 acceptance wording.
