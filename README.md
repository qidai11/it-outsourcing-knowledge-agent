# IT Outsourcing Knowledge and Ticket Collaboration Agent

面向 IT 外包交付场景的多项目知识与工单协同 Agent。

## Current status

```text
Task 0 engineering baseline       : complete
Task 0 real-business validation   : pending
Task 1 engineering baseline       : complete
Task 2 PostgreSQL schema/domain   : implemented; live PostgreSQL gate runs on dev server
Task 3 ports/test doubles         : implemented
Task 4 local source object store  : implemented
Task 5 RAGFlow adapter/datasets   : implemented; live RAGFlow gate pending
Task 6 document publication       : implemented; human-governed metadata/lifecycle gate passed
Task 7 identifier registry        : implemented; exact B-tree path + pg_trgm suggestions
Task 8 PostgreSQL worker           : implemented; live PostgreSQL gate on dev server
Task 9 authorization primitives   : implemented; membership-derived least-privilege scope
WS1 FastAPI auth/runtime wiring     : implemented; offline gate PASS
WS1 live PostgreSQL API gate       : PENDING (requires RUN_POSTGRES_INTEGRATION=1)
Task 10 minimal QA graph           : implemented; LangGraph runtime gate requires synced deps
Task 11 authority/citation guard    : implemented; live PostgreSQL evidence gate on dev server
Task 12 sandbox issue candidates    : implemented; project-scoped read-only candidate retrieval
```

## V1 technical direction

```text
FastAPI
+ LangGraph
+ PostgreSQL
+ PostgreSQL Job Queue
+ RAGFlow
+ LocalFileObjectStoreAdapter
+ SandboxProjectTrackerAdapter
```

Task 4 implements secure local source-file storage. Task 5 adds the project-isolated RAGFlow adapter. Task 6 connects source storage, human-confirmed metadata, document lifecycle, PostgreSQL persistence, and RAGFlow publication semantics. Task 7 adds deterministic identifier extraction and a project-scoped exact registry: exact hits use the PostgreSQL B-tree path, while pg_trgm is restricted to spelling suggestions. AI/rules only prefill metadata; they cannot approve authority or publish documents. A real chat LLM and production Jira/禅道/飞书项目 are still not connected.

## Development

```bash
conda activate it-agent
cd ~/workspace/it-outsourcing-knowledge-agent
cp .env.example .env
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"
uv lock
uv sync --all-groups
python scripts/run_checks.py
```

## Run API

```bash
uv run uvicorn project_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

Health probes:

```text
GET /live
GET /ready
```

## Task 3 contracts

```text
KnowledgeIngestionPort
KnowledgeRetrievalPort
KnowledgeAdminPort
ObjectStorePort
ProjectTrackerPort
JobQueuePort
StructuredLLMPort
```

See `TASK12_README.md` for Sandbox Issue candidate Gate 12, `TASK11_README.md` for Authority/Evidence/Citation Gate 11, and `docs/runbooks/ragflow-baseline.md` for the live RAGFlow baseline.

## Task 8 — PostgreSQL Job Queue and Worker

Task 8 adds the single-node background execution layer without Redis/Celery:

- PostgreSQL `FOR UPDATE SKIP LOCKED` job claiming;
- aggregate-only job input (`aggregate_id`);
- lease, heartbeat, Reaper and bounded exponential retry;
- configurable parse concurrency limiter (default 2);
- process-local model token buckets;
- short-TTL prompt snapshots from `system_configs`;
- safety-first `RETENTION_SWEEP`, dry-run by default.

Live PostgreSQL queue checks remain opt-in via `RUN_POSTGRES_INTEGRATION=1`.


## Task 9 — Project Authorization

The V1 authorization path now treats JWT as authentication-only and rebuilds authorization from PostgreSQL:

```text
Verified JWT sub
→ active ProjectMembership
→ ProjectAccessScope
→ PUBLISHED document versions + active knowledge spaces
→ retrieval down-push
→ Evidence post-filter
```

Cross-project evidence and unverifiable provider chunks are dropped before they can enter later Agent stages.

WS1 adds the production FastAPI runtime/authentication envelope for document write operations: Bearer JWT establishes only `user_id`, every protected request reloads current `ProjectMembership`, and document permissions are derived server-side. The WS1 offline gate passes in the implementation environment; the real PostgreSQL API revocation gate remains PENDING until explicitly run with `RUN_POSTGRES_INTEGRATION=1`.

## Task 10 — Minimal Project QA Graph

Task 10 introduces the first LangGraph workflow while keeping business rules deterministic:

```text
Prompt Snapshot
→ Query Analysis
→ Project Selection / Authorization
→ Exact Identifier Registry
→ constrained RAGFlow Retrieval
→ ACL post-filter
→ refusal or structured answer
```

Graph checkpoints store reference IDs rather than query/Evidence/answer payloads. PostgreSQL `AsyncPostgresSaver` provides durable checkpoints, while `agent_runs` records the model alias, Prompt version/hash, token totals and retrieval rounds.

## Task 11 — Authority, Evidence Snapshot and Citation Guard

Task 11 upgrades authorized retrieval candidates into frozen answer evidence:

```text
ACL-filtered Retrieval
→ Authority/current/effective filter
→ Evidence Packing
→ Frozen Snapshot
→ claim-level grounded answer
→ deterministic Citation Guard
→ one bounded revision or refusal
```

Final answers persist `citations → evidence_snapshots`; retrieval score never overrides the manually selected Authority level, and unresolved explicit conflicts must be disclosed rather than silently resolved by the model.


## Task 12 — Sandbox Issue Candidate Retrieval

Task 12 activates the PostgreSQL-backed `SandboxProjectTrackerAdapter` for read-only Agent use:

```text
Authorized project scope
→ same-project Sandbox issues
→ exact error/module + keyword/status ranking
→ possible_duplicates
→ user chooses view/link/continue/cancel
```

No Agent node calls `create_issue` in Task 12. A similar historical Issue is evidence for a user decision, not an automatic duplicate verdict.

## Task 13 — Explicitly confirmed, idempotent Issue creation

Task 13 turns the Task 12 candidate flow into the first controlled write path:

```text
possible_duplicates
→ IssueDraft
→ payload-bound LangGraph interrupt
→ explicit user confirmation
→ permission re-check
→ durable idempotency barrier
→ Sandbox create
→ response-loss reconciliation
```

No confirmation means zero create-side effects. The application key is `(sandbox_issue_create, issue_draft_id)`, while the Sandbox provider independently enforces unique `(project_id, client_request_id)`. A reconciliation job cannot create anything unless the confirmed execution path already established an `IN_PROGRESS` idempotency record.

See `TASK13_README.md` and `docs/runbooks/issue-create-idempotency.md`.
