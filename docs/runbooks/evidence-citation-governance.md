# Evidence and Citation Governance Runbook

## Purpose

This runbook verifies that a QA answer is produced only from current, authorized and authority-governed evidence snapshots.

## Required invariants

```text
Cross-project Citation = 0
Citation ID validity = 100%
Claim citation coverage = 100%
Non-PUBLISHED final Evidence = 0
Non-current final Evidence = 0
Unresolved explicit conflicts are disclosed
Maximum answer revision = 1
```

## Quick verification

```bash
uv run pytest \
  tests/unit/agent/test_authority_policy.py \
  tests/unit/agent/test_citation_guard.py \
  tests/unit/agent/test_answer_revision.py \
  tests/security/test_cross_project_citation.py \
  -v
```

With PostgreSQL running:

```bash
export RUN_POSTGRES_INTEGRATION=1
uv run pytest tests/integration/evidence -v
```

## Operational interpretation

A high retrieval score is not authority. A document becomes final answer evidence only after project authorization, document/version validity, AuthorityPolicy and snapshot freezing. Citation Guard validates references against that frozen bundle rather than against live RAGFlow output.
