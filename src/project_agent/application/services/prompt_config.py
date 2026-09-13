from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PromptConfigRecord:
    config_key: str
    content: str
    version: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class PromptSnapshot:
    config_key: str
    content: str
    version: int
    content_hash: str


class PromptConfigRepository(Protocol):
    async def latest_enabled(self, config_key: str) -> PromptConfigRecord: ...


class PromptConfigService:
    def __init__(
        self,
        repository: PromptConfigRepository,
        *,
        ttl_seconds: float = 30,
        clock=time.monotonic,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds cannot be negative")
        self._repository = repository
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[tuple[str, int], PromptSnapshot] = {}
        self._latest: dict[str, tuple[float, int]] = {}

    async def get_snapshot(self, config_key: str) -> PromptSnapshot:
        now = self._clock()
        latest = self._latest.get(config_key)
        if latest is not None and now - latest[0] <= self._ttl:
            cached = self._cache[(config_key, latest[1])]
            return cached
        record = await self._repository.latest_enabled(config_key)
        cache_key = (record.config_key, record.version)
        snapshot = self._cache.get(cache_key)
        if snapshot is None:
            snapshot = PromptSnapshot(
                config_key=record.config_key,
                content=record.content,
                version=record.version,
                content_hash=record.content_hash,
            )
            self._cache[cache_key] = snapshot
        self._latest[config_key] = (now, record.version)
        return snapshot

    def invalidate(self, config_key: str | None = None) -> None:
        if config_key is None:
            self._cache.clear()
            self._latest.clear()
        else:
            self._latest.pop(config_key, None)
            for key in [key for key in self._cache if key[0] == config_key]:
                self._cache.pop(key, None)
