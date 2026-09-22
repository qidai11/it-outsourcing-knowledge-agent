from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

import project_agent.cli.worker as module


class FakeLoop:
    def __init__(self) -> None:
        self.handlers: dict[object, Any] = {}
        self.removed: list[object] = []

    def add_signal_handler(self, signum: object, callback: Any) -> None:
        self.handlers[signum] = callback

    def remove_signal_handler(self, signum: object) -> bool:
        self.removed.append(signum)
        self.handlers.pop(signum, None)
        return True


class FakeWorker:
    def __init__(self) -> None:
        self.served = False
        self.stop_calls = 0
        self.on_serve: Any = None

    async def serve_forever(self) -> None:
        self.served = True
        if self.on_serve is not None:
            self.on_serve()

    def stop(self) -> None:
        self.stop_calls += 1


@pytest.mark.asyncio
async def test_run_worker_loads_settings_enters_runtime_and_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = object()
    worker = FakeWorker()
    loop = FakeLoop()
    events: list[object] = []

    @asynccontextmanager
    async def fake_runtime(settings: object):
        events.append(("enter", settings))
        try:
            yield SimpleNamespace(worker=worker)
        finally:
            events.append(("exit", settings))

    monkeypatch.setattr(module, "load_settings", lambda: configured)
    monkeypatch.setattr(module, "build_worker_runtime", fake_runtime)
    monkeypatch.setattr(module.asyncio, "get_running_loop", lambda: loop)

    await module.run_worker()

    assert worker.served is True
    assert events == [("enter", configured), ("exit", configured)]


@pytest.mark.asyncio
async def test_run_worker_installs_signal_handlers_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = object()
    worker = FakeWorker()
    loop = FakeLoop()
    exited = False

    def invoke_sigterm() -> None:
        callback = loop.handlers[module.signal.SIGTERM]
        callback()

    worker.on_serve = invoke_sigterm

    @asynccontextmanager
    async def fake_runtime(settings: object):
        nonlocal exited
        assert settings is configured
        try:
            yield SimpleNamespace(worker=worker)
        finally:
            exited = True

    monkeypatch.setattr(module, "load_settings", lambda: configured)
    monkeypatch.setattr(module, "build_worker_runtime", fake_runtime)
    monkeypatch.setattr(module.asyncio, "get_running_loop", lambda: loop)

    await module.run_worker()

    assert worker.stop_calls == 1
    assert set(loop.removed) == {module.signal.SIGINT, module.signal.SIGTERM}
    assert loop.handlers == {}
    assert exited is True


def test_main_returns_zero_after_normal_worker_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_run_worker() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(module, "run_worker", fake_run_worker)

    assert module.main() == 0
    assert called is True


def test_main_does_not_swallow_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_worker() -> None:
        raise RuntimeError("startup failed")

    monkeypatch.setattr(module, "run_worker", fake_run_worker)

    with pytest.raises(RuntimeError, match="startup failed"):
        module.main()
