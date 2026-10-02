from __future__ import annotations

import random

import pytest

from fxbot.brokers.backoff import Backoff, TokenBucket
from fxbot.brokers.symbols import SymbolMap


def test_symbol_maps() -> None:
    mt5 = SymbolMap.concatenated(["EUR_USD", "USD_JPY"], suffix="m")
    oanda = SymbolMap.identity(["EUR_USD"])

    assert mt5.to_broker("EUR_USD") == "EURUSDm"
    assert mt5.to_canonical("USDJPYm") == "USD_JPY"
    assert oanda.to_broker("EUR_USD") == "EUR_USD"
    assert "EUR_USD" in mt5 and "GBP_USD" not in mt5
    assert "EURUSDm" in repr(mt5)
    with pytest.raises(KeyError, match="no broker symbol"):
        mt5.to_broker("GBP_USD")
    with pytest.raises(KeyError, match="not mapped"):
        mt5.to_canonical("GBPUSDm")
    with pytest.raises(ValueError, match="canonical"):
        SymbolMap({"EURUSD": "EURUSD"})
    with pytest.raises(ValueError, match="mapped twice"):
        SymbolMap({"EUR_USD": "X", "GBP_USD": "X"})


def test_backoff_is_capped_and_jittered() -> None:
    backoff = Backoff(initial=1.0, maximum=30.0)
    rng = random.Random(0)

    delays = [backoff.delay(n, rng) for n in range(8)]

    for n, delay in enumerate(delays):
        nominal = min(30.0, 2.0**n)
        assert nominal / 2 <= delay <= nominal


async def test_token_bucket_paces_requests() -> None:
    now = [0.0]
    waits: list[float] = []

    async def sleep(delay: float) -> None:
        waits.append(delay)
        now[0] += delay

    bucket = TokenBucket(2.0, burst=2, monotonic=lambda: now[0], sleep=sleep)
    for _ in range(4):
        await bucket.acquire()

    assert waits == [0.5, 0.5]
    with pytest.raises(ValueError):
        TokenBucket(0)
