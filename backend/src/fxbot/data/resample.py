"""Resample bid/ask candles to a coarser granularity (e.g. H1 → H4 or D).

Target bars align like OANDA's: 2h+ intraday and daily bars start at 17:00 New York, so
their UTC boundaries follow US daylight-saving time. Bars are labelled by their open time
and emitted only once their period has ended (no partial bars).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from itertools import groupby

from fxbot.domain.calendar import bar_close_time, bar_open_time, ensure_utc
from fxbot.domain.enums import Granularity
from fxbot.domain.errors import DataIntegrityError
from fxbot.domain.models import OHLC, Candle


def _merge(sides: Sequence[OHLC]) -> OHLC:
    return OHLC(
        open=sides[0].open,
        high=max(side.high for side in sides),
        low=min(side.low for side in sides),
        close=sides[-1].close,
    )


def resample(
    candles: Sequence[Candle], target: Granularity, *, as_of: datetime | None = None
) -> list[Candle]:
    """Aggregate ``candles`` (one instrument, one granularity, ascending) into ``target`` bars.

    A target bar is returned only if it has ended by ``as_of`` (default: the close of the
    last input candle).
    """
    if not candles:
        return []
    first = candles[0]
    if target.duration <= first.granularity.duration:
        raise ValueError("resample target must be coarser than the source granularity")
    previous: datetime | None = None
    for candle in candles:
        if candle.instrument != first.instrument or candle.granularity != first.granularity:
            raise DataIntegrityError("resample expects one instrument and one granularity")
        if previous is not None and candle.time <= previous:
            raise DataIntegrityError("resample expects strictly increasing candle times")
        previous = candle.time
    cutoff = ensure_utc(as_of) if as_of is not None else candles[-1].close_time

    result: list[Candle] = []
    for bucket_open, group in groupby(candles, key=lambda c: bar_open_time(c.time, target)):
        members = list(group)
        if bar_close_time(bucket_open, target) > cutoff:
            continue
        result.append(
            Candle(
                instrument=first.instrument,
                granularity=target,
                time=bucket_open,
                bid=_merge([c.bid for c in members]),
                ask=_merge([c.ask for c in members]),
                volume=sum(c.volume for c in members),
                complete=True,
                ask_source=members[0].ask_source,
            )
        )
    return result


# Bars of 2h and more are always built from H1 here, never taken from a broker, so OANDA, MT5
# brokers (whose H4/D1 follow their server clock) and the validation datasets all share the
# same 17:00 New York alignment (research 08 §D.1).
BASE_GRANULARITY = Granularity.H1
DERIVED_GRANULARITIES = frozenset(g for g in Granularity if g.duration > BASE_GRANULARITY.duration)


def base_window(
    start: datetime, end: datetime | None, target: Granularity
) -> tuple[datetime, datetime | None]:
    """The H1 range needed to build every ``target`` bar opening in ``[start, end)``."""
    base_start = bar_open_time(start, target)
    if end is None:
        return base_start, None
    last_open = bar_open_time(end - BASE_GRANULARITY.duration, target)
    return base_start, max(end, bar_close_time(last_open, target))


def resample_window(
    base: Sequence[Candle],
    target: Granularity,
    start: datetime,
    end: datetime | None,
    *,
    as_of: datetime,
) -> list[Candle]:
    """``target`` bars opening in ``[start, end)`` that have ended by ``as_of``."""
    start = ensure_utc(start)
    bars = resample(base, target, as_of=as_of)
    return [c for c in bars if c.time >= start and (end is None or c.time < end)]
