from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fxbot.data.spreads import SpreadProfile, candle_from_bid, hour_of_week, session_multiplier
from fxbot.domain.enums import AskSource, Granularity
from fxbot.domain.models import OHLC
from tests.data.conftest import bar

D = Decimal
MONDAY_NOON_NY = datetime(2024, 3, 4, 17, tzinfo=UTC)


def test_hour_of_week_and_session_multiplier() -> None:
    assert hour_of_week(MONDAY_NOON_NY) == 12
    assert session_multiplier(MONDAY_NOON_NY) == 1
    assert session_multiplier(datetime(2024, 3, 4, 21, 50, tzinfo=UTC)) == 4  # 16:50 New York
    assert session_multiplier(datetime(2024, 3, 3, 22, 30, tzinfo=UTC)) == 3  # Sunday 17:30


def test_typical_profile() -> None:
    profile = SpreadProfile.typical(["EUR_USD"])

    assert profile.spread_at("EUR_USD", MONDAY_NOON_NY) == D("0.00013")
    assert profile.spread_at("EUR_USD", datetime(2024, 3, 4, 21, tzinfo=UTC)) == D("0.00052")
    with pytest.raises(KeyError):
        profile.spread_at("GBP_USD", MONDAY_NOON_NY)
    assert "EUR_USD" in repr(profile)


def test_profile_from_quoted_candles() -> None:
    candles = [bar(MONDAY_NOON_NY + timedelta(weeks=w)) for w in range(25)]
    candles.append(bar(MONDAY_NOON_NY + timedelta(hours=1)))  # too few samples for its hour

    profile = SpreadProfile.from_candles(candles)

    assert profile.spread_at("EUR_USD", MONDAY_NOON_NY) == D("0.0001")
    assert profile.spread_at("EUR_USD", MONDAY_NOON_NY + timedelta(hours=1)) == D("0.0001")


def test_ask_uses_the_wider_of_bar_and_profile_spread() -> None:
    profile = SpreadProfile.typical(["EUR_USD"])
    bid = OHLC(open=D("1.10000"), high=D("1.10100"), low=D("1.09900"), close=D("1.10050"))
    common = {
        "instrument": "EUR_USD",
        "granularity": Granularity.H1,
        "time": MONDAY_NOON_NY,
        "bid": bid,
    }

    narrow = candle_from_bid(**common, bar_spread=D("0.00005"), profile=profile)  # type: ignore[arg-type]
    wide = candle_from_bid(**common, bar_spread=D("0.00030"), profile=profile)  # type: ignore[arg-type]

    assert narrow.spread_open == D("0.00013") and narrow.ask_source is AskSource.MODEL_SPREAD
    assert wide.spread_open == D("0.00030") and wide.ask_source is AskSource.BAR_SPREAD
