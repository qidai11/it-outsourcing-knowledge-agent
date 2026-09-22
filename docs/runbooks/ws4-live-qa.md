# WS4 Real Structured LLM + QA Live Acceptance Runbook

## Purpose

This runbook is the server-side acceptance procedure for **WS4 — Real Structured LLM +
QA Completion**. It proves the approved WS4 boundary only:

- real OpenAI-compatible Structured LLM JSON-schema response + token usage;
- real RAGFlow project isolation and application-owned metadata mapping;
- real PostgreSQL Run/Event/Evidence/Answer/Citation persistence;
- real LangGraph PostgreSQL checkpointer path;
- the existing WS3 BackgroundWorker `EXECUTE_AGENT_RUN` path;
- one successful grounded QA Run and one controlled refusal Run;
- a controlled/sanitized Structured LLM provider failure projected through existing WS3
  retry/final-failure semantics;
- retrieval telemetry remains bounded to at most two provider retrievals.

It does **not** validate WS5 Issue workflows, WS6 cost/observability work, WS7 Compose, or
WS8 evaluation quality. Passing these tests is not a claim about general model accuracy.

## Required worktree and Python environment

Run all commands from the WS4 worktree:

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws4-real-structured-llm-qa
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate it-agent
export PYTHONPATH="$PWD/src"

python --version
git branch --show-current
git status --short
```

Expected branch:

```text
feat/ws4-real-structured-llm-qa
```

Do not use the primary repository or the frozen WS3 worktree for WS4 acceptance.

## Live dependency flags

PostgreSQL:

```bash
export RUN_POSTGRES_INTEGRATION=1
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
```

RAGFlow:

```bash
export RUN_RAGFLOW_INTEGRATION=1
export RAGFLOW_BASE_URL='<real RAGFlow base URL>'
export RAGFLOW_API_KEY='<real RAGFlow API key>'
```

Additional RAGFlow settings used by the production adapter:

```bash
export RAGFLOW_EXPECTED_VERSION='<deployed version>'
# Required when the API-key tenant has no default embedding model. The value
# must be an embedding model configured and accessible in that same RAGFlow tenant.
export RAGFLOW_EMBEDDING_MODEL='<configured embedding model>'
export RAGFLOW_CHUNK_METHOD='naive'
export RAGFLOW_REQUEST_TIMEOUT_SECONDS=30
export RAGFLOW_MAX_ATTEMPTS=3
```

Structured LLM:

```bash
export RUN_LLM_INTEGRATION=1
export LLM_BASE_URL='<OpenAI-compatible base URL ending at /v1 or equivalent>'
export LLM_API_KEY='<real provider API key>'
export LLM_MODEL_ALIAS='<server-approved model alias>'
export LLM_REQUEST_TIMEOUT_SECONDS=30
export LLM_MAX_ATTEMPTS=3
export LLM_REQUEST_CAPACITY=10
export LLM_TOKEN_CAPACITY=100000
```

Never paste secrets into test logs, Git, screenshots, or completion documents.

## Database head gate

```bash
alembic current
alembic heads
```

WS4 requires the existing head only:

```text
0005_run_runtime_envelope
```

WS4 introduces no Alembic migration.

## Gate 1 — real Structured LLM probe

```bash
python -m pytest -q -rs tests/integration/llm/test_structured_provider.py
```

Required evidence:

- test runs rather than skips when `RUN_LLM_INTEGRATION=1`;
- the real adapter receives a schema-valid `{"status":"ok"}` result;
- provider usage reports non-negative input/output token counts;
- zero failures.

If the configured provider does not support the approved OpenAI-compatible
`chat/completions` + JSON Schema contract, stop. Do not add a second provider adapter ad
hoc during acceptance.

## Gate 2 — real RAGFlow project isolation

```bash
python -m pytest -q -rs tests/integration/ragflow/test_project_isolation.py
```

Required evidence:

- alpha and beta datasets are created/bound independently;
- alpha retrieval returns only alpha project/document metadata;
- beta-only content is never returned to alpha retrieval;
- zero failures and zero skips when `RUN_RAGFLOW_INTEGRATION=1`.

The integration test deletes its temporary provider documents. RAGFlow datasets may remain
for later manual cleanup because the existing RAGFlow API contract does not require dataset
delete for this gate.

## Gate 3 — PostgreSQL QA runtime and durable Worker

```bash
python -m pytest -q -rs \
  tests/integration/agent/test_qa_runtime_postgres.py \
  tests/integration/workers/test_qa_worker_postgres.py
```

Required evidence:

- QA answer/citation/token/retrieval telemetry persists;
- durable Worker success path persists one-round telemetry;
- durable Worker refusal path persists at most two retrieval rounds;
- zero failures.

## Gate 4 — complete real WS4 Worker QA path

All three live flags must be enabled before running this gate:

```bash
python -m pytest -q -rs tests/integration/workers/test_qa_worker_live.py
```

This file contains two acceptance cases with different dependency requirements.

### Real external-provider QA case

The first case requires PostgreSQL + RAGFlow + Structured LLM. It:

1. creates two temporary project scopes and two real RAGFlow datasets;
2. ingests one unique approved-design marker into the alpha dataset;
3. leaves the beta dataset empty to make refusal deterministic;
4. creates durable PostgreSQL QA Runs/jobs for both authorized projects;
5. enters `build_worker_runtime()` with no injected graph executor, exercising the default
   production RAGFlow + LLM composition;
6. requires alpha to finish `SUCCEEDED` with persisted grounded citations;
7. requires beta to finish `REFUSED` with no citation;
8. requires `1 <= retrieval_rounds <= 2`, persisted prompt/model fields, and positive token
   accounting;
9. requires all persisted alpha Evidence to remain in the alpha project scope.

### Controlled provider-failure case

The second case requires PostgreSQL only. It uses the real Structured LLM adapter with a
local `httpx.MockTransport` returning HTTP 500 and `max_attempts=1`. It proves the existing
WS3 Worker path records:

```text
job status = FAILED
job last_error_code = StructuredLLMHTTPError
Run status = FAILED
RUN_FAILED payload error_code = StructuredLLMHTTPError
```

It also verifies that neither the configured API key nor an Authorization header is stored
in durable job/event failure data.

A skip is not a pass. With all three live flags enabled, both cases must execute.

## Gate 5 — static acceptance and full regression

With PostgreSQL enabled and live provider flags intentionally set for the acceptance run:

```bash
ruff check src tests
mypy src
git diff --check
python -m pytest -q -rs
```

Record the exact pass/skip/fail counts. Requirements:

- zero failures;
- no newly skipped WS4 tests;
- with `RUN_POSTGRES_INTEGRATION=1`, `RUN_RAGFLOW_INTEGRATION=1`, and
  `RUN_LLM_INTEGRATION=1`, all WS4 live tests execute rather than skip;
- any remaining skip must be an unrelated, documented optional prerequisite.

## Expected persisted evidence to inspect

For the real alpha QA Run, the test itself verifies:

```text
agent_runs.status = SUCCEEDED
agent_runs.model_alias = configured LLM_MODEL_ALIAS
agent_runs.prompt_version is set
agent_runs.prompt_content_hash is set
1 <= agent_runs.retrieval_rounds <= 2
agent_runs.total_tokens = input_tokens + output_tokens > 0
answers.refusal_reason IS NULL
at least one citation exists
all citation evidence belongs to the same authorized project
```

For the empty beta Run:

```text
agent_runs.status = REFUSED
1 <= agent_runs.retrieval_rounds <= 2
agent_runs.total_tokens > 0
answers.refusal_reason IS NOT NULL
no citation exists
```

## Cleanup behavior

The new live Worker test cleans up its temporary PostgreSQL rows and LangGraph checkpoint
threads in `finally` blocks. It also deletes the temporary alpha RAGFlow document. The beta
dataset is deliberately empty. If a test process is killed before cleanup, identify temporary
resources by the `WS4-LIVE-*` / `ws4-live-*` prefixes before deleting them manually.

Do not delete shared baseline RAGFlow datasets or any non-WS4 resources.

## Architecture/scope audit

Before marking WS4 complete, verify the branch contains no new:

```text
Redis / Celery / ARQ
MinIO
second vector database
new multi-agent orchestration
production Jira / ZenTao / Feishu integration
Kubernetes
unified replacement LangGraph architecture
WS5 Issue evidence-chain implementation
WS6 cost/observability implementation
WS7 Docker/Compose expansion
WS8 evaluation runner
Alembic migration
```

The following frozen source-of-truth documents must remain unchanged:

```text
docs/adr/0004-v1-architecture-lock.md
docs/superpowers/specs/2026-09-12-v1-completion-design.md
```

## WS4 completion record gate

Create:

```text
docs/superpowers/plans/2026-09-16-ws4-real-structured-llm-qa-completed.md
```

**only after** every required server live/static/regression gate above is freshly green.
Record:

- branch and final HEAD;
- Big Task commit SHAs;
- Ruff and MyPy results;
- full pytest counts;
- each PostgreSQL/RAGFlow/LLM live command and exact counts;
- observed max retrieval rounds;
- answer/citation/token persistence evidence;
- known WS5+ remaining work;
- architecture-lock audit.

If any required external service is unavailable or any live test is skipped, record
`live acceptance ⏳` instead of declaring `WS4 COMPLETE`.
