# Task 13 — Issue Draft, explicit confirmation, and idempotent creation

## Goal

Task 13 is the first stage that permits an Agent-initiated write to the Sandbox ProjectTracker. The write path is intentionally narrower than the read path:

```text
Task 12 possible_duplicates
→ IssueDraft
→ exact payload hash
→ LangGraph interrupt
→ explicit confirm/cancel
→ project permission re-check
→ durable idempotency barrier
→ Sandbox create_issue
→ CREATED or PENDING_RECONCILIATION
```

A draft, ranking score, or model suggestion can never create an Issue by itself.

## New modules

```text
src/project_agent/domain/issues.py
src/project_agent/application/ports/issue_workflow.py
src/project_agent/application/services/issue_drafts.py
src/project_agent/application/services/issue_confirmation.py
src/project_agent/application/services/issue_creation.py
src/project_agent/agent/nodes/build_issue_draft.py
src/project_agent/agent/nodes/confirm_issue_create.py
src/project_agent/agent/nodes/execute_issue_create.py
src/project_agent/agent/issue_graph.py
src/project_agent/infrastructure/db/repositories/issue_workflow.py
src/project_agent/workers/issue_reconciliation.py
migrations/versions/0004_issue_create_idempotency.py
```

## Draft semantics

`IssueDraftService` builds a deterministic proposed draft from the user text and Task 12 candidates. It persists candidate links only after a real `issue_draft_id` exists. The existing `issue_candidates.score NUMERIC(8,6)` stores the optional bounded semantic score (`0..1`), not the Task 12 display/ranking score, which can exceed 1000. Deterministic ranking remains represented by `rank` and `reasons_json`.

Draft states used in Task 13:

```text
DRAFT → CONFIRMED → CREATED
  └────→ CANCELLED
```

## Explicit confirmation

`confirm_issue_create_node` prepares a canonical `CreateIssueRequest`, hashes it with SHA-256, and then calls LangGraph `interrupt()` before any confirmation or tool-write persistence.

The resume payload must echo the displayed hash:

```json
{
  "action": "confirm",
  "request_payload_hash": "..."
}
```

The confirmation is bound to:

- project ID;
- draft/request ID;
- title and description;
- issue type and priority;
- reporter;
- module/error code/environment.

Changing the draft after confirmation invalidates the confirmation.

Default confirmation TTL is 900 seconds and can be configured with:

```dotenv
TOOL_CONFIRMATION_TTL_SECONDS=900
```

## Permission re-check

A confirmation is not authorization. Immediately before the idempotency barrier, Task 13 reconstructs the current project authorization from PostgreSQL. V1 create roles are:

```text
project_manager
developer
qa
implementation
support
```

`viewer` cannot create an Issue even if a confirmation exists. If membership is revoked between confirmation and execution, the write is denied.

## Two-layer idempotency

### Application barrier

```text
namespace = sandbox_issue_create
request_id = issue_draft.id
```

The unique `(namespace, request_id)` row in `idempotency_records` is durably reserved as `IN_PROGRESS` before the external/provider write.

### Provider barrier

Migration `0004_issue_create_idempotency` adds:

```sql
CREATE UNIQUE INDEX uq_sandbox_issues_project_request
ON sandbox_issues(project_id, client_request_id)
WHERE client_request_id IS NOT NULL;
```

The Sandbox adapter uses PostgreSQL `ON CONFLICT DO NOTHING` and then reconciles by request ID, so concurrent/replayed provider calls cannot create a second row for the same project request.

## Response-lost semantics

A timeout after the provider may have committed is an uncertain outcome, not a normal failure:

```text
create_issue
→ timeout / response lost
→ leave idempotency IN_PROGRESS
→ enqueue RECONCILE_ISSUE_CREATE(draft_id)
```

The worker first looks up the provider resource by the same request ID. It does not invent a new request ID.

Reconciliation itself is protected: without an existing `IN_PROGRESS` idempotency record, a reconciliation job is rejected and cannot create anything.

## Database impact

Business table count remains 28. Task 13 adds no table, but advances Alembic head to:

```text
0004_issue_create_idempotency
```

## Local gate

Without live PostgreSQL/LangGraph, the implementation gate verifies pure business behavior and leaves online tests skipped. With the real services enabled:

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

Then run:

```bash
uv run ruff check src tests
uv run mypy src
python scripts/run_checks.py
```
