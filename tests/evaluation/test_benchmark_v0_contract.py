from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = REPO_ROOT / "evaluation" / "datasets" / "v0"

EXPECTED_CASE_IDS = {f"Q{index:03d}" for index in range(1, 51)}
EXPECTED_RUNTIME_SCOPE_UNSCORABLE = {"Q014", "Q046", "Q049"}
EXPECTED_RUNTIME_FINDING_CODES = {
    "Q014": "FUZZY_IDENTIFIER_NOT_COMPOSED",
    "Q046": "COMPANY_PUBLIC_SCOPE_UNSUPPORTED",
    "Q049": "ISSUE_KEY_EXACT_LOOKUP_UNSUPPORTED",
}
EXPECTED_METRIC_POPULATIONS = {
    "exact_identifier_hit_at_10": 14,
    "evidence_recall_at_10": 27,
    "current_version_hit_rate": 7,
    "citation_id_validity": 25,
    "no_answer_refusal_accuracy": 3,
    "cross_project_evidence": 9,
    "unconfirmed_issue_creation": 5,
    "duplicate_issue_side_effects": 2,
    "critical_regression": 15,
}
EXPECTED_FILE_SHA256 = {
    "B7_FREEZE_REVIEW.json": "9d5999a1b718ac675d2b94955adaa0f4189776be437b5dd5e2bfffcfcd4f4981",
    "BENCHMARK_FREEZE_REVIEW.md": (
        "453d3dbdb65732f8c0682a24db53a2a977be29a0e43aecb4bb46a95932c2f3aa"
    ),
    "BENCHMARK_VALIDATION.md": "478e8c4a5a28975519fcd2060a63ff84983ce28043b0ffc533a04ef99299c9b2",
    "FINAL_STATIC_VALIDATION.json": (
        "3d84dfcd8910b58d5a64ed30c814a0bc93f85d914bee80e54f179501669cc34a"
    ),
    "corpus-manifest.jsonl": "c899de928f2c48d9ef27abb3a0e5cebee8ee1aeca97e03b35e7c062a70aa1512",
    "dataset-manifest.json": "cb138d84f8af2e6e76c906aab9549e90668a2ed48c0f60031843b9efdbf1024d",
    "fixtures/fault-scenarios.json": (
        "2eba568c8f56efa77b2d071e01f1c78986febf4be1bd1c59483d2947d99a3ca2"
    ),
    "fixtures/identities.json": "2bb6c8533ae83a0163dbb419b123d68326ae6156d34065e7db1a9f9c866eeb7e",
    "fixtures/memberships.json": "a083009633a7914bfd826325c5e3ffd121ef11919ab89def0566c37d097cc422",
    "fixtures/sandbox-issues.json": (
        "416c26db09e5e4e4f3045da436e4ef2d0eb9391add044a2792b4686f5459b9c1"
    ),
    "gold-manifest.jsonl": "05e6962b927762dc85cb8f5217cf8d8970cab98b2214b92cb27aff3b3bc388b1",
    "gold-manifest.schema.json": "4d37d43936a35d1a1f11a45a9df834d6432cc268e678abcefbfbdb74d0b8f0bb",
    "question-catalog.csv": "c79eb4c30395308216d271fb3f632f5ba1256ab452c15145943ddf021d1d94e5",
}
EXPECTED_AGGREGATE_SHA256 = {
    "corpus_sha256": "e880c250b570f9419528b8958cec21c7a239e7394e0c8cc3d54aad1688cc9521",
    "fixtures_sha256": "30af875821a8bf4f0bec8f2721276d7f6d05683359dcd3cbd2d958f756d0e41e",
}
EXPECTED_B7_FILES = {
    "B7_FREEZE_REVIEW.json",
    "BENCHMARK_FREEZE_REVIEW.md",
    "BENCHMARK_VALIDATION.md",
    "FINAL_STATIC_VALIDATION.json",
    "README.md",
    "SHA256SUMS.txt",
    "corpus-manifest.jsonl",
    "dataset-manifest.json",
    "gold-manifest.jsonl",
    "gold-manifest.schema.json",
    "question-catalog.csv",
    "fixtures/fault-scenarios.json",
    "fixtures/identities.json",
    "fixtures/memberships.json",
    "fixtures/sandbox-issues.json",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_catalog() -> list[dict[str, str]]:
    with (DATASET_ROOT / "question-catalog.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


def test_b7_frozen_artifacts_are_present() -> None:
    missing = sorted(
        relative_path
        for relative_path in EXPECTED_B7_FILES
        if not (DATASET_ROOT / relative_path).is_file()
    )
    assert missing == []

    corpus_files = sorted((DATASET_ROOT / "corpus").rglob("*.md"))
    assert len(corpus_files) == 22


def test_b7_sha256s_match_frozen_files() -> None:
    checksum_file = DATASET_ROOT / "SHA256SUMS.txt"
    checksum_lines = [
        line.strip()
        for line in checksum_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert checksum_lines

    parsed_checksums = {}
    for line in checksum_lines:
        expected_hash, relative_path = line.split(maxsplit=1)
        parsed_checksums[relative_path] = expected_hash
        target = (DATASET_ROOT / relative_path).resolve()
        assert target.is_relative_to(DATASET_ROOT.resolve())
        assert target.is_file(), relative_path
        assert _sha256(target) == expected_hash, relative_path

    assert parsed_checksums == EXPECTED_FILE_SHA256

    corpus_manifest = _load_jsonl(DATASET_ROOT / "corpus-manifest.jsonl")
    assert len(corpus_manifest) == 22
    for record in corpus_manifest:
        relative_path = record["source_path"]
        target = (DATASET_ROOT / relative_path).resolve()
        assert target.is_relative_to(DATASET_ROOT.resolve())
        assert target.is_file(), relative_path
        assert _sha256(target) == record["sha256"], relative_path


def test_b7_manifest_has_expected_counts() -> None:
    manifest = _load_json(DATASET_ROOT / "dataset-manifest.json")
    assert manifest["status"] == "V0_FROZEN_READY_FOR_WS8_IMPLEMENTATION"
    assert manifest["dataset_version"] == "v0"
    assert manifest["data_provenance"] == "synthetic"
    assert manifest["counts"] == {
        "alpha_documents": 10,
        "beta_documents": 9,
        "company_public_documents": 3,
        "corpus_documents": 22,
        "frozen_document_facts": 40,
        "gold_records": 50,
        "known_unscorable_runtime_scope_cases": 3,
        "question_cases": 50,
        "scorable_gold_cases": 47,
        "unscorable_runtime_scope_cases": 3,
    }

    freeze_review = _load_json(DATASET_ROOT / "B7_FREEZE_REVIEW.json")
    assert freeze_review["decision"] == "PASS_READY_FOR_WS8_IMPLEMENTATION"
    assert freeze_review["benchmark_side_blocker_count"] == 0

    for key, expected_hash in EXPECTED_AGGREGATE_SHA256.items():
        assert manifest["integrity"][key] == expected_hash


def test_b7_gold_has_exactly_q001_through_q050() -> None:
    gold = _load_jsonl(DATASET_ROOT / "gold-manifest.jsonl")
    case_ids = [record["case_id"] for record in gold]

    assert len(case_ids) == 50
    assert len(set(case_ids)) == 50
    assert set(case_ids) == EXPECTED_CASE_IDS

    catalog_case_ids = {row["question_id"] for row in _load_catalog()}
    assert catalog_case_ids == EXPECTED_CASE_IDS


def test_b7_has_exactly_47_scorable_and_3_runtime_scope_unscorable() -> None:
    gold = _load_jsonl(DATASET_ROOT / "gold-manifest.jsonl")
    statuses = Counter(record["scoring"]["status"] for record in gold)

    assert statuses == Counter(
        {
            "SCORABLE": 47,
            "UNSCORABLE_RUNTIME_SCOPE": 3,
        }
    )


def test_b7_runtime_scope_set_is_exactly_q014_q046_q049() -> None:
    gold = _load_jsonl(DATASET_ROOT / "gold-manifest.jsonl")
    runtime_scope_records = {
        record["case_id"]: record["scoring"]
        for record in gold
        if record["scoring"]["status"] == "UNSCORABLE_RUNTIME_SCOPE"
    }

    assert set(runtime_scope_records) == EXPECTED_RUNTIME_SCOPE_UNSCORABLE
    assert {
        case_id: scoring["benchmark_finding_code"]
        for case_id, scoring in runtime_scope_records.items()
    } == EXPECTED_RUNTIME_FINDING_CODES
    assert all(scoring["reason"] for scoring in runtime_scope_records.values())


def test_b7_metric_populations_are_frozen() -> None:
    gold = _load_jsonl(DATASET_ROOT / "gold-manifest.jsonl")
    metric_counts = Counter(
        metric_id
        for record in gold
        for metric_id in record["metric_applicability"]
    )

    assert dict(metric_counts) == EXPECTED_METRIC_POPULATIONS


def test_b7_p0_population_is_15() -> None:
    catalog = _load_catalog()
    p0_case_ids = {
        row["question_id"] for row in catalog if row["priority"] == "P0"
    }
    assert len(p0_case_ids) == 15

    gold = _load_jsonl(DATASET_ROOT / "gold-manifest.jsonl")
    critical_regression_case_ids = {
        record["case_id"]
        for record in gold
        if "critical_regression" in record["metric_applicability"]
    }
    assert critical_regression_case_ids == p0_case_ids
