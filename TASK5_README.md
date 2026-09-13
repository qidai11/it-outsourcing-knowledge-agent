# Task 5 — RAGFlow Adapter 与项目 Dataset

## Scope

Task 5 adds the RAGFlow provider adapter only:

- pinned RAGFlow baseline `v0.26.4`;
- baseline datasets;
- shared async HTTP client boundary;
- bounded transient retries;
- document metadata mapping to `document_version_id`;
- project/dataset defense-in-depth filtering;
- contract tests and opt-in real integration test.

It does **not** implement the Task 6 document-governance ingestion workflow, LangGraph orchestration, or a real LLM.

## Local gate

```bash
uv run pytest tests/contract/ragflow -v
```

## Live gate

See:

```text
docs/runbooks/ragflow-baseline.md
```

Then run:

```bash
RUN_RAGFLOW_INTEGRATION=1 uv run pytest tests/integration/ragflow -v
```

## Status interpretation

```text
TASK5_IMPLEMENTATION = COMPLETE      # after contract tests pass
TASK5_LIVE_RAGFLOW_GATE = PASS       # only after real integration test passes
```
