"""WS8 evaluation fixture preparation, read-only verification, and owned cleanup.

Only the existing evaluation fixture service mutates PostgreSQL/RAGFlow.  This
CLI validates the frozen input, checks ownership, and writes secret-safe state.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from project_agent.application.ports.object_store import (
    ObjectPayload,
    PutObjectRequest,
    StoredObject,
)
from project_agent.evaluation.artifacts import ArtifactStore
from project_agent.evaluation.dataset import EvaluationDataset, load_evaluation_dataset

if TYPE_CHECKING:
    from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
    from project_agent.infrastructure.ragflow.client import RagflowHttpClient

_PROJECT_CODES = ("PRJ-RETAIL-ALPHA", "PRJ-LOGISTICS-BETA")
_NAMESPACE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


def validate_namespace(value: str) -> str:
    """Use one single evaluation-owned segment, never a path or provider wildcard."""
    if value in {".", ".."} or not _NAMESPACE_PATTERN.fullmatch(value):
        raise ValueError("invalid evaluation namespace (use letters, digits, dots, _ or -)")
    return value


def _db_target(url: URL) -> tuple[str, int, str | None]:
    host = (url.host or "").casefold()
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "loopback"
    return (host, url.port or 5432, url.database)


def dedicated_database_url(value: str | None, *, primary_url: str | None) -> str:
    """Require an explicitly named evaluation database distinct from the primary."""
    if not value:
        raise ValueError("WS8_EVAL_DATABASE_URL must name a dedicated evaluation database")
    try:
        parsed = make_url(value)
        if (
            parsed.get_backend_name() != "postgresql"
            or "eval" not in (parsed.database or "").lower()
        ):
            raise ValueError("WS8_EVAL_DATABASE_URL must name a dedicated PostgreSQL evaluation DB")
        if not primary_url:
            raise ValueError("DATABASE_URL must identify the primary DB for an isolation check")
        primary = make_url(primary_url)
        # Ignore driver/user/password and normalize common loopback aliases.
        if _db_target(parsed) == _db_target(primary):
            raise ValueError("evaluation database must not match the primary DATABASE_URL")
    except (ArgumentError, TypeError, AttributeError) as exc:
        raise ValueError("invalid evaluation database URL") from exc
    return value


def _parse_recovery_ids(values: list[str] | None) -> dict[str, str]:
    """Parse operator-supplied project=provider-ID pairs; never guess ownership."""
    claimed: dict[str, str] = {}
    for item in values or []:
        code, separator, provider_id = item.partition("=")
        if (
            not separator
            or code not in _PROJECT_CODES
            or code in claimed
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{5,127}", provider_id) is None
        ):
            raise ValueError("invalid or duplicate --recover-dataset PROJECT_CODE=DATASET_ID")
        claimed[code] = provider_id
    if len(set(claimed.values())) != len(claimed):
        raise ValueError("duplicate provider IDs in recovery request")
    return claimed


async def _audit_existing_provider_spaces(
    provider: RagflowHttpClient,
    *,
    namespace: str,
    recovery_ids: Mapping[str, str],
) -> dict[str, str]:
    """Read-only preflight: require exact operator IDs for orphan recovery.

    Dataset names alone do not establish ownership. The project-scoped
    description and the operator's previously audited provider ID must match.
    This function never binds, creates, deletes or ingests provider resources.
    """
    expected_names = {
        f"ws8-v0-{namespace}-{code.lower()}".casefold(): code
        for code in _PROJECT_CODES
    }
    found: dict[str, dict[str, Any]] = {}
    seen_pages: set[tuple[str, ...]] = set()
    for page in range(1, 21):
        response = await provider.request_data(
            "GET", "/api/v1/datasets", params={"page": page, "page_size": 100}
        )
        if not isinstance(response, list) or not all(isinstance(v, dict) for v in response):
            raise ValueError("unexpected RAGFlow dataset list during recovery audit")
        page_ids = tuple(str(v.get("id")) for v in response)
        if page_ids and page_ids in seen_pages:
            raise ValueError("RAGFlow dataset pagination did not advance")
        seen_pages.add(page_ids)
        for item in response:
            actual_name = str(item.get("name", ""))
            code = expected_names.get(actual_name.casefold())
            if code is None:
                continue
            if actual_name != f"ws8-v0-{namespace}-{code.lower()}":
                raise ValueError(f"RAGFlow recovery exact dataset name mismatch for {code}")
            if code in found:
                raise ValueError(f"duplicate evaluation dataset name for {code}")
            found[code] = item
        if len(response) < 100:
            break
    else:
        raise ValueError("RAGFlow dataset audit exceeds 20 pages: cannot prove ownership")

    if not found:
        if recovery_ids:
            raise ValueError("no existing RAGFlow datasets to recover for this namespace")
        return {}
    if set(found) != set(recovery_ids):
        raise ValueError(
            "existing RAGFlow datasets require --recover-dataset exactly once "
            "for every matching project; inspect provider IDs before retrying"
        )
    for code, item in found.items():
        if str(item.get("id")) != recovery_ids[code]:
            raise ValueError(f"RAGFlow recovery ID mismatch for {code}")
        expected_description = (
            "Managed by project-agent for scope "
            + _expected_uuid("v0", namespace, f"project:{code}")
        )
        if item.get("description") != expected_description:
            raise ValueError(f"RAGFlow recovery ownership description mismatch for {code}")
    return dict(recovery_ids)


def _read_frozen_json(dataset: EvaluationDataset, name: str, key: str) -> list[dict[str, Any]]:
    payload = json.loads((dataset.root / "fixtures" / name).read_text(encoding="utf-8"))
    items = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError(f"invalid frozen fixture data: {name}")
    return cast(list[dict[str, Any]], items)


def _expected_uuid(version: str, namespace: str, logical_key: str) -> str:
    """Independently check the published fixture_uuid UUIDv5 ownership contract."""
    parent = uuid5(NAMESPACE_URL, f"it-outsourcing-knowledge-agent/ws8/evaluation/{namespace}")
    return str(uuid5(parent, f"{version}\0{logical_key}"))


def _same_uuid(actual: object, expected: str, *, label: str) -> None:
    try:
        is_match = UUID(str(actual)) == UUID(expected)
    except (TypeError, ValueError, AttributeError):
        is_match = False
    if not is_match:
        raise ValueError(f"fixture-state ownership mismatch for {label}")


def _check_frozen_bytes(dataset: EvaluationDataset) -> None:
    """Validate bytes against the frozen manifest, not the working tree."""
    for source_path, expected in dataset.integrity["fixture_file_sha256"].items():
        path = (dataset.root / source_path).resolve()
        if not path.is_relative_to(dataset.root) or not path.is_file():
            raise ValueError("frozen fixture file missing or escaped dataset root")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("frozen fixture hash mismatch")
    for doc in dataset.documents_by_code.values():
        path = (dataset.root / doc.source_path).resolve()
        if not path.is_relative_to(dataset.root) or not path.is_file():
            raise ValueError("frozen corpus document missing or escaped dataset root")
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc.sha256:
            raise ValueError(f"frozen corpus hash mismatch for {doc.doc_code}")
    expected_manifest_hash = dataset.integrity["corpus_manifest_sha256"]
    actual_manifest_hash = hashlib.sha256(
        (dataset.root / "corpus-manifest.jsonl").read_bytes()
    ).hexdigest()
    if actual_manifest_hash != expected_manifest_hash:
        raise ValueError("frozen corpus manifest hash mismatch")
    for name, digest_field in (
        ("question-catalog.csv", "question_catalog_sha256"),
        ("gold-manifest.jsonl", "gold_manifest_sha256"),
        ("gold-manifest.schema.json", "gold_manifest_schema_sha256"),
    ):
        actual_hash = hashlib.sha256((dataset.root / name).read_bytes()).hexdigest()
        if actual_hash != dataset.integrity[digest_field]:
            raise ValueError(f"frozen {name} hash mismatch")


def verify_fixture_state(
    dataset: EvaluationDataset,
    state: Mapping[str, Any],
    *,
    evaluation_namespace: str,
) -> None:
    """Refuse a forged/old state file before verify, reprepare, or cleanup."""
    namespace = validate_namespace(evaluation_namespace)
    if dataset.dataset_version != "v0":
        raise ValueError("only the B7-frozen v0 benchmark is supported")
    if state.get("evaluation_namespace") != namespace:
        raise ValueError("fixture-state ownership mismatch: evaluation namespace")
    if state.get("integrity") != dataset.integrity:
        raise ValueError("fixture-state hash mismatch against frozen B7 manifest")
    _check_frozen_bytes(dataset)
    _same_uuid(
        state.get("company_id"),
        _expected_uuid("v0", namespace, "company"),
        label="company_id",
    )
    for field, prefix in (("client_ids", "client"), ("project_ids", "project")):
        mapping = state.get(field)
        if not isinstance(mapping, Mapping) or set(mapping) != set(_PROJECT_CODES):
            raise ValueError(f"fixture-state ownership mismatch for {field}")
        for code in _PROJECT_CODES:
            _same_uuid(
                mapping[code], _expected_uuid("v0", namespace, f"{prefix}:{code}"),
                label=f"{field}[{code}]",
            )
    frozen_users = _read_frozen_json(dataset, "identities.json", "identities")
    users = state.get("user_ids")
    if not isinstance(users, Mapping) or {
        key: str(value) for key, value in users.items()
    } != {item["alias"]: item["user_id"] for item in frozen_users}:
        raise ValueError("fixture-state ownership mismatch for frozen identities")
    frozen_memberships = _read_frozen_json(dataset, "memberships.json", "memberships")
    membership_ids = state.get("membership_ids")
    actual_membership_ids = (
        {key: str(value) for key, value in membership_ids.items()}
        if isinstance(membership_ids, Mapping)
        else None
    )
    scoped_membership_ids = {
        item["fact_id"]: str(
            _expected_uuid("v0", namespace, f"membership:{item['fact_id']}")
        )
        for item in frozen_memberships
    }
    legacy_membership_ids = {
        item["fact_id"]: item["membership_id"] for item in frozen_memberships
    }
    if actual_membership_ids not in (scoped_membership_ids, legacy_membership_ids):
        raise ValueError("fixture-state ownership mismatch for memberships")

    frozen_issues = _read_frozen_json(dataset, "sandbox-issues.json", "issues")
    issue_ids = state.get("sandbox_issue_ids")
    actual_issue_ids = (
        {key: str(value) for key, value in issue_ids.items()}
        if isinstance(issue_ids, Mapping)
        else None
    )
    scoped_issue_ids = {
        item["issue_key"]: str(
            _expected_uuid("v0", namespace, f"sandbox-issue:{item['issue_key']}")
        )
        for item in frozen_issues
    }
    legacy_issue_ids = {item["issue_key"]: item["issue_id"] for item in frozen_issues}
    if actual_issue_ids not in (scoped_issue_ids, legacy_issue_ids):
        raise ValueError("fixture-state ownership mismatch for sandbox issues")

    docs = {
        code: doc for code, doc in dataset.documents_by_code.items()
        if doc.project_code in _PROJECT_CODES
    }
    document_ids = state.get("document_ids")
    version_ids = state.get("document_version_ids")
    if not isinstance(document_ids, Mapping) or not isinstance(version_ids, Mapping):
        raise ValueError("fixture-state document mappings missing")
    if set(document_ids) != set(docs) or set(version_ids) != set(docs):
        raise ValueError("fixture-state document mapping differs from frozen corpus")
    for code in docs:
        root_code = code
        while (parent_code := docs[root_code].supersedes_doc_code) is not None:
            root_code = parent_code
        _same_uuid(
            document_ids[code], _expected_uuid("v0", namespace, f"document:{root_code}"),
            label=f"document_ids[{code}]",
        )
        _same_uuid(
            version_ids[code], _expected_uuid("v0", namespace, f"document-version:{code}"),
            label=f"document_version_ids[{code}]",
        )

    spaces = state.get("knowledge_space_ids")
    if not isinstance(spaces, Mapping) or set(spaces) != set(_PROJECT_CODES):
        raise ValueError("fixture-state ownership mismatch for knowledge spaces")
    if len(set(str(value) for value in spaces.values())) != len(_PROJECT_CODES):
        raise ValueError("fixture-state cross-project knowledge space overlap")
    provider_docs = state.get("ragflow_documents")
    if not isinstance(provider_docs, Mapping):
        raise ValueError("fixture-state provider document mappings missing")
    for code, mapping in provider_docs.items():
        doc = docs.get(code)
        if doc is None or (
            doc.lifecycle_status != "PUBLISHED"
            and doc.provider_residue_mode != "adversarial_test_only"
        ):
            raise ValueError("fixture-state provider document not permitted by frozen corpus")
        if not isinstance(mapping, Mapping) or (
            str(mapping.get("dataset_id")) != str(spaces[doc.project_code])
            or not mapping.get("document_id")
        ):
            raise ValueError("fixture-state provider document/project binding mismatch")
    if provider_docs:
        expected_provider_codes = {
            code for code, doc in docs.items()
            if doc.lifecycle_status == "PUBLISHED"
            or doc.provider_residue_mode == "adversarial_test_only"
        }
        if set(provider_docs) != expected_provider_codes:
            raise ValueError("fixture-state provider document mapping incomplete")
    else:
        for code in _PROJECT_CODES:
            _same_uuid(
                spaces[code], _expected_uuid("v0", namespace, f"knowledge-space:{code}"),
                label=f"knowledge_space_ids[{code}]",
            )


class FrozenCorpusObjectStore:
    """Read-only provider upload adapter over verified B7 corpus bytes."""

    def __init__(self, dataset: EvaluationDataset) -> None:
        self._dataset = dataset

    async def put(self, request: PutObjectRequest) -> StoredObject:
        raise PermissionError("frozen corpus object store is read-only")

    async def exists(self, object_key: str) -> bool:
        return object_key in self._dataset.documents_by_code

    async def delete(self, object_key: str) -> None:
        raise PermissionError("frozen corpus object store is read-only")

    async def get(self, object_key: str) -> ObjectPayload:
        try:
            doc = self._dataset.documents_by_code[object_key]
        except KeyError as exc:
            raise KeyError("unknown frozen corpus document") from exc
        path = (self._dataset.root / doc.source_path).resolve()
        if not path.is_relative_to(self._dataset.root):
            raise ValueError("corpus path escapes dataset root")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != doc.sha256:
            raise ValueError("frozen corpus hash mismatch")
        return ObjectPayload(
            object_key=object_key,
            data=raw,
            mime_type="text/markdown",
            sha256=digest,
        )


@asynccontextmanager
async def _ragflow_resources(
    dataset: EvaluationDataset,
) -> AsyncIterator[tuple[RagflowAdapter, RagflowHttpClient]]:
    from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
    from project_agent.infrastructure.ragflow.client import RagflowHttpClient

    url, key = os.getenv("RAGFLOW_BASE_URL"), os.getenv("RAGFLOW_API_KEY")
    if not url or not key:
        raise ValueError("--with-ragflow requires RAGFLOW_BASE_URL and RAGFLOW_API_KEY")
    async with httpx.AsyncClient(base_url=url, timeout=30.0) as http:
        adapter = RagflowAdapter.from_http_client(
            http,
            api_key=key,
            object_store=FrozenCorpusObjectStore(dataset),
            embedding_model=os.getenv("RAGFLOW_EMBEDDING_MODEL") or None,
        )
        yield adapter, RagflowHttpClient(http, api_key=key)


async def _verify_postgres(session_factory: Any, state: Mapping[str, Any]) -> None:
    """Read-only existence/ownership check, never seed or repair in verify mode."""
    from project_agent.infrastructure.db.models.schema import (
        DocumentVersionModel,
        ProjectMembershipModel,
        ProjectModel,
        SandboxIssueModel,
    )

    async with session_factory() as session:
        for code, project_id in state["project_ids"].items():
            project = await session.get(ProjectModel, UUID(str(project_id)))
            if (project is None or project.code != code
                    or project.company_id != UUID(str(state["company_id"]))
                    or project.client_id != UUID(str(state["client_ids"][code]))):
                raise ValueError(f"evaluation project missing or ownership mismatch: {code}")
        for mid in state["membership_ids"].values():
            if await session.get(ProjectMembershipModel, UUID(str(mid))) is None:
                raise ValueError("evaluation membership missing")
        for vid in state["document_version_ids"].values():
            if await session.get(DocumentVersionModel, UUID(str(vid))) is None:
                raise ValueError("evaluation document version missing")
        for iid in state["sandbox_issue_ids"].values():
            if await session.get(SandboxIssueModel, UUID(str(iid))) is None:
                raise ValueError("evaluation sandbox issue missing")


async def _verify_provider(
    client: RagflowHttpClient,
    dataset: EvaluationDataset,
    state: Mapping[str, Any],
) -> None:
    """Check recorded provider IDs without creating/rebinding any datasets."""
    expected = {
        f"ws8-v0-{state['evaluation_namespace']}-{code.lower()}": str(space_id)
        for code, space_id in state["knowledge_space_ids"].items()
    }
    if not state["ragflow_documents"]:
        raise ValueError("fixture state contains no RAGFlow materialization to verify")
    visible: dict[str, str] = {}
    page = 1
    while expected.keys() - visible.keys():
        response = await client.request_data(
            "GET", "/api/v1/datasets", params={"page": page, "page_size": 100}
        )
        if not isinstance(response, list):
            raise ValueError("unexpected RAGFlow dataset list")
        for item in response:
            if item.get("name") in expected:
                visible[str(item["name"])] = str(item["id"])
        if len(response) < 100 or page >= 20:
            break
        page += 1
    if visible != expected:
        raise ValueError("RAGFlow provider dataset ownership/id mismatch")
    from project_agent.infrastructure.ragflow.baseline import (
        DOCUMENT_VERSION_METADATA_FIELD,
        PROJECT_METADATA_FIELD,
    )

    for code, record in state["ragflow_documents"].items():
        frozen = dataset.documents_by_code[code]
        provider_id = str(record["dataset_id"])
        data = await client.request_data(
            "GET", f"/api/v1/datasets/{provider_id}/documents",
            params={"page": 1, "page_size": 100},
        )
        docs = data.get("docs", []) if isinstance(data, dict) else data
        if not isinstance(docs, list):
            raise ValueError("unexpected RAGFlow document response")
        matching = next(
            (item for item in docs if str(item.get("id")) == str(record["document_id"])),
            None,
        )
        if matching is None:
            raise ValueError(f"RAGFlow provider document missing: {frozen.doc_code}")
        meta = matching.get("meta_fields")
        if not isinstance(meta, dict) or (
            str(meta.get(PROJECT_METADATA_FIELD))
            != frozen.project_code
            or str(meta.get(DOCUMENT_VERSION_METADATA_FIELD))
            != str(state["document_version_ids"][code])
        ):
            raise ValueError(f"RAGFlow provider metadata mismatch: {frozen.doc_code}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project-agent-eval-prepare",
        description="WS8 V0 evaluation-owned fixture preparation (dedicated eval DB only)",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--evaluation-namespace", required=True, help="single owned WS8 V0 namespace"
    )
    common.add_argument("--dataset-root", type=Path, default=Path("evaluation/datasets/v0"))
    common.add_argument("--artifact-root", type=Path, default=Path("evaluation/artifacts"))
    common.add_argument(
        "--with-ragflow", action="store_true", help="include owned RAGFlow datasets"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser(
        "prepare", parents=[common], help="idempotently materialize frozen B7 V0"
    )
    prepare.add_argument(
        "--recover-dataset", action="append", metavar="PROJECT_CODE=DATASET_ID",
        help="explicitly reuse a provider ID from a failed prepare (repeat per orphan project)",
    )
    subcommands.add_parser(
        "verify", parents=[common], help="read-only state and live ownership check"
    )
    cleanup = subcommands.add_parser(
        "cleanup", parents=[common], help="delete ONLY owned eval fixtures"
    )
    cleanup.add_argument(
        "--confirm-cleanup", action="store_true",
        help="explicitly authorize owned resource deletion",
    )
    return parser


async def run(args: argparse.Namespace) -> dict[str, str | bool]:
    """Perform exactly one mode, with all destructive ownership checks first."""
    namespace = validate_namespace(args.evaluation_namespace)
    if args.command == "cleanup" and not args.confirm_cleanup:
        raise ValueError("cleanup requires --confirm-cleanup and --evaluation-namespace")
    database_url = dedicated_database_url(
        os.getenv("WS8_EVAL_DATABASE_URL"), primary_url=os.getenv("DATABASE_URL")
    )
    dataset = load_evaluation_dataset(args.dataset_root)
    _check_frozen_bytes(dataset)
    store = ArtifactStore(args.artifact_root, namespace)
    state_file = store.fixture_state_path
    state: Mapping[str, Any] | None = None
    if state_file.exists():
        loaded = json.loads(state_file.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("fixture-state.json is not an object")
        state = loaded
        verify_fixture_state(dataset, state, evaluation_namespace=namespace)
    if args.command in ("verify", "cleanup") and state is None:
        raise ValueError("fixture-state.json missing: prepare the owned namespace first")
    if (
        state is not None
        and state["ragflow_documents"]
        and args.command in ("prepare", "cleanup")
        and not args.with_ragflow
    ):
        raise ValueError("existing provider state requires --with-ragflow for safe operation")
    recovery_ids = _parse_recovery_ids(getattr(args, "recover_dataset", None))
    if recovery_ids and (args.command != "prepare" or not args.with_ragflow or state):
        raise ValueError("--recover-dataset is only for provider prepare without fixture-state")
    if args.with_ragflow and (
        not os.getenv("RAGFLOW_BASE_URL") or not os.getenv("RAGFLOW_API_KEY")
    ):
        raise ValueError("--with-ragflow requires RAGFLOW_BASE_URL and RAGFLOW_API_KEY")

    from project_agent.evaluation.fixtures import cleanup_v0, prepare_v0
    from project_agent.infrastructure.db.session import create_engine, create_session_factory

    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    try:
        if args.with_ragflow:
            async with _ragflow_resources(dataset) as (adapter, provider):
                return await _execute_mode(
                    args, namespace, dataset, store, state, sessions, adapter, provider,
                    prepare_v0=prepare_v0, cleanup_v0=cleanup_v0,
                    recovery_ids=recovery_ids,
                )
        return await _execute_mode(
            args, namespace, dataset, store, state, sessions, None, None,
            prepare_v0=prepare_v0, cleanup_v0=cleanup_v0,
            recovery_ids=recovery_ids,
        )
    finally:
        await engine.dispose()


async def _execute_mode(
    args: argparse.Namespace,
    namespace: str,
    dataset: EvaluationDataset,
    store: ArtifactStore,
    previous_state: Mapping[str, Any] | None,
    sessions: Any,
    adapter: RagflowAdapter | None,
    provider: RagflowHttpClient | None,
    *,
    prepare_v0: Any,
    cleanup_v0: Any,
    recovery_ids: Mapping[str, str] | None = None,
) -> dict[str, str | bool]:
    if args.command == "prepare":
        audited_ids: dict[str, str] = {}
        if adapter is not None and provider is not None and previous_state is None:
            audited_ids = await _audit_existing_provider_spaces(
                provider, namespace=namespace, recovery_ids=recovery_ids or {},
            )
        state = await prepare_v0(
            dataset=dataset,
            evaluation_namespace=namespace,
            session_factory=sessions,
            ragflow_adapter=adapter,
        )
        verify_fixture_state(dataset, state, evaluation_namespace=namespace)
        for project_code, expected_provider_id in audited_ids.items():
            if str(state["knowledge_space_ids"][project_code]) != expected_provider_id:
                raise ValueError("RAGFlow recovered dataset ID changed during prepare")
        store.write_json(store.fixture_state_path, state)
        return {"mode": "prepare", "namespace": namespace, "state": str(store.fixture_state_path)}
    assert previous_state is not None  # enforced by run() before any provider/DB access
    if args.command == "verify":
        await _verify_postgres(sessions, previous_state)
        if adapter is not None and provider is not None:
            await _verify_provider(provider, dataset, previous_state)
        return {
            "mode": "verify",
            "namespace": namespace,
            "postgres_checked": True,
            "ragflow_checked": provider is not None,
        }
    if args.command == "cleanup":
        await _verify_postgres(sessions, previous_state)
        await cleanup_v0(
            evaluation_namespace=namespace, session_factory=sessions, ragflow_adapter=adapter,
        )
        store.fixture_state_path.unlink()
        return {"mode": "cleanup", "namespace": namespace, "owned_resources_removed": True}
    raise ValueError("unknown evaluation preparation mode")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as exc:
        parser.exit(2, f"evaluation preparation failed: {exc}\n")
    print(json.dumps(result, sort_keys=True))  # never print credentials or JWTs
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
