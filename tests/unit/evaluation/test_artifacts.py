from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from project_agent.evaluation.artifacts import ArtifactStore, SecretArtifactError
from project_agent.evaluation.models import TrialClassification


def test_json_artifact_output_is_stable_and_sorted(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, "eval-001")
    path = store.root / "stable.json"

    store.write_json(path, {"z": 1, "a": {"y": 2, "b": 3}})

    assert path.read_bytes() == b'{"a":{"b":3,"y":2},"z":1}\n'


def test_trial_path_is_stable_for_case_and_trial_number(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, "eval-001")

    assert store.trial_path("Q007", 1) == (
        tmp_path / "eval-001" / "cases" / "Q007" / "trial-001.json"
    )
    assert store.trial_path("Q007", 12).name == "trial-012.json"


def test_artifact_writer_rejects_secret_fields(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, "eval-001")

    for payload in (
        {"authorization": "opaque"},
        {"nested": {"api_key": "secret"}},
        {"jwt": "opaque"},
        {"password": "secret"},
        {"database_url": "postgresql://user:secret@localhost/db"},
    ):
        with pytest.raises(SecretArtifactError):
            store.write_json(store.root / "secret.json", payload)


def test_artifact_writer_rejects_bearer_tokens_and_jwt_like_values(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, "eval-001")

    with pytest.raises(SecretArtifactError):
        store.write_json(store.root / "bearer.json", {"message": "Bearer abcdefghijklmnop"})

    with pytest.raises(SecretArtifactError):
        store.write_json(
            store.root / "jwt-value.json",
            {"message": "aaaaaaaa.bbbbbbbb.cccccccc"},
        )


def test_artifact_writer_does_not_serialize_secret_settings(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, "eval-001")

    @dataclass(frozen=True)
    class SecretSettings:
        llm_api_key: str
        harmless: str

    with pytest.raises(SecretArtifactError):
        store.write_json(
            store.root / "settings.json",
            {"classification": TrialClassification.SCORED, "settings": SecretSettings("x", "ok")},
        )

    assert not (store.root / "settings.json").exists()


def test_same_payload_produces_same_sha256(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, "eval-001")
    first = store.root / "first.json"
    second = store.root / "second.json"
    payload = {"case_id": "Q001", "values": [3, 2, 1], "ok": True}

    first_hash = store.write_json(first, payload)
    second_hash = store.write_json(second, payload)

    assert first_hash == second_hash
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8")) == payload
