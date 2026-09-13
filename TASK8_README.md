# Task 8 — PostgreSQL Job Queue and Worker

## Scope

- PostgreSQL queue with `FOR UPDATE SKIP LOCKED`
- aggregate-only Job payload (`aggregate_id`)
- lease + heartbeat
- exponential retry + max attempts
- expired lease Reaper
- RAGFlow parse semaphore (default 2)
- process-local model TokenBucket
- Prompt config short-TTL snapshots
- RETENTION_SWEEP, dry-run by default

## Live Gate

```bash
export RUN_POSTGRES_INTEGRATION=1
uv run alembic upgrade head
uv run pytest tests/unit/workers tests/integration/jobs tests/integration/config \
  tests/reliability/test_worker_crash.py tests/reliability/test_retention_safety.py -v
```

Expected on a live PostgreSQL instance: no skipped PostgreSQL queue tests.
