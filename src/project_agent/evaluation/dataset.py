"""Load the frozen WS8 Evaluation Benchmark V0 without inferring Gold."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from project_agent.evaluation.models import (
    CorpusDocument,
    EvaluationCase,
    GoldExecution,
    GoldRecord,
    GoldScoring,
    GoldScoringStatus,
    RunProtocol,
)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return cast(dict[str, Any], payload)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {path}:{line_no}")
            records.append(cast(dict[str, Any], payload))
    return records


def _optional_text(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    root: Path
    dataset_version: str
    data_provenance: str
    corpus_version: str
    gold_schema_version: str
    metric_definition_version: str
    cases: tuple[EvaluationCase, ...]
    gold_by_case: Mapping[str, GoldRecord]
    documents_by_code: Mapping[str, CorpusDocument]
    integrity: Mapping[str, Any]
    manifest: Mapping[str, Any]

    def gold_for(self, case_id: str) -> GoldRecord:
        return self.gold_by_case[case_id]

    def document_for(self, doc_code: str) -> CorpusDocument:
        return self.documents_by_code[doc_code]


def _load_cases(path: Path) -> tuple[EvaluationCase, ...]:
    cases_by_id: dict[str, EvaluationCase] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            case_id = row["question_id"]
            if case_id in cases_by_id:
                raise ValueError(f"duplicate question case_id: {case_id}")
            cases_by_id[case_id] = EvaluationCase(
                case_id=case_id,
                split=row["split"],
                priority=row["priority"],
                project_code=row["project_code"],
                user_alias=row["user_id"],
                user_role=row["user_role"],
                question_type=row["question_type"],
                question=row["question"],
                expected_behavior=row["expected_behavior"],
                expected_source_type=row["expected_source_type"],
                expected_identifier=_optional_text(row.get("expected_identifier")),
                expected_project_scope=row["expected_project_scope"],
                notes=_optional_text(row.get("notes")),
            )
    return tuple(sorted(cases_by_id.values(), key=lambda item: item.case_id))


def _load_gold(path: Path, case_ids: set[str]) -> Mapping[str, GoldRecord]:
    gold_by_case: dict[str, GoldRecord] = {}
    for raw in _read_jsonl(path):
        case_id = str(raw["case_id"])
        if case_id not in case_ids:
            raise ValueError(f"gold references unknown case_id: {case_id}")
        if case_id in gold_by_case:
            raise ValueError(f"duplicate gold case_id: {case_id}")

        execution_raw = cast(dict[str, Any], raw["execution"])
        scoring_raw = cast(dict[str, Any], raw["scoring"])
        request_overrides = execution_raw.get("request_overrides")
        gold_by_case[case_id] = GoldRecord(
            schema_version=str(raw["schema_version"]),
            case_id=case_id,
            dataset_version=str(raw["dataset_version"]),
            data_provenance=str(raw["data_provenance"]),
            execution=GoldExecution(
                business_mode=str(execution_raw["business_mode"]),
                run_protocol=RunProtocol(str(execution_raw["run_protocol"])),
                project_code=str(execution_raw["project_code"]),
                user_alias=str(execution_raw["user_alias"]),
                fixture_scenario=cast(str | None, execution_raw.get("fixture_scenario")),
                setup_scenario=cast(str | None, execution_raw.get("setup_scenario")),
                fault_scenario=cast(str | None, execution_raw.get("fault_scenario")),
                request_overrides=(
                    cast(Mapping[str, Any], _freeze(request_overrides))
                    if isinstance(request_overrides, dict)
                    else None
                ),
            ),
            expected=cast(Mapping[str, Any], _freeze(raw["expected"])),
            metric_applicability=tuple(str(item) for item in raw["metric_applicability"]),
            scoring=GoldScoring(
                status=GoldScoringStatus(str(scoring_raw["status"])),
                reason=cast(str | None, scoring_raw.get("reason")),
                benchmark_finding_code=cast(
                    str | None, scoring_raw.get("benchmark_finding_code")
                ),
            ),
            authoring=cast(Mapping[str, Any], _freeze(raw.get("authoring", {}))),
            raw=cast(Mapping[str, Any], _freeze(raw)),
        )

    missing = sorted(case_ids.difference(gold_by_case))
    if missing:
        raise ValueError(f"missing gold for case_id(s): {', '.join(missing)}")
    return MappingProxyType(dict(sorted(gold_by_case.items())))


def _load_documents(path: Path) -> Mapping[str, CorpusDocument]:
    documents: dict[str, CorpusDocument] = {}
    for raw in _read_jsonl(path):
        doc_code = str(raw["doc_code"])
        if doc_code in documents:
            raise ValueError(f"duplicate corpus doc_code: {doc_code}")
        version_no_raw = raw.get("version_no")
        documents[doc_code] = CorpusDocument(
            doc_code=doc_code,
            source_path=str(raw["source_path"]),
            sha256=str(raw["sha256"]),
            project_code=str(raw["project_code"]),
            document_category=str(raw["document_category"]),
            title=str(raw["title"]),
            version_no=int(version_no_raw) if version_no_raw is not None else None,
            version_label=cast(str | None, raw.get("version_label")),
            authority_level=str(raw["authority_level"]),
            lifecycle_status=str(raw["lifecycle_status"]),
            is_current=bool(raw["is_current"]),
            effective_from=cast(str | None, raw.get("effective_from")),
            effective_to=cast(str | None, raw.get("effective_to")),
            supersedes_doc_code=cast(str | None, raw.get("supersedes_doc_code")),
            identifier_targets=tuple(
                cast(Mapping[str, Any], _freeze(item)) for item in raw["identifier_targets"]
            ),
            provider_residue_mode=str(raw["provider_residue_mode"]),
            raw=cast(Mapping[str, Any], _freeze(raw)),
        )
    return MappingProxyType(dict(sorted(documents.items())))


def load_evaluation_dataset(root: Path) -> EvaluationDataset:
    """Load one frozen evaluation dataset from its manifest-defined files.

    The join key is strictly `case_id`.  Corpus document lookup is strictly sourced
    from `corpus-manifest.jsonl`; filesystem discovery is intentionally not used.
    """

    root = root.resolve()
    manifest_raw = _read_json(root / "dataset-manifest.json")
    artifacts = cast(dict[str, Any], manifest_raw["artifacts"])
    versions = cast(dict[str, Any], manifest_raw["versions"])

    cases = _load_cases(root / str(artifacts["question_catalog"]))
    case_ids = {case.case_id for case in cases}
    gold_by_case = _load_gold(root / str(artifacts["gold_manifest"]), case_ids)
    documents_by_code = _load_documents(root / str(artifacts["corpus_manifest"]))

    return EvaluationDataset(
        root=root,
        dataset_version=str(manifest_raw["dataset_version"]),
        data_provenance=str(manifest_raw["data_provenance"]),
        corpus_version=str(versions["corpus_version"]),
        gold_schema_version=str(versions["gold_schema_version"]),
        metric_definition_version=str(versions["metric_definition_version"]),
        cases=cases,
        gold_by_case=gold_by_case,
        documents_by_code=documents_by_code,
        integrity=cast(Mapping[str, Any], _freeze(manifest_raw["integrity"])),
        manifest=cast(Mapping[str, Any], _freeze(manifest_raw)),
    )
