from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from fxbot.domain.enums import AskSource, FillReason, Granularity, OrderStatus, Side
from fxbot.domain.instruments import DEFAULT_INSTRUMENTS, default_instruments
from fxbot.domain.masking import mask_account_id
from fxbot.domain.models import (
    OHLC,
    Candle,
    Fill,
    Instrument,
    OrderRequest,
    OrderResult,
    Position,
    Price,
    Trade,
    make_client_id,
)

D = Decimal
T0 = datetime(2024, 3, 4, 12, tzinfo=UTC)


def ohlc(o: str, h: str, low: str, c: str) -> OHLC:
    return OHLC(open=D(o), high=D(h), low=D(low), close=D(c))


def order_fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "client_id": "afx-1",
        "instrument": "EUR_USD",
        "side": Side.BUY,
        "units": D(1000),
        "stop_loss": D("1.09"),
        "take_profit": D("1.12"),
        "price_bound": D("1.1005"),
        "strategy_id": "s1.trend",
        "signal_id": "sig:2024-03-04T12:00Z",
    }
    return fields | overrides


# ------------------------------------------------------------------------- numbers


def test_decimals_round_trip_exactly_through_json() -> None:
    price = Price(instrument="EUR_USD", time=T0, bid=D("1.10000"), ask=D("1.10012"))

    restored = Price.model_validate_json(price.model_dump_json())

    assert restored == price
    assert str(restored.bid) == "1.10000"  # trailing zeros kept
    assert '"bid":"1.10000"' in price.model_dump_json()  # Decimals travel as strings


@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), D("-Infinity"), "nan", "inf"])
def test_non_finite_numbers_are_rejected(bad: Any) -> None:
    with pytest.raises(ValidationError):
        Price(instrument="EUR_USD", time=T0, bid=bad, ask=D("1.1"))
    with pytest.raises(ValidationError):
        OrderRequest(**order_fields(units=bad))
    with pytest.raises(ValidationError):
        Fill(
            transaction_id="1",
            time=T0,
            instrument="EUR_USD",
            side=Side.BUY,
            units=D(1),
            price=D("1.1"),
            trade_id="1",
            reason=FillReason.ENTRY,
            realized_pl=bad,
        )


@pytest.mark.parametrize("value", [1.1, True])
def test_floats_and_bools_are_refused_for_money(value: Any) -> None:
    with pytest.raises(ValidationError, match="not accepted"):
        Price(instrument="EUR_USD", time=T0, bid=value, ask=D("1.2"))


def test_ints_and_strings_are_accepted() -> None:
    price = Price(instrument="USD_JPY", time=T0, bid=150, ask="150.010")  # type: ignore[arg-type]

    assert price.bid == D(150) and price.ask == D("150.010")


# ------------------------------------------------------------------------- instruments


def test_pip_and_tick_size_from_precision() -> None:
    eur_usd, usd_jpy = DEFAULT_INSTRUMENTS["EUR_USD"], DEFAULT_INSTRUMENTS["USD_JPY"]

    assert eur_usd.pip_size == D("0.0001") and eur_usd.tick_size == D("0.00001")
    assert usd_jpy.pip_size == D("0.01") and usd_jpy.tick_size == D("0.001")
    assert (eur_usd.base, eur_usd.quote) == ("EUR", "USD")
    assert eur_usd.to_pips(D("0.0025")) == 25
    assert eur_usd.round_price(D("1.123456")) == D("1.12346")
    assert usd_jpy.round_price(D("150.12349")) == D("150.123")


def test_units_round_down_to_the_step_and_respect_limits() -> None:
    # An MT5-style symbol: lots of 100,000 units, volume step 0.01 lot = 1,000 units.
    lots = Instrument(
        name="EUR_USD",
        pip_location=-4,
        display_precision=5,
        units_step=D(1000),
        min_units=D(1000),
        max_units=D(5_000_000),
        contract_size=D(100_000),
        min_stop_distance=D("0.00050"),
        margin_rate=D("0.0333"),
    )

    assert lots.round_units(D(12_999)) == D(12_000)
    assert lots.round_units(D(999)) == 0
    assert lots.to_lots(D(12_000)) == D("0.12")
    assert lots.from_lots(D("0.12")) == D(12_000)
    assert lots.size_problem(D(12_000)) is None
    assert "positive" in (lots.size_problem(D(0)) or "")
    assert "minimum" in (lots.size_problem(D(500)) or "")
    assert "maximum" in (lots.size_problem(D(6_000_000)) or "")
    assert "step" in (lots.size_problem(D(1_500)) or "")
    assert "positive" in (lots.size_problem(D(-1)) or "")
    assert lots.stop_distance_problem(D("1.10000"), D("1.09970")) is not None
    assert lots.stop_distance_problem(D("1.10000"), D("1.09900")) is None

    fractional = Instrument(
        name="XAU_USD",
        pip_location=-2,
        display_precision=2,
        units_step=D("0.01"),
        min_units=D("0.01"),
        margin_rate=D("0.05"),
    )
    assert fractional.units_places == 2
    assert fractional.round_units(D("1.239")) == D("1.23")


def test_default_instrument_catalog() -> None:
    assert set(default_instruments(["EUR_USD"])) == {"EUR_USD"}
    assert len(default_instruments()) == len(DEFAULT_INSTRUMENTS)
    with pytest.raises(KeyError):
        default_instruments(["XXX_YYY"])


def test_instrument_names_are_canonical() -> None:
    with pytest.raises(ValidationError):
        Instrument(name="EURUSD", pip_location=-4, display_precision=5, margin_rate=D("0.05"))


# ------------------------------------------------------------------------- candles and prices


def test_candle_mid_spread_and_close_time() -> None:
    candle = Candle(
        instrument="EUR_USD",
        granularity=Granularity.H1,
        time=T0,
        bid=ohlc("1.10000", "1.10100", "1.09900", "1.10050"),
        ask=ohlc("1.10010", "1.10112", "1.09910", "1.10064"),
    )

    assert candle.mid == ohlc("1.10005", "1.10106", "1.09905", "1.10057")
    assert candle.spread_open == D("0.00010") and candle.spread_close == D("0.00014")
    assert candle.close_time == T0 + timedelta(hours=1)
    assert candle.ask_source is AskSource.QUOTED


def test_crossed_candles_and_quotes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="crossed candle"):
        Candle(
            instrument="EUR_USD",
            granularity=Granularity.H1,
            time=T0,
            bid=ohlc("1.10010", "1.10100", "1.09900", "1.10050"),
            ask=ohlc("1.10000", "1.10110", "1.09910", "1.10060"),
        )
    with pytest.raises(ValidationError, match="crossed quote"):
        Price(instrument="EUR_USD", time=T0, bid=D("1.1001"), ask=D("1.1000"))


def test_ohlc_range_is_enforced() -> None:
    with pytest.raises(ValidationError, match="inconsistent OHLC"):
        ohlc("1.1", "1.09", "1.08", "1.085")
    with pytest.raises(ValidationError):
        ohlc("0", "1", "0", "1")  # prices must be positive


def test_candle_from_bid_and_spread() -> None:
    candle = Candle.from_bid_and_spread(
        instrument="EUR_USD",
        granularity=Granularity.H1,
        time=T0,
        bid=ohlc("1.10000", "1.10100", "1.09900", "1.10050"),
        spread=D("0.00012"),
        volume=42,
    )

    assert candle.ask == ohlc("1.10012", "1.10112", "1.09912", "1.10062")
    assert candle.ask_source is AskSource.BAR_SPREAD
    assert candle.volume == 42
    with pytest.raises(ValueError, match="spread"):
        Candle.from_bid_and_spread(
            instrument="EUR_USD",
            granularity=Granularity.H1,
            time=T0,
            bid=ohlc("1.1", "1.1", "1.1", "1.1"),
            spread=D(-1),
        )


@pytest.mark.parametrize(
    "when",
    [datetime(2024, 3, 4, 12), "2024-03-04T12:00:00"],
    ids=["naive-datetime", "naive-string"],
)
def test_naive_datetimes_are_rejected(when: Any) -> None:
    with pytest.raises(ValidationError, match="naive"):
        Price(instrument="EUR_USD", time=when, bid=D("1.1"), ask=D("1.1"))


def test_aware_datetimes_are_normalised_to_utc() -> None:
    tokyo = timezone(timedelta(hours=9))
    price = Price(
        instrument="EUR_USD", time=datetime(2024, 3, 4, 21, tzinfo=tokyo), bid=D(1), ask=D(1)
    )

    assert price.time == T0 and price.time.tzinfo is UTC


def test_price_helpers() -> None:
    price = Price(instrument="EUR_USD", time=T0, bid=D("1.1000"), ask=D("1.1002"))

    assert price.spread == D("0.0002") and price.mid == D("1.1001")
    assert price.for_side(Side.BUY) == price.ask and price.for_side(Side.SELL) == price.bid


# ------------------------------------------------------------------------- orders


def test_order_units_must_be_positive() -> None:
    for units in (D(0), D(-1000)):
        with pytest.raises(ValidationError):
            OrderRequest(**order_fields(units=units))


@pytest.mark.parametrize(
    "overrides",
    [
        {"stop_loss": D("1.2")},  # buy stop above the bound
        {"take_profit": D("1.08")},  # buy target below the stop
        {"side": Side.SELL, "stop_loss": D("1.09"), "price_bound": D("1.0995")},
    ],
)
def test_order_levels_must_be_on_the_right_side(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="wrong side"):
        OrderRequest(**order_fields(**overrides))


@pytest.mark.parametrize("client_id", ["7f3c2a", "afx-" + "x" * 28, "afx-bad id", "afx-é"])
def test_client_ids_are_short_ascii_with_our_prefix(client_id: str) -> None:
    with pytest.raises(ValidationError):
        OrderRequest(**order_fields(client_id=client_id))


def test_make_client_id_is_deterministic_and_valid() -> None:
    first = make_client_id("sig-1", "0")

    assert first == make_client_id("sig-1", "0")
    assert first != make_client_id("sig-1", "1")
    assert first.startswith("afx-") and len(first) <= 31
    OrderRequest(**order_fields(client_id=first))


def test_order_result_consistency() -> None:
    fill = Fill(
        transaction_id="2",
        time=T0,
        instrument="EUR_USD",
        side=Side.BUY,
        units=D(1),
        price=D("1.1"),
        trade_id="2",
        reason=FillReason.ENTRY,
    )
    with pytest.raises(ValidationError, match="needs a fill"):
        OrderResult(status=OrderStatus.FILLED, client_id="afx-1")
    with pytest.raises(ValidationError, match="only filled"):
        OrderResult(status=OrderStatus.CANCELLED, client_id="afx-1", fill=fill)
    assert OrderResult(status=OrderStatus.FILLED, client_id="afx-1", fill=fill).fill == fill


def test_trade_position_and_side_helpers() -> None:
    trade = Trade(
        id="1",
        client_id="manual",
        instrument="EUR_USD",
        side=Side.SELL,
        units=D(1),
        initial_units=D(1),
        entry_price=D("1.1"),
        open_time=T0,
    )
    position = Position(instrument="EUR_USD", long_units=D(3), short_units=D(5))

    assert not trade.is_ours
    assert position.net_units == -2
    assert Side.BUY.sign == 1 and Side.SELL.sign == -1
    assert Side.BUY.opposite is Side.SELL and Side.SELL.opposite is Side.BUY
    assert Granularity.H4.seconds == 4 * 3600 and Granularity.W.duration == timedelta(weeks=1)


def test_masking_keeps_only_the_last_segment() -> None:
    assert mask_account_id("101-004-1234567-001") == "***-***-*******-001"
    assert mask_account_id("12345") == "***"
