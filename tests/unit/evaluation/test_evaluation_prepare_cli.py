"""Offline RED contracts for the narrowly-scoped WS8 preparation CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from project_agent.evaluation.dataset import load_evaluation_dataset

DATASET = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "v0"
NS = "ws8-cli-unit"


def _id(key: str) -> str:
    namespace = uuid5(NAMESPACE_URL, f"it-outsourcing-knowledge-agent/ws8/evaluation/{NS}")
    return str(uuid5(namespace, f"v0\0{key}"))


def _state() -> dict[str, object]:
    dataset = load_evaluation_dataset(DATASET)
    users = json.loads((DATASET / "fixtures" / "identities.json").read_text())["identities"]
    memberships = json.loads((DATASET / "fixtures" / "memberships.json").read_text())["memberships"]
    issues = json.loads((DATASET / "fixtures" / "sandbox-issues.json").read_text())["issues"]
    codes = ("PRJ-RETAIL-ALPHA", "PRJ-LOGISTICS-BETA")
    docs = {
        key: item for key, item in dataset.documents_by_code.items()
        if item.project_code in codes
    }
    return {
        "evaluation_namespace": NS,
        "company_id": _id("company"),
        "client_ids": {code: _id(f"client:{code}") for code in codes},
        "project_ids": {code: _id(f"project:{code}") for code in codes},
        "user_ids": {item["alias"]: item["user_id"] for item in users},
        "membership_ids": {item["fact_id"]: item["membership_id"] for item in memberships},
        "document_ids": {key: _id("document:" + _root_code(key, docs)) for key in docs},
        "document_version_ids": {key: _id(f"document-version:{key}") for key in docs},
        "knowledge_space_ids": {code: _id(f"knowledge-space:{code}") for code in codes},
        "ragflow_documents": {},
        "sandbox_issue_ids": {item["issue_key"]: item["issue_id"] for item in issues},
        "integrity": json.loads((DATASET / "dataset-manifest.json").read_text())["integrity"],
    }


def _root_code(code: str, docs: dict[str, object]) -> str:
    current = code
    while docs[current].supersedes_doc_code is not None:
        current = docs[current].supersedes_doc_code
    return current


def test_cli_parser_offers_three_explicit_modes_and_safe_cleanup_confirmation() -> None:
    from project_agent.cli.evaluation_prepare import build_parser

    parser = build_parser()
    for name in ("prepare", "verify", "cleanup"):
        args = parser.parse_args([name, "--evaluation-namespace", NS])
        assert args.command == name
        assert args.evaluation_namespace == NS
    assert not parser.parse_args(["cleanup", "--evaluation-namespace", NS]).confirm_cleanup
    assert parser.parse_args(
        ["cleanup", "--evaluation-namespace", NS, "--confirm-cleanup"]
    ).confirm_cleanup
    with pytest.raises(SystemExit):
        parser.parse_args(["cleanup"])


def test_verify_accepts_exact_frozen_state_without_modifying_it() -> None:
    from project_agent.cli.evaluation_prepare import verify_fixture_state

    state = _state()
    encoded_before = json.dumps(state, sort_keys=True)
    verify_fixture_state(load_evaluation_dataset(DATASET), state, evaluation_namespace=NS)
    assert json.dumps(state, sort_keys=True) == encoded_before


@pytest.mark.parametrize(
    "field", ["company_id", "project_ids", "integrity", "evaluation_namespace"]
)
def test_verify_refuses_mismatched_state_ownership_and_hashes(field: str) -> None:
    from project_agent.cli.evaluation_prepare import verify_fixture_state

    state = _state()
    if field == "project_ids":
        state["project_ids"]["PRJ-RETAIL-ALPHA"] = _id("project:OTHER")
    elif field == "integrity":
        state["integrity"]["fixtures_sha256"] = "0" * 64
    elif field == "company_id":
        state[field] = _id("other-company")
    else:
        state[field] = "different-namespace"
    with pytest.raises(ValueError, match="(mismatch|ownership|hash)"):
        verify_fixture_state(load_evaluation_dataset(DATASET), state, evaluation_namespace=NS)


def test_verify_refuses_missing_frozen_document_mapping() -> None:
    from project_agent.cli.evaluation_prepare import verify_fixture_state

    state = _state()
    del state["document_version_ids"]["A-API-001"]
    with pytest.raises(ValueError, match="document"):
        verify_fixture_state(load_evaluation_dataset(DATASET), state, evaluation_namespace=NS)


@pytest.mark.parametrize("value", ["", "../outside", "a/b", "../", "..", "a\nb"])
def test_namespace_rejects_unsafe_segments(value: str) -> None:
    from project_agent.cli.evaluation_prepare import validate_namespace

    with pytest.raises(ValueError, match="evaluation namespace"):
        validate_namespace(value)


def test_database_guard_requires_dedicated_eval_database_not_primary() -> None:
    from project_agent.cli.evaluation_prepare import dedicated_database_url

    url = "postgresql+asyncpg://u:p@127.0.0.1:5432/project_agent_eval"
    assert dedicated_database_url(url, primary_url="postgresql://u:p@127.0.0.1/main") == url
    with pytest.raises(ValueError, match="primary"):
        dedicated_database_url(url, primary_url=url)
    with pytest.raises(ValueError, match="evaluation"):
        dedicated_database_url("postgresql+asyncpg://u:p@127.0.0.1/main", primary_url=None)
    with pytest.raises(ValueError, match="evaluation"):
        dedicated_database_url("", primary_url=None)


@pytest.mark.asyncio
async def test_corpus_store_serves_only_hash_verified_frozen_bytes() -> None:
    from project_agent.cli.evaluation_prepare import FrozenCorpusObjectStore

    dataset = load_evaluation_dataset(DATASET)
    store = FrozenCorpusObjectStore(dataset)
    original = dataset.documents_by_code["A-API-001"]
    payload = await store.get("A-API-001")
    assert payload.sha256 == original.sha256
    assert hashlib.sha256(payload.data).hexdigest() == original.sha256
    with pytest.raises((KeyError, ValueError)):
        await store.get("../../outside")


@pytest.mark.asyncio
async def test_cleanup_without_confirmation_refuses_before_opening_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from project_agent.cli import evaluation_prepare as cli

    args = cli.build_parser().parse_args(["cleanup", "--evaluation-namespace", NS])
    monkeypatch.setenv("WS8_EVAL_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/eval_db")
    with pytest.raises(ValueError, match="confirm-cleanup"):
        await cli.run(args)


def test_verify_frozen_corpus_fingerprint_is_not_rewritten() -> None:
    """The CLI must never write into the frozen B7 input tree."""
    from project_agent.cli.evaluation_prepare import verify_fixture_state

    dataset = load_evaluation_dataset(DATASET)
    benchmark_hash = hashlib.sha256((DATASET / "SHA256SUMS.txt").read_bytes()).hexdigest()
    verify_fixture_state(dataset, _state(), evaluation_namespace=NS)
    assert hashlib.sha256((DATASET / "SHA256SUMS.txt").read_bytes()).hexdigest() == benchmark_hash


@pytest.mark.asyncio
async def test_verify_provider_rejects_document_missing_project_version_metadata() -> None:
    from project_agent.cli.evaluation_prepare import _verify_provider

    state = _state()
    state["knowledge_space_ids"] = {
        "PRJ-RETAIL-ALPHA": "provider-alpha",
        "PRJ-LOGISTICS-BETA": "provider-beta",
    }
    state["ragflow_documents"] = {
        "A-API-001": {"dataset_id": "provider-alpha", "document_id": "provider-doc"}
    }

    class FakeClient:
        async def request_data(self, method: str, path: str, **kwargs: object) -> object:
            if path == "/api/v1/datasets":
                return [
                    {"id": "provider-alpha", "name": f"ws8-v0-{NS}-prj-retail-alpha"},
                    {"id": "provider-beta", "name": f"ws8-v0-{NS}-prj-logistics-beta"},
                ]
            return {"docs": [{"id": "provider-doc", "meta_fields": {}}]}

    with pytest.raises(ValueError, match="metadata"):
        await _verify_provider(FakeClient(), load_evaluation_dataset(DATASET), state)


def test_verify_refuses_missing_ingested_provider_document_mapping() -> None:
    from project_agent.cli.evaluation_prepare import verify_fixture_state

    state = _state()
    state["knowledge_space_ids"] = {
        "PRJ-RETAIL-ALPHA": "provider-alpha",
        "PRJ-LOGISTICS-BETA": "provider-beta",
    }
    state["ragflow_documents"] = {
        "A-API-001": {"dataset_id": "provider-alpha", "document_id": "only-one"}
    }
    with pytest.raises(ValueError, match="provider document"):
        verify_fixture_state(load_evaluation_dataset(DATASET), state, evaluation_namespace=NS)


def test_database_guard_detects_same_database_with_different_driver_or_credentials() -> None:
    from project_agent.cli.evaluation_prepare import dedicated_database_url

    primary = "postgresql://admin:secret@localhost:5432/safe_eval"
    alternative = "postgresql+asyncpg://worker:different@localhost:5432/safe_eval"
    with pytest.raises(ValueError, match="primary"):
        dedicated_database_url(alternative, primary_url=primary)


@pytest.mark.asyncio
async def test_frozen_corpus_store_implements_read_only_object_store_port() -> None:
    from project_agent.application.ports.object_store import (
        ObjectStorePort,
        PutObjectRequest,
    )
    from project_agent.cli.evaluation_prepare import FrozenCorpusObjectStore

    store = FrozenCorpusObjectStore(load_evaluation_dataset(DATASET))
    assert isinstance(store, ObjectStorePort)
    assert await store.exists("A-API-001")
    assert not await store.exists("../outsider")
    with pytest.raises(PermissionError, match="read.only"):
        await store.put(PutObjectRequest(
            project_id="p", object_key="A-API-001", data=b"changed", mime_type="text/markdown",
        ))
    with pytest.raises(PermissionError, match="read.only"):
        await store.delete("A-API-001")


def test_database_guard_detects_localhost_aliases_for_same_database() -> None:
    from project_agent.cli.evaluation_prepare import dedicated_database_url

    primary = "postgresql+asyncpg://main@localhost:5432/same_eval"
    candidate = "postgresql+asyncpg://other@127.0.0.1:5432/same_eval"
    with pytest.raises(ValueError, match="primary"):
        dedicated_database_url(candidate, primary_url=primary)

@pytest.mark.asyncio
async def test_prepare_cli_uses_sqlalchemy_factory_and_persists_verified_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Use the repository's actual SQLAlchemy wrapper without connecting to a DB."""
    from project_agent.cli import evaluation_prepare as cli
    from project_agent.evaluation import fixtures as fixture_service
    from project_agent.infrastructure.db import session as db_session

    class FakeEngine:
        disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    sessions = object()
    monkeypatch.setattr(db_session, "create_engine", lambda url: engine)
    monkeypatch.setattr(db_session, "create_session_factory", lambda e: sessions)

    async def fake_prepare_v0(**kwargs: object) -> dict[str, object]:
        assert kwargs["session_factory"] is sessions
        assert kwargs["ragflow_adapter"] is None
        return _state()

    monkeypatch.setattr(fixture_service, "prepare_v0", fake_prepare_v0)
    monkeypatch.setenv("WS8_EVAL_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/ws8_eval")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/project_agent")
    args = cli.build_parser().parse_args([
        "prepare", "--evaluation-namespace", NS,
        "--dataset-root", str(DATASET), "--artifact-root", str(tmp_path),
    ])
    result = await cli.run(args)
    state = json.loads((tmp_path / NS / "fixture-state.json").read_text())
    assert result["mode"] == "prepare"
    assert state["evaluation_namespace"] == NS
    assert "jwt" not in state
    assert engine.disposed


def test_database_guard_requires_known_primary_target() -> None:
    from project_agent.cli.evaluation_prepare import dedicated_database_url

    with pytest.raises(ValueError, match="DATABASE_URL"):
        dedicated_database_url(
            "postgresql+asyncpg://u:p@localhost/my_eval", primary_url=None,
        )
