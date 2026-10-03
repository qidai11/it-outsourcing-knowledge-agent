from __future__ import annotations

import json
from pathlib import Path

from project_agent.evaluation.dataset import load_evaluation_dataset
from project_agent.evaluation.fixtures import fixture_uuid

DATASET = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "v0"
PROJECT_CODES = ("PRJ-RETAIL-ALPHA", "PRJ-LOGISTICS-BETA")


def _root_code(code: str, docs: dict[str, object]) -> str:
    current = code
    while docs[current].supersedes_doc_code is not None:
        current = docs[current].supersedes_doc_code
    return current


def _state(namespace: str, *, scoped_child_ids: bool) -> dict[str, object]:
    dataset = load_evaluation_dataset(DATASET)
    users = json.loads((DATASET / "fixtures" / "identities.json").read_text())["identities"]
    memberships = json.loads((DATASET / "fixtures" / "memberships.json").read_text())[
        "memberships"
    ]
    issues = json.loads((DATASET / "fixtures" / "sandbox-issues.json").read_text())["issues"]
    docs = {
        key: item
        for key, item in dataset.documents_by_code.items()
        if item.project_code in PROJECT_CODES
    }
    membership_ids = {
        item["fact_id"]: (
            str(
                fixture_uuid(
                    "v0",
                    f"membership:{item['fact_id']}",
                    evaluation_namespace=namespace,
                )
            )
            if scoped_child_ids
            else item["membership_id"]
        )
        for item in memberships
    }
    issue_ids = {
        item["issue_key"]: (
            str(
                fixture_uuid(
                    "v0",
                    f"sandbox-issue:{item['issue_key']}",
                    evaluation_namespace=namespace,
                )
            )
            if scoped_child_ids
            else item["issue_id"]
        )
        for item in issues
    }
    return {
        "evaluation_namespace": namespace,
        "company_id": str(fixture_uuid("v0", "company", evaluation_namespace=namespace)),
        "client_ids": {
            code: str(fixture_uuid("v0", f"client:{code}", evaluation_namespace=namespace))
            for code in PROJECT_CODES
        },
        "project_ids": {
            code: str(fixture_uuid("v0", f"project:{code}", evaluation_namespace=namespace))
            for code in PROJECT_CODES
        },
        "user_ids": {item["alias"]: item["user_id"] for item in users},
        "membership_ids": membership_ids,
        "document_ids": {
            key: str(
                fixture_uuid(
                    "v0",
                    "document:" + _root_code(key, docs),
                    evaluation_namespace=namespace,
                )
            )
            for key in docs
        },
        "document_version_ids": {
            key: str(
                fixture_uuid(
                    "v0", f"document-version:{key}", evaluation_namespace=namespace
                )
            )
            for key in docs
        },
        "knowledge_space_ids": {
            code: str(
                fixture_uuid(
                    "v0", f"knowledge-space:{code}", evaluation_namespace=namespace
                )
            )
            for code in PROJECT_CODES
        },
        "ragflow_documents": {},
        "sandbox_issue_ids": issue_ids,
        "integrity": json.loads((DATASET / "dataset-manifest.json").read_text())["integrity"],
    }


def test_verify_accepts_namespace_scoped_membership_and_issue_ids() -> None:
    from project_agent.cli.evaluation_prepare import verify_fixture_state

    namespace = "ws8-namespace-scoped-unit"
    state = _state(namespace, scoped_child_ids=True)
    verify_fixture_state(
        load_evaluation_dataset(DATASET), state, evaluation_namespace=namespace
    )


def test_verify_keeps_legacy_state_compatible_for_in_place_upgrade() -> None:
    from project_agent.cli.evaluation_prepare import verify_fixture_state

    namespace = "ws8-legacy-upgrade-unit"
    state = _state(namespace, scoped_child_ids=False)
    verify_fixture_state(
        load_evaluation_dataset(DATASET), state, evaluation_namespace=namespace
    )


def test_namespace_scoped_child_ids_do_not_overlap_between_namespaces() -> None:
    first = _state("ws8-isolation-a", scoped_child_ids=True)
    second = _state("ws8-isolation-b", scoped_child_ids=True)

    assert set(first["membership_ids"].values()).isdisjoint(
        second["membership_ids"].values()
    )
    assert set(first["sandbox_issue_ids"].values()).isdisjoint(
        second["sandbox_issue_ids"].values()
    )
