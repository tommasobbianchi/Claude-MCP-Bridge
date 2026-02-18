from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class RateLimiter:
    """Sliding-window rate limiter per tool name."""

    def __init__(self, max_per_minute: int = 10) -> None:
        self._max_per_minute = max_per_minute
        self._calls: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, tool_name: str) -> None:
        async with self._lock:
            now = time.monotonic()
            window = now - 60.0
            self._calls[tool_name] = [
                t for t in self._calls[tool_name] if t > window
            ]
            if len(self._calls[tool_name]) >= self._max_per_minute:
                raise RuntimeError(
                    f"Rate limit exceeded for {tool_name}: "
                    f"max {self._max_per_minute} requests/minute"
                )
            self._calls[tool_name].append(now)


class ConcurrencyLimiter:
    """Fail-fast concurrency limiter using asyncio.Semaphore."""

    def __init__(self, max_concurrent: int = 3) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max = max_concurrent

    async def acquire(self) -> None:
        if self._semaphore._value == 0:
            raise RuntimeError(
                f"Max concurrent claude_execute limit reached ({self._max})"
            )
        await self._semaphore.acquire()

    def release(self) -> None:
        self._semaphore.release()
