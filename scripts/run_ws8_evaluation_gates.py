from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "feat/ws8"
EXPECTED_ALEMBIC = "0005_run_runtime_envelope"
EXPECTED_RAGFLOW_VERSION = "v0.26.4"
EXPECTED_SELECTED = 50
EXPECTED_RUNTIME_UNSCORABLE = 3
EXPECTED_ACCEPTANCE_METRICS = 9
LIVE_VARIANTS = ("no_exact_registry", "single_round_only")
SHADOW_VARIANTS = ("pre_governance_shadow", "pre_guard_shadow")
REQUIRED_ENV = (
    "DATABASE_URL",
    "WS8_EVAL_DATABASE_URL",
    "RAGFLOW_BASE_URL",
    "RAGFLOW_API_KEY",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL_ALIAS",
    "JWT_HS256_SECRET",
)
SECRET_ENV = (
    "DATABASE_URL",
    "WS8_EVAL_DATABASE_URL",
    "RAGFLOW_API_KEY",
    "LLM_API_KEY",
    "JWT_HS256_SECRET",
)
PLACEHOLDER_MARKERS = ("replace-me", "changeme", "example-key", "your-api-key")
JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"(?![A-Za-z0-9_-])"
)
BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+|bearer\s+)[^\s,;]+")
DSN_RE = re.compile(r"(?P<scheme>postgres(?:ql)?(?:\+[^:]+)?://)(?P<user>[^:/\s]+):[^@/\s]+@")


class GateError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise GateError(f"JSON artifact must be an object: {path}")
    return value


def verify_b7_hashes(dataset_root: Path) -> dict[str, str]:
    dataset_root = dataset_root.resolve()
    manifest = dataset_root / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise GateError("B7 SHA256 manifest missing")
    checked: dict[str, str] = {}
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise GateError("invalid B7 SHA256 manifest line")
        expected, relative = parts
        relative = relative.lstrip("*")
        path = (dataset_root / relative).resolve()
        if not path.is_relative_to(dataset_root) or not path.is_file():
            raise GateError(f"B7 frozen file missing: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise GateError(f"B7 SHA256 mismatch: {relative}")
        checked[relative] = actual
    if not checked:
        raise GateError("B7 SHA256 manifest is empty")
    return checked


def validate_required_environment(env: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    missing: list[str] = []
    placeholders: list[str] = []
    for name in REQUIRED_ENV:
        value = str(env.get(name, "")).strip()
        if not value:
            missing.append(name)
            continue
        result[name] = value
        lowered = value.casefold()
        if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            placeholders.append(name)
    if missing:
        raise GateError("missing required environment: " + ", ".join(missing))
    if placeholders:
        raise GateError("placeholder configuration is forbidden: " + ", ".join(placeholders))
    if len(result["JWT_HS256_SECRET"].encode("utf-8")) < 32:
        raise GateError("JWT_HS256_SECRET must contain at least 32 bytes")
    if result["DATABASE_URL"] == result["WS8_EVAL_DATABASE_URL"]:
        raise GateError("WS8_EVAL_DATABASE_URL must differ from DATABASE_URL")
    if "eval" not in result["WS8_EVAL_DATABASE_URL"].casefold():
        raise GateError("WS8_EVAL_DATABASE_URL must name an evaluation database")
    return result


def redact(text: str, env: Mapping[str, str]) -> str:
    sanitized = text
    values = {str(env.get(name, "")).strip() for name in SECRET_ENV}
    values.discard("")
    for value in sorted(values, key=len, reverse=True):
        sanitized = sanitized.replace(value, "[REDACTED]")
    sanitized = BEARER_RE.sub(lambda m: m.group(1) + "[REDACTED]", sanitized)
    sanitized = JWT_RE.sub("[REDACTED-JWT]", sanitized)
    sanitized = DSN_RE.sub(r"\g<scheme>\g<user>:[REDACTED]@", sanitized)
    return sanitized


def find_running_ragflow_image(images: Sequence[str]) -> str:
    candidates = sorted({item.strip() for item in images if "infiniflow/ragflow:" in item})
    expected_suffix = f":{EXPECTED_RAGFLOW_VERSION}"
    matching = [item for item in candidates if item.endswith(expected_suffix)]
    if len(matching) != 1:
        observed = ", ".join(candidates) or "none"
        raise GateError(
            "running RAGFlow image must be pinned to "
            f"{EXPECTED_RAGFLOW_VERSION}; observed {observed}"
        )
    wrong = [item for item in candidates if not item.endswith(expected_suffix)]
    if wrong:
        raise GateError("multiple running RAGFlow versions detected")
    return matching[0]


def validate_trial_coverage(
    artifact_dir: Path,
    *,
    expected_selected: int = EXPECTED_SELECTED,
    expected_runtime_unscorable: int = EXPECTED_RUNTIME_UNSCORABLE,
) -> dict[str, int]:
    artifact_dir = artifact_dir.resolve()
    manifest = _json(artifact_dir / "run-manifest.json")
    selected = manifest.get("selected_case_ids")
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        raise GateError("run manifest selected_case_ids is invalid")
    if len(selected) != expected_selected or len(set(selected)) != len(selected):
        raise GateError(
            f"selected case count mismatch: expected {expected_selected}, got {len(selected)}"
        )
    counts: Counter[str] = Counter()
    for case_id in selected:
        paths = sorted((artifact_dir / "cases" / case_id).glob("trial-*.json"))
        if len(paths) != 1:
            raise GateError(f"selected case {case_id} must have exactly one trial artifact")
        trial = _json(paths[0])
        if trial.get("case_id") != case_id or trial.get("trial_no") != 1:
            raise GateError(f"trial identity mismatch for {case_id}")
        classification = str(trial.get("classification", ""))
        counts[classification] += 1
    forbidden = {
        "UNSCORABLE_GOLD": counts["UNSCORABLE_GOLD"],
        "INFRA_FAILURE": counts["INFRA_FAILURE"],
        "RUNNER_FAILURE": counts["RUNNER_FAILURE"],
    }
    if any(forbidden.values()):
        raise GateError(f"unexpected pipeline classification: {forbidden}")
    if counts["UNSCORABLE_RUNTIME_SCOPE"] != expected_runtime_unscorable:
        raise GateError(
            "runtime-scope unscorable count mismatch: "
            f"expected {expected_runtime_unscorable}, got {counts['UNSCORABLE_RUNTIME_SCOPE']}"
        )
    expected_scored = expected_selected - expected_runtime_unscorable
    if counts["SCORED"] != expected_scored:
        raise GateError(
            f"attempted/scored count mismatch: expected {expected_scored}, "
            f"got {counts['SCORED']}"
        )
    return dict(counts)


def validate_report(report: Mapping[str, Any]) -> str:
    pipeline = report.get("pipeline_status")
    product = report.get("product_status")
    acceptance = report.get("acceptance")
    if not isinstance(pipeline, Mapping) or pipeline.get("status") != "COMPLETE":
        raise GateError("report pipeline_status is not COMPLETE")
    if not isinstance(product, Mapping):
        raise GateError("report product_status missing")
    if not isinstance(acceptance, list) or len(acceptance) != EXPECTED_ACCEPTANCE_METRICS:
        raise GateError("report must contain exactly nine acceptance metrics")
    allowed = {"PASS", "FAIL", "UNSCORABLE", "NOT_APPLICABLE"}
    for raw in acceptance:
        if not isinstance(raw, Mapping):
            raise GateError("acceptance metric entry must be an object")
        status = raw.get("status")
        if status not in allowed:
            raise GateError("acceptance metric has invalid status")
        measured = raw.get("measured")
        notes = raw.get("notes")
        if status in {"PASS", "FAIL"} and measured is None:
            raise GateError("measured acceptance metric cannot omit value")
        if status in {"UNSCORABLE", "NOT_APPLICABLE"} and not notes:
            raise GateError("unscorable/not-applicable metric requires explicit notes")
    return str(product.get("status", ""))


def assert_replay_equal(before_dir: Path, after_dir: Path) -> None:
    for name in ("metrics.json", "report.json"):
        if _json(before_dir / name) != _json(after_dir / name):
            raise GateError(f"offline replay semantic mismatch: {name}")
    before_md = (before_dir / "report.md").read_text(encoding="utf-8")
    after_md = (after_dir / "report.md").read_text(encoding="utf-8")
    if before_md != after_md:
        raise GateError("offline replay byte mismatch: report.md")


def gate_exit_code(summary: Mapping[str, Any]) -> int:
    return 0 if summary.get("pipeline_gate_status") == "PASS" else 1


def run_with_restore(
    switch: Callable[[], Any], body: Callable[[], Any], restore: Callable[[], Any]
) -> Any:
    try:
        switch()
        return body()
    finally:
        restore()


def _run(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path = ROOT,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        tail = "\n".join((completed.stdout or "").splitlines()[-30:])
        raise GateError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{redact(tail, env)}"
        )
    return completed


def _command_json(command: Sequence[str], *, env: Mapping[str, str]) -> dict[str, Any]:
    completed = _run(command, env=env)
    lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise GateError(f"command did not emit a JSON object: {' '.join(command)}")


def _containerize_url(value: str) -> str:
    parts = urlsplit(value)
    host = parts.hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return value
    userinfo = ""
    if parts.username is not None:
        userinfo = parts.username
        if parts.password is not None:
            userinfo += ":" + parts.password
        userinfo += "@"
    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"{userinfo}host.docker.internal{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _write_compose_override(env: Mapping[str, str]) -> tuple[Path, dict[str, str]]:
    runtime_env = dict(env)
    runtime_env["WS8_EVAL_CONTAINER_DATABASE_URL"] = _containerize_url(env["WS8_EVAL_DATABASE_URL"])
    runtime_env["WS8_EVAL_CONTAINER_RAGFLOW_BASE_URL"] = _containerize_url(env["RAGFLOW_BASE_URL"])
    runtime_env["WS8_EVAL_CONTAINER_LLM_BASE_URL"] = _containerize_url(env["LLM_BASE_URL"])
    fd, raw_path = tempfile.mkstemp(prefix="ws8-task8-compose-", suffix=".yaml", dir="/tmp")
    os.close(fd)
    path = Path(raw_path)
    path.write_text(
        "services:\n"
        "  app-api:\n"
        "    environment:\n"
        "      DATABASE_URL: ${WS8_EVAL_CONTAINER_DATABASE_URL:?required}\n"
        "      RAGFLOW_BASE_URL: ${WS8_EVAL_CONTAINER_RAGFLOW_BASE_URL:?required}\n"
        "      RAGFLOW_API_KEY: ${RAGFLOW_API_KEY:?required}\n"
        "      LLM_BASE_URL: ${WS8_EVAL_CONTAINER_LLM_BASE_URL:?required}\n"
        "      LLM_API_KEY: ${LLM_API_KEY:?required}\n"
        "      LLM_MODEL_ALIAS: ${LLM_MODEL_ALIAS:?required}\n"
        "      JWT_HS256_SECRET: ${JWT_HS256_SECRET:?required}\n"
        "      RAGFLOW_EXPECTED_VERSION: v0.26.4\n"
        "  app-worker:\n"
        "    environment:\n"
        "      DATABASE_URL: ${WS8_EVAL_CONTAINER_DATABASE_URL:?required}\n"
        "      RAGFLOW_BASE_URL: ${WS8_EVAL_CONTAINER_RAGFLOW_BASE_URL:?required}\n"
        "      RAGFLOW_API_KEY: ${RAGFLOW_API_KEY:?required}\n"
        "      LLM_BASE_URL: ${WS8_EVAL_CONTAINER_LLM_BASE_URL:?required}\n"
        "      LLM_API_KEY: ${LLM_API_KEY:?required}\n"
        "      LLM_MODEL_ALIAS: ${LLM_MODEL_ALIAS:?required}\n"
        "      JWT_HS256_SECRET: ${JWT_HS256_SECRET:?required}\n"
        "      RAGFLOW_EXPECTED_VERSION: v0.26.4\n",
        encoding="utf-8",
    )
    return path, runtime_env


def _compose(
    env: Mapping[str, str], override: Path | None, *args: str
) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "-f", "compose.yaml"]
    if override is not None:
        command += ["-f", str(override)]
    command.extend(args)
    return _run(command, env=env, timeout=900)


def _wait_http_ready(url: str, *, timeout_seconds: float = 120.0) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_seconds
    last = "not attempted"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw)
                if (
                    response.status == 200
                    and isinstance(payload, dict)
                    and payload.get("status") == "ready"
                ):
                    return payload
                last = f"HTTP {response.status}: {raw[:200]}"
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last = type(exc).__name__
        time.sleep(1.0)
    raise GateError(f"GET /ready did not become ready: {last}")


def _git_preflight(env: Mapping[str, str]) -> dict[str, Any]:
    branch = _run(("git", "branch", "--show-current"), env=env).stdout.strip()
    if branch != EXPECTED_BRANCH:
        raise GateError(f"required branch is {EXPECTED_BRANCH}, got {branch or '<detached>'}")
    head = _run(("git", "rev-parse", "HEAD"), env=env).stdout.strip()
    status = _run(
        ("git", "status", "--porcelain", "--untracked-files=normal"), env=env
    ).stdout
    tracked = _run(
        ("git", "status", "--short", "--untracked-files=no"), env=env
    ).stdout
    return {
        "branch": branch,
        "head": head,
        "dirty_worktree": bool(status.strip()),
        "tracked_worktree_status": tracked.splitlines(),
    }


def _alembic_preflight(env: Mapping[str, str]) -> str:
    eval_env = dict(env)
    eval_env["DATABASE_URL"] = env["WS8_EVAL_DATABASE_URL"]
    output = _run((sys.executable, "-m", "alembic", "current"), env=eval_env).stdout or ""
    if EXPECTED_ALEMBIC not in output:
        raise GateError(f"evaluation DB Alembic revision must be {EXPECTED_ALEMBIC}")
    return EXPECTED_ALEMBIC


def _ragflow_preflight(env: Mapping[str, str]) -> str:
    output = _run(("docker", "ps", "--format", "{{.Image}}"), env=env).stdout or ""
    image = find_running_ragflow_image(output.splitlines())
    _run(
        (sys.executable, "scripts/check_ragflow_version.py", "--image", image),
        env=env,
        timeout=120,
    )
    return image


def _fixture_prepare_and_verify(
    env: Mapping[str, str], *, namespace: str, dataset_root: Path, artifact_root: Path
) -> None:
    common = (
        "--evaluation-namespace", namespace,
        "--dataset-root", str(dataset_root),
        "--artifact-root", str(artifact_root),
        "--with-ragflow",
    )
    _run(
        (sys.executable, "-m", "project_agent.cli.evaluation_prepare", "prepare", *common),
        env=env,
        timeout=1200,
    )
    _run(
        (sys.executable, "-m", "project_agent.cli.evaluation_prepare", "verify", *common),
        env=env,
        timeout=600,
    )


def _compose_service_rows(raw: str) -> dict[str, Mapping[str, Any]]:
    rows: list[Any] = []
    stripped = raw.strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line in stripped.splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise GateError("docker compose ps emitted invalid JSON") from exc
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        service = str(row.get("Service") or row.get("service") or "")
        if service:
            result[service] = row
    return result


def _compose_service_healthy(row: Mapping[str, Any]) -> bool:
    state = str(row.get("State") or row.get("state") or "").casefold()
    health = str(row.get("Health") or row.get("health") or "").casefold()
    status = str(row.get("Status") or row.get("status") or "").casefold()
    return state == "running" and (health == "healthy" or "(healthy)" in status)


def _runtime_preflight(
    env: Mapping[str, str], override: Path, *, timeout_seconds: float = 120.0
) -> None:
    deadline = time.monotonic() + timeout_seconds
    unhealthy: list[str] = []
    while True:
        ps = _compose(env, override, "ps", "--format", "json").stdout or ""
        services = _compose_service_rows(ps)
        unhealthy = [
            name
            for name in ("postgres", "app-api", "app-worker")
            if services.get(name) is None or not _compose_service_healthy(services[name])
        ]
        if not unhealthy:
            break
        if time.monotonic() >= deadline:
            raise GateError(
                "compose services did not become running and healthy: " + ", ".join(unhealthy)
            )
        time.sleep(1.0)
    _wait_http_ready("http://127.0.0.1:8000/ready", timeout_seconds=timeout_seconds)
    worker = _run(
        (
            sys.executable,
            "-c",
            "import urllib.request; "
            "urllib.request.urlopen('http://127.0.0.1:9101/metrics', timeout=3).read()",
        ),
        env=env,
        check=False,
    )
    if worker.returncode != 0:
        raise GateError("app-worker metrics endpoint is not healthy")


def _run_eval(
    env: Mapping[str, str], *, namespace: str, dataset_root: Path, artifact_root: Path
) -> Path:
    result = _command_json(
        (
            sys.executable,
            "-m",
            "project_agent.cli.evaluation",
            "run",
            "--dataset",
            "v0",
            "--dataset-root",
            str(dataset_root),
            "--evaluation-namespace",
            namespace,
            "--artifact-root",
            str(artifact_root),
            "--api-base-url",
            "http://127.0.0.1:8000",
        ),
        env=env,
    )
    if int(result.get("selected_count", -1)) != EXPECTED_SELECTED:
        raise GateError("evaluation CLI did not select all 50 frozen cases")
    if int(result.get("failure_count", -1)) != 0:
        raise GateError("evaluation CLI reported infrastructure/runner failure")
    path = Path(str(result.get("artifact_dir", ""))).resolve()
    if not path.is_dir():
        raise GateError("evaluation CLI artifact directory is missing")
    return path


def _patch_manifest_provenance(
    artifact_dir: Path, *, alembic_revision: str, ragflow_image: str
) -> None:
    path = artifact_dir / "run-manifest.json"
    manifest = _json(path)
    manifest["alembic_revision"] = alembic_revision
    manifest["ragflow_observed_version"] = ragflow_image.rsplit(":", 1)[-1]
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _score_and_report(
    env: Mapping[str, str], *, artifact_dir: Path, dataset_root: Path
) -> dict[str, Any]:
    for command in ("score", "report"):
        _command_json(
            (
                sys.executable,
                "-m",
                "project_agent.cli.evaluation",
                command,
                "--artifact-dir",
                str(artifact_dir),
                "--dataset-root",
                str(dataset_root),
            ),
            env=env,
        )
    report = _json(artifact_dir / "report.json")
    validate_report(report)
    return report


def _run_shadow_ablation(
    env: Mapping[str, str], *, artifact_dir: Path, dataset_root: Path, variant: str
) -> None:
    result = _command_json(
        (
            sys.executable,
            "-m",
            "project_agent.cli.evaluation",
            "ablate",
            "--artifact-dir",
            str(artifact_dir),
            "--dataset-root",
            str(dataset_root),
            "--variant",
            variant,
        ),
        env=env,
    )
    if result.get("mode") != "shadow" or result.get("requires_live_runtime") is not False:
        raise GateError(f"shadow ablation did not complete offline: {variant}")


def _prepare_live_ablation_manifest(
    env: Mapping[str, str], *, artifact_dir: Path, dataset_root: Path, variant: str
) -> None:
    result = _command_json(
        (
            sys.executable,
            "-m",
            "project_agent.cli.evaluation",
            "ablate",
            "--artifact-dir",
            str(artifact_dir),
            "--dataset-root",
            str(dataset_root),
            "--variant",
            variant,
        ),
        env=env,
    )
    if result.get("mode") != "live" or result.get("requires_live_runtime") is not True:
        raise GateError(f"live ablation manifest was not created: {variant}")


def _write_live_ablation_result(
    *, baseline_dir: Path, variant_dir: Path, dataset_root: Path, variant: str
) -> None:
    from project_agent.evaluation.ablations import build_live_ablation_result
    from project_agent.evaluation.artifacts import ArtifactStore
    from project_agent.evaluation.dataset import load_evaluation_dataset
    from project_agent.evaluation.report import load_saved_run

    base_manifest, base_trials = load_saved_run(baseline_dir)
    variant_manifest, variant_trials = load_saved_run(variant_dir)
    payload = build_live_ablation_result(
        variant,
        base_trials,
        variant_trials,
        baseline_run_id=base_manifest.evaluation_run_id,
        variant_run_id=variant_manifest.evaluation_run_id,
        dataset=load_evaluation_dataset(dataset_root),
    )
    store = ArtifactStore(baseline_dir.parent, baseline_dir.name)
    store.write_json(store.ablations_dir / variant / "ablation.json", payload)


def _start_variant_worker(env: Mapping[str, str], override: Path, variant: str) -> str:
    _compose(env, override, "stop", "app-worker")
    name = f"ws8-task8-{variant}-{os.getpid()}"
    command = [
        "docker", "compose", "-f", "compose.yaml", "-f", str(override),
        "run", "-d", "--no-deps", "--name", name,
        "-e", "WORKER_METRICS_ENABLED=false",
        "app-worker", "python", "scripts/run_ws8_evaluation_gates.py",
        "--variant-worker", variant,
    ]
    completed = _run(command, env=env, timeout=120)
    container_id = (completed.stdout or "").strip().splitlines()[-1].strip()
    if not container_id:
        raise GateError(f"failed to start controlled variant worker: {variant}")
    time.sleep(2.0)
    state = _run(
        ("docker", "inspect", "-f", "{{.State.Running}}", container_id), env=env
    ).stdout.strip()
    if state != "true":
        raise GateError(f"controlled variant worker did not stay running: {variant}")
    return container_id


def _stop_variant_worker(env: Mapping[str, str], container_id: str) -> None:
    _run(("docker", "rm", "-f", container_id), env=env, check=False, timeout=60)


def _run_live_variant(
    env: Mapping[str, str],
    *,
    override: Path,
    namespace: str,
    dataset_root: Path,
    artifact_root: Path,
    baseline_dir: Path,
    variant: str,
    alembic_revision: str,
    ragflow_image: str,
) -> Path:
    _prepare_live_ablation_manifest(
        env, artifact_dir=baseline_dir, dataset_root=dataset_root, variant=variant
    )
    container_id = _start_variant_worker(env, override, variant)
    try:
        variant_dir = _run_eval(
            env, namespace=namespace, dataset_root=dataset_root, artifact_root=artifact_root
        )
        _patch_manifest_provenance(
            variant_dir, alembic_revision=alembic_revision, ragflow_image=ragflow_image
        )
        validate_trial_coverage(variant_dir)
        _write_live_ablation_result(
            baseline_dir=baseline_dir,
            variant_dir=variant_dir,
            dataset_root=dataset_root,
            variant=variant,
        )
        return variant_dir
    finally:
        _stop_variant_worker(env, container_id)


def _replay_report(
    env: Mapping[str, str], *, artifact_dir: Path, dataset_root: Path, evidence_dir: Path
) -> None:
    canonical = evidence_dir / "canonical-report"
    replayed = evidence_dir / "replayed-report"
    canonical.mkdir(parents=True, exist_ok=True)
    replayed.mkdir(parents=True, exist_ok=True)
    for name in ("metrics.json", "report.json", "report.md"):
        shutil.copy2(artifact_dir / name, canonical / name)
        (artifact_dir / name).unlink()
    _score_and_report(env, artifact_dir=artifact_dir, dataset_root=dataset_root)
    for name in ("metrics.json", "report.json", "report.md"):
        shutil.copy2(artifact_dir / name, replayed / name)
    assert_replay_equal(canonical, replayed)


def _write_summary(path: Path, payload: Mapping[str, Any], env: Mapping[str, str]) -> None:
    text = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(redact(text, env), encoding="utf-8")


def _run_live_gate(args: argparse.Namespace) -> dict[str, Any]:
    env = validate_required_environment(os.environ)
    dataset_root = args.dataset_root.resolve()
    artifact_root = args.artifact_root.resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path(args.evidence_dir).resolve() if args.evidence_dir else Path(
        tempfile.mkdtemp(prefix="ws8-task8-live-", dir="/tmp")
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)

    b7 = verify_b7_hashes(dataset_root)
    git = _git_preflight(env)
    ragflow_image = _ragflow_preflight(env)
    override, runtime_env = _write_compose_override(env)
    variant_dirs: dict[str, str] = {}
    live_state: dict[str, str] = {}

    def switch() -> None:
        _compose(
            runtime_env,
            override,
            "up",
            "-d",
            "--build",
            "--force-recreate",
            "postgres",
            "app-api",
            "app-worker",
        )

    def restore() -> None:
        try:
            _compose(env, None, "up", "-d", "--force-recreate", "postgres", "app-api", "app-worker")
        finally:
            override.unlink(missing_ok=True)

    def body() -> dict[str, Any]:
        alembic = _alembic_preflight(env)
        live_state["alembic_revision"] = alembic
        _fixture_prepare_and_verify(
            env,
            namespace=args.evaluation_namespace,
            dataset_root=dataset_root,
            artifact_root=artifact_root,
        )
        _runtime_preflight(runtime_env, override)
        baseline_dir = _run_eval(
            env,
            namespace=args.evaluation_namespace,
            dataset_root=dataset_root,
            artifact_root=artifact_root,
        )
        _patch_manifest_provenance(
            baseline_dir, alembic_revision=alembic, ragflow_image=ragflow_image
        )
        coverage = validate_trial_coverage(baseline_dir)
        initial_report = _score_and_report(
            env, artifact_dir=baseline_dir, dataset_root=dataset_root
        )

        for variant in LIVE_VARIANTS:
            variant_dir = _run_live_variant(
                runtime_env,
                override=override,
                namespace=args.evaluation_namespace,
                dataset_root=dataset_root,
                artifact_root=artifact_root,
                baseline_dir=baseline_dir,
                variant=variant,
                alembic_revision=alembic,
                ragflow_image=ragflow_image,
            )
            variant_dirs[variant] = str(variant_dir)
        for variant in SHADOW_VARIANTS:
            _run_shadow_ablation(
                env,
                artifact_dir=baseline_dir,
                dataset_root=dataset_root,
                variant=variant,
            )

        # Ruling: Task 6 reports intentionally include ablation artifacts.  Therefore the
        # canonical replay snapshot is refreshed after Task 8 creates all four ablations;
        # otherwise Plan steps 5 and 6 would compare different declared report inputs.
        final_report = _score_and_report(env, artifact_dir=baseline_dir, dataset_root=dataset_root)
        ablations = final_report.get("ablations")
        observed_variants = [
            item.get("variant") for item in ablations if isinstance(item, dict)
        ] if isinstance(ablations, list) else []
        expected_variants = [
            "no_exact_registry",
            "single_round_only",
            "pre_governance_shadow",
            "pre_guard_shadow",
        ]
        if observed_variants != expected_variants:
            raise GateError("final report does not contain exactly the four frozen ablations")
        _replay_report(
            env,
            artifact_dir=baseline_dir,
            dataset_root=dataset_root,
            evidence_dir=evidence_dir,
        )
        replay_report = _json(baseline_dir / "report.json")
        product_status = validate_report(replay_report)
        return {
            "pipeline_gate_status": "PASS",
            "product_evaluation_status": product_status,
            "baseline_artifact_dir": str(baseline_dir),
            "variant_artifact_dirs": variant_dirs,
            "coverage": coverage,
            "initial_product_status": (
                initial_report.get("product_status", {}).get("status")
                if isinstance(initial_report.get("product_status"), dict)
                else None
            ),
            "dirty_worktree": git["dirty_worktree"],
            "tracked_worktree_status": git["tracked_worktree_status"],
        }

    result: dict[str, Any]
    try:
        result = run_with_restore(switch, body, restore)
    except Exception as exc:
        result = {
            "pipeline_gate_status": "FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "dirty_worktree": git["dirty_worktree"],
            "tracked_worktree_status": git["tracked_worktree_status"],
        }
    result.update(
        {
            "branch": git["branch"],
            "git_head": git["head"],
            "alembic_revision": live_state.get("alembic_revision"),
            "ragflow_image": ragflow_image,
            "b7_checked_files": len(b7),
            "evidence_dir": str(evidence_dir),
        }
    )
    _write_summary(evidence_dir / "summary.json", result, env)
    return result


async def _variant_worker(variant: str) -> None:
    import httpx

    from project_agent.config import load_settings
    from project_agent.evaluation.variants import build_controlled_variant_qa_executor
    from project_agent.infrastructure.db.session import create_engine, create_session_factory
    from project_agent.infrastructure.llm.adapter import (
        OpenAICompatibleStructuredLLMAdapter,
        StructuredLLMRetryPolicy,
    )
    from project_agent.infrastructure.object_store.local import LocalFileObjectStoreAdapter
    from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
    from project_agent.infrastructure.ragflow.client import RagflowRetryPolicy
    from project_agent.runtime.issue import ProductionIssueRunGraphExecutor
    from project_agent.runtime.run_graph import build_production_run_graph_executor
    from project_agent.runtime.worker import build_worker_runtime

    settings = load_settings()

    class ControlledExecutor:
        def __init__(self, saver: object) -> None:
            self._engine = create_engine(settings.database_url)
            sessions = create_session_factory(self._engine)
            self._ragflow_http = httpx.AsyncClient(
                base_url=settings.ragflow_base_url,
                timeout=settings.ragflow_request_timeout_seconds,
            )
            self._llm_http = httpx.AsyncClient(
                base_url=settings.llm_base_url,
                timeout=settings.llm_request_timeout_seconds,
            )
            knowledge = RagflowAdapter.from_http_client(
                self._ragflow_http,
                api_key=settings.ragflow_api_key.get_secret_value(),
                object_store=LocalFileObjectStoreAdapter(settings.local_storage_root),
                embedding_model=settings.ragflow_embedding_model,
                chunk_method=settings.ragflow_chunk_method,
                retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
            )
            llm = OpenAICompatibleStructuredLLMAdapter(
                self._llm_http,
                api_key=settings.llm_api_key.get_secret_value(),
                retry_policy=StructuredLLMRetryPolicy(max_attempts=settings.llm_max_attempts),
                request_timeout_seconds=settings.llm_request_timeout_seconds,
            )
            qa = build_controlled_variant_qa_executor(
                variant=variant,
                settings=settings,
                session_factory=sessions,
                saver=saver,
                knowledge=knowledge,
                llm=llm,
                llm_usage=llm,
            )
            issue = ProductionIssueRunGraphExecutor(settings, saver, knowledge=knowledge)
            self._delegate = build_production_run_graph_executor(qa=qa, issue=issue)

        async def execute(self, run: Any) -> Any:
            return await self._delegate.execute(run)

        async def resume(self, run: Any, resume_payload: dict[str, object]) -> Any:
            return await self._delegate.resume(run, resume_payload)

        async def aclose(self) -> None:
            await self._delegate.aclose()
            await self._ragflow_http.aclose()
            await self._llm_http.aclose()
            await self._engine.dispose()

    # build_worker_runtime creates the durable queue/checkpointer and uses this explicit
    # evaluation-owned executor factory; default production worker behavior is untouched.
    async with build_worker_runtime(
        settings, graph_executor_factory=lambda saver: ControlledExecutor(saver)
    ) as runtime:
        loop = asyncio.get_running_loop()
        installed: list[signal.Signals] = []
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signum, runtime.worker.stop)
                installed.append(signum)
            await runtime.worker.serve_forever()
        finally:
            for signum in installed:
                loop.remove_signal_handler(signum)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WS8 real live evaluation gate")
    parser.add_argument("--dataset", choices=("v0",), default="v0")
    parser.add_argument("--dataset-root", type=Path, default=Path("evaluation/datasets/v0"))
    parser.add_argument("--artifact-root", type=Path, default=Path("evaluation/artifacts"))
    parser.add_argument("--evaluation-namespace", default="ws8-v0-live-gate")
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--variant-worker", choices=LIVE_VARIANTS, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.variant_worker:
        asyncio.run(_variant_worker(args.variant_worker))
        return 0
    if args.dataset != "v0":
        raise GateError("only frozen v0 is supported")
    try:
        summary = _run_live_gate(args)
    except Exception as exc:
        # No secret-bearing exception body is emitted before an environment is validated.
        print(f"WS8 evaluation gate FAILED: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return gate_exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
