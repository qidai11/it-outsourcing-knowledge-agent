# WS7 Docker Compose Live Acceptance Gates

This runbook is the operator path for the final WS7 live acceptance. It assumes the WS7 branch is `feat/ws7`, Task 2 has already produced the three-service Compose topology, companion RAGFlow is reachable on the host, and `.env` contains the real provider credentials used by the acceptance environment.

## Required operator sequence

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

The required runner performs prerequisite checks before the first mandatory gate. It records the branch, HEAD, and current short Git status, requires Docker/Compose plus healthy `postgres`, `app-api`, and `app-worker`, checks host RAGFlow, API `/live`, API `/ready`, and Worker `/metrics`, and requires all PostgreSQL/RAGFlow/LLM/JWT configuration values needed by the live gates.

The runner temporarily isolates the Compose Worker while host-side PostgreSQL/provider tests create their own Worker instances. This avoids a second Worker consuming the same PostgreSQL test queue and avoids host port `9101` contention. The Compose Worker is restored and required to become healthy before the real Compose QA and Issue process-boundary tests run.

## PASS contract

A WS7 PASS requires all mandatory groups to execute with zero failures and **zero skips**:

```text
postgres_runtime PASS
ragflow PASS
structured_llm PASS
qa_provider_runtime PASS
compose_qa PASS
compose_issue PASS
WS7 PASS
```

A missing prerequisite, non-zero command result, or mandatory pytest skip makes the run `FAILED` or `INCOMPLETE` and the runner returns non-zero. A skipped provider/live test is not acceptance evidence.

## Evidence

Every invocation writes bounded evidence under:

```text
artifacts/ws7-live/<UTC-run-id>/summary.json
artifacts/ws7-live/<UTC-run-id>/postgres_runtime.log
artifacts/ws7-live/<UTC-run-id>/ragflow.log
artifacts/ws7-live/<UTC-run-id>/structured_llm.log
artifacts/ws7-live/<UTC-run-id>/qa_provider_runtime.log
artifacts/ws7-live/<UTC-run-id>/compose_qa.log
artifacts/ws7-live/<UTC-run-id>/compose_issue.log
```

Inspect `summary.json` after the command. A completion-quality summary has `status: "PASS"`, branch `feat/ws7`, all six required gate names, every gate status `PASS`, and every `skipped` count equal to `0`.

The evidence directory is ignored by Git. Never copy `.env`, raw API keys, JWT secrets, Authorization headers, password-bearing database URLs, provider request bodies, or other credentials into evidence. The runner sanitizes mandatory gate output before persistence, but operators must still avoid adding secret-bearing files manually.

## Schema and service verification

After the required runner passes, verify:

```bash
docker compose run --rm app-api alembic current
docker compose ps
git status --short
git diff --check
```

The migration head must remain:

```text
0005_run_runtime_envelope (head)
```

`postgres`, `app-api`, and `app-worker` must be running and healthy. No WS7 live evidence file should appear in `git status`.

## Cleanup

Routine acceptance may leave the three Compose services running for inspection. Optional non-destructive cleanup is:

```bash
docker compose down
```

Do **not** use this as routine cleanup:

```bash
docker compose down -v
```

`-v` removes Compose volumes and is destructive to the acceptance PostgreSQL/application data.
