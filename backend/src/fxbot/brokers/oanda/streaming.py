"""OANDA pricing and transaction streams (newline-delimited JSON over a long-lived GET).

- Watchdog: if no line (data or heartbeat) arrives within ``stale_after`` seconds the stream
  raises ``FeedStaleError``. The caller pauses entries and iterates again, which reconnects.
- Disconnects, 5xx and 429 reconnect with capped exponential backoff and jitter (never faster
  than ``backoff.initial``). 401/403 and other 4xx are raised: retrying would not help.
- Malformed lines, unknown message types and quotes with an empty book are logged and skipped.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from fxbot.brokers.backoff import Backoff, Sleep
from fxbot.brokers.oanda.client import OandaClient
from fxbot.brokers.oanda.wire import parse_price, parse_time, parse_transaction
from fxbot.domain.errors import (
    BrokerRejectedError,
    BrokerUnavailableError,
    DataIntegrityError,
    FeedStaleError,
    RateLimitedError,
)
from fxbot.domain.models import Price, Transaction
from fxbot.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StreamPolicy:
    stale_after: float = 10.0
    backoff: Backoff = field(default_factory=lambda: Backoff(initial=1.0, maximum=30.0))
    max_reconnects: int | None = None  # None: keep trying; the watchdog still reports staleness


class _NdjsonStream:
    """Reconnecting NDJSON reader with a heartbeat watchdog."""

    def __init__(
        self,
        name: str,
        opener: Callable[[], AbstractAsyncContextManager[httpx.Response]],
        policy: StreamPolicy,
        sleep: Sleep,
        rng: random.Random,
    ) -> None:
        self._name = name
        self._opener = opener
        self._policy = policy
        self._sleep = sleep
        self._rng = rng
        self.last_heartbeat: datetime | None = None
        self.reconnects = 0

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        failures = 0
        while True:
            try:
                async with self._opener() as response:
                    async for message in self._read(response):
                        failures = 0
                        yield message
                log.info("stream closed by server; reconnecting", stream=self._name)
            except BrokerRejectedError:
                raise  # auth or bad request: reconnecting would not help
            except BrokerUnavailableError as exc:
                log.warning("stream interrupted; reconnecting", stream=self._name, error=str(exc))
                retry_after = exc.retry_after if isinstance(exc, RateLimitedError) else None
            else:
                retry_after = None
            failures += 1
            self.reconnects += 1
            limit = self._policy.max_reconnects
            if limit is not None and failures > limit:
                raise BrokerUnavailableError(
                    f"{self._name}: gave up after {limit} reconnect attempts", endpoint=self._name
                )
            delay = self._policy.backoff.delay(failures - 1, self._rng)
            await self._sleep(max(delay, retry_after or 0.0))

    async def _read(self, response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        lines = response.aiter_lines().__aiter__()
        while True:
            try:
                async with asyncio.timeout(self._policy.stale_after):
                    line = await anext(lines)
            except TimeoutError:
                raise FeedStaleError(
                    f"{self._name}: nothing received for {self._policy.stale_after:g}s"
                ) from None
            except StopAsyncIteration:
                return
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                log.warning("skipping malformed stream line", stream=self._name)
                continue
            if not isinstance(message, dict):
                log.warning("skipping non-object stream line", stream=self._name)
                continue
            if message.get("type") == "HEARTBEAT":
                self._on_heartbeat(message)
                continue
            yield message

    def _on_heartbeat(self, message: dict[str, Any]) -> None:
        try:
            self.last_heartbeat = parse_time(message.get("time"))
        except DataIntegrityError:
            log.warning("heartbeat with an invalid time", stream=self._name)


class OandaPriceStream:
    """Live quotes for a set of instruments, from one stream connection."""

    def __init__(
        self,
        client: OandaClient,
        instruments: Sequence[str],
        *,
        policy: StreamPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        names = tuple(instruments)
        self._stream = _NdjsonStream(
            "pricing_stream",
            lambda: client.pricing_stream(names),
            policy or StreamPolicy(),
            sleep,
            rng or random.Random(),  # noqa: S311 - backoff jitter, not cryptography
        )

    @property
    def last_heartbeat(self) -> datetime | None:
        return self._stream.last_heartbeat

    @property
    def reconnects(self) -> int:
        return self._stream.reconnects

    async def prices(self) -> AsyncIterator[Price]:
        async for message in self._stream.messages():
            kind = message.get("type", "PRICE")  # the official SDK treats a missing type as PRICE
            if kind != "PRICE":
                log.debug("ignoring stream message", kind=str(kind)[:32])
                continue
            try:
                price = parse_price(message)
            except DataIntegrityError as exc:
                log.warning("skipping invalid price", error=str(exc))
                continue
            if price is None:
                log.info("skipping quote with an empty book", instrument=message.get("instrument"))
                continue
            yield price

    def __repr__(self) -> str:
        return "OandaPriceStream()"


class OandaTransactionStream:
    """Account transactions as they happen (fills, SL/TP closes, financing, margin calls)."""

    def __init__(
        self,
        client: OandaClient,
        *,
        policy: StreamPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._client = client
        self._stream = _NdjsonStream(
            "transaction_stream",
            client.transaction_stream,
            policy or StreamPolicy(),
            sleep,
            rng or random.Random(),  # noqa: S311 - backoff jitter, not cryptography
        )

    @property
    def last_heartbeat(self) -> datetime | None:
        return self._stream.last_heartbeat

    async def transactions(self) -> AsyncIterator[Transaction]:
        async for message in self._stream.messages():
            self._client.check_account_fields(message, "transaction_stream")
            try:
                transaction = parse_transaction(message)
            except DataIntegrityError as exc:
                log.warning("skipping invalid transaction", error=str(exc))
                continue
            yield transaction

    def __repr__(self) -> str:
        return "OandaTransactionStream()"
