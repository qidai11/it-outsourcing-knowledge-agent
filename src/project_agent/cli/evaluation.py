"""WS8 runtime evaluation: frozen B7 cases and an isolated, owned fixture state.

Task 4 owns ``run``. Task 6 adds deterministic offline ``score``/``report`` replay.
Task 7 adds safety-safe live-variant manifests and offline shadow ablations.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from project_agent.cli.evaluation_prepare import (
    dedicated_database_url,
    validate_namespace,
    verify_fixture_state,
)
from project_agent.evaluation.ablations import run_ablation
from project_agent.evaluation.artifacts import ArtifactStore
from project_agent.evaluation.client import EvaluationClient
from project_agent.evaluation.dataset import load_evaluation_dataset
from project_agent.evaluation.models import TrialClassification
from project_agent.evaluation.report import report_artifact_directory, score_artifact_directory
from project_agent.evaluation.runner import (
    EvaluationRunner,
    PostgresEvaluationBackend,
    select_cases,
)
from project_agent.evaluation.scenarios import PostgresIssueScenarioDriver
from project_agent.evaluation.variants import SUPPORTED_ABLATION_NAMES
from project_agent.infrastructure.db.session import create_engine, create_session_factory

_OFFLINE_V0_DATASET_ROOT = (
    Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "v0"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project-agent-eval", description="WS8 frozen benchmark evaluation runner",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="execute frozen V0 via production Run API")
    run_parser.add_argument("--dataset", choices=("v0",), default="v0")
    run_parser.add_argument("--dataset-root", type=Path, default=Path("evaluation/datasets/v0"))
    run_parser.add_argument("--evaluation-namespace", required=True)
    run_parser.add_argument("--artifact-root", type=Path, default=Path("evaluation/artifacts"))
    run_parser.add_argument("--case", action="append", metavar="Q001")
    run_parser.add_argument("--split")
    run_parser.add_argument("--priority")
    run_parser.add_argument("--business-mode", choices=("qa", "issue_lookup", "issue_create"))
    run_parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    run_parser.add_argument("--run-timeout-seconds", type=float, default=120.0)
    run_parser.add_argument("--waiting-timeout-seconds", type=float, default=120.0)
    run_parser.add_argument("--http-timeout-seconds", type=float, default=10.0)
    run_parser.add_argument("--poll-interval-seconds", type=float, default=0.5)
    for command in ("score", "report"):
        offline = sub.add_parser(command, help=f"offline {command} saved evaluation artifacts")
        offline.add_argument("--artifact-dir", type=Path, required=True)
        offline.add_argument(
            "--dataset-root", type=Path, default=_OFFLINE_V0_DATASET_ROOT
        )
    ablate = sub.add_parser("ablate", help="run one frozen safety-safe ablation")
    ablate.add_argument("--artifact-dir", type=Path, required=True)
    ablate.add_argument("--dataset-root", type=Path, default=_OFFLINE_V0_DATASET_ROOT)
    ablate.add_argument("--variant", choices=SUPPORTED_ABLATION_NAMES, required=True)
    return parser


def _git_provenance() -> tuple[str, bool]:
    """Read-only provenance; missing .git is reported, never invented."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], capture_output=True,
            check=True, text=True, timeout=3,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            capture_output=True, check=True, text=True, timeout=5,
        ).stdout
        return commit, bool(status.strip())
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unavailable", True


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """Preflight the dedicated DB and prepared ownership state before any API call."""
    if args.dataset != "v0":
        raise ValueError("only the frozen v0 benchmark is supported")
    namespace = validate_namespace(args.evaluation_namespace)
    database_url = dedicated_database_url(
        os.getenv("WS8_EVAL_DATABASE_URL"), primary_url=os.getenv("DATABASE_URL"),
    )
    dataset = load_evaluation_dataset(args.dataset_root.resolve())
    selected = select_cases(
        dataset, case_ids=args.case, split=args.split, priority=args.priority,
        business_mode=args.business_mode,
    )
    state_file = ArtifactStore(args.artifact_root, namespace).fixture_state_path
    if not state_file.is_file():
        raise ValueError("verified fixture-state.json missing: prepare the namespace first")
    loaded = json.loads(state_file.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("fixture-state.json must be a JSON object")
    verify_fixture_state(dataset, loaded, evaluation_namespace=namespace)
    if (args.run_timeout_seconds <= 0 or args.http_timeout_seconds <= 0
            or args.waiting_timeout_seconds <= 0 or args.poll_interval_seconds <= 0):
        raise ValueError("all evaluation timeouts and polling intervals must be positive")
    secret = os.getenv("JWT_HS256_SECRET")
    if not secret or len(secret.encode("utf-8")) < 32 or secret.startswith("replace-me"):
        raise ValueError("JWT_HS256_SECRET must be the actual API signing secret")
    # Each invocation gets a new artifact directory and an isolated fault
    # request-ID scope without rewriting the persistent Task 2 fixture namespace.
    evaluation_run_id = f"eval-v0-{namespace}-{uuid4().hex}"
    store = ArtifactStore(args.artifact_root, evaluation_run_id)
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    commit, dirty = _git_provenance()
    try:
        async with EvaluationClient(
            api_base_url=args.api_base_url, fixture_state=loaded, jwt_secret=secret,
            jwt_issuer=os.getenv("JWT_ISSUER", "project-agent"),
            jwt_audience=os.getenv("JWT_AUDIENCE", "project-agent-api"),
            http_timeout_seconds=args.http_timeout_seconds,
            run_timeout_seconds=args.run_timeout_seconds,
            waiting_timeout_seconds=args.waiting_timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        ) as client:
            runner = EvaluationRunner(
                dataset, loaded, store, client, PostgresEvaluationBackend(sessions),
                scenario_driver=PostgresIssueScenarioDriver(
                    dataset_root=dataset.root,
                    evaluation_namespace=f"{namespace}/{evaluation_run_id}",
                    fixture_state=loaded, session_factory=sessions,
                ),
                git_commit=commit, dirty_worktree=dirty,
                model_alias=os.getenv("LLM_MODEL_ALIAS"),
            )
            trials = await runner.run(case_ids=tuple(item.case_id for item in selected))
    finally:
        await engine.dispose()
    counts = Counter(trial.classification for trial in trials)
    failures = counts[TrialClassification.INFRA_FAILURE] + counts[
        TrialClassification.RUNNER_FAILURE
    ]
    return {
        "evaluation_run_id": evaluation_run_id,
        "selected_count": len(selected),
        "artifact_dir": str(store.root),
        "failure_count": failures,
        "classifications": {category.value: counts[category] for category in TrialClassification},
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ablate":
        try:
            ablation_result = run_ablation(args.artifact_dir, args.dataset_root, args.variant)
        except (ValueError, KeyError, FileNotFoundError, OSError, TypeError) as exc:
            print(f"evaluation ablation error: {type(exc).__name__}", file=sys.stderr)
            return 2
        print(json.dumps(ablation_result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command in {"score", "report"}:
        try:
            if args.command == "score":
                metrics = score_artifact_directory(args.artifact_dir, args.dataset_root)
                result: dict[str, Any] = {
                    "artifact_dir": str(args.artifact_dir),
                    "metric_definition_version": metrics.metric_definition_version,
                    "acceptance_metric_count": len(metrics.acceptance_metrics),
                    "metrics_path": str(args.artifact_dir / "metrics.json"),
                }
            else:
                report, _markdown = report_artifact_directory(
                    args.artifact_dir, args.dataset_root
                )
                result = {
                    "artifact_dir": str(args.artifact_dir),
                    "pipeline_status": report["pipeline_status"]["status"],
                    "product_status": report["product_status"]["status"],
                    "report_json_path": str(args.artifact_dir / "report.json"),
                    "report_markdown_path": str(args.artifact_dir / "report.md"),
                }
        except (ValueError, KeyError, FileNotFoundError, OSError, TypeError) as exc:
            print(f"evaluation offline replay error: {type(exc).__name__}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    try:
        result = asyncio.run(run(args))
    except (ValueError, KeyError, FileNotFoundError, OSError) as exc:
        # Only the exception TYPE is printed; DB URL, HTTP bodies and tokens must
        # never leak to a shared CLI/CI log.
        print(f"evaluation preflight/runner error: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if result["failure_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
