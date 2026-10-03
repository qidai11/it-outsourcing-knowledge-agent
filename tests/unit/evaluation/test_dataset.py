from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from project_agent.evaluation.dataset import load_evaluation_dataset
from project_agent.evaluation.models import GoldScoringStatus, RunProtocol

REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET_ROOT = REPO_ROOT / "evaluation" / "datasets" / "v0"


def _copy_dataset(tmp_path: Path) -> Path:
    target = tmp_path / "v0"
    shutil.copytree(DATASET_ROOT, target)
    return target


def _read_gold(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_gold(path: Path, records: list[dict[str, object]]) -> None:
    payload = "\n".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records
    )
    path.write_text(payload + "\n", encoding="utf-8")


def test_load_v0_returns_50_catalog_cases_and_50_gold_records() -> None:
    dataset = load_evaluation_dataset(DATASET_ROOT)

    assert len(dataset.cases) == 50
    assert len(dataset.gold_by_case) == 50
    assert dataset.cases[0].case_id == "Q001"
    assert dataset.cases[-1].case_id == "Q050"
    assert dataset.dataset_version == "v0"
    assert dataset.corpus_version == "v0"
    assert dataset.gold_schema_version == "gold-v1"
    assert dataset.metric_definition_version == "v1"


def test_loader_joins_catalog_and_gold_by_case_id_only(tmp_path: Path) -> None:
    dataset_root = _copy_dataset(tmp_path)
    gold_path = dataset_root / "gold-manifest.jsonl"
    records = list(reversed(_read_gold(gold_path)))
    _write_gold(gold_path, records)

    dataset = load_evaluation_dataset(dataset_root)

    assert dataset.gold_for("Q001").case_id == "Q001"
    assert dataset.gold_for("Q001").execution.project_code == "PRJ-RETAIL-ALPHA"
    assert dataset.gold_for("Q050").case_id == "Q050"


def test_loader_preserves_b7_scoring_status_and_reason() -> None:
    dataset = load_evaluation_dataset(DATASET_ROOT)

    gold = dataset.gold_for("Q014")

    assert gold.scoring.status is GoldScoringStatus.UNSCORABLE_RUNTIME_SCOPE
    assert gold.scoring.benchmark_finding_code == "FUZZY_IDENTIFIER_NOT_COMPOSED"
    assert gold.scoring.reason == (
        "Current production QA graph does not compose fuzzy spelling suggestion/identifier "
        "confirmation into the Run protocol."
    )
    assert gold.execution.run_protocol is RunProtocol.UNSCORABLE_RUNTIME_SCOPE


def test_loader_preserves_metric_applicability_without_recomputing_it() -> None:
    dataset = load_evaluation_dataset(DATASET_ROOT)

    assert dataset.gold_for("Q001").metric_applicability == (
        "exact_identifier_hit_at_10",
        "evidence_recall_at_10",
        "citation_id_validity",
    )
    assert dataset.gold_for("Q014").metric_applicability == ()


def test_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    dataset_root = _copy_dataset(tmp_path)
    catalog_path = dataset_root / "question-catalog.csv"
    rows = list(csv.DictReader(catalog_path.open(encoding="utf-8-sig", newline="")))
    fieldnames = list(rows[0])
    rows.append(dict(rows[0]))

    with catalog_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match=r"duplicate question case_id: Q001"):
        load_evaluation_dataset(dataset_root)


def test_loader_rejects_unknown_gold_case(tmp_path: Path) -> None:
    dataset_root = _copy_dataset(tmp_path)
    gold_path = dataset_root / "gold-manifest.jsonl"
    records = _read_gold(gold_path)
    unknown = dict(records[0])
    unknown["case_id"] = "Q999"
    records.append(unknown)
    _write_gold(gold_path, records)

    with pytest.raises(ValueError, match=r"gold references unknown case_id: Q999"):
        load_evaluation_dataset(dataset_root)


def test_loader_resolves_doc_codes_only_from_corpus_manifest(tmp_path: Path) -> None:
    dataset_root = _copy_dataset(tmp_path)
    extra = dataset_root / "corpus" / "PRJ-RETAIL-ALPHA" / "UNLISTED.md"
    extra.write_text("not part of frozen corpus manifest\n", encoding="utf-8")

    dataset = load_evaluation_dataset(dataset_root)

    assert dataset.document_for("A-REQ-001").source_path.endswith("A-REQ-001.md")
    assert len(dataset.documents_by_code) == 22
    with pytest.raises(KeyError):
        dataset.document_for("UNLISTED")
