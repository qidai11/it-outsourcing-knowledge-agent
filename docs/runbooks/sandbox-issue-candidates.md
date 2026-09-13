# Sandbox Issue Candidate Runbook

## Seed

```bash
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
uv run alembic upgrade head
uv run python scripts/seed_sandbox_issues.py
```

The seed is idempotent for the fixed simulated project codes and Issue keys.

## Inspect

```bash
docker compose exec postgres \
  psql -U project_agent -d project_agent \
  -c "SELECT p.code, i.issue_key, i.error_code, i.module, i.status, i.title
      FROM sandbox_issues i
      JOIN projects p ON p.id = i.project_id
      ORDER BY p.code, i.issue_key;"
```

Expected business property: both simulated projects deliberately reuse identifiers such as
`ERR-IMPORT-004`, but a query scoped to one project must never return rows from the other.

## Gate

```bash
export RUN_POSTGRES_INTEGRATION=1
uv run pytest tests/contract/project_tracker tests/e2e/test_issue_candidates.py -v
```

Task 12 is read-only at the Agent layer. A populated `possible_duplicates` list must still
include `continue_create`; there is no `duplicate=true` field and no call to `create_issue`.
