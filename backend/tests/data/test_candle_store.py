from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fxbot.data.candle_store import CandleStore, find_gaps
from fxbot.domain.enums import Granularity
from fxbot.domain.errors import DataIntegrityError
from tests.data.conftest import bar, dataset, hourly

MONDAY = datetime(2024, 3, 4, tzinfo=UTC)


async def test_upsert_is_idempotent_and_replaces_values(store: CandleStore) -> None:
    candles = hourly(MONDAY, 48)

    assert await store.upsert(candles, dataset=dataset()) == 48
    assert await store.upsert(candles, dataset=dataset()) == 48
    stored = await store.get_candles("EUR_USD", Granularity.H1)
    assert stored == candles

    corrected = bar(MONDAY, mid="1.20000")
    await store.upsert([corrected], dataset=dataset())
    assert (
        await store.get_candles("EUR_USD", Granularity.H1, MONDAY, MONDAY + timedelta(hours=1))
    ) == [corrected]


async def test_range_query_is_ordered_and_bounded(store: CandleStore) -> None:
    candles = hourly(MONDAY, 24)
    shuffled = candles[:]
    random.Random(1).shuffle(shuffled)
    await store.upsert(shuffled, dataset=dataset())

    window = await store.get_candles(
        "EUR_USD", Granularity.H1, MONDAY + timedelta(hours=5), MONDAY + timedelta(hours=9)
    )

    assert [c.time.hour for c in window] == [5, 6, 7, 8]
    assert await store.latest_time("EUR_USD", Granularity.H1) == MONDAY + timedelta(hours=23)
    assert await store.get_candles("GBP_USD", Granularity.H1) == []
    assert await store.latest_time("GBP_USD", Granularity.H1) is None


async def test_duplicates_and_incomplete_candles_are_refused(store: CandleStore) -> None:
    with pytest.raises(DataIntegrityError, match="duplicate"):
        await store.upsert([bar(MONDAY), bar(MONDAY, mid="1.2")], dataset=dataset())
    with pytest.raises(DataIntegrityError, match="incomplete"):
        await store.upsert([bar(MONDAY, complete=False)], dataset=dataset())
    assert await store.upsert([], dataset=dataset()) == 0


async def test_gaps_skip_weekends_and_are_never_filled(store: CandleStore) -> None:
    friday = datetime(2024, 3, 8, tzinfo=UTC)
    candles = hourly(friday, 24 * 4)  # Friday to Monday, weekend hours absent
    missing = friday + timedelta(days=3, hours=5)  # a Monday hour
    await store.upsert([c for c in candles if c.time != missing], dataset=dataset())

    gaps = await store.find_gaps("EUR_USD", Granularity.H1)

    (gap,) = gaps
    assert gap.missing_bars == 1
    assert gap.after == missing - timedelta(hours=1) and gap.before == missing + timedelta(hours=1)
    stored = await store.get_candles("EUR_USD", Granularity.H1)
    assert missing not in {c.time for c in stored}
    assert await store.find_gaps("GBP_USD", Granularity.H1) == []


def test_holidays_are_reported_as_gaps() -> None:
    christmas_eve = datetime(2024, 12, 24, 21, tzinfo=UTC)
    after = datetime(2024, 12, 25, 23, tzinfo=UTC)

    (gap,) = find_gaps([christmas_eve, after], Granularity.H1)

    assert gap.missing_bars == 25


async def test_provenance_is_stored(store: CandleStore) -> None:
    source = dataset(smoothed=True, tz_origin="UTC-05", licence_note="local use only")
    await store.upsert(hourly(MONDAY, 3), dataset=source)

    (stored,) = await store.datasets("EUR_USD", Granularity.H1)

    assert stored == source


async def test_datasets_never_overwrite_each_other(store: CandleStore) -> None:
    await store.upsert([bar(MONDAY, mid="1.10000")], dataset=dataset("a"))
    await store.upsert([bar(MONDAY, mid="1.20000")], dataset=dataset("b"))

    with pytest.raises(DataIntegrityError, match="name the one to use"):
        await store.get_candles("EUR_USD", Granularity.H1)
    (a,) = await store.get_candles("EUR_USD", Granularity.H1, dataset="a")
    (b,) = await store.get_candles("EUR_USD", Granularity.H1, dataset="b")
    assert (a.bid.open, b.bid.open) == (Decimal("1.10000"), Decimal("1.20000"))
    assert await store.get_candles("EUR_USD", Granularity.H1, dataset="missing") == []
    assert await store.latest_time("EUR_USD", Granularity.H1, dataset="b") == MONDAY
    assert len(await store.find_gaps("EUR_USD", Granularity.H1, dataset="a")) == 0
    assert repr(store) == "CandleStore()"
