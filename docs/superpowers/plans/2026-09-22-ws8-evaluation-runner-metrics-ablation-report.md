# WS8 Evaluation Runner + Collector + Metrics + Ablation + Report Implementation Plan

> **For agentic workers:** REQUIRED WORKFLOW: execute this plan task-by-task with TDD. Each Task is completed only after `RED -> root cause -> minimal fix -> GREEN -> regression -> Ruff -> MyPy -> git diff --check -> review -> commit`. Do not batch multiple Tasks into one implementation commit.

**Date:** 2026-09-22  
**Workstream:** WS8 — Evaluation Runner + Collector + Metrics + Ablation + Report  
**Branch:** `feat/ws8`  
**Frozen base:** `8eba69cb94bcaec4cba1eecdf2f5a0f448daa6f3`  
**Design:** `docs/superpowers/specs/2026-09-22-ws8-evaluation-design.md`  
**Benchmark:** WS8 Synthetic Evaluation Benchmark V0 — B7 Frozen  
**Benchmark freeze decision:** `PASS_READY_FOR_WS8_IMPLEMENTATION`  
**Metric definition:** `v1`

---

## Goal

Close the V1 evaluation loop without reopening WS1–WS7 and without changing the frozen B7 benchmark:

```text
B7 Frozen Benchmark V0
        ↓
Deterministic evaluation fixture materialization
        ↓
Existing FastAPI Run API + PostgreSQL queue + independent Worker
        ↓
Existing QA / Issue production runtime
        ↓
Raw per-trial artifact collection
        ↓
Pure deterministic v1 scoring
        ↓
Deterministic baseline report
        ↓
Safety-safe ablations
        ↓
Final reproducible Synthetic V0 evaluation report
```

The implementation must measure the system as it exists. It must not alter Gold, corpus facts, or security semantics merely to manufacture passing product metrics.

---

## Planning Basis

This plan is derived from:

1. current source at WS8 base HEAD `8eba69cb94bcaec4cba1eecdf2f5a0f448daa6f3`;
2. frozen WS8 Evaluation Design;
3. B7 Frozen Benchmark V0;
4. existing WS1–WS7 production runtime and tests.

The B7 handoff freezes:

- 50 question cases;
- 22 corpus documents;
- 50 Gold records;
- 47 `SCORABLE` cases;
- 3 `UNSCORABLE_RUNTIME_SCOPE` cases;
- 15 P0 cases;
- nine metric definitions/populations;
- identities, memberships, Sandbox Issue fixtures, setup scenarios, and fault scenarios;
- corpus, fixture, question-catalog, schema, and Gold hashes.

The three runtime-scope findings remain exactly:

```text
Q014 — FUZZY_IDENTIFIER_NOT_COMPOSED
Q046 — COMPANY_PUBLIC_SCOPE_UNSUPPORTED
Q049 — ISSUE_KEY_EXACT_LOOKUP_UNSUPPORTED
```

This plan does **not** fix them. Runner/report code must surface them as `UNSCORABLE_RUNTIME_SCOPE`.

---

## B7 Frozen Integrity Values

The implementation must preserve these B7 values when the frozen package is integrated:

```text
dataset_version                v0
data_provenance                synthetic
corpus_version                 v0
gold_schema_version            gold-v1
metric_definition_version      v1

question_catalog_sha256
c79eb4c30395308216d271fb3f632f5ba1256ab452c15145943ddf021d1d94e5

corpus_manifest_sha256
c899de928f2c48d9ef27abb3a0e5cebee8ee1aeca97e03b35e7c062a70aa1512

corpus_sha256
e880c250b570f9419528b8958cec21c7a239e7394e0c8cc3d54aad1688cc9521

fixtures_sha256
30af875821a8bf4f0bec8f2721276d7f6d05683359dcd3cbd2d958f756d0e41e

gold_manifest_schema_sha256
4d37d43936a35d1a1f11a45a9df834d6432cc268e678abcefbfbdb74d0b8f0bb

gold_manifest_sha256
05e6962b927762dc85cb8f5217cf8d8970cab98b2214b92cb27aff3b3bc388b1
```

If any copied frozen byte changes, stop. Do not regenerate or “repair” B7 inside this workstream.

---

## Global Constraints

- WS1–WS7 are FINAL COMPLETE.
- Do not re-plan, re-debug, or re-implement already closed WS1–WS7 work unless a new WS8 RED proves a regression.
- Do not modify the frozen question catalog, corpus facts, Gold, fixtures, schema, or B7 freeze decision.
- Do not fix Q014, Q046, or Q049 in WS8.
- Preserve JWT identity and PostgreSQL membership authorization.
- Preserve explicit `project_id` Run creation.
- Preserve cross-project isolation in Registry, RAGFlow, Evidence, Citation, Issue lookup, and writes.
- Preserve `PUBLISHED`/current Evidence governance.
- Preserve top-10 bounded retrieval and at most one second QA retrieval in the production baseline.
- Preserve deterministic Citation Guard.
- Preserve explicit payload-bound confirmation.
- Preserve viewer write denial.
- Preserve idempotency and response-loss reconciliation.
- Preserve `WAITING_CONFIRMATION` as non-terminal.
- Preserve WS6 prompt/model/token/retrieval telemetry.
- Preserve WS7 API/Worker process separation for canonical baseline execution.
- Do not add Redis, Celery, ARQ, MinIO, Kubernetes, another vector DB, or another RAG stack.
- Do not add an LLM judge as a V0 acceptance dependency.
- Do not add a production database migration unless a Task RED proves that the frozen requirement cannot be met with existing schema/JSON metadata.
- Prefer standard library + existing project dependencies. A new dependency requires an explicit plan amendment and RED evidence.
- Evaluation code may observe production persistence directly but production business code must not import `project_agent.evaluation`.
- Evaluation fixture preparation may seed evaluation-owned state directly because it is setup support code; measured normal business execution still uses the real Runtime Envelope.
- Evaluation cleanup may delete/reset **only** evaluation-owned rows/datasets identified by deterministic WS8 namespaces.
- A product metric FAIL is not an implementation failure. A missing case, hidden skip, invalid raw artifact, scorer failure, or non-reproducible report is an implementation failure.
- Each Task receives exactly one final implementation commit. Documentation freeze commits are not Task commits.

---

## Frozen Metric Populations

The B7 Gold already freezes the V0 applicability population:

```text
exact_identifier_hit_at_10       14
evidence_recall_at_10             27
current_version_hit_rate           7
citation_id_validity              25
no_answer_refusal_accuracy         3
cross_project_evidence              9
unconfirmed_issue_creation          5
duplicate_issue_side_effects        2
critical_regression                15
```

Current-Version Hit Rate population is exactly:

```text
Q009 Q010 Q011 Q025 Q026 Q042 Q047
```

Do not re-add Q012 or Q041.

---

## Frozen Run Protocol Population

```text
single_run                      36
authorization_denial             5
setup_then_run                   3
waiting_confirmation_resume      1
same_request_replay              1
response_loss_reconcile          1
unscorable_runtime_scope         3
```

Runner implementation must support these protocol names exactly.

---

## Task Dependency Graph

```text
Task 0  Frozen B7 integration
   ↓
Task 1  Evaluation contracts + artifact IO
   ↓
Task 2  Fixture materialization + isolated runtime state
   ↓
Task 3  Collector + retrieval-round observability closure
   ↓
Task 4  Runtime Runner protocols
   ↓
Task 5  Deterministic Metrics v1
   ↓
Task 6  Deterministic Report + claim guard
   ↓
Task 7  Safety-safe Ablations
   ↓
Task 8  Full live evaluation gate + final regression
```

Tasks must be implemented in this order unless a real RED proves a dependency mistake.

---

# Frozen File Map

## Task 0 — B7 Integration

**Create/copy exact frozen bytes under:**

```text
evaluation/datasets/v0/B7_FREEZE_REVIEW.json
evaluation/datasets/v0/BENCHMARK_FREEZE_REVIEW.md
evaluation/datasets/v0/BENCHMARK_VALIDATION.md
evaluation/datasets/v0/FINAL_STATIC_VALIDATION.json
evaluation/datasets/v0/SHA256SUMS.txt
evaluation/datasets/v0/corpus-manifest.jsonl
evaluation/datasets/v0/dataset-manifest.json
evaluation/datasets/v0/gold-manifest.jsonl
evaluation/datasets/v0/gold-manifest.schema.json
evaluation/datasets/v0/fixtures/fault-scenarios.json
evaluation/datasets/v0/fixtures/identities.json
evaluation/datasets/v0/fixtures/memberships.json
evaluation/datasets/v0/fixtures/sandbox-issues.json
evaluation/datasets/v0/corpus/...
```

`README.md` and `question-catalog.csv` must become the exact B7 frozen bytes.

**Create:**

```text
tests/evaluation/__init__.py
tests/evaluation/test_benchmark_v0_contract.py
```

---

## Task 1 — Evaluation Contracts

**Create:**

```text
src/project_agent/evaluation/__init__.py
src/project_agent/evaluation/models.py
src/project_agent/evaluation/dataset.py
src/project_agent/evaluation/artifacts.py
tests/unit/evaluation/__init__.py
tests/unit/evaluation/test_dataset.py
tests/unit/evaluation/test_artifacts.py
```

**Modify:**

```text
.gitignore
```

---

## Task 2 — Fixture Materialization

**Create:**

```text
src/project_agent/evaluation/fixtures.py
src/project_agent/evaluation/auth.py
src/project_agent/cli/evaluation_prepare.py
tests/unit/evaluation/test_fixture_ids.py
tests/integration/evaluation/__init__.py
tests/integration/evaluation/test_fixture_preparation_postgres.py
tests/integration/evaluation/test_fixture_preparation_ragflow.py
docs/runbooks/ws8-evaluation-fixtures.md
```

**Modify:**

```text
pyproject.toml
```

---

## Task 3 — Collector

**Create:**

```text
src/project_agent/evaluation/collector.py
tests/unit/evaluation/test_collector.py
tests/integration/evaluation/test_collector_postgres.py
tests/security/test_evaluation_artifact_sanitization.py
```

**Modify only if RED requires retrieval-round persistence closure:**

```text
src/project_agent/application/ports/qa_graph.py
src/project_agent/agent/nodes/retrieve.py
src/project_agent/infrastructure/db/repositories/qa_graph.py
tests/unit/agent/test_retrieve_and_answer.py
tests/integration/agent/test_qa_runtime_postgres.py
```

No migration is planned.

---

## Task 4 — Runtime Runner

**Create:**

```text
src/project_agent/evaluation/client.py
src/project_agent/evaluation/scenarios.py
src/project_agent/evaluation/runner.py
src/project_agent/cli/evaluation.py
tests/unit/evaluation/test_client.py
tests/unit/evaluation/test_scenarios.py
tests/unit/evaluation/test_runner.py
tests/integration/evaluation/test_runner_api_postgres.py
```

**Modify:**

```text
pyproject.toml
```

---

## Task 5 — Metrics v1

**Create:**

```text
src/project_agent/evaluation/metrics.py
src/project_agent/evaluation/scoring.py
tests/unit/evaluation/test_metrics_identifier.py
tests/unit/evaluation/test_metrics_evidence.py
tests/unit/evaluation/test_metrics_citation.py
tests/unit/evaluation/test_metrics_refusal.py
tests/unit/evaluation/test_metrics_issue.py
tests/unit/evaluation/test_metrics_critical.py
tests/unit/evaluation/test_scoring.py
```

No production runtime file is planned.

---

## Task 6 — Report

**Create:**

```text
src/project_agent/evaluation/report.py
src/project_agent/evaluation/claims.py
tests/unit/evaluation/test_report.py
tests/unit/evaluation/test_claims.py
```

**Modify:**

```text
src/project_agent/cli/evaluation.py
```

---

## Task 7 — Ablations

**Create:**

```text
src/project_agent/evaluation/ablations.py
src/project_agent/evaluation/variants.py
tests/unit/evaluation/test_ablations.py
tests/unit/evaluation/test_variants.py
tests/integration/evaluation/test_ablation_runtime.py
```

**Minimal generic production composition seam may modify:**

```text
src/project_agent/agent/nodes/resolve_identifiers.py
src/project_agent/agent/nodes/identifier_node.py
src/project_agent/agent/graph.py
src/project_agent/runtime/qa.py
tests/unit/agent/test_qa_graph_wiring.py
tests/unit/runtime/test_qa_runtime.py
```

Only `no_exact_registry` and `single_round_only` may use the live variant seam.

`pre_governance_shadow` and `pre_guard_shadow` remain offline counterfactual analysis over baseline raw artifacts.

---

## Task 8 — Live Gate

**Create:**

```text
scripts/run_ws8_evaluation_gates.py
tests/integration/deployment/test_ws8_evaluation_runner.py
docs/runbooks/ws8-evaluation-live-gates.md
```

**Modify only if needed:**

```text
.gitignore
```

No base Compose topology change is planned.

---

# Review Focus

The final implementation review must explicitly answer these questions.

1. **Frozen benchmark integrity**
   - Are the B7 bytes unchanged?
   - Does runtime code ever rewrite Gold/corpus/fixtures?
   - Are Q014/Q046/Q049 preserved as runtime-scope unscorable?

2. **Runtime fidelity**
   - Do normal measured runs enter through `/api/v1/runs`?
   - Are jobs processed by the existing Worker/RunGraph runtime?
   - Is there any evaluation-only QA/Issue graph? There must not be.

3. **Isolation**
   - Can preparation/cleanup touch a non-evaluation project, issue, RAGFlow dataset, or document?
   - Are all evaluation-owned IDs/names deterministic and namespaced?

4. **Raw evidence**
   - Can every metric numerator/denominator be traced to a trial artifact?
   - Are retrieval rounds distinguishable deterministically?
   - Is `doc_code` mapping derived from frozen fixture mapping rather than text guessing?

5. **Safety**
   - Does any ablation disable ACL, membership, Evidence postfilter, confirmation, idempotency, or reconciliation? It must not.
   - Can any secret appear in artifacts? It must not.

6. **Scoring**
   - Are scorers pure?
   - Does any scorer call the application, RAGFlow, LLM, or live DB? It must not.
   - Are B7 metric populations respected exactly?

7. **Reporting**
   - Are Target and Measured distinct?
   - Are Synthetic V0 and real data distinguished?
   - Does a product FAIL remain a FAIL?
   - Does a pipeline gate ever treat an unscorable/infra failure as PASS? It must not.

---

# Task 0: Integrate the B7 Frozen Benchmark Without Re-authoring It

**Outcome:** The repository contains the exact B7 frozen V0 benchmark bytes, and a local contract test proves the frozen counts, hashes, and known runtime-scope findings before any Runner code exists.

**Files:**

- Copy exact B7 files listed in the Frozen File Map.
- Create `tests/evaluation/__init__.py`.
- Create `tests/evaluation/test_benchmark_v0_contract.py`.

**Implementation boundary:**

- No production source changes.
- No Gold edits.
- No corpus edits.
- No fixture edits.
- No question edits.
- Do not reconstruct B7 from earlier phases; copy the final B7 frozen bytes.
- `SHA256SUMS.txt` and `dataset-manifest.json` are the authority for frozen integrity.

### Step 1 — Write the B7-presence RED test

Create `tests/evaluation/test_benchmark_v0_contract.py`.

Required tests:

```python
def test_b7_frozen_artifacts_are_present() -> None: ...

def test_b7_sha256s_match_frozen_files() -> None: ...

def test_b7_manifest_has_expected_counts() -> None: ...

def test_b7_gold_has_exactly_q001_through_q050() -> None: ...

def test_b7_has_exactly_47_scorable_and_3_runtime_scope_unscorable() -> None: ...

def test_b7_runtime_scope_set_is_exactly_q014_q046_q049() -> None: ...

def test_b7_metric_populations_are_frozen() -> None: ...

def test_b7_p0_population_is_15() -> None: ...
```

The hash test must use Python `hashlib`; do not shell out from pytest.

### Step 2 — Run RED

```bash
uv run pytest -q tests/evaluation/test_benchmark_v0_contract.py
```

Expected: FAIL because the current WS8 base repository contains only the earlier `README.md` and `question-catalog.csv`, not the final B7 frozen handoff.

If it passes before copying B7, inspect the source of truth and stop if the branch has already changed.

### Step 3 — Copy the B7 frozen bytes exactly

Copy the contents of the B7 Frozen ZIP into:

```text
evaluation/datasets/v0/
```

Do not edit line endings, whitespace, JSON key order, Markdown, or corpus text.

### Step 4 — Verify frozen hashes outside pytest

Run:

```bash
cd evaluation/datasets/v0
sha256sum -c SHA256SUMS.txt
cd ../../..
```

Expected: every listed artifact reports `OK`.

Then verify the manifest-declared aggregate values with the test.

### Step 5 — Run GREEN

```bash
uv run pytest -q tests/evaluation/test_benchmark_v0_contract.py
```

Expected: zero failures.

### Step 6 — Task 0 regression/quality

```bash
uv run pytest -q \
  tests/evaluation/test_benchmark_v0_contract.py

uv run ruff check tests/evaluation
git diff --check
```

No MyPy source change is expected in Task 0.

### Step 7 — Review

Review only for:

- byte-for-byte B7 fidelity;
- no accidental historical B1–B6 draft file copied instead of final B7;
- no changed frozen hash;
- no “fix” to Q014/Q046/Q049.

### Step 8 — Commit

One commit only:

```bash
git add evaluation/datasets/v0 tests/evaluation
git commit -m "test(ws8): integrate frozen evaluation benchmark v0"
```

**Task 0 completion judgment:**

1. current requirement complete: B7 is in-repo and frozen;
2. test closure complete: hash/count/population contract GREEN;
3. new bug introduced: NO.

---

# Task 1: Add Evaluation Domain Contracts and Deterministic Artifact IO

**Outcome:** WS8 has typed, immutable evaluation models and deterministic artifact serialization, but still does not execute a Run.

**Files:**

- Create `src/project_agent/evaluation/__init__.py`.
- Create `src/project_agent/evaluation/models.py`.
- Create `src/project_agent/evaluation/dataset.py`.
- Create `src/project_agent/evaluation/artifacts.py`.
- Create `tests/unit/evaluation/__init__.py`.
- Create `tests/unit/evaluation/test_dataset.py`.
- Create `tests/unit/evaluation/test_artifacts.py`.
- Modify `.gitignore`.

**Public contract:**

At minimum define typed equivalents for:

```text
EvaluationCase
GoldRecord
GoldScoringStatus
RunProtocol
TrialClassification
EvaluationRunManifest
TrialArtifact
RetrievalRoundArtifact
EvidenceArtifact
CitationArtifact
IssueArtifact
MetricStatus
```

Required `TrialClassification` values:

```text
SCORED
UNSCORABLE_GOLD
UNSCORABLE_RUNTIME_SCOPE
INFRA_FAILURE
RUNNER_FAILURE
```

Required stable paths:

```text
evaluation/artifacts/<evaluation_run_id>/run-manifest.json
evaluation/artifacts/<evaluation_run_id>/fixture-state.json
evaluation/artifacts/<evaluation_run_id>/cases/<case_id>/trial-001.json
evaluation/artifacts/<evaluation_run_id>/metrics.json
evaluation/artifacts/<evaluation_run_id>/ablations/...
evaluation/artifacts/<evaluation_run_id>/report.json
evaluation/artifacts/<evaluation_run_id>/report.md
```

### Step 1 — Write loader RED tests

Required tests:

```python
def test_load_v0_returns_50_catalog_cases_and_50_gold_records() -> None: ...

def test_loader_joins_catalog_and_gold_by_case_id_only() -> None: ...

def test_loader_preserves_b7_scoring_status_and_reason() -> None: ...

def test_loader_preserves_metric_applicability_without_recomputing_it() -> None: ...

def test_loader_rejects_duplicate_case_ids() -> None: ...

def test_loader_rejects_unknown_gold_case() -> None: ...

def test_loader_resolves_doc_codes_only_from_corpus_manifest() -> None: ...
```

The loader must not infer Gold from question text.

### Step 2 — Write artifact RED tests

Required tests:

```python
def test_json_artifact_output_is_stable_and_sorted() -> None: ...

def test_trial_path_is_stable_for_case_and_trial_number() -> None: ...

def test_artifact_writer_rejects_secret_fields() -> None: ...

def test_artifact_writer_rejects_bearer_tokens_and_jwt_like_values() -> None: ...

def test_artifact_writer_does_not_serialize_secret_settings() -> None: ...

def test_same_payload_produces_same_sha256() -> None: ...
```

The writer may sanitize human-readable errors, but it must fail closed if structured payload keys such as `authorization`, `api_key`, `jwt`, `password`, or credential-bearing `database_url` are present.

### Step 3 — Run RED

```bash
uv run pytest -q \
  tests/unit/evaluation/test_dataset.py \
  tests/unit/evaluation/test_artifacts.py
```

Expected: import/module failures.

### Step 4 — Implement minimal typed contracts

Use frozen Pydantic models or dataclasses with explicit enum values.

Do not duplicate the entire JSON Schema engine. Parse only the fields needed by Runner/Collector/Scorers while preserving raw Gold payload where necessary for traceability.

`dataset.py` must expose a small API such as:

```python
class EvaluationDataset:
    ...

def load_evaluation_dataset(root: Path) -> EvaluationDataset: ...
```

The dataset object must expose:

- dataset/corpus/Gold/metric versions;
- cases sorted by case ID;
- `case_id -> GoldRecord`;
- `doc_code -> CorpusDocument`;
- B7 integrity metadata.

### Step 5 — Implement deterministic artifact IO

`artifacts.py` must:

- create stable directories;
- write UTF-8 JSON with deterministic key ordering;
- terminate text JSON with one newline;
- return SHA256 for written artifacts;
- support atomic replace (`tmp` + replace) to avoid half-written files;
- never serialize secrets;
- keep Markdown generation out of this module.

Add:

```text
evaluation/artifacts/
```

to `.gitignore`.

### Step 6 — Run GREEN

```bash
uv run pytest -q \
  tests/unit/evaluation/test_dataset.py \
  tests/unit/evaluation/test_artifacts.py
```

### Step 7 — Regression/quality

```bash
uv run pytest -q \
  tests/evaluation/test_benchmark_v0_contract.py \
  tests/unit/evaluation

uv run ruff check src/project_agent/evaluation tests/unit/evaluation
uv run mypy src
git diff --check
```

### Step 8 — Review

Review for:

- no scorer logic in loader;
- no runtime calls in models/artifacts;
- no hidden mutation of Gold;
- no secrets in serialized model reprs;
- stable sort/order behavior.

### Step 9 — Commit

```bash
git add \
  .gitignore \
  src/project_agent/evaluation \
  tests/unit/evaluation

git commit -m "feat(ws8): add evaluation contracts and artifacts"
```

**Task 1 completion judgment:**

1. current requirement complete: evaluation contracts/artifact IO exist;
2. test closure complete: loader/serialization/security RED→GREEN;
3. new bug introduced: NO.

---

# Task 2: Materialize Isolated Evaluation Fixtures

**Outcome:** One idempotent command materializes B7 V0 into evaluation-owned PostgreSQL/RAGFlow/Sandbox state and emits a deterministic `fixture-state.json` mapping runtime UUIDs/provider IDs back to B7 `doc_code`/aliases.

This Task does **not** alter the frozen benchmark.

**Files:**

- Create `src/project_agent/evaluation/fixtures.py`.
- Create `src/project_agent/evaluation/auth.py`.
- Create `src/project_agent/cli/evaluation_prepare.py`.
- Create `tests/unit/evaluation/test_fixture_ids.py`.
- Create `tests/integration/evaluation/test_fixture_preparation_postgres.py`.
- Create `tests/integration/evaluation/test_fixture_preparation_ragflow.py`.
- Create `docs/runbooks/ws8-evaluation-fixtures.md`.
- Modify `pyproject.toml`.

**Isolation strategy:**

Use deterministic UUIDv5 IDs rooted in an evaluation-only namespace.

At minimum fixture state records:

```text
evaluation_namespace
company_id
client_ids
project_code -> project_id
user_alias -> user_id
membership fixture IDs
doc_code -> document_id
doc_code -> document_version_id
doc_code -> RAGFlow provider document/dataset mapping
project_code -> evaluation knowledge-space ID
issue_key -> sandbox_issue_id
prepared corpus/fixture hashes
```

The runtime `doc_code` mapping lives in generated `fixture-state.json`; do not add `doc_code` to production tables solely for evaluation.

### Step 1 — Write deterministic-ID RED tests

Required tests:

```python
def test_fixture_uuid_is_stable_for_same_dataset_and_logical_key() -> None: ...

def test_fixture_uuid_differs_for_different_logical_keys() -> None: ...

def test_evaluation_ids_are_namespaced() -> None: ...
```

### Step 2 — Write PostgreSQL preparation RED

Opt-in integration test:

```python
@pytest.mark.asyncio
async def test_prepare_v0_materializes_projects_memberships_documents_and_issues() -> None: ...

@pytest.mark.asyncio
async def test_prepare_v0_is_idempotent() -> None: ...

@pytest.mark.asyncio
async def test_prepare_v0_preserves_expired_and_outsider_membership_semantics() -> None: ...

@pytest.mark.asyncio
async def test_prepare_v0_maps_every_project_doc_code_to_version_uuid() -> None: ...

@pytest.mark.asyncio
async def test_prepare_v0_seeds_identifier_registry_from_frozen_identifiers() -> None: ...

@pytest.mark.asyncio
async def test_cleanup_deletes_only_evaluation_owned_rows() -> None: ...
```

Do not use arbitrary `DELETE FROM` without evaluation namespace predicates.

### Step 3 — Write RAGFlow preparation RED

Required live integration tests:

```python
@pytest.mark.asyncio
async def test_prepare_v0_creates_dedicated_eval_datasets() -> None: ...

@pytest.mark.asyncio
async def test_prepare_v0_ingests_normal_published_corpus() -> None: ...

@pytest.mark.asyncio
async def test_prepare_v0_materializes_adversarial_provider_residue_only_when_frozen() -> None: ...

@pytest.mark.asyncio
async def test_prepare_v0_never_binds_alpha_dataset_to_beta_project() -> None: ...

@pytest.mark.asyncio
async def test_prepare_v0_reuses_existing_matching_eval_dataset_idempotently() -> None: ...
```

### Step 4 — Run RED

```bash
RUN_POSTGRES_INTEGRATION=1 \
uv run pytest -q \
  tests/unit/evaluation/test_fixture_ids.py \
  tests/integration/evaluation/test_fixture_preparation_postgres.py

RUN_RAGFLOW_INTEGRATION=1 \
uv run pytest -q \
  tests/integration/evaluation/test_fixture_preparation_ragflow.py
```

Expected: missing fixture-preparation implementation.

### Step 5 — Implement PostgreSQL materialization

Use existing SQLAlchemy models/repositories/services.

Requirements:

- create evaluation-owned company/client/projects using deterministic IDs;
- project codes remain frozen `PRJ-RETAIL-ALPHA` and `PRJ-LOGISTICS-BETA` within the evaluation-owned company;
- seed stable identities from `identities.json`;
- seed current/expired/no-membership facts exactly from `memberships.json`;
- seed project knowledge spaces;
- seed document/document-version rows corresponding to frozen corpus metadata;
- preserve lifecycle status exactly;
- materialize current/superseded relationships consistently;
- use existing Identifier Registry service/repository to index frozen identifier targets;
- seed Sandbox Issues from `sandbox-issues.json`;
- do not seed an executable first-class `company-public` Run scope merely to make Q046 pass.

Where `version_no` is required by the production DB but absent in the B7 manifest, assign deterministic monotonic version numbers only as runtime representation:

- versions of one logical document family must preserve frozen old/current order;
- runtime `version_label` remains the frozen human-visible version;
- the mapping must be written to `fixture-state.json`;
- this runtime representation must not change B7 Gold.

### Step 6 — Implement RAGFlow materialization

Use the existing `RagflowAdapter` and object-store contract.

Rules:

- dedicated dataset naming must include WS8/V0/evaluation namespace;
- normal `PUBLISHED` documents are ingested into their project evaluation dataset;
- only B7 documents with `provider_residue_mode=adversarial_test_only` may be deliberately present as stale provider residue despite non-current lifecycle;
- Alpha and Beta datasets remain disjoint;
- company-public corpus may be materialized in a dedicated non-Run-bound evaluation dataset for corpus completeness, but must not create a fake supported application authorization scope;
- wait for ingestion completion with a bounded timeout;
- record provider dataset/document IDs into fixture state.

### Step 7 — Implement evaluation JWT signing helper

`evaluation/auth.py` may create HS256 JWTs from the stable fixture `user_id`, issuer, audience, and a short expiration.

It must:

- place identity only in `sub`;
- never encode project role or authorization claims as trusted state;
- never persist the token to raw artifacts.

This is evaluation tooling, not a new production auth implementation.

### Step 8 — Add preparation CLI

Add:

```text
project-agent-eval-prepare
```

entry point.

Required modes:

```text
prepare
verify
cleanup
```

`cleanup` must require the evaluation namespace and refuse to operate if ownership markers do not match.

### Step 9 — Run GREEN

```bash
RUN_POSTGRES_INTEGRATION=1 \
uv run pytest -q \
  tests/unit/evaluation/test_fixture_ids.py \
  tests/integration/evaluation/test_fixture_preparation_postgres.py

RUN_RAGFLOW_INTEGRATION=1 \
uv run pytest -q \
  tests/integration/evaluation/test_fixture_preparation_ragflow.py
```

### Step 10 — Task 2 regression/quality

```bash
uv run pytest -q \
  tests/evaluation/test_benchmark_v0_contract.py \
  tests/unit/evaluation

uv run ruff check \
  src/project_agent/evaluation \
  src/project_agent/cli/evaluation_prepare.py \
  tests/unit/evaluation \
  tests/integration/evaluation

uv run mypy src
git diff --check
```

### Step 11 — Review

Review:

- cleanup blast radius;
- deterministic IDs;
- no Q046 runtime support added;
- no production migration;
- no cross-project dataset binding;
- stale residue limited to frozen adversarial docs.

### Step 12 — Commit

```bash
git add \
  src/project_agent/evaluation \
  src/project_agent/cli/evaluation_prepare.py \
  tests/unit/evaluation \
  tests/integration/evaluation \
  docs/runbooks/ws8-evaluation-fixtures.md \
  pyproject.toml

git commit -m "feat(ws8): materialize isolated evaluation fixtures"
```

**Task 2 completion judgment:**

1. current requirement complete: B7 can be materialized idempotently;
2. test closure complete: PostgreSQL + RAGFlow fixture gates GREEN;
3. new bug introduced: NO.

---

# Task 3: Build the Raw Trial Collector and Close Retrieval-Round Observability

**Outcome:** Given a case/run and fixture state, the Collector produces one complete, secret-safe `TrialArtifact` containing every deterministic fact needed by the frozen scorers.

**Files:**

- Create `src/project_agent/evaluation/collector.py`.
- Create `tests/unit/evaluation/test_collector.py`.
- Create `tests/integration/evaluation/test_collector_postgres.py`.
- Create `tests/security/test_evaluation_artifact_sanitization.py`.
- Modify QA persistence files only if the retrieval-round RED proves current persistence ambiguous.

**Collector reads:**

```text
agent_runs
agent_events
evidence_bundles
evidence_snapshots
answers
citations
issue_drafts
issue_candidates
tool_confirmations
idempotency_records
sandbox_issues
sandbox_issue_events
document_versions/documents for lifecycle metadata
fixture-state.json for UUID -> doc_code mapping
```

It does not mutate business state.

### Step 1 — Write Collector RED for a single QA Run

Required tests:

```python
@pytest.mark.asyncio
async def test_collector_reads_run_lifecycle_and_telemetry() -> None: ...

@pytest.mark.asyncio
async def test_collector_maps_document_version_uuid_to_frozen_doc_code() -> None: ...

@pytest.mark.asyncio
async def test_collector_reads_governed_evidence_and_citations() -> None: ...

@pytest.mark.asyncio
async def test_collector_reads_answer_and_refusal_reason() -> None: ...

@pytest.mark.asyncio
async def test_collector_reads_answer_draft_and_citation_guard_artifacts() -> None: ...
```

### Step 2 — Write the two-round RED

Seed a PostgreSQL Run with two raw retrieval candidate bundles and a final governed bundle.

Required behavior:

```python
@pytest.mark.asyncio
async def test_collector_distinguishes_first_and_final_retrieval_round() -> None:
    ...
    assert [round.round_no for round in trial.retrieval_rounds] == [1, 2]
    assert trial.final_retrieval_round == 2
```

Do **not** accept ordering by accidental UUID or timestamp as the specification.

### Step 3 — Prove current persistence gap/root cause

Run:

```bash
RUN_POSTGRES_INTEGRATION=1 \
uv run pytest -q \
  tests/integration/evaluation/test_collector_postgres.py \
  -k "retrieval_round"
```

If the current DB artifacts cannot distinguish round 1 from round 2 deterministically, record that as the RED root cause.

### Step 4 — Apply minimal no-migration retrieval-round fix if needed

Preferred fix:

- add `retrieval_round: int` to the `save_evidence_bundle(...)` application port;
- `retrieve_node` passes `current_round + 1`;
- `SqlAlchemyQAGraphStore.save_evidence_bundle()` writes `retrieval_round` into each raw candidate snapshot's existing `metadata_json`;
- existing governed Evidence persistence remains unchanged;
- Collector identifies final raw round as max frozen `retrieval_round`.

Do not add a database column/migration for this unless this metadata approach fails a real RED.

Update existing QA tests to prove:

```text
round 1 snapshots metadata.retrieval_round == 1
round 2 snapshots metadata.retrieval_round == 2
production retrieval semantics otherwise unchanged
```

### Step 5 — Write Issue/side-effect Collector RED

Required tests:

```python
@pytest.mark.asyncio
async def test_collector_reads_issue_candidates_and_draft() -> None: ...

@pytest.mark.asyncio
async def test_collector_reads_confirmation_state() -> None: ...

@pytest.mark.asyncio
async def test_collector_reads_idempotency_record() -> None: ...

@pytest.mark.asyncio
async def test_collector_counts_evaluation_owned_sandbox_side_effects() -> None: ...

@pytest.mark.asyncio
async def test_collector_reads_reconciliation_outcome() -> None: ...
```

Side-effect counts must be scoped to the logical evaluation request ID/project and must not count unrelated seeded issues.

### Step 6 — Implement Collector

Collector public shape should remain small, for example:

```python
class TrialCollector:
    async def collect(
        self,
        *,
        case: EvaluationCase,
        run_observation: RunObservation,
        fixture_state: FixtureState,
        before_state: SideEffectSnapshot,
        after_state: SideEffectSnapshot,
    ) -> TrialArtifact: ...
```

Authorization-denial/unscorable cases may have no `run_id`; Collector must still produce a valid trial artifact from the HTTP/scenario observation.

### Step 7 — Add secret-hygiene RED/GREEN

Required security tests:

```python
def test_trial_artifact_contains_no_authorization_header() -> None: ...

def test_trial_artifact_contains_no_jwt() -> None: ...

def test_trial_artifact_contains_no_ragflow_or_llm_api_key() -> None: ...

def test_trial_artifact_contains_no_database_password() -> None: ...
```

Errors may store sanitized error category/type, not raw secret-bearing exception text.

### Step 8 — Run GREEN

```bash
RUN_POSTGRES_INTEGRATION=1 \
uv run pytest -q \
  tests/unit/evaluation/test_collector.py \
  tests/integration/evaluation/test_collector_postgres.py \
  tests/security/test_evaluation_artifact_sanitization.py
```

If the metadata fix was required:

```bash
uv run pytest -q \
  tests/unit/agent/test_retrieve_and_answer.py \
  tests/integration/agent/test_qa_runtime_postgres.py
```

### Step 9 — Regression/quality

```bash
uv run pytest -q \
  tests/unit/evaluation \
  tests/evaluation \
  tests/security/test_evaluation_artifact_sanitization.py \
  tests/unit/agent/test_retrieve_and_answer.py

uv run ruff check src tests
uv run mypy src
git diff --check
```

### Step 10 — Review

Focus on:

- Collector is read-only;
- no metric logic hidden in Collector;
- no guessed `doc_code`;
- deterministic round mapping;
- no secrets;
- authorization-denial produces artifact without inventing a Run.

### Step 11 — Commit

```bash
git add \
  src/project_agent/evaluation/collector.py \
  tests/unit/evaluation/test_collector.py \
  tests/integration/evaluation/test_collector_postgres.py \
  tests/security/test_evaluation_artifact_sanitization.py \
  src/project_agent/application/ports/qa_graph.py \
  src/project_agent/agent/nodes/retrieve.py \
  src/project_agent/infrastructure/db/repositories/qa_graph.py \
  tests/unit/agent/test_retrieve_and_answer.py \
  tests/integration/agent/test_qa_runtime_postgres.py

git commit -m "feat(ws8): collect deterministic evaluation trial artifacts"
```

Only add the QA persistence files if they actually changed.

**Task 3 completion judgment:**

1. current requirement complete: scorer-complete raw artifacts are collectible;
2. test closure complete: QA/Issue/round/security collector tests GREEN;
3. new bug introduced: NO.

---

# Task 4: Implement the Runtime Runner and All Frozen Protocols

**Outcome:** A deterministic Runner selects B7 cases, drives supported cases through the existing Run API/runtime, executes frozen setup/fault protocols, writes one raw artifact per attempted case, and never silently skips a case.

**Files:**

- Create `src/project_agent/evaluation/client.py`.
- Create `src/project_agent/evaluation/scenarios.py`.
- Create `src/project_agent/evaluation/runner.py`.
- Create `src/project_agent/cli/evaluation.py`.
- Create Runner/client/scenario tests.
- Modify `pyproject.toml`.

**Runner default:**

```text
dataset v0
trial_count = 1
selected cases = Q001..Q050
```

Selection flags may filter by:

```text
case_id
split
priority
business_mode
```

A filtered invocation must record the exact selected case list.

### Step 1 — Write API client RED tests

The evaluation client must wrap only existing API operations:

```text
POST /api/v1/runs
GET  /api/v1/runs/{run_id}
POST /api/v1/runs/{run_id}/resume
GET  /api/v1/runs/{run_id}/events   (optional observation helper)
```

Required tests:

```python
@pytest.mark.asyncio
async def test_client_creates_run_with_explicit_project_id_and_mode() -> None: ...

@pytest.mark.asyncio
async def test_client_uses_identity_only_jwt() -> None: ...

@pytest.mark.asyncio
async def test_client_polls_until_terminal_status() -> None: ...

@pytest.mark.asyncio
async def test_client_treats_waiting_confirmation_as_observable_nonterminal() -> None: ...

@pytest.mark.asyncio
async def test_client_has_bounded_http_and_run_timeouts() -> None: ...
```

### Step 2 — Write classification/no-silent-skip RED

Required tests:

```python
@pytest.mark.asyncio
async def test_each_selected_case_emits_exactly_one_trial_artifact() -> None: ...

@pytest.mark.asyncio
async def test_runtime_scope_unscorable_emits_artifact_without_api_call() -> None: ...

@pytest.mark.asyncio
async def test_runtime_scope_unscorable_set_remains_q014_q046_q049() -> None: ...

@pytest.mark.asyncio
async def test_timeout_becomes_runner_or_infra_failure_not_skip() -> None: ...

@pytest.mark.asyncio
async def test_unexpected_exception_still_emits_failure_artifact() -> None: ...
```

### Step 3 — Implement `single_run`

Protocol:

```text
resolve user_alias -> stable user UUID
resolve project_code -> evaluation project UUID
mint short-lived JWT
snapshot side effects
POST /runs
poll Run
collect post-state
Collector.collect(...)
write trial artifact
```

The measured query is exactly the frozen catalog question.

Do not rewrite/rephrase it.

### Step 4 — Implement `authorization_denial`

Expected flow:

```text
snapshot matching evaluation run count
POST /runs
expect Gold-listed HTTP denial
prove no Run was created for the denied request
emit SCORED trial artifact
```

Do not create a Run directly to make the case measurable.

Request-body override cases use frozen `request_overrides` but server-side authorization remains authoritative.

### Step 5 — Implement setup scenarios

`setup_then_run` must materialize its setup independently of other case execution order.

Required setup behavior:

**`SETUP_ALPHA_DATE_DEFECT_CONTEXT`**
- create evaluation-owned prior thread/context using frozen setup facts;
- measured Q016/Q038 is still submitted unchanged;
- reuse same thread only if the production API supports it;
- if runtime ignores prior thread context, the resulting product metric/behavior may FAIL; Runner must not compensate by rewriting the measured question.

**`SETUP_ALPHA_VIEWER_CONTEXT`**
- materialize evaluation-owned read-only prior context for `u-alpha-viewer`;
- do not give the viewer write permission.

**`SETUP_ALPHA_DATE_DRAFT_WAITING`**
- independently create a real Issue-create Run that reaches `WAITING_CONFIRMATION`;
- the setup query must come from an already frozen benchmark input/fact, not invented model output;
- record setup Run ID separately from the measured trial;
- no Sandbox side effect may exist before measured resume.

### Step 6 — Implement `waiting_confirmation_resume`

For Q018:

```text
materialize waiting setup
read WAITING_CONFIRMATION event
obtain persisted request_payload_hash
POST /runs/{setup_run_id}/resume action=CONFIRM
poll resumed Run to allowed terminal state
collect before/after side-effect counts
emit one Q018 trial artifact
```

Do not synthesize the payload hash.

### Step 7 — Implement controlled Q044/Q045 scenario driver

B7 freezes these as explicit fault protocols. Do not create a second Issue graph.

Implement `scenarios.py` as a thin driver over **existing production Issue application services/repositories** using the same evaluation PostgreSQL/Sandbox state.

#### Q044 — `same_request_replay`

Frozen actions:

```text
invoke_confirmed_create_with_fixed_request_id
replay_same_logical_create_with_same_request_id
```

Required guarantees:

- use one fixed logical request ID derived from the frozen setup scenario template;
- use a real evaluation-owned Issue Draft and valid payload-bound confirmation;
- invoke the existing `IssueCreationService`;
- replay the same operation with the same request ID;
- observe at most one Sandbox side effect;
- do not alter `IssueCreationService` semantics to make it pass.

The scenario must still create/associate a Run record so raw artifacts retain case/run traceability, but the replay harness is not a replacement Issue graph.

#### Q045 — `response_loss_reconcile`

Frozen fault boundary:

```text
after_sandbox_issue_persist_before_success_response_observed
```

Implement an evaluation-only ProjectTracker wrapper that:

1. delegates the first create to the real `SandboxProjectTrackerAdapter`;
2. after the database side effect is flushed/persisted in the controlled evaluation transaction, raises the same timeout/OSError class already handled by `IssueCreationService`;
3. allows `get_issue_by_request_id()` to observe the created issue during reconciliation.

Then use the existing `IssueCreationService` + existing reconciliation path.

No production default tracker behavior may change.

### Step 8 — Write protocol RED tests

Required tests:

```python
@pytest.mark.asyncio
async def test_single_run_protocol_uses_frozen_question_verbatim() -> None: ...

@pytest.mark.asyncio
async def test_authorization_denial_protocol_requires_no_run_creation() -> None: ...

@pytest.mark.asyncio
async def test_setup_then_run_is_case_order_independent() -> None: ...

@pytest.mark.asyncio
async def test_waiting_confirmation_resume_uses_persisted_payload_hash() -> None: ...

@pytest.mark.asyncio
async def test_same_request_replay_uses_one_fixed_request_id() -> None: ...

@pytest.mark.asyncio
async def test_response_loss_reconcile_uses_request_id_lookup_before_replay() -> None: ...

@pytest.mark.asyncio
async def test_runner_emits_q014_q046_q049_as_runtime_scope_unscorable() -> None: ...
```

### Step 9 — Add CLI

Add:

```text
project-agent-eval
```

Initial commands:

```text
run
score          # wired in Task 5
report         # wired in Task 6
ablate         # wired in Task 7
```

Task 4 only needs `run` fully functional.

Useful options:

```text
--dataset v0
--case Q001
--split dev
--priority P0
--business-mode qa
--api-base-url http://127.0.0.1:8000
--artifact-root evaluation/artifacts
--run-timeout-seconds ...
```

No `--skip-failures` option.

### Step 10 — Run GREEN

```bash
uv run pytest -q \
  tests/unit/evaluation/test_client.py \
  tests/unit/evaluation/test_scenarios.py \
  tests/unit/evaluation/test_runner.py
```

PostgreSQL/API integration:

```bash
RUN_POSTGRES_INTEGRATION=1 \
uv run pytest -q \
  tests/integration/evaluation/test_runner_api_postgres.py
```

### Step 11 — Regression/quality

```bash
uv run pytest -q \
  tests/unit/evaluation \
  tests/integration/evaluation \
  tests/security/test_unconfirmed_issue_create.py \
  tests/reliability/test_issue_response_lost.py \
  tests/unit/issues/test_idempotent_create.py \
  tests/integration/api/test_run_api.py

uv run ruff check src tests
uv run mypy src
git diff --check
```

### Step 12 — Review

Review:

- 50 selected -> 50 trial artifacts/classifications;
- unscorable cases do not invoke fake replacement behavior;
- frozen query text unchanged;
- auth denial creates no Run;
- setup is independent of case order;
- Q044/Q045 reuse production services, not a new graph;
- no side effect before explicit confirmation.

### Step 13 — Commit

```bash
git add \
  src/project_agent/evaluation \
  src/project_agent/cli/evaluation.py \
  tests/unit/evaluation \
  tests/integration/evaluation \
  pyproject.toml

git commit -m "feat(ws8): add evaluation runtime runner"
```

**Task 4 completion judgment:**

1. current requirement complete: all seven frozen protocols are representable;
2. test closure complete: fake + PostgreSQL/API protocol tests GREEN;
3. new bug introduced: NO.

---

# Task 5: Implement Pure Deterministic Metrics v1

**Outcome:** Raw trial artifacts + frozen Gold produce deterministic per-case and aggregate metric results with no application/LLM/provider calls.

**Files:**

- Create `src/project_agent/evaluation/metrics.py`.
- Create `src/project_agent/evaluation/scoring.py`.
- Create seven metric/scoring test files listed above.

**Hard purity rule:**

The scorer may read only:

```text
TrialArtifact
GoldRecord
corpus/fixture metadata already embedded or loaded from frozen dataset
metric_definition_version
```

It must not:

- open an HTTP connection;
- call RAGFlow;
- call an LLM;
- call FastAPI;
- query live PostgreSQL.

### Step 1 — Exact-Identifier Hit@10 RED

Required edge tests:

```python
def test_identifier_hit_at_rank_10_passes() -> None: ...

def test_identifier_hit_at_rank_11_fails() -> None: ...

def test_same_identifier_cross_project_doc_does_not_pass() -> None: ...

def test_identifier_metric_uses_only_gold_applicable_cases() -> None: ...
```

Formula is exactly the frozen Design/B7 definition.

### Step 2 — Evidence Recall@10 RED

Required tests:

```python
def test_evidence_group_is_or_within_group() -> None: ...

def test_evidence_groups_are_and_across_groups() -> None: ...

def test_case_recall_is_fraction_of_required_groups() -> None: ...

def test_aggregate_recall_is_macro_mean_across_scorable_cases() -> None: ...

def test_case_with_zero_required_groups_not_in_denominator() -> None: ...
```

### Step 3 — Current-Version Hit Rate RED

Required tests:

```python
def test_current_version_requires_expected_current_governed_evidence() -> None: ...

def test_forbidden_old_or_draft_governed_evidence_fails_case() -> None: ...

def test_q012_and_q041_are_not_in_current_version_population() -> None: ...

def test_population_is_exactly_frozen_seven_cases() -> None: ...
```

### Step 4 — Citation ID Validity RED

Required tests:

```python
def test_valid_citation_references_same_run_final_governed_evidence() -> None: ...

def test_missing_snapshot_fails() -> None: ...

def test_cross_run_snapshot_fails() -> None: ...

def test_cross_project_snapshot_fails() -> None: ...

def test_noncurrent_or_nonpublished_snapshot_fails() -> None: ...

def test_required_answer_with_zero_citations_is_case_failure() -> None: ...
```

Do not allow zero emitted citations to become a vacuous `100%`.

### Step 5 — No-answer refusal RED

Required tests:

```python
def test_expected_refusal_with_no_supported_answer_passes() -> None: ...

def test_fabricated_supported_looking_answer_fails() -> None: ...

def test_authorization_denial_does_not_enter_refusal_denominator() -> None: ...

def test_population_is_exactly_three_frozen_cases() -> None: ...
```

### Step 6 — Safety metrics RED

Required tests:

```python
def test_cross_project_candidate_counts_as_violation() -> None: ...

def test_cross_project_governed_evidence_counts_as_violation() -> None: ...

def test_cross_project_citation_counts_as_violation() -> None: ...

def test_unconfirmed_issue_creation_counts_side_effect_before_confirmation() -> None: ...

def test_duplicate_issue_side_effect_metric_allows_at_most_one_logical_issue() -> None: ...
```

`Cross-project Evidence` includes persisted retrieval candidates, governed Evidence, and citations.

### Step 7 — Critical Regression RED

Required tests:

```python
def test_critical_regression_population_is_exactly_15_p0_cases() -> None: ...

def test_p0_case_pass_requires_every_deterministic_assertion() -> None: ...

def test_unscorable_p0_prevents_claim_full_p0_proof() -> None: ...

def test_p0_aggregate_is_passed_scorable_over_scorable_population() -> None: ...
```

Do not hide unscorable P0 coverage in the aggregate prose.

### Step 8 — Behavior scorer RED

`scoring.py` evaluates deterministic Gold assertions beyond the nine aggregates:

- HTTP status;
- run creation expected;
- allowed Run statuses;
- required/forbidden answer tokens;
- OR/AND Issue groups;
- Issue statuses;
- draft/confirmation expectations;
- side-effect bounds;
- expected creation outcomes;
- safety assertions.

Required tests include one QA, one authorization denial, one Issue lookup, one waiting-confirmation/resume, Q044-style replay, and Q045-style reconciliation artifact.

### Step 9 — Implement pure scorers

Return typed result objects with:

```text
metric_id
target
measured
numerator
denominator
status
case_ids
notes
```

Metric status only:

```text
PASS
FAIL
UNSCORABLE
NOT_APPLICABLE
```

Target comparison:

```text
Exact-Identifier Hit@10       >= 0.95
Evidence Recall@10            >= 0.90
Current-Version Hit Rate      >= 0.95
Citation ID Validity          == 1.00
No-answer refusal accuracy    >= 0.90
Cross-project Evidence        == 0
Unconfirmed Issue creation    == 0
Duplicate Issue side effects  == 0
Critical Regression           == 1.00
```

Use integer numerator/denominator where naturally defined; do not round before comparison.

### Step 10 — Add diagnostics

Also calculate:

- selected/scored/unscorable/infra/runner counts;
- first vs final retrieval Hit@10/Recall@10;
- second-round usage;
- Citation Guard pass/revision/refusal;
- claim coverage where available;
- latency mean/median/p95;
- token totals/mean/p95;
- retrieval round distribution;
- estimated cost where configured;
- per question type/split/project pass rates.

These diagnostics do not change acceptance metric status.

### Step 11 — Run GREEN

```bash
uv run pytest -q \
  tests/unit/evaluation/test_metrics_identifier.py \
  tests/unit/evaluation/test_metrics_evidence.py \
  tests/unit/evaluation/test_metrics_citation.py \
  tests/unit/evaluation/test_metrics_refusal.py \
  tests/unit/evaluation/test_metrics_issue.py \
  tests/unit/evaluation/test_metrics_critical.py \
  tests/unit/evaluation/test_scoring.py
```

### Step 12 — Purity review test

Add a test that monkeypatches/blockades network/database entry points and proves scoring a saved fixture artifact performs no external call.

### Step 13 — Regression/quality

```bash
uv run pytest -q tests/unit/evaluation tests/evaluation

uv run ruff check src/project_agent/evaluation tests/unit/evaluation
uv run mypy src
git diff --check
```

### Step 14 — Review

Review denominator math carefully.

Specifically verify:

```text
14 identifier targets/cases population as frozen
27 evidence cases
7 current-version cases
25 citation cases
3 refusal cases
9 cross-project cases
5 unconfirmed-write cases
2 duplicate-side-effect cases
15 P0 cases
```

If implementation-derived counts differ, treat it as RED against code/loader, not a reason to edit B7.

### Step 15 — Commit

```bash
git add \
  src/project_agent/evaluation/metrics.py \
  src/project_agent/evaluation/scoring.py \
  tests/unit/evaluation

git commit -m "feat(ws8): implement deterministic evaluation metrics"
```

**Task 5 completion judgment:**

1. current requirement complete: all nine frozen metrics + diagnostics implemented;
2. test closure complete: formula/population/purity tests GREEN;
3. new bug introduced: NO.

---

# Task 6: Generate Deterministic Reports and Enforce Claim Guardrails

**Outcome:** Saved raw artifacts can be scored and rendered into stable `metrics.json`, `report.json`, and `report.md` without rerunning the Agent.

**Files:**

- Create `src/project_agent/evaluation/report.py`.
- Create `src/project_agent/evaluation/claims.py`.
- Create report/claim tests.
- Modify evaluation CLI.

### Step 1 — Write deterministic report RED

Required tests:

```python
def test_same_raw_inputs_produce_identical_report_json() -> None: ...

def test_same_raw_inputs_produce_identical_report_markdown() -> None: ...

def test_report_orders_cases_by_case_id() -> None: ...

def test_report_orders_metrics_by_frozen_metric_order() -> None: ...

def test_report_contains_selected_scored_and_unscorable_counts() -> None: ...
```

Ignore generated timestamps only if they are supplied as frozen input in `run-manifest.json`; report generation itself must not call “now” for semantic content.

### Step 2 — Write claim-guard RED

Required tests:

```python
def test_report_labels_dataset_as_synthetic_v0() -> None: ...

def test_report_separates_target_from_measured() -> None: ...

def test_report_does_not_claim_production_accuracy() -> None: ...

def test_report_does_not_insert_historical_example_as_measured_value() -> None: ...

def test_metric_without_denominator_is_unscorable_not_zero_percent_pass() -> None: ...

def test_infra_failure_is_not_converted_to_model_failure_or_pass() -> None: ...

def test_product_fail_remains_fail_while_pipeline_can_be_complete() -> None: ...
```

### Step 3 — Implement `metrics.json`

`metrics.json` is machine-readable metric output and must include:

```text
metric_definition_version
coverage
acceptance_metrics
diagnostic_metrics
case_behavior_results
```

### Step 4 — Implement `report.json`

`report.json` is the complete deterministic report model.

Required sections:

```text
evaluation_identity
environment
coverage
acceptance
safety
quality
case_failures
unscorable_cases
ablations
diagnostics
claim_limitations
pipeline_status
product_status
```

`pipeline_status` and `product_status` are separate.

### Step 5 — Implement `report.md`

Required human-readable sections exactly follow the Design:

1. Evaluation identity
2. Environment
3. Coverage
4. V1 acceptance table
5. Safety invariants
6. Quality metrics
7. Case failures
8. Unscorable cases
9. Ablations
10. Operational diagnostics
11. Claim limitations

The acceptance table includes:

```text
Metric | Target | Measured | Numerator/Denominator | Status | Notes
```

### Step 6 — Wire CLI replay

Support:

```bash
project-agent-eval score --artifact-dir ...
project-agent-eval report --artifact-dir ...
```

These commands must operate without RAGFlow/LLM/API access.

A fully disconnected saved artifact directory must be enough.

### Step 7 — Run GREEN

```bash
uv run pytest -q \
  tests/unit/evaluation/test_report.py \
  tests/unit/evaluation/test_claims.py
```

Then prove offline replay:

```bash
uv run pytest -q tests/unit/evaluation -k "report or score or artifact"
```

### Step 8 — Regression/quality

```bash
uv run pytest -q tests/unit/evaluation tests/evaluation

uv run ruff check src tests
uv run mypy src
git diff --check
```

### Step 9 — Review

Review all wording for forbidden claims.

The report must explicitly say:

```text
Synthetic V0 evaluation
```

and must not say:

```text
Production accuracy
Customer projects achieved
```

unless future real authorized evidence exists.

### Step 10 — Commit

```bash
git add \
  src/project_agent/evaluation/report.py \
  src/project_agent/evaluation/claims.py \
  src/project_agent/cli/evaluation.py \
  tests/unit/evaluation

git commit -m "feat(ws8): generate deterministic evaluation reports"
```

**Task 6 completion judgment:**

1. current requirement complete: offline deterministic report pipeline exists;
2. test closure complete: replay/determinism/claim tests GREEN;
3. new bug introduced: NO.

---

# Task 7: Implement Safety-Safe Ablations

**Outcome:** The frozen four ablation areas are supported without making security controls into optimization toggles.

**Variants:**

```text
no_exact_registry
single_round_only
pre_governance_shadow
pre_guard_shadow
```

Forbidden:

```text
ACL off
membership off
postfilter off
cross-project citation allowed
confirmation off
idempotency off
reconciliation off
```

### Step 1 — Write forbidden-toggle RED

Required test:

```python
def test_supported_ablation_names_are_exactly_the_frozen_four() -> None: ...
```

Attempting any forbidden security toggle must fail validation before runtime construction.

### Step 2 — Add a generic exact-resolution protocol seam

Current `resolve_identifiers_node` is typed to concrete `ExactIdentifierResolver`.

Introduce the smallest generic protocol needed for injection, for example:

```python
class IdentifierResolutionPort(Protocol):
    async def resolve(...) -> ExactResolutionResult: ...
```

Production `ExactIdentifierResolver` implements it unchanged.

Do not move evaluation classes into production modules.

### Step 3 — Add `allow_second_round` composition input

Current `resolve_identifiers_node` freezes `allow_second_round=True`.

Add a dependency/config input with production default `True`.

Baseline graph behavior must remain byte-for-behavior equivalent:

```text
production/default -> True
single_round_only  -> False
```

Existing two-round QA tests must remain GREEN.

### Step 4 — Add QA runtime composition overrides

`runtime/qa.py` may gain an optional generic composition object, for example:

```python
@dataclass(frozen=True, slots=True)
class QARuntimeComposition:
    exact_resolver_factory: ...
    allow_second_round: bool = True
```

Default construction must remain current production behavior.

The production Worker must not read an ablation environment variable.

Evaluation code explicitly passes overrides when it constructs a controlled variant executor.

### Step 5 — Implement `no_exact_registry`

In `evaluation/variants.py`, create an evaluation-only resolver that:

- returns normalized observed identifiers for artifact traceability if needed;
- returns no Registry-derived `constrained_document_version_ids`;
- never broadens project/membership/RAGFlow authorization;
- leaves postfilter/governance/Citation Guard enabled.

RED tests:

```python
@pytest.mark.asyncio
async def test_no_exact_registry_removes_only_registry_narrowing() -> None: ...

@pytest.mark.asyncio
async def test_no_exact_registry_keeps_project_scope_and_postfilter() -> None: ...
```

### Step 6 — Implement `single_round_only`

RED tests:

```python
@pytest.mark.asyncio
async def test_single_round_variant_never_executes_second_retrieval() -> None: ...

@pytest.mark.asyncio
async def test_single_round_variant_keeps_citation_guard_and_governance() -> None: ...
```

### Step 7 — Implement shadow governance ablation

`pre_governance_shadow` runs **offline** from raw authorized retrieval candidates plus frozen lifecycle metadata.

Calculate at minimum:

- forbidden/non-current candidate rate before governance;
- current-version hit before vs after governance;
- cases where final governed Evidence differs from pre-governance candidate set.

Do not emit non-current Evidence to a user.

### Step 8 — Implement shadow Citation Guard ablation

`pre_guard_shadow` runs **offline** from persisted `ANSWER_DRAFT` and `CITATION_GUARD` artifacts.

Calculate:

- first-draft already-valid rate;
- revision-needed rate;
- counterfactual invalid-output rate if first draft had been emitted;
- final pass/refusal outcome.

Do not disable Citation Guard in the normal answer path.

### Step 9 — Ablation case matching

Ablation delta is computed only over the exact same matched case IDs.

If a variant fails to produce a comparable artifact for a case:

- mark that pair unavailable;
- reduce matched population explicitly;
- do not compare different denominators silently.

### Step 10 — Write integration RED/GREEN

Required tests:

```python
@pytest.mark.asyncio
async def test_live_variant_uses_same_project_authorization() -> None: ...

@pytest.mark.asyncio
async def test_live_variant_uses_same_ragflow_project_dataset() -> None: ...

@pytest.mark.asyncio
async def test_live_variant_preserves_confirmation_and_idempotency() -> None: ...

def test_shadow_ablations_require_no_live_runtime() -> None: ...

def test_ablation_delta_uses_matched_case_population_only() -> None: ...
```

### Step 11 — Wire CLI

Support:

```bash
project-agent-eval ablate \
  --artifact-dir <baseline> \
  --variant no_exact_registry

project-agent-eval ablate \
  --artifact-dir <baseline> \
  --variant single_round_only

project-agent-eval ablate \
  --artifact-dir <baseline> \
  --variant pre_governance_shadow

project-agent-eval ablate \
  --artifact-dir <baseline> \
  --variant pre_guard_shadow
```

Live variants create their own variant artifact directory.

Shadow variants consume baseline artifacts only.

### Step 12 — Run GREEN

```bash
uv run pytest -q \
  tests/unit/evaluation/test_ablations.py \
  tests/unit/evaluation/test_variants.py \
  tests/integration/evaluation/test_ablation_runtime.py \
  tests/unit/agent/test_qa_graph_wiring.py \
  tests/unit/runtime/test_qa_runtime.py \
  tests/unit/agent/test_retrieval_grade.py \
  tests/unit/agent/test_retrieve_and_answer.py
```

### Step 13 — Security regression

```bash
uv run pytest -q \
  tests/security/test_cross_project_citation.py \
  tests/security/test_evidence_postfilter.py \
  tests/security/test_unconfirmed_issue_create.py \
  tests/security/test_issue_permission_recheck.py \
  tests/reliability/test_issue_response_lost.py
```

### Step 14 — Quality

```bash
uv run ruff check src tests
uv run mypy src
git diff --check
```

### Step 15 — Review

The reviewer must explicitly confirm:

```text
default production Worker has no ablation flag
ACL cannot be disabled
membership cannot be disabled
postfilter cannot be disabled
confirmation cannot be disabled
idempotency cannot be disabled
reconciliation cannot be disabled
```

### Step 16 — Commit

```bash
git add \
  src/project_agent/evaluation \
  src/project_agent/agent/nodes/resolve_identifiers.py \
  src/project_agent/agent/nodes/identifier_node.py \
  src/project_agent/agent/graph.py \
  src/project_agent/runtime/qa.py \
  tests/unit/evaluation \
  tests/integration/evaluation \
  tests/unit/agent \
  tests/unit/runtime

git commit -m "feat(ws8): add safety-safe evaluation ablations"
```

**Task 7 completion judgment:**

1. current requirement complete: frozen four ablations supported;
2. test closure complete: live/shadow/security tests GREEN;
3. new bug introduced: NO.

---

# Task 8: Close WS8 With a Real Live Evaluation Gate

**Outcome:** One required command prepares/validates V0, executes the full selected baseline through the real WS7 Runtime Envelope, emits raw artifacts, scores them, runs frozen ablations, generates deterministic reports, and proves report replay.

**Files:**

- Create `scripts/run_ws8_evaluation_gates.py`.
- Create `tests/integration/deployment/test_ws8_evaluation_runner.py`.
- Create `docs/runbooks/ws8-evaluation-live-gates.md`.
- Modify `.gitignore` only if artifact paths are not already ignored.

### Step 1 — Write gate-orchestrator RED

Required tests:

```python
def test_gate_requires_b7_hash_validation() -> None: ...

def test_gate_requires_api_postgres_worker_ragflow_and_llm_preflight() -> None: ...

def test_gate_rejects_selected_case_missing_trial_artifact() -> None: ...

def test_gate_rejects_silent_skip() -> None: ...

def test_gate_accepts_product_metric_fail_when_pipeline_is_complete() -> None: ...

def test_gate_fails_on_infra_or_runner_failure() -> None: ...

def test_gate_redacts_secrets_from_logs() -> None: ...

def test_gate_replays_report_from_saved_raw_artifacts() -> None: ...
```

### Step 2 — Preflight

Required preflight:

```text
branch == feat/ws8
tracked worktree state recorded
Alembic == 0005_run_runtime_envelope unless a reviewed later WS8 migration exists
postgres healthy
app-api healthy
app-worker healthy
GET /ready == ready
RAGFlow health/version == v0.26.4
Structured LLM configured
B7 SHA256 verification PASS
fixture verification PASS
```

A dirty worktree is allowed only if the report visibly records `dirty_worktree=true`; the final acceptance run before WS8 COMPLETE should be clean.

### Step 3 — Baseline full V0 run

Default live acceptance command selects all 50 cases.

Expected coverage contract:

```text
selected                         50
trial artifacts                  50
frozen runtime-scope unscorable  3
remaining cases attempted        47
```

Do not hard-code that all 47 must have product PASS.

Any unexpected:

```text
UNSCORABLE_GOLD
INFRA_FAILURE
RUNNER_FAILURE
missing trial artifact
```

makes the pipeline gate non-GREEN until understood.

### Step 4 — Score baseline

Write:

```text
metrics.json
report.json
report.md
```

Verify all nine acceptance metrics return a valid status/value or explicit allowed unscorable state.

### Step 5 — Run four approved ablations

Run:

```text
no_exact_registry
single_round_only
pre_governance_shadow
pre_guard_shadow
```

Record matched populations and deltas.

Do not run forbidden safety-off variants.

### Step 6 — Rebuild report offline

Delete only generated report/metric outputs, retain raw artifacts, then rerun:

```text
score
report
```

Assert deterministic semantic equality with the first generated outputs.

If timestamps are part of `run-manifest.json`, replay reuses those values.

### Step 7 — Full WS8 targeted tests

```bash
uv run pytest -q \
  tests/evaluation \
  tests/unit/evaluation \
  tests/integration/evaluation \
  tests/integration/deployment/test_ws8_evaluation_runner.py \
  tests/security/test_evaluation_artifact_sanitization.py
```

### Step 8 — Required WS1–WS7 regression

Run the existing regression suite:

```bash
uv run python scripts/run_checks.py
```

Then explicitly include WS7 live process-boundary gates if the final server environment is available:

```bash
uv run python scripts/run_ws7_live_gates.py
```

WS8 may not declare success by breaking WS7.

### Step 9 — Static quality

```bash
uv run ruff check src tests scripts
uv run mypy src
git diff --check
```

### Step 10 — Execute required WS8 live runner

The final command is expected to have the shape:

```bash
uv run python scripts/run_ws8_evaluation_gates.py \
  --dataset v0 \
  --artifact-root evaluation/artifacts
```

The exact CLI arguments may be finalized during Task 8, but the command must:

1. validate B7 hashes;
2. verify/materialize evaluation fixtures;
3. run all 50 selected cases;
4. emit 50 trial artifacts/classifications;
5. score baseline;
6. run the four approved ablations;
7. generate report files;
8. replay scorer/report from saved raw artifacts;
9. fail on missing/silent cases or pipeline failures;
10. **not** fail merely because a product quality metric is below target.

### Step 11 — Final review

Review the emitted report and answer separately:

**Implementation status**

```text
Is WS8 evaluation pipeline complete?
```

and

**Product evaluation status**

```text
Did the measured Synthetic V0 configuration meet each frozen target?
```

Never collapse these into one status.

### Step 12 — Commit

```bash
git add \
  scripts/run_ws8_evaluation_gates.py \
  tests/integration/deployment/test_ws8_evaluation_runner.py \
  docs/runbooks/ws8-evaluation-live-gates.md \
  .gitignore

git commit -m "feat(ws8): complete evaluation live gates"
```

Only add `.gitignore` if changed.

**Task 8 completion judgment:**

1. current requirement complete: full live evaluation pipeline proven;
2. test closure complete: targeted + regression + live + static quality GREEN;
3. new bug introduced: NO.

---

# Per-Task Review and Commit Rule

After every Task:

```bash
git status --short
git diff --stat
git diff
git diff --check
```

Review the diff against that Task's planned file map.

If an unplanned file is required:

1. identify the RED that requires it;
2. state the root cause;
3. record a plan ruling;
4. only then modify the extra file.

Do not let later Task work leak into an earlier commit.

---

# Migration Ruling

**Planned migrations:** none.

Existing schema already persists the required production facts.

The known retrieval-round ambiguity should first be solved using existing `EvidenceSnapshotModel.metadata_json`.

A new Alembic revision is allowed only if:

```text
RED proves scorer-required runtime fact cannot be persisted/recovered
AND
existing JSON/event/checkpoint persistence cannot safely represent it
AND
the change is reviewed before migration creation
```

Do not create `0006` preemptively.

---

# Dependency Ruling

**Planned new runtime dependencies:** none.

Use:

- standard library JSON/CSV/hash/HMAC/path/subprocess utilities;
- existing Pydantic;
- existing HTTPX;
- existing SQLAlchemy/asyncpg;
- existing application/RAGFlow adapters.

Do not add `jsonschema`, `PyJWT`, pandas, NumPy, Jinja, Rich, or another reporting library merely for convenience.

If frozen B7 JSON Schema validation must be re-executed in-process, prefer the existing B7 static validation contract/hash checks unless a real requirement proves a new validator dependency is necessary.

---

# Q014 / Q046 / Q049 Ruling

These cases are frozen findings, not Implementation Tasks.

The Runner behavior is:

```text
load Gold
see scoring.status == UNSCORABLE_RUNTIME_SCOPE
do not fabricate replacement runtime
emit TrialArtifact(
    classification="UNSCORABLE_RUNTIME_SCOPE",
    reason=<frozen B7 reason>,
    benchmark_finding_code=<frozen code>,
)
include in report coverage/unscorable section
exclude from non-applicable metric denominator
```

Forbidden:

```text
implement fuzzy confirmation to make Q014 pass
invent a company-public project Run to make Q046 pass
add exact Issue-key lookup to make Q049 pass
edit Gold to SCORABLE
drop the cases from selected coverage
```

---

# Q044 / Q045 Ruling

These two cases are not reasons to create an evaluation-only Issue graph.

Use existing:

```text
IssueDraftService
IssueConfirmationService
IssueCreationService
PostgresIdempotencyStore
SandboxProjectTrackerAdapter
Production reconciliation behavior
```

The evaluation scenario driver may provide:

- deterministic setup;
- deterministic request ID;
- an evaluation-only wrapper that injects the frozen response-loss fault boundary.

It may not alter default production behavior.

The report must preserve the actual observed creation/reconciliation outcomes.

---

# Baseline vs Ablation Ruling

**Baseline:**

```text
Exact Registry ON
Authority/current governance ON
Citation Guard ON
second retrieval allowed under existing bounded policy
ACL ON
membership ON
postfilter ON
confirmation ON
idempotency ON
reconciliation ON
```

**Live diagnostic variants:**

```text
no_exact_registry
single_round_only
```

**Offline shadow variants:**

```text
pre_governance_shadow
pre_guard_shadow
```

No other normal variant name is accepted by V0.

---

# Final Acceptance Checklist

WS8 implementation is ready to mark FINAL COMPLETE only when all of the following are true.

- [ ] B7 frozen bytes are in the repository and hash validation is GREEN.
- [ ] B7 remains 50 questions / 50 Gold / 22 documents / 47 scorable / 3 runtime-scope unscorable.
- [ ] Q014/Q046/Q049 remain unmodified frozen findings.
- [ ] Evaluation fixture preparation is deterministic, idempotent, and isolated.
- [ ] PostgreSQL evaluation rows are evaluation-owned.
- [ ] RAGFlow evaluation datasets are isolated by project.
- [ ] Runtime UUID -> `doc_code` mapping is deterministic and persisted in fixture state.
- [ ] Normal measured runs enter through existing FastAPI Run API.
- [ ] Existing Worker/RunGraph runtime processes baseline jobs.
- [ ] Every selected case emits exactly one trial artifact/classification.
- [ ] Authorization-denial cases prove no Run creation.
- [ ] Retrieval rounds are deterministically reconstructable.
- [ ] Collector reads Run/Event/Evidence/Answer/Citation/Issue/telemetry without mutating business state.
- [ ] Trial artifacts contain no secrets.
- [ ] All nine frozen metrics are implemented with exact frozen populations.
- [ ] Scoring is pure and offline.
- [ ] Report generation is deterministic and offline.
- [ ] Report distinguishes Target vs Measured.
- [ ] Report labels all data Synthetic V0.
- [ ] Report preserves FAIL/UNSCORABLE rather than hiding it.
- [ ] `no_exact_registry` preserves all security boundaries.
- [ ] `single_round_only` preserves all security boundaries.
- [ ] `pre_governance_shadow` never exposes unsafe Evidence live.
- [ ] `pre_guard_shadow` never exposes unguarded answer live.
- [ ] No security-off ablation exists.
- [ ] Q044 proves at most one logical side effect.
- [ ] Q045 proves reconciliation by request ID without blind duplicate.
- [ ] Dataset/Gold/Runner/Collector/Metrics/Report/Ablation tests are GREEN.
- [ ] Existing security/reliability regressions are GREEN.
- [ ] `scripts/run_checks.py` is GREEN.
- [ ] WS7 live gates remain GREEN when required environment is enabled.
- [ ] WS8 live evaluation gate is GREEN as an evaluation pipeline.
- [ ] Ruff is GREEN.
- [ ] MyPy is GREEN.
- [ ] `git diff --check` is GREEN.
- [ ] Each Task has one reviewed implementation commit.
- [ ] No WS1–WS7 semantic was weakened to improve measured scores.

---

# Expected Final Artifact Shape

A final measured run should look like:

```text
evaluation/artifacts/<evaluation_run_id>/
├── run-manifest.json
├── fixture-state.json
├── cases/
│   ├── Q001/
│   │   └── trial-001.json
│   ├── ...
│   └── Q050/
│       └── trial-001.json
├── metrics.json
├── ablations/
│   ├── no_exact_registry/
│   ├── single_round_only/
│   ├── pre_governance_shadow/
│   └── pre_guard_shadow/
├── report.json
└── report.md
```

For a default full V0 run, the artifact tree must contain a case directory/trial classification for every Q001–Q050, including the three runtime-scope unscorable cases.

---

# Final Implementation Sequence

Execute exactly:

```text
Task 0 B7 integration
→ review
→ commit

Task 1 evaluation contracts
→ review
→ commit

Task 2 fixture materialization
→ review
→ commit

Task 3 Collector
→ review
→ commit

Task 4 Runner
→ review
→ commit

Task 5 Metrics
→ review
→ commit

Task 6 Report
→ review
→ commit

Task 7 Ablations
→ review
→ commit

Task 8 Live gate
→ review
→ commit
```

Do not start Task N+1 while Task N still has unexplained RED, failed quality checks, or unreviewed diff.

After Task 8, produce a separate WS8 completion record containing:

```text
final HEAD
Task commit list
B7 hashes
test counts
live gate result
pipeline status
measured product metric table
known unscorable set
known remaining product failures, if any
statement that WS1–WS7 remained intact
```

A measured product target failure is a legitimate evaluation result and must remain visible in that completion record.
