"""Offline RED contracts for the narrowly-scoped WS8 preparation CLI."""

from __future__ import annotations

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


class _ReadOnlyProvider:
    """A provider listing with no mutation methods: recovery must be read-only."""

    def __init__(self, namespace: str, *, wrong_description: bool = False) -> None:
        self.requests: list[tuple[str, str]] = []
        self.ids = {
            "PRJ-RETAIL-ALPHA": "retail-owned-id",
            "PRJ-LOGISTICS-BETA": "logistics-owned-id",
        }
        self.items = [
            {
                "id": identifier,
                "name": f"ws8-v0-{namespace}-{code.lower()}",
                "description": (
                    "unrelated application" if wrong_description else
                    f"Managed by project-agent for scope {_id('project:' + code)}"
                ),
            }
            for code, identifier in self.ids.items()
        ]

    async def request_data(self, method: str, path: str, **kwargs: object) -> object:
        self.requests.append((method, path))
        assert method == "GET" and path == "/api/v1/datasets"
        return self.items


@pytest.mark.asyncio
async def test_orphan_recovery_requires_exact_ids_and_scoped_description() -> None:
    from project_agent.cli.evaluation_prepare import _audit_existing_provider_spaces

    provider = _ReadOnlyProvider(NS)
    with pytest.raises(ValueError, match="--recover-dataset"):
        await _audit_existing_provider_spaces(provider, namespace=NS, recovery_ids={})
    with pytest.raises(ValueError, match="ID mismatch"):
        await _audit_existing_provider_spaces(
            provider,
            namespace=NS,
            recovery_ids={**provider.ids, "PRJ-RETAIL-ALPHA": "unrelated-dataset"},
        )
    with pytest.raises(ValueError, match="ownership description"):
        wrong_owner = _ReadOnlyProvider(NS, wrong_description=True)
        await _audit_existing_provider_spaces(
            wrong_owner, namespace=NS, recovery_ids=wrong_owner.ids,
        )
    assert await _audit_existing_provider_spaces(
        provider, namespace=NS, recovery_ids=provider.ids,
    ) == provider.ids
    assert all(method == "GET" for method, _ in provider.requests)


@pytest.mark.asyncio
async def test_orphan_recovery_rejects_missing_or_duplicate_provider_identity() -> None:
    from project_agent.cli.evaluation_prepare import _audit_existing_provider_spaces

    provider = _ReadOnlyProvider(NS)
    with pytest.raises(ValueError, match="exactly"):
        await _audit_existing_provider_spaces(
            provider,
            namespace=NS,
            recovery_ids={"PRJ-RETAIL-ALPHA": provider.ids["PRJ-RETAIL-ALPHA"]},
        )
    provider.items.append(dict(provider.items[0], id="colliding-id"))
    with pytest.raises(ValueError, match="duplicate"):
        await _audit_existing_provider_spaces(
            provider, namespace=NS, recovery_ids=provider.ids,
        )
    provider.items.clear()
    with pytest.raises(ValueError, match="no existing"):
        await _audit_existing_provider_spaces(
            provider, namespace=NS, recovery_ids=provider.ids,
        )


def test_recovery_parser_rejects_unsafe_or_duplicate_project_ids() -> None:
    from project_agent.cli.evaluation_prepare import _parse_recovery_ids, build_parser

    args = build_parser().parse_args([
        "prepare", "--evaluation-namespace", NS, "--with-ragflow",
        "--recover-dataset", "PRJ-RETAIL-ALPHA=retail-owned-id",
        "--recover-dataset", "PRJ-LOGISTICS-BETA=logistics-owned-id",
    ])
    assert _parse_recovery_ids(args.recover_dataset) == {
        "PRJ-RETAIL-ALPHA": "retail-owned-id",
        "PRJ-LOGISTICS-BETA": "logistics-owned-id",
    }
    for values in (
        ["PRJ-RETAIL-ALPHA=retail-owned-id", "PRJ-RETAIL-ALPHA=other-id"],
        ["UNKNOWN=untrusted-id"],
        ["PRJ-RETAIL-ALPHA=../outside"],
    ):
        with pytest.raises(ValueError, match="recovery|recover"):
            _parse_recovery_ids(values)

@pytest.mark.asyncio
async def test_cli_recovery_resumes_exact_orphans_and_writes_verified_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from contextlib import asynccontextmanager

    from project_agent.cli import evaluation_prepare as cli
    from project_agent.evaluation import fixtures as service
    from project_agent.infrastructure.db import session as db_session

    provider = _ReadOnlyProvider(NS)
    prepare_calls: list[int] = []
    adapter = object()

    @asynccontextmanager
    async def fake_resources(dataset: object):
        yield adapter, provider

    monkeypatch.setattr(cli, "_ragflow_resources", fake_resources)

    class FakeEngine:
        disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    monkeypatch.setattr(db_session, "create_engine", lambda url: engine)
    monkeypatch.setattr(db_session, "create_session_factory", lambda e: object())

    async def fake_prepare(**kwargs: object) -> dict[str, object]:
        assert kwargs["ragflow_adapter"] is adapter
        prepare_calls.append(1)
        state = _state()
        state["knowledge_space_ids"] = provider.ids
        dataset = load_evaluation_dataset(DATASET)
        state["ragflow_documents"] = {
            code: {
                "dataset_id": provider.ids[doc.project_code],
                "document_id": f"owned-{code}",
            }
            for code, doc in dataset.documents_by_code.items()
            if doc.project_code in provider.ids
            and (doc.lifecycle_status == "PUBLISHED"
                 or doc.provider_residue_mode == "adversarial_test_only")
        }
        return state

    monkeypatch.setattr(service, "prepare_v0", fake_prepare)
    monkeypatch.setenv("WS8_EVAL_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/ws8_eval")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/primary")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://localhost:9380")
    monkeypatch.setenv("RAGFLOW_API_KEY", "UNIT_TEST_ONLY")

    base = [
        "prepare", "--evaluation-namespace", NS, "--with-ragflow",
        "--dataset-root", str(DATASET), "--artifact-root", str(tmp_path),
    ]
    with pytest.raises(ValueError, match="--recover-dataset"):
        await cli.run(cli.build_parser().parse_args(base))
    assert not prepare_calls  # fail closed before any DB/provider mutation
    assert not (tmp_path / NS / "fixture-state.json").exists()
    assert engine.disposed

    recovered = base + [
        arg for code, provider_id in provider.ids.items()
        for arg in ("--recover-dataset", f"{code}={provider_id}")
    ]
    assert (await cli.run(cli.build_parser().parse_args(recovered)))["mode"] == "prepare"
    assert len(prepare_calls) == 1
    path = tmp_path / NS / "fixture-state.json"
    state = json.loads(path.read_text())
    assert state["knowledge_space_ids"] == provider.ids
    assert all(method == "GET" for method, _ in provider.requests)

    # A successful recovered state may not be silently re-adopted by another run.
    with pytest.raises(ValueError, match="only for provider prepare without fixture-state"):
        await cli.run(cli.build_parser().parse_args(recovered))
    assert len(prepare_calls) == 1

@pytest.mark.asyncio
async def test_recovery_rejects_casefold_name_collision_before_provider_bind() -> None:
    from project_agent.cli.evaluation_prepare import _audit_existing_provider_spaces

    provider = _ReadOnlyProvider(NS)
    provider.items = [dict(provider.items[0], name=provider.items[0]["name"].upper())]
    with pytest.raises(ValueError, match="name mismatch"):
        await _audit_existing_provider_spaces(
            provider,
            namespace=NS,
            recovery_ids={"PRJ-RETAIL-ALPHA": provider.ids["PRJ-RETAIL-ALPHA"]},
        )
