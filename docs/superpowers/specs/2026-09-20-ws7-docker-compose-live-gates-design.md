# WS7 Docker / Compose + Live Gates Design

**Date:** 2026-09-20
**Workstream:** WS7 — Docker / Compose + Live Gates
**Branch:** `feat/ws7`
**Frozen base:** `be1c5d702e7e65582ff59fbfdd6740d394e8fad7`
**Status:** **FROZEN** — approved in chat on 2026-09-21. Implementation must follow the approved Implementation Plan and preserve this design unless a new explicit WS7 requirement plus RED evidence justifies an amendment.

## 1. Authority and verified starting state

The current project code is the source of truth. The uploaded WS7 startup ZIP was compared against the live-server tracked-file manifest from `/home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws7`: all **348/348 tracked files matched SHA256**, with **0 missing and 0 mismatches**. The ZIP contains three additional handoff documents only: `WS7_NEW_CHAT_PROMPT.md`, `WS7_SERVER_SNAPSHOT.txt`, and `WS7_STARTUP_README.md`.

The live server is verified at:

- branch `feat/ws7`;
- HEAD `be1c5d702e7e65582ff59fbfdd6740d394e8fad7`;
- clean tracked worktree;
- Python `3.12.14`;
- Docker `29.2.1`;
- Docker Compose `v5.0.2`;
- Alembic `0005_run_runtime_envelope (head)`;
- application Compose currently contains only `postgres`;
- PostgreSQL is healthy on the live server;
- RAGFlow is a separate same-host companion Compose stack using `infiniflow/ragflow:v0.26.4`;
- RAGFlow compose project/service/network are `docker` / `ragflow-cpu` / `docker_ragflow`;
- host-side `RAGFLOW_BASE_URL=http://localhost:9380` returns HTTP 200 from the health endpoint;
- Structured LLM is configured as an external OpenAI-compatible provider;
- required PostgreSQL, RAGFlow, LLM, and JWT secrets are present on the live server but are not part of this design artifact.

The binding parent design is `docs/superpowers/specs/2026-09-12-v1-completion-design.md`, especially sections 15, 16, and the WS7 workstream definition. WS1–WS6 are FINAL COMPLETE and are not reopened by WS7.

## 2. Goal

WS7 closes the V1 runtime/deployment boundary without redesigning the application. A clean supported environment must be able to build one application image, start `postgres`, `app-api`, and `app-worker`, connect the application containers to the existing RAGFlow companion stack and external LLM provider, invoke migrations/seeding deterministically, and reproduce the required PostgreSQL/RAGFlow/LangGraph/LLM/end-to-end live gates with captured pass/fail evidence.

The essential deployment proof is process separation:

```text
HTTP client
  → app-api container
  → PostgreSQL Run/Event/Job
  → app-worker container
  → QA or Issue graph
  → PostgreSQL checkpoint/result/evidence
  → API/SSE terminal state
```

For Issue creation, the proof additionally crosses an actual LangGraph interrupt and a later resume job handled by the independent Worker process.

## 3. Non-goals

WS7 does not add Redis, Celery, ARQ, MinIO, Kubernetes, a Prometheus server, Grafana, log shipping, a second vector database, another RAG implementation, production Jira/Feishu/ZenTao writes, a new Agent architecture, a unified giant LangGraph, WS8 evaluation code, or a new multi-tenant model.

WS7 does not redesign authorization, project isolation, Run/Event/SSE semantics, PostgreSQL queue leases/retries/final failure, Evidence/Citation boundaries, Structured LLM behavior, Issue confirmation/idempotency/reconciliation, WS6 structured logging, metric-cardinality rules, or sanitization.

WS7 does not add an Alembic migration unless a WS7 RED test demonstrates that a frozen WS7 requirement cannot be satisfied by schema head `0005_run_runtime_envelope`. Dockerization by itself is not justification for a migration.

## 4. Inherited frozen contracts

The implementation must preserve the following already-frozen behavior:

- JWT provides trusted user identity; current PostgreSQL membership authorizes project access.
- `project_id` remains explicit and project isolation is enforced before Evidence or side effects are exposed.
- Run/Event/SSE ordering and terminal/non-terminal semantics remain unchanged.
- `WAITING_CONFIRMATION` remains non-terminal.
- PostgreSQL remains the durable background queue; lease, heartbeat, retry, reaper, and final-failure semantics remain unchanged.
- LangGraph PostgreSQL checkpointing remains the durable resume boundary.
- Issue creation still requires confirmation, uses idempotency, and preserves response-loss reconciliation.
- RAGFlow remains the retrieval provider and preserves project-isolated knowledge-space behavior.
- Structured LLM continues to use the existing validated adapter and controlled failure behavior.
- WS6 logging, metrics, bounded labels, token-cost policy, and sanitization remain unchanged except for deployment host/port overrides required to expose already-existing scrape endpoints.

## 5. Current WS7 gaps proven by source inspection

The current repository intentionally stops before WS7 closure:

1. `compose.yaml` contains only `postgres`; no application container is started.
2. There is no application `Dockerfile` or `.dockerignore` defining a reproducible image.
3. `BackgroundWorker.serve_forever()` exists, but there is no production CLI/module entrypoint that loads settings, owns `build_worker_runtime()`, and runs the Worker until termination.
4. The default `build_worker_runtime(settings)` constructs only the production QA executor. WS5 Issue execution is available only through injected `build_issue_graph_executor_factory(...)`. Therefore one default production Worker does not yet execute `qa`, `issue_lookup`, and `issue_create` in the same deployed runtime.
5. `/ready` currently validates configuration only; it does not prove the application can reach PostgreSQL.
6. Existing PostgreSQL/RAGFlow/LLM live tests prove real integrations but do not prove an HTTP request entering one container is durably consumed by a separate Worker container.
7. There is no WS7 runner that treats required live gates as mandatory, captures evidence, and refuses to call skipped/unavailable gates GREEN.
8. Host settings use `DATABASE_URL=...@localhost:5432/...` and `RAGFLOW_BASE_URL=http://localhost:9380`; these addresses are not valid provider addresses from inside the application containers without deployment-specific overrides.

These are WS7 integration/composition gaps, not regressions in WS1–WS6.

## 6. Architecture decision: thin runtime closure

WS7 uses the existing application architecture and adds only the deployment/composition seams that are missing. One application image is reused by the API and Worker with different commands.

```text
                     external Structured LLM
                              ▲
                              │ HTTPS
                              │
RAGFlow companion            │
(same host, published 9380)   │
        ▲                     │
        │ host gateway        │
        │                     │
┌───────┴─────────────────────┴──────────────────────────┐
│ application Compose                                  │
│                                                      │
│  app-api :8000           app-worker :9101            │
│       │                       │                       │
│       └────────────┬──────────┘                       │
│                    ▼                                  │
│             PostgreSQL :5432                          │
│                                                      │
│  app-api ─────┐                                       │
│               ├── shared local-storage volume         │
│  app-worker ──┘                                       │
└──────────────────────────────────────────────────────┘
```

The design intentionally avoids introducing another broker or storage service.

## 7. Application image contract

Create one production-oriented `Dockerfile` at repository root and a `.dockerignore`.

The image contract is:

- base runtime: Python 3.12 slim;
- dependency resolution is frozen by `uv.lock`;
- build tooling is pinned and does not become an application runtime dependency;
- install the project without development/test dependencies in the final application image;
- run as a non-root application user;
- set unbuffered Python output;
- copy application source, Alembic files, scripts needed by deterministic operational commands, and required static/runtime files;
- do not copy `.env`, credentials, test caches, local databases, logs, archives, or worktrees;
- do not use Uvicorn reload in the container command;
- the same image must support API, Worker, Alembic, seed, and live-gate helper commands where those helpers are intentionally shipped.

No new production Python dependency is required solely to build the image.

## 8. API process contract

`app-api` runs the existing FastAPI application with a production command equivalent to:

```text
uvicorn project_agent.main:app --host 0.0.0.0 --port 8000
```

The service exposes port `8000` and uses the existing `/live`, `/ready`, and `/metrics` endpoints. WS7 does not introduce an alternative HTTP server or API code path.

## 9. Worker process contract

Add one thin production Worker entrypoint. It must:

1. call `load_settings()`;
2. enter `build_worker_runtime(settings)`;
3. run `runtime.worker.serve_forever()`;
4. handle normal SIGINT/SIGTERM cancellation by exiting the runtime context so the existing Worker stop, graph-executor close, metrics-server close, and SQLAlchemy engine disposal paths run;
5. return a non-zero process exit on startup/runtime failure rather than masking the failure.

Expose this entrypoint as a project script named `project-agent-worker` (or an equivalently explicit name fixed by the implementation plan). The entrypoint contains no business logic.

## 10. Unified production RunGraphExecutor composition

The deployed default Worker must support all currently shipped business modes:

```text
qa
issue_lookup
issue_create
```

WS7 adds a thin routing/composition executor at the runtime boundary rather than merging QA and Issue graphs.

Conceptually:

```text
ProductionRunGraphExecutor
  ├─ qa           → existing ProductionQARunExecutor
  ├─ issue_lookup → existing ProductionIssueRunGraphExecutor
  └─ issue_create → existing ProductionIssueRunGraphExecutor
```

The router dispatches solely from the already-persisted `RunBusinessMode`. It must not mutate Run semantics, rebuild the graph protocol, or duplicate authorization decisions. Unsupported modes continue to produce a visible controlled failure.

The composition must share the same WS3 PostgreSQL checkpointer instance for QA and Issue execution in one Worker runtime. Existing injected `graph_executor_factory` support remains available for tests and specialized integration seams; it is not removed merely because the default production runtime becomes complete.

Resource ownership must remain explicit. Shared HTTP/DB resources should be owned once where practical; if existing QA/Issue executors retain separate internal resources, the implementation must prove they close deterministically and must not introduce leaked engines or HTTP clients.

## 11. Compose topology and configuration contract

Expand `compose.yaml` to three services:

```text
postgres
app-api
app-worker
```

Both application services build/use the same image and receive configuration from environment/`.env`; secrets are never baked into the image.

Container-specific deployment overrides are explicit:

- `DATABASE_URL` points to Compose service `postgres`, not `localhost`;
- `LOCAL_STORAGE_ROOT` points to the shared mounted application-data path;
- `RAGFLOW_BASE_URL` points to the documented RAGFlow companion access path from inside a container;
- Worker metrics bind to `0.0.0.0:9101` in the container so WS6 exposes a distinct Worker scrape target;
- API remains `0.0.0.0:8000`.

`app-api` and `app-worker` share one named local-file volume at the same container path. PostgreSQL retains its existing named data volume.

`app-api` and `app-worker` depend on PostgreSQL health, but `depends_on` is not considered a substitute for application readiness tests.

## 12. RAGFlow companion-stack connection

RAGFlow remains outside the application Compose project. On the verified WS7 server, RAGFlow is already published on host port `9380` by a separate Compose stack. To minimize coupling to the companion stack's project/network naming, the supported WS7 local/staging connection uses the Docker host gateway:

```text
RAGFLOW_BASE_URL=http://host.docker.internal:9380
```

On Linux, both application services add:

```text
host.docker.internal:host-gateway
```

This choice is deliberate: it reuses the companion stack's already-published stable port and avoids making the application Compose lifecycle depend on attaching to `docker_ragflow` or on an internal RAGFlow service alias. The application still verifies the configured RAGFlow expected version through its existing baseline/live-gate logic.

The host developer path may continue using `http://localhost:9380`; only container deployment overrides it. RAGFlow credentials remain supplied through the environment.

## 13. Readiness and health contract

### API liveness

`GET /live` remains process liveness only and performs no external calls.

### API readiness

`GET /ready` must validate:

- settings are valid; and
- PostgreSQL is reachable through the actual API runtime database engine/session path.

If configuration is invalid or PostgreSQL cannot be reached, return HTTP 503 with bounded, non-secret diagnostic state. The endpoint must not expose DSNs, credentials, provider bodies, or exception strings containing secrets.

The endpoint explicitly does **not** claim RAGFlow or LLM provider readiness. Provider health is proven by their required WS7 live gates. This avoids making global API readiness depend on external providers for routes that do not require them while also avoiding a false claim that those providers are ready.

### Worker readiness

The already-existing WS6 Worker metrics HTTP server remains the Worker process probe/scrape target. In Compose it binds to `0.0.0.0:9101`. Its lifecycle must only remain active while the Worker runtime owns successfully initialized critical local runtime dependencies, including PostgreSQL/checkpointer setup. A container healthcheck probes the metrics endpoint from inside the Worker container.

RAGFlow/LLM availability is not silently represented by Worker process health; those providers have separate live gates.

## 14. Migration and seed contract

WS7 adds no migration by default. The deterministic schema command is an explicit one-shot operation, not an automatic side effect of starting API/Worker containers:

```text
docker compose run --rm app-api alembic upgrade head
```

Completion must prove the database reports `0005_run_runtime_envelope (head)` after this command.

Existing seed utilities remain authoritative for the data they own. WS7 does not invent a broad permanent demo-data model merely to run acceptance. The live-gate fixtures seed isolated PostgreSQL/RAGFlow data required for their test and clean it afterward. Existing `scripts/seed_sandbox_issues.py` remains available for its existing sandbox use case and may be documented as a deterministic invocation.

## 15. Live-gate model

WS7 has two layers of live evidence.

### Layer A — existing provider/runtime gates

Reuse the existing real integration coverage for:

- PostgreSQL schema/repositories/auth/queue/Run/Event/Evidence/Issue persistence;
- RAGFlow version/project isolation/retrieval mapping;
- PostgreSQL LangGraph checkpointer behavior;
- real Structured LLM structured output/token usage/controlled provider failure behavior.

WS7 may add small deployment-focused probes, but must not fork existing business logic into a second test implementation.

### Layer B — Compose process-boundary end-to-end gates

Add two mandatory WS7 live gates that use the running Compose API and independently running Compose Worker rather than `TestClient` plus an in-test Worker.

#### QA gate

Prove:

```text
HTTP POST /api/v1/runs (qa)
→ PostgreSQL run/event/job
→ independent app-worker claim
→ production QA graph
→ real RAGFlow + real Structured LLM
→ persisted Answer/Evidence/Citations
→ API/SSE observes terminal result
```

The gate also proves a non-member/cross-project request cannot obtain another project's run/evidence.

#### Issue gate

Prove:

```text
HTTP POST /api/v1/runs (issue_create)
→ independent app-worker
→ production Issue graph
→ actual LangGraph interrupt
→ WAITING_CONFIRMATION
→ no Issue side effect before confirmation
→ HTTP resume request
→ RESUME_AGENT_RUN
→ PostgreSQL checkpoint resume in Worker process
→ idempotent Sandbox Issue create
→ terminal API/SSE result
```

The gate must also prove duplicate/replayed confirmation does not create a second Issue and that non-member/cross-project authorization is denied.

The live tests operate on unique per-run fixture identifiers and clean up the data they own. They must not depend on pre-existing business records other than configured provider infrastructure.

## 16. Required-gate semantics

A required WS7 live gate is never counted GREEN merely because pytest skipped it.

The WS7 runner performs preflight first. When invoked in required-live mode, missing credentials, unreachable PostgreSQL/RAGFlow/LLM, missing Docker/Compose capability, unhealthy application service, or a selected skip is an **INCOMPLETE/FAILED** WS7 result with non-zero exit status.

Ordinary repository test runs may continue to leave opt-in live tests disabled/skipped by default. The distinction is explicit: default CI safety is not WS7 completion evidence.

## 17. Live-gate runner and captured evidence

Add one orchestration script, expected to be `scripts/run_ws7_live_gates.py`, that invokes existing and WS7-specific gates in a fixed order and captures evidence. It is an orchestrator, not an alternative implementation of business logic.

The runner records at least:

- UTC timestamp;
- git branch/HEAD and dirty-state check;
- Docker/Compose versions;
- Alembic current/head;
- application Compose service state/health;
- RAGFlow version/health preflight;
- provider gate command and exit status;
- Compose QA gate command and exit status;
- Compose Issue gate command and exit status;
- final PASS/FAIL/INCOMPLETE summary.

Secrets, Authorization headers, full JWTs, API keys, password-bearing DSNs, provider raw secret-bearing error bodies, and unbounded user text are never written to evidence artifacts.

Evidence is written under an ignored path such as:

```text
artifacts/ws7-live/<run-id>/
```

with a machine-readable `summary.json` plus bounded text logs. `.gitignore` is extended for this runtime evidence directory.

## 18. Offline/TDD verification strategy

WS7 feature implementation remains test-first. The implementation plan must create a RED before each production behavior change. Static/file-existence assertions alone are not sufficient when behavior can be exercised.

Expected offline/controlled test areas include:

- image/build contract validation without requiring provider secrets;
- Worker CLI lifecycle and non-zero startup failure behavior;
- default production Worker routing for `qa`, `issue_lookup`, and `issue_create`;
- unsupported business-mode failure remains visible;
- API readiness returns ready only when configuration and PostgreSQL are usable;
- readiness failure sanitizes diagnostics;
- Compose config renders exactly `postgres`, `app-api`, `app-worker`, correct volumes/ports/healthchecks/host gateway, and no forbidden sidecars;
- live-gate runner returns non-zero for missing mandatory preflight and for selected skips/failures;
- evidence writer redacts bounded secret fields and records all required gate outcomes.

The implementation plan must reuse existing test helpers where doing so preserves the real interface, and must not weaken tests to accommodate the implementation.

## 19. Regression and completion gates

Each WS7 task follows:

```text
RED
→ confirm missing behavior
→ minimal GREEN
→ targeted regression
→ broader regression
→ required live gate for that task
→ commit
```

Before WS7 completion, the branch must run fresh verification covering at least:

- Ruff over `src` and `tests`;
- MyPy over `src`;
- `git diff --check`;
- full repository pytest suite with zero failures;
- schema still at `0005_run_runtime_envelope` unless an independently approved WS7 RED justified a migration;
- required PostgreSQL live gate;
- required RAGFlow live gate;
- required Structured LLM live gate;
- required PostgreSQL LangGraph/checkpointer gate;
- Compose QA process-boundary gate;
- Compose Issue interrupt/resume process-boundary gate;
- clean captured WS7 evidence summary with no mandatory skips.

No completion claim is made from historical WS6 results alone; WS7 requires fresh target-worktree evidence.

## 20. Frozen implementation file boundary

The approved implementation plan may touch only the following WS7-owned files unless an unexpected RED proves that an additional file is required. Any additional production file requires a recorded plan ruling before modification.

```text
Create:
  Dockerfile
  .dockerignore
  src/project_agent/cli/__init__.py
  src/project_agent/cli/worker.py
  src/project_agent/runtime/run_graph.py
  scripts/run_ws7_live_gates.py
  tests/unit/runtime/test_run_graph_runtime.py
  tests/unit/cli/test_worker.py
  tests/integration/deployment/test_compose_contract.py
  tests/integration/deployment/test_ws7_live_runner.py
  tests/live/conftest.py
  tests/live/test_ws7_compose_qa.py
  tests/live/test_ws7_compose_issue.py
  docs/runbooks/ws7-compose-live-gates.md

Modify:
  compose.yaml
  pyproject.toml
  src/project_agent/runtime/worker.py
  src/project_agent/api/v1/health.py
  tests/unit/runtime/test_worker_runtime.py
  tests/integration/api/test_health.py
  .env.example
  .gitignore
```

No Alembic revision is part of the frozen boundary. `Makefile`, `scripts/run_checks.py`, WS1–WS6 graph/business modules, and existing WS4/WS5 live-test implementations remain unchanged unless a new WS7 RED directly proves that this boundary is insufficient.

## 21. Frozen implementation task boundaries

WS7 implementation is intentionally limited to **three Tasks**. These are the only implementation Task boundaries:

### Task 1 — Application Runtime Closure

Deliver one reproducible application image plus the missing deployed Worker runtime seam. This Task owns the Docker image contract, `project-agent-worker` CLI, unified default `qa` / `issue_lookup` / `issue_create` executor composition, resource closure, and preservation of the existing injected graph-executor test seam. It ends only after focused runtime tests, image build/import verification, targeted runtime regressions, Ruff/MyPy/diff checks, and one implementation commit are green.

### Task 2 — Compose Deployment Closure

Expand application Compose to exactly `postgres`, `app-api`, and `app-worker`; add container-only database/storage/RAGFlow/metrics overrides; share application storage; make `/ready` prove configuration plus PostgreSQL without claiming RAGFlow/LLM readiness; and expose deterministic migration/seed commands. It ends only after Compose contract tests, readiness RED→GREEN, actual Compose build/up, Alembic head proof, API/Worker health probes, in-container RAGFlow connectivity, targeted regressions, and one implementation commit are green.

### Task 3 — WS7 Live Acceptance and Evidence

Add the mandatory WS7 live-gate runner, sanitized evidence capture, Compose QA process-boundary acceptance, Compose Issue interrupt/resume/idempotency acceptance, authorization-negative checks, and the WS7 runbook. It ends only after the required PostgreSQL/RAGFlow/LangGraph/LLM gates, both Compose E2E gates, offline full regression, Ruff, MyPy, `git diff --check`, evidence-summary validation, schema-head verification, and one implementation commit are freshly green.

The implementation plan must give exact files, named tests, RED commands and expected failure reasons, minimal GREEN edits, targeted/broader regression commands, required live-gate commands, and exactly one final implementation commit boundary per Task. Design/Plan documentation freeze commits occur before implementation and do **not** count as Task 1–3 implementation commits. No feature coding starts before that plan is reviewed and approved.

## 22. Rejected alternatives

### Embed RAGFlow in application Compose

Rejected. The parent design fixes RAGFlow as an external/companion stack; duplicating it would create a second deployment authority and exceed WS7 scope.

### Attach directly to `docker_ragflow` as the only supported connection

Rejected as the primary V1 local/staging contract. Although the current server exposes that network, binding the application Compose to the companion project's internal network name/service alias creates unnecessary cross-Compose lifecycle coupling. The verified published `9380` host port plus Docker host gateway is a smaller stable contract. Direct external-network attachment can be reconsidered later if a deployment environment explicitly requires it.

### Add Redis/Celery for the Worker

Rejected. PostgreSQL queue semantics are already frozen and complete; a second broker would change architecture without a WS7 requirement.

### Auto-run Alembic migration from API/Worker startup

Rejected. Schema mutation is an explicit operational action so concurrent API/Worker startup cannot race or obscure migration failures.

### Make `/ready` synchronously call RAGFlow and the LLM

Rejected. Global API readiness would then fail routes that only require PostgreSQL when an external provider is unavailable. `/ready` proves configuration + PostgreSQL; dedicated mandatory provider gates prove RAGFlow/LLM readiness and prevent false completion claims.

### Merge QA and Issue graphs into one new graph

Rejected. WS7 needs runtime routing/composition only. Existing graph boundaries and their frozen semantics remain intact.

## 23. Freeze criteria

This design is frozen because the reviewer approved the following criteria:

- WS7 closes deployment and live-evidence gaps only;
- the application remains one API process plus one durable Worker process over PostgreSQL;
- one image is reused by API/Worker;
- RAGFlow stays companion/external and the container connection contract is explicit;
- the default production Worker supports all shipped business modes without graph redesign;
- readiness claims are meaningful and bounded;
- no migration or new application runtime dependency is introduced without a future explicit RED;
- both QA and Issue flows are proven across actual Compose process boundaries;
- required live-gate skips are not treated as PASS;
- captured evidence is reproducible and sanitized;
- WS1–WS6 frozen contracts remain unchanged.

This frozen file is the binding authority for `docs/superpowers/plans/2026-09-20-ws7-docker-compose-live-gates.md`.
