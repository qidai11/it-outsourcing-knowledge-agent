from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_ROOT = REPO_ROOT / "artifacts" / "ws7-live"
REQUIRED_GATE_NAMES = (
    "postgres_runtime",
    "ragflow",
    "structured_llm",
    "qa_provider_runtime",
    "compose_qa",
    "compose_issue",
)
_REQUIRED_ENV = (
    "DATABASE_URL",
    "RAGFLOW_BASE_URL",
    "RAGFLOW_API_KEY",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL_ALIAS",
    "JWT_HS256_SECRET",
)
_SECRET_ENV = (
    "RAGFLOW_API_KEY",
    "LLM_API_KEY",
    "JWT_HS256_SECRET",
    "DATABASE_URL",
)
_SKIP_RE = re.compile(r"(?<!\w)(\d+)\s+skipped\b", re.IGNORECASE)
_BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"']+")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_DSN_RE = re.compile(
    r"(?P<scheme>postgres(?:ql)?(?:\+asyncpg)?://)(?P<user>[^:@/\s]+):(?P<password>[^@/\s]+)@",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Gate:
    name: str
    command: tuple[str, ...]
    env: dict[str, str]


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    status: Literal["PASS", "FAILED", "INCOMPLETE"]
    returncode: int
    skipped: int
    log_file: str


class PreflightError(RuntimeError):
    """Raised when a required WS7 live prerequisite is missing."""


def _run_process(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        tuple(command),
        cwd=cwd,
        env=dict(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _probe_url(url: str, *, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(response.status), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - exercised by live preflight
        raise PreflightError(f"URL probe failed for {url}: {type(exc).__name__}") from exc


def redact(text: str, env: Mapping[str, str]) -> str:
    sanitized = text
    values: set[str] = set()
    for name in _SECRET_ENV:
        value = env.get(name, "").strip()
        if value:
            values.add(value)
    for value in sorted(values, key=len, reverse=True):
        sanitized = sanitized.replace(value, "[REDACTED]")
    sanitized = _BEARER_RE.sub(r"\1[REDACTED]", sanitized)
    sanitized = _JWT_RE.sub("[REDACTED-JWT]", sanitized)
    sanitized = _DSN_RE.sub(r"\g<scheme>\g<user>:[REDACTED]@", sanitized)
    return sanitized


def _skip_count(output: str) -> int:
    matches = [int(item) for item in _SKIP_RE.findall(output)]
    return max(matches, default=0)


def run_gate(
    gate: Gate,
    *,
    evidence_dir: Path,
    base_env: Mapping[str, str],
) -> GateResult:
    env = dict(base_env)
    env.update(gate.env)
    completed = _run_process(gate.command, env=env)
    raw = completed.stdout or ""
    skipped = _skip_count(raw)
    if completed.returncode != 0:
        status: Literal["PASS", "FAILED", "INCOMPLETE"] = "FAILED"
    elif skipped:
        status = "INCOMPLETE"
    else:
        status = "PASS"

    log_path = evidence_dir / f"{gate.name}.log"
    header = (
        f"gate={gate.name}\n"
        f"command={json.dumps(list(gate.command))}\n"
        f"returncode={completed.returncode}\n"
        f"skipped={skipped}\n"
        f"status={status}\n\n"
    )
    log_path.write_text(redact(header + raw, env), encoding="utf-8")
    return GateResult(
        name=gate.name,
        status=status,
        returncode=completed.returncode,
        skipped=skipped,
        log_file=log_path.name,
    )


def write_summary(
    path: Path,
    results: Sequence[GateResult],
    metadata: Mapping[str, object],
) -> None:
    payload = dict(metadata)
    payload["gates"] = [asdict(result) for result in results]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _checked(command: Sequence[str], env: Mapping[str, str], *, label: str) -> str:
    result = _run_process(command, env=env)
    output = result.stdout or ""
    if result.returncode != 0:
        raise PreflightError(f"{label} failed with exit code {result.returncode}")
    return output.strip()


def _compose_services(env: Mapping[str, str]) -> dict[str, dict[str, object]]:
    output = _checked(
        ("docker", "compose", "ps", "--format", "json"),
        env,
        label="docker compose ps",
    )
    if not output:
        return {}
    try:
        parsed = json.loads(output)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    services: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        service = str(row.get("Service") or row.get("service") or "")
        if service:
            services[service] = row
    return services


def _service_is_healthy(row: Mapping[str, object]) -> bool:
    state = str(row.get("State") or row.get("state") or "").lower()
    health = str(row.get("Health") or row.get("health") or "").lower()
    status = str(row.get("Status") or row.get("status") or "").lower()
    return state == "running" and (health == "healthy" or "(healthy)" in status)


def _required_preflight(env: Mapping[str, str]) -> dict[str, object]:
    missing = [name for name in _REQUIRED_ENV if not env.get(name, "").strip()]
    if missing:
        raise PreflightError("missing required environment: " + ", ".join(missing))

    branch = _checked(("git", "branch", "--show-current"), env, label="git branch")
    if branch != "feat/ws7":
        raise PreflightError(f"required branch is feat/ws7, got {branch or '<detached>'}")
    head = _checked(("git", "rev-parse", "HEAD"), env, label="git HEAD")
    git_status = _checked(("git", "status", "--short"), env, label="git status")

    _checked(("docker", "info"), env, label="Docker daemon")
    _checked(("docker", "compose", "version"), env, label="docker compose")
    services = _compose_services(env)
    for name in ("postgres", "app-api", "app-worker"):
        row = services.get(name)
        if row is None or not _service_is_healthy(row):
            raise PreflightError(f"compose service {name} must be running and healthy")

    ragflow = env["RAGFLOW_BASE_URL"].rstrip("/") + "/api/v1/system/healthz"
    api_base = env.get("WS7_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    probes = (
        ("RAGFlow", ragflow),
        ("API /live", api_base + "/live"),
        ("API /ready", api_base + "/ready"),
        ("Worker metrics", "http://127.0.0.1:9101/metrics"),
    )
    for label, url in probes:
        status, _body = _probe_url(url)
        if status != 200:
            raise PreflightError(f"{label} returned HTTP {status}")

    return {
        "branch": branch,
        "head": head,
        "git_status": git_status,
    }


def _required_gates() -> tuple[Gate, ...]:
    required_env = {
        "RUN_POSTGRES_INTEGRATION": "1",
        "RUN_RAGFLOW_INTEGRATION": "1",
        "RUN_LLM_INTEGRATION": "1",
        "RUN_WS7_COMPOSE_LIVE": "1",
        "WS7_API_BASE_URL": "http://127.0.0.1:8000",
        # Host-side provider/runtime gates create their own Worker instances.
        # Keep their metrics listener disabled while Compose Worker is isolated.
        "WORKER_METRICS_ENABLED": "false",
        "RETENTION_SWEEP_ENABLED": "false",
    }
    return (
        Gate(
            "postgres_runtime",
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "-rs",
                "tests/integration/db/test_postgres_schema.py",
                "tests/integration/agent/test_postgres_checkpointer.py",
                "tests/integration/api/test_run_api_postgres.py",
                "tests/integration/issues/test_issue_run_runtime_postgres.py",
            ),
            dict(required_env),
        ),
        Gate(
            "ragflow",
            (
                "bash",
                "-lc",
                "uv run python scripts/check_ragflow_version.py && "
                "uv run pytest -q -rs tests/integration/ragflow/test_project_isolation.py",
            ),
            dict(required_env),
        ),
        Gate(
            "structured_llm",
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "-rs",
                "tests/integration/llm/test_structured_provider.py",
            ),
            dict(required_env),
        ),
        Gate(
            "qa_provider_runtime",
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "-rs",
                "tests/integration/workers/test_qa_worker_live.py",
            ),
            dict(required_env),
        ),
        Gate(
            "compose_qa",
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "-rs",
                "tests/live/test_ws7_compose_qa.py",
            ),
            dict(required_env),
        ),
        Gate(
            "compose_issue",
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "-rs",
                "tests/live/test_ws7_compose_issue.py",
            ),
            dict(required_env),
        ),
    )


def _isolate_compose_worker(env: Mapping[str, str]) -> None:
    for command in (
        ("docker", "compose", "stop", "app-worker"),
        ("docker", "compose", "rm", "-sf", "app-worker"),
    ):
        result = _run_process(command, env=env)
        if result.returncode != 0:
            raise PreflightError("failed to isolate Compose Worker for host runtime gates")


def _restore_compose_worker(env: Mapping[str, str]) -> None:
    result = _run_process(
        ("docker", "compose", "up", "-d", "--force-recreate", "app-worker"),
        env=env,
    )
    if result.returncode != 0:
        raise PreflightError("failed to restore Compose Worker")
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        try:
            status, _body = _probe_url("http://127.0.0.1:9101/metrics", timeout=3.0)
        except PreflightError:
            status = 0
        if status == 200:
            services = _compose_services(env)
            row = services.get("app-worker")
            if row is not None and _service_is_healthy(row):
                return
        time.sleep(1.0)
    raise PreflightError("restored Compose Worker did not become healthy")


def _new_evidence_dir(root: Path) -> Path:
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    path = root / run_id
    path.mkdir(parents=True, exist_ok=False)
    return path


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS7 mandatory live acceptance gates")
    parser.add_argument("--required", action="store_true", help="require every WS7 live gate")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=DEFAULT_EVIDENCE_ROOT,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.required:
        print("WS7 runner requires --required", file=sys.stderr)
        return 2

    evidence_dir = _new_evidence_dir(args.evidence_root)
    summary_path = evidence_dir / "summary.json"
    base_env = dict(os.environ)
    metadata: dict[str, object] = {
        "created_at": datetime.now(UTC).isoformat(),
        "required": True,
        "status": "INCOMPLETE",
    }
    results: list[GateResult] = []
    worker_isolated = False
    worker_restored = False

    try:
        metadata.update(_required_preflight(base_env))
        _isolate_compose_worker(base_env)
        worker_isolated = True

        for gate in _required_gates():
            if gate.name == "compose_qa" and worker_isolated and not worker_restored:
                _restore_compose_worker(base_env)
                worker_restored = True
            result = run_gate(gate, evidence_dir=evidence_dir, base_env=base_env)
            results.append(result)
            print(f"{result.name} {result.status}")
            if result.status != "PASS":
                metadata["status"] = result.status
                write_summary(summary_path, results, metadata)
                print(f"WS7 {result.status}")
                return 1

        metadata["status"] = "PASS"
        write_summary(summary_path, results, metadata)
        print("WS7 PASS")
        return 0
    except PreflightError as exc:
        metadata["status"] = "INCOMPLETE"
        metadata["preflight_error"] = redact(str(exc), base_env)
        write_summary(summary_path, results, metadata)
        print(f"WS7 INCOMPLETE: {metadata['preflight_error']}", file=sys.stderr)
        return 1
    finally:
        if worker_isolated and not worker_restored:
            try:
                _restore_compose_worker(base_env)
            except PreflightError as exc:
                if summary_path.exists():
                    payload = json.loads(summary_path.read_text(encoding="utf-8"))
                else:
                    payload = metadata | {"gates": [asdict(item) for item in results]}
                payload["status"] = "FAILED"
                payload["worker_restore_error"] = redact(str(exc), base_env)
                summary_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )


if __name__ == "__main__":
    raise SystemExit(main())
