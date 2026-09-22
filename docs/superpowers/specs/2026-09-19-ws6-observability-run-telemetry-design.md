# WS6 — Observability + Run Telemetry Detailed Design

- **Project:** `it-outsourcing-knowledge-agent`
- **Workstream:** WS6 — Observability + Run Telemetry
- **Date:** 2026-09-19
- **Status:** Design Freeze Candidate — self-review complete; pending human approval
- **WS6 branch:** `feat/ws6-observability-run-telemetry`
- **WS6 starting HEAD:** `5123efbaa3821f34a6198cdebadd4631f8bceeef`
- **Frozen WS4 branch:** `feat/ws4-real-structured-llm-qa`
- **Frozen WS4 HEAD:** `ed6add6`
- **Alembic baseline/head:** `0005_run_runtime_envelope`
- **Fresh offline baseline:** `328 passed, 26 skipped`

## 1. Source of truth and design authority

This design is derived from the current WS6 handoff source and the verified real-server state. Source-of-truth priority remains:

1. real WS6 server worktree and Git state;
2. `WS6_SERVER_SNAPSHOT.txt`;
3. `it-outsourcing-knowledge-agent-ws6-start.zip`;
4. `docs/superpowers/specs/2026-09-12-v1-completion-design.md`;
5. `docs/adr/0004-v1-architecture-lock.md`;
6. `docs/business/v1-scope.md`;
7. `docs/business/forbidden-claims.md`;
8. WS1–WS5 completed/planning documents;
9. `README.md`, `pyproject.toml`, `src/project_agent/`, and `tests/`.

Verified server facts at design time:

```text
branch = feat/ws6-observability-run-telemetry
HEAD = 5123efbaa3821f34a6198cdebadd4631f8bceeef
working tree = clean
Python = 3.12.14
ruff = GREEN
mypy = GREEN
pytest = 328 passed, 26 skipped
alembic current = 0005_run_runtime_envelope
alembic heads = 0005_run_runtime_envelope
```

The frozen V1 completion design defines WS6 responsibility as:

- `structlog` JSON configuration/context;
- Prometheus API endpoint and Worker exposure;
- bounded-cardinality metrics;
- accurate Run telemetry and cost policy;
- sanitization tests.

Its acceptance boundary is that API and Worker produce machine-readable logs and metrics covering success, failure, security, and runtime paths without secrets or high-cardinality labels.

## 2. Design goal

WS6 instruments the existing runtime so that operators and later evaluation tooling can answer:

- what happened to an API request, job, and Run;
- how long it took;
- whether it succeeded, refused, cancelled, retried, reconciled, or failed;
- how RAGFlow and the structured LLM behaved;
- how many retrieval rounds and tokens a Run consumed;
- whether citation, authorization, and Issue safety paths fired;
- what configured token-price policy estimates the Run cost to be;
- whether the observed values are configured estimates rather than invented provider prices.

The governing principle is:

```text
instrument existing runtime
NOT
redesign existing runtime
```

## 3. Non-goals and frozen boundaries

WS6 must not change the business semantics frozen by WS1–WS5.

### 3.1 Frozen contracts

WS6 may add logging, metrics, timing, context binding, and telemetry persistence at existing seams. It must not change:

- WS2 Run API request/response, Run persistence, event ordering, SSE, or resume contract;
- WS3 PostgreSQL queue ownership, leases, heartbeats, retry policy, reaper semantics, checkpointing, execute/resume semantics, or transaction boundaries;
- WS4 retrieval, answer generation, structured LLM, max-two-round retrieval, evidence, citation, or refusal semantics;
- WS5 Issue evidence, confirmation, idempotency barrier, create/reconciliation, or side-effect semantics.

### 3.2 Architecture lock

WS6 does not introduce:

- Redis, ARQ, or Celery;
- MinIO;
- a second vector database;
- a new multi-agent runtime;
- a unified LangGraph rewrite;
- Kubernetes;
- production Jira / 禅道 / 飞书 project-system integration.

### 3.3 Persistence boundary

No Alembic migration is required by this design. `agent_runs` already contains:

```text
model_alias
prompt_version
prompt_content_hash
input_tokens
output_tokens
total_tokens
retrieval_rounds
ocr_pages
estimated_cost_microunits
cost_currency
started_at
finished_at
status
```

`cost_estimate_configured` is an observability fact, not a new durable Run column. A migration may be proposed only if a later RED test proves an approved WS6 acceptance requirement cannot be met with the existing schema.

## 4. Current capability map

### 4.1 Already present

The starting tree already has:

- `structlog` declared in `pyproject.toml`;
- durable Run lifecycle status plus `started_at` / `finished_at`;
- prompt model/version/hash persistence through the QA graph store;
- cumulative LLM input/output/total token persistence;
- retrieval-round persistence;
- `ocr_pages` and cost columns in `agent_runs`;
- RAGFlow centralized HTTP boundary with retry behavior;
- Run lifecycle service with idempotent terminal projection;
- PostgreSQL queue with claim, completion, retry/final failure, heartbeat, and lease reaping;
- Citation Guard pass/revision/refusal branching;
- project authorization and additional Run/Issue safety checks;
- Issue confirmation, idempotent creation, pending reconciliation, and reconciliation outcomes.

### 4.2 Missing

The starting tree does not yet provide:

- production JSON structured logging configuration;
- contextual log binding and cleanup;
- a log sanitization policy with tests;
- a Prometheus client dependency;
- API `/metrics`;
- Worker process-local metrics exposure;
- HTTP, Run, queue, provider, citation, authorization, or Issue metric families;
- a configured cost-estimation policy;
- code that updates `estimated_cost_microunits`;
- observability-specific regression tests.

## 5. WS4 integration state

The verified repository contains the frozen branch:

```text
feat/ws4-real-structured-llm-qa @ ed6add6
```

The current WS6 starting HEAD is:

```text
feat/ws6-observability-run-telemetry @ 5123efb
```

The WS6 handoff tree itself does not contain the frozen WS4 production Structured LLM implementation. Therefore:

1. WS6 must not reimplement the WS4 adapter or QA semantics;
2. the implementation plan must include an explicit frozen-WS4 integration gate before LLM-provider-specific WS6 work;
3. any merge conflict resolution is integration-only and must preserve both frozen WS4 and WS5 behavior;
4. the exact frozen WS4 commit/branch is used, not reconstructed from memory;
5. after integration, the full baseline is rerun before WS6 LLM instrumentation proceeds.

The observability design targets the stable WS4 application ports (`StructuredLLMPort`, `StructuredLLMUsagePort`) rather than depending on provider-specific details.

## 6. High-level architecture

```text
                         +-----------------------------+
                         | Observability Foundation    |
                         |                             |
                         | structlog JSON config       |
                         | contextvars                 |
                         | sanitization                |
                         | Prometheus registry         |
                         | cost estimation policy      |
                         +--------------+--------------+
                                        |
              +-------------------------+--------------------------+
              |                         |                          |
              v                         v                          v
            FastAPI                   Worker                      Run
              |                         |                          |
              |                    PostgreSQL Queue                |
              |                         |                          |
              +---------- RAGFlow -----+--------------------------+
              |                                                    |
              +------ Structured LLM / WS4 -----------------------+
              |                                                    |
              +------ Citation / Authorization -------------------+
              |                                                    |
              +------ Issue confirmation/create/reconcile --------+
```

Observability is a side effect of the existing runtime. It must never become a prerequisite for business correctness: a logging/metrics recording failure must not change an otherwise valid Run, queue, retrieval, or Issue outcome.

## 7. Proposed file/module boundaries

The implementation should introduce a focused observability package:

```text
src/project_agent/observability/
├── __init__.py
├── logging.py
├── sanitization.py
├── metrics.py
└── cost.py
```

Responsibilities:

- `logging.py`: idempotent `structlog` JSON configuration, logger acquisition, contextvar bind/clear helpers, duration helpers;
- `sanitization.py`: defense-in-depth field filtering and safe exception metadata;
- `metrics.py`: process-local Prometheus registry, collectors, bounded recording methods, API rendering helpers, Worker metrics-server lifecycle helper;
- `cost.py`: immutable explicit-price policy and integer microunit calculation.

Existing files are modified only at stable instrumentation seams. No broad runtime refactor is part of WS6.

## 8. Structured logging design

### 8.1 Output format

Production logs go to stdout as one JSON object per event through `structlog`.

Every event carries these common fields when applicable:

```text
timestamp
level
event
service
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

Not every event must have every field. Missing context is omitted rather than populated with fake values.

`timestamp` is UTC ISO-8601. `duration_ms` is numeric. `level` is normalized by the logging configuration.

### 8.2 Context lifecycle

Use `structlog.contextvars` so concurrent async requests/jobs do not share mutable context.

API lifecycle:

```text
clear contextvars
→ bind service=api
→ execute request
→ bind additional known run/project/user context where applicable
→ emit completion/failure event
→ clear contextvars in finally
```

Worker lifecycle:

```text
clear contextvars
→ bind service=worker, job_id, job_type, attempt_count
→ handler loads business object
→ bind run/project/user/business_mode where known
→ emit outcome
→ clear contextvars in finally
```

The Worker must not assume every `aggregate_id` is a Run ID because reconciliation and retention jobs use different aggregate semantics.

### 8.3 Event catalog

The design uses stable semantic event names. Initial V1 event names are:

```text
http_request_completed
http_request_failed
job_claimed
job_completed
job_retry_scheduled
job_failed
job_reaped
run_started
run_waiting_confirmation
run_succeeded
run_refused
run_cancelled
run_failed
ragflow_request_completed
ragflow_request_failed
llm_request_completed
llm_request_failed
llm_usage_recorded
citation_guard_passed
citation_guard_revision
citation_guard_refused
authorization_denied
issue_confirmation_recorded
issue_create_outcome
issue_reconciliation_outcome
```

These are log event names only. They do not rename or replace durable `AgentEventType` values and therefore do not alter SSE/evaluation contracts.

### 8.4 Sensitive-data policy

Logs must not contain:

- raw JWTs or Authorization headers;
- API keys;
- passwords, secrets, cookies, provider credentials;
- complete user query text;
- complete Evidence text;
- complete answer text;
- complete system/user prompts;
- raw request/response bodies;
- raw provider error bodies;
- arbitrary exception messages when those messages may contain provider/user data.

The preferred control is **allowlisted event construction**: event producers log IDs, bounded codes, timings, counts, and states rather than whole objects.

A global sanitizer is still applied as defense in depth. Keys representing credentials or protected content are replaced with a redaction marker rather than serialized.

Provider exceptions are converted to safe metadata. For example, RAGFlow failures may expose:

```text
provider=ragflow
operation=retrieve
status_code=500
error_type=RagflowHttpError
outcome=failure
```

They must not log `RagflowHttpError.message`, `RagflowApiError.message`, `str(exc)`, or raw response text.

Default production JSON logging does not automatically serialize `exc_info` for provider failures because the exception string may embed the provider body. Unexpected internal failures may record `error_type` and a bounded internal error code; adding stack traces later requires a separate safety review.

## 9. Prometheus design

### 9.1 Registry ownership

Each process owns one Prometheus registry:

- API process: one registry rendered by FastAPI `/metrics`;
- Worker process: one registry exposed by a small process-local HTTP metrics server.

Do not use PostgreSQL, Redis, or another transport to aggregate Worker metrics.

The registry implementation must support isolated registries in tests to avoid duplicate-collector registration and cross-test counter leakage.

### 9.2 Cardinality rules

Prometheus labels must be finite or tightly bounded.

Never use these as labels:

```text
run_id
job_id
user_id
project_id
query text
issue key
document ID
document version ID
RAGFlow dataset/document ID
raw URL containing resource IDs
arbitrary exception/error body
provider response body
```

Approved label dimensions are limited to enumerated/configured values such as:

```text
method
route_template
status_code
business_mode
outcome
job_type
operation
model_alias
direction
reason
```

`model_alias` is the configured application model alias, not provider response text.

### 9.3 HTTP metrics

Metric families:

```text
project_agent_http_requests_total{method,route,status_code}
project_agent_http_request_duration_seconds{method,route}
```

`route` uses the matched FastAPI/Starlette route template, for example:

```text
/api/v1/runs/{run_id}
```

It must never use the raw path containing a UUID. Requests that cannot be mapped to a route use a fixed fallback such as `unmatched`.

The API exposes:

```text
GET /metrics
```

The metrics response itself is observable without introducing request-specific labels.

### 9.4 Run metrics

Metric families:

```text
project_agent_runs_total{business_mode,outcome}
project_agent_run_duration_seconds{business_mode,outcome}
```

Allowed terminal outcomes:

```text
succeeded
refused
cancelled
failed
```

Run metrics are emitted only when `RunExecutionService` performs a new terminal transition. Existing idempotent early returns for already-terminal Runs must not increment counters again.

Duration uses the durable Run `started_at` and terminal `finished_at`; resume does not reset the original start timestamp.

`WAITING_CONFIRMATION` is observable in logs but is not a terminal Run outcome and therefore does not increment `project_agent_runs_total`.

### 9.5 Queue metrics

Metric families:

```text
project_agent_queue_claims_total{job_type}
project_agent_queue_completions_total{job_type}
project_agent_queue_failures_total{job_type,outcome}
project_agent_queue_reaped_total{job_type,outcome}
project_agent_queue_age_seconds{job_type}
```

Allowed failure outcomes:

```text
retry
failed
```

Allowed reaper outcomes:

```text
retry
failed
```

The PostgreSQL queue is the authoritative seam for retry-vs-final-failure and reaper decisions because it already evaluates `attempt_count`, `max_attempts`, leases, and retry delay. Instrumentation must not duplicate or recalculate that policy in the Worker.

Queue age is observed at claim from the durable job timestamp to claim time. It is a histogram, not a per-job gauge. This avoids adding new queue-domain fields or polling the database solely for metrics.

### 9.6 Retrieval and RAGFlow metrics

Metric families:

```text
project_agent_retrieval_rounds_total
project_agent_ragflow_requests_total{operation,outcome}
project_agent_ragflow_request_duration_seconds{operation}
```

`retrieval_rounds_total` increments at the same successful logical point where durable `agent_runs.retrieval_rounds` is incremented. It has no Run/document/user label.

RAGFlow `operation` comes from a finite normalization table, not the raw path. Expected values include the operations already represented by the adapter, such as:

```text
dataset_list
dataset_create
document_upload
document_metadata_update
parse_start
document_list
document_delete
retrieve
```

Unknown paths map to a fixed `other` operation. Dynamic dataset/document IDs never reach metric labels.

A request that succeeds after retry counts as one completed logical RAGFlow request with its full observed latency. A terminal transport/HTTP/API/protocol failure counts as one error outcome. Retry attempts may be represented in structured logs if useful but do not create unbounded labels.

### 9.7 LLM metrics

After the frozen WS4 implementation is integrated, instrumentation wraps the stable structured-LLM boundary rather than rewriting the provider adapter.

Metric families:

```text
project_agent_llm_requests_total{model_alias,outcome}
project_agent_llm_request_duration_seconds{model_alias}
project_agent_llm_tokens_total{model_alias,direction}
```

Allowed outcomes:

```text
success
error
```

Allowed token directions:

```text
input
output
total
```

Prompts, generated text, provider payloads, and provider error bodies are never metric values or labels.

The wrapper/decorator implements the existing `StructuredLLMPort` / `StructuredLLMUsagePort` behavior and delegates to the frozen WS4 implementation. It does not alter request IDs, model selection, structured response validation, usage semantics, retry behavior, or provider error propagation.

### 9.8 Citation Guard metrics

Metric family:

```text
project_agent_citation_guard_total{outcome}
```

Allowed outcomes:

```text
pass
revision
refusal
```

The graph node is the authoritative seam because only it knows whether a failed validation triggers the one allowed revision or final refusal.

### 9.9 Authorization metrics

Metric family:

```text
project_agent_authorization_denials_total{reason}
```

`reason` is an internal bounded code, never `str(exc)`. Initial codes are limited to existing safety decisions, for example:

```text
no_active_membership
scope_mismatch
actor_mismatch
role_denied
```

Adding a new reason requires code review to ensure it is bounded. Authentication failures may remain represented by HTTP status metrics unless a later approved requirement adds a separate authentication metric family.

### 9.10 Issue metrics

Metric families:

```text
project_agent_issue_confirmation_total{outcome}
project_agent_issue_create_total{outcome}
```

Confirmation outcomes:

```text
confirmed
cancelled
expired
payload_mismatch
```

Issue create/reconciliation outcomes:

```text
created
already_created
pending_reconciliation
reconciled
denied
```

Metrics are emitted only after the existing service determines the business outcome. Instrumentation must not move the confirmation check, permission re-check, idempotency reservation, provider create, or reconciliation decision.

## 10. API metrics endpoint design

`create_app()` adds an unauthenticated Prometheus scrape route at `/metrics` that contains only aggregated process metrics and no business payloads, IDs, queries, Evidence, or answers.

The API process owns its registry. Tests must be able to create multiple app instances with isolated registries without duplicate-registration errors.

HTTP middleware records status and latency for normal responses and exceptions. It must:

- use route templates, never raw request paths as labels;
- not log headers or bodies;
- clear contextvars in `finally`;
- preserve existing FastAPI exception behavior and response models.

## 11. Worker metrics endpoint design

The Worker process exposes a small Prometheus HTTP endpoint on a separately configured host/port. Proposed settings:

```text
worker_metrics_enabled: bool = true
worker_metrics_host: str = "127.0.0.1"
worker_metrics_port: int = 9101
```

WS7 may override host/network values for Compose so API and Worker remain distinct scrape targets.

The Worker runtime owns the metrics-server lifecycle. Startup creates the server; shutdown closes it. Tests can disable the endpoint or use an isolated/ephemeral configuration so test processes do not leak listening sockets.

Starting or stopping the metrics endpoint must not alter Worker polling, claim, heartbeat, lease, or handler behavior.

## 12. Run telemetry design

### 12.1 Existing durable fields

WS6 reuses the existing `agent_runs` telemetry fields.

Current producers remain authoritative:

- prompt load → `model_alias`, prompt version/hash;
- LLM usage recording → cumulative input/output/total tokens;
- retrieval execution → retrieval rounds;
- Run execution → start/finish/status.

### 12.2 OCR pages

WS6 does not create a new OCR pipeline. If OCR is not performed, `ocr_pages` remains `0` exactly as the frozen V1 design requires.

A future existing ingestion/OCR producer may update the field when such data is genuinely available, but WS6 must not infer OCR page counts from PDF page count, file metadata, or model knowledge.

### 12.3 Cost configuration

Add Settings fields equivalent to:

```text
llm_input_cost_microunits_per_million_tokens: int | None = None
llm_output_cost_microunits_per_million_tokens: int | None = None
cost_currency: str = "USD"
```

Rules:

1. input and output prices are either both configured or both omitted;
2. configured prices are non-negative integers;
3. currency is a short normalized code suitable for the existing `cost_currency` column;
4. no provider/model price is inferred from model alias;
5. no price table is hard-coded from model knowledge or web memory;
6. development/test may omit both rates;
7. the staging/live acceptance gate must explicitly configure both rates.

### 12.4 Cost computation

Cost is computed from cumulative Run token totals using integer arithmetic:

```text
numerator =
    cumulative_input_tokens  * input_price_microunits_per_million_tokens
  + cumulative_output_tokens * output_price_microunits_per_million_tokens

estimated_cost_microunits = numerator // 1_000_000
```

The division is performed after using cumulative Run token totals, not once per LLM call. This prevents repeated per-call flooring from accumulating avoidable rounding loss.

When prices are omitted:

```text
estimated_cost_microunits = 0
cost_estimate_configured = false
```

When both prices are configured:

```text
cost_estimate_configured = true
```

`cost_estimate_configured` is emitted in structured telemetry so a zero estimate cannot be misrepresented as a measured provider cost.

### 12.5 Atomic persistence point

The existing QA graph store is the authoritative persistence seam for token accumulation. WS6 extends that same transaction to recompute and persist the cumulative estimated cost immediately after token totals change.

This design has four properties:

- token and cost persistence stay consistent;
- multiple LLM calls/revisions produce one cumulative Run estimate;
- failed Runs still retain already-recorded token cost if usage was successfully captured before failure;
- no new Run API or database schema contract is needed.

The cost policy is injected from runtime settings. An omitted policy behaves as an explicit unconfigured policy, not as an implicit provider price.

## 13. Instrumentation ownership matrix

| Concern | Authoritative seam | Why |
|---|---|---|
| HTTP request count/latency | FastAPI middleware | Knows matched route/status/duration without touching business services |
| API metrics scrape | FastAPI `/metrics` | Process-local API registry |
| Worker job context/logs | `BackgroundWorker._process` | Knows job ID/type/attempt and handler outcome |
| Queue claim/age | `PostgresJobQueue.claim` | Has durable row timestamps and job type |
| Queue retry/final failure | `PostgresJobQueue.fail` | Owns retry decision |
| Reaper outcome | `PostgresJobQueue.reap_expired` | Owns lease-expiry decision |
| Run terminal count/duration | `RunExecutionService` | Owns idempotent terminal transition |
| Retrieval round count | Existing graph-store increment seam | Same logical point as durable round update |
| RAGFlow latency/error | `RagflowHttpClient` | Central provider HTTP boundary |
| LLM latency/error | Observed wrapper around frozen WS4 LLM port | Preserves provider adapter semantics |
| LLM token metrics | LLM usage wrapper | Owns usage returned by WS4 |
| Token/cost persistence | QA graph store usage update | Atomic with cumulative Run token state |
| Citation pass/revision/refusal | Citation Guard graph node | Owns final routing decision |
| Authorization denial | Existing authorization/run/issue safety branches | Own fixed, bounded denial reason |
| Issue confirmation outcome | `IssueConfirmationService.record_decision` | Owns confirmation decision |
| Issue create/reconcile outcome | `IssueCreationService` | Owns idempotency/create/reconcile status |

The rule is: **the component that knows the real outcome emits the observation**. Higher layers must not infer internal outcomes from a final Run status.

## 14. Failure isolation

Observability must be fail-safe relative to business behavior.

- Structlog serialization uses supported scalar/collection metadata only.
- Metric recording methods do not perform network or database I/O.
- Metrics-server failure during Worker startup is a runtime configuration/startup failure, not a change to queue semantics.
- Logging/metric helpers must not raise because an optional context field is absent.
- Provider instrumentation uses `try/finally` timing but re-raises the original provider exception unchanged.
- No observability code catches and converts business exceptions into different domain outcomes.

## 15. Security and sanitization design

WS6 requires explicit tests proving that sensitive values do not leave through logs or metrics.

Minimum sensitive fixtures include unique sentinel values for:

```text
JWT
RAGFlow API key
LLM API key
password/secret
full query
Evidence text
answer text
system prompt
user prompt
provider error body
issue key
document ID
user ID/run ID for metric-label tests
```

Required assertions:

- sentinels for credentials/content do not occur in captured JSON log output;
- provider error body sentinel does not occur in logs;
- raw dynamic IDs/content do not occur in rendered Prometheus label values;
- IDs explicitly permitted in structured logs, such as `run_id`/`user_id`, remain absent from Prometheus output;
- redaction does not remove safe event type, outcome, timing, and error class fields needed for debugging.

## 16. Test strategy

WS6 implementation follows strict TDD:

```text
RED
→ verify failure is the missing WS6 behavior
→ minimal GREEN
→ targeted regression
→ broader regression
```

### 16.1 Offline/unit gates

Required coverage includes:

- JSON log shape and UTC timestamp/level/event;
- context bind/clear and concurrent context isolation;
- sanitizer redaction;
- safe provider exception projection;
- cost settings validation;
- configured/unconfigured cost policy;
- cumulative integer cost calculation across multiple LLM calls;
- isolated Prometheus registries;
- metric label whitelist/cardinality behavior;
- API `/metrics` and route-template HTTP metrics;
- queue claim/completion/retry/final-failure/reaper metrics;
- terminal Run metrics emitted once;
- retrieval-round metrics;
- RAGFlow success/error latency metrics using deterministic HTTP fakes;
- LLM wrapper success/error/token metrics after WS4 integration;
- Citation Guard pass/revision/refusal metrics;
- authorization denial metrics;
- Issue confirmation/create/reconciliation outcomes;
- no business behavior changes in existing tests.

### 16.2 PostgreSQL live gate

PostgreSQL is required for final WS6 closure. It must verify at minimum:

- current schema remains `0005_run_runtime_envelope` unless a separately approved migration becomes necessary;
- cumulative Run token and cost persistence;
- Run start/finish/outcome instrumentation on real repositories;
- queue claim/retry/final-failure/reaper metrics on real rows;
- resume/confirmation behavior remains unchanged.

### 16.3 RAGFlow live gate

The existing real-RAGFlow gate is required for final WS6 closure of provider success-path telemetry. Deterministic failure/sanitization behavior should be tested offline so the test suite does not depend on intentionally destabilizing a live provider.

### 16.4 LLM live gate

LLM live telemetry requires the frozen WS4 implementation to be integrated first. Once available, final WS6 closure must prove a real structured-LLM call records request latency and real provider-returned usage through the existing usage path. Prices still come only from explicit WS6 configuration; provider prices are not inferred.

If the required WS4 integration or live LLM environment is unavailable, the LLM live gate is reported as incomplete rather than silently skipped and called GREEN.

### 16.5 Completion baseline

Before claiming WS6 COMPLETE, run at least:

```text
ruff check src tests
mypy src
git diff --check
python -m pytest -q -rs
alembic current
alembic heads
```

plus required PostgreSQL, RAGFlow, and LLM live gates for the implemented WS6 paths.

## 17. Expected Settings changes

The implementation may add only WS6-specific settings required by this design:

```text
log_level
worker_metrics_enabled
worker_metrics_host
worker_metrics_port
llm_input_cost_microunits_per_million_tokens
llm_output_cost_microunits_per_million_tokens
cost_currency
```

Existing secret fields remain `SecretStr`. No secret is copied into log context or metric labels.

No new external infrastructure setting is allowed.

## 18. Dependency changes

- Keep existing `structlog` dependency.
- Add the minimal official Prometheus Python client dependency.
- Do not add OpenTelemetry, StatsD, Redis metrics transport, Sentry, or another observability backend in WS6.

Exact dependency version bounds are implementation-plan details and must remain compatible with Python 3.12 and the existing project dependency policy.

## 19. Deployment/runtime interaction

WS6 prepares runtime observability; WS7 owns Docker/Compose closure.

WS6 therefore provides:

- API `/metrics`;
- separately configurable Worker metrics HTTP exposure;
- stdout JSON logs;
- settings needed for explicit cost estimation.

WS6 does not add Kubernetes, Prometheus server deployment, Grafana, log shipping, alert rules, dashboards, or Compose topology beyond the interfaces WS7 will consume.

## 20. Observability semantics vs durable application events

Three data categories remain distinct:

1. **`agent_events`** — durable business/runtime history consumed by API/SSE/evaluation;
2. **structured logs** — machine-readable operational diagnostics, ephemeral by default;
3. **Prometheus metrics** — aggregated process telemetry with bounded labels.

Prometheus counters/histograms are operational best-effort telemetry, not a transactional audit ledger. A process crash or a database rollback after an in-process observation can create temporary divergence. Exact business/evaluation truth must come from durable Run/Event/telemetry records, not from reconstructing audited counts from Prometheus. Queue observations should be emitted after the queue's own commit where practical; Run instrumentation relies on the existing idempotent transition guard to prevent normal replay double-counting.

WS6 must not replace durable `agent_events` with logs/metrics and must not store large Evidence/answer bodies in logs merely because they already exist in database artifacts.

## 21. Acceptance criteria

WS6 is complete only when all applicable criteria are demonstrated:

1. API emits JSON structured logs and serves Prometheus metrics.
2. Worker emits JSON structured logs and exposes a distinct process-local Prometheus endpoint.
3. context from one request/job does not leak into another.
4. metrics use only bounded labels and never contain raw Run/user/query/Issue/document identifiers as labels.
5. HTTP request count/latency are visible by method/route/status.
6. terminal Run count/duration/outcome are visible by business mode without double counting replayed terminal transitions.
7. queue claim/completion/retry/final failure/reaper and queue-age telemetry are visible without altering queue semantics.
8. retrieval rounds and RAGFlow latency/errors are observable.
9. integrated WS4 LLM request latency/error/token counts are observable without logging prompts/responses/provider bodies.
10. Citation Guard pass/revision/refusal counts are observable.
11. authorization denials are observable with bounded internal reason codes.
12. Issue confirmation/create/reconciliation outcomes are observable without changing confirmation/idempotency/reconciliation behavior.
13. Run model/prompt/token/retrieval/start/finish/status fields remain accurate.
14. configured token prices produce deterministic integer microunit estimates.
15. omitted dev/test prices leave estimated cost at zero and emit `cost_estimate_configured=false`.
16. no provider price is hard-coded or inferred.
17. OCR pages remain zero when OCR is not performed.
18. sanitization tests prove JWT/API keys/secrets/query/Evidence/answer/prompt/provider-body content do not leak.
19. no new Alembic migration is introduced unless separately justified by a failing approved requirement.
20. required live integration skips are reported as incomplete, not as WS6 completion.

## 22. Out of scope for WS6

Explicitly deferred:

- WS7 Docker/Compose implementation;
- WS8 evaluation runner/metrics/report;
- Prometheus server installation;
- Grafana/dashboard work;
- alerting/on-call policy;
- distributed tracing/OpenTelemetry;
- centralized log storage;
- production SaaS observability;
- production Jira/project tracker integration;
- a new OCR subsystem;
- business-level cost budgets or billing;
- provider-price auto-discovery;
- any multi-agent redesign.

## 23. Implementation decomposition boundary

After this design is approved, `writing-plans` should turn it into reviewable TDD tasks roughly along these boundaries:

1. frozen WS4 integration/baseline gate;
2. observability foundation, settings, cost policy, and dependency;
3. API JSON logging + HTTP metrics + `/metrics`;
4. Worker/queue logging + metrics endpoint + queue telemetry;
5. Run lifecycle and durable cost telemetry;
6. RAGFlow/retrieval + integrated WS4 LLM telemetry;
7. Citation/authorization/Issue outcome telemetry;
8. sanitization regression and PostgreSQL/RAGFlow/LLM live closure.

This section is not the Implementation Plan. It defines design boundaries only; exact files, RED tests, commands, and commits belong in the subsequent plan after human approval.

## 24. Design Review Record

### 24.1 Placeholder scan

Result: **PASS**.

No unresolved implementation placeholders remain. The WS4 integration is an explicit prerequisite, not an unspecified implementation detail.

### 24.2 Internal consistency

Result: **PASS**.

Checked invariants:

- API and Worker metrics are process-local and use separate scrape endpoints;
- logs may contain contextual IDs, while Prometheus labels may not;
- durable Run telemetry reuses existing schema;
- `cost_estimate_configured` remains structured telemetry rather than a new database column;
- cost is derived only from explicit configured integer rates;
- cost calculation uses cumulative tokens and integer arithmetic;
- Run terminal metrics follow existing idempotent terminal transitions;
- queue retry/reaper metrics are emitted where the existing queue already decides the outcome;
- LLM observability wraps frozen WS4 interfaces and does not reconstruct WS4 behavior;
- WS7/WS8 responsibilities remain out of scope.

### 24.3 Scope check

Result: **PASS**.

The design is large but cohesive: every component serves WS6 observability/telemetry. It does not introduce a second business subsystem. Task decomposition can stay under one WS6 implementation plan.

### 24.4 Ambiguity check

Result: **PASS with explicit resolutions**.

Previously ambiguous points are resolved as follows:

- **Queue age vs pending count:** choose queue-age histogram at claim; no new polling query is required.
- **Raw RAGFlow path labels:** forbidden; use a finite operation normalizer.
- **LLM integration:** wrap frozen WS4 ports after explicit branch integration; do not rewrite provider code.
- **Cost rounding:** floor only once after cumulative-token numerator is calculated.
- **Unconfigured price:** persist zero and emit `cost_estimate_configured=false`.
- **OCR pages:** remain zero when no OCR producer exists.
- **Run terminal metrics:** increment only on a newly persisted terminal transition.
- **Worker scrape:** separate configurable process-local HTTP endpoint; lifecycle owned by Worker runtime.
- **Provider errors:** log type/code/status only, not raw error body/message.
- **Schema:** no migration under the approved design.

### 24.5 Frozen-contract collision review

Result: **PASS, with one controlled integration risk**.

No planned WS6 behavior requires changing WS2, WS3, WS4, or WS5 business semantics. The main collision risk is integrating the already-frozen WS4 branch with the WS5-based WS6 starting branch. The implementation plan must treat merge conflict resolution as an integration gate and rerun the complete baseline before any LLM-specific instrumentation.

### 24.6 Security review

Result: **PASS at design level; implementation proof required**.

The design defaults to allowlisted operational fields, defense-in-depth sanitization, no raw exception bodies, and bounded metric labels. Completion still requires executable sanitization and metric-rendering tests with sentinel secrets/content.

### 24.7 Migration review

Result: **NO MIGRATION REQUIRED**.

The existing `0005_run_runtime_envelope` schema already contains the Run telemetry fields required by the frozen V1 design.

### 24.8 Live-gate review

Result: **DEFINED, NOT YET EXECUTED**.

Final WS6 closure depends on:

- PostgreSQL live gate: required;
- RAGFlow live success-path telemetry gate: required;
- structured LLM live telemetry gate: required after frozen WS4 integration;
- offline provider failure/sanitization tests: required;
- required skips do not count as completion.

## 25. Freeze decision

This document is ready to become the frozen WS6 detailed design.

Human approval of this document is the gate for the next Superpowers stage:

```text
brainstorming / design
        ↓ approval
writing-plans
        ↓ plan review
TDD implementation
```

No production coding should begin before the Design is approved and the subsequent Implementation Plan has also been reviewed.
