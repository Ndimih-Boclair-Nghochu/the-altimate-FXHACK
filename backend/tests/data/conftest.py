from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fxbot.data.candle_store import CandleStore
from fxbot.domain.calendar import is_market_open
from fxbot.domain.enums import AskSource, Granularity
from fxbot.domain.models import OHLC, Candle, Dataset
from fxbot.persistence.db import Database


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'db' / 'candles.db').as_posix()}")
    await db.create_all()
    yield db
    await db.dispose()


@pytest.fixture
async def store(database: Database) -> CandleStore:
    return CandleStore(database)


def dataset(name: str = "test:eurusd", **overrides: object) -> Dataset:
    fields: dict[str, object] = {
        "name": name,
        "source": "test",
        "price_side": "BA",
        "ask_source": AskSource.QUOTED,
        "sha256": "0" * 64,
        "licence_note": "generated in tests",
    }
    return Dataset(**(fields | overrides))  # type: ignore[arg-type]


def bar(
    time: datetime,
    *,
    instrument: str = "EUR_USD",
    granularity: Granularity = Granularity.H1,
    mid: str = "1.10000",
    complete: bool = True,
) -> Candle:
    price = Decimal(mid)
    return Candle(
        instrument=instrument,
        granularity=granularity,
        time=time,
        bid=OHLC(
            open=price, high=price + Decimal("0.001"), low=price - Decimal("0.001"), close=price
        ),
        ask=OHLC(
            open=price + Decimal("0.0001"),
            high=price + Decimal("0.0011"),
            low=price - Decimal("0.0009"),
            close=price + Decimal("0.0001"),
        ),
        volume=5,
        complete=complete,
    )


def hourly(start: datetime, hours: int, **kwargs: object) -> list[Candle]:
    """Bars for every open-market hour in ``[start, start + hours)``."""
    times = [start + timedelta(hours=h) for h in range(hours)]
    return [bar(t, **kwargs) for t in times if is_market_open(t)]  # type: ignore[arg-type]
