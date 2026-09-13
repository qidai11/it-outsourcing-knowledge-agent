from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TransactionCommitPort(Protocol):
    async def commit(self) -> None: ...
