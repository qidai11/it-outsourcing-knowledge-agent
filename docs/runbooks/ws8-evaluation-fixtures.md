# WS8 Task 2 — Evaluation Fixture Preparation (B7 V0)

This runbook covers **only** the evaluation-owned fixture lifecycle: `prepare`,
`verify`, and `cleanup`. It does not modify the B7 dataset, production JWT
verification, production authorization, fixture materialization, or RAGFlow
adapter. All measured API/Run operations still use the existing Runtime
Envelope and current PostgreSQL memberships.

## Preconditions and safety

Operate from the **complete server** `feat/ws8` worktree, not an extracted
subset of the handoff ZIP. The handoff ZIP includes the WS8-relevant snapshot,
but the server also contains `project_agent.config`, runtime, and other modules
not included in that snapshot. Retain those server files.

```bash
cd /home1/ckx/workspace/it-outsourcing-knowledge-agent/.worktrees/ws8
conda activate it-agent
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export RUN_POSTGRES_INTEGRATION=1
# Reuse your ALREADY PROVISIONED, migrated, isolated evaluation PostgreSQL DB.
# Set the actual private value locally; do not commit/print it.
: "${WS8_EVAL_DATABASE_URL:?Set the already-provisioned evaluation DB URL}"
# DATABASE_URL identifies the primary DB and must NOT match WS8_EVAL_DATABASE_URL.
: "${DATABASE_URL:?Keep the primary DB URL available for isolation checks}"
```

`WS8_EVAL_DATABASE_URL` **must** point to a dedicated PostgreSQL database whose
name contains `eval` and whose host/port/database tuple differs from
`DATABASE_URL` even if the driver or database username differ. The CLI never
creates databases or applies migrations. Confirm the existing eval database is
already at Alembic head `0005_run_runtime_envelope`. Do **not** run these
commands against the main application database. Do not edit any B7 input files.

Install the new console-script entry point in the existing environment without
changing installed dependency versions:

```bash
python -m pip install -e . --no-deps
project-agent-eval-prepare --help
# Equivalent without reinstalling console scripts:
python -m project_agent.cli.evaluation_prepare --help
```

## 1. Prepare — isolated PostgreSQL + optional RAGFlow

Use a **unique single-segment namespace**. The same namespace is idempotent
when the frozen input bytes, database and provider state are unchanged.

```bash
export WS8_NS="ws8-v0-acceptance-001"
# PostgreSQL-only, with no provider datasets:
project-agent-eval-prepare prepare \
  --evaluation-namespace "$WS8_NS" \
  --dataset-root evaluation/datasets/v0 \
  --artifact-root evaluation/artifacts
```

For a complete B7 fixture including **dedicated** RAGFlow datasets, first
configure credentials in the current shell. `--with-ragflow` is explicit: it
never binds or deletes baseline developer datasets.

```bash
: "${RAGFLOW_BASE_URL:?Set the existing RAGFlow URL}"
: "${RAGFLOW_API_KEY:?Set the existing RAGFlow API key}"
# Optional: export RAGFLOW_EMBEDDING_MODEL=<existing RAGFlow model alias>
export RUN_RAGFLOW_INTEGRATION=1
project-agent-eval-prepare prepare \
  --evaluation-namespace "$WS8_NS" \
  --dataset-root evaluation/datasets/v0 \
  --artifact-root evaluation/artifacts \
  --with-ragflow
```

The CLI delegates materialization to the **existing** `evaluation.fixtures.prepare_v0`
service and reads upload bytes from the frozen manifest through a read-only
object store. Its only generated local artifact is:

```text
evaluation/artifacts/<evaluation-namespace>/fixture-state.json
```

This state records `company_id`, `client_ids`, `project_ids`, `user_ids`,
`membership_ids`, `document_ids`, `document_version_ids`,
`knowledge_space_ids`, `ragflow_documents`, `sandbox_issue_ids`, and frozen
`integrity` hashes. `doc_code` to provider/document/version mappings remain in
this artifact, **never** in newly invented production database columns.
The `company-public` corpus is not given a fake project Run scope (Q046).

If provider preparation fails midway, the PostgreSQL transaction can roll
back while RAGFlow datasets remain. **Do not rerun blindly or delete by
name.** When `fixture-state.json` is missing and existing names match the
same namespace, CLI `prepare` fails closed before mutating the provider. Use
a read-only provider listing and the original failure log to establish the
exact dataset ID, project scope and `description` of each orphan. Recovery
requires the exact operator-supplied ID for **every** existing evaluation
project dataset; it does not infer ownership from a matching name alone.

For example, after checking the IDs and expected scope descriptions:

```bash
# Substitute the exact IDs obtained from your own read-only provider audit.
export RETAIL_PROVIDER_ID='<verified-retail-provider-id>'
export LOGISTICS_PROVIDER_ID='<verified-logistics-provider-id>'
# Retry with the same namespace and unchanged frozen dataset.
project-agent-eval-prepare prepare \
  --evaluation-namespace "$WS8_NS" \
  --with-ragflow \
  --recover-dataset "PRJ-RETAIL-ALPHA=$RETAIL_PROVIDER_ID" \
  --recover-dataset "PRJ-LOGISTICS-BETA=$LOGISTICS_PROVIDER_ID"
project-agent-eval-prepare verify \
  --evaluation-namespace "$WS8_NS" \
  --with-ragflow
```

This read-only preflight requires exact names and IDs plus the project's
`Managed by project-agent for scope <project-UUID>` description. Extra,
missing, duplicate or unowned datasets are rejected **before** prepare.
The ordinary `prepare` operation then reuses those provider IDs and writes
normal, hash-verified `fixture-state.json`; cleanup remains the existing
state-backed, explicitly confirmed operation. If the provider omits or
changes the ownership description, stop and inspect it manually; never
fabricate a state file or use a wildcard delete. Do not retry a partial
provider recovery using a new namespace.

## 2. Verify — read-only checks

```bash
# Prepared without RAGFlow:
project-agent-eval-prepare verify \
  --evaluation-namespace "$WS8_NS"

# Prepared with RAGFlow (also checks recorded provider IDs/metadata):
project-agent-eval-prepare verify \
  --evaluation-namespace "$WS8_NS" \
  --with-ragflow
```

Verification performs no materialization or deletion. It checks the state
namespace/UUIDv5 ownership, fixture and corpus bytes against B7 hashes,
identity/membership/issue mappings, frozen document mappings, current eval
PostgreSQL project and row presence, and (when requested) provider dataset,
provider document, project and version metadata. A PostgreSQL-only verify
**does not** claim that RAGFlow was checked. If a hash or ownership check fails,
stop; do not overwrite the state to force cleanup.

## 3. Evaluation JWT — identity only, never an artifact

Use `evaluation.auth.mint_fixture_identity_jwt` in the evaluation client or a
short-lived in-memory process, with the **existing production API's** HS256
configuration (`JWT_HS256_SECRET`, `JWT_ISSUER`, `JWT_AUDIENCE`, exposed by the
server's `Settings` object):

```python
import json
from pathlib import Path
from project_agent.config import Settings
from project_agent.evaluation.auth import mint_fixture_identity_jwt

settings = Settings()  # use the same settings as the target API
state = json.loads(Path("evaluation/artifacts/ws8-v0-acceptance-001/fixture-state.json").read_text())
token = mint_fixture_identity_jwt(
    state=state,
    user_alias="u-alpha-viewer",  # use an alias present in frozen identities.json
    secret=settings.jwt_hs256_secret.get_secret_value(),
    issuer=settings.jwt_issuer,
    audience=settings.jwt_audience,
    expires_in_seconds=900,
)
# Keep token only in process memory; pass it to the API client over HTTPS.
# Never print it, persist it to fixture-state.json, log Authorization, or
# place it in a raw trial artifact. PostgreSQL membership grants authorization.
```

The helper signs HS256 and includes only `sub` plus `iss`, `aud`, `iat`, `nbf`
and `exp`. No `role`, `project_ids`, company, or document permission can be
trusted from the JWT. Short-lived tokens are reissued as needed.

## 4. Cleanup — explicit and namespace-scoped

Only after verifying the exact generated state and identifying all evaluation
resources for this namespace:

```bash
# For PostgreSQL-only state:
project-agent-eval-prepare cleanup \
  --evaluation-namespace "$WS8_NS" \
  --confirm-cleanup

# For state with RAGFlow resources:
project-agent-eval-prepare cleanup \
  --evaluation-namespace "$WS8_NS" \
  --with-ragflow \
  --confirm-cleanup
```

Cleanup refuses missing state, wrong namespace, changed frozen hashes,
non-evaluation DBs, and provider-backed states without `--with-ragflow`.
It validates eval project ownership and delegates scoped deletion to existing
`evaluation.fixtures.cleanup_v0` and the existing RAGFlow adapter's ownership
checks. It removes the state file **only after** the owned-resource cleanup
returns successfully. Never use an unfiltered `DELETE`, `DROP DATABASE`, or
RAGFlow dataset-name-only deletion.

## 5. Task 2 CHECK — run on the complete server, not the handoff subset

Run the smallest gates first. Do not interpret a skipped live test as PASS.

```bash
# New offline contracts and existing WS8 unit-level behavior
python -m pytest -q \
  tests/unit/evaluation/test_auth.py \
  tests/unit/evaluation/test_evaluation_prepare_cli.py \
  tests/unit/evaluation/test_fixture_runbook.py \
  tests/unit/evaluation/test_fixture_ids.py \
  tests/unit/evaluation/test_dataset.py \
  tests/unit/evaluation/test_artifacts.py

# PostgreSQL LIVE (already migrated, dedicated eval DB)
RUN_POSTGRES_INTEGRATION=1 python -m pytest -q \
  tests/integration/evaluation/test_fixture_preparation_postgres.py

# RAGFlow LIVE (same dedicated eval DB, existing RAGFlow service)
RUN_POSTGRES_INTEGRATION=1 RUN_RAGFLOW_INTEGRATION=1 python -m pytest -q \
  tests/integration/evaluation/test_fixture_preparation_ragflow.py

# Quality gates, then ONLY AFTER those pass consider Task 2 Full Acceptance
ruff check src/project_agent/evaluation src/project_agent/cli/evaluation_prepare.py \
  tests/unit/evaluation tests/integration/evaluation
mypy src
python -m pytest -q tests/evaluation/test_benchmark_v0_contract.py tests/unit/evaluation
git diff --check
```

The ZIP was assembled outside the server, so these live results and the
server-wide Ruff/MyPy/full acceptance remain **unverified** until executed
against the complete, provisioned `feat/ws8` checkout. Archive the actual logs
and hashes before marking Task 2 COMPLETE.
