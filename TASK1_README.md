# Task 1 — Engineering Baseline Increment Package

## Scope

This package implements only the V3.2 Task 1 engineering baseline:

- Python 3.12 project metadata;
- Settings / `.env` configuration;
- staging in-memory database rejection;
- FastAPI app factory;
- `/live` and `/ready`;
- unit + integration tests;
- Ruff / MyPy / Pytest configuration;
- Makefile;
- GitHub Actions CI;
- unified local quality-gate script.

It does **not** connect to PostgreSQL, RAGFlow, or a real LLM.

## Apply

Copy/extract this package into the repository root, preserving paths.

Then:

```bash
conda activate it-agent
cd ~/workspace/it-outsourcing-knowledge-agent

cp .env.example .env
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"

uv lock
uv sync --all-groups
python scripts/run_checks.py
```

Run the API:

```bash
uv run uvicorn project_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify:

```bash
curl http://127.0.0.1:8000/live
curl http://127.0.0.1:8000/ready
```

Expected:

```json
{"status":"ok"}
```

```json
{"status":"ready","configuration":"ok"}
```

## Commit

```bash
git add .
git commit -m "chore: bootstrap compact project agent"
```

## Gate 1

Task 1 tests use injected fake configuration only. They make no request to a real RAGFlow server or LLM endpoint.
