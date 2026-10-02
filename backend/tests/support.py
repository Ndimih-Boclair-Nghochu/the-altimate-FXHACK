"""Helpers shared by tests: fixtures on disk, fake sleeps, OANDA client wiring."""

from __future__ import annotations

import json
import random
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import respx
from pydantic import SecretStr

from fxbot.brokers.backoff import Backoff
from fxbot.brokers.hosts import OandaEnvironment, hosts_for
from fxbot.brokers.oanda.client import OandaClient, RetryPolicy
from fxbot.domain.clock import SimClock
from tests.fakes import FakeOandaCredentials

FIXTURES = Path(__file__).parent / "fixtures"
CREDENTIALS = FakeOandaCredentials()
PRACTICE = hosts_for(OandaEnvironment.PRACTICE)
ACCOUNT_PATH = f"/v3/accounts/{CREDENTIALS.account_id}"


def fixture_text(name: str) -> str:
    return (FIXTURES / "oanda" / name).read_text(encoding="utf-8")


def fixture(name: str) -> Any:
    return json.loads(fixture_text(name))


class RecordingSleep:
    """Stands in for ``asyncio.sleep``: records delays and advances a ``SimClock`` if given."""

    def __init__(self, clock: SimClock | None = None) -> None:
        self.calls: list[float] = []
        self._clock = clock

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)
        if self._clock is not None and delay > 0:
            self._clock.advance(timedelta(seconds=delay))


def practice_client(
    router: respx.Router,
    *,
    sleep: RecordingSleep | None = None,
    stream_transport: httpx.AsyncBaseTransport | None = None,
    attempts: int = 3,
) -> OandaClient:
    return OandaClient(
        environment=OandaEnvironment.PRACTICE,
        account_id=SecretStr(CREDENTIALS.account_id),
        api_token=SecretStr(CREDENTIALS.api_token),
        transport=httpx.MockTransport(router.async_handler),
        stream_transport=stream_transport,
        requests_per_second=10_000,
        retry=RetryPolicy(max_attempts=attempts, backoff=Backoff(initial=0.5, maximum=8.0)),
        sleep=sleep or RecordingSleep(),
        rng=random.Random(1),
    )
