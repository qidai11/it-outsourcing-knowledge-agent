# WS8 Task 8 — Real Live Evaluation Gate

## Scope

This runbook closes WS8 Task 8 only. The frozen authority is:

- `docs/superpowers/specs/2026-09-22-ws8-evaluation-design.md`
- `docs/superpowers/plans/2026-09-22-ws8-evaluation-runner-metrics-ablation-report.md`
- `evaluation/datasets/v0/SHA256SUMS.txt`

Do not edit the B7 V0 dataset, Gold, corpus, fixtures, Task 0–7 production semantics, or
security controls to manufacture a passing product metric. A measured metric may be `FAIL`
while the Task 8 technical pipeline remains `PASS`.

## Preconditions

Run from the complete server worktree:

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws8
source /home1/ckx/miniconda3/etc/profile.d/conda.sh
conda activate it-agent
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
```

Load credentials only from the existing secure server configuration. Do not echo them and do
not write them into scripts, logs, snapshots, tests, or artifacts. The gate requires these
variables to be available to the process:

```text
DATABASE_URL
WS8_EVAL_DATABASE_URL
RAGFLOW_BASE_URL
RAGFLOW_API_KEY
LLM_BASE_URL
LLM_API_KEY
LLM_MODEL_ALIAS
JWT_HS256_SECRET
```

`WS8_EVAL_DATABASE_URL` must remain the dedicated, migrated evaluation PostgreSQL database;
it must not equal `DATABASE_URL`. The evaluation database must already be at
`0005_run_runtime_envelope`; Task 8 does not create databases or migrations.

The live gate verifies the actual running RAGFlow Docker image and requires exactly
`infiniflow/ragflow:v0.26.4` (registry prefix differences are allowed only when the image name
still contains `infiniflow/ragflow:` and the tag is exactly `v0.26.4`). It also performs the
existing authenticated RAGFlow health/API-shape check.

## What the one-command gate does

```bash
python scripts/run_ws8_evaluation_gates.py \
  --dataset v0 \
  --artifact-root evaluation/artifacts \
  --evaluation-namespace ws8-v0-live-gate
```

When invoked under `uv run python` or the activated `it-agent` interpreter, the gate:

1. verifies all B7 `SHA256SUMS.txt` entries before any measured run;
2. verifies branch `feat/ws8` and records Git HEAD, tracked dirty state and dirty-worktree flag;
3. verifies the actual running RAGFlow image/health/version is `v0.26.4`;
4. creates a temporary `/tmp` Compose override containing placeholders only, never secret
   values;
5. recreates Compose `postgres`, `app-api`, and `app-worker` against the dedicated evaluation
   database and host provider endpoints;
6. verifies the evaluation DB Alembic revision, idempotently prepares and then read-only
   verifies the Task 2 PostgreSQL/RAGFlow fixtures;
7. requires `postgres`, `app-api`, and `app-worker` to be running and healthy and requires
   `GET /ready` to return `status=ready`;
8. executes the full 50-case baseline through the normal Compose API/Worker;
9. rejects missing trials, silent skips, `UNSCORABLE_GOLD`, `INFRA_FAILURE`, and
   `RUNNER_FAILURE`; the frozen coverage contract is 50 selected / 50 trial artifacts /
   3 `UNSCORABLE_RUNTIME_SCOPE` / 47 `SCORED`;
10. emits baseline `metrics.json`, `report.json`, and `report.md` and validates exactly nine
    acceptance metrics;
11. runs the approved live variants `no_exact_registry` and `single_round_only` through an
    explicit evaluation-owned controlled worker using Task 7 composition seams;
12. runs `pre_governance_shadow` and `pre_guard_shadow` offline from baseline artifacts;
13. records matched populations/deltas in the four frozen ablation artifacts;
14. regenerates the canonical post-ablation report, deletes only generated metric/report
    outputs, replays `score` + `report` from saved raw artifacts, and requires semantic equality;
15. restores the normal base Compose API/Worker configuration in a `finally` path, including
    when switching, preflight, runtime, scorer, ablation, or replay fails.

The gate never calls Task 2 cleanup and never deletes `fixture-state.json`.

### Compatibility ruling for the WS7 boundary gate

Task 8 Step 8 requires `scripts/run_ws7_live_gates.py` to run from `feat/ws8`. The accepted
WS7 script originally rejected every branch except `feat/ws7`, so the frozen Task 8 command
would fail before executing any WS7 live gate. A Task 8 RED test proves that conflict. The
minimal compatibility change allows exactly `feat/ws7` or `feat/ws8`; no gate definition,
provider flag, Compose topology, runtime behavior, or safety check is changed.

### Plan ruling for replay ordering

Task 6 reports intentionally include Task 7 ablation artifacts. The frozen Task 8 sequence says
to generate a report before ablations and later compare an offline replay after ablations with
"the first generated outputs". Those two declared input sets are different. Task 8 therefore
retains the Step 4 baseline report as an intermediate check, then refreshes the **canonical
first complete report after all four ablation artifacts exist**. Offline replay is compared with
that canonical complete report. No metric, Gold, or ablation semantics are changed by this
ordering ruling.

## Artifact layout

The baseline uses the existing Task 4 deterministic layout:

```text
evaluation/artifacts/<baseline-run-id>/
  run-manifest.json
  cases/Q001/trial-001.json
  ...
  cases/Q050/trial-001.json
  metrics.json
  ablations/
    no_exact_registry/variant-manifest.json
    no_exact_registry/ablation.json
    single_round_only/variant-manifest.json
    single_round_only/ablation.json
    pre_governance_shadow/ablation.json
    pre_guard_shadow/ablation.json
  report.json
  report.md
```

The two live variants each have their own normal evaluation run directory under
`evaluation/artifacts/`. The baseline ablation JSON records the matched population and variant
run ID.

Secret-safe gate evidence is written to `/tmp/ws8-task8-live-*` unless `--evidence-dir` is
provided. It contains `summary.json` plus canonical/replayed report copies. It must never
contain `.env`, API keys, JWTs, database passwords, private keys, DB dumps, or
`fixture-state.json`.

## Pipeline status versus product status

Task 8 has two independent conclusions:

```text
pipeline_gate_status       PASS | FAILED
product_evaluation_status  PASS | FAIL | UNSCORABLE | NOT_APPLICABLE
```

A product metric below its frozen target does **not** make the technical pipeline fail. The gate
fails on missing/silent cases, invalid raw artifacts, unexpected unscorable Gold, provider or
runner failure, missing approved ablations, invalid metric/report structure, or non-reproducible
replay.

## Required server verification

After installing the Task 8 package, run:

```bash
uv run pytest -q \
  tests/evaluation \
  tests/unit/evaluation \
  tests/integration/evaluation \
  tests/integration/deployment/test_ws8_evaluation_runner.py \
  tests/security/test_evaluation_artifact_sanitization.py

uv run python scripts/run_checks.py
uv run python scripts/run_ws7_live_gates.py
uv run ruff check src tests scripts
uv run mypy src
git diff --check
(cd evaluation/datasets/v0 && sha256sum -c SHA256SUMS.txt)

uv run python scripts/run_ws8_evaluation_gates.py \
  --dataset v0 \
  --artifact-root evaluation/artifacts \
  --evaluation-namespace ws8-v0-live-gate

(cd evaluation/datasets/v0 && sha256sum -c SHA256SUMS.txt)
git status --short
```

Do not describe a skipped provider/live test as PASS. The WS8 Task 8 completion judgment is
only valid after the real server live command exits zero and the final targeted/regression/live/
static/B7 checks are GREEN. Preserve measured product FAILs exactly as emitted.
