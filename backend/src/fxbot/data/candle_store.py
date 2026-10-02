"""Candle store: validated, provenance-tracked bid/ask candles in the database."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from fxbot.domain.calendar import bar_close_time, ensure_utc, is_market_open
from fxbot.domain.clock import Clock, SystemClock
from fxbot.domain.enums import Granularity
from fxbot.domain.errors import DataIntegrityError
from fxbot.domain.models import Candle, Dataset
from fxbot.persistence.db import Database
from fxbot.persistence.repositories import CandleRepository, DatasetRepository


@dataclass(frozen=True, slots=True)
class Gap:
    """Missing bars between two stored bars, ignoring the weekend market closure."""

    after: datetime  # open time of the last bar before the gap
    before: datetime  # open time of the first bar after the gap
    missing_bars: int


def check_sequence(candles: Sequence[Candle]) -> None:
    """Refuse incomplete candles, duplicates and out-of-order times (per instrument/granularity)."""
    last: dict[tuple[str, Granularity], datetime] = {}
    for candle in candles:
        if not candle.complete:
            raise DataIntegrityError(f"incomplete {candle.instrument} candle; only closed bars")
        key = (candle.instrument, candle.granularity)
        previous = last.get(key)
        if previous is not None and candle.time <= previous:
            kind = "duplicate" if candle.time == previous else "out-of-order"
            raise DataIntegrityError(
                f"{kind} {candle.instrument} candle at {candle.time:%Y-%m-%d %H:%M}"
            )
        last[key] = candle.time


def find_gaps(times: Sequence[datetime], granularity: Granularity) -> list[Gap]:
    """Gaps in an ascending series of bar open times. Nothing is filled in.

    Bars that would open while the FX market is closed (Friday 17:00 to Sunday 17:00 New
    York) are not expected, so weekends are not gaps; holidays are reported.
    """
    gaps: list[Gap] = []
    for previous, current in pairwise(times):
        expected = bar_close_time(previous, granularity)
        missing = 0
        while expected < current:
            if is_market_open(expected):
                missing += 1
            expected = bar_close_time(expected, granularity)
        if missing:
            gaps.append(Gap(after=previous, before=current, missing_bars=missing))
    return gaps


class CandleStore:
    """Candles grouped by dataset. Reads name the dataset unless exactly one holds the series."""

    def __init__(self, database: Database, *, clock: Clock | None = None) -> None:
        self._candles = CandleRepository(database)
        self._datasets = DatasetRepository(database)
        self._clock = clock or SystemClock()

    def __repr__(self) -> str:
        return "CandleStore()"

    async def register_dataset(self, dataset: Dataset) -> int:
        return await self._datasets.upsert(dataset, now=self._clock.now())

    async def upsert(self, candles: Sequence[Candle], *, dataset: Dataset) -> int:
        """Store complete candles (idempotent: re-storing a candle replaces it)."""
        if not candles:
            return 0
        check_sequence(sorted(candles, key=lambda c: (c.instrument, c.granularity, c.time)))
        dataset_id = await self.register_dataset(dataset)
        return await self._candles.upsert(candles, dataset_id=dataset_id)

    async def _dataset_id(
        self, instrument: str, granularity: Granularity, dataset: str | None
    ) -> int | None:
        if dataset is not None:
            return await self._datasets.id_of(dataset)
        ids = await self._candles.dataset_ids(instrument, granularity)
        if len(ids) > 1:
            raise DataIntegrityError(
                f"{len(ids)} datasets hold {instrument} {granularity.value}; name the one to use"
            )
        return ids[0] if ids else None

    async def get_candles(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        dataset: str | None = None,
    ) -> list[Candle]:
        dataset_id = await self._dataset_id(instrument, granularity, dataset)
        if dataset_id is None:
            return []
        return await self._candles.range(
            dataset_id,
            instrument,
            granularity,
            ensure_utc(start) if start else None,
            ensure_utc(end) if end else None,
        )

    async def latest_time(
        self, instrument: str, granularity: Granularity, *, dataset: str | None = None
    ) -> datetime | None:
        dataset_id = await self._dataset_id(instrument, granularity, dataset)
        if dataset_id is None:
            return None
        return await self._candles.latest_time(dataset_id, instrument, granularity)

    async def find_gaps(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        dataset: str | None = None,
    ) -> list[Gap]:
        dataset_id = await self._dataset_id(instrument, granularity, dataset)
        if dataset_id is None:
            return []
        times = await self._candles.times(dataset_id, instrument, granularity, start, end)
        return find_gaps(times, granularity)

    async def datasets(self, instrument: str, granularity: Granularity) -> list[Dataset]:
        """Provenance of every dataset holding this series."""
        found = []
        for dataset_id in await self._candles.dataset_ids(instrument, granularity):
            dataset = await self._datasets.get_by_id(dataset_id)
            if dataset is not None:
                found.append(dataset)
        return found
