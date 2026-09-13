from __future__ import annotations

import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "docs/business/company-discovery.md",
    "docs/business/v1-scope.md",
    "docs/business/roles-and-permissions.md",
    "docs/business/document-catalog.md",
    "docs/business/document-lifecycle.md",
    "docs/business/sandbox-issue-workflow.md",
    "docs/business/forbidden-claims.md",
    "docs/business/product-positioning.md",
    "docs/business/evolution-roadmap.md",
    "docs/business/task0-status.md",
    "docs/adr/0004-v1-architecture-lock.md",
    "evaluation/datasets/v0/question-catalog.csv",
    "evaluation/datasets/v0/README.md",
]

REQUIRED_QTYPES = {
    "exact_identifier",
    "api_path",
    "database_table",
    "error_code",
    "version",
    "no_answer",
    "cross_project_identifier",
    "unauthorized_project",
    "prompt_injection",
    "issue_draft",
    "possible_duplicate",
    "idempotency",
}

PROJECTS = {"PRJ-RETAIL-ALPHA", "PRJ-LOGISTICS-BETA"}

def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)

def main() -> int:
    missing = [p for p in REQUIRED_FILES if not (ROOT / p).exists()]
    if missing:
        fail(f"missing required files: {missing}")

    catalog = ROOT / "evaluation/datasets/v0/question-catalog.csv"
    with catalog.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if len(rows) < 30:
        fail(f"question catalog must contain >=30 rows, got {len(rows)}")

    p0 = [r for r in rows if r["priority"] == "P0"]
    if len(p0) < 10:
        fail(f"P0 set must contain >=10 rows, got {len(p0)}")

    projects = {r["project_code"] for r in rows}
    if not PROJECTS.issubset(projects):
        fail(f"missing project coverage: {PROJECTS - projects}")

    qtypes = {r["question_type"] for r in rows}
    missing_types = REQUIRED_QTYPES - qtypes
    if missing_types:
        fail(f"missing question types: {sorted(missing_types)}")

    ids = [r["question_id"] for r in rows]
    if len(ids) != len(set(ids)):
        fail("question_id contains duplicates")

    if any(not r["expected_behavior"].strip() for r in rows):
        fail("expected_behavior cannot be blank")

    print("[PASS] Task 0 engineering baseline is valid")
    print(f"       questions: {len(rows)}")
    print(f"       P0 cases : {len(p0)}")
    print(f"       projects : {sorted(PROJECTS)}")
    print("       real-business interviews remain explicitly PENDING")
    return 0

if __name__ == "__main__":
    sys.exit(main())
