"""WS8 runbook contract: no magic cleanup or stored JWT instructions."""

from pathlib import Path


def test_runbook_documents_all_three_modes_and_live_safety_gates() -> None:
    root = Path(__file__).resolve().parents[3]
    runbook = root / "docs" / "runbooks" / "ws8-evaluation-fixtures.md"
    text = runbook.read_text(encoding="utf-8")
    for required in (
        "project-agent-eval-prepare prepare",
        "project-agent-eval-prepare verify",
        "project-agent-eval-prepare cleanup",
        "--evaluation-namespace",
        "--confirm-cleanup",
        "--with-ragflow",
        "WS8_EVAL_DATABASE_URL",
        "DATABASE_URL",
        "RAGFLOW_BASE_URL",
        "RAGFLOW_API_KEY",
        "mint_fixture_identity_jwt",
        "JWT_HS256_SECRET",
        "fixture-state.json",
    ):
        assert required in text, required


def test_runbook_documents_safe_partial_provider_recovery() -> None:
    root = Path(__file__).resolve().parents[3]
    content = (root / "docs/runbooks/ws8-evaluation-fixtures.md").read_text(encoding="utf-8")
    for required in (
        "--recover-dataset",
        "fixture-state.json",
        "dataset ID",
        "description",
        "same namespace",
    ):
        assert required in content
