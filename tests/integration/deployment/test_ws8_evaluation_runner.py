from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "run_ws8_evaluation_gates.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ws8_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_baseline(root: Path, *, classifications: dict[str, str]) -> Path:
    artifact_dir = root / "eval-v0-test"
    selected = sorted(classifications)
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "run-manifest.json").write_text(
        json.dumps({"evaluation_run_id": artifact_dir.name, "selected_case_ids": selected}),
        encoding="utf-8",
    )
    for case_id, classification in classifications.items():
        case_dir = artifact_dir / "cases" / case_id
        case_dir.mkdir(parents=True)
        (case_dir / "trial-001.json").write_text(
            json.dumps({"case_id": case_id, "trial_no": 1, "classification": classification}),
            encoding="utf-8",
        )
    return artifact_dir


def test_gate_requires_b7_hash_validation(tmp_path: Path) -> None:
    gate = _module()
    dataset = tmp_path / "v0"
    dataset.mkdir()
    payload = dataset / "a.txt"
    payload.write_text("frozen\n", encoding="utf-8")
    (dataset / "SHA256SUMS.txt").write_text("0" * 64 + "  a.txt\n", encoding="utf-8")
    with pytest.raises(gate.GateError, match="B7 SHA256 mismatch"):
        gate.verify_b7_hashes(dataset)


def test_gate_requires_api_postgres_worker_ragflow_and_llm_preflight() -> None:
    gate = _module()
    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pw@127.0.0.1:5432/project_agent",
        "WS8_EVAL_DATABASE_URL": "postgresql+asyncpg://user:pw@127.0.0.1:5432/project_agent_eval",
        "RAGFLOW_BASE_URL": "http://127.0.0.1:9380",
        "RAGFLOW_API_KEY": "real-ragflow-key",
        "LLM_BASE_URL": "http://127.0.0.1:11435/v1",
        "LLM_API_KEY": "real-llm-key",
        "LLM_MODEL_ALIAS": "model-a",
        "JWT_HS256_SECRET": "x" * 40,
    }
    checked = gate.validate_required_environment(env)
    assert checked["WS8_EVAL_DATABASE_URL"].endswith("project_agent_eval")


def test_gate_rejects_selected_case_missing_trial_artifact(tmp_path: Path) -> None:
    gate = _module()
    artifact_dir = _write_baseline(tmp_path, classifications={"Q001": "SCORED", "Q002": "SCORED"})
    (artifact_dir / "cases" / "Q002" / "trial-001.json").unlink()
    with pytest.raises(gate.GateError, match="exactly one trial artifact"):
        gate.validate_trial_coverage(
            artifact_dir, expected_selected=2, expected_runtime_unscorable=0
        )


def test_gate_rejects_silent_skip(tmp_path: Path) -> None:
    gate = _module()
    artifact_dir = _write_baseline(tmp_path, classifications={"Q001": "SCORED"})
    manifest = json.loads((artifact_dir / "run-manifest.json").read_text(encoding="utf-8"))
    manifest["selected_case_ids"].append("Q002")
    (artifact_dir / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(gate.GateError, match="exactly one trial artifact"):
        gate.validate_trial_coverage(
            artifact_dir, expected_selected=2, expected_runtime_unscorable=0
        )


def test_gate_accepts_product_metric_fail_when_pipeline_is_complete() -> None:
    gate = _module()
    report = {
        "pipeline_status": {"status": "COMPLETE"},
        "product_status": {"status": "FAIL"},
        "acceptance": [
            {
                "metric_id": f"m{i}",
                "status": "FAIL" if i == 0 else "PASS",
                "measured": 0.5,
                "denominator": 1,
                "notes": [],
            }
            for i in range(9)
        ],
    }
    assert gate.validate_report(report) == "FAIL"


def test_gate_fails_on_infra_or_runner_failure(tmp_path: Path) -> None:
    gate = _module()
    artifact_dir = _write_baseline(tmp_path, classifications={"Q001": "INFRA_FAILURE"})
    with pytest.raises(gate.GateError, match="pipeline classification"):
        gate.validate_trial_coverage(
            artifact_dir, expected_selected=1, expected_runtime_unscorable=0
        )


def test_gate_redacts_secrets_from_logs() -> None:
    gate = _module()
    env = {
        "LLM_API_KEY": "super-secret-llm",
        "RAGFLOW_API_KEY": "super-secret-rag",
        "DATABASE_URL": "postgresql+asyncpg://user:db-password@localhost/db",
    }
    raw = (
        "Authorization: Bearer abc.def.ghi super-secret-llm super-secret-rag "
        "postgresql+asyncpg://user:db-password@localhost/db"
    )
    redacted = gate.redact(raw, env)
    for forbidden in ("abc.def.ghi", "super-secret-llm", "super-secret-rag", "db-password"):
        assert forbidden not in redacted


def test_gate_replays_report_from_saved_raw_artifacts(tmp_path: Path) -> None:
    gate = _module()
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    payload = {"b": [2, 1], "a": {"status": "COMPLETE"}}
    for root in (before, after):
        (root / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (root / "report.json").write_text(
            json.dumps(payload, separators=(",", ":")), encoding="utf-8"
        )
        (root / "report.md").write_text("# stable\n", encoding="utf-8")
    gate.assert_replay_equal(before, after)


def test_failed_summary_never_returns_success() -> None:
    gate = _module()
    assert gate.gate_exit_code({"pipeline_gate_status": "FAILED"}) != 0
    assert gate.gate_exit_code({"pipeline_gate_status": "PASS"}) == 0


def test_compose_restore_runs_when_body_fails() -> None:
    gate = _module()
    events: list[str] = []
    def switch() -> None: events.append("switch")
    def body() -> None:
        events.append("body")
        raise gate.GateError("preflight failed")
    def restore() -> None: events.append("restore")
    with pytest.raises(gate.GateError, match="preflight failed"):
        gate.run_with_restore(switch, body, restore)
    assert events == ["switch", "body", "restore"]


def test_gate_requires_running_ragflow_image_version() -> None:
    gate = _module()
    assert gate.find_running_ragflow_image(
        ["postgres:16", "infiniflow/ragflow:v0.26.4"]
    ) == "infiniflow/ragflow:v0.26.4"
    with pytest.raises(gate.GateError, match="v0.26.4"):
        gate.find_running_ragflow_image(["infiniflow/ragflow:v0.26.3"])


def test_gate_rejects_placeholder_provider_or_jwt_configuration() -> None:
    gate = _module()
    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pw@127.0.0.1:5432/project_agent",
        "WS8_EVAL_DATABASE_URL": "postgresql+asyncpg://user:pw@127.0.0.1:5432/project_agent_eval",
        "RAGFLOW_BASE_URL": "http://127.0.0.1:9380",
        "RAGFLOW_API_KEY": "replace-me",
        "LLM_BASE_URL": "http://127.0.0.1:11435/v1",
        "LLM_API_KEY": "real-llm-key",
        "LLM_MODEL_ALIAS": "model-a",
        "JWT_HS256_SECRET": "x" * 40,
    }
    with pytest.raises(gate.GateError, match="placeholder"):
        gate.validate_required_environment(env)


def test_compose_override_is_plain_valid_yaml_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _module()
    monkeypatch.setattr(
        gate.tempfile,
        "mkstemp",
        lambda **_: (
            os.open(tmp_path / "override.yaml", os.O_CREAT | os.O_RDWR),
            str(tmp_path / "override.yaml"),
        ),
    )
    env = {
        "WS8_EVAL_DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1:5432/project_agent_eval",
        "RAGFLOW_BASE_URL": "http://127.0.0.1:9380",
        "LLM_BASE_URL": "http://127.0.0.1:11435/v1",
    }
    path, runtime_env = gate._write_compose_override(env)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("services:\n  app-api:\n")
    assert '\n"' not in text
    assert "host.docker.internal" in runtime_env["WS8_EVAL_CONTAINER_DATABASE_URL"]


def test_compose_restore_runs_even_if_switch_raises() -> None:
    gate = _module()
    events: list[str] = []
    def switch() -> None:
        events.append("switch")
        raise gate.GateError("compose partially changed")
    def body() -> None: events.append("body")
    def restore() -> None: events.append("restore")
    with pytest.raises(gate.GateError, match="partially changed"):
        gate.run_with_restore(switch, body, restore)
    assert events == ["switch", "restore"]


def test_runtime_preflight_waits_for_compose_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _module()
    outputs = iter(
        [
            '\n'.join(
                json.dumps(row)
                for row in (
                    {"Service": "postgres", "State": "running", "Health": "healthy"},
                    {"Service": "app-api", "State": "running", "Health": "starting"},
                    {"Service": "app-worker", "State": "running", "Health": "starting"},
                )
            ),
            '\n'.join(
                json.dumps(row)
                for row in (
                    {"Service": "postgres", "State": "running", "Health": "healthy"},
                    {"Service": "app-api", "State": "running", "Health": "healthy"},
                    {"Service": "app-worker", "State": "running", "Health": "healthy"},
                )
            ),
        ]
    )

    class Completed:
        def __init__(self, stdout: str, returncode: int = 0) -> None:
            self.stdout = stdout
            self.returncode = returncode

    monkeypatch.setattr(
        gate,
        "_compose",
        lambda *_args, **_kwargs: Completed(next(outputs)),
    )
    monkeypatch.setattr(gate.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(gate, "_wait_http_ready", lambda *_args, **_kwargs: {"status": "ready"})
    monkeypatch.setattr(
        gate,
        "_run",
        lambda *_args, **_kwargs: Completed("", 0),
    )

    gate._runtime_preflight({}, Path("/tmp/override.yaml"), timeout_seconds=1.0)


def test_ws7_live_boundary_runner_accepts_ws8_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_ws7_live_gates as ws7

    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1:5432/project_agent",
        "RAGFLOW_BASE_URL": "http://127.0.0.1:9380",
        "RAGFLOW_API_KEY": "rag-key",
        "LLM_BASE_URL": "http://127.0.0.1:11435/v1",
        "LLM_API_KEY": "llm-key",
        "LLM_MODEL_ALIAS": "model-a",
        "JWT_HS256_SECRET": "x" * 40,
    }

    def checked(command, _env, *, label):  # type: ignore[no-untyped-def]
        del _env, label
        if tuple(command) == ("git", "branch", "--show-current"):
            return "feat/ws8"
        if tuple(command) == ("git", "rev-parse", "HEAD"):
            return "abc123"
        if tuple(command) == ("git", "status", "--short"):
            return ""
        return ""

    healthy = {
        name: {"Service": name, "State": "running", "Health": "healthy"}
        for name in ("postgres", "app-api", "app-worker")
    }
    monkeypatch.setattr(ws7, "_checked", checked)
    monkeypatch.setattr(ws7, "_compose_services", lambda _env: healthy)
    monkeypatch.setattr(ws7, "_probe_url", lambda _url: (200, "ok"))

    result = ws7._required_preflight(env)
    assert result["branch"] == "feat/ws8"
