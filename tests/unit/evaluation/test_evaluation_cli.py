"""Task 4 CLI contract: explicit owner namespace, no silent skip, no credentials in output."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_agent.cli import evaluation

ROOT = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "v0"


def test_cli_has_frozen_run_selection_and_no_skip_failures() -> None:
    parser = evaluation.build_parser()
    args = parser.parse_args([
        "run", "--evaluation-namespace", "task4-unit", "--case", "Q014",
        "--case", "Q049", "--split", "dev", "--priority", "P0",
        "--business-mode", "qa", "--api-base-url", "http://localhost:8000",
        "--run-timeout-seconds", "2.5",
    ])
    assert args.case == ["Q014", "Q049"]
    assert args.dataset == "v0"
    assert args.run_timeout_seconds == 2.5
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--evaluation-namespace", "n", "--skip-failures"])


def test_cli_ablate_requires_frozen_task7_arguments() -> None:
    with pytest.raises(SystemExit):
        evaluation.build_parser().parse_args(["ablate"])


@pytest.mark.asyncio
async def test_cli_scope_only_run_emits_manifest_and_trial_without_api_or_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """For frozen unsupported cases the runner never calls an external system."""
    namespace = "task4-unit"
    state_file = tmp_path / namespace / "fixture-state.json"
    state_file.parent.mkdir()
    state_file.write_text(json.dumps({"evaluation_namespace": namespace, "project_ids": {},
                                      "user_ids": {}}))
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://a:b@localhost/main")
    monkeypatch.setenv("WS8_EVAL_DATABASE_URL", "postgresql+asyncpg://a:b@localhost/ws8_eval")
    monkeypatch.setenv("JWT_HS256_SECRET", "z" * 48)
    class NoConnectionEngine:
        async def dispose(self): pass
    monkeypatch.setattr(evaluation, "create_engine", lambda url: NoConnectionEngine())
    monkeypatch.setattr(evaluation, "create_session_factory", lambda engine: object())
    checked = []
    monkeypatch.setattr(evaluation, "verify_fixture_state", lambda dataset, state, *,
                        evaluation_namespace: checked.append(evaluation_namespace))
    args = evaluation.build_parser().parse_args([
        "run", "--evaluation-namespace", namespace, "--artifact-root", str(tmp_path),
        "--dataset-root", str(ROOT), "--case", "Q014", "--case", "Q046",
        "--case", "Q049",
    ])
    result = await evaluation.run(args)
    assert result["selected_count"] == 3
    assert result["failure_count"] == 0
    assert checked == [namespace]
    run_dir = tmp_path / result["evaluation_run_id"]
    assert (run_dir / "run-manifest.json").exists()
    assert len(list(run_dir.glob("cases/*/trial-001.json"))) == 3
    assert json.loads((run_dir / "run-manifest.json").read_text())["selected_case_ids"] == [
        "Q014", "Q046", "Q049"]


@pytest.mark.asyncio
async def test_cli_refuses_unprepared_namespace_before_engine_creation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://a:b@localhost/main")
    monkeypatch.setenv("WS8_EVAL_DATABASE_URL", "postgresql+asyncpg://a:b@localhost/ws8_eval")
    args = evaluation.build_parser().parse_args([
        "run", "--evaluation-namespace", "not-prepared", "--artifact-root", str(tmp_path),
    ])
    with pytest.raises(ValueError, match="fixture-state.json"):
        await evaluation.run(args)
    assert list(tmp_path.glob("*/run-manifest.json")) == []


def test_cli_wires_frozen_ablation_names_and_artifact_dir(tmp_path: Path) -> None:
    parser = evaluation.build_parser()
    for variant in (
        "no_exact_registry",
        "single_round_only",
        "pre_governance_shadow",
        "pre_guard_shadow",
    ):
        args = parser.parse_args(
            ["ablate", "--artifact-dir", str(tmp_path / "baseline"), "--variant", variant]
        )
        assert args.artifact_dir == tmp_path / "baseline"
        assert args.variant == variant
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["ablate", "--artifact-dir", str(tmp_path / "baseline"), "--variant", "acl_off"]
        )


def test_cli_shadow_ablation_is_offline_and_emits_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    called = []

    def fake_run_ablation(
        artifact_dir: Path, dataset_root: Path, variant: str
    ):  # type: ignore[no-untyped-def]
        called.append((artifact_dir, dataset_root, variant))
        return {"variant": variant, "mode": "shadow", "artifact_path": "x"}
    monkeypatch.setattr(evaluation, "run_ablation", fake_run_ablation, raising=False)
    rc = evaluation.main(
        [
            "ablate",
            "--artifact-dir",
            str(tmp_path / "baseline"),
            "--dataset-root",
            str(ROOT),
            "--variant",
            "pre_guard_shadow",
        ]
    )
    assert rc == 0
    assert called == [(tmp_path / "baseline", ROOT, "pre_guard_shadow")]
    assert json.loads(capsys.readouterr().out)["mode"] == "shadow"
