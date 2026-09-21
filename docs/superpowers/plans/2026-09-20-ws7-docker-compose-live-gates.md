# WS7 Docker / Compose + Live Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the V1 deployment boundary with one reusable application image, a real `postgres` + `app-api` + `app-worker` Compose topology, and mandatory process-boundary live acceptance for QA and Issue flows.

**Architecture:** Preserve every WS1–WS6 business/runtime contract. Add only the missing runtime composition seam: one default Worker routes the persisted `RunBusinessMode` to the existing QA or Issue executor, one thin Worker CLI owns process lifetime, one image serves API/Worker/ops commands, Compose supplies container-only provider addresses, and a mandatory WS7 runner proves provider gates plus real API→PostgreSQL→Worker→graph end-to-end behavior with sanitized evidence.

**Tech Stack:** Python 3.12, FastAPI/Uvicorn, SQLAlchemy/asyncpg, PostgreSQL 16, LangGraph PostgreSQL checkpointing, RAGFlow v0.26.4 companion stack, OpenAI-compatible Structured LLM, Docker 29+, Docker Compose v5, pytest, Ruff, MyPy.

**Spec:** `docs/superpowers/specs/2026-09-20-ws7-docker-compose-live-gates-design.md`

## Global Constraints

- Frozen base is `be1c5d702e7e65582ff59fbfdd6740d394e8fad7` on branch `feat/ws7`.
- WS1–WS6 are FINAL COMPLETE; do not re-plan or redesign their business semantics.
- Preserve JWT identity + PostgreSQL membership authorization and explicit `project_id` isolation.
- Preserve Run/Event/SSE ordering, `WAITING_CONFIRMATION` non-terminal semantics, queue lease/heartbeat/retry/final-failure behavior, and durable resume intent.
- Preserve LangGraph PostgreSQL checkpointing as the resume boundary.
- Preserve RAGFlow retrieval/evidence/citation boundaries and Structured LLM controlled behavior.
- Preserve Issue confirmation, idempotency, response-loss reconciliation, and Sandbox tracker behavior.
- Preserve WS6 structured logging, bounded metric labels, token-cost policy, and sanitization.
- Do not add Redis, Celery, ARQ, MinIO, Kubernetes, Prometheus Server, Grafana, a second vector DB, or a replacement RAG stack.
- Do not add an Alembic migration unless a new WS7 RED proves schema head `0005_run_runtime_envelope` cannot satisfy a frozen requirement.
- Do not add a new application runtime Python dependency solely for WS7.
- RAGFlow remains a separate companion stack; application containers use `http://host.docker.internal:9380` on the verified Linux server with `host-gateway` mapping.
- Required WS7 live gates may skip in ordinary repository runs, but a skip during the explicit WS7 required-live runner is FAILURE/INCOMPLETE, never PASS.
- Implementation is exactly three Tasks. Each Task gets exactly one final implementation commit. The Design and Plan documentation freeze commits are preparation commits and are not Task commits.

## Frozen File Map

**Task 1 creates:**
- `Dockerfile` — one reusable Python 3.12 production image.
- `.dockerignore` — prevent secrets/caches/worktrees/artifacts entering build context.
- `src/project_agent/cli/__init__.py` — CLI package marker.
- `src/project_agent/cli/worker.py` — Worker process entrypoint and signal-safe lifetime.
- `src/project_agent/runtime/run_graph.py` — thin production QA/Issue RunGraph router.
- `tests/unit/runtime/test_run_graph_runtime.py` — router behavior/closure tests.
- `tests/unit/cli/test_worker.py` — Worker CLI lifetime/failure tests.

**Task 1 modifies:**
- `src/project_agent/runtime/worker.py` — default production composition becomes QA + Issue.
- `tests/unit/runtime/test_worker_runtime.py` — assert unified default composition and preserved injection/resource ownership.
- `pyproject.toml` — expose `project-agent-worker` script.

**Task 2 creates:**
- `tests/integration/deployment/test_compose_contract.py` — rendered Compose topology/config assertions.

**Task 2 modifies:**
- `compose.yaml` — exactly `postgres`, `app-api`, `app-worker`.
- `.env.example` — document host values and container overrides without secrets.
- `src/project_agent/api/v1/health.py` — `/ready` proves settings + PostgreSQL only.
- `tests/integration/api/test_health.py` — readiness RED/GREEN and sanitized failure coverage.

**Task 3 creates:**
- `scripts/run_ws7_live_gates.py` — required-live orchestrator/evidence writer.
- `tests/integration/deployment/test_ws7_live_runner.py` — mandatory-gate/skip/redaction/summary tests.
- `tests/live/conftest.py` — unique live fixtures, JWT, polling, cleanup helpers.
- `tests/live/test_ws7_compose_qa.py` — real Compose QA process-boundary gate.
- `tests/live/test_ws7_compose_issue.py` — real Compose Issue interrupt/resume/idempotency gate.
- `docs/runbooks/ws7-compose-live-gates.md` — operator commands and failure interpretation.

**Task 3 modifies:**
- `.gitignore` — ignore `artifacts/ws7-live/` evidence.

No other production file is planned. If execution proves another file is required, record a plan ruling before touching it.

## Review Focus

1. **Worker receives any persisted shipped business mode:** `qa`, `issue_lookup`, and `issue_create` must dispatch through one default production Worker without changing Run semantics; pinned by `test_execute_routes_*` and `test_default_worker_runtime_builds_unified_qa_and_issue_executor` in Task 1.
2. **Worker termination while idle or while runtime resources are owned:** SIGINT/SIGTERM must stop `serve_forever()` and unwind the runtime context; pinned by `test_run_worker_installs_signal_handlers_and_closes_runtime` in Task 1.
3. **PostgreSQL becomes unreachable after API startup:** `/live` remains 200 while `/ready` returns sanitized 503 and never leaks a DSN/secret; pinned by `test_ready_returns_sanitized_not_ready_when_database_probe_fails` in Task 2.
4. **RAGFlow/LLM unavailable while API/PostgreSQL are otherwise ready:** `/ready` must not falsely claim provider readiness; the required-live runner must fail/incomplete the provider gate instead; pinned by `test_runner_fails_when_required_preflight_is_missing` in Task 3.
5. **A required pytest command exits 0 only because tests skipped:** the runner must classify the gate FAILED/INCOMPLETE and return non-zero; pinned by `test_runner_rejects_required_gate_with_skips` in Task 3.

---

### Task 1: Application Runtime Closure

**Outcome:** One image can import/run the application, and the default deployed Worker supports QA + Issue modes through existing executors with deterministic resource cleanup.

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `src/project_agent/cli/__init__.py`
- Create: `src/project_agent/cli/worker.py`
- Create: `src/project_agent/runtime/run_graph.py`
- Create: `tests/unit/runtime/test_run_graph_runtime.py`
- Create: `tests/unit/cli/test_worker.py`
- Modify: `src/project_agent/runtime/worker.py`
- Modify: `tests/unit/runtime/test_worker_runtime.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: existing `RunGraphExecutor.execute(run)`, `RunGraphExecutor.resume(run, payload)`, `RunBusinessMode`, `ProductionQARunExecutor`, `ProductionIssueRunGraphExecutor`, `build_worker_runtime(settings)`, and `BackgroundWorker.serve_forever()/stop()`.
- Produces: `ProductionRunGraphExecutor(qa: RunGraphExecutor, issue: RunGraphExecutor)`, `build_production_run_graph_executor(*, qa, issue)`, `project_agent.cli.worker.run_worker() -> None`, `project_agent.cli.worker.main() -> int`, and installed console script `project-agent-worker`.
- Resource rule: the router owns child executor closure; QA provider HTTP clients remain owned by `runtime.worker` context; the Issue executor receives the same RAGFlow adapter/checkpointer and closes its own DB engine exactly once.

- [ ] **Step 1: Write the production router RED tests first**

Create `tests/unit/runtime/test_run_graph_runtime.py` with these named tests:

```python
@pytest.mark.asyncio
async def test_execute_routes_qa_to_qa_executor() -> None: ...

@pytest.mark.asyncio
async def test_execute_routes_issue_lookup_to_issue_executor() -> None: ...

@pytest.mark.asyncio
async def test_execute_routes_issue_create_to_issue_executor() -> None: ...

@pytest.mark.asyncio
async def test_resume_routes_issue_create_to_issue_executor() -> None: ...

@pytest.mark.asyncio
async def test_resume_rejects_qa_without_delegating() -> None: ...

@pytest.mark.asyncio
async def test_aclose_closes_closable_child_executor_once() -> None: ...
```

Use a tiny recording fake implementing `RunGraphExecutor`; assert the QA fake sees only `RunBusinessMode.QA`, the Issue fake sees only `ISSUE_LOOKUP`/`ISSUE_CREATE`, QA resume raises the existing controlled unsupported behavior, and `aclose()` closes the closable Issue child once.

- [ ] **Step 2: Run router RED and confirm the missing module/API**

Run:

```bash
uv run pytest -q \
  tests/unit/runtime/test_run_graph_runtime.py
```

Expected: **FAIL during collection/import** because `project_agent.runtime.run_graph` / `ProductionRunGraphExecutor` does not exist. A pass means the RED is invalid; do not continue until the test proves the missing behavior.

- [ ] **Step 3: Implement the minimal runtime router**

Create `src/project_agent/runtime/run_graph.py` with this public shape:

```python
class ProductionRunGraphExecutor(RunGraphExecutor):
    def __init__(self, *, qa: RunGraphExecutor, issue: RunGraphExecutor) -> None: ...

    async def execute(self, run: RunRecord) -> RunGraphOutcome:
        return await self._for_mode(run.business_mode).execute(run)

    async def resume(
        self,
        run: RunRecord,
        resume_payload: dict[str, object],
    ) -> RunGraphOutcome:
        if run.business_mode is RunBusinessMode.QA:
            raise RunGraphUnavailable(run.business_mode.value)
        return await self._for_mode(run.business_mode).resume(run, resume_payload)

    async def aclose(self) -> None: ...

    def _for_mode(self, mode: RunBusinessMode) -> RunGraphExecutor:
        if mode is RunBusinessMode.QA:
            return self._qa
        if mode in {RunBusinessMode.ISSUE_LOOKUP, RunBusinessMode.ISSUE_CREATE}:
            return self._issue
        raise RunGraphUnavailable(str(mode))


def build_production_run_graph_executor(
    *,
    qa: RunGraphExecutor,
    issue: RunGraphExecutor,
) -> ProductionRunGraphExecutor: ...
```

Import `RunGraphUnavailable` from the existing Worker graph boundary; do not define a second failure type.

- [ ] **Step 4: Run router GREEN**

Run:

```bash
uv run pytest -q \
  tests/unit/runtime/test_run_graph_runtime.py
```

Expected: all named router tests PASS.

- [ ] **Step 5: Write default Worker composition RED**

In `tests/unit/runtime/test_worker_runtime.py`, add:

```python
@pytest.mark.asyncio
async def test_default_worker_runtime_builds_unified_qa_and_issue_executor(
    runtime_dependencies: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None: ...
```

The test must patch the QA builder and Issue executor constructor with recording fakes, enter `build_worker_runtime(settings())` **without** `graph_executor_factory`, and assert:

```text
same saver object reaches QA and Issue
same shared RagflowAdapter reaches QA and Issue
EXECUTE_AGENT_RUN and RESUME_AGENT_RUN use the unified executor
both QA and Issue modes are dispatchable
Issue child is closed on runtime exit
```

Update the existing `test_default_worker_runtime_owns_provider_clients_and_preserves_ws3_handlers` so it still proves both provider HTTP clients remain open inside the runtime and close after exit, while now expecting unified composition rather than QA-only composition.

- [ ] **Step 6: Run Worker composition RED**

Run:

```bash
uv run pytest -q \
  tests/unit/runtime/test_worker_runtime.py::test_default_worker_runtime_builds_unified_qa_and_issue_executor \
  tests/unit/runtime/test_worker_runtime.py::test_default_worker_runtime_owns_provider_clients_and_preserves_ws3_handlers
```

Expected: FAIL because the default runtime currently constructs QA only and never constructs/composes the Issue executor.

- [ ] **Step 7: Make the default Worker composition minimally GREEN**

Modify `src/project_agent/runtime/worker.py` only at the default graph-executor lifetime seam:

```python
# construct one RAGFlow adapter using LocalFileObjectStoreAdapter(settings.local_storage_root)
# construct existing Structured LLM adapter
qa = build_production_qa_executor(
    settings=settings,
    session_factory=session_factory,
    saver=saver,
    knowledge=knowledge,
    llm=llm,
    llm_usage=llm,
)
issue = ProductionIssueRunGraphExecutor(
    settings,
    saver,
    knowledge=knowledge,
)
yield build_production_run_graph_executor(qa=qa, issue=issue)
```

Preserve the existing injected `graph_executor_factory` fast path exactly. Do not modify QA graph code, Issue graph code, handler semantics, queue semantics, or checkpoint semantics.

- [ ] **Step 8: Run Worker composition GREEN and targeted runtime regressions**

Run:

```bash
uv run pytest -q \
  tests/unit/runtime/test_run_graph_runtime.py \
  tests/unit/runtime/test_worker_runtime.py \
  tests/unit/runtime/test_issue_runtime.py \
  tests/unit/runtime/test_qa_runtime.py \
  tests/unit/workers/test_run_graph.py
```

Expected: zero failures.

- [ ] **Step 9: Write Worker CLI RED tests**

Create `tests/unit/cli/test_worker.py` with these exact tests:

```python
@pytest.mark.asyncio
async def test_run_worker_loads_settings_enters_runtime_and_serves() -> None: ...

@pytest.mark.asyncio
async def test_run_worker_installs_signal_handlers_and_closes_runtime() -> None: ...

def test_main_returns_zero_after_normal_worker_exit(monkeypatch: pytest.MonkeyPatch) -> None: ...

def test_main_does_not_swallow_startup_failure(monkeypatch: pytest.MonkeyPatch) -> None: ...
```

The async tests use a fake async context manager runtime and fake Worker. The signal test records `SIGINT`/`SIGTERM` registration and removal and invokes the registered callback to prove it calls `worker.stop()`. The startup-failure test raises `RuntimeError("startup failed")` from the async runner and asserts `main()` does not convert it to success.

- [ ] **Step 10: Run CLI RED**

Run:

```bash
uv run pytest -q tests/unit/cli/test_worker.py
```

Expected: FAIL during import because `project_agent.cli.worker` does not exist.

- [ ] **Step 11: Implement the thin Worker CLI and project script**

Create `src/project_agent/cli/__init__.py` and `src/project_agent/cli/worker.py` with the following contract:

```python
async def run_worker() -> None:
    settings = load_settings()
    async with build_worker_runtime(settings) as runtime:
        loop = asyncio.get_running_loop()
        installed: list[signal.Signals] = []
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signum, runtime.worker.stop)
                installed.append(signum)
            await runtime.worker.serve_forever()
        finally:
            for signum in installed:
                loop.remove_signal_handler(signum)


def main() -> int:
    asyncio.run(run_worker())
    return 0
```

Do not catch general exceptions; an initialization/runtime exception must produce a non-zero process exit naturally.

Add to `pyproject.toml`:

```toml
[project.scripts]
project-agent-worker = "project_agent.cli.worker:main"
```

- [ ] **Step 12: Run CLI GREEN**

Run:

```bash
uv run pytest -q tests/unit/cli/test_worker.py
```

Expected: zero failures.

- [ ] **Step 13: Establish Docker image RED before creating image files**

Run:

```bash
docker build --progress=plain -t project-agent:ws7-task1 .
```

Expected: FAIL because the repository has no `Dockerfile`. This is the RED for the image/build contract.

- [ ] **Step 14: Add the minimal production image and build context rules**

Create `Dockerfile` with these required elements:

```dockerfile
FROM ghcr.io/astral-sh/uv:0.12.13 AS uv
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /var/lib/project-agent/data \
    && chown -R app:app /app /var/lib/project-agent
USER app

CMD ["uvicorn", "project_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `.dockerignore` excluding at minimum `.git`, `.worktrees`, `.env*` except no secret exception is needed for Docker context, caches, `artifacts/`, local `data/`, logs, archives, and test caches. The image must not copy `.env`.

- [ ] **Step 15: Run image GREEN and prove the Worker entrypoint is installed**

Run:

```bash
docker build --progress=plain -t project-agent:ws7-task1 .
docker run --rm --entrypoint python project-agent:ws7-task1 \
  -c "import importlib.util; assert importlib.util.find_spec('project_agent.cli.worker')"
docker run --rm --entrypoint sh project-agent:ws7-task1 \
  -c "command -v project-agent-worker >/dev/null && command -v alembic >/dev/null"
```

Expected: all commands exit 0.

- [ ] **Step 16: Task 1 broader verification**

Run:

```bash
uv run ruff check src tests
uv run mypy src
git diff --check
uv run pytest -q \
  tests/unit/runtime \
  tests/unit/workers \
  tests/unit/cli \
  tests/integration/agent/test_qa_runtime_postgres.py \
  tests/integration/issues/test_issue_run_runtime_postgres.py
```

Expected: zero failures in enabled tests; PostgreSQL opt-in tests may skip in this Task because Task 1's required gate is the image/runtime closure, not live-provider completion.

- [ ] **Step 17: Task 1 commit boundary — one implementation commit**

Before commit, inspect `git status --short` and ensure there is no migration file or unrelated WS1–WS6 change. Then:

```bash
git add \
  Dockerfile \
  .dockerignore \
  pyproject.toml \
  src/project_agent/cli/__init__.py \
  src/project_agent/cli/worker.py \
  src/project_agent/runtime/run_graph.py \
  src/project_agent/runtime/worker.py \
  tests/unit/cli/test_worker.py \
  tests/unit/runtime/test_run_graph_runtime.py \
  tests/unit/runtime/test_worker_runtime.py

git commit -m "feat(ws7): close application runtime"
```

Task 1 completion evidence: named REDs observed, all Task 1 GREEN commands exit 0, image builds, Worker script is installed, no migration, one commit.

---

### Task 2: Compose Deployment Closure

**Outcome:** `docker compose` renders and starts exactly PostgreSQL + API + Worker using the Task 1 image, container-safe provider addresses, shared local storage, meaningful health/readiness, and deterministic migrate/seed operations.

**Files:**
- Create: `tests/integration/deployment/test_compose_contract.py`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `src/project_agent/api/v1/health.py`
- Modify: `tests/integration/api/test_health.py`

**Interfaces:**
- Consumes: Task 1 image/`project-agent-worker`; existing `create_app()` lifespan storing `app.state.runtime`; existing `ApiRuntime.engine`; existing `/live`, `/ready`, `/metrics`; RAGFlow companion host port `9380`.
- Produces: Compose services `postgres`, `app-api`, `app-worker`; named volume `project_agent_app_data`; API readiness contract `{status, configuration, database}`; documented one-shot migrate/seed commands.

- [ ] **Step 1: Write Compose topology RED tests**

Create `tests/integration/deployment/test_compose_contract.py`. Render config with:

```python
result = subprocess.run(
    ["docker", "compose", "config", "--format", "json"],
    check=True,
    capture_output=True,
    text=True,
)
config = json.loads(result.stdout)
```

Add these named tests:

```python
def test_compose_declares_only_postgres_api_and_worker() -> None: ...

def test_api_and_worker_reuse_one_application_image() -> None: ...

def test_api_and_worker_share_storage_and_wait_for_healthy_postgres() -> None: ...

def test_compose_uses_container_database_and_ragflow_host_gateway() -> None: ...

def test_compose_exposes_api_and_worker_healthchecks() -> None: ...
```

Assert exactly three services; both app services build from the repository root and use the same image name; both mount the same app-data volume at `/var/lib/project-agent/data`; both use `postgres` in `DATABASE_URL`, `http://host.docker.internal:9380` for RAGFlow, and `host.docker.internal:host-gateway`; Worker binds metrics to `0.0.0.0:9101`; API health probes `/ready`; Worker health probes port 9101; no Redis/Celery/RAGFlow service appears.

- [ ] **Step 2: Run Compose contract RED**

Run:

```bash
uv run pytest -q tests/integration/deployment/test_compose_contract.py
```

Expected: FAIL because rendered Compose currently contains only `postgres`.

- [ ] **Step 3: Write API readiness RED tests before implementation**

Modify `tests/integration/api/test_health.py`:

1. Keep `test_live_does_not_require_external_services` unchanged.
2. Replace the configuration-only readiness assertion with:

```python
def test_ready_reports_database_ready_without_calling_provider_services(tmp_path: Path) -> None:
    ...
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "configuration": "ok",
        "database": "ok",
    }
```

3. Add:

```python
def test_ready_returns_sanitized_not_ready_when_database_probe_fails(tmp_path: Path) -> None:
    ...
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "configuration": "ok",
        "database": "unavailable",
    }
    assert "postgresql" not in response.text
    assert "secret" not in response.text
```

Use an injected fake `ApiRuntime`/fake engine so no real RAGFlow or LLM request occurs. Preserve the invalid-environment test and extend its expected body only if necessary; invalid settings must still fail before runtime construction.

- [ ] **Step 4: Run readiness RED**

Run:

```bash
uv run pytest -q \
  tests/integration/api/test_health.py::test_ready_reports_database_ready_without_calling_provider_services \
  tests/integration/api/test_health.py::test_ready_returns_sanitized_not_ready_when_database_probe_fails
```

Expected: at least one FAIL because `/ready` currently returns only configuration state and never probes PostgreSQL.

- [ ] **Step 5: Implement bounded PostgreSQL readiness**

Modify `src/project_agent/api/v1/health.py` so `/live` remains unchanged and `/ready` follows exactly:

```python
try:
    _resolve_settings(request)
except ValidationError:
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "configuration": "invalid"},
    )

runtime = getattr(request.app.state, "runtime", None)
if runtime is None:
    return JSONResponse(
        status_code=503,
        content={
            "status": "not_ready",
            "configuration": "ok",
            "database": "unavailable",
        },
    )

try:
    async with runtime.engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
except Exception:
    return JSONResponse(
        status_code=503,
        content={
            "status": "not_ready",
            "configuration": "ok",
            "database": "unavailable",
        },
    )

return {"status": "ready", "configuration": "ok", "database": "ok"}
```

Do not include exception text, DSN, RAGFlow state, or LLM state in the response.

- [ ] **Step 6: Implement the three-service Compose contract**

Modify `compose.yaml` to retain the current PostgreSQL service and add one shared application anchor plus `app-api` and `app-worker`. The rendered contract must be equivalent to:

```yaml
x-app-common: &app-common
  build:
    context: .
  image: project-agent:ws7
  env_file:
    - path: .env
      required: false
  environment:
    DATABASE_URL: postgresql+asyncpg://project_agent:project_agent@postgres:5432/project_agent
    LOCAL_STORAGE_ROOT: /var/lib/project-agent/data
    RAGFLOW_BASE_URL: http://host.docker.internal:9380
  extra_hosts:
    - host.docker.internal:host-gateway
  depends_on:
    postgres:
      condition: service_healthy
  volumes:
    - project_agent_app_data:/var/lib/project-agent/data

services:
  postgres:
    # preserve current postgres:16 configuration and healthcheck

  app-api:
    <<: *app-common
    command: ["uvicorn", "project_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"]
      interval: 5s
      timeout: 4s
      retries: 20

  app-worker:
    <<: *app-common
    command: ["project-agent-worker"]
    environment:
      DATABASE_URL: postgresql+asyncpg://project_agent:project_agent@postgres:5432/project_agent
      LOCAL_STORAGE_ROOT: /var/lib/project-agent/data
      RAGFLOW_BASE_URL: http://host.docker.internal:9380
      WORKER_METRICS_ENABLED: "true"
      WORKER_METRICS_HOST: 0.0.0.0
      WORKER_METRICS_PORT: "9101"
    ports:
      - "9101:9101"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9101/metrics', timeout=3)"]
      interval: 5s
      timeout: 4s
      retries: 20

volumes:
  project_agent_postgres_data:
  project_agent_app_data:
```

If Compose anchor merge would drop inherited environment keys, use a second environment anchor or repeat the full four required Worker overrides. The rendered tests, not YAML aesthetics, are authoritative.

Update `.env.example` comments to document:

```text
host developer DATABASE_URL uses localhost:5432
Compose overrides DATABASE_URL to postgres:5432
host developer RAGFLOW_BASE_URL uses localhost:9380
Compose overrides RAGFLOW_BASE_URL to host.docker.internal:9380
Compose overrides LOCAL_STORAGE_ROOT to /var/lib/project-agent/data
Compose overrides WORKER_METRICS_HOST to 0.0.0.0
```

Do not add secret values.

- [ ] **Step 7: Run Task 2 GREEN tests**

Run:

```bash
uv run pytest -q \
  tests/integration/deployment/test_compose_contract.py \
  tests/integration/api/test_health.py
```

Expected: zero failures.

- [ ] **Step 8: Render/build Compose and prove deterministic migrate/seed commands**

Run from the WS7 worktree with the existing server `.env` loaded/present:

```bash
docker compose config --quiet
docker compose build app-api app-worker
docker compose up -d postgres
docker compose run --rm app-api alembic upgrade head
docker compose run --rm app-api alembic current
docker compose run --rm app-api python scripts/seed_sandbox_issues.py
```

Expected:

```text
compose config/build exit 0
postgres healthy
alembic current prints 0005_run_runtime_envelope (head)
seed command prints [PASS] Task 12 sandbox seeded
```

If Alembic reports a different head, stop; do not create a migration to silence the mismatch.

- [ ] **Step 9: Start API/Worker and run Task 2 live deployment gates**

Run:

```bash
docker compose up -d app-api app-worker

docker compose ps

curl -fsS http://127.0.0.1:8000/live
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:9101/metrics >/dev/null

docker compose exec -T app-api python -c \
  "import urllib.request; r=urllib.request.urlopen('http://host.docker.internal:9380/api/v1/system/healthz', timeout=5); print(r.status); assert r.status == 200"

docker compose exec -T app-worker python -c \
  "import urllib.request; r=urllib.request.urlopen('http://host.docker.internal:9380/api/v1/system/healthz', timeout=5); print(r.status); assert r.status == 200"
```

Expected:

```text
/live -> {"status":"ok"}
/ready -> {"status":"ready","configuration":"ok","database":"ok"}
worker /metrics responds successfully
both containers print 200 for RAGFlow health
postgres/app-api/app-worker show running/healthy after healthcheck convergence
```

Do not add RAGFlow/LLM calls to `/ready` if a provider gate fails; provider failures belong to Task 3.

- [ ] **Step 10: Task 2 targeted/broader regressions**

Run:

```bash
uv run pytest -q \
  tests/integration/deployment/test_compose_contract.py \
  tests/integration/api/test_health.py \
  tests/integration/api/test_run_api.py \
  tests/unit/runtime/test_api_runtime.py
uv run ruff check src tests
uv run mypy src
git diff --check
```

Expected: zero failures.

- [ ] **Step 11: Task 2 commit boundary — one implementation commit**

Leave the three Compose services running for Task 3 acceptance. Then:

```bash
git add \
  compose.yaml \
  .env.example \
  src/project_agent/api/v1/health.py \
  tests/integration/api/test_health.py \
  tests/integration/deployment/test_compose_contract.py

git commit -m "feat(ws7): add compose deployment closure"
```

Task 2 completion evidence: rendered topology exactly three services, migration stays `0005`, seed command succeeds, API/Worker health is real, both containers reach companion RAGFlow, no new migration, one commit.

---

### Task 3: WS7 Live Acceptance and Evidence

**Outcome:** One explicit command proves every mandatory provider/runtime gate and both real Compose process-boundary flows, writes sanitized reproducible evidence, and returns non-zero for missing prerequisites, skips, or failed gates.

**Files:**
- Create: `scripts/run_ws7_live_gates.py`
- Create: `tests/integration/deployment/test_ws7_live_runner.py`
- Create: `tests/live/conftest.py`
- Create: `tests/live/test_ws7_compose_qa.py`
- Create: `tests/live/test_ws7_compose_issue.py`
- Create: `docs/runbooks/ws7-compose-live-gates.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 2 running API at `http://127.0.0.1:8000`, Worker metrics at `http://127.0.0.1:9101`, host `DATABASE_URL`, host RAGFlow URL/API key, LLM URL/API key/model, JWT secret/issuer/audience, existing PostgreSQL/RAGFlow/LangGraph/LLM live tests, existing Run API/SSE, existing Sandbox Issue storage.
- Produces: `python scripts/run_ws7_live_gates.py --required` as the sole WS7 completion runner; evidence under `artifacts/ws7-live/<UTC-run-id>/summary.json` plus bounded gate logs.
- Required runner result: only `PASS` when every selected gate executes with zero failures **and zero skips**; otherwise return non-zero with `FAILED` or `INCOMPLETE`.

- [ ] **Step 1: Write required-live runner RED tests**

Create `tests/integration/deployment/test_ws7_live_runner.py` with these exact tests:

```python
def test_runner_fails_when_required_preflight_is_missing(tmp_path: Path, monkeypatch) -> None: ...

def test_runner_rejects_required_gate_with_skips(tmp_path: Path, monkeypatch) -> None: ...

def test_runner_stops_after_failed_gate_and_returns_nonzero(tmp_path: Path, monkeypatch) -> None: ...

def test_evidence_redacts_secrets_authorization_and_password_dsn(tmp_path: Path) -> None: ...

def test_summary_records_every_required_gate_and_final_pass(tmp_path: Path, monkeypatch) -> None: ...
```

Drive the runner through injected/substitutable subprocess execution rather than launching real providers in these tests. The skip test simulates pytest output `"1 passed, 1 skipped"` with exit code 0 and requires a non-zero runner result. The redaction test includes a fake API key, JWT-like token, `Authorization: Bearer ...`, and password-bearing PostgreSQL URL and asserts none appear in the persisted log/JSON.

- [ ] **Step 2: Run runner RED**

Run:

```bash
uv run pytest -q tests/integration/deployment/test_ws7_live_runner.py
```

Expected: FAIL during import because `scripts/run_ws7_live_gates.py` does not exist as the required runner implementation.

- [ ] **Step 3: Implement the mandatory runner minimally**

Create `scripts/run_ws7_live_gates.py` with these concrete units:

```python
@dataclass(frozen=True, slots=True)
class Gate:
    name: str
    command: tuple[str, ...]
    env: dict[str, str]

@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    status: Literal["PASS", "FAILED", "INCOMPLETE"]
    returncode: int
    skipped: int
    log_file: str


def redact(text: str, env: Mapping[str, str]) -> str: ...

def run_gate(gate: Gate, *, evidence_dir: Path, base_env: Mapping[str, str]) -> GateResult: ...

def write_summary(path: Path, results: Sequence[GateResult], metadata: Mapping[str, object]) -> None: ...

def main(argv: Sequence[str] | None = None) -> int: ...
```

`--required` performs preflight before any test command:

```text
branch is feat/ws7
HEAD and `git status --short` are captured as evidence; dirty state is recorded but is not a pre-commit gate
Docker daemon + docker compose available
postgres/app-api/app-worker are running and healthy
DATABASE_URL, RAGFLOW_BASE_URL, RAGFLOW_API_KEY, LLM_BASE_URL, LLM_API_KEY,
LLM_MODEL_ALIAS, JWT_HS256_SECRET are non-empty
host RAGFlow health responds 200
API /live and /ready respond 200
Worker metrics responds 200
```

Use a copied environment for required gates and force:

```python
RUN_POSTGRES_INTEGRATION="1"
RUN_RAGFLOW_INTEGRATION="1"
RUN_LLM_INTEGRATION="1"
RUN_WS7_COMPOSE_LIVE="1"
WS7_API_BASE_URL="http://127.0.0.1:8000"
```

The required gate sequence is exactly:

```text
postgres_runtime:
  uv run pytest -q -rs
    tests/integration/db/test_postgres_schema.py
    tests/integration/agent/test_postgres_checkpointer.py
    tests/integration/api/test_run_api_postgres.py
    tests/integration/issues/test_issue_run_runtime_postgres.py

ragflow:
  uv run python scripts/check_ragflow_version.py
  then uv run pytest -q -rs tests/integration/ragflow/test_project_isolation.py

structured_llm:
  uv run pytest -q -rs tests/integration/llm/test_structured_provider.py

qa_provider_runtime:
  uv run pytest -q -rs tests/integration/workers/test_qa_worker_live.py

compose_qa:
  uv run pytest -q -rs tests/live/test_ws7_compose_qa.py

compose_issue:
  uv run pytest -q -rs tests/live/test_ws7_compose_issue.py
```

Treat any non-zero subprocess result or any parsed pytest skip count greater than zero as non-PASS. Stop after the first failed mandatory gate, write the summary, and return non-zero. Never persist raw secret values.

- [ ] **Step 4: Run runner unit/integration GREEN**

Run:

```bash
uv run pytest -q tests/integration/deployment/test_ws7_live_runner.py
```

Expected: zero failures.

- [ ] **Step 5: Write shared live-fixture helpers before the Compose E2E tests**

Create `tests/live/conftest.py` with these exact helper interfaces:

```python
@dataclass(frozen=True, slots=True)
class LiveScope:
    company_id: UUID
    client_id: UUID
    project_a: UUID
    project_b: UUID
    user_a: UUID
    user_b: UUID
    project_a_code: str
    project_b_code: str
    project_a_dataset: str
    project_b_dataset: str


def require_ws7_live() -> None: ...

def make_live_token(*, user_id: UUID) -> str: ...

async def seed_qa_scope() -> tuple[LiveScope, str]: ...
async def seed_issue_scope() -> tuple[LiveScope, UUID]: ...
async def cleanup_live_scope(scope: LiveScope) -> None: ...

async def wait_for_run_status(
    client: httpx.AsyncClient,
    *,
    run_id: UUID,
    headers: dict[str, str],
    expected: set[str],
    timeout_seconds: float = 90.0,
) -> dict[str, object]: ...
```

Rules for these helpers:

- `require_ws7_live()` skips only when `RUN_WS7_COMPOSE_LIVE != "1"`; once enabled, a missing required env uses `pytest.fail`, not skip.
- Build HS256 JWTs with the existing `tests.helpers.jwt.make_hs256_token` and the configured JWT issuer/audience/secret.
- Use unique UUID/project codes for every invocation.
- QA fixture creates two PostgreSQL projects/memberships, creates two RAGFlow spaces through the existing `RagflowAdapter`, ingests one unique alpha document containing a unique marker, persists the alpha Document/DocumentVersion/ProjectKnowledgeSpace mapping required by existing authorization/evidence policy, ensures an enabled `prompt.qa.answer` SystemConfig row exists exactly as the WS4 live gate does, and leaves beta without alpha authorization.
- Issue fixture persists the same minimum WS5 objects already proven by `test_issue_run_runtime_postgres.py`: Client, Project, Membership, ProjectKnowledgeSpace, SandboxProject, requirement Document/Version, plus any pre-existing Sandbox issue needed for duplicate-candidate coverage. It also creates a unique RAGFlow space and ingests the matching requirement content so the deployed default Issue executor uses the real RAGFlow path rather than a fake knowledge port.
- Cleanup deletes only rows/RAGFlow documents created under the unique fixture identifiers and deletes LangGraph checkpoint threads owned by the test; never truncate shared tables.
- `wait_for_run_status()` polls the **HTTP API**, not the database, until one of the expected statuses appears or fails with the last bounded response.

- [ ] **Step 6: Write Compose QA RED**

Create `tests/live/test_ws7_compose_qa.py` with these exact tests:

```python
@pytest.mark.asyncio
async def test_compose_qa_run_crosses_api_worker_and_persists_authorized_evidence(
    ws7_live_scope,
) -> None: ...

@pytest.mark.asyncio
async def test_compose_qa_run_is_not_readable_by_non_member(ws7_live_scope) -> None: ...
```

The positive test must:

```text
POST /api/v1/runs with business_mode=qa and user_a token
receive 201/QUEUED
wait through HTTP until SUCCEEDED
GET /api/v1/runs/{id}/events and observe terminal SSE
query PostgreSQL only after the HTTP-visible result to assert Answer/Evidence/Citations exist
assert evidence belongs to project_a and contains the unique alpha marker
```

The negative test uses `user_b` token against project_a run and requires HTTP 403 for run/event access. It must not inspect another project through a privileged helper and call that authorization proof.

- [ ] **Step 7: Run Compose QA RED against the already-running Task 2 stack**

Run:

```bash
RUN_WS7_COMPOSE_LIVE=1 \
RUN_POSTGRES_INTEGRATION=1 \
RUN_RAGFLOW_INTEGRATION=1 \
RUN_LLM_INTEGRATION=1 \
uv run pytest -q -rs tests/live/test_ws7_compose_qa.py
```

Expected before the live fixture/test implementation is complete: FAIL for the missing fixture/helper behavior. After the helper is implemented, this command must execute rather than skip and must PASS through the independent `app-worker` container. Do not replace it with an in-test Worker.

- [ ] **Step 8: Write Compose Issue interrupt/resume RED**

Create `tests/live/test_ws7_compose_issue.py` with these exact tests:

```python
@pytest.mark.asyncio
async def test_compose_issue_create_interrupt_resume_creates_exactly_one_issue(
    ws7_live_issue_scope,
) -> None: ...

@pytest.mark.asyncio
async def test_compose_issue_run_is_not_resumable_by_non_member(
    ws7_live_issue_scope,
) -> None: ...
```

The positive test must prove, through HTTP plus post-condition queries:

```text
POST issue_create -> 201/QUEUED
independent Worker reaches WAITING_CONFIRMATION
WAITING_CONFIRMATION event exposes request_payload_hash
SandboxIssue count for the run is zero before confirmation
POST /{run_id}/resume with action=confirm -> 202
Worker resumes from PostgreSQL LangGraph checkpoint and reaches SUCCEEDED
exactly one SandboxIssue exists with exactly one completed idempotency record
replaying the same resume returns the existing controlled conflict/replay-safe response
replay does not create a second SandboxIssue
terminal SSE is observable from API
```

The negative test uses a non-member token to call the resume endpoint and requires HTTP 403 with zero new issue side effects.

- [ ] **Step 9: Run Compose Issue RED/GREEN**

Run:

```bash
RUN_WS7_COMPOSE_LIVE=1 \
RUN_POSTGRES_INTEGRATION=1 \
RUN_RAGFLOW_INTEGRATION=1 \
RUN_LLM_INTEGRATION=1 \
uv run pytest -q -rs tests/live/test_ws7_compose_issue.py
```

Expected after implementation: all tests execute, zero failures, zero skips. A skipped LangGraph/provider test is not acceptable in this command.

- [ ] **Step 10: Ignore evidence and write the operator runbook**

Append to `.gitignore`:

```text
# WS7 live acceptance evidence
artifacts/ws7-live/
```

Create `docs/runbooks/ws7-compose-live-gates.md` containing the exact operator sequence:

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws7
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate it-agent
set -a
source .env
set +a

docker compose build app-api app-worker
docker compose up -d postgres
docker compose run --rm app-api alembic upgrade head
docker compose up -d app-api app-worker
python scripts/run_ws7_live_gates.py --required
```

Document that PASS requires no skipped mandatory gate; where evidence is stored; how to inspect `summary.json`; that `.env`/credentials must never be copied into evidence; and that `docker compose down` is optional cleanup while `docker compose down -v` is destructive and must not be part of routine acceptance.

- [ ] **Step 11: Run the full offline regression before the required-live gate**

Run with live switches explicitly disabled so this command proves deterministic repository regressions separately from provider availability:

```bash
RUN_POSTGRES_INTEGRATION=0 \
RUN_RAGFLOW_INTEGRATION=0 \
RUN_LLM_INTEGRATION=0 \
RUN_WS7_COMPOSE_LIVE=0 \
uv run pytest -q tests

uv run ruff check src tests
uv run mypy src
git diff --check
```

Expected: pytest has zero failures; opt-in integration/live tests may skip here by design. Ruff/MyPy/diff all exit 0.

- [ ] **Step 12: Run the single mandatory WS7 live acceptance command**

Ensure Task 2 Compose services are up, then run:

```bash
python scripts/run_ws7_live_gates.py --required
```

Expected final console summary:

```text
postgres_runtime PASS
ragflow PASS
structured_llm PASS
qa_provider_runtime PASS
compose_qa PASS
compose_issue PASS
WS7 PASS
```

Expected evidence:

```text
artifacts/ws7-live/<run-id>/summary.json
artifacts/ws7-live/<run-id>/postgres_runtime.log
artifacts/ws7-live/<run-id>/ragflow.log
artifacts/ws7-live/<run-id>/structured_llm.log
artifacts/ws7-live/<run-id>/qa_provider_runtime.log
artifacts/ws7-live/<run-id>/compose_qa.log
artifacts/ws7-live/<run-id>/compose_issue.log
```

Open `summary.json` and verify every required gate status is `PASS`, every skip count is `0`, branch is `feat/ws7`, and no secret-bearing field is present.

- [ ] **Step 13: Fresh final schema/service/security verification**

Run:

```bash
docker compose run --rm app-api alembic current
docker compose ps

git status --short
git diff --check
```

Expected:

```text
Alembic = 0005_run_runtime_envelope (head)
postgres/app-api/app-worker running/healthy
only intended Task 3 tracked files are uncommitted
no artifacts/ws7-live files appear in git status
no migration file exists
```

- [ ] **Step 14: Task 3 commit boundary — one implementation commit**

```bash
git add \
  .gitignore \
  scripts/run_ws7_live_gates.py \
  tests/integration/deployment/test_ws7_live_runner.py \
  tests/live/conftest.py \
  tests/live/test_ws7_compose_qa.py \
  tests/live/test_ws7_compose_issue.py \
  docs/runbooks/ws7-compose-live-gates.md

git commit -m "feat(ws7): complete compose live acceptance"
```

Task 3/WS7 completion evidence: fresh full offline suite green, Ruff/MyPy/diff green, schema still `0005`, all six required-live groups PASS with zero skips, Compose QA and Issue gates cross real process boundaries, evidence sanitized, one Task 3 commit.

---

## Final WS7 Verification Contract

After Task 3 commit and before any claim that WS7 is FINAL COMPLETE, use `superpowers:verification-before-completion` and rerun fresh evidence from the committed tree:

```bash
git status --short
uv run ruff check src tests
uv run mypy src
git diff --check
RUN_POSTGRES_INTEGRATION=0 RUN_RAGFLOW_INTEGRATION=0 RUN_LLM_INTEGRATION=0 RUN_WS7_COMPOSE_LIVE=0 uv run pytest -q tests
python scripts/run_ws7_live_gates.py --required
docker compose run --rm app-api alembic current
git log --oneline -8
```

Completion is valid only when:

```text
git status is clean
Ruff = PASS
MyPy = PASS
git diff --check = PASS
full offline pytest = zero failures
required WS7 runner = PASS, zero mandatory skips
Alembic = 0005_run_runtime_envelope (head)
Task 1 commit = feat(ws7): close application runtime
Task 2 commit = feat(ws7): add compose deployment closure
Task 3 commit = feat(ws7): complete compose live acceptance
```

If any final command fails, do not amend the completion claim. Use `superpowers:systematic-debugging`, reproduce the root cause, add/observe a RED, make the smallest fix, rerun the owning Task gate plus this final contract, and record the deviation as a plan ruling if it changes any frozen interface.

## Documentation Freeze Before Execution

The Design and this Plan should be committed before Task 1 starts. These are documentation-preparation commits and do not count toward the three implementation Task commit boundaries:

```bash
git add docs/superpowers/specs/2026-09-20-ws7-docker-compose-live-gates-design.md
git commit -m "docs(ws7): freeze docker compose live gates design"

git add docs/superpowers/plans/2026-09-20-ws7-docker-compose-live-gates.md
git commit -m "docs(ws7): freeze docker compose live gates implementation plan"
```

After these two commits, implementation starts at Task 1 under `superpowers:executing-plans` + `superpowers:test-driven-development`. Unexpected failures use `superpowers:systematic-debugging`; every Task completion and WS7 completion claim uses `superpowers:verification-before-completion`.
