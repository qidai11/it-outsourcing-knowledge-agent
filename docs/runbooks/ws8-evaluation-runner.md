# WS8 Task 4 — Runtime Runner (frozen B7 v0)

## Scope and handoff

This runbook covers only Task 4: `project-agent-eval run` and the seven frozen
execution protocols. `score`, `report`, and `ablate` are deliberately unavailable
until Tasks 5–7. Do not alter the B7 dataset, Task 2 prepared fixture namespace,
application IssueCreationService, or baseline Postgres database.

Task 4 package installs four runtime/CLI modules, five test files,
`pyproject.toml`, and this runbook. The full project archive also contains the
unaltered Task 0–3 source snapshot. The standalone installer checks the baseline
source SHA256 against the original Task 3 server snapshot and refuses conflicts.
Task 2/3 may still be uncommitted: **do not `git reset`, `git clean`, or checkout**.

## Prepare the server

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws8
source /home1/ckx/miniconda3/etc/profile.d/conda.sh
conda activate it-agent
# Configure secrets and service URLs ONLY from existing secure server settings.
# DATABASE_URL points to primary PostgreSQL, WS8_EVAL_DATABASE_URL to a distinct
# dedicated eval PostgreSQL DB. Never paste connection strings into shared logs.
: "${DATABASE_URL:?primary DB URL required for isolation preflight}"
: "${WS8_EVAL_DATABASE_URL:?dedicated evaluation DB URL required}"
: "${JWT_HS256_SECRET:?same HS256 signing secret as the production API required}"
(cd evaluation/datasets/v0 && sha256sum -c SHA256SUMS.txt)
```

Use the **already prepared**, verified Task 2 `evaluation/artifacts/<namespace>/fixture-state.json`;
do not re-run `evaluation-prepare --cleanup` to start Task 4. Keep the
namespace unique and never choose a namespace whose state you do not own.
`project-agent-eval run` checks that the evaluation DB is distinct from the
primary DB, verifies frozen dataset/fixture state, and creates a new run-artifact
folder for each invocation. It does not silently skip failures.

## Local and server acceptance gates

The unit/fake tests can run without an API or database:

```bash
python -m pytest -q tests/unit/evaluation/test_client.py \
  tests/unit/evaluation/test_scenarios.py tests/unit/evaluation/test_runner.py \
  tests/unit/evaluation/test_evaluation_cli.py
```

The actual Run API + PostgreSQL seams must be tested independently on the server:

```bash
RUN_POSTGRES_INTEGRATION=1 python -m pytest -q -rs \
  tests/integration/evaluation/test_runner_api_postgres.py
```

**Require 0 skipped** for the server gate. These tests use a disposable,
test-specific evaluation fixture namespace and the production FastAPI + Issue
application services; they do not launch the LLM/RAGFlow worker. A genuine
end-to-end worker/provider run is a separate acceptance activity and must not
be represented by these two API/DB tests. The optional real RAGFlow fixture
gate requires `RUN_RAGFLOW_INTEGRATION=1` and working provider credentials.

Then execute Ruff, MyPy, evaluation/regression pytest, `git diff --check`, and
B7 SHA256 verification. Verify no Task 0–3 source was overwritten and compare
installed source to the package manifest. The provided
`WS8_TASK4_FINAL_ACCEPTANCE.sh` runs and logs the complete server gate to `/tmp`.

## Measured evaluation (requires live API and worker)

```bash
project-agent-eval run \
  --evaluation-namespace YOUR_PREPARED_EVAL_NAMESPACE \
  --dataset v0 \
  --dataset-root evaluation/datasets/v0 \
  --api-base-url http://127.0.0.1:8000 \
  --artifact-root evaluation/artifacts \
  --run-timeout-seconds 120
```

Omit `--case` to select Q001–Q050 once each. For a limited validation, add
`--case Q001` (repeatable), `--split`, `--priority`, or `--business-mode`.
Q014/Q046/Q049 emit `UNSCORABLE_RUNTIME_SCOPE` with **no replacement API
call**. `authorization_denial` must create no Run. Q018 must read the persisted
`WAITING_CONFIRMATION` hash, then confirm/resume. Q044/Q045 use the evaluation
sandbox PostgreSQL and the existing IssueCreationService; they do **not**
provide evidence that an unrelated background worker ran or that a provider
fault was injected into production. Run destructive/fault-protocol cases only
against the disposable evaluation namespace and isolated infrastructure.

A nonzero CLI exit indicates a runner/infra failure; consult the classified,
redacted per-case artifacts rather than treating a zero-selected or skipped
case as success. Preserve the raw output directory for Task 5 scorer input.
