from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fxbot.brokers.paper import PaperBroker, PaperConfig
from fxbot.domain.clock import SimClock
from fxbot.domain.enums import FillReason, Granularity, OrderStatus, Side
from fxbot.domain.errors import BrokerRejectedError
from fxbot.domain.instruments import DEFAULT_INSTRUMENTS
from fxbot.domain.models import OHLC, Candle, Instrument, OrderRequest, Price

T0 = datetime(2024, 3, 4, 12, 0, tzinfo=UTC)  # a Monday
D = Decimal


def make_broker(**config: object) -> tuple[PaperBroker, SimClock]:
    clock = SimClock(T0)
    return PaperBroker(clock=clock, config=PaperConfig(**config)), clock  # type: ignore[arg-type]


def quote(broker: PaperBroker, instrument: str, bid: str, ask: str, **kw: object) -> list:  # type: ignore[type-arg]
    return broker.on_price(
        Price(instrument=instrument, time=T0, bid=D(bid), ask=D(ask), **kw)  # type: ignore[arg-type]
    )


def order(
    side: Side = Side.BUY,
    *,
    client_id: str = "afx-1",
    instrument: str = "EUR_USD",
    units: str = "10000",
    stop: str | None = None,
    target: str | None = None,
    bound: str | None = None,
) -> OrderRequest:
    buy = side is Side.BUY
    return OrderRequest(
        client_id=client_id,
        instrument=instrument,
        side=side,
        units=D(units),
        stop_loss=D(stop or ("1.09500" if buy else "1.10500")),
        take_profit=D(target) if target else None,
        price_bound=D(bound or ("1.10100" if buy else "1.09900")),
        strategy_id="test",
        signal_id="sig",
    )


def candle(
    bid: tuple[str, str, str, str],
    *,
    spread: str = "0.00010",
    time: datetime = T0,
    instrument: str = "EUR_USD",
) -> Candle:
    return Candle.from_bid_and_spread(
        instrument=instrument,
        granularity=Granularity.H1,
        time=time,
        bid=OHLC(open=D(bid[0]), high=D(bid[1]), low=D(bid[2]), close=D(bid[3])),
        spread=D(spread),
    )


# ------------------------------------------------------------------------- entries


async def test_buy_fills_at_ask_plus_slippage_and_sell_at_bid_minus_slippage() -> None:
    broker, _ = make_broker(hedging=True)
    quote(broker, "EUR_USD", "1.10000", "1.10010")

    bought = await broker.submit_order(order(Side.BUY))
    sold = await broker.submit_order(order(Side.SELL, client_id="afx-2"))

    assert bought.fill is not None and sold.fill is not None
    assert bought.fill.price == D("1.10011")  # ask + 0.1 pip
    assert sold.fill.price == D("1.09999")  # bid - 0.1 pip
    assert bought.fill.half_spread_cost == D("0.00005") * 10000


async def test_random_slippage_is_deterministic_for_a_seed() -> None:
    async def fills(seed: int) -> list[Decimal]:
        broker, _ = make_broker(seed=seed, random_slippage_pips=D(1), hedging=True)
        quote(broker, "EUR_USD", "1.10000", "1.10010")
        prices = []
        for i in range(5):
            result = await broker.submit_order(order(client_id=f"afx-{i}"))
            assert result.fill is not None
            prices.append(result.fill.price)
        return prices

    assert await fills(3) == await fills(3)
    assert await fills(3) != await fills(4)


@pytest.mark.parametrize(
    ("setup", "kwargs", "reason"),
    [
        ("halted", {}, "MARKET_HALTED"),
        ("quote", {"bound": "1.10005"}, "BOUNDS_VIOLATION"),
        ("quote", {"stop": "1.10000"}, "STOP_LOSS_ON_FILL_LOSS"),
        ("quote", {"target": "1.10005", "stop": "1.09000"}, "TAKE_PROFIT_ON_FILL_LOSS"),
        ("quote", {"units": "5000000"}, "INSUFFICIENT_MARGIN"),
    ],
)
async def test_unfillable_orders_are_cancelled(
    setup: str, kwargs: dict[str, str], reason: str
) -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010", tradeable=setup != "halted")

    result = await broker.submit_order(order(**kwargs))  # type: ignore[arg-type]

    assert result.status is OrderStatus.CANCELLED
    assert result.reason == reason
    assert await broker.get_open_trades() == []
    # A cancelled order is remembered: resubmitting returns the same outcome.
    assert (await broker.submit_order(order(**kwargs))).reason == reason  # type: ignore[arg-type]


async def test_invalid_orders_are_rejected_and_not_remembered() -> None:
    broker, _ = make_broker()

    assert (await broker.submit_order(order())).reason == "NO_QUOTE"
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    assert (await broker.submit_order(order(units="0.4"))).status is OrderStatus.REJECTED
    unknown = order(instrument="XAU_USD")
    assert (await broker.submit_order(unknown)).reason == "INSTRUMENT_UNKNOWN"
    assert (await broker.submit_order(order())).status is OrderStatus.FILLED


async def test_minimum_stop_distance_is_enforced() -> None:
    spec = DEFAULT_INSTRUMENTS["EUR_USD"].model_copy(update={"min_stop_distance": D("0.00100")})
    broker = PaperBroker(clock=SimClock(T0), instruments={"EUR_USD": spec})
    quote(broker, "EUR_USD", "1.10000", "1.10010")

    result = await broker.submit_order(order(stop="1.09950"))

    assert result.reason == "STOP_LOSS_ON_FILL_PRICE_DISTANCE_MINIMUM_NOT_MET"


# ------------------------------------------------------------------------- netting


async def test_netting_reduces_before_opening() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    first = await broker.submit_order(order(units="1000"))

    result = await broker.submit_order(order(Side.SELL, client_id="afx-2", units="1500"))

    assert result.status is OrderStatus.FILLED
    (closed,) = result.closed
    assert first.fill is not None and closed.trade_id == first.fill.trade_id
    assert closed.units == 1000
    assert result.fill is not None and result.fill.units == 500
    (remaining,) = await broker.get_open_trades()
    assert remaining.side is Side.SELL and remaining.units == 500


async def test_netting_full_reduction_opens_nothing() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    await broker.submit_order(order(units="1000"))

    result = await broker.submit_order(order(Side.SELL, client_id="afx-2", units="1000"))

    assert result.status is OrderStatus.FILLED
    assert result.fill is None and len(result.closed) == 1
    assert await broker.get_open_trades() == []


async def test_hedging_keeps_opposite_trades() -> None:
    broker, _ = make_broker(hedging=True)
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    await broker.submit_order(order(units="1000"))
    await broker.submit_order(order(Side.SELL, client_id="afx-2", units="1000"))

    assert len(await broker.get_open_trades()) == 2
    (position,) = await broker.get_positions()
    assert position.net_units == 0


# ------------------------------------------------------------------------- exits


async def test_long_stop_triggers_on_bid() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    await broker.submit_order(order(stop="1.09900"))

    assert quote(broker, "EUR_USD", "1.09901", "1.09911") == []

    (fill,) = quote(broker, "EUR_USD", "1.09890", "1.09900")
    assert fill.reason is FillReason.STOP_LOSS
    assert fill.price == D("1.09889")  # bid minus slippage


async def test_short_stop_triggers_on_ask_even_with_bid_below_it() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    await broker.submit_order(order(Side.SELL, stop="1.10200"))

    (fill,) = quote(broker, "EUR_USD", "1.10195", "1.10205")

    assert fill.reason is FillReason.STOP_LOSS
    assert fill.price == D("1.10206")  # ask plus slippage


async def test_short_take_profit_on_tick() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    await broker.submit_order(order(Side.SELL, target="1.09500"))

    (fill,) = quote(broker, "EUR_USD", "1.09480", "1.09490")

    assert fill.reason is FillReason.TAKE_PROFIT
    assert fill.price == D("1.09490")


async def _open_before_bar(side: Side, **kwargs: str) -> PaperBroker:
    broker, clock = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    await broker.submit_order(order(side, **kwargs))
    clock.advance(timedelta(hours=1))
    return broker


async def test_long_stop_on_bar_bid_low() -> None:
    broker = await _open_before_bar(Side.BUY, stop="1.09800")
    bar = candle(("1.10000", "1.10100", "1.09790", "1.09950"), time=T0 + timedelta(hours=1))

    (fill,) = broker.on_candle(bar)

    assert fill.reason is FillReason.STOP_LOSS
    assert fill.price == D("1.09799")
    assert fill.time == bar.close_time


async def test_short_stop_on_bar_ask_high() -> None:
    broker = await _open_before_bar(Side.SELL, stop="1.10200")
    # bid high 1.10195 stays below the stop, but the ask high (bid + 1 pip) reaches it.
    bar = candle(("1.10000", "1.10195", "1.09900", "1.10000"), time=T0 + timedelta(hours=1))

    (fill,) = broker.on_candle(bar)

    assert fill.reason is FillReason.STOP_LOSS
    assert fill.price == D("1.10201")


async def test_gap_through_stop_fills_at_open() -> None:
    broker = await _open_before_bar(Side.BUY, stop="1.09800")
    bar = candle(("1.09500", "1.09600", "1.09400", "1.09550"), time=T0 + timedelta(hours=1))

    (fill,) = broker.on_candle(bar)

    assert fill.price == D("1.09499")  # the gapped open, minus slippage


async def test_stop_wins_when_both_levels_are_inside_one_bar() -> None:
    broker = await _open_before_bar(Side.BUY, stop="1.09800", target="1.10300")
    bar = candle(("1.10000", "1.10400", "1.09700", "1.10000"), time=T0 + timedelta(hours=1))

    (fill,) = broker.on_candle(bar)

    assert fill.reason is FillReason.STOP_LOSS


async def test_target_on_bar_and_gap_through_target() -> None:
    broker = await _open_before_bar(Side.BUY, stop="1.09800", target="1.10300")
    (fill,) = broker.on_candle(
        candle(("1.10000", "1.10350", "1.09900", "1.10100"), time=T0 + timedelta(hours=1))
    )
    assert (fill.reason, fill.price) == (FillReason.TAKE_PROFIT, D("1.10300"))

    gapped = await _open_before_bar(Side.BUY, stop="1.09800", target="1.10300")
    (fill,) = gapped.on_candle(
        candle(("1.10400", "1.10500", "1.10350", "1.10450"), time=T0 + timedelta(hours=1))
    )
    assert (fill.reason, fill.price) == (FillReason.TAKE_PROFIT, D("1.10400"))


async def test_entry_bar_only_counts_a_close_beyond_the_stop() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    await broker.submit_order(order(stop="1.09800", target="1.10200"))

    # Same bar as the entry: touching both levels intra-bar is ambiguous, so nothing happens.
    assert broker.on_candle(candle(("1.10000", "1.10300", "1.09700", "1.10000"))) == []
    # ...but a close beyond the stop does count.
    broker2, _ = make_broker()
    quote(broker2, "EUR_USD", "1.10000", "1.10010")
    await broker2.submit_order(order(stop="1.09800"))
    (fill,) = broker2.on_candle(candle(("1.10000", "1.10100", "1.09700", "1.09750")))
    assert fill.price == D("1.09749")


# ------------------------------------------------------------------------- P&L


async def test_pnl_is_converted_for_usd_jpy_in_a_usd_account() -> None:
    broker, _ = make_broker()
    quote(broker, "USD_JPY", "150.000", "150.010")
    result = await broker.submit_order(
        order(instrument="USD_JPY", stop="149.000", bound="150.100", units="10000")
    )
    assert result.fill is not None and result.fill.price == D("150.011")

    quote(broker, "USD_JPY", "151.011", "151.021")
    fill = await broker.close_trade(result.fill.trade_id)

    # Exit 151.011 - 0.1 pip slippage = 151.010; +0.999 JPY x 10,000 = 9,990 JPY.
    assert fill.price == D("151.010")
    expected = D("9990") / D("151.016")
    assert abs(fill.realized_pl - expected) < D("0.000001")
    account = await broker.get_account()
    assert account.balance == D(100_000) + fill.realized_pl


async def test_pnl_is_converted_for_eur_gbp_in_a_usd_account() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_GBP", "0.85000", "0.85010")
    eur_gbp = order(instrument="EUR_GBP", stop="0.84000", bound="0.85100")
    assert (await broker.submit_order(eur_gbp)).reason == "NO_CONVERSION_RATE"

    quote(broker, "GBP_USD", "1.26995", "1.27005")
    result = await broker.submit_order(
        order(client_id="afx-2", instrument="EUR_GBP", stop="0.84000", bound="0.85100")
    )
    assert result.fill is not None
    quote(broker, "EUR_GBP", "0.85511", "0.85521")
    fill = await broker.close_trade(result.fill.trade_id)

    # (0.85510 - 0.85011) x 10,000 = 49.90 GBP, x GBP_USD mid 1.27 = 63.373 USD.
    assert fill.realized_pl == D("49.90") * D("1.27")


async def test_account_tracks_unrealized_pl_and_margin() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    await broker.submit_order(order())
    quote(broker, "EUR_USD", "1.10111", "1.10121")

    account = await broker.get_account()

    assert account.unrealized_pl == (D("1.10111") - D("1.10011")) * 10000
    assert account.margin_used > 0
    assert account.nav == account.balance + account.unrealized_pl
    (trade,) = await broker.get_open_trades()
    assert trade.unrealized_pl == account.unrealized_pl


# ------------------------------------------------------------------------- closes


async def test_partial_close_reduces_the_trade() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    result = await broker.submit_order(order())
    assert result.fill is not None

    fill = await broker.close_trade(result.fill.trade_id, D("4000"))

    assert fill.units == 4000
    (trade,) = await broker.get_open_trades()
    assert trade.units == 6000 and trade.initial_units == 10000


async def test_close_errors() -> None:
    broker, _ = make_broker()
    with pytest.raises(BrokerRejectedError) as missing:
        await broker.close_trade("999")
    assert missing.value.status_code == 404

    quote(broker, "EUR_USD", "1.10000", "1.10010")
    result = await broker.submit_order(order())
    assert result.fill is not None
    with pytest.raises(BrokerRejectedError, match="invalid close units"):
        await broker.close_trade(result.fill.trade_id, D("20000"))
    quote(broker, "EUR_USD", "1.10000", "1.10010", tradeable=False)
    with pytest.raises(BrokerRejectedError, match="halted"):
        await broker.close_trade(result.fill.trade_id)
    assert await broker.close_all() == []  # logged, not raised; caller re-checks positions


async def test_moving_a_stop_through_the_market_closes_at_once() -> None:
    broker, _ = make_broker()
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    result = await broker.submit_order(order(target="1.11000"))
    assert result.fill is not None

    await broker.modify_trade_exits(result.fill.trade_id, take_profit=D("1.10500"))
    (trade,) = await broker.get_open_trades()
    assert trade.take_profit == D("1.10500")

    await broker.modify_trade_exits(result.fill.trade_id, stop_loss=D("1.10050"))

    assert await broker.get_open_trades() == []


async def test_transaction_log_and_instruments() -> None:
    broker, _ = make_broker()
    assert (await broker.get_transactions_since(None)).last_id == "0"
    quote(broker, "EUR_USD", "1.10000", "1.10010")
    await broker.submit_order(order(target="1.11000"))

    page = await broker.get_transactions_since("0")

    assert [t.type for t in page.items] == [
        "MARKET_ORDER",
        "ORDER_FILL",
        "STOP_LOSS_ORDER",
        "TAKE_PROFIT_ORDER",
    ]
    assert [int(t.id) for t in page.items] == [1, 2, 3, 4]
    assert page.last_id == "4"
    assert (await broker.get_transactions_since("4")).items == ()
    assert len(await broker.get_instruments(["EUR_USD", "XXX_YYY"])) == 1
    assert len(await broker.get_instruments()) == len(DEFAULT_INSTRUMENTS)
    assert await broker.get_prices(["EUR_USD", "GBP_USD"]) == [
        Price(instrument="EUR_USD", time=T0, bid=D("1.10000"), ask=D("1.10010"))
    ]
    assert repr(broker) == "PaperBroker(currency='USD')"
    await broker.connect()
    await broker.aclose()


def test_custom_instrument_specs_are_used() -> None:
    spec = Instrument(name="EUR_USD", pip_location=-4, display_precision=5, margin_rate=D("0.02"))
    broker = PaperBroker(clock=SimClock(T0), instruments={"EUR_USD": spec})
    assert broker.capabilities.supports_hedging is False
