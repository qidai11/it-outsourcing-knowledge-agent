import asyncio
import io
import json
from contextlib import redirect_stdout

import pytest

from project_agent.observability.logging import (
    bind_log_context,
    clear_log_context,
    configure_structured_logging,
    elapsed_ms,
    get_logger,
)


def test_structured_log_has_timestamp_level_event_and_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_structured_logging(log_level="INFO")
    clear_log_context()
    bind_log_context(service="api", run_id="run-safe")
    get_logger().info("run_started", outcome="running")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "run_started"
    assert payload["level"] == "info"
    assert payload["service"] == "api"
    assert payload["run_id"] == "run-safe"
    assert payload["outcome"] == "running"
    assert payload["timestamp"].endswith("Z") or "+00:00" in payload["timestamp"]


async def _capture_context(value: str) -> str:
    clear_log_context()
    bind_log_context(run_id=value)
    await asyncio.sleep(0)
    from structlog.contextvars import get_contextvars

    return str(get_contextvars()["run_id"])


@pytest.mark.asyncio
async def test_concurrent_contexts_do_not_leak() -> None:
    left, right = await asyncio.gather(
        _capture_context("run-left"),
        _capture_context("run-right"),
    )
    assert {left, right} == {"run-left", "run-right"}


def test_clear_log_context_removes_bound_fields() -> None:
    from structlog.contextvars import get_contextvars

    clear_log_context()
    bind_log_context(run_id="run-safe")
    assert get_contextvars()["run_id"] == "run-safe"

    clear_log_context()
    assert "run_id" not in get_contextvars()


def test_elapsed_ms_uses_monotonic_nanoseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "project_agent.observability.logging.time.perf_counter_ns",
        lambda: 5_500_000,
    )
    assert elapsed_ms(500_000) == 5.0


def test_configure_structured_logging_can_be_called_repeatedly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_structured_logging(log_level="INFO")
    configure_structured_logging(log_level="INFO")
    clear_log_context()
    get_logger().info("configured_twice")

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "configured_twice"


def test_configure_structured_logging_does_not_capture_transient_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    transient_stdout = io.StringIO()
    with redirect_stdout(transient_stdout):
        configure_structured_logging(log_level="INFO")
    transient_stdout.close()

    clear_log_context()
    get_logger().info("after_transient_stdout")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "after_transient_stdout"
