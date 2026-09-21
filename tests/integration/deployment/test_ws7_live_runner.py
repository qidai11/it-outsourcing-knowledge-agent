from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import run_ws7_live_gates as runner


def _completed(
    command: tuple[str, ...],
    *,
    code: int = 0,
    output: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, code, stdout=output, stderr="")


def _pass_preflight(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        runner,
        "_required_preflight",
        lambda env: {"branch": "feat/ws7", "head": "abc123", "git_status": ""},
    )
    monkeypatch.setattr(runner, "_isolate_compose_worker", lambda env: None)
    monkeypatch.setattr(runner, "_restore_compose_worker", lambda env: None)


def test_runner_fails_when_required_preflight_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    def fail_preflight(env):  # type: ignore[no-untyped-def]
        del env
        raise runner.PreflightError("RAGFLOW_API_KEY is required")

    monkeypatch.setattr(runner, "_required_preflight", fail_preflight)

    result = runner.main(["--required", "--evidence-root", str(tmp_path)])

    assert result != 0
    summaries = list(tmp_path.glob("*/summary.json"))
    assert len(summaries) == 1
    payload = json.loads(summaries[0].read_text())
    assert payload["status"] == "INCOMPLETE"
    assert "RAGFLOW_API_KEY" in payload["preflight_error"]


def test_runner_rejects_required_gate_with_skips(
    tmp_path: Path, monkeypatch
) -> None:
    _pass_preflight(monkeypatch)
    calls = 0

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        del kwargs
        calls += 1
        return _completed(tuple(command), output="1 passed, 1 skipped\n")

    monkeypatch.setattr(runner, "_run_process", fake_run)

    result = runner.main(["--required", "--evidence-root", str(tmp_path)])

    assert result != 0
    assert calls == 1
    payload = json.loads(next(tmp_path.glob("*/summary.json")).read_text())
    assert payload["gates"][0]["status"] == "INCOMPLETE"
    assert payload["gates"][0]["skipped"] == 1


def test_runner_stops_after_failed_gate_and_returns_nonzero(
    tmp_path: Path, monkeypatch
) -> None:
    _pass_preflight(monkeypatch)
    calls = 0

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        del kwargs
        calls += 1
        return _completed(tuple(command), code=1, output="1 failed\n")

    monkeypatch.setattr(runner, "_run_process", fake_run)

    result = runner.main(["--required", "--evidence-root", str(tmp_path)])

    assert result != 0
    assert calls == 1
    payload = json.loads(next(tmp_path.glob("*/summary.json")).read_text())
    assert len(payload["gates"]) == 1
    assert payload["gates"][0]["status"] == "FAILED"


def test_evidence_redacts_secrets_authorization_and_password_dsn(tmp_path: Path) -> None:
    env = {
        "RAGFLOW_API_KEY": "ragflow-secret-value",
        "LLM_API_KEY": "llm-secret-value",
        "JWT_HS256_SECRET": "jwt-secret-value",
        "DATABASE_URL": (
            "postgresql+asyncpg://project_agent:db-password@localhost:5432/project_agent"
        ),
    }
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signaturevalue"
    raw = (
        "ragflow-secret-value llm-secret-value jwt-secret-value "
        f"Authorization: Bearer {token} "
        "postgresql+asyncpg://project_agent:db-password@localhost:5432/project_agent"
    )

    redacted = runner.redact(raw, env)
    path = tmp_path / "gate.log"
    path.write_text(redacted)

    persisted = path.read_text()
    for forbidden in (
        "ragflow-secret-value",
        "llm-secret-value",
        "jwt-secret-value",
        token,
        "db-password",
    ):
        assert forbidden not in persisted
    assert "[REDACTED]" in persisted


def test_summary_records_every_required_gate_and_final_pass(
    tmp_path: Path, monkeypatch
) -> None:
    _pass_preflight(monkeypatch)

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return _completed(tuple(command), output="2 passed\n")

    monkeypatch.setattr(runner, "_run_process", fake_run)

    result = runner.main(["--required", "--evidence-root", str(tmp_path)])

    assert result == 0
    payload = json.loads(next(tmp_path.glob("*/summary.json")).read_text())
    assert payload["status"] == "PASS"
    assert [item["name"] for item in payload["gates"]] == list(runner.REQUIRED_GATE_NAMES)
    assert all(item["status"] == "PASS" for item in payload["gates"])
    assert all(item["skipped"] == 0 for item in payload["gates"])
