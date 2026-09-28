"""Простой TTL-кэш метаданных видео (по video_id)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class _Entry:
    value: dict
    expires_at: float


class MetadataCache:
    """Мини-кэш: dict + TTL, очистка просроченных при записи."""

    def __init__(self, ttl_sec: int) -> None:
        self._ttl = ttl_sec
        self._data: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self.hits = 0
        self.misses = 0

    async def get(self, video_id: str) -> dict | None:
        async with self._lock:
            entry = self._data.get(video_id)
            if entry is None:
                self.misses += 1
                return None
            if time.monotonic() >= entry.expires_at:
                del self._data[video_id]
                self.misses += 1
                return None
            self.hits += 1
            return entry.value

    async def put(self, video_id: str, value: dict) -> None:
        async with self._lock:
            # Периодическая чистка просроченных, чтобы кэш не пух.
            now = time.monotonic()
            if len(self._data) > 64:
                expired = [k for k, v in self._data.items() if now >= v.expires_at]
                for key in expired:
                    del self._data[key]
            self._data[video_id] = _Entry(value=value, expires_at=now + self._ttl)


__all__ = ["MetadataCache"]
