"""Spread models: typical spreads per instrument and New York hour of the week.

Bid-only sources (MT5 bars, bid-only datasets) need a modelled ask. Following research 08 §D.2,
the ask is ``bid + max(bar spread, profile spread)``: a bar's own spread (often its minimum)
understates the ask side, while the profile captures the usual level for that hour, including
the wider spreads around the 17:00 New York rollover and the Sunday open.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Final

from fxbot.domain.calendar import NEW_YORK, ensure_utc
from fxbot.domain.enums import AskSource, Granularity
from fxbot.domain.instruments import DEFAULT_INSTRUMENTS
from fxbot.domain.models import OHLC, Candle

# Typical retail spreads in pips during liquid hours (research 07 §3: EUR/USD 1.2-1.4,
# GBP/USD 1.6, USD/JPY 1.4); others are conservative estimates.
TYPICAL_SPREAD_PIPS: Final[Mapping[str, Decimal]] = {
    "EUR_USD": Decimal("1.3"),
    "GBP_USD": Decimal("1.6"),
    "USD_JPY": Decimal("1.4"),
    "AUD_USD": Decimal("1.5"),
    "USD_CAD": Decimal("2.0"),
    "NZD_USD": Decimal("2.2"),
    "USD_CHF": Decimal("1.8"),
    "EUR_GBP": Decimal("1.6"),
    "EUR_JPY": Decimal("2.0"),
    "GBP_JPY": Decimal("3.0"),
    "EUR_CHF": Decimal("2.0"),
    "AUD_JPY": Decimal("2.2"),
}
_HOURS_PER_WEEK: Final = 168


def hour_of_week(at: datetime) -> int:
    """0..167, counted from Monday 00:00 New York time."""
    local = ensure_utc(at).astimezone(NEW_YORK)
    return local.weekday() * 24 + local.hour


def session_multiplier(at: datetime) -> Decimal:
    """Spread widening at the 17:00 New York rollover and the thin Sunday open."""
    local = ensure_utc(at).astimezone(NEW_YORK)
    minutes = local.hour * 60 + local.minute
    multiplier = Decimal(1)
    if 16 * 60 + 45 <= minutes < 17 * 60 + 30:
        multiplier = Decimal(4)
    if local.weekday() == 6 and minutes < 19 * 60:
        multiplier = max(multiplier, Decimal(3))
    return multiplier


class SpreadProfile:
    """Spread in price units for an instrument at a time (by New York hour of the week)."""

    def __init__(
        self,
        by_hour: Mapping[str, Mapping[int, Decimal]],
        fallback: Mapping[str, Decimal] | None = None,
    ) -> None:
        self._by_hour = {name: dict(hours) for name, hours in by_hour.items()}
        self._fallback = dict(fallback or {})

    def __repr__(self) -> str:
        return f"SpreadProfile(instruments={sorted(set(self._by_hour) | set(self._fallback))!r})"

    def spread_at(self, instrument: str, at: datetime) -> Decimal:
        hours = self._by_hour.get(instrument, {})
        value = hours.get(hour_of_week(at))
        if value is None:
            value = self._fallback.get(instrument)
        if value is None:
            raise KeyError(f"no spread profile for {instrument}")
        return value

    @classmethod
    def typical(cls, instruments: Iterable[str] | None = None) -> SpreadProfile:
        """Typical spreads with rollover and Sunday-open widening (no measured data needed)."""
        names = list(instruments) if instruments is not None else list(TYPICAL_SPREAD_PIPS)
        by_hour: dict[str, dict[int, Decimal]] = {}
        fallback: dict[str, Decimal] = {}
        for name in names:
            pip = DEFAULT_INSTRUMENTS[name].pip_size
            base = TYPICAL_SPREAD_PIPS.get(name, Decimal(3)) * pip
            fallback[name] = base
            # A reference week (Monday 2024-01-08, New York); the rule is the same every week.
            reference = datetime(2024, 1, 8, tzinfo=NEW_YORK)
            hours = {}
            for hour in range(_HOURS_PER_WEEK):
                local_hour = reference.replace(day=8 + hour // 24, hour=hour % 24)
                # Sample at :50 so the 16:45-17:30 rollover window counts for the 16:00 hour.
                widest = max(
                    session_multiplier(local_hour.replace(minute=minute)) for minute in (0, 50)
                )
                hours[hour] = base * widest
            by_hour[name] = hours
        return cls(by_hour, fallback)

    @classmethod
    def from_candles(cls, candles: Iterable[Candle], *, min_samples: int = 20) -> SpreadProfile:
        """Median opening spread per instrument and hour of week, from bid/ask candles."""
        samples: dict[str, dict[int, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
        overall: dict[str, list[Decimal]] = defaultdict(list)
        for candle in candles:
            if candle.ask_source is not AskSource.QUOTED:
                continue
            spread = candle.spread_open
            samples[candle.instrument][hour_of_week(candle.time)].append(spread)
            overall[candle.instrument].append(spread)
        by_hour = {
            name: {
                hour: statistics.median(values)
                for hour, values in hours.items()
                if len(values) >= min_samples
            }
            for name, hours in samples.items()
        }
        fallback = {name: statistics.median(values) for name, values in overall.items()}
        return cls(by_hour, fallback)


def candle_from_bid(
    *,
    instrument: str,
    granularity: Granularity,
    time: datetime,
    bid: OHLC,
    bar_spread: Decimal,
    profile: SpreadProfile,
    volume: int = 0,
    complete: bool = True,
) -> Candle:
    """Candle from bid OHLC with ``ask = bid + max(bar spread, profile spread)``."""
    modelled = profile.spread_at(instrument, time)
    from_bar = bar_spread >= modelled
    return Candle.from_bid_and_spread(
        instrument=instrument,
        granularity=granularity,
        time=time,
        bid=bid,
        spread=bar_spread if from_bar else modelled,
        volume=volume,
        complete=complete,
        ask_source=AskSource.BAR_SPREAD if from_bar else AskSource.MODEL_SPREAD,
    )
