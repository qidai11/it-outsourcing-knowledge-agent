# WS4 — Real Structured LLM + Production QA Runtime — Completion Record

**Status:** COMPLETE
**Date:** 2026-09-17
**Branch:** `feat/ws4-real-structured-llm-qa`
**WS4 starting HEAD:** `ba1f9b3`
**Logical base branch:** `feat/ws2-postgres-acceptance`
**Worktree:** `/home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws4-real-structured-llm-qa`

---

## 1. Completion Summary

WS4 is complete.

The final WS4 acceptance gate passed on the real server environment after completing all three WS4 Big Tasks and resolving the live-provider compatibility issues found during acceptance.

WS4 now provides the V1 production QA path required by the approved design baseline:

- real OpenAI-compatible structured LLM integration;
- structured retrieval grading;
- bounded project-scoped retrieval with at most two retrieval rounds;
- explicit insufficient-evidence refusal;
- project-authorized RAGFlow retrieval;
- canonical RAGFlow dataset binding;
- persisted Evidence / Citation / Answer artifacts;
- production QA runtime executed through the existing WS3 worker path;
- PostgreSQL-backed run persistence and checkpointing;
- real RAGFlow, real structured LLM, PostgreSQL, and worker live acceptance.

No WS5+ scope was intentionally pulled into WS4.

---

## 2. Source-of-Truth Constraints Preserved

WS4 continued to follow the approved V1 design and architecture lock.

The implementation did **not** introduce:

- Redis;
- Celery;
- MinIO;
- a second vector database;
- a new multi-agent architecture;
- a unified LangGraph rewrite;
- production Jira/SaaS integrations;
- Kubernetes;
- an additional database migration beyond the existing WS2/WS3 runtime envelope.

Alembic remains at:

`0005_run_runtime_envelope`

WS3 execution semantics remain the execution entrance for production runs.

---

## 3. Big Task 1 — Real Structured LLM + Bounded QA Retrieval Core

**Status:** COMPLETE

Implemented and verified:

- OpenAI-compatible structured HTTP LLM adapter;
- JSON Schema structured output;
- request timeout / retry handling;
- provider error sanitization;
- token / usage accounting;
- `RetrievalGrade` structured schema and node;
- bounded QA retrieval;
- maximum two retrieval rounds;
- refined second-round query support;
- identical authorization scope across first and second retrieval rounds;
- insufficient-evidence refusal after bounded retrieval;
- project-scoped evidence handling.

The provider-facing answer schema was later tightened during live acceptance so each generated claim must explicitly contain at least one evidence ID before the result can enter the domain answer model.

Citation Guard semantics were not weakened.

---

## 4. Big Task 2 — Canonical RAGFlow Scope + Production QA Runtime Wiring

**Status:** COMPLETE

Implemented and verified:

- canonical provider-facing project scope based on project code;
- explicit authorized RAGFlow dataset binding;
- worker retrieval does not guess project/dataset bindings;
- `ProductionQARunExecutor`;
- per-run SQLAlchemy `AsyncSession`;
- reuse of existing authorization, identifier, prompt, evidence, citation, and graph-store layers;
- PostgreSQL-backed production QA execution;
- commit / rollback semantics;
- resume rejection where required by the approved WS4 scope;
- `build_worker_runtime()` production wiring;
- preservation of WS3 Execute / Resume handler entry points.

No new migration was required.

---

## 5. Big Task 3 — Real Provider / RAGFlow / PostgreSQL / Worker Acceptance

**Status:** COMPLETE

The final live acceptance covered:

### Real Structured LLM

Verified the configured OpenAI-compatible provider using the production structured-output adapter.

### Real RAGFlow

Verified real dataset creation, ingestion, parsing, retrieval, project isolation, and cleanup.

During live acceptance, the following RAGFlow compatibility issues were found and resolved:

1. name-filter dataset lookup could return RAGFlow code 102 on the deployed instance;
2. dataset discovery was changed to enumerate the current tenant's visible datasets and perform exact local matching before creation;
3. live datasets use unique names to avoid shared-instance collisions;
4. the live test now wires `RAGFLOW_EMBEDDING_MODEL` into the adapter when explicitly configured;
5. the RAGFlow tenant must have a working default embedding model or an explicit configured embedding model.

### PostgreSQL QA Runtime

Verified the PostgreSQL-backed production QA runtime, durable run state, artifacts, events, evidence, citations, and worker queue integration.

### Real End-to-End QA Worker

Verified the complete production path:

`PostgreSQL durable job -> WS3 BackgroundWorker -> ExecuteAgentRunHandler -> ProductionQARunExecutor -> PostgreSQL LangGraph saver -> authorization -> real RAGFlow -> real structured LLM -> Evidence/Citation/Answer persistence`

The live test verifies both:

- an answerable project-scoped case;
- a no-authorized-evidence refusal case.

For the no-authorized-evidence path, the correct frozen safety behavior is:

- zero provider retrieval calls;
- `retrieval_rounds == 0`;
- zero LLM token usage;
- terminal `NO_AUTHORIZED_EVIDENCE` refusal.

---

## 6. Live-Acceptance Defects Resolved

The final acceptance process identified and resolved several issues that were not visible in offline-only testing.

### RAGFlow dataset lookup / permission behavior

The deployed RAGFlow instance returned code 102 for name-filter dataset lookup in cases where the requested dataset was not visible to the current tenant.

The production adapter was changed to enumerate visible datasets and perform exact local matching instead of relying on the problematic name-filter existence probe.

### RAGFlow embedding model configuration

Real document parsing exposed the RAGFlow server error:

`No default embedding model is set.`

The live integration test now correctly forwards the configured `RAGFLOW_EMBEDDING_MODEL`, while still supporting the RAGFlow tenant default when no explicit model is configured.

### Structured-answer citation contract

Real LLM acceptance demonstrated that the original provider-facing answer schema allowed a claim to omit `evidence_ids`, which Pydantic could normalize to an empty collection.

This produced a legitimate Citation Guard failure:

`UNCITED_CLAIM`

The provider-facing structured answer schema was tightened so:

- every claim must contain `evidence_ids`;
- `evidence_ids` must contain at least one entry;
- the answer must contain at least one claim.

The domain model and Citation Guard remain defense-in-depth controls.

### E2E response-model-name coupling

An E2E test was coupled to the internal response-model class name `GroundedAnswerDraft`.

After the provider-facing schema was intentionally tightened to an internal structured model, the E2E assertion was changed to verify the real behavior instead:

- two retrieval-grade calls;
- exactly one answer-generation call;
- the correct answer request ID.

The test no longer depends on an internal private class name.

---

## 7. Final Acceptance Evidence

The final WS4 acceptance gate was executed on the real WS4 worktree with:

- `RUN_POSTGRES_INTEGRATION=1`;
- `RUN_RAGFLOW_INTEGRATION=1`;
- `RUN_LLM_INTEGRATION=1`;
- real PostgreSQL;
- real RAGFlow;
- real structured LLM provider.

The user-reported final gate result was **PASS for all stages**.

Verified gate categories:

| Gate | Result |
|---|---|
| WS4 branch / environment check | PASS |
| required live configuration | PASS |
| Ruff | PASS |
| MyPy | PASS |
| `git diff --check` | PASS |
| Alembic compatibility / expected head | PASS |
| real Structured LLM integration | PASS |
| real RAGFlow project-isolation integration | PASS |
| PostgreSQL QA runtime integration | PASS |
| real end-to-end QA Worker integration | PASS |
| combined WS4 live acceptance | PASS |
| full regression | PASS |
| final static recheck | PASS |
| secret / generated-artifact guard | PASS |

Final full regression completed with **0 failures**.

---

## 8. Operational Configuration Required for Live QA

A live WS4 deployment requires the environment to provide the existing project settings for:

- PostgreSQL `DATABASE_URL`;
- RAGFlow base URL and API key;
- a usable RAGFlow embedding model, either as the tenant default or through `RAGFLOW_EMBEDDING_MODEL`;
- OpenAI-compatible LLM base URL;
- LLM API key;
- LLM model alias.

A new SSH shell must reload `.env` when the live tests or runtime depend on shell environment variables, for example:

```bash
set -a
source .env
set +a
```

Secrets remain outside Git.

---

## 9. Completion Decision

The three WS4 Big Tasks are complete:

| Work item | Status |
|---|---|
| Big Task 1 — Real Structured LLM + bounded QA retrieval core | COMPLETE |
| Big Task 2 — Canonical RAGFlow scope + production QA runtime wiring | COMPLETE |
| Big Task 3 — Real provider / RAGFlow / PostgreSQL / Worker acceptance | COMPLETE |

Final phase judgment:

- **需求完成：✅**
- **测试闭环：✅**
- **新 bug：未发现**
- **WS4 implementation acceptance：✅**
- **WS4 formal close-out：✅ pending only Git integration choice**

No additional WS4 feature coding is required before branch integration.

---

## 10. Post-Completion Boundary

The following work belongs to later workstreams and must not be retroactively added to WS4 unless the approved V1 plan is explicitly changed:

- evaluation dataset construction and formal evaluation runs;
- additional production observability beyond the frozen WS4 scope;
- broader external-system integrations;
- deployment/platform work outside the architecture lock;
- later V1 workstreams.

WS4 should now be closed as a completed implementation branch and integrated using the normal branch-finishing workflow.
