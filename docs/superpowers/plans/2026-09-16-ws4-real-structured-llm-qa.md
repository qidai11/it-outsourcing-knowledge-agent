# WS4 Real Structured LLM + QA Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task after the Plan Review Gate is approved. Every production-code task also requires `superpowers:test-driven-development`; unexpected failures require `superpowers:systematic-debugging`; every completion claim requires `superpowers:verification-before-completion`; final branch close-out requires `superpowers:finishing-a-development-branch`.

**Status:** PLAN REVIEW REQUIRED — revised to 3 Big Tasks. Do not start Big Task 1 until this revised plan and Decisions A/B are approved.

**Goal:** Complete WS4 by adding the real Structured LLM adapter, bounded retrieval grading/second retrieval, canonical RAGFlow project scoping, and production QA Worker composition on top of the frozen WS1–WS3 runtime contracts.

**Architecture:** Retain the existing QA LangGraph, `StructuredLLMPort`, `QAGraphStorePort`, evidence governance, Citation Guard, RAGFlow adapter, and WS3 `RunGraphExecutor`/Worker lifecycle. Extend only the missing WS4 seams: a concrete asynchronous Structured LLM HTTP adapter; a structured retrieval-grade node with a hard maximum of two retrieval rounds; safe RAGFlow project-code/dataset binding; and a production QA graph factory that plugs into the existing Worker graph-executor injection point. Do not introduce a second orchestration architecture or a second LLM abstraction.

**Tech Stack:** Python 3.12, FastAPI project runtime, Pydantic v2, SQLAlchemy async + PostgreSQL, LangGraph + PostgreSQL checkpointer, `httpx`, RAGFlow, pytest/pytest-asyncio, Ruff, MyPy.

**Spec:** `docs/superpowers/specs/2026-09-12-v1-completion-design.md`

**Architecture lock:** `docs/adr/0004-v1-architecture-lock.md`

**Business constraints:** `docs/business/v1-scope.md`, `docs/business/forbidden-claims.md`

**Previous workstream contract:** `docs/superpowers/plans/2026-09-16-ws3-worker-execution-completed.md`

## Global Constraints

- WS4 starts from `ba1f9b3` on branch `feat/ws4-real-structured-llm-qa` in `/home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws4-real-structured-llm-qa`.
- WS3 is frozen. Do not change WS3 Run status semantics, Worker claim/lease/retry semantics, resume semantics, checkpoint identity, or handler side-effect rules.
- Keep the existing `StructuredLLMPort` and `StructuredLLMUsagePort`; do not introduce a second LLM abstraction.
- Keep the existing QA Graph and extend it narrowly; do not replace it with a new unified LangGraph or multi-agent architecture.
- Maximum knowledge retrieval rounds per QA Run is exactly **2**.
- A second retrieval may refine the query, but it must preserve the same authorized `ProjectAccessScope`, project, knowledge-space set, and allowed document-version constraints.
- Retrieval grade cannot override authority/current/effective filtering. Evidence governance remains authoritative after retrieval.
- Every actual graph retrieval increments `agent_runs.retrieval_rounds` exactly once on the normal execution path. Non-retrieval modes remain at `0`.
- Inadequate evidence after the bounded second round produces refusal, not unsupported generation.
- Existing Citation Guard and one-revision maximum remain unchanged.
- Provider/network/schema failures must be controlled and sanitized; API keys and raw Authorization headers must never enter logs, events, or exception strings.
- Use the existing `httpx` dependency. Do not add an OpenAI SDK unless this plan is explicitly revised and re-approved.
- No Redis, Celery, MinIO, second vector DB, production Jira/ZenTao/Feishu integration, Kubernetes, new multi-agent architecture, or WS5+ business implementation.
- No Alembic migration is planned for WS4. Existing `agent_runs` already contains model/prompt/token/retrieval telemetry fields, and QA artifacts can use existing event/evidence/answer/citation persistence.
- Unit/contract tests use fakes by default. PostgreSQL, RAGFlow, and real LLM tests remain explicit opt-in live gates.
- Server live evidence is authoritative. Sandbox success is never reported as a live pass.
- Every **Big Task** follows RED → confirm correct failure → minimal implementation → GREEN → targeted regression → Ruff → MyPy → `git diff --check` → required live gate → Big Task review/delivery. Each internal Phase preserves its own RED/GREEN checkpoint and may use a checkpoint commit.
- Every Big Task completion report must include:

```text
需求完成：✅ / ❌ / ⏳
测试闭环：✅ / ❌ / ⚠️
新 bug：未发现 / 已发现：写出具体问题和受影响文件
```

---

## Plan Review Gate — Decisions This Plan Proposes to Freeze

The source-of-truth defines the required behavior but leaves two implementation details underspecified/inconsistent in the current snapshot. Approval of this plan approves the following narrow decisions. If either decision is rejected, revise the plan before Big Task 1; do not improvise during coding.

### Decision A — Structured LLM wire protocol

The approved design requires a real settings-driven HTTP adapter but does not name the provider protocol. This plan proposes one concrete V1 wire contract:

- OpenAI-compatible Chat Completions endpoint relative to `llm_base_url`: `chat/completions`;
- Bearer API-key authentication;
- model = `StructuredLLMRequest.model_alias`;
- `temperature` forwarded from the existing request;
- strict structured output requested with `response_format.type = "json_schema"` and `response_model.model_json_schema()`;
- response content parsed only from `choices[0].message.content` as JSON;
- usage read from `usage.prompt_tokens` and `usage.completion_tokens`;
- malformed/missing content, malformed JSON, invalid Pydantic output, or malformed usage fields are controlled provider/schema failures, never a valid business result.

This decision creates a concrete adapter, not a new application abstraction. If the real server provider is not OpenAI-compatible, Big Task 1 / Phase 1A must be revised before implementation.

### Decision B — Canonical RAGFlow project scope

The QA/access-policy/RAGFlow baseline already uses `project_code` (for example `PRJ-RETAIL-ALPHA`) as the provider-facing project scope. The current document publish/delete use cases instead send `str(project_id)` UUIDs to RAGFlow. This would make app-published documents invisible to QA metadata filtering and is inconsistent with the adapter's project isolation model.

This plan proposes:

1. `project_code` remains the canonical provider-facing RAGFlow project key.
2. `DocumentWorkflowRepository` gains a narrow `project_code(project_id: UUID) -> str` lookup using the existing `projects.code` data; no schema change.
3. Publish/delete use that canonical code in `KnowledgeIngestionRequest` / `DeleteKnowledgeDocumentRequest`.
4. RAGFlow `ingest` and `delete_document` may establish the local in-memory dataset binding from the trusted application request via the existing collision-checking `_bind_space`; they still reject a dataset already bound to another project.
5. Worker QA composition explicitly seeds `project_code -> active knowledge_space_id` bindings from the DB-authorized `AuthorizedProjectContext` before retrieval. Direct retrieval does not silently broaden access.

This is a targeted WS4 integration repair required for the WS4 live path; it is not a redesign of Big Task 2 / Phase 2C or the architecture lock.

---

## Source Recon and File Responsibility Map

### Existing production contracts retained

| Area | Existing contract | WS4 treatment |
| --- | --- | --- |
| Structured LLM | `StructuredLLMPort.generate()` + `StructuredLLMUsagePort.get_usage()` | Keep; add concrete HTTP adapter only |
| QA graph state | checkpoint-safe `AgentState` references + small route controls | Add only retrieval-grade/round references |
| Retrieval authorization | `ProjectAccessPolicy.constrain_retrieval()` + `postfilter_evidence()` | Keep unchanged as security boundary |
| Evidence governance | `EvidenceGovernanceService` | Keep unchanged; grade cannot bypass it |
| Citations | `CitationGuard` + grounded answer/citation persistence | Keep unchanged |
| QA persistence | `QAGraphStorePort` / `SqlAlchemyQAGraphStore` | Reuse existing artifacts/telemetry |
| RAGFlow | `RagflowAdapter`, HTTP retry client, project metadata filtering | Reuse; repair canonical project binding |
| Run execution | `RunGraphExecutor`, `LangGraphRunExecutor`, WS3 handlers | Keep semantics; provide QA graph composition at factory seam |
| Checkpointer | `async_postgres_saver` with `thread_id` | Keep unchanged |
| DB schema | Alembic `0005_run_runtime_envelope` | No WS4 migration expected |

### Current implementation already present

- QA graph from prompt load → query analysis → project selection → scope → exact identifier resolution → retrieval → evidence governance → answer → Citation Guard → at most one answer revision/refusal.
- Existing exact-identifier and `ProjectAccessScope` constraints.
- Existing raw and governed Evidence persistence.
- Existing grounded answer and citation persistence.
- Existing per-Run `model_alias`, prompt version/hash, input/output/total token counters, and `retrieval_rounds`.
- Existing real RAGFlow HTTP client/adapter with bounded retry and defensive post-mapping.
- Existing WS3 durable Worker execute/resume/checkpointer lifecycle.

### Missing or test-only pieces

- No real implementation of `StructuredLLMPort`; only `tests/fakes/llm.py` is used by QA tests.
- No retrieval grade schema/node.
- No second retrieval route; `RetrievalPlan.allow_second_round` exists but is always initialized `False`.
- Current retrieval routes directly to evidence governance when any chunk exists and refuses immediately when none exist.
- No production QA graph/executor composition for the Worker; `build_worker_runtime()` requires an injected `graph_executor_factory`.
- RAGFlow dataset bindings are process-local, while API publish and Worker retrieval create separate adapters.
- Publish/delete currently send UUID project identity while QA retrieval uses project code.
- No real Structured LLM live gate and no combined production QA Worker live gate.

### Primary WS4 modification surface

```text
src/project_agent/config.py
.env.example
src/project_agent/infrastructure/llm/__init__.py                 # new
src/project_agent/infrastructure/llm/errors.py                   # new
src/project_agent/infrastructure/llm/adapter.py                  # new
src/project_agent/agent/state.py
src/project_agent/agent/nodes/models.py
src/project_agent/agent/nodes/grade_retrieval.py                 # new
src/project_agent/agent/nodes/retrieve.py
src/project_agent/agent/nodes/identifier_node.py
src/project_agent/agent/graph.py
src/project_agent/application/ports/document_repository.py
src/project_agent/infrastructure/db/repositories/documents.py
tests/fakes/document_repository.py
src/project_agent/application/use_cases/publish_document.py
src/project_agent/application/use_cases/delete_document.py
src/project_agent/infrastructure/ragflow/adapter.py
src/project_agent/runtime/qa.py                                  # new
src/project_agent/runtime/worker.py
src/project_agent/runtime/__init__.py
```

### Existing tests to preserve/reuse

```text
tests/contract/test_llm_port.py
tests/contract/ragflow/test_http_client.py
tests/contract/ragflow/test_ingestion.py
tests/contract/ragflow/test_retrieval_mapping.py
tests/unit/agent/test_retrieve_and_answer.py
tests/unit/agent/test_answer_revision.py
tests/security/test_evidence_postfilter.py
tests/security/test_cross_project_citation.py
tests/e2e/test_project_qa.py
tests/unit/runtime/test_worker_runtime.py
tests/unit/workers/test_run_graph.py
tests/integration/evidence/test_citation_persistence.py
tests/integration/ragflow/test_project_isolation.py
tests/integration/workers/test_run_worker_postgres.py
tests/integration/workers/test_run_resume_postgres.py
```

---

### Big Task 1: Real Structured LLM + Bounded QA Retrieval Core

**Big Task Goal:** Complete all provider-facing Structured LLM behavior and the bounded retrieval decision loop while keeping the existing QA graph, authorization, evidence governance, and Citation Guard contracts intact.

**Internal execution order:** Phase 1A → Phase 1B → Phase 1C. Do not externally review/deliver between phases unless a RED test exposes a source-of-truth or architecture ambiguity; do run the phase-level RED/GREEN and static gates before moving forward.

#### Phase 1A: Real Structured LLM HTTP Adapter and Failure Contract

**Goal:** Implement the real adapter behind the already-frozen Structured LLM ports, with strict schema validation, bounded retry, sanitized failures, and token usage capture.

**Files:**
- Create: `src/project_agent/infrastructure/llm/__init__.py`
- Create: `src/project_agent/infrastructure/llm/errors.py`
- Create: `src/project_agent/infrastructure/llm/adapter.py`
- Modify: `src/project_agent/config.py:14-52`
- Modify: `.env.example`
- Modify: `tests/unit/test_config.py`
- Create: `tests/contract/llm/test_http_adapter.py`
- Preserve: `src/project_agent/application/ports/llm.py` unless a typing-only import adjustment is necessary; do not change its public method signatures.

**Interfaces:**
- Consumes: `StructuredLLMRequest`, `StructuredLLMPort`, `StructuredLLMUsagePort`, `LLMTokenUsage`.
- Produces:

```text
StructuredLLMRetryPolicy(max_attempts: int = 3)
OpenAICompatibleStructuredLLMAdapter.generate(
    request: StructuredLLMRequest,
    response_model: type[TStructured],
) -> TStructured
OpenAICompatibleStructuredLLMAdapter.get_usage(request_id: str) -> LLMTokenUsage
```

- Produces controlled exceptions:

```python
class StructuredLLMError(RuntimeError):
    pass

class StructuredLLMTransportError(StructuredLLMError):
    pass

class StructuredLLMHTTPError(StructuredLLMError):
    pass

class StructuredLLMProtocolError(StructuredLLMError):
    pass

class StructuredLLMSchemaError(StructuredLLMError):
    pass
```

- New settings:

```python
llm_request_timeout_seconds: float = 30.0
llm_max_attempts: int = 3
```

The existing `llm_base_url`, `llm_api_key`, `llm_model_alias`, request/token capacity, and rate-window settings remain unchanged.

- [ ] **Step 1: RED — add adapter contract tests before implementation**

Create `tests/contract/llm/test_http_adapter.py` using `httpx.MockTransport`. Cover all of these cases explicitly:

```python
class RouteDecision(BaseModel):
    route: Literal["knowledge", "issue"]

@pytest.mark.asyncio
async def test_structured_http_adapter_validates_json_schema_and_records_usage() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"route":"knowledge"}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        )

    async with httpx.AsyncClient(
        base_url="https://llm.example.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(
            http,
            api_key="secret-test-key",
            retry_policy=StructuredLLMRetryPolicy(max_attempts=1),
        )
        request = StructuredLLMRequest(
            request_id="llm-1",
            model_alias="test-model",
            system_prompt="Return one valid route.",
            user_prompt="How do I deploy?",
            temperature=0.0,
        )
        result = await adapter.generate(request, RouteDecision)

    assert result == RouteDecision(route="knowledge")
    assert await adapter.get_usage("llm-1") == LLMTokenUsage(11, 3)
    outbound = captured[0]
    body = json.loads(outbound.content)
    assert body["model"] == "test-model"
    assert body["temperature"] == 0.0
    assert body["response_format"]["type"] == "json_schema"
    assert outbound.headers["Authorization"] == "Bearer secret-test-key"
```

Also add separate RED tests proving:

- malformed JSON raises `StructuredLLMSchemaError`;
- Pydantic-invalid JSON raises `StructuredLLMSchemaError`;
- missing `choices[0].message.content` raises `StructuredLLMProtocolError`;
- missing/non-integer/negative usage fields raises `StructuredLLMProtocolError`;
- HTTP 400 is not retried and raises sanitized `StructuredLLMHTTPError`;
- HTTP 429 is retried up to `max_attempts` then raises sanitized `StructuredLLMHTTPError`;
- HTTP 500 is retried up to `max_attempts`;
- `httpx.TimeoutException` / transport failure is retried up to `max_attempts` then raises `StructuredLLMTransportError`;
- error strings do not contain the configured API key or raw Authorization header;
- `get_usage("unknown")` raises `LookupError`.

Use a retry policy with no test sleep or monkeypatch the sleep function so contract tests remain deterministic.

- [ ] **Step 2: Run RED and verify the failure is the missing production adapter**

```bash
export PYTHONPATH="$PWD/src"
python -m pytest -q tests/contract/llm/test_http_adapter.py
```

Expected RED: import/module/class failures for the new `infrastructure.llm` adapter/errors, not failures in unrelated existing code.

- [ ] **Step 3: Implement the minimal error types and retry policy**

`errors.py` contains only the five sanitized exception classes above. `adapter.py` defines the retry policy and validates `max_attempts >= 1`.

Retry only:

```text
httpx.TimeoutException
httpx.TransportError
HTTP 429
HTTP 5xx
```

Do not retry ordinary 4xx, protocol-shape failures, malformed JSON, or Pydantic schema failures.

Do not include response bodies, API keys, or outbound headers in exception text.

- [ ] **Step 4: Implement the minimal OpenAI-compatible request/response mapping**

Generate a request body equivalent to:

```python
payload = {
    "model": request.model_alias,
    "temperature": request.temperature,
    "messages": [
        {"role": "system", "content": request.system_prompt},
        {"role": "user", "content": request.user_prompt},
    ],
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": response_model.__name__,
            "strict": True,
            "schema": response_model.model_json_schema(),
        },
    },
}
```

POST to relative path `chat/completions` so a configured base URL ending in `/v1/` is preserved.

Parse only:

```text
choices[0].message.content -> response_model.model_validate_json(content)
usage.prompt_tokens        -> input_tokens
usage.completion_tokens    -> output_tokens
```

Store usage by `request.request_id` only after a structurally valid provider response is received. Never coerce malformed structured content into a business object.

- [ ] **Step 5: Add settings and `.env.example` defaults**

Add:

```text
LLM_REQUEST_TIMEOUT_SECONDS=30
LLM_MAX_ATTEMPTS=3
```

Extend `tests/unit/test_config.py` to assert configured overrides are parsed and defaults are stable. Do not add a provider enum or new provider abstraction in WS4.

- [ ] **Step 6: GREEN — run adapter + existing LLM contracts**

```bash
python -m pytest -q \
  tests/contract/test_llm_port.py \
  tests/contract/llm/test_http_adapter.py \
  tests/unit/test_config.py
```

Acceptance: all pass; malformed output remains a failure; usage values are exact.

- [ ] **Step 7: Targeted regression + static gate**

```bash
python -m pytest -q tests/unit/agent/test_retrieve_and_answer.py tests/e2e/test_project_qa.py
ruff check src tests
mypy src
git diff --check
```

Do not run/claim the live provider gate yet; Big Task 3 owns the live provider acceptance.

- [ ] **Step 8: Checkpoint commit — Phase 1A**

```bash
git add \
  src/project_agent/infrastructure/llm \
  src/project_agent/config.py \
  .env.example \
  tests/contract/llm/test_http_adapter.py \
  tests/unit/test_config.py
git commit -m "feat(llm): add real structured http adapter"
```

**Completion criteria:** Real adapter satisfies the existing ports; schema/usage/retry/failure contracts are covered offline; no QA graph behavior has changed; live acceptance remains `⏳`.

---

#### Phase 1B: Structured Retrieval Grade Schema and Node

**Goal:** Introduce an explicit bounded retrieval-grade artifact that can only judge evidence sufficiency/relevance/coverage and can only propose a refined query, never authorization or authority decisions.

**Files:**
- Modify: `src/project_agent/agent/state.py:6-36`
- Modify: `src/project_agent/agent/nodes/models.py:12-30`
- Create: `src/project_agent/agent/nodes/grade_retrieval.py`
- Modify: `tests/fakes/qa_graph_store.py` only if needed for the new artifact path; retain the same port behavior.
- Create: `tests/unit/agent/test_retrieval_grade.py`

**Interfaces:**

Add state references/controls:

```python
retrieval_grade_id: str | None
retrieval_round: int
```

Add the exact grade schema:

```python
class RetrievalGradeReason(StrEnum):
    ADEQUATE = "ADEQUATE"
    EMPTY_EVIDENCE = "EMPTY_EVIDENCE"
    INSUFFICIENT_RELEVANCE = "INSUFFICIENT_RELEVANCE"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"

class RetrievalGrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    adequate: bool
    reason: RetrievalGradeReason
    second_round_justified: bool = False
    refined_query: str | None = None
```

Validation invariants:

```text
adequate=True  => reason=ADEQUATE, second_round_justified=False, refined_query=None
adequate=False + second_round_justified=True => refined_query is non-empty
adequate=False + second_round_justified=False => refined_query=None
```

The model deliberately contains no project ID, knowledge-space ID, document IDs, authority level, lifecycle status, or security fields.

New node signature:

```text
grade_retrieval_node(
    state: AgentState,
    *,
    llm: StructuredLLMPort,
    llm_usage: StructuredLLMUsagePort,
    store: QAGraphStorePort,
    model_alias: str,
) -> AgentState
```

- [ ] **Step 1: RED — grade schema invariants**

Create tests proving valid and invalid combinations. Example:

```python
def test_inadequate_grade_requires_refined_query_when_second_round_is_justified() -> None:
    with pytest.raises(ValidationError):
        RetrievalGrade(
            adequate=False,
            reason=RetrievalGradeReason.INSUFFICIENT_COVERAGE,
            second_round_justified=True,
            refined_query=None,
        )
```

Also prove an adequate grade cannot ask for round 2.

- [ ] **Step 2: RED — grade node uses only post-filtered evidence and existing LLM port**

Build state with a persisted `RetrievalPlan` and persisted raw Evidence bundle. Queue a `RetrievalGrade` response in `FakeStructuredLLM` and assert:

```text
request_id = f"{run_id}:qa-retrieval-grade:{retrieval_round}"
response_model = RetrievalGrade
usage is added through store.record_llm_usage
artifact_type = RETRIEVAL_GRADE
```

Inspect the generated prompt and assert it contains query + only the chunks in the persisted post-filtered bundle. It must not contain instructions permitting project/space/document expansion.

- [ ] **Step 3: RED — second-round plan preserves all frozen constraints**

For an inadequate-but-justified first-round grade, assert the node writes a new `RetrievalPlan` where exactly one semantic field changes:

```python
assert second.original_query == first.original_query
assert second.standalone_query == grade.refined_query
assert second.exact_identifiers == first.exact_identifiers
assert second.identifier_resolutions == first.identifier_resolutions
assert second.constrained_document_version_ids == first.constrained_document_version_ids
assert second.constrained_provider_document_ids == first.constrained_provider_document_ids
assert second.allowed_categories == first.allowed_categories
assert second.allow_second_round is first.allow_second_round
```

- [ ] **Step 4: Run RED**

```bash
python -m pytest -q tests/unit/agent/test_retrieval_grade.py
```

Expected RED: missing `RetrievalGrade`/node/state fields, not unrelated failures.

- [ ] **Step 5: Implement the schema and minimal grading prompt**

The grading prompt must say, in substance:

```text
Judge only whether the supplied, already-authorized retrieved chunks are sufficiently relevant
and sufficiently complete to attempt evidence governance/answering the user's query.
Do not decide authority, current/effective version, project membership, knowledge-space access,
or citation validity. Those are enforced elsewhere.
If one bounded second retrieval is justified, return only a refined standalone query.
Never return or request a new project, knowledge space, document ID, or security scope.
```

No model-created filters are accepted because the response schema has no such fields.

- [ ] **Step 6: Implement usage/artifact persistence and route output**

After `llm.generate(request, RetrievalGrade)` succeeds:

```python
usage = await llm_usage.get_usage(request_id)
await store.record_llm_usage(
    run_id=run_id,
    input_tokens=usage.input_tokens,
    output_tokens=usage.output_tokens,
)
grade_id = await store.save_artifact(
    run_id=run_id,
    artifact_type="RETRIEVAL_GRADE",
    payload=grade.model_dump(mode="json"),
)
```

Return route controls:

```text
adequate                           -> route="govern_evidence"
inadequate + justified + round < 2 -> route="retrieve_again" and new retrieval_plan_id
otherwise                          -> route="refusal", last_error_code="INSUFFICIENT_EVIDENCE"
```

Phase 1C will wire these routes into LangGraph and enforce the hard retrieval ceiling defensively.

- [ ] **Step 7: GREEN + regression**

```bash
python -m pytest -q \
  tests/unit/agent/test_retrieval_grade.py \
  tests/unit/agent/test_retrieve_and_answer.py \
  tests/security/test_evidence_postfilter.py
ruff check src tests
mypy src
git diff --check
```

- [ ] **Step 8: Checkpoint commit — Phase 1B**

```bash
git add \
  src/project_agent/agent/state.py \
  src/project_agent/agent/nodes/models.py \
  src/project_agent/agent/nodes/grade_retrieval.py \
  tests/unit/agent/test_retrieval_grade.py \
  tests/fakes/qa_graph_store.py
git commit -m "feat(qa): add structured retrieval grade"
```

**Completion criteria:** Grade output is structurally incapable of widening access; usage is accumulated through the existing path; no graph loop exists yet outside the isolated node tests.

---

#### Phase 1C: Wire One-Round Success and Hard Max-Two Retrieval into the Existing QA Graph

**Goal:** Extend the current QA graph narrowly so every authorized provider retrieval is graded, at most one justified refinement can trigger a second retrieval, and inadequate second-round evidence refuses.

**Files:**
- Modify: `src/project_agent/agent/nodes/identifier_node.py:13-46`
- Modify: `src/project_agent/agent/nodes/retrieve.py:13-51`
- Modify: `src/project_agent/agent/graph.py:25-228`
- Modify: `tests/unit/agent/test_retrieve_and_answer.py`
- Modify: `tests/e2e/test_project_qa.py`
- Modify: `tests/security/test_evidence_postfilter.py`
- Preserve: `src/project_agent/agent/nodes/govern_evidence.py`, `generate_answer.py`, `citation_guard.py`, `revise_answer.py` unless a route-name import adjustment is required.

**Interfaces:**
- Existing `RetrievalPlan.allow_second_round` becomes active and is initialized `True` for QA retrieval plans.
- `retrieve_node()` returns `retrieval_round` only when `knowledge.retrieve()` is actually invoked.
- New graph route:

```text
resolve_identifiers
  -> retrieve
  -> grade_retrieval
       -> govern_evidence
       -> retrieve      # once only, refined query
       -> refuse
```

- [ ] **Step 1: RED — one-round adequate path**

Update/add E2E test:

```text
round 1 returns authorized chunks
retrieval grade = ADEQUATE
answer generation returns grounded draft
Citation Guard accepts
```

Assert:

```text
knowledge.retrieve calls = 1
persisted retrieval_rounds = 1
grade LLM calls = 1
answer LLM calls = 1 (plus at most one existing citation revision if intentionally exercised)
terminal route = answered
answer + citations persist
```

- [ ] **Step 2: RED — justified second round stays in identical authorization scope**

First retrieval returns weak/empty authorized evidence. Queue grade:

```python
RetrievalGrade(
    adequate=False,
    reason=RetrievalGradeReason.INSUFFICIENT_COVERAGE,
    second_round_justified=True,
    refined_query="deployment rollback procedure exact service identifier",
)
```

Second retrieval returns adequate authorized evidence. Assert exactly two `KnowledgeRetrievalRequest`s and:

```python
assert second.project_id == first.project_id
assert second.document_version_ids == first.document_version_ids
assert second.knowledge_space_ids == first.knowledge_space_ids
assert second.query != first.query
```

Persisted `retrieval_rounds == 2`.

- [ ] **Step 3: RED — second-round inadequate path refuses without answer generation**

Queue two inadequate grades, where the second cannot request a third round. Assert:

```text
knowledge.retrieve calls = 2
retrieval_rounds = 2
terminal route = refusal
last_error_code = INSUFFICIENT_EVIDENCE
no GroundedAnswerDraft generation call occurs
```

- [ ] **Step 4: RED — no authorized retrieval remains zero-call/zero-round**

Preserve the security behavior where `ProjectAccessPolicy.constrain_retrieval()` returns `None` because no authorized document versions or spaces exist. Assert:

```text
knowledge.retrieve calls = 0
retrieval_rounds = 0
retrieval-grade LLM calls = 0
answer LLM calls = 0
terminal refusal
```

This test is distinct from “authorized provider retrieval returned no chunks,” which is allowed to invoke the retrieval grader and possibly one refined retry.

- [ ] **Step 5: RED — cross-project/wrong-space chunks remain filtered on both rounds**

Extend `tests/security/test_evidence_postfilter.py` so a fake provider injects cross-project, wrong-version, and wrong-space chunks in both calls. Assert those chunks never appear in a persisted Evidence bundle passed to the grader/governance and never appear in citations.

- [ ] **Step 6: Run RED**

```bash
python -m pytest -q \
  tests/unit/agent/test_retrieve_and_answer.py \
  tests/e2e/test_project_qa.py \
  tests/security/test_evidence_postfilter.py
```

Expected RED: missing grade route/second-round behavior or changed current one-round routing.

- [ ] **Step 7: Implement hard-round accounting in `retrieve_node()`**

Required control flow:

```python
current_round = int(state.get("retrieval_round", 0))
if current_round >= 2:
    return {"route": "refusal", "last_error_code": "RETRIEVAL_ROUND_LIMIT"}

constrained = access_policy.constrain_retrieval(request, context)
if constrained is None:
    # no provider request, no round increment
    persist empty bundle
    return {"route": "refusal", "last_error_code": "NO_AUTHORIZED_EVIDENCE"}

await store.increment_retrieval_rounds(run_id=run_id)
chunks = access_policy.postfilter_evidence(await knowledge.retrieve(constrained), context)
# persist post-filtered bundle
return {
    "evidence_bundle_id": str(bundle_id),
    "retrieval_round": current_round + 1,
    "route": "grade_retrieval",
    "last_error_code": None,
}
```

Do not increment on policy-denied/no-scope paths. Do not add an unbounded graph edge.

- [ ] **Step 8: Activate `allow_second_round=True` at plan construction**

`resolve_identifiers_node()` keeps the exact identifiers and constrained IDs it already produces, changing only:

```python
allow_second_round=True
```

This flag authorizes one refinement attempt inside the same frozen plan constraints; it does not grant any new project/document access.

- [ ] **Step 9: Wire the node and conditional edges in `build_project_qa_graph()`**

Add `grade_retrieval` closure using the same `deps.llm`, `deps.llm_usage`, `deps.store`, and `deps.model_alias` as answer generation.

Graph edges must make a third retrieval structurally unreachable:

```text
retrieve -> grade_retrieval | refuse
grade_retrieval -> govern_evidence | retrieve | refuse
```

The second grade must route only to governance/refusal because `retrieval_round == 2`.

- [ ] **Step 10: GREEN + frozen Citation Guard regression**

```bash
python -m pytest -q \
  tests/unit/agent/test_retrieval_grade.py \
  tests/unit/agent/test_retrieve_and_answer.py \
  tests/unit/agent/test_answer_revision.py \
  tests/e2e/test_project_qa.py \
  tests/security/test_evidence_postfilter.py \
  tests/security/test_cross_project_citation.py
ruff check src tests
mypy src
git diff --check
```

- [ ] **Step 11: Checkpoint commit — Phase 1C and close Big Task 1**

```bash
git add \
  src/project_agent/agent/nodes/identifier_node.py \
  src/project_agent/agent/nodes/retrieve.py \
  src/project_agent/agent/graph.py \
  tests/unit/agent/test_retrieve_and_answer.py \
  tests/e2e/test_project_qa.py \
  tests/security/test_evidence_postfilter.py
git commit -m "feat(qa): bound retrieval to two rounds"
```

**Completion criteria:** one-round success, exact two-round success, exact two-round refusal, zero-call no-scope path, and cross-project filtering are all proven offline; Citation Guard semantics remain unchanged.


**Big Task 1 acceptance gate:**

- real HTTP adapter satisfies the frozen Structured LLM ports offline;
- retrieval grade is structured and cannot broaden authorization;
- one-round success, exactly-two-round success, and exactly-two-round refusal are proven;
- no path can execute a third knowledge retrieval;
- Citation Guard/evidence governance remain unchanged;
- targeted regression + Ruff + MyPy + `git diff --check` are fresh;
- real provider acceptance remains explicitly `⏳` until Big Task 3.

---

### Big Task 2: Canonical RAGFlow Scope + Production QA Runtime Wiring

**Big Task Goal:** Make the real RAGFlow boundary and the frozen WS3 Worker runtime compose into one production QA execution path, without changing WS3 lifecycle/checkpoint semantics or weakening project isolation.

**Internal execution order:** Phase 2A → Phase 2B → Phase 2C. Phase 2A fixes the provider-facing identity boundary first; Phase 2B composes per-Run QA dependencies; Phase 2C plugs the executor into the existing Worker factory seam.

#### Phase 2A: Repair Canonical RAGFlow Project Scope and Dataset Binding

**Goal:** Make document ingestion/deletion and QA retrieval use the same canonical provider project identity and make separate API/Worker RAGFlow adapter lifetimes usable without weakening project isolation.

**Why this Task is required:** In the current snapshot, `PublishDocumentUseCase`/`DeleteDocumentUseCase` send `str(project_id)` UUID while QA retrieval sends `AuthorizedProjectContext.project_code`. RAGFlow metadata filtering and document mappings compare these strings exactly. A document published by the current API can therefore be excluded from the current QA retrieval path even when it belongs to the same DB project.

**Files:**
- Modify: `src/project_agent/application/ports/document_repository.py:12-84`
- Modify: `src/project_agent/infrastructure/db/repositories/documents.py`
- Modify: `tests/fakes/document_repository.py`
- Modify: `src/project_agent/application/use_cases/publish_document.py:24-142`
- Modify: `src/project_agent/application/use_cases/delete_document.py:20-64`
- Modify: `src/project_agent/infrastructure/ragflow/adapter.py:44-420`
- Modify: `tests/e2e/test_document_lifecycle.py`
- Modify: `tests/contract/ragflow/test_ingestion.py`
- Modify: `tests/contract/ragflow/test_retrieval_mapping.py`
- Modify: `tests/integration/ragflow/test_project_isolation.py`

**Interfaces:**

Extend existing document repository protocol:

```text
DocumentWorkflowRepository.project_code(project_id: UUID) -> str
```

The SQL implementation loads the existing `ProjectModel.code`; the fake adds an explicit project-id→project-code binding helper for tests. No migration.

Expose an adapter method for Worker composition:

```python
def bind_authorized_space(self, *, project_id: str, dataset_id: str) -> None:
    self._bind_space(project_id, dataset_id)
```

It is deliberately synchronous/local and delegates to existing collision detection. It performs no provider-side dataset creation.

- [ ] **Step 1: RED — document publish uses project code, not UUID**

Extend `tests/e2e/test_document_lifecycle.py` so the fake repository binds:

```text
project UUID -> PRJ-RETAIL-ALPHA
project UUID -> ks-alpha
```

After publish, assert the captured `KnowledgeIngestionRequest` contains:

```python
assert request.project_id == "PRJ-RETAIL-ALPHA"
assert request.project_id != str(project_uuid)
assert request.knowledge_space_id == "ks-alpha"
```

Add the analogous delete assertion for `DeleteKnowledgeDocumentRequest`.

- [ ] **Step 2: RED — fresh adapter can safely establish a trusted ingestion/deletion binding**

In the RAGFlow contract tests, construct a fresh adapter and call ingest with `project_id="PRJ-RETAIL-ALPHA"`, `knowledge_space_id="dataset-a"` without a preceding `ensure_space()` call. Assert ingestion succeeds and the adapter records only that binding.

Then attempt to reuse `dataset-a` for `PRJ-LOGISTICS-BETA`; assert `RagflowProjectIsolationError`.

Apply the same collision behavior to delete.

- [ ] **Step 3: RED — Worker-side authorized binding preserves retrieval isolation**

Test `bind_authorized_space(project_id="PRJ-RETAIL-ALPHA", dataset_id="dataset-a")` then retrieve with that exact project/dataset. Assert allowed. Bind collision from another project and assert rejected.

Do not add “auto-bind arbitrary retrieval request” behavior.

- [ ] **Step 4: Run RED**

```bash
python -m pytest -q \
  tests/e2e/test_document_lifecycle.py \
  tests/contract/ragflow/test_ingestion.py \
  tests/contract/ragflow/test_retrieval_mapping.py
```

- [ ] **Step 5: Implement repository project-code lookup**

`SqlAlchemyDocumentWorkflowRepository.project_code()` queries `ProjectModel.code` for the exact UUID and raises `LookupError` if absent. The in-memory fake requires explicit binding; tests must not invent project codes implicitly from UUIDs.

- [ ] **Step 6: Change publish/delete provider requests to canonical code**

Use:

```python
project_code = await self._repository.project_code(current.project_id)
knowledge_space_id = await self._repository.knowledge_space_id(current.project_id)
```

Then pass `project_code` to RAGFlow requests. All DB audit records continue using UUID `project_id`; only the external provider scope changes.

- [ ] **Step 7: Implement safe local binding behavior in `RagflowAdapter`**

- `bind_authorized_space()` calls `_bind_space()`.
- `ingest()` establishes the first local binding by calling `_bind_space(request.project_id, request.knowledge_space_id)` instead of requiring a pre-existing process-local binding.
- `delete_document()` does the same.
- `_bind_space()` continues to reject any conflicting existing dataset→project binding.
- Retrieval with explicit dataset IDs still calls `_assert_space_for_project()`; production Worker composition must seed only DB-authorized spaces before retrieval.
- Metadata stamping/filtering remains `project_code` + `document_version_id`.

- [ ] **Step 8: GREEN + RAGFlow security regression**

```bash
python -m pytest -q \
  tests/e2e/test_document_lifecycle.py \
  tests/contract/ragflow/test_baseline.py \
  tests/contract/ragflow/test_dataset_admin.py \
  tests/contract/ragflow/test_http_client.py \
  tests/contract/ragflow/test_ingestion.py \
  tests/contract/ragflow/test_retrieval_mapping.py \
  tests/security/test_evidence_postfilter.py
ruff check src tests
mypy src
git diff --check
```

- [ ] **Step 9: Server live RAGFlow gate**

On the real WS4 server only:

```bash
export RUN_RAGFLOW_INTEGRATION=1
# retain the server's configured RAGFLOW_* variables/credentials
python -m pytest -q -rs tests/integration/ragflow/test_project_isolation.py
```

Acceptance: the two-project seeded corpus proves no cross-project Evidence and uses the same canonical project-code metadata as the application path. If the real RAGFlow environment is unavailable, mark `live acceptance ⏳`; do not replace this with a fake.

- [ ] **Step 10: Checkpoint commit — Phase 2A**

```bash
git add \
  src/project_agent/application/ports/document_repository.py \
  src/project_agent/infrastructure/db/repositories/documents.py \
  tests/fakes/document_repository.py \
  src/project_agent/application/use_cases/publish_document.py \
  src/project_agent/application/use_cases/delete_document.py \
  src/project_agent/infrastructure/ragflow/adapter.py \
  tests/e2e/test_document_lifecycle.py \
  tests/contract/ragflow/test_ingestion.py \
  tests/contract/ragflow/test_retrieval_mapping.py \
  tests/integration/ragflow/test_project_isolation.py
git commit -m "fix(ragflow): align project scope bindings"
```

**Completion criteria:** ingestion, deletion, and QA retrieval share `project_code`; a fresh adapter can use a DB-authorized dataset mapping; cross-project dataset rebinding still fails; live RAGFlow isolation is either freshly PASS or explicitly `⏳`.

---

#### Phase 2B: Production QA Graph Factory with Per-Run Database Session

**Goal:** Build the real QA dependency graph for a durable Run without sharing a mutable SQLAlchemy `AsyncSession` across concurrent Worker jobs.

**Files:**
- Create: `src/project_agent/runtime/qa.py`
- Modify: `src/project_agent/runtime/__init__.py`
- Create: `tests/unit/runtime/test_qa_runtime.py`
- Create: `tests/integration/agent/test_qa_runtime_postgres.py`
- Modify: `src/project_agent/infrastructure/db/repositories/qa_graph.py` only if a minimal explicit commit hook is required by the selected production session boundary; do not change persistence schema.

**Interfaces:**

Create a production QA executor/factory with the frozen Worker-facing interface:

```text
ProductionQARunExecutor.execute(run: RunRecord) -> RunGraphOutcome
ProductionQARunExecutor.resume(
    run: RunRecord,
    resume_payload: dict[str, object],
) -> RunGraphOutcome
```

`execute()` supports `RunBusinessMode.QA` only. `resume()` for QA must reject because WS4 QA has no interrupt/resume business state; WS3 resume behavior for Issue is not redefined here.

Provide a factory that receives long-lived external adapters plus the PostgreSQL checkpointer, but opens a **fresh application DB session per execute call**:

```text
build_production_qa_executor(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    saver: object,
    knowledge: RagflowAdapter,
    llm: StructuredLLMPort,
    llm_usage: StructuredLLMUsagePort,
) -> RunGraphExecutor
```

- [ ] **Step 1: RED — graph composition uses the existing concrete services/repositories**

In `tests/unit/runtime/test_qa_runtime.py`, monkeypatch builders/repositories and assert one QA execution creates dependencies equivalent to:

```text
AuthorizationService(SqlAlchemyProjectAuthorizationRepository(session))
extractor = IdentifierExtractor()
QueryAnalysisService(extractor)
registry = IdentifierRegistryService(SqlAlchemyIdentifierRegistryRepository(session), extractor)
ExactIdentifierResolver(registry)
ProjectAccessPolicy()
PromptConfigService(
    SqlAlchemyPromptConfigRepository(session),
    ttl_seconds=settings.prompt_cache_ttl_seconds,
)
EvidenceGovernanceService(SqlAlchemyEvidenceGovernanceRepository(session))
CitationGuard()
SqlAlchemyQAGraphStore(session)
RagflowAdapter (shared HTTP adapter, but DB-authorized spaces bound per Run)
StructuredLLM adapter + usage port
settings.llm_model_alias
```

Do not create alternate authorization/evidence/citation rules.

- [ ] **Step 2: RED — each concurrent execute obtains a distinct AsyncSession**

Use a fake session factory that records session identities. Execute two QA Runs concurrently and assert sessions differ while the long-lived RAGFlow/LLM HTTP adapters may be shared safely.

- [ ] **Step 3: RED — RAGFlow binding is seeded only from DB authorization**

Before graph retrieval, authorize `run.user_id` + `run.project_id` through `AuthorizationService`, then call:

```python
for dataset_id in context.knowledge_space_ids:
    knowledge.bind_authorized_space(
        project_id=context.project_code,
        dataset_id=dataset_id,
    )
```

Test that no dataset not present in `AuthorizedProjectContext.knowledge_space_ids` is bound.

- [ ] **Step 4: RED — production executor preserves WS3 result projection**

Given a compiled QA graph returning:

```python
{"route": "answered", "answer_id": str(answer_id)}
```

assert `RunGraphOutcome(SUCCEEDED, result_ref=str(answer_id))`.

Given:

```python
{"route": "refusal", "answer_id": str(answer_id), "last_error_code": "INSUFFICIENT_EVIDENCE"}
```

assert the same `RunGraphOutcomeKind.REFUSED` behavior already defined by `LangGraphRunExecutor`.

Prefer delegating projection to `LangGraphRunExecutor({RunBusinessMode.QA: compiled_graph})` rather than duplicating projection logic.

- [ ] **Step 5: Run RED**

```bash
python -m pytest -q tests/unit/runtime/test_qa_runtime.py
```

- [ ] **Step 6: Implement the minimum per-Run composition**

Execution sequence:

```text
open fresh AsyncSession
-> construct repositories/services/store bound to this session
-> authorize run user/project for binding seed
-> bind only returned active RAGFlow spaces
-> build QAGraphDependencies
-> build_project_qa_graph(deps, checkpointer=saver)
-> delegate execute to LangGraphRunExecutor
-> commit application-session graph artifacts/telemetry before returning outcome
-> rollback on exception
-> close session
```

The session is not stored in Worker-global state and is not shared across concurrent jobs.

**Transaction note:** WS4 must not weaken the frozen WS3 checkpoint semantics. The implementation must ensure the final successful/refusal graph invocation commits QA artifacts before the Worker persists the terminal Run outcome. A crash exactly between individual node persistence and LangGraph checkpoint persistence is not redesigned into a distributed transaction in WS4; if implementation uncovers a reproducible inconsistency at this boundary, stop and surface it rather than adding a new transaction/queue architecture.

- [ ] **Step 7: GREEN unit runtime**

```bash
python -m pytest -q \
  tests/unit/runtime/test_qa_runtime.py \
  tests/unit/workers/test_run_graph.py \
  tests/unit/runtime/test_worker_runtime.py
```

- [ ] **Step 8: Add PostgreSQL integration test for real QA persistence**

`tests/integration/agent/test_qa_runtime_postgres.py` is opt-in with `RUN_POSTGRES_INTEGRATION=1`. It must use real PostgreSQL repositories/checkpointer while keeping RAGFlow and LLM as deterministic fakes. Seed:

```text
company/client/project with code
active user membership
active project knowledge space
published authorized document version
prompt config
RUN_QUEUED query event
```

Execute a QA Run and assert persisted:

```text
answer row
citation row(s)
model_alias
prompt_version/content_hash
input_tokens/output_tokens/total_tokens
retrieval_rounds in {1, 2}
terminal graph outcome consistent with persisted answer/refusal
```

- [ ] **Step 9: Server PostgreSQL gate**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
export PYTHONPATH="$PWD/src"

alembic current
alembic heads
python -m pytest -q -rs \
  tests/integration/agent/test_qa_runtime_postgres.py \
  tests/integration/evidence/test_citation_persistence.py \
  tests/integration/agent/test_postgres_checkpointer.py
```

Expected migration state remains `0005_run_runtime_envelope (head)`. Any new Alembic head is a scope violation unless the plan is revised.

- [ ] **Step 10: Static gate and commit**

```bash
ruff check src tests
mypy src
git diff --check
git add \
  src/project_agent/runtime/qa.py \
  src/project_agent/runtime/__init__.py \
  src/project_agent/infrastructure/db/repositories/qa_graph.py \
  tests/unit/runtime/test_qa_runtime.py \
  tests/integration/agent/test_qa_runtime_postgres.py
git commit -m "feat(qa): compose production qa runtime"
```

**Completion criteria:** real QA dependencies can be constructed per Run, PostgreSQL artifacts/telemetry persist, and no shared `AsyncSession` exists across Worker concurrency. RAGFlow/LLM are still fake in this Task's PostgreSQL gate.

---

#### Phase 2C: Wire Production QA Executor into the Existing WS3 Worker Runtime

**Goal:** Connect the WS4 QA executor at the exact WS3 factory seam without changing frozen Execute/Resume handler behavior or breaking test injection.

**Files:**
- Modify: `src/project_agent/runtime/worker.py:22-151`
- Modify: `src/project_agent/runtime/__init__.py`
- Modify: `tests/unit/runtime/test_worker_runtime.py`
- Create: `tests/integration/workers/test_qa_worker_postgres.py`

**Interfaces:**

Preserve the existing override:

```python
type GraphExecutorFactory = Callable[[object], RunGraphExecutor]
```

Change `build_worker_runtime()` so production can omit the test factory while all existing tests/callers may still inject one:

```text
build_worker_runtime(
    settings: Settings,
    *,
    graph_executor_factory: GraphExecutorFactory | None = None,
    retention_repository: RetentionRepository | None = None,
) -> AsyncIterator[WorkerRuntime]
```

When a factory is explicitly supplied, behavior must remain byte-for-byte equivalent at the contract level: call it once with the saver and register existing WS3 handlers.

When omitted, Worker runtime owns the real WS4 `httpx.AsyncClient` lifetimes and builds the production QA executor using Phase 2B.

- [ ] **Step 1: RED — existing injected factory behavior remains unchanged**

Keep current assertions in `tests/unit/runtime/test_worker_runtime.py` and add one explicit assertion that an injected factory prevents creation of real RAGFlow/LLM clients.

This prevents WS4 production composition from making unit tests open live services.

- [ ] **Step 2: RED — default production path owns both HTTP clients**

Monkeypatch `httpx.AsyncClient` and Phase 2B's builder. Assert the default path creates:

```text
RAGFlow client: base_url=settings.ragflow_base_url, timeout=settings.ragflow_request_timeout_seconds
LLM client:     base_url=settings.llm_base_url with trailing slash preserved, timeout=settings.llm_request_timeout_seconds
```

Construct:

```text
RagflowAdapter.from_http_client(
    ragflow_http,
    api_key=settings.ragflow_api_key.get_secret_value(),
    object_store=None,
    embedding_model=settings.ragflow_embedding_model,
    chunk_method=settings.ragflow_chunk_method,
    retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
)
OpenAICompatibleStructuredLLMAdapter(
    llm_http,
    api_key=settings.llm_api_key.get_secret_value(),
    retry_policy=StructuredLLMRetryPolicy(max_attempts=settings.llm_max_attempts),
)
```

Both clients close when `build_worker_runtime()` exits.

- [ ] **Step 3: RED — WS3 handlers remain the execution owner**

Resolve `EXECUTE_AGENT_RUN` and assert it is still `ExecuteAgentRunHandler`; resolve `RESUME_AGENT_RUN` and assert it is still `ResumeAgentRunHandler`. Do not invoke graphs directly from the queue or Worker bootstrap.

- [ ] **Step 4: Run RED**

```bash
python -m pytest -q tests/unit/runtime/test_worker_runtime.py
```

- [ ] **Step 5: Implement default WS4 graph-factory composition**

Inside the existing checkpointer lifetime:

```text
if graph_executor_factory is provided:
    graph_executor = graph_executor_factory(saver)
else:
    create real RAGFlow + real LLM HTTP clients/adapters
    graph_executor = build_production_qa_executor(
        settings=settings,
        session_factory=session_factory,
        saver=saver,
        knowledge=knowledge,
        llm=llm,
        llm_usage=llm,
    )
```

Do not alter `_build_handler_registry()` semantics except typing required to accept the returned executor.

Do not enable `INGEST_DOCUMENT`/`DELETE_DOCUMENT` Worker jobs; their WS3 explicit-disabled decision remains frozen unless a later approved workstream changes it.

- [ ] **Step 6: GREEN worker unit regression**

```bash
python -m pytest -q \
  tests/unit/runtime/test_worker_runtime.py \
  tests/unit/workers/test_run_execution.py \
  tests/unit/workers/test_run_graph.py
```

- [ ] **Step 7: Add PostgreSQL Worker integration using fake external providers**

`tests/integration/workers/test_qa_worker_postgres.py` should:

```text
create durable QA Run (`RunBusinessMode.QA`) + EXECUTE_AGENT_RUN job
use real PostgreSQL queue + real WS3 ExecuteAgentRunHandler + real checkpointer
inject Phase 2B QA executor with fake Knowledge port + FakeStructuredLLM
run one Worker cycle
assert Run terminal state, answer/citations, token counters, retrieval_rounds
assert RUN_STARTED/terminal event idempotency remains WS3-compatible
```

Also include an inadequate-two-round case ending `REFUSED` with exactly `retrieval_rounds == 2`.

- [ ] **Step 8: Server inherited WS3 + new QA Worker PostgreSQL gate**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
export PYTHONPATH="$PWD/src"

python -m pytest -q -rs \
  tests/integration/workers/test_run_worker_postgres.py \
  tests/integration/workers/test_run_resume_postgres.py \
  tests/integration/workers/test_qa_worker_postgres.py
```

WS3 tests must remain green unchanged. A WS3 regression blocks Big Task 2 completion.

- [ ] **Step 9: Static gate and commit**

```bash
ruff check src tests
mypy src
git diff --check
git add \
  src/project_agent/runtime/worker.py \
  src/project_agent/runtime/__init__.py \
  tests/unit/runtime/test_worker_runtime.py \
  tests/integration/workers/test_qa_worker_postgres.py
git commit -m "feat(worker): wire production qa executor"
```

**Completion criteria:** default Worker runtime can build the real QA executor; explicit injected factory still works for tests; WS3 execute/resume semantics are unchanged; PostgreSQL durable QA Worker flow passes with fake external providers.


**Big Task 2 acceptance gate:**

- ingestion/delete/retrieval share canonical `project_code` provider scope;
- cross-project binding rejection remains enforced;
- production QA dependencies are created per Run without shared mutable `AsyncSession`;
- default Worker runtime constructs the production QA executor through the existing factory seam while explicit test injection still works;
- inherited WS3 execute/resume/checkpointer regressions remain green;
- PostgreSQL live gate is fresh; RAGFlow live isolation is fresh when server prerequisites are available, otherwise explicitly `⏳`;
- no migration and no WS3 semantic change.

---

### Big Task 3: Real Provider/RAGFlow QA Live Acceptance and WS4 Close-Out

**Big Task Goal:** Prove the complete WS4 acceptance boundary against real PostgreSQL + RAGFlow + Structured LLM, project controlled provider failures through the existing Run semantics, and create the WS4 close-out evidence only after all required live gates are green.

**Dependency:** Big Tasks 1–2 must be accepted first. No new business behavior is introduced here except fixes required by a genuinely failing WS4 live RED, and such fixes require `systematic-debugging` before modification.

#### Phase 3A: Real Provider/RAGFlow QA Live Gate, Failure Projection, and Close-Out Evidence

**Goal:** Prove the WS4 acceptance boundary against real PostgreSQL + RAGFlow + Structured LLM without folding WS5/WS7 work into this workstream.

**Files:**
- Create: `tests/integration/llm/test_structured_provider.py`
- Create: `tests/integration/workers/test_qa_worker_live.py`
- Create: `docs/runbooks/ws4-live-qa.md`
- Create only after all server gates pass: `docs/superpowers/plans/2026-09-16-ws4-real-structured-llm-qa-completed.md`
- Modify existing files only when a live RED exposes a genuine WS4 defect; use `systematic-debugging` before any fix.

**Live flags:**

```text
RUN_POSTGRES_INTEGRATION=1
RUN_RAGFLOW_INTEGRATION=1
RUN_LLM_INTEGRATION=1
```

The tests must skip unless their exact live dependency flag is enabled. A skip is not a pass.

- [ ] **Step 1: RED/skip-first — add deterministic Structured LLM live test**

`tests/integration/llm/test_structured_provider.py` uses the real Big Task 1 / Phase 1A adapter and a tiny deterministic Pydantic schema:

```python
class LiveStructuredProbe(BaseModel):
    status: Literal["ok"]
```

Prompt the configured provider to return `{"status":"ok"}` and assert:

```text
validated model == LiveStructuredProbe(status="ok")
usage.input_tokens >= 0
usage.output_tokens >= 0
```

Also send one intentionally invalid/unfulfillable protocol test using `httpx.MockTransport` in the contract suite, not by trying to force the real provider to violate its schema. The real live gate proves reachability/structured output/usage; deterministic offline tests prove malformed-response mapping.

- [ ] **Step 2: Run live Structured LLM gate on server**

```bash
export RUN_LLM_INTEGRATION=1
export PYTHONPATH="$PWD/src"
# LLM_BASE_URL / LLM_API_KEY / LLM_MODEL_ALIAS come from the server's WS4 environment.
python -m pytest -q -rs tests/integration/llm/test_structured_provider.py
```

If the server provider does not support the Plan Review Gate's OpenAI-compatible JSON-schema protocol, stop here and revise Big Task 1 / Phase 1A and this plan. Do not add a second adapter ad hoc.

- [ ] **Step 3: Build combined real QA Worker live test**

`tests/integration/workers/test_qa_worker_live.py` must use:

```text
real PostgreSQL repositories/queue/checkpointer
real RAGFlow adapter/client
real Structured LLM adapter
real build_project_qa_graph
real WS3 Worker execute handler
```

The test seeds two projects with distinct codes/spaces and a minimal published QA document corpus. It then creates a durable QA Run for one authorized user/project and asserts:

```text
Run is consumed from PostgreSQL job queue
RAGFlow returns only authorized project Evidence
retrieval_rounds is 1 or 2, never > 2
answer is either grounded+persisted with citations or controlled refusal
if answered, every citation points to persisted governed Evidence from the same project
model_alias + prompt snapshot fields are set
input/output/total token usage is persisted
no cross-project Evidence/Citation exists
```

Include a deterministic refusal scenario where bounded retrieval remains inadequate and confirm no unsupported answer is persisted.

- [ ] **Step 4: Prove controlled provider failure projection**

Use a Worker integration test with a deliberately failing local/mock LLM HTTP transport so the real adapter raises one of its sanitized application-visible exceptions. Run through `ExecuteAgentRunHandler`/queue attempts and assert the existing WS3 final-failure mechanism records a controlled error code derived from the typed exception and never stores the API key/raw Authorization header.

Do not change WS3 retry/final-failure semantics simply to produce a nicer WS4 status.

- [ ] **Step 5: Run complete live WS4 gate on real server**

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws4-real-structured-llm-qa
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate it-agent
export PYTHONPATH="$PWD/src"

export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
export RUN_RAGFLOW_INTEGRATION=1
export RUN_LLM_INTEGRATION=1

alembic current
alembic heads

python -m pytest -q -rs tests/integration/llm/test_structured_provider.py
python -m pytest -q -rs tests/integration/ragflow/test_project_isolation.py
python -m pytest -q -rs tests/integration/agent/test_qa_runtime_postgres.py
python -m pytest -q -rs tests/integration/workers/test_qa_worker_postgres.py
python -m pytest -q -rs tests/integration/workers/test_qa_worker_live.py
```

Required live acceptance:

```text
PostgreSQL head = 0005_run_runtime_envelope
Structured provider reachable + valid structured response + usage
RAGFlow project isolation passes
QA graph executes from durable Run/job/checkpointer path
one-round and bounded-two-round telemetry is correct
real answer/refusal respects existing evidence/citation rules
provider failure is controlled/sanitized
0 failed in WS4 live gates
0 skipped among explicitly enabled WS4 live tests
```

- [ ] **Step 6: Full regression and static acceptance**

With PostgreSQL enabled and the existing RAGFlow/LLM flags set as appropriate for the environment:

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest -q -rs
```

Record exact pass/skip/fail counts. Do not accept a newly skipped WS4 test. Existing optional skips must be explained by a dependency flag that was intentionally not enabled; when all three WS4 flags are enabled, all WS4 live tests must run.

- [ ] **Step 7: Architecture/scope audit before completion record**

Verify the diff contains no:

```text
Redis/Celery/ARQ
MinIO
second vector DB
new multi-agent orchestration
production Jira/ZenTao/Feishu integration
Kubernetes
new unified LangGraph
WS5 Issue evidence-chain implementation
WS6 cost/observability implementation
WS7 Docker/Compose expansion
WS8 evaluation runner
new Alembic migration
```

Verify these frozen files are unchanged unless the user explicitly approved a documentation-only correction:

```text
docs/adr/0004-v1-architecture-lock.md
docs/superpowers/specs/2026-09-12-v1-completion-design.md
```

- [ ] **Step 8: Write the WS4 live runbook**

`docs/runbooks/ws4-live-qa.md` documents exact environment variables, fixture/seeding assumptions, individual live commands, expected evidence, and cleanup. It must distinguish offline tests from server live gates and must not claim provider quality/accuracy beyond measured behavior.

- [ ] **Step 9: Use verification-before-completion and write completion record only with fresh evidence**

`docs/superpowers/plans/2026-09-16-ws4-real-structured-llm-qa-completed.md` records:

```text
branch + final HEAD
Task commit SHAs
Ruff result
MyPy result
full pytest pass/skip/fail counts
PostgreSQL/RAGFlow/LLM live commands and counts
max retrieval-round evidence
answer/citation/token persistence evidence
known remaining WS5+ items
scope/architecture-lock audit
```

If any required live gate is unavailable, do not create a document that says `WS4 COMPLETE`; record `live acceptance ⏳` instead.

- [ ] **Step 10: Commit live tests/runbook/completion evidence**

Only after all required gates are freshly green:

```bash
git add \
  tests/integration/llm/test_structured_provider.py \
  tests/integration/workers/test_qa_worker_live.py \
  docs/runbooks/ws4-live-qa.md \
  docs/superpowers/plans/2026-09-16-ws4-real-structured-llm-qa-completed.md
git commit -m "test(ws4): prove live qa completion"
```

Then use `superpowers:finishing-a-development-branch` for final branch review/merge options. Do not delete the WS3 preserved worktree.

**Completion criteria:** the exact WS4 acceptance boundary is demonstrated with real RAGFlow + real Structured LLM + PostgreSQL/checkpointer + existing Worker runtime, with answer/refusal, citations, token usage, and retrieval rounds persisted and no architecture-lock expansion.

---

## No-Migration Decision

WS4 does **not** require a new migration based on the current snapshot because:

- `agent_runs` already stores `model_alias`, prompt version/hash, input/output/total token counters, and `retrieval_rounds`;
- QA artifacts already have `agent_events`/Evidence bundle storage;
- answers and citations already have persistence models;
- project code and project knowledge-space mappings already exist in PostgreSQL;
- Big Task 2 / Phase 2A only reads the existing project code and changes provider-facing identity/binding behavior.

If a RED test appears to require a migration, stop and demonstrate the missing persisted field against the current schema before adding one. A convenience migration is not allowed.

## Configuration Decision

New application settings planned in WS4 are only:

```text
LLM_REQUEST_TIMEOUT_SECONDS=30
LLM_MAX_ATTEMPTS=3
```

The live-test flag `RUN_LLM_INTEGRATION=1` is a pytest environment gate, not persisted application configuration. Existing RAGFlow/PostgreSQL flags remain unchanged.

## Offline vs Live Verification Matrix

| Behavior | Offline proof | Required server live proof |
| --- | --- | --- |
| Structured request JSON-schema mapping | `httpx.MockTransport` contract tests | real provider deterministic structured probe |
| Retry/failure sanitization | contract tests | controlled Worker failure projection can use local/mock failing transport; no secret exposure |
| Pydantic structured validation | contract tests | real structured response validates |
| Grade schema/invariants | unit tests | exercised in real QA live Run |
| Max two rounds | unit/e2e/security tests | persisted live `retrieval_rounds <= 2` |
| ProjectAccessScope preservation | security tests | two-project RAGFlow isolation |
| RAGFlow metadata/mapping | RAGFlow contract tests | real RAGFlow project-isolation test |
| PostgreSQL QA persistence | opt-in Postgres integration | same test on server PostgreSQL |
| Checkpointer/Worker dispatch | existing WS3 + new Postgres Worker tests | real PostgreSQL checkpointer path |
| Answer/citations/token telemetry | offline fake-provider + Postgres test | combined real QA Worker live test |

## Exact WS4 ↔ WS3 Connection Point

WS4 does not replace the Worker lifecycle. The intended production call chain after Big Task 2 is:

```text
PostgreSQL background_jobs(EXECUTE_AGENT_RUN, aggregate_id=run_id)
  -> BackgroundWorker
  -> ExecuteAgentRunHandler
  -> RunExecutionService.prepare_execute(run_id)
  -> existing Run becomes RUNNING / RUN_STARTED persisted
  -> WS4 ProductionQARunExecutor.execute(run)
       -> fresh per-Run AsyncSession
       -> DB authorization -> canonical RAGFlow space binding
       -> build_project_qa_graph(deps, checkpointer=existing WS3 saver)
       -> LangGraphRunExecutor.execute(run)
       -> QA graph nodes
       -> persisted answer/refusal/citations/tokens/retrieval rounds
  -> RunGraphOutcome
  -> existing RunExecutionService.persist_outcome(run.id, outcome)
  -> existing terminal Run/Event semantics
  -> queue completion/retry/final-failure semantics remain WS3-owned
```

`RESUME_AGENT_RUN` remains registered and frozen for WS3/WS5-compatible interrupt flows. WS4 QA itself does not invent a resume interaction.

## WS4 Scope Audit Checklist

Before Big Task 1 and again before WS4 close-out, verify:

- [ ] WS3 Worker/run/checkpointer semantics are unchanged.
- [ ] Existing `StructuredLLMPort` remains the only LLM application abstraction.
- [ ] Existing evidence governance/Citation Guard remain authoritative.
- [ ] Grade output cannot grant access or override document authority/current/effective filtering.
- [ ] Second retrieval preserves the original authorized project/spaces/document versions.
- [ ] Graph has no path to a third retrieval.
- [ ] No new Alembic migration exists.
- [ ] No WS5 Issue runtime/evidence chain is implemented.
- [ ] No WS6 observability/cost accounting expansion is implemented.
- [ ] No WS7 Docker/Compose expansion is implemented.
- [ ] No WS8 evaluation runner is implemented.
- [ ] No architecture-lock infrastructure is added.
- [ ] Live gates are marked `⏳` until run on the real server.

## Implementation Order and Review Gates

Execute exactly one **Big Task** at a time:

```text
Revised Plan approval + Decisions A/B accepted
  -> Big Task 1
       Phase 1A: real Structured LLM adapter
       Phase 1B: retrieval grade schema/node
       Phase 1C: bounded max-two-round QA graph
       -> Big Task 1 verification/report/full-project ZIP
  -> Big Task 2
       Phase 2A: canonical RAGFlow project scope/binding
       Phase 2B: production QA factory + per-Run session
       Phase 2C: WS3 Worker factory-seam wiring
       -> Big Task 2 PostgreSQL/RAGFlow/inherited regression report/full-project ZIP
  -> Big Task 3
       real PostgreSQL + RAGFlow + Structured LLM live acceptance
       controlled failure projection
       close-out evidence / completed-plan document
```

Do not stop for an external review between internal phases unless a failing RED exposes a design/source-of-truth ambiguity. Still run each phase's RED/GREEN/targeted/static gates before advancing. After each **Big Task**, stop for the required three-status report and user review; do not implement Big Tasks 1–3 in one delivery.

## Plan Self-Review

**Spec coverage:**

- Real Structured LLM adapter/usage: Big Task 1 / Phase 1A + Big Task 3.
- Provider failure handling: Big Task 1 / Phase 1A + Big Task 3.
- Retrieval grade: Big Task 1 / Phase 1B.
- Max-two-round retrieval and same-scope retry: Big Task 1 / Phase 1C, with Phase 1B–1C security tests.
- RAGFlow real boundary/project isolation: Big Task 2 / Phase 2A + Big Task 3.
- QA production dependency wiring: Big Task 2 / Phases 2B–2C.
- QA live path/token/retrieval telemetry: Big Tasks 2–3.
- Existing evidence/citation rules: preserved and regressed in Big Task 1 / Phase 1C, Big Task 2 / Phase 2B, and Big Task 3.
- WS3 runtime contract: Big Task 2 / Phase 2C explicitly composes at the existing factory seam.
- No WS5+ scope: explicitly excluded in every global/close-out audit.

**Placeholder scan:** No implementation step intentionally defers unspecified error handling, validation, tests, or live commands. The two source-level ambiguities are explicit Plan Review Gate decisions rather than hidden implementation assumptions.

**Type/interface consistency:** `StructuredLLMPort`, `StructuredLLMUsagePort`, `RunGraphExecutor`, `AuthorizedProjectContext`, `QAGraphStorePort`, and `KnowledgeRetrievalRequest` remain the shared interfaces throughout all Big Tasks. New retrieval grade/state names are consistent across Big Task 1 Phases 1B–1C. The production QA executor produced in Big Task 2 / Phase 2B is the object consumed by Phase 2C.

---

## Coding Start Gate

WS4 implementation is technically ready to begin from the supplied baseline **only after** all of the following are true:

- [ ] this revised 3-Big-Task plan is approved;
- [ ] Decision A is accepted, or the real server LLM protocol is supplied and the plan is revised before Phase 1A;
- [ ] Decision B is accepted;
- [ ] real WS4 worktree still reports branch `feat/ws4-real-structured-llm-qa`, expected starting HEAD lineage from `ba1f9b3`, and a clean status;
- [ ] shell uses `it-agent` and `PYTHONPATH="$PWD/src"`;
- [ ] fresh server pre-coding baseline is rerun before the first production change (at minimum Ruff, MyPy, targeted inherited WS3 gate, and full pytest baseline as practical).

No additional migration, architecture redesign, or WS5 prerequisite is required before Big Task 1.

---

## Plan Review Gate

**Do not start Big Task 1 yet.** Review/approve this revised plan first, especially:

1. Decision A: OpenAI-compatible Chat Completions + JSON Schema as the concrete V1 Structured LLM protocol.
2. Decision B: `project_code` as canonical RAGFlow provider scope and the targeted publish/delete/binding repair.
3. The three-Big-Task boundary, retained internal TDD phases, and the explicit no-migration decision.

After approval, execute **Big Task 1 only**, preserving Phase 1A→1B→1C TDD gates, and produce one requested full-project Big Task 1 ZIP delivery rather than a patch-only response.
