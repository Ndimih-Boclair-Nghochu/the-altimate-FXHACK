"""Retry pacing shared by broker adapters: capped exponential backoff and a token bucket."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Backoff:
    """Delay before attempt ``n + 1``: ``initial * 2**n`` capped at ``maximum``, with jitter.

    Jitter draws from ``[delay / 2, delay]`` so many clients never reconnect in lockstep, and
    the delay never drops below half the nominal value.
    """

    initial: float = 0.5
    maximum: float = 8.0

    def delay(self, attempt: int, rng: random.Random) -> float:
        nominal = min(self.maximum, self.initial * (2 ** max(0, attempt)))
        return rng.uniform(nominal / 2, nominal)


class TokenBucket:
    """Client-side request rate limit (far below the broker's own limit)."""

    def __init__(
        self,
        rate_per_second: float,
        *,
        burst: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._rate = rate_per_second
        self._capacity = burst if burst is not None else rate_per_second
        self._tokens = self._capacity
        self._monotonic = monotonic
        self._sleep = sleep
        self._updated = monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._monotonic()
                elapsed = max(0.0, now - self._updated)
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await self._sleep((1 - self._tokens) / self._rate)
