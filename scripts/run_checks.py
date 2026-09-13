from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence


COMMANDS: tuple[tuple[str, ...], ...] = (
    (sys.executable, "scripts/validate_task0.py"),
    ("uv", "run", "ruff", "check", "src", "tests"),
    ("uv", "run", "mypy", "src"),
    (
        "uv",
        "run",
        "pytest",
        "tests/unit",
        "tests/integration/api",
        "tests/integration/db",
        "tests/integration/identifiers",
        "tests/integration/jobs",
        "tests/integration/config",
        "tests/integration/auth",
        "tests/integration/agent",
        "tests/integration/evidence",
        "tests/integration/issues",
        "tests/contract",
        "tests/security",
        "tests/integration/ragflow",
        "tests/e2e",
        "tests/reliability",
        "-v",
    ),
)


def run(command: Sequence[str]) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, check=True, env=os.environ.copy())


def main() -> int:
    for command in COMMANDS:
        run(command)
    print(
        "All Task 0 through Task 13 quality gates passed for the enabled environments. "
        "Live PostgreSQL/RAGFlow checks require their opt-in flags."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
