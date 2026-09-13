# V1 Completion Design

- Status: Approved design baseline; implementation not started
- Date: 2026-09-12
- Process: Superpowers brainstorming — architectural completion
- Scope: Complete the already-frozen V1 end-to-end runtime and verification loop without redesigning Task 0–13

## 1. Purpose

This specification defines how to complete the existing V1 implementation into a runnable, verifiable end-to-end system.

The current repository is the source of truth. Existing Task 0–13 code is retained unless a narrowly-scoped change is required to wire or complete an already-frozen V1 behavior. README completion labels are not acceptance evidence by themselves.

The completion goal is:

```text
Authenticated internal user
→ project-authorized FastAPI request
→ durable Run / Event / PostgreSQL Job
→ real Worker handler
→ existing QA or Issue LangGraph workflow
→ RAGFlow / Structured LLM / PostgreSQL adapters
→ persisted answer / evidence / issue state / events
→ SSE-visible progress and terminal result
→ interrupt/resume for Issue creation
→ reproducible Docker/live gates
→ reproducible evaluation metrics and report
```

This is an architectural completion project, not a new product design.

## 2. Frozen Decisions

The following decisions are fixed for V1 Completion.

1. **Do not rewrite Task 0–13.** Add a production Runtime Envelope around the existing modules and make only targeted changes needed to complete frozen V1 behavior.
2. **Do not create a giant Unified LangGraph.** A Run Orchestrator provides the unified business entry point and dispatches to the existing QA Graph or Issue Graph.
3. **The V1 Run API requires an explicit `project_id`.** Do not make `threads.project_id` or `agent_runs.project_id` nullable to support automatic project discovery.

The V1 Architecture Lock remains:

```text
FastAPI
+ LangGraph
+ PostgreSQL
+ PostgreSQL Job Queue
+ RAGFlow
+ LocalFileObjectStoreAdapter
+ SandboxProjectTrackerAdapter
```

The completion must not add Redis, ARQ, Celery, MinIO, a second vector database, multi-Agent orchestration, production Jira/禅道/飞书 writes, SaaS multi-tenancy, Kubernetes, or another infrastructure stack that changes ADR-0004.

## 3. Evidence Basis and Current State

The design is based on the current repository code, V1 Scope, ADR-0004, Task 0–13 documentation, tests, and evaluation tree.

Observed repository state at design time:

```text
Task 0 validator: PASS
pytest with PYTHONPATH=src: 156 passed, 14 skipped
```

The skipped tests are concentrated around optional live/runtime integrations such as PostgreSQL, RAGFlow, and LangGraph/checkpointer paths. Those skips are not treated as live-gate passes.

The uploaded review tree does not contain `.git`, so `git log --oneline -15` and the live worktree `git status` cannot be reconstructed from this artifact. Before implementation begins in the real worktree, the implementation workflow must capture those two commands as preflight evidence.

### 3.1 Implemented components that are retained

The repository already contains, among other components:

- FastAPI application factory and document lifecycle API;
- PostgreSQL schema and repositories;
- project membership authorization services and JWT verifier;
- LocalFileObjectStoreAdapter;
- RAGFlow adapters/clients and project-isolation contracts;
- identifier extraction/registry and exact lookup path;
- PostgreSQL Job Queue primitives, lease/heartbeat/retry/reaper worker loop;
- QA LangGraph and QA persistence abstractions;
- Authority/Evidence/Citation governance;
- SandboxProjectTrackerAdapter and issue-candidate ranking;
- Issue Draft, confirmation, idempotency, reconciliation services and Issue LangGraph;
- agent run/event/evidence/answer/issue tables required for runtime persistence.

### 3.2 Completion gaps

The main gaps are not a reason to redesign the existing tasks. They are completion gaps:

- no production composition root/bootstrap that builds the real dependency graph;
- FastAPI still does not wire JWT authentication into PostgreSQL-backed project authorization;
- no Run API or Agent Event/SSE API;
- no registered production `EXECUTE_AGENT_RUN` or `RESUME_AGENT_RUN` worker handler;
- no real Structured LLM adapter;
- QA retrieval grading and bounded second retrieval are absent;
- Issue creation does not yet build the frozen requirement/test Evidence chain required by V1 Scope;
- JSON logging and Prometheus metrics are absent;
- Compose does not provide the application API/Worker runtime loop;
- live gates are not collected as reproducible completion evidence;
- evaluation contains a dataset but no runner, metric pipeline, ablation runner, raw result format, or report generator.

## 4. Scope Contract

### 4.1 V1 business scenarios

The completion must make both frozen V1 scenarios runnable through the production Runtime Envelope.

#### Scenario A — Project knowledge QA

```text
JWT identity
→ explicit project_id
→ PostgreSQL ProjectMembership authorization
→ Query Analysis
→ Exact Identifier Resolver
→ project-scoped RAGFlow retrieval
→ Retrieval Grade
→ optional bounded second retrieval
→ Authority / Version Filter
→ Evidence Packing / frozen snapshots
→ Structured LLM answer
→ Citation Guard
→ at most one bounded answer revision
→ persisted answer/citations/events
```

#### Scenario B — Historical Issue query and Sandbox creation

```text
JWT identity
→ explicit project_id
→ PostgreSQL ProjectMembership authorization
→ requirement/test evidence retrieval and freeze
→ same-project Sandbox Issue search
→ possible_duplicates
→ Issue Draft containing evidence_ids
→ LangGraph interrupt
→ explicit payload-bound user confirmation
→ permission re-check
→ durable idempotency barrier
→ Sandbox create
→ response-loss reconciliation when necessary
→ Sandbox Issue Key / terminal event
```

Historical issue similarity remains advisory. No rule or model is allowed to declare a business duplicate automatically.

### 4.2 V1 cross-cutting capabilities

Completion must cover all V1-scope cross-cutting items relevant to runtime closure:

- FastAPI API;
- LangGraph orchestration;
- PostgreSQL business data, queue, and checkpointer;
- RAGFlow retrieval;
- LocalFileObjectStoreAdapter;
- project authorization and Evidence isolation;
- document version/authority governance;
- Exact Identifier Registry;
- Citation Guard;
- Sandbox Issue and explicit confirmation;
- `client_request_id` idempotency;
- JSON logging;
- base Prometheus metrics;
- Run-level model/token/OCR/retrieval-round/estimated-cost fields;
- Prompt snapshot/version tracking;
- retention/legal-hold compatibility with the existing model.

Task 0 real-business validation remains explicitly pending and is not reclassified as complete by this engineering work.

## 5. Runtime Envelope Architecture

The Runtime Envelope is a thin composition/orchestration layer around existing modules.

```text
┌─────────────────────────────────────────────────────────────┐
│ FastAPI                                                     │
│                                                             │
│ JWT dependency → Membership authorization                   │
│ Documents API                                               │
│ Run API / Run status / SSE / Resume                         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Run Application Service / Run Orchestrator                  │
│                                                             │
│ create run + initial event + enqueue job atomically          │
│ route business mode: QA | ISSUE_LOOKUP | ISSUE_CREATE       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ PostgreSQL                                                  │
│ threads / agent_runs / agent_events / background_jobs       │
│ evidence / answers / issue workflow / checkpoints           │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ BackgroundWorker + production HandlerRegistry               │
│                                                             │
│ EXECUTE_AGENT_RUN                                           │
│ RESUME_AGENT_RUN                                            │
│ existing document / retention / reconciliation jobs         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
           Existing QA Graph       Existing Issue Graph
                    │                     │
              RAGFlow + LLM      Evidence + Sandbox Tracker
                    └──────────┬──────────┘
                               ▼
                    persisted artifacts/events
```

The Run Orchestrator is the common entry point. It does not duplicate graph business rules and does not move deterministic domain rules into prompts.

## 6. API Contract

The exact Pydantic names may follow existing project conventions, but the external behavior is frozen here.

### 6.1 Authentication

Protected V1 routes use:

```text
Authorization: Bearer <JWT>
```

JWT verifies identity only. Authorization must be rebuilt from the current PostgreSQL `ProjectMembership` state on every protected operation that needs project access.

A token claim must never directly grant project access.

### 6.2 Run creation

Minimum endpoint:

```text
POST /api/v1/runs
```

Required request information:

- `project_id` — mandatory;
- business mode — `qa`, `issue_lookup`, or `issue_create`;
- user query/input text;
- optional existing `thread_id` when the caller is continuing an authorized thread.

Run creation must:

1. verify JWT identity;
2. rebuild project authorization from PostgreSQL;
3. reject non-members before creating executable work;
4. create or validate a project-bound thread;
5. create the `agent_runs` row;
6. persist the initial user/run-request event;
7. enqueue `EXECUTE_AGENT_RUN` with `aggregate_id = run_id`;
8. make steps 4–7 atomic with respect to the database transaction so a durable Run cannot be left without its intended initial job because of a partial commit.

The queue payload remains aggregate-only. Query and resume payloads live in durable application tables/events, not inside `background_jobs`.

### 6.3 Run read/status

Minimum endpoint:

```text
GET /api/v1/runs/{run_id}
```

The caller must still have project access. The response exposes stable run status and result references/summary, not internal secrets or unfiltered provider payloads.

Required terminal/non-terminal semantics include at least:

```text
QUEUED
RUNNING
WAITING_CONFIRMATION
SUCCEEDED
REFUSED
CANCELLED
FAILED
```

Implementation may map existing internal statuses to this API vocabulary, but terminal semantics must be unambiguous and testable.

### 6.4 Agent Events / SSE

Minimum endpoint:

```text
GET /api/v1/runs/{run_id}/events
Accept: text/event-stream
```

Requirements:

- event ordering is based on persisted per-run `sequence_no`;
- SSE is a projection of durable `agent_events`, not the source of truth;
- reconnect must support resumption from the last delivered sequence via standard `Last-Event-ID` behavior or an equivalent documented cursor;
- the endpoint must authorize access using the run's project;
- disconnecting the HTTP client must not cancel the background Run;
- terminal events close or naturally quiesce the stream according to a documented behavior;
- secrets, raw JWTs, and unsafe provider payloads must not enter events.

### 6.5 Run resume

Minimum endpoint:

```text
POST /api/v1/runs/{run_id}/resume
```

The request carries the user action needed by the current interrupt. For Issue creation it must include the Task 13 payload-bound confirmation information, including the displayed request payload hash.

Resume must:

1. re-authenticate and re-authorize the current user/project;
2. verify the Run is actually waiting for compatible input;
3. persist the resume input durably;
4. enqueue `RESUME_AGENT_RUN` with only `run_id` as aggregate identity;
5. make duplicate/replayed resume requests safe through state/idempotency checks;
6. let the Worker reload the durable resume payload and invoke LangGraph resume semantics.

The API endpoint does not directly execute the Sandbox write.

## 7. Production Composition and Resource Lifetime

A production composition root must build the real dependencies while preserving `create_app()` testability.

The production bootstrap must own the lifecycle of at least:

- `Settings`;
- PostgreSQL engine/session factory;
- repositories/services;
- JWT verifier;
- LocalFileObjectStoreAdapter;
- RAGFlow HTTP client/adapter;
- Structured LLM HTTP client/adapter;
- SandboxProjectTrackerAdapter;
- PostgreSQL Job Queue;
- LangGraph PostgreSQL checkpointer;
- QA Graph;
- Issue Graph;
- Run Orchestrator and API services.

FastAPI lifespan should open and close long-lived application resources. Tests must remain able to inject fakes without opening live services.

The Worker has a separate bootstrap using the same settings and infrastructure factories where practical, but runs as a separate process/service.

## 8. JWT → FastAPI → ProjectMembership

Current `JwtIdentityVerifier` and authorization services are retained.

Completion replaces manual/injected production actor identity with a FastAPI authentication dependency that:

1. parses the Bearer token;
2. verifies issuer/audience/signature/expiry using the existing verifier;
3. obtains the authenticated user identity;
4. loads current membership data from PostgreSQL;
5. constructs the operation-specific project authorization/actor object.

Document lifecycle routes must no longer depend on a production `app.state.document_actor` shortcut. Test-only dependency injection remains allowed.

Authorization invariants:

```text
cross-client Evidence = 0
cross-project Evidence = 0
non-member project access = 0
cross-project Citation = 0
revoked membership cannot be bypassed by a previously issued JWT
```

Issue creation still performs its existing immediate pre-write permission re-check; request-time authorization does not replace that barrier.

## 9. PostgreSQL Job Queue and Worker Handlers

The existing Job Queue implementation, lease, heartbeat, retry, reaper, rate limiters, and `BackgroundWorker` remain the execution substrate.

A production `HandlerRegistry` must register the actual handlers required by enabled V1 paths, including:

```text
INGEST_DOCUMENT
DELETE_DOCUMENT
EXECUTE_AGENT_RUN
RESUME_AGENT_RUN
RECONCILE_ISSUE_CREATE
RETENTION_SWEEP
```

Where an existing job type is not currently emitted by an enabled V1 API path, its handler still needs a deterministic registration decision: implemented and tested, or explicitly disabled through configuration with a clear startup/error contract. Unknown enabled job types must fail visibly; they must not be silently dropped.

### 9.1 EXECUTE_AGENT_RUN

`EXECUTE_AGENT_RUN(run_id)` must:

1. load the Run and durable initial input;
2. verify it is in an executable non-terminal state;
3. mark/record execution start idempotently;
4. dispatch by the frozen business mode;
5. invoke the existing QA Graph, Issue lookup flow, or Issue create flow;
6. persist relevant progress/terminal events;
7. update terminal Run status and `finished_at` when appropriate;
8. preserve `WAITING_CONFIRMATION` as non-terminal for interrupted Issue creation.

A retried job must not duplicate terminal answers or Issue side effects.

### 9.2 RESUME_AGENT_RUN

`RESUME_AGENT_RUN(run_id)` must:

1. load the existing Run/checkpoint and durable resume event/payload;
2. reject incompatible or stale resumes;
3. invoke LangGraph using the saved thread/checkpoint identity and `Command(resume=...)` semantics;
4. continue the existing Issue Graph from its interrupt;
5. persist progress/terminal events and Run status;
6. preserve Task 13 confirmation, permission re-check, idempotency, and response-loss behavior unchanged.

## 10. Real Structured LLM Adapter

V1 Completion must implement a real adapter for the existing `StructuredLLMPort`/usage contract. It must be settings-driven using the existing LLM configuration fields and must not introduce a second LLM abstraction.

Required behavior:

- asynchronous HTTP interaction using the project's existing HTTP stack or a minimal compatible implementation;
- configured `llm_base_url`, API key, and model alias;
- structured output validation into the existing Pydantic/domain response models;
- bounded timeout/retry behavior with no unbounded retry loop;
- explicit translation of provider/network/schema failures into application-visible failure classes/statuses;
- token usage returned through the existing usage path and accumulated into `agent_runs`;
- API keys and raw authorization headers excluded from logs/events/errors;
- test fake remains the default for unit/contract tests;
- opt-in live gate verifies at least one deterministic structured response against the configured provider.

The adapter must not silently accept malformed JSON/structured output as a valid business answer.

## 11. QA Completion — Retrieval Grade and Bounded Second Retrieval

The current QA Graph is retained and extended narrowly to implement the already-frozen retrieval behavior.

Required semantics:

```text
Exact Identifier Resolver
→ retrieval round 1
→ deterministic/structured retrieval grade
→ if adequate: evidence governance
→ if inadequate and second round is justified: retrieval round 2
→ grade again
→ evidence governance or refusal
```

Rules:

- maximum retrieval rounds per Run: **2**;
- no open-ended loop;
- second retrieval must remain inside the same authorized `ProjectAccessScope`;
- second retrieval may refine query terms/filters based on bounded grade output but may not broaden to unauthorized projects/knowledge spaces;
- retrieval grade is not allowed to override authority/current/effective filtering;
- each actual retrieval increments persisted `retrieval_rounds` exactly once;
- `retrieval_rounds` must be 0 for modes that never retrieve knowledge;
- inadequate evidence after the bounded second round leads to refusal, not unsupported generation.

The exact grade schema belongs in the implementation plan, but acceptance must test both one-round success and two-round/refusal paths.

## 12. Unified Issue Business Entry and Evidence Chain

The Run Orchestrator exposes `issue_lookup` and `issue_create` as business modes while reusing Task 12/13 services.

### 12.1 Requirement/test Evidence before creation

Before freezing an Issue Draft for `issue_create`, the runtime must retrieve and freeze project-authorized requirement/test Evidence relevant to the user's issue description.

The evidence chain must:

1. use the same explicit `project_id` and current `ProjectAccessScope`;
2. retrieve only allowed/published/current sources according to existing governance;
3. prioritize V1 requirement/test evidence types rather than arbitrary cross-project material;
4. persist frozen EvidenceSnapshot IDs;
5. populate `IssueDraft.evidence_ids` / `evidence_ids_json` with those frozen IDs;
6. make the evidence visible for review in the draft/confirmation experience without allowing the model to fabricate IDs.

Historical Sandbox issues remain a separate candidate source. Issue candidate links are not substitutes for requirement/test EvidenceSnapshot IDs.

If no adequate requirement/test evidence exists, **V1 `issue_create` refuses before creating an Issue Draft** with a stable `EVIDENCE_REQUIRED`-class outcome. It must not fabricate evidence or enter the confirmation/write path. `issue_lookup` remains available because historical Issue search is independently useful and read-only. This freezes the V1 interpretation of the scope phrase `需求/测试/历史问题证据`: a new Sandbox Issue created by the Agent must carry at least one governed requirement/test EvidenceSnapshot, while historical Issue candidates remain advisory context rather than a substitute for that evidence.

### 12.2 Issue lookup

`issue_lookup` performs same-project Sandbox search/ranking and returns `possible_duplicates` plus the frozen user choices. It does not create a draft or side effect unless the caller explicitly chooses the create path.

### 12.3 Issue create / HITL

`issue_create` follows:

```text
requirement/test Evidence
→ refresh same-project possible_duplicates
→ IssueDraft
→ payload hash
→ interrupt
→ WAITING_CONFIRMATION
→ /resume
→ RESUME_AGENT_RUN
→ Command(resume=...)
→ confirmation receipt
→ permission re-check
→ idempotency barrier
→ Sandbox create/reconcile
```

The existing Task 13 no-confirmation/no-side-effect and two-layer idempotency invariants remain mandatory.

## 13. Run/Event Persistence Semantics

The existing `agent_runs` and `agent_events` tables are the durable application record for the Runtime Envelope.

### 13.1 Run telemetry

The runtime must keep the following fields accurate when applicable:

- `model_alias`;
- prompt version/hash;
- input/output/total tokens;
- retrieval rounds;
- OCR pages;
- estimated cost microunits/currency;
- start/finish timestamps;
- status.

If OCR is not performed, `ocr_pages` remains `0`.

Estimated cost must be calculated only from explicit configured input/output token prices for the configured model. WS6 adds settings for input and output cost in integer microunits per one million tokens and uses integer arithmetic to update `estimated_cost_microunits`; `cost_currency` remains the configured currency. A V1 staging/live gate must configure those prices. In development/test, an omitted price configuration leaves the estimate at `0` and must emit `cost_estimate_configured=false` in structured telemetry so that zero is not presented as a measured provider cost. Provider prices must never be inferred or hard-coded from memory.

### 13.2 Event contract

Event type names must be stable enough for API/SSE and evaluation tooling. At minimum the runtime must make it possible to distinguish:

- accepted/queued;
- started;
- meaningful graph progress/artifact availability;
- waiting for confirmation;
- resumed;
- succeeded with result reference;
- refused/cancelled;
- failed.

Events are append-only application history for the Run. Large Evidence bodies should stay in evidence/artifact tables and be referenced where possible.

## 14. JSON Logging and Prometheus Metrics

### 14.1 JSON logging

Use the already-declared `structlog` dependency for production JSON stdout logs.

Required contextual fields where applicable:

```text
timestamp
level
event
service                 # api | worker
run_id
job_id
project_id
user_id
job_type
business_mode
attempt_count
duration_ms
outcome
error_type
```

Sensitive content rules:

- no raw JWT;
- no API keys;
- no full secrets;
- user query/evidence/answer text should not be logged by default;
- provider error bodies must be sanitized before logging.

### 14.2 Prometheus

Add the minimal Prometheus client dependency. The API exposes its scrape endpoint through FastAPI. The Worker exposes a process-local Prometheus HTTP endpoint on a separately configured port using the same client library; it does not publish metrics through Redis, PostgreSQL, or another transport. The Compose design must give API and Worker distinct scrape targets.

Minimum metric families:

- HTTP request count/latency;
- Run count/latency/outcome by business mode;
- queue claim/completion/failure/retry/reaper counts;
- queue age or pending count where practical;
- retrieval rounds and RAGFlow request latency/error count;
- LLM request latency/error and token counts;
- citation guard pass/revision/refusal counts;
- authorization denial counts;
- Issue confirmation/create/reconciliation outcomes.

Metric labels must avoid unbounded cardinality. Do not label metrics by `run_id`, `user_id`, query text, issue key, or document ID.

## 15. Docker / Compose Runtime Closure

V1 local/staging completion must provide a reproducible container path for the application runtime.

The application Compose layer must include at least:

```text
postgres
app-api
app-worker
```

RAGFlow remains the fixed external/companion stack defined by its own supported deployment; it must not be reimplemented inside this project or replaced by another vector system. The completion documentation must make network/configuration expectations explicit.

Required characteristics:

- one application image may be reused by API and Worker with different commands;
- API and Worker use the same PostgreSQL and compatible local-file volume mapping;
- health/readiness behavior is meaningful, not only process-alive;
- startup does not claim RAGFlow/LLM readiness if required live dependencies are unreachable for a route that needs them;
- migrations/seeding have a documented deterministic invocation;
- configuration comes from environment/.env, not image-baked secrets;
- volumes preserve PostgreSQL data and required local source files;
- no Redis/Celery/MinIO sidecar is introduced.

## 16. Live Gates

A feature is not considered V1-complete only because mocks pass. The project must provide explicit, opt-in live gates that produce reproducible command output/artifacts.

Required live gates:

### 16.1 PostgreSQL

Verify:

- migration head;
- repositories and membership authorization;
- queue claim/lease/retry/reaper;
- run/event transaction path;
- evidence/citation persistence;
- Issue idempotency/reconciliation persistence.

### 16.2 RAGFlow

Verify:

- expected version/baseline;
- project-isolated ingestion and retrieval;
- retrieval mapping;
- no cross-project Evidence for the seeded two-project corpus.

### 16.3 LangGraph/checkpointer

Verify with PostgreSQL checkpointer:

- QA run can execute from durable run/job state;
- Issue create reaches an actual interrupt;
- process restart or separate Worker invocation can resume the saved checkpoint;
- resume reaches the intended node without replaying unsafe side effects.

### 16.4 Structured LLM

Verify:

- configured real provider is reachable;
- structured output validates;
- token usage is recorded;
- malformed/failing provider response maps to a controlled Run failure/refusal path as designed.

### 16.5 End-to-end API/Worker gates

At minimum demonstrate:

```text
API → PostgreSQL Run/Event/Job → Worker → QA Graph → result/SSE
```

and:

```text
API → Worker → Issue Graph interrupt
→ WAITING_CONFIRMATION
→ resume API → RESUME_AGENT_RUN
→ checkpoint resume → idempotent Sandbox create
→ terminal event/SSE
```

The gates must include negative security checks for non-member/cross-project access and unconfirmed Issue creation.

A README statement that a gate was once run is not sufficient completion evidence. The final completion report must reference reproducible commands and captured results from the target worktree/environment.

## 17. Evaluation Design

The existing `evaluation/datasets/v0/question-catalog.csv` remains the frozen starting catalog. It is not rewritten merely to improve scores.

V1 Completion adds an evaluation harness with four layers.

### 17.1 Frozen evaluation manifest / gold data

Create a versioned manifest that maps evaluation cases to the minimum gold data required for reproducible scoring, including where applicable:

- project scope;
- expected behavior class;
- expected identifier(s);
- expected source/evidence identifiers or acceptable evidence set;
- current-version expectations;
- refusal expectation;
- issue-side expected safety outcome.

Gold data must come from the seeded/frozen evaluation corpus. It cannot be inferred from the system answer being scored.

### 17.2 Runner and raw artifacts

The runner invokes the same Run Runtime Envelope used by the application, not a second evaluation-only graph.

Each trial must persist a raw result artifact with enough metadata to reproduce/inspect the run:

```text
evaluation dataset version
case id
business mode
project id
model alias
prompt version/hash
RAGFlow expected/observed version where available
run id
retrieval evidence IDs/ranks
answer/refusal/citations or issue outcome
latency/tokens/retrieval rounds
metric-relevant flags
```

Do not store secrets in evaluation artifacts.

### 17.3 Metrics

The evaluation must compute the V1 acceptance metrics from `v1-scope.md`:

| Metric | V1 target |
|---|---:|
| Exact-Identifier Hit@10 | >= 95% |
| Evidence Recall@10 | >= 90% |
| Current-Version Hit Rate | >= 95% |
| Citation ID Validity | 100% |
| No-answer refusal accuracy | >= 90% |
| Cross-project Evidence | 0 |
| Unconfirmed Issue creation | 0 |
| Duplicate Issue side effects | 0 |
| Critical Regression | 100% |

Metric definitions must be implemented explicitly and versioned. Missing gold labels must be reported as unscorable rather than silently counted as pass.

### 17.4 Ablations

Ablations are diagnostic and must not bypass safety boundaries. At minimum support controlled comparisons that isolate the value of:

- Exact Identifier Registry;
- Authority/current-version governance;
- Citation Guard;
- retrieval grade/second retrieval where measurable.

Cross-project ACL checks and unconfirmed-write protections are safety invariants, not ablation toggles for a normal benchmark run.

### 17.5 Report

Generate a deterministic report from raw results and metric output. The report must distinguish:

- target vs measured result;
- offline vs live-environment result;
- passed safety invariants vs quality metrics;
- unsupported/unscorable metrics;
- model/prompt/dataset/RAGFlow versions.

Numbers such as historical examples `82% → 97%` must not be presented as project results unless reproduced by the completed evaluation harness and backed by raw artifacts.

## 18. Workstream Decomposition

Each workstream is independently planned, TDD-driven, accepted, and committed. No single implementation plan may cover all eight workstreams.

### WS1 — Production Bootstrap + Authentication Wiring

**Responsibility**

- production composition root/resource lifecycle;
- real dependency construction for API-facing services;
- JWT Bearer FastAPI dependency;
- PostgreSQL membership-derived project authorization;
- replace production manual `DocumentActor` path while preserving test injection.

**Does not own**

- Run/SSE API;
- worker execute/resume handlers;
- LLM implementation;
- retrieval changes.

**Acceptance boundary**

A protected document operation can authenticate with JWT, derive current membership from PostgreSQL, reject non-members/revoked membership, and use production dependencies without hand-injected actors.

### WS2 — Run API + Agent Event + SSE

**Responsibility**

- Run/thread application service and repository boundary as needed;
- `POST /runs`, run read, event SSE, resume API;
- atomic Run + initial event + queue enqueue;
- explicit `project_id` contract;
- durable resume-input persistence;
- API-level authorization and reconnectable event ordering.

**Depends on** WS1.

**Does not own**

- executing LangGraph jobs;
- LLM/retrieval implementation.

**Acceptance boundary**

API can durably create/inspect/stream/resume authorized Runs and produces the correct queued jobs, using fakes for execution if WS3 is not yet merged.

### WS3 — PostgreSQL Worker Runtime + EXECUTE/RESUME Handlers

**Responsibility**

- Worker production bootstrap;
- real HandlerRegistry;
- `EXECUTE_AGENT_RUN` and `RESUME_AGENT_RUN`;
- enabled V1 handler registration decisions for existing job types;
- Run state/event transitions around graph execution;
- checkpoint identity/resume integration.

**Depends on** WS1 and WS2 contracts.

**Acceptance boundary**

A queued Run is consumed by a real Worker handler and dispatched to an injected graph; interrupted Runs can be resumed from durable input/checkpoint without unsafe replay.

### WS4 — Real Structured LLM + QA Completion

**Responsibility**

- real Structured LLM adapter and usage capture;
- provider failure handling;
- QA production dependency wiring;
- retrieval grade and max-two-round retrieval;
- QA graph live path and token/retrieval telemetry.

**Depends on** WS1–WS3 runtime contracts.

**Acceptance boundary**

A production QA Run can execute through RAGFlow + real structured LLM, generate/refuse under existing evidence/citation rules, never exceed two retrieval rounds, and persist answer/citations/usage.

### WS5 — Unified Issue Runtime + Requirement/Test Evidence Chain

**Responsibility**

- `issue_lookup` and `issue_create` Run dispatch;
- authorized requirement/test Evidence retrieval and frozen snapshot IDs;
- populate `IssueDraft.evidence_ids`;
- existing Issue Graph integration with Run events/status;
- real interrupt/resume through WS2/WS3;
- preservation of Task 13 permission/idempotency/reconciliation rules.

**Depends on** WS1–WS3; may reuse retrieval/LLM infrastructure from WS4 where justified but must not require answer generation.

**Acceptance boundary**

Issue lookup is read-only; Issue create reaches WAITING_CONFIRMATION with evidence/candidates/draft, and only an authorized valid resume can produce one idempotent Sandbox Issue.

### WS6 — Observability + Run Telemetry

**Responsibility**

- structlog JSON configuration/context;
- Prometheus endpoint/worker exposure;
- bounded-cardinality metrics;
- accurate run telemetry/cost policy;
- sanitization tests.

**Depends on** stable WS2–WS5 runtime/event semantics.

**Acceptance boundary**

API/Worker produce machine-readable logs and metrics covering success/failure/security/runtime paths without secrets or high-cardinality labels.

### WS7 — Docker / Compose + Live Gates

**Responsibility**

- application Docker image;
- Compose `app-api` and `app-worker` alongside PostgreSQL;
- local-file volume/network/config contract;
- documented RAGFlow companion-stack connection;
- migrations/seeding/runbooks;
- reproducible PostgreSQL/RAGFlow/LangGraph/LLM/end-to-end live gates.

**Depends on** WS1–WS6.

**Acceptance boundary**

A clean supported environment can start the V1 application stack and reproduce both business-flow live gates with captured pass/fail evidence.

### WS8 — Evaluation Runner + Metrics + Ablation + Report

**Responsibility**

- frozen gold manifest;
- runtime-based evaluation runner;
- raw artifacts;
- versioned metric definitions;
- safety-safe ablations;
- deterministic report generation;
- result-claim guardrails.

**Depends on** the stable runtime and live-gate interfaces from WS1–WS7.

**Acceptance boundary**

The project can run the frozen V1 evaluation, calculate all scorable acceptance metrics from raw artifacts, identify unscorable cases explicitly, run approved ablations, and generate a report that never confuses targets/examples with measured results.

## 19. Workstream Dependency Order

Recommended execution order:

```text
WS1  Production Bootstrap + Auth
 ↓
WS2  Run / Event / SSE API
 ↓
WS3  Worker Execute / Resume Runtime
 ├──────────────┐
 ↓              ↓
WS4 QA          WS5 Issue
 └──────┬───────┘
        ↓
WS6 Observability
        ↓
WS7 Docker + Live Gates
        ↓
WS8 Evaluation
```

WS4 and WS5 may be developed in parallel after WS3 if their shared runtime contracts are frozen and separate worktrees/commit boundaries are used.

## 20. Testing and Acceptance Strategy

Every workstream implementation plan must use TDD and define:

- the failing test/gate first;
- exact targeted test commands;
- existing regression commands;
- opt-in live commands where applicable;
- acceptance conditions;
- explicit commit boundary.

Global regression expectations after each workstream must preserve the existing Task 0–13 safety tests. No workstream is allowed to make skipped live tests pass by removing the live dependency assertion or replacing the real adapter with a fake.

The final V1 completion gate requires all of:

1. offline unit/contract/security/reliability/e2e regression green;
2. required live PostgreSQL/RAGFlow/LangGraph/LLM gates green in the declared environment;
3. API → Queue → Worker → QA end-to-end pass;
4. API → Queue → Worker → Issue interrupt/resume → Sandbox create pass;
5. P0 safety invariants pass;
6. Docker/Compose reproduction path documented and verified;
7. evaluation report generated from raw measured artifacts;
8. forbidden claims audit passes.

## 21. Explicit Non-Goals

V1 Completion will not:

- redesign Task 0–13 into a different architecture;
- introduce a second workflow engine or queue;
- add production Jira/禅道/飞书 write adapters;
- add a client guest/tenant billing product surface;
- add long-term conversational memory;
- add code-changing or production-deployment agents;
- automatically determine business responsibility, cost, schedule, contract authority, or Issue duplication;
- automatically publish documents or bypass human authority governance;
- claim real-business validation that Task 0 explicitly marks pending;
- claim target/example evaluation numbers as measured results.

## 22. Completion Definition

V1 Completion is achieved only when the frozen V1 capabilities operate as one verified runtime system, not merely as individually-tested modules.

The decisive proof is:

```text
real authenticated request
→ current project membership
→ durable run/event/job
→ PostgreSQL worker
→ existing LangGraph workflow
→ real configured infrastructure adapters
→ durable governed result
→ observable/reconnectable event stream
→ safe human-confirmed write when applicable
→ reproducible live gates
→ reproducible evaluation report
```

Until that chain is demonstrated, the correct project description is "Task 0–13 component implementation largely complete; V1 end-to-end completion in progress," not "V1 fully complete."
