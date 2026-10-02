"""Historical candle downloader: paginated, resumable, complete bid/ask candles only.

Each page is stored before the next is requested, so an interrupted download resumes from
the last stored candle (``includeFirst=false``) instead of starting over.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fxbot.data.candle_store import CandleStore
from fxbot.domain.calendar import ensure_utc
from fxbot.domain.enums import AskSource, Granularity
from fxbot.domain.models import Candle, Dataset
from fxbot.logging import get_logger

log = get_logger(__name__)


class CandlePageSource(Protocol):
    def iter_candle_pages(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime,
        end: datetime | None = None,
        *,
        include_first: bool = True,
    ) -> AsyncIterator[list[Candle]]: ...


@dataclass(frozen=True, slots=True)
class DownloadReport:
    instrument: str
    granularity: Granularity
    stored: int
    resumed_from: datetime | None
    first: datetime | None
    last: datetime | None


def oanda_dataset(environment: str, instrument: str, granularity: Granularity) -> Dataset:
    return Dataset(
        name=f"oanda-{environment}:{instrument}:{granularity.value}:BA",
        source=f"oanda-{environment}",
        price_side="BA",
        ask_source=AskSource.QUOTED,
        smoothed=False,
        tz_origin="UTC",
        licence_note="OANDA API data for the account holder's own research; do not redistribute.",
    )


class HistoricalDownloader:
    def __init__(self, source: CandlePageSource, store: CandleStore) -> None:
        self._source = source
        self._store = store

    def __repr__(self) -> str:
        return "HistoricalDownloader()"

    async def download(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime,
        end: datetime | None = None,
        *,
        dataset: Dataset,
    ) -> DownloadReport:
        start = ensure_utc(start)
        latest = await self._store.latest_time(instrument, granularity, dataset=dataset.name)
        resume = latest is not None and latest >= start
        cursor = latest if resume and latest is not None else start
        stored = 0
        first: datetime | None = None
        last: datetime | None = None
        async for page in self._source.iter_candle_pages(
            instrument, granularity, cursor, end, include_first=not resume
        ):
            complete = [c for c in page if c.complete]
            if not complete:
                continue
            stored += await self._store.upsert(complete, dataset=dataset)
            first = first or complete[0].time
            last = complete[-1].time
            log.info(
                "stored candles",
                instrument=instrument,
                granularity=granularity.value,
                count=len(complete),
                through=last.isoformat(),
            )
        return DownloadReport(
            instrument=instrument,
            granularity=granularity,
            stored=stored,
            resumed_from=cursor if resume else None,
            first=first,
            last=last,
        )
