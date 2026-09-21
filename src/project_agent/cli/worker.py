from __future__ import annotations

import asyncio
import signal

from project_agent.config import load_settings
from project_agent.runtime.worker import build_worker_runtime


async def run_worker() -> None:
    settings = load_settings()
    async with build_worker_runtime(settings) as runtime:
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


def main() -> int:
    asyncio.run(run_worker())
    return 0
