# Task 13 — Issue create confirmation and idempotency runbook

## Safety invariants

1. `IssueDraft` is side-effect free.
2. `possible_duplicates` never auto-block creation.
3. `interrupt()` occurs before any create-side effect in the confirmation node.
4. A confirmation is bound to the exact canonical create payload by SHA-256.
5. Project authorization and write-role permission are rechecked immediately before the idempotency barrier.
6. Application idempotency uses `(namespace, request_id)` in `idempotency_records`.
7. Provider idempotency uses `(project_id, client_request_id)` in `sandbox_issues`.
8. A response-loss timeout never triggers an immediate blind duplicate write; it queues `RECONCILE_ISSUE_CREATE`.
9. Reconciliation requires a pre-existing `IN_PROGRESS` idempotency barrier. A bare draft ID can never create an Issue.

## Migration

```bash
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
uv run alembic upgrade head
uv run alembic current
```

Expected head:

```text
0004_issue_create_idempotency (head)
```

Verify provider-side unique request index:

```bash
docker compose exec postgres \
  psql -U project_agent -d project_agent \
  -c "SELECT indexname,indexdef FROM pg_indexes WHERE indexname='uq_sandbox_issues_project_request';"
```

The index must be unique over `project_id, client_request_id` where `client_request_id IS NOT NULL`.

## Confirmation flow

Initial graph invocation pauses at the interrupt and returns a payload containing the draft summary, possible duplicate candidates, `request_id`, `request_payload_hash`, and expiry time.

Resume the same LangGraph thread with a JSON-serializable value equivalent to:

```python
Command(
    resume={
        "action": "confirm",
        "request_payload_hash": "<hash shown by interrupt>",
    }
)
```

Cancel uses `action="cancel"`. A missing or changed payload hash is rejected.

## Response-loss recovery

If the provider commits the Issue but the response is lost:

```text
idempotency_records = IN_PROGRESS
provider issue exists with same client_request_id
worker job = RECONCILE_ISSUE_CREATE(draft_id)
```

The reconciliation handler first calls `get_issue_by_request_id`. If found, it completes the idempotency record and marks the draft `CREATED`. If not found, it may replay the same provider request only because the application barrier already exists and the provider request key is unique.

## Gate 13

```bash
export RUN_POSTGRES_INTEGRATION=1
uv run pytest \
  tests/unit/issues \
  tests/security/test_unconfirmed_issue_create.py \
  tests/security/test_issue_permission_recheck.py \
  tests/security/test_confirmation_payload_binding.py \
  tests/security/test_cancelled_issue_create.py \
  tests/security/test_reconcile_requires_idempotency_barrier.py \
  tests/reliability/test_issue_response_lost.py \
  tests/integration/issues \
  tests/e2e/test_issue_create_interrupt.py \
  -v
```
