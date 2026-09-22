# WS5 Unified Issue Runtime + Requirement/Test Evidence Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete WS5 so `issue_lookup` and `issue_create` execute through the frozen WS2/WS3 Run/Worker envelope, `issue_create` freezes authorized requirement/test EvidenceSnapshot IDs before creating a draft, exposes those IDs at confirmation, and only an authorized valid resume can create one idempotent Sandbox Issue.

**Architecture:** Keep the frozen WS2/WS3 runtime contracts and Task 13 write-safety rules intact. Add a WS5-only requirement/test Evidence selector and retrieval/freeze node, add two Issue Run graphs (`issue_lookup` and `issue_create`), and provide a WS5 concrete graph-executor factory that plugs into the existing `build_worker_runtime(..., graph_executor_factory=...)` injection point. Reuse the existing EvidenceSnapshot schema, IssueDraft `evidence_ids_json`, PostgreSQL checkpointer, Run/Event state machine, Sandbox tracker, idempotency and reconciliation paths; do not merge WS4 or require answer generation.

**Tech Stack:** Python 3.12.14, FastAPI, LangGraph 1.2.x, SQLAlchemy asyncio, PostgreSQL/asyncpg, PostgreSQL LangGraph checkpointer, RAGFlow retrieval adapter, Pydantic v2, pytest/pytest-asyncio, Ruff, MyPy.

**Spec:** `docs/superpowers/specs/2026-09-12-v1-completion-design.md` §§12, 19 WS5, 20; plus the approved WS5 design gate in the 2026-09-18 handoff: **independent WS5 Issue Evidence Selector + reuse existing EvidenceSnapshot/schema + two Issue Run graphs + keep WS2/WS3/Task13 contracts unchanged + no dependency on WS4 answer generation**.

## Verified Starting Evidence

Fresh server evidence supplied for the real WS5 worktree:

```text
python=/home1/ckx/miniconda3/envs/it-agent/bin/python
Python 3.12.14
branch=feat/ws5-issue-runtime-evidence
HEAD=ba1f9b3f910b3ebf4e3f543228587ef4dd8511e9
ruff check src tests -> All checks passed!
mypy src -> Success: no issues found in 121 source files
python -m pytest -q -rs -> 302 passed, 22 skipped in 3.57s
```

The 22 skips are live/environment gates and are **not** counted as passed live evidence. Offline baseline is GREEN; PostgreSQL/RAGFlow live verification remains an explicit WS5 gate below.

## Global Constraints

- Real worktree: `/home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws5-issue-runtime-evidence`.
- Branch must remain `feat/ws5-issue-runtime-evidence`; starting baseline is `ba1f9b3f910b3ebf4e3f543228587ef4dd8511e9`.
- Do **not** rebase onto or merge the WS4 feature branch.
- Do **not** redesign WS1–WS4 or replace the frozen WS2 Run API / resume contract.
- Do **not** change WS3 queue claim, lease, heartbeat, retry, `EXECUTE_AGENT_RUN`, `RESUME_AGENT_RUN`, `RunExecutionService`, `Command(resume=...)`, or Run/Event projection semantics.
- Do **not** weaken Task 13 confirmation, immediate pre-write authorization re-check, idempotency barrier, provider request-id uniqueness, or reconciliation behavior.
- `issue_lookup` is business-read-only: it may persist normal Run/AgentEvent artifacts, but it must create no IssueDraft, ToolConfirmation, IdempotencyRecord, or SandboxIssue.
- `issue_create` must freeze at least one governed `requirement_baseline` or `approved_test_spec` EvidenceSnapshot **before** IssueDraft creation. No qualifying evidence => terminal refusal with stable `EVIDENCE_REQUIRED`, zero draft, zero confirmation, zero Sandbox write.
- Historical Issue candidates remain advisory and never substitute for requirement/test EvidenceSnapshot IDs.
- Evidence IDs displayed at confirmation are review metadata bound to the immutable draft. Preserve the existing Task 13 `CreateIssueRequest` payload-hash algorithm; do **not** add evidence IDs to that provider payload hash in WS5.
- Reuse existing schema. Planned Alembic head remains `0005_run_runtime_envelope`; no `0006` migration is allowed unless a RED test proves the frozen requirements cannot be represented by existing columns.
- No Redis, Celery, MinIO, second vector DB, new multi-agent architecture, unified LangGraph rewrite, Kubernetes, production Jira/SaaS writes, WS6 observability work, WS7 Docker closure, or WS8 evaluation implementation.
- Do not require WS4 Structured LLM/answer generation. WS5 may use RAGFlow retrieval directly.
- Final verification commands are non-mutating; never use `ruff check --fix` as a completion gate.
- Every implementation task follows RED -> confirm expected failure -> minimal GREEN -> targeted regression -> static gates -> explicit commit.

---

# File Map Locked for WS5

## Create

- `src/project_agent/application/services/issue_evidence.py` — deterministic selector for project-authorized, current/effective requirement/test document versions.
- `src/project_agent/agent/nodes/issue_evidence.py` — WS5 node that performs constrained retrieval, post-filter, governance, and EvidenceSnapshot freeze; emits `EVIDENCE_REQUIRED` fail-closed.
- `src/project_agent/agent/issue_run_graph.py` — the two WS5 Run graphs only: `issue_lookup` and `issue_create`.
- `src/project_agent/runtime/issue.py` — concrete WS5 Issue `RunGraphExecutor` factory consumed by the frozen WS3 `build_worker_runtime(..., graph_executor_factory=...)` injection point; owns WS5 graph dependency construction and resource cleanup.
- `tests/unit/issues/test_issue_evidence.py` — selector/node RED/GREEN tests.
- `tests/unit/agent/test_issue_run_graph.py` — graph routing, read-only lookup, pre-draft evidence refusal, and interrupt path tests.
- `tests/unit/runtime/test_issue_runtime.py` — concrete dependency-construction/dispatch/cleanup tests without real RAGFlow.
- `tests/integration/issues/test_issue_run_runtime_postgres.py` — real PostgreSQL API/queue/worker/checkpointer Issue lookup + interrupt/resume + idempotent Sandbox create gate.
- `tests/integration/issues/test_issue_evidence_ragflow.py` — real RAGFlow requirement/test retrieval gate; no LLM.

## Modify

- `src/project_agent/application/services/issue_drafts.py` — accept frozen evidence IDs when creating a draft; leave provider request payload/hash unchanged.
- `src/project_agent/domain/issues.py` — expose immutable `evidence_ids` in `ConfirmationRequest`.
- `src/project_agent/application/services/issue_confirmation.py` — copy draft evidence IDs into the confirmation review payload.
- `src/project_agent/agent/nodes/build_issue_draft.py` — when a governed evidence bundle reference exists, load it and pass frozen snapshot IDs into the draft.
- `src/project_agent/runtime/worker.py` — only add optional cleanup of a concrete graph executor that exposes `aclose()`; do not change Worker job semantics or the graph-factory call signature.
- Existing test files only when extending a frozen invariant is clearer than duplicating it:
  - `tests/unit/issues/test_issue_draft.py`
  - `tests/unit/issues/test_confirmation.py`
  - `tests/unit/runtime/test_worker_runtime.py`
  - `tests/unit/workers/test_run_graph.py`
  - `tests/security/test_unconfirmed_issue_create.py`
  - `tests/security/test_issue_permission_recheck.py`
  - `tests/reliability/test_issue_response_lost.py`

## Explicitly Not Modified

- migrations / Alembic files unless a RED test forces reconsideration; expected outcome is no migration.
- WS2 Run API external request/resume schemas.
- `src/project_agent/application/services/run_execution.py`.
- `src/project_agent/workers/run_execution.py`.
- `src/project_agent/workers/main.py` queue/lease/heartbeat behavior.
- Task 13 provider payload format / payload-hash field set.
- WS4 QA graph, Structured LLM, retrieval-grading, answer-generation code.

---

# Pre-Implementation Gate: Real PostgreSQL Baseline

This gate happens before Task 1 code changes because the offline baseline skipped all live PostgreSQL tests.

- [ ] **Step 1: Re-enter the exact WS5 worktree and environment**

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws5-issue-runtime-evidence
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate it-agent
export PYTHONPATH="$PWD/src"
set -a
source .env
set +a

export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

python --version
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected before coding:

```text
Python 3.12.14
feat/ws5-issue-runtime-evidence
ba1f9b3f910b3ebf4e3f543228587ef4dd8511e9
<empty git status --short>
```

- [ ] **Step 2: Run the existing live PostgreSQL baseline most relevant to WS5**

```bash
python -m pytest \
  tests/integration/db/test_postgres_schema.py \
  tests/integration/auth/test_authorization_repository.py \
  tests/integration/api/test_run_api_postgres.py \
  tests/integration/issues/test_postgres_issue_workflow.py \
  tests/integration/workers/test_run_worker_postgres.py \
  tests/integration/workers/test_run_resume_postgres.py \
  -v -rs
```

Expected: all selected PostgreSQL tests PASS with **zero selected-test skips**. If this fails, stop in baseline diagnosis and invoke `superpowers:systematic-debugging`; do not start WS5 RED tests.

- [ ] **Step 3: Reconfirm schema head before WS5**

```bash
alembic current
alembic heads
```

Expected: both resolve to `0005_run_runtime_envelope`.

**Gate judgment:**

```text
需求完成：⏳ precondition only
测试闭环：✅ only if selected live PostgreSQL baseline has zero skips/failures
新 bug：未发现 / 已发现：<exact baseline failure>
```

---

## Task 1: Independent Requirement/Test Evidence Selector + Freeze Node

**Files:**
- Create: `src/project_agent/application/services/issue_evidence.py`
- Create: `src/project_agent/agent/nodes/issue_evidence.py`
- Create: `tests/unit/issues/test_issue_evidence.py`
- Reuse unchanged: `src/project_agent/application/services/evidence_governance.py`
- Reuse unchanged: `src/project_agent/agent/policies/access.py`
- Reuse unchanged: `src/project_agent/application/ports/knowledge.py`
- Reuse unchanged: `src/project_agent/application/ports/qa_graph.py`

**Interfaces:**
- Consumes: `AuthorizedProjectContext`, `EvidenceGovernanceRepository`, `KnowledgeRetrievalPort`, `ProjectAccessPolicy`, `EvidenceGovernanceService`, `QAGraphStorePort`.
- Produces:
  - `IssueEvidenceSelector.select_document_version_ids(*, project_id: UUID, context: AuthorizedProjectContext) -> tuple[UUID, ...]`
  - `retrieve_issue_evidence_node(...) -> AgentState`
  - success state: `{"evidence_bundle_id": "<uuid>", "route": "issue_evidence_ready", "last_error_code": None}`
  - fail-closed state: `{"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}`

- [ ] **Step 1: Write RED selector tests**

Add tests proving that selection occurs **before retrieval** and is limited to the two frozen document categories.

```python
async def test_issue_evidence_selector_returns_only_authorized_requirement_and_test_versions():
    project_id = uuid4()
    requirement = uuid4()
    test_spec = uuid4()
    design = uuid4()
    other_project = uuid4()

    repo = FakeEvidenceGovernanceRepository()
    repo.records[requirement] = metadata(
        version_id=requirement,
        project_id=project_id,
        category=DocumentCategory.REQUIREMENT_BASELINE,
    )
    repo.records[test_spec] = metadata(
        version_id=test_spec,
        project_id=project_id,
        category=DocumentCategory.APPROVED_TEST_SPEC,
    )
    repo.records[design] = metadata(
        version_id=design,
        project_id=project_id,
        category=DocumentCategory.APPROVED_DESIGN,
    )
    repo.records[other_project] = metadata(
        version_id=other_project,
        project_id=uuid4(),
        category=DocumentCategory.REQUIREMENT_BASELINE,
    )
    context = authorized_context(
        project_id=project_id,
        allowed_version_ids=(requirement, test_spec, design, other_project),
    )

    selected = await IssueEvidenceSelector(repo).select_document_version_ids(
        project_id=project_id,
        context=context,
    )

    assert selected == tuple(sorted((requirement, test_spec), key=str))
```

Also add one test where requirement/test metadata is `DRAFT`, `is_current=False`, future-effective, or expired. Expected selected tuple is empty for those records.

- [ ] **Step 2: Run selector RED**

```bash
python -m pytest tests/unit/issues/test_issue_evidence.py -v
```

Expected: FAIL because `IssueEvidenceSelector` does not exist.

- [ ] **Step 3: Implement the minimal selector**

`src/project_agent/application/services/issue_evidence.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from uuid import UUID

from project_agent.application.services.authorization import AuthorizedProjectContext
from project_agent.application.services.evidence_governance import EvidenceGovernanceRepository
from project_agent.domain.enums import DocumentCategory, DocumentLifecycleStatus


class IssueEvidenceSelector:
    ALLOWED_CATEGORIES = frozenset(
        {
            DocumentCategory.REQUIREMENT_BASELINE,
            DocumentCategory.APPROVED_TEST_SPEC,
        }
    )

    def __init__(
        self,
        repository: EvidenceGovernanceRepository,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._repository = repository
        self._today = today or date.today

    async def select_document_version_ids(
        self,
        *,
        project_id: UUID,
        context: AuthorizedProjectContext,
    ) -> tuple[UUID, ...]:
        allowed = tuple(context.scope.allowed_document_version_ids or ())
        if not allowed:
            return ()
        metadata = await self._repository.get_document_evidence_metadata(
            document_version_ids=allowed
        )
        today = self._today()
        selected = []
        for version_id in allowed:
            item = metadata.get(version_id)
            if item is None or item.project_id != project_id:
                continue
            if item.document_category not in self.ALLOWED_CATEGORIES:
                continue
            if item.lifecycle_status is not DocumentLifecycleStatus.PUBLISHED:
                continue
            if not item.is_current:
                continue
            if item.effective_from is not None and item.effective_from > today:
                continue
            if item.effective_to is not None and item.effective_to < today:
                continue
            selected.append(version_id)
        return tuple(sorted(set(selected), key=str))
```

Do not modify `AuthorizedProjectContext`; the selector deliberately uses existing scope IDs plus existing governance metadata.

- [ ] **Step 4: Write RED retrieval/freeze node tests**

Cover all of these in `tests/unit/issues/test_issue_evidence.py`:

```text
selected request contains requirement/test IDs only
request is constrained by current ProjectAccessPolicy
cross-project/provider chunks are removed by postfilter
EvidenceGovernanceService runs before freeze
successful node persists governed EvidenceSnapshot records through QAGraphStorePort
no eligible versions -> EVIDENCE_REQUIRED
provider returns no authorized chunks -> EVIDENCE_REQUIRED
governance removes every chunk -> EVIDENCE_REQUIRED
```

Core assertion:

```python
result = await retrieve_issue_evidence_node(
    state,
    selector=selector,
    knowledge=knowledge,
    access_policy=ProjectAccessPolicy(),
    evidence_governance=governance,
    store=store,
)

assert result["route"] == "issue_evidence_ready"
bundle = await store.load_governed_evidence_bundle(UUID(result["evidence_bundle_id"]))
assert bundle.evidence
assert {item.document_category for item in bundle.evidence} <= {
    DocumentCategory.REQUIREMENT_BASELINE,
    DocumentCategory.APPROVED_TEST_SPEC,
}
```

- [ ] **Step 5: Run node RED**

```bash
python -m pytest tests/unit/issues/test_issue_evidence.py -v
```

Expected: selector tests GREEN; node tests FAIL because the node does not exist.

- [ ] **Step 6: Implement the minimal freeze node**

`src/project_agent/agent/nodes/issue_evidence.py` should follow the existing `retrieve.py` + `govern_evidence.py` policies without answer-generation dependencies:

```python
async def retrieve_issue_evidence_node(
    state: AgentState,
    *,
    selector: IssueEvidenceSelector,
    knowledge: KnowledgeRetrievalPort,
    access_policy: ProjectAccessPolicy,
    evidence_governance: EvidenceGovernanceService,
    store: QAGraphStorePort,
) -> AgentState:
    project_raw = state.get("project_id")
    scope_raw = state.get("access_scope_id")
    if not project_raw or not scope_raw:
        return {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}

    run_id = UUID(state["run_id"])
    project_id = UUID(project_raw)
    context = deserialize_authorized_context(await store.load_artifact(UUID(scope_raw)))
    query = await store.load_query(run_id)
    version_ids = await selector.select_document_version_ids(
        project_id=project_id,
        context=context,
    )
    if not version_ids:
        return {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}

    request = KnowledgeRetrievalRequest(
        project_id=context.project_code,
        query=query,
        limit=10,
        document_version_ids=tuple(str(value) for value in version_ids),
    )
    constrained = access_policy.constrain_retrieval(request, context)
    if constrained is None:
        return {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}

    await store.increment_retrieval_rounds(run_id=run_id)
    chunks = access_policy.postfilter_evidence(
        await knowledge.retrieve(constrained),
        context,
    )
    pack = await evidence_governance.pack(
        project_id=project_id,
        project_code=context.project_code,
        chunks=chunks,
    )
    pack = GovernedEvidencePack(
        evidence=tuple(
            item
            for item in pack.evidence
            if item.document_category in IssueEvidenceSelector.ALLOWED_CATEGORIES
        ),
        unresolved_conflicts=dict(pack.unresolved_conflicts),
    )
    if not pack.evidence:
        return {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}

    bundle_id = await store.save_governed_evidence_bundle(
        run_id=run_id,
        project_id=project_id,
        query_text=query,
        pack=pack,
    )
    return {
        "evidence_bundle_id": str(bundle_id),
        "route": "issue_evidence_ready",
        "last_error_code": None,
    }
```

The post-governance category guard is intentional defense-in-depth; it prevents a future governance change from silently broadening the WS5 evidence contract.

- [ ] **Step 7: GREEN + Task 1 regression**

```bash
python -m pytest \
  tests/unit/issues/test_issue_evidence.py \
  tests/unit/agent/test_authority_policy.py \
  tests/security/test_evidence_postfilter.py \
  -v
ruff check src tests
mypy src
git diff --check
```

Expected: all GREEN.

- [ ] **Step 8: Commit Task 1**

```bash
git add \
  src/project_agent/application/services/issue_evidence.py \
  src/project_agent/agent/nodes/issue_evidence.py \
  tests/unit/issues/test_issue_evidence.py
git diff --cached --check
git commit -m "feat: add WS5 issue evidence selector"
```

**Task 1 end judgment:**

```text
需求完成：✅ only if requirement/test preselection + constrained retrieval + frozen governed bundle are covered
测试闭环：✅ only with fresh targeted/static GREEN
新 bug：未发现 / 已发现：...
```

---

## Task 2: Bind Frozen Evidence IDs to Draft and Confirmation Review

**Files:**
- Modify: `src/project_agent/application/services/issue_drafts.py`
- Modify: `src/project_agent/agent/nodes/build_issue_draft.py`
- Modify: `src/project_agent/domain/issues.py`
- Modify: `src/project_agent/application/services/issue_confirmation.py`
- Modify: `tests/unit/issues/test_issue_draft.py`
- Modify: `tests/unit/issues/test_confirmation.py`
- Modify: `tests/integration/issues/test_postgres_issue_workflow.py`

**Interfaces:**
- Consumes: frozen `FrozenEvidenceBundle.evidence[*].snapshot_id` created in Task 1.
- Produces:
  - `IssueDraftService.create_from_text(..., evidence_ids: tuple[str, ...] = ())`
  - `IssueDraft.evidence_ids` persisted through existing `issue_drafts.evidence_ids_json`
  - `ConfirmationRequest.evidence_ids: tuple[str, ...]`
- Preserves: `IssueDraftService.build_create_request()` and `payload_hash()` field set exactly as Task 13 currently defines it.

- [ ] **Step 1: Write RED draft-binding test**

```python
async def test_issue_draft_persists_frozen_evidence_ids():
    repo = FakeIssueWorkflowRepository()
    service = IssueDraftService(repo)
    evidence_ids = (str(uuid4()), str(uuid4()))

    draft = await service.create_from_text(
        run_id=uuid4(),
        project_id=uuid4(),
        created_by=uuid4(),
        text="ERR-IMPORT-004 failed",
        evidence_ids=evidence_ids,
    )

    assert draft.evidence_ids == evidence_ids
    assert repo.drafts[draft.id].evidence_ids == evidence_ids
```

- [ ] **Step 2: Write RED node-binding test**

Seed an `InMemoryQAGraphStore.governed_bundles` bundle containing two `FrozenEvidence` items, put its ID in `AgentState.evidence_bundle_id`, call `build_issue_draft_node`, then assert the created draft contains exactly those two `snapshot_id` strings.

- [ ] **Step 3: Write RED confirmation visibility/hash-preservation test**

```python
request = await confirmations.prepare(draft.id)
assert request.evidence_ids == draft.evidence_ids

create_request = drafts.build_create_request(draft)
assert request.request_payload_hash == drafts.payload_hash(create_request)
assert "evidence_ids" not in {
    "project_id", "request_id", "title", "description", "issue_type",
    "priority", "reporter_id", "module", "error_code", "environment",
}
```

The second assertion is conceptual: the implementation must not add `evidence_ids` to `build_create_request()` or the canonical hash dictionary.

- [ ] **Step 4: Run RED**

```bash
python -m pytest \
  tests/unit/issues/test_issue_draft.py \
  tests/unit/issues/test_confirmation.py \
  -v
```

Expected: FAIL on the new `evidence_ids` argument / confirmation field.

- [ ] **Step 5: Implement minimal evidence binding**

Change `IssueDraftService.create_from_text` signature:

```python
async def create_from_text(
    self,
    *,
    run_id: UUID,
    project_id: UUID,
    created_by: UUID,
    text: str,
    candidates: IssueCandidateResult | None = None,
    evidence_ids: tuple[str, ...] = (),
) -> IssueDraft:
```

and pass:

```python
IssueDraftCreate(
    ...,
    module=module,
    evidence_ids=evidence_ids,
)
```

In `build_issue_draft_node`, preserve Task 13 compatibility: when `state.evidence_bundle_id` is absent, pass the existing empty tuple; the WS5 Run graph added later is responsible for guaranteeing evidence before this node.

```python
evidence_ids: tuple[str, ...] = ()
bundle_id = state.get("evidence_bundle_id")
if bundle_id:
    frozen = await store.load_governed_evidence_bundle(UUID(bundle_id))
    evidence_ids = tuple(str(item.snapshot_id) for item in frozen.evidence)

...
draft = await drafts.create_from_text(
    ...,
    candidates=candidate_result,
    evidence_ids=evidence_ids,
)
```

Add to `ConfirmationRequest`:

```python
evidence_ids: tuple[str, ...] = ()
```

and to `IssueConfirmationService.prepare()`:

```python
evidence_ids=draft.evidence_ids,
```

Do **not** modify the provider `CreateIssueRequest` or `payload_hash()` payload fields.

- [ ] **Step 6: Prove PostgreSQL already persists the field; no migration**

Extend `tests/integration/issues/test_postgres_issue_workflow.py` so the created `IssueDraftCreate` includes two fake snapshot ID strings and the reloaded draft asserts the same tuple.

Do not edit migration files. Run:

```bash
export RUN_POSTGRES_INTEGRATION=1
python -m pytest tests/integration/issues/test_postgres_issue_workflow.py -v -rs
alembic current
alembic heads
```

Expected: test PASS, zero selected-test skips, head stays `0005_run_runtime_envelope`.

- [ ] **Step 7: Task 2 regression**

```bash
python -m pytest \
  tests/unit/issues/test_issue_draft.py \
  tests/unit/issues/test_confirmation.py \
  tests/unit/issues/test_interrupt_node.py \
  tests/security/test_unconfirmed_issue_create.py \
  tests/security/test_issue_permission_recheck.py \
  tests/reliability/test_issue_response_lost.py \
  -v
ruff check src tests
mypy src
git diff --check
```

- [ ] **Step 8: Commit Task 2**

```bash
git add \
  src/project_agent/application/services/issue_drafts.py \
  src/project_agent/agent/nodes/build_issue_draft.py \
  src/project_agent/domain/issues.py \
  src/project_agent/application/services/issue_confirmation.py \
  tests/unit/issues/test_issue_draft.py \
  tests/unit/issues/test_confirmation.py \
  tests/integration/issues/test_postgres_issue_workflow.py
git diff --cached --check
git commit -m "feat: bind frozen evidence to issue drafts"
```

**Task 2 end judgment:**

```text
需求完成：✅ only if persisted draft IDs == frozen EvidenceSnapshot IDs and confirmation exposes them
测试闭环：✅ only if Task13 safety regression stays GREEN and PostgreSQL field round-trip passes
新 bug：未发现 / 已发现：...
```

---

## Task 3: `issue_lookup` Run Graph — Authorized and Business-Read-Only

**Files:**
- Create: `src/project_agent/agent/issue_run_graph.py`
- Create: `tests/unit/agent/test_issue_run_graph.py`
- Reuse unchanged: `src/project_agent/agent/nodes/resolve_scope.py`
- Reuse unchanged: `src/project_agent/agent/nodes/search_issues.py`
- Reuse unchanged: `src/project_agent/workers/run_graph.py`

**Interfaces:**
- Consumes: WS3 initial Run state (`run_id`, `thread_id`, `user_id`, `project_id`) and current `AuthorizationService`.
- Produces:
  - `IssueLookupRunGraphDependencies(authorization, candidates, store)`
  - `build_issue_lookup_run_graph(deps, *, checkpointer=None)`
  - terminal graph result with `issue_candidate_id` and `route="issue_candidates"`.

- [ ] **Step 1: Write RED graph tests**

At minimum:

```text
lookup starts by resolving current project scope
authorized lookup persists ISSUE_CANDIDATES artifact and succeeds
candidate search receives the Run project_id only
lookup creates no IssueDraft
lookup creates no ToolConfirmation
lookup creates no Sandbox Issue
unauthorized project fails closed before candidate search
```

Use `FakeProjectAuthorizationRepository`, `AuthorizationService`, `SandboxProjectTrackerAdapter` fake equivalent, `IssueCandidateService`, and `InMemoryQAGraphStore`.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/unit/agent/test_issue_run_graph.py -v
```

Expected: FAIL because `build_issue_lookup_run_graph` does not exist.

- [ ] **Step 3: Implement lookup graph without creating a draft path**

`src/project_agent/agent/issue_run_graph.py`:

```python
@dataclass(frozen=True, slots=True)
class IssueLookupRunGraphDependencies:
    authorization: AuthorizationService
    candidates: IssueCandidateService
    store: QAGraphStorePort


def build_issue_lookup_run_graph(
    deps: IssueLookupRunGraphDependencies,
    *,
    checkpointer: Any | None = None,
) -> Any:
    builder = StateGraph(AgentState)

    async def scope(state: AgentState) -> AgentState:
        return await resolve_scope_node(
            state,
            authorization=deps.authorization,
            store=deps.store,
        )

    async def search(state: AgentState) -> AgentState:
        return await search_issues_node(
            state,
            candidates=deps.candidates,
            store=deps.store,
        )

    builder.add_node("resolve_scope", scope)
    builder.add_node("search_issues", search)
    builder.add_edge(START, "resolve_scope")
    builder.add_edge("resolve_scope", "search_issues")
    builder.add_edge("search_issues", END)
    return builder.compile() if checkpointer is None else builder.compile(checkpointer=checkpointer)
```

Do not add `build_issue_draft`, confirmation, or create nodes to this graph.

- [ ] **Step 4: Prove WS3 projection recognizes lookup result**

Extend `tests/unit/workers/test_run_graph.py`:

```python
@pytest.mark.asyncio
async def test_issue_lookup_projects_candidate_artifact_as_success():
    run = make_run(business_mode=RunBusinessMode.ISSUE_LOOKUP)
    graph = RecordingGraph({"issue_candidate_id": "candidate:1", "route": "issue_candidates"})
    executor = LangGraphRunExecutor({RunBusinessMode.ISSUE_LOOKUP: graph})

    outcome = await executor.execute(run)

    assert outcome.kind is RunGraphOutcomeKind.SUCCEEDED
    assert outcome.result_ref == "candidate:1"
```

No production change to `LangGraphRunExecutor` should be necessary for this test.

- [ ] **Step 5: GREEN + read-only regression**

```bash
python -m pytest \
  tests/unit/agent/test_issue_run_graph.py \
  tests/unit/workers/test_run_graph.py \
  tests/e2e/test_issue_candidates.py \
  -v
ruff check src tests
mypy src
git diff --check
```

- [ ] **Step 6: Commit Task 3**

```bash
git add \
  src/project_agent/agent/issue_run_graph.py \
  tests/unit/agent/test_issue_run_graph.py \
  tests/unit/workers/test_run_graph.py
git diff --cached --check
git commit -m "feat: add read-only issue lookup run graph"
```

**Task 3 end judgment:**

```text
需求完成：✅ only if lookup is authorized and has zero Issue write-side effects
测试闭环：✅ only with graph + candidate + WS3 projection GREEN
新 bug：未发现 / 已发现：...
```

---

## Task 4: `issue_create` Run Graph — Evidence Before Draft, Real Interrupt After Draft

**Files:**
- Modify: `src/project_agent/agent/issue_run_graph.py`
- Modify: `tests/unit/agent/test_issue_run_graph.py`
- Reuse Task 13 unchanged: `src/project_agent/agent/nodes/confirm_issue_create.py`
- Reuse Task 13 unchanged: `src/project_agent/agent/nodes/execute_issue_create.py`
- Reuse Task 13 unchanged: `src/project_agent/application/services/issue_creation.py`

**Interfaces:**
- Consumes Task 1 evidence node and Task 2 draft binding.
- Produces:
  - `IssueCreateRunGraphDependencies(...)`
  - `build_issue_create_run_graph(deps, *, checkpointer=None)`
- Required order:

```text
resolve_scope
→ retrieve_issue_evidence
→ [EVIDENCE_REQUIRED => END/refusal]
→ search_issues
→ build_issue_draft
→ confirm_issue_create / LangGraph interrupt
→ [cancel => END | confirm => execute_issue_create]
→ END
```

- [ ] **Step 1: Write RED no-evidence test**

Use a tracker seeded with a strong historical candidate but no qualifying requirement/test evidence. Assert:

```python
result = await graph.ainvoke(initial_state, config)
assert result["route"] == "refusal"
assert result["last_error_code"] == "EVIDENCE_REQUIRED"
assert workflow_repo.drafts == {}
assert workflow_repo.confirmations == {}
assert tracker.create_side_effect_count == 0
```

This proves historical candidates cannot substitute for requirement/test Evidence.

- [ ] **Step 2: Write RED successful interrupt test**

Seed one governed requirement/test chunk and one same-project historical issue. Compile with a LangGraph checkpointer suitable for the unit test. Assert execution returns exactly one interrupt and its value contains:

```text
request_payload_hash
request_id
draft_id
evidence_ids
possible_duplicates
```

Then inspect the draft:

```python
assert draft.evidence_ids
assert set(interrupt.value["evidence_ids"]) == set(draft.evidence_ids)
assert tracker.create_side_effect_count == 0
```

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/unit/agent/test_issue_run_graph.py -v
```

Expected: lookup tests remain GREEN; create graph tests FAIL because the WS5 create graph does not exist.

- [ ] **Step 4: Implement create graph with explicit evidence routing**

Add:

```python
@dataclass(frozen=True, slots=True)
class IssueCreateRunGraphDependencies:
    authorization: AuthorizationService
    evidence_selector: IssueEvidenceSelector
    knowledge: KnowledgeRetrievalPort
    access_policy: ProjectAccessPolicy
    evidence_governance: EvidenceGovernanceService
    candidates: IssueCandidateService
    drafts: IssueDraftService
    confirmations: IssueConfirmationService
    creation: IssueCreationService
    store: QAGraphStorePort
```

Routing helper:

```python
def _after_issue_evidence(state: AgentState) -> str:
    return "search_issues" if state.get("route") == "issue_evidence_ready" else "refusal"
```

Build the exact node order shown in the Task interface. On evidence refusal, route directly to `END`; do not call `search_issues`, `build_issue_draft`, or `confirm_issue_create`.

Reuse Task 13 `_after_confirmation` behavior or reproduce its narrow routing logic without changing confirmation/write rules.

- [ ] **Step 5: Verify Task 13 payload-bound resume behavior still passes**

```bash
python -m pytest \
  tests/unit/agent/test_issue_run_graph.py \
  tests/unit/issues/test_interrupt_node.py \
  tests/unit/issues/test_confirmation.py \
  tests/unit/issues/test_idempotent_create.py \
  tests/security/test_cancelled_issue_create.py \
  tests/security/test_unconfirmed_issue_create.py \
  tests/security/test_issue_permission_recheck.py \
  tests/reliability/test_issue_response_lost.py \
  tests/e2e/test_issue_create_interrupt.py \
  -v
```

Expected: all GREEN. No Task 13 safety test may be weakened or deleted.

- [ ] **Step 6: Static/regression gate**

```bash
ruff check src tests
mypy src
git diff --check
```

- [ ] **Step 7: Commit Task 4**

```bash
git add \
  src/project_agent/agent/issue_run_graph.py \
  tests/unit/agent/test_issue_run_graph.py
git diff --cached --check
git commit -m "feat: add evidence-gated issue create run graph"
```

**Task 4 end judgment:**

```text
需求完成：✅ only if EVIDENCE_REQUIRED happens before draft and successful path reaches a real LangGraph interrupt
测试闭环：✅ only if Task13 security/idempotency/reconciliation tests remain GREEN
新 bug：未发现 / 已发现：...
```

---

## Task 5: WS5 Concrete Issue Runtime Composition Through Frozen WS3 Injection Point

**Files:**
- Create: `src/project_agent/runtime/issue.py`
- Create: `tests/unit/runtime/test_issue_runtime.py`
- Modify narrowly: `src/project_agent/runtime/worker.py`
- Modify narrowly: `tests/unit/runtime/test_worker_runtime.py`
- Reuse unchanged: `src/project_agent/workers/run_graph.py`
- Reuse unchanged: `src/project_agent/workers/run_execution.py`
- Reuse unchanged: `src/project_agent/application/services/run_execution.py`

**Interfaces:**
- Consumes: `build_worker_runtime(settings, *, graph_executor_factory=...)` exactly as frozen by WS3.
- Produces:
  - `ProductionIssueRunGraphExecutor(settings, checkpointer, *, knowledge=None)` implementing `RunGraphExecutor` for only `ISSUE_LOOKUP` and `ISSUE_CREATE`.
  - `build_issue_graph_executor_factory(settings, *, knowledge=None) -> Callable[[object], RunGraphExecutor]`.
  - optional async resource cleanup via `ProductionIssueRunGraphExecutor.aclose()`.
- Does **not** register QA or depend on WS4. A later integration branch may combine WS4/WS5 mappings without changing either business graph.

- [ ] **Step 1: Write RED runtime-construction tests**

`tests/unit/runtime/test_issue_runtime.py` must prove:

```text
ISSUE_LOOKUP builds the lookup Run graph
ISSUE_CREATE builds the create Run graph
QA raises visible RunGraphUnavailable in the isolated WS5 factory
one session transaction wraps each graph invocation
successful/interrupt graph invocation commits graph business state
exception rolls back graph business state
injected FakeKnowledgePort avoids HTTP/RAGFlow in offline tests
aclose closes owned HTTP client/engine when production knowledge is owned
```

Also extend `tests/unit/runtime/test_worker_runtime.py` with one test proving `build_worker_runtime` invokes an injected executor's optional `aclose()` on context exit while the existing FakeRunGraphExecutor without `aclose()` still works unchanged.

- [ ] **Step 2: Run RED**

```bash
python -m pytest \
  tests/unit/runtime/test_issue_runtime.py \
  tests/unit/runtime/test_worker_runtime.py \
  -v
```

Expected: FAIL because concrete WS5 runtime composition does not exist and Worker does not yet close optional graph resources.

- [ ] **Step 3: Implement production Issue executor without changing WS3 execute/resume semantics**

Core structure for `src/project_agent/runtime/issue.py`:

```python
class ProductionIssueRunGraphExecutor(RunGraphExecutor):
    def __init__(
        self,
        settings: Settings,
        checkpointer: object,
        *,
        knowledge: KnowledgeRetrievalPort | None = None,
    ) -> None:
        self._settings = settings
        self._checkpointer = checkpointer
        self._engine = create_engine(settings.database_url)
        self._session_factory = create_session_factory(self._engine)
        self._queue = PostgresJobQueue(
            self._session_factory,
            lease_seconds=settings.worker_lease_seconds,
            retry_base_seconds=settings.worker_retry_base_seconds,
            retry_max_seconds=settings.worker_retry_max_seconds,
        )
        self._http: httpx.AsyncClient | None = None
        if knowledge is None:
            self._http = httpx.AsyncClient(
                base_url=settings.ragflow_base_url,
                timeout=settings.ragflow_request_timeout_seconds,
            )
            object_store = LocalFileObjectStoreAdapter(settings.local_storage_root)
            self._knowledge = RagflowAdapter.from_http_client(
                self._http,
                api_key=settings.ragflow_api_key.get_secret_value(),
                object_store=object_store,
                embedding_model=settings.ragflow_embedding_model,
                chunk_method=settings.ragflow_chunk_method,
                retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
            )
        else:
            self._knowledge = knowledge
```

For every `execute` / `resume`, open a fresh SQLAlchemy session, construct **current** DB-backed authorization/evidence/issue services, compile only the requested Issue graph with the shared PostgreSQL checkpointer, delegate execution/projection to the already-frozen `LangGraphRunExecutor`, then commit or roll back the graph-business session.

Dependency construction inside one invocation must use:

```text
SqlAlchemyProjectAuthorizationRepository(session)
AuthorizationService(...)
SqlAlchemyEvidenceGovernanceRepository(session)
EvidenceGovernanceService(...)
IssueEvidenceSelector(...)
SqlAlchemyQAGraphStore(session)
SandboxProjectTrackerAdapter(session)
IdentifierExtractor()
IssueCandidateService(...)
SqlAlchemyIssueWorkflowRepository(session)
IssueDraftService(...)
IssueConfirmationService(..., ttl=timedelta(seconds=settings.tool_confirmation_ttl_seconds))
PostgresIdempotencyStore(self._session_factory)
IssueCreationService(..., job_queue=self._queue)
ProjectAccessPolicy()
```

Dispatch must be explicit:

```python
if run.business_mode is RunBusinessMode.ISSUE_LOOKUP:
    graph = build_issue_lookup_run_graph(..., checkpointer=self._checkpointer)
elif run.business_mode is RunBusinessMode.ISSUE_CREATE:
    graph = build_issue_create_run_graph(..., checkpointer=self._checkpointer)
else:
    raise RunGraphUnavailable(run.business_mode.value)
```

Then use the existing adapter rather than reimplementing WS3 state/resume projection:

```python
delegate = LangGraphRunExecutor({run.business_mode: graph})
return await delegate.execute(run)
# or
return await delegate.resume(run, resume_payload)
```

`aclose()`:

```python
async def aclose(self) -> None:
    if self._http is not None:
        await self._http.aclose()
    await self._engine.dispose()
```

Factory:

```python
def build_issue_graph_executor_factory(
    settings: Settings,
    *,
    knowledge: KnowledgeRetrievalPort | None = None,
):
    def factory(checkpointer: object) -> RunGraphExecutor:
        return ProductionIssueRunGraphExecutor(
            settings,
            checkpointer,
            knowledge=knowledge,
        )
    return factory
```

- [ ] **Step 4: Add only resource cleanup to `build_worker_runtime`**

Preserve this exact public call contract:

```python
build_worker_runtime(settings, *, graph_executor_factory=..., retention_repository=None)
```

Do not modify handler registration, queue semantics, Run state transitions, or retry behavior. In the existing runtime `finally`, after `worker.stop()`, call `aclose()` only when present:

```python
close = getattr(graph_executor, "aclose", None)
if callable(close):
    await close()
```

If MyPy requires a small local protocol/helper, keep it private to `runtime/worker.py`; do not change `RunGraphExecutor` to require cleanup from all existing fakes/implementations.

- [ ] **Step 5: GREEN + WS3 contract regression**

```bash
python -m pytest \
  tests/unit/runtime/test_issue_runtime.py \
  tests/unit/runtime/test_worker_runtime.py \
  tests/unit/workers/test_run_graph.py \
  tests/unit/workers/test_run_execution.py \
  tests/unit/runtime/test_run_execution_service.py \
  -v
ruff check src tests
mypy src
git diff --check
```

Expected: GREEN; existing WS3 tests require no behavior rewrite.

- [ ] **Step 6: Commit Task 5**

```bash
git add \
  src/project_agent/runtime/issue.py \
  src/project_agent/runtime/worker.py \
  tests/unit/runtime/test_issue_runtime.py \
  tests/unit/runtime/test_worker_runtime.py
git diff --cached --check
git commit -m "feat: wire WS5 issue graphs into worker runtime"
```

**Task 5 end judgment:**

```text
需求完成：✅ only if the frozen WS3 graph-factory API is preserved and both Issue business modes resolve concrete graphs
测试闭环：✅ only if all WS3 execution/runtime tests stay GREEN
新 bug：未发现 / 已发现：...
```

---

## Task 6: Live WS5 Acceptance — PostgreSQL Run/Worker/Interrupt/Resume + Real RAGFlow Evidence

**Files:**
- Create: `tests/integration/issues/test_issue_run_runtime_postgres.py`
- Create: `tests/integration/issues/test_issue_evidence_ragflow.py`
- Modify only if required for documented completion evidence: `docs/superpowers/plans/2026-09-18-ws5-unified-issue-runtime-evidence-completed.md`
- Do not create migrations.

**Interfaces:**
- Consumes all Tasks 1–5.
- Produces reproducible evidence for the WS5 acceptance boundary:
  - lookup read-only;
  - create freezes evidence/candidates/draft and reaches `WAITING_CONFIRMATION`;
  - restart-safe `/resume` continues the same checkpointer thread;
  - one authorized confirmation creates exactly one Sandbox Issue;
  - invalid/no evidence path creates zero drafts/issues;
  - real RAGFlow retrieval returns only eligible project requirement/test evidence;
  - no LLM is invoked.

### Task 6A — Real PostgreSQL end-to-end with deterministic injected Knowledge port

- [ ] **Step 1: Write RED live PostgreSQL issue lookup gate**

Seed:

```text
Client + Project A + active developer membership
Project A active knowledge-space row
Project A published/current REQUIREMENT_BASELINE DocumentVersion
Project A active SandboxProject
one existing same-project SandboxIssue candidate
```

Create the Run through the real FastAPI `POST /api/v1/runs` route with `business_mode="issue_lookup"`, then consume the queued job through real `build_worker_runtime` with the WS5 graph factory and `FakeKnowledgePort` injection.

Assertions:

```text
Run -> SUCCEEDED
RUN_QUEUED -> RUN_STARTED -> RUN_SUCCEEDED present
result_ref points to ISSUE_CANDIDATES artifact
candidate belongs to Project A
IssueDraft count for run == 0
ToolConfirmation count for run == 0
SandboxIssue count unchanged
```

- [ ] **Step 2: Write RED live PostgreSQL issue-create/no-evidence gate**

Use `business_mode="issue_create"` but seed no eligible requirement/test source (or seed only approved_design). Worker execution must produce:

```text
RunStatus.REFUSED
RUN_REFUSED payload.summary == "EVIDENCE_REQUIRED"
IssueDraft count == 0
ToolConfirmation count == 0
SandboxIssue count unchanged
```

- [ ] **Step 3: Write RED live PostgreSQL interrupt/resume gate**

Seed a qualifying requirement/test version and configure the injected `FakeKnowledgePort` to return a matching `KnowledgeChunk` whose project code, document version ID, and knowledge-space ID are all authorized.

Flow:

```text
POST /api/v1/runs issue_create
→ Worker process/runtime instance #1 run_once()
→ Run == WAITING_CONFIRMATION
→ WAITING_CONFIRMATION event contains evidence_ids + possible_duplicates + request_payload_hash
→ corresponding IssueDraft.evidence_ids_json contains the same frozen snapshot IDs
→ dispose Worker runtime #1
→ POST /api/v1/runs/{run_id}/resume with action=confirm and exact request_payload_hash
→ create Worker runtime #2 with same DATABASE_URL/checkpointer
→ run_once()
→ same LangGraph thread resumes
→ Run == SUCCEEDED
→ exactly one SandboxIssue with client_request_id == draft.id
→ exactly one completed idempotency record for namespace sandbox_issue_create/request_id=draft.id
```

This test must recreate the Worker/checkpointer context between interrupt and resume so it proves process-boundary durability instead of in-memory continuation.

- [ ] **Step 4: Run PostgreSQL RED**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
python -m pytest tests/integration/issues/test_issue_run_runtime_postgres.py -v -rs
```

Expected initially: FAIL because the full WS5 live gate is new. After Tasks 1–5 are implemented, GREEN with zero skips.

### Task 6B — Real RAGFlow requirement/test retrieval gate, no LLM

- [ ] **Step 5: Write RED real RAGFlow gate**

Follow the resource lifecycle pattern already used by `tests/integration/ragflow/test_project_isolation.py`:

```text
RUN_RAGFLOW_INTEGRATION=1 required
create unique Project A / Project B RAGFlow spaces
upload one Project A requirement/test token document
upload one Project A non-WS5 category control document
upload one Project B requirement/test isolation-control document
wait until provider parsing succeeds
run the WS5 evidence retrieval path for Project A
assert frozen evidence contains only Project A allowed requirement/test document-version IDs
assert Project A non-WS5 category and Project B evidence are absent
cleanup provider documents in finally
```

The test must use real RAGFlow but no Structured LLM and no answer generation.

- [ ] **Step 6: Run real RAGFlow gate**

```bash
export RUN_RAGFLOW_INTEGRATION=1
python -m pytest tests/integration/issues/test_issue_evidence_ragflow.py -v -rs
```

Expected: PASS with zero selected-test skips. If the real RAGFlow environment is unavailable, WS5 cannot be marked fully COMPLETE; report `测试闭环：⚠️` and the exact external precondition instead of substituting a fake pass.

### Task 6C — Full WS5 regression and completion evidence

- [ ] **Step 7: Run all WS5 targeted tests with live PostgreSQL enabled**

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'

python -m pytest \
  tests/unit/issues/test_issue_evidence.py \
  tests/unit/issues/test_issue_draft.py \
  tests/unit/issues/test_confirmation.py \
  tests/unit/agent/test_issue_run_graph.py \
  tests/unit/runtime/test_issue_runtime.py \
  tests/unit/workers/test_run_graph.py \
  tests/security/test_evidence_postfilter.py \
  tests/security/test_cancelled_issue_create.py \
  tests/security/test_unconfirmed_issue_create.py \
  tests/security/test_issue_permission_recheck.py \
  tests/reliability/test_issue_response_lost.py \
  tests/e2e/test_issue_candidates.py \
  tests/e2e/test_issue_create_interrupt.py \
  tests/integration/issues/test_postgres_issue_workflow.py \
  tests/integration/issues/test_issue_run_runtime_postgres.py \
  tests/integration/workers/test_run_worker_postgres.py \
  tests/integration/workers/test_run_resume_postgres.py \
  -v -rs
```

Expected: all selected tests PASS; zero PostgreSQL selected-test skips.

- [ ] **Step 8: Run final non-mutating static gate**

```bash
ruff check src tests
mypy src
git diff --check
```

Expected: all PASS.

- [ ] **Step 9: Run full offline regression**

Disable live-only flags for the ordinary suite and capture exact counts:

```bash
unset RUN_POSTGRES_INTEGRATION
unset RUN_RAGFLOW_INTEGRATION
python -m pytest -q -rs
```

Expected: no failures. Live tests may skip here; those skips are acceptable only because Steps 7 and 6 separately captured their required live passes.

- [ ] **Step 10: Re-run required real RAGFlow gate separately**

```bash
export RUN_RAGFLOW_INTEGRATION=1
python -m pytest tests/integration/issues/test_issue_evidence_ragflow.py -v -rs
```

Expected: PASS, zero selected-test skips.

- [ ] **Step 11: Prove no schema drift / no accidental migration**

```bash
alembic current
alembic heads
git diff --name-only ba1f9b3...HEAD -- migrations
```

Expected:

```text
current/head: 0005_run_runtime_envelope
no WS5 migration files
```

- [ ] **Step 12: Scope/secret audit**

```bash
git status --short
git diff --stat ba1f9b3...HEAD
git diff --check ba1f9b3...HEAD

git diff --name-only ba1f9b3...HEAD | grep -E '(^|/)(\.env|.*\.zip|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache)' && exit 1 || true

git diff ba1f9b3...HEAD -- \
  src/project_agent/application/services/run_execution.py \
  src/project_agent/workers/run_execution.py \
  src/project_agent/workers/main.py
```

Expected: no secrets/temp artifacts; the three frozen WS3 semantic files have no WS5 diff.

- [ ] **Step 13: Write the WS5 completion record from fresh command output**

Only after all required gates are GREEN, create:

`docs/superpowers/plans/2026-09-18-ws5-unified-issue-runtime-evidence-completed.md`

It must record:

```text
branch and final local HEAD
starting baseline ba1f9b3
modified/created files
schema head 0005
exact targeted counts
exact full offline counts
exact live PostgreSQL counts
exact live RAGFlow count
confirmation that no LLM gate was required for WS5
confirmation that no WS4 branch was merged
confirmation that Issue lookup produced zero Issue write-side effects
confirmation that no-evidence Issue create produced zero draft/write side effects
confirmation that interrupt payload evidence_ids == persisted draft EvidenceSnapshot IDs
confirmation that restart/resume produced exactly one Sandbox Issue
```

No `COMPLETE` language if any required live gate is skipped.

- [ ] **Step 14: Commit Task 6 / WS5 close-out**

```bash
git add \
  tests/integration/issues/test_issue_run_runtime_postgres.py \
  tests/integration/issues/test_issue_evidence_ragflow.py \
  docs/superpowers/plans/2026-09-18-ws5-unified-issue-runtime-evidence-completed.md
git diff --cached --check
git diff --cached --stat
git commit -m "test: close WS5 issue runtime evidence chain"
```

Do not use `finishing-a-development-branch` until this commit exists and every required WS5 gate above is freshly GREEN.

**Task 6 end judgment:**

```text
需求完成：✅ only if both WS5 business modes satisfy the acceptance boundary
测试闭环：✅ only if PostgreSQL + real RAGFlow + offline regression are all fresh GREEN
新 bug：未发现 / 已发现：...
```

---

# Required TDD / Debugging Skill Transitions During Execution

At the start of each implementation task:

```text
是否需要使用 Superpowers：是
使用 skill：test-driven-development
原因：当前 Task 是 feature implementation，必须先得到预期 RED 再写最小 GREEN。
```

If any RED fails for an unrelated reason, any previously-green test regresses, or live behavior differs from the expected contract:

```text
是否需要使用 Superpowers：是
使用 skill：systematic-debugging
原因：出现测试失败/行为异常，先定位 root cause，不允许猜修或顺带重构。
```

Before any Task/WS5 completion claim:

```text
是否需要使用 Superpowers：是
使用 skill：verification-before-completion
原因：必须用 fresh command output 证明 targeted/static/live/regression gates。
```

Only after all Task 6 live/offline gates are GREEN and the WS5 branch is clean:

```text
是否需要使用 Superpowers：是
使用 skill：finishing-a-development-branch
原因：整个 WS5 branch 才具备集成/交付资格。
```

---

# WS5 Acceptance Matrix

| Requirement | Primary proof |
|---|---|
| `issue_lookup` Run dispatch | `test_issue_run_graph.py` + live PostgreSQL lookup gate |
| Lookup read-only | no IssueDraft/Confirmation/SandboxIssue rows in live lookup gate |
| Current authorization before Issue business work | `resolve_scope` first node + auth/security regression |
| Requirement/test-only retrieval | `test_issue_evidence.py` preselection assertions |
| Cross-project Evidence denied | access-policy test + WS5 selector/node test + real RAGFlow isolation control |
| Published/current/effective only | selector RED/GREEN + existing governance regression |
| Frozen EvidenceSnapshot IDs | QAGraph store governed-bundle persistence + live DB assertions |
| Draft carries evidence IDs | Task 2 unit + PostgreSQL round-trip |
| Confirmation displays evidence IDs | Task 2 confirmation test + WAITING event payload |
| No evidence => `EVIDENCE_REQUIRED` before draft | Task 4 unit + Task 6 live negative gate |
| Historical candidates are advisory | Task 12 regression + no-evidence candidate control |
| Real interrupt => `WAITING_CONFIRMATION` | Task 4 graph test + Task 6 live Run/Event assertions |
| Resume uses same checkpoint thread | existing WS3 resume tests + Task 6 runtime restart gate |
| Permission re-check preserved | `test_issue_permission_recheck.py` |
| Payload-bound confirmation preserved | `test_confirmation.py`, resume API tests |
| Idempotent single Sandbox write | `test_idempotent_create.py`, response-lost test, Task 6 exact row count |
| Reconciliation preserved | `test_issue_response_lost.py` + existing reconciliation handler path |
| No WS4 answer-generation dependency | import/diff audit; WS5 gates run without Structured LLM |
| Schema unchanged | Alembic current/heads `0005`; no migration diff |
| WS3 semantics unchanged | no diff in run execution/worker semantics + WS3 regression GREEN |

---

# Explicit WS6+ Exclusions

Do not implement any of the following while executing this Plan:

```text
WS6: structlog JSON configuration, Prometheus endpoint/metrics, new cost/telemetry policy
WS7: Docker/Compose API+Worker production closure, deployment scripts, health orchestration
WS8: evaluation runner, datasets/metrics/ablations/report generation
production Jira/禅道/飞书 writes
new SaaS/multi-tenant architecture
Redis/Celery/MinIO/Kubernetes
second vector database
new multi-agent orchestration
unified LangGraph rewrite
automatic duplicate decision
new Requirement/Test domain tables
WS4 Structured LLM / answer generation / QA retrieval grading
```

The existing retrieval-round counter may be incremented by WS5 because it already exists in the frozen runtime; do not add WS6 observability surfaces around it.

---

# Plan Self-Review

## Spec Coverage

- V1 Design §12.1 requirement/test Evidence before creation -> Tasks 1, 2, 4, 6.
- §12.2 read-only issue lookup -> Tasks 3, 5, 6.
- §12.3 Issue create/HITL order -> Tasks 2, 4, 5, 6.
- WS5 responsibility: both Run dispatch modes -> Tasks 3–6.
- frozen EvidenceSnapshot IDs -> Tasks 1, 2, 6.
- `IssueDraft.evidence_ids` -> Task 2.
- existing Issue Graph integration with Run status/events -> Tasks 4–6.
- real interrupt/resume through WS2/WS3 -> Tasks 5–6.
- Task 13 permission/idempotency/reconciliation preservation -> Tasks 2, 4, 6 regression gates.
- no WS4 answer-generation dependency -> Global Constraints + Tasks 5–6.

No approved WS5 requirement is intentionally deferred to WS6+.

## Placeholder Scan

No placeholder directives or unspecified implementation/error-handling steps remain. External live availability is treated as an acceptance precondition, not as permission to claim a skipped gate passed.

## Type / Naming Consistency

The Plan uses the following names consistently across tasks:

```text
IssueEvidenceSelector
retrieve_issue_evidence_node
IssueLookupRunGraphDependencies
IssueCreateRunGraphDependencies
build_issue_lookup_run_graph
build_issue_create_run_graph
ProductionIssueRunGraphExecutor
build_issue_graph_executor_factory
EVIDENCE_REQUIRED
issue_evidence_ready
```

If implementation discovers that an existing exact type signature differs from this reviewed ZIP snapshot, stop before renaming interfaces and report the source-of-truth difference; do not silently adapt frozen contracts.

---

# Execution Handoff

Plan execution starts only after this plan is copied into the real WS5 worktree and its Git diff is reviewed. Recommended execution mode is **Subagent-Driven** with a fresh implementation/review cycle per Task; **Inline Execution** with `superpowers:executing-plans` is also valid.

Before Task 1, first run the **Pre-Implementation Real PostgreSQL Baseline** above. Then execute Tasks 1 -> 6 strictly in order; each task must end with its three required judgments and a commit boundary before the next task begins.
