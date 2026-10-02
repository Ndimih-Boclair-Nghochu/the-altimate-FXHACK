"""``PaperBroker``: a local, deterministic broker simulator.

It follows the same rules as the real adapters so strategies cannot tell the difference:

- Market orders are fill-or-kill: buys fill at the ask, sells at the bid, plus adverse
  slippage; a fill beyond ``price_bound`` is cancelled (``BOUNDS_VIOLATION``).
- Every trade carries a broker-side stop. Long stops and targets trigger on the bid, short
  ones on the ask.
- Price source: ``on_price`` (ticks) or ``on_candle`` (bars). On a bar, a gap through a level
  fills at the open; if the stop and the target are both inside the bar, the stop wins; on the
  bar a trade was opened in, only a close beyond the stop counts.
- P&L is converted to the account currency with current quotes (``USD_JPY`` for JPY P&L in a
  USD account, ``GBP_USD`` for GBP P&L), so feed those instruments too.
- Every action is a transaction with an increasing numeric id.

Financing and commission are not simulated here (the backtester's cost model owns them).
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from fxbot.brokers.base import BrokerCapabilities, ClientIdSupport
from fxbot.domain.clock import Clock
from fxbot.domain.enums import FillReason, OrderStatus, PositionAccounting, Side
from fxbot.domain.errors import BrokerRejectedError, DataIntegrityError
from fxbot.domain.instruments import default_instruments
from fxbot.domain.models import (
    AccountSummary,
    Candle,
    Fill,
    Instrument,
    OrderRequest,
    OrderResult,
    Position,
    Price,
    Trade,
    Transaction,
    TransactionPage,
)
from fxbot.logging import get_logger

log = get_logger(__name__)

_TWO = Decimal(2)


@dataclass(frozen=True, slots=True)
class PaperConfig:
    account_currency: str = "USD"
    initial_balance: Decimal = Decimal(100_000)
    slippage_pips: Decimal = Decimal("0.1")  # adverse, on market fills and stop exits
    random_slippage_pips: Decimal = Decimal(0)  # extra adverse slippage, uniform in [0, x]
    seed: int = 0
    # False (default, like most OANDA accounts): an opposite order first reduces open trades,
    # oldest first, and only the remainder opens a new trade. True: trades coexist.
    hedging: bool = False
    # NATIVE keeps an index by client id; COMMENT emulates brokers without client ids (MT5),
    # where orders are found again by scanning history for our magic number and comment.
    client_id_support: ClientIdSupport = ClientIdSupport.NATIVE
    magic: int = 7_001
    comment_limit: int = 31


@dataclass(slots=True)
class _OpenTrade:
    id: str
    client_id: str
    instrument: str
    side: Side
    units: Decimal
    initial_units: Decimal
    entry_price: Decimal
    open_time: datetime
    stop_loss: Decimal
    take_profit: Decimal | None
    realized_pl: Decimal = Decimal(0)


@dataclass(slots=True)
class _OrderRecord:
    magic: int
    comment: str
    result: OrderResult


@dataclass(slots=True)
class _State:
    balance: Decimal
    next_id: int = 1
    prices: dict[str, Price] = field(default_factory=dict)
    trades: dict[str, _OpenTrade] = field(default_factory=dict)
    orders_by_client_id: dict[str, OrderResult] = field(default_factory=dict)
    order_history: list[_OrderRecord] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)


class PaperBroker:
    def __init__(
        self,
        *,
        clock: Clock,
        instruments: Mapping[str, Instrument] | None = None,
        config: PaperConfig | None = None,
    ) -> None:
        self._clock = clock
        self._config = config or PaperConfig()
        self._instruments = dict(instruments or default_instruments())
        self._rng = random.Random(self._config.seed)  # noqa: S311 - simulated slippage
        self._state = _State(balance=self._config.initial_balance)

    def __repr__(self) -> str:
        return f"PaperBroker(currency={self._config.account_currency!r})"

    @property
    def name(self) -> str:
        return "paper"

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            position_accounting=PositionAccounting.PER_TRADE,
            supports_hedging=self._config.hedging,
            fifo_required=False,
            supports_sl_on_fill=True,
            supports_tp_on_fill=True,
            supports_trailing_stop=False,
            supports_guaranteed_stop=False,
            client_id_support=self._config.client_id_support,
            supports_price_streaming=False,
            supports_transaction_streaming=False,
            candle_price_sides=frozenset({"B", "A"}),
        )

    async def connect(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    # ------------------------------------------------------------------ price input

    def on_price(self, price: Price) -> list[Fill]:
        """Feed a quote; returns fills from stops or targets it triggered."""
        self._state.prices[price.instrument] = price
        fills: list[Fill] = []
        for trade in self._open_trades_for(price.instrument):
            fill = self._check_exit_on_tick(trade, price)
            if fill is not None:
                fills.append(fill)
        return fills

    def on_candle(self, candle: Candle) -> list[Fill]:
        """Feed a closed bar; checks exits against its range, then quotes its close."""
        fills: list[Fill] = []
        for trade in self._open_trades_for(candle.instrument):
            fill = self._check_exit_on_bar(trade, candle)
            if fill is not None:
                fills.append(fill)
        close = Price(
            instrument=candle.instrument,
            time=candle.close_time,
            bid=candle.bid.close,
            ask=candle.ask.close,
        )
        self._state.prices[candle.instrument] = close
        return fills

    def _open_trades_for(self, instrument: str) -> list[_OpenTrade]:
        return [t for t in self._state.trades.values() if t.instrument == instrument]

    # ------------------------------------------------------------------ reads

    async def get_instruments(self, names: Sequence[str] | None = None) -> list[Instrument]:
        if names is None:
            return list(self._instruments.values())
        return [self._instruments[n] for n in names if n in self._instruments]

    async def get_prices(self, instruments: Sequence[str]) -> list[Price]:
        prices = self._state.prices
        return [prices[name] for name in instruments if name in prices]

    async def get_account(self) -> AccountSummary:
        unrealized = sum((self._unrealized(t) for t in self._state.trades.values()), Decimal(0))
        margin = sum((self._margin(t) for t in self._state.trades.values()), Decimal(0))
        nav = self._state.balance + unrealized
        return AccountSummary(
            masked_id="paper",
            currency=self._config.account_currency,
            balance=self._state.balance,
            nav=nav,
            unrealized_pl=unrealized,
            margin_used=margin,
            margin_available=nav - margin,
            margin_closeout_percent=(margin / 2 / nav) if nav > 0 else Decimal(0),
            open_trade_count=len(self._state.trades),
            open_position_count=len({t.instrument for t in self._state.trades.values()}),
            hedging_enabled=True,
            last_transaction_id=self._last_transaction_id(),
        )

    async def get_open_trades(self) -> list[Trade]:
        return [self._to_trade(t) for t in self._state.trades.values()]

    async def get_positions(self) -> list[Position]:
        grouped: dict[str, list[_OpenTrade]] = defaultdict(list)
        for trade in self._state.trades.values():
            grouped[trade.instrument].append(trade)
        positions = []
        for instrument, trades in grouped.items():
            longs = [t for t in trades if t.side is Side.BUY]
            shorts = [t for t in trades if t.side is Side.SELL]
            positions.append(
                Position(
                    instrument=instrument,
                    long_units=sum((t.units for t in longs), Decimal(0)),
                    short_units=sum((t.units for t in shorts), Decimal(0)),
                    long_average_price=_average_price(longs),
                    short_average_price=_average_price(shorts),
                    unrealized_pl=sum((self._unrealized(t) for t in trades), Decimal(0)),
                )
            )
        return positions

    async def get_transactions_since(self, last_id: str | None) -> TransactionPage:
        last = self._last_transaction_id() or "0"  # "0": before the first transaction
        if last_id is None:
            return TransactionPage(items=(), last_id=last)
        newer = tuple(t for t in self._state.transactions if int(t.id) > int(last_id))
        return TransactionPage(items=newer, last_id=last)

    async def find_order(self, client_id: str) -> OrderResult | None:
        if self._config.client_id_support is ClientIdSupport.NATIVE:
            return self._state.orders_by_client_id.get(client_id)
        comment = client_id[: self._config.comment_limit]
        for record in reversed(self._state.order_history):
            if record.magic == self._config.magic and record.comment == comment:
                return record.result
        return None

    # ------------------------------------------------------------------ orders

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        existing = await self.find_order(order.client_id)
        if existing is not None:
            log.info("paper order already known; not resending", client_id=order.client_id)
            return existing
        instrument = self._instruments.get(order.instrument)
        if instrument is None:
            return self._reject(order, "INSTRUMENT_UNKNOWN")
        units = instrument.round_units(order.units)
        if problem := instrument.size_problem(units):
            return self._reject(order, problem)
        quote = self._state.prices.get(order.instrument)
        if quote is None:
            return self._reject(order, "NO_QUOTE")

        order_id = self._record("MARKET_ORDER", self._order_payload(order, units))
        if not quote.tradeable:
            return self._cancel(order, order_id, "MARKET_HALTED")
        fill_price = instrument.round_price(
            quote.for_side(order.side) + self._slippage(instrument) * order.side.sign
        )
        if (fill_price - order.price_bound) * order.side.sign > 0:
            return self._cancel(order, order_id, "BOUNDS_VIOLATION")
        exit_quote = quote.for_side(order.side.opposite)
        if (exit_quote - order.stop_loss) * order.side.sign <= 0:
            return self._cancel(order, order_id, "STOP_LOSS_ON_FILL_LOSS")
        if instrument.stop_distance_problem(fill_price, order.stop_loss):
            return self._cancel(order, order_id, "STOP_LOSS_ON_FILL_PRICE_DISTANCE_MINIMUM_NOT_MET")
        if (
            order.take_profit is not None
            and (order.take_profit - fill_price) * order.side.sign <= 0
        ):
            return self._cancel(order, order_id, "TAKE_PROFIT_ON_FILL_LOSS")
        to_reduce = [] if self._config.hedging else self._opposite_trades(order)
        opening = units - min(units, sum((t.units for t in to_reduce), Decimal(0)))
        try:
            required = self._margin_for(instrument, opening, quote)
            half_spread = quote.spread / _TWO * units * self._quote_to_account(instrument.quote)
        except DataIntegrityError:
            return self._cancel(order, order_id, "NO_CONVERSION_RATE")
        account = await self.get_account()
        if account.margin_used + required > account.nav:
            return self._cancel(order, order_id, "INSUFFICIENT_MARGIN")

        closed: list[Fill] = []
        remaining = units
        for trade in to_reduce:
            portion = min(trade.units, remaining)
            closed.append(self._close(trade, portion, fill_price, FillReason.CLOSE))
            remaining -= portion
        if remaining == 0:
            result = OrderResult(
                status=OrderStatus.FILLED,
                client_id=order.client_id,
                broker_order_id=order_id,
                closed=tuple(closed),
                last_transaction_id=self._last_transaction_id(),
            )
            self._remember(order.client_id, result)
            return result
        units = remaining

        now = self._clock.now()
        signed_units = str(units * order.side.sign)
        trade_id = self._next_transaction_id()  # like OANDA: the trade id is the fill's id
        fill_id = self._record(
            "ORDER_FILL",
            {
                "orderID": order_id,
                "instrument": order.instrument,
                "units": signed_units,
                "price": str(fill_price),
                "reason": "MARKET_ORDER",
                "tradeOpened": {"tradeID": trade_id, "units": signed_units},
            },
        )
        trade = _OpenTrade(
            id=fill_id,
            client_id=order.client_id,
            instrument=order.instrument,
            side=order.side,
            units=units,
            initial_units=units,
            entry_price=fill_price,
            open_time=now,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
        )
        self._state.trades[trade.id] = trade
        self._record("STOP_LOSS_ORDER", {"tradeID": trade.id, "price": str(order.stop_loss)})
        if order.take_profit is not None:
            self._record(
                "TAKE_PROFIT_ORDER", {"tradeID": trade.id, "price": str(order.take_profit)}
            )
        fill = Fill(
            transaction_id=fill_id,
            time=now,
            instrument=order.instrument,
            side=order.side,
            units=units,
            price=fill_price,
            trade_id=trade.id,
            reason=FillReason.ENTRY,
            client_id=order.client_id,
            half_spread_cost=half_spread,
        )
        result = OrderResult(
            status=OrderStatus.FILLED,
            client_id=order.client_id,
            broker_order_id=order_id,
            fill=fill,
            closed=tuple(closed),
            last_transaction_id=self._last_transaction_id(),
        )
        self._remember(order.client_id, result)
        return result

    def _opposite_trades(self, order: OrderRequest) -> list[_OpenTrade]:
        trades = self._open_trades_for(order.instrument)
        opposite = [t for t in trades if t.side is order.side.opposite]
        return sorted(opposite, key=lambda t: int(t.id))  # oldest first

    async def modify_trade_exits(
        self,
        trade_id: str,
        *,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> None:
        trade = self._trade(trade_id)
        instrument = self._instruments[trade.instrument]
        if stop_loss is not None:
            trade.stop_loss = instrument.round_price(stop_loss)
            self._record("STOP_LOSS_ORDER", {"tradeID": trade.id, "price": str(trade.stop_loss)})
        if take_profit is not None:
            trade.take_profit = instrument.round_price(take_profit)
            self._record(
                "TAKE_PROFIT_ORDER", {"tradeID": trade.id, "price": str(trade.take_profit)}
            )
        # Like a real broker, a level already through the market fills at once.
        quote = self._state.prices.get(trade.instrument)
        if quote is not None:
            self._check_exit_on_tick(trade, quote)

    async def close_trade(self, trade_id: str, units: Decimal | None = None) -> Fill:
        trade = self._trade(trade_id)
        quote = self._state.prices.get(trade.instrument)
        if quote is None:
            raise BrokerRejectedError(f"no quote for {trade.instrument}", code="NO_QUOTE")
        if not quote.tradeable:
            raise BrokerRejectedError("market halted", code="MARKET_HALTED")
        instrument = self._instruments[trade.instrument]
        close_units = trade.units if units is None else instrument.round_units(units)
        if close_units <= 0 or close_units > trade.units:
            raise BrokerRejectedError("invalid close units", code="UNITS_INVALID")
        price = quote.for_side(trade.side.opposite) - self._slippage(instrument) * trade.side.sign
        return self._close(trade, close_units, instrument.round_price(price), FillReason.CLOSE)

    async def close_all(self) -> list[Fill]:
        fills = []
        for trade_id in list(self._state.trades):
            try:
                fills.append(await self.close_trade(trade_id))
            except BrokerRejectedError as exc:
                log.error("could not close paper trade", trade_id=trade_id, code=exc.code)
        return fills

    # ------------------------------------------------------------------ exits

    def _check_exit_on_tick(self, trade: _OpenTrade, quote: Price) -> Fill | None:
        instrument = self._instruments[trade.instrument]
        exit_price = quote.for_side(trade.side.opposite)
        sign = trade.side.sign
        if (exit_price - trade.stop_loss) * sign <= 0:
            slipped = instrument.round_price(exit_price - self._slippage(instrument) * sign)
            return self._close(trade, trade.units, slipped, FillReason.STOP_LOSS, quote.time)
        if trade.take_profit is not None and (exit_price - trade.take_profit) * sign >= 0:
            return self._close(trade, trade.units, exit_price, FillReason.TAKE_PROFIT, quote.time)
        return None

    def _check_exit_on_bar(self, trade: _OpenTrade, candle: Candle) -> Fill | None:
        instrument = self._instruments[trade.instrument]
        bars = candle.bid if trade.side is Side.BUY else candle.ask
        sign = trade.side.sign
        slip = self._slippage(instrument) * sign
        stop, target, when = trade.stop_loss, trade.take_profit, candle.close_time

        def close_at(price: Decimal, reason: FillReason) -> Fill:
            return self._close(trade, trade.units, instrument.round_price(price), reason, when)

        if trade.open_time >= candle.time:
            # Entry bar: the order of events inside it is unknown; only a close beyond the stop.
            if (bars.close - stop) * sign <= 0:
                return close_at(bars.close - slip, FillReason.STOP_LOSS)
            return None
        worst, best = (bars.low, bars.high) if trade.side is Side.BUY else (bars.high, bars.low)
        if (bars.open - stop) * sign <= 0:
            return close_at(bars.open - slip, FillReason.STOP_LOSS)  # gapped through the stop
        if target is not None and (bars.open - target) * sign >= 0:
            return close_at(bars.open, FillReason.TAKE_PROFIT)  # gapped through the target
        if (worst - stop) * sign <= 0:
            return close_at(stop - slip, FillReason.STOP_LOSS)  # stop wins if both were touched
        if target is not None and (best - target) * sign >= 0:
            return close_at(target, FillReason.TAKE_PROFIT)
        return None

    def _close(
        self,
        trade: _OpenTrade,
        units: Decimal,
        price: Decimal,
        reason: FillReason,
        when: datetime | None = None,
    ) -> Fill:
        instrument = self._instruments[trade.instrument]
        when = when or self._clock.now()
        pl_quote = (price - trade.entry_price) * units * trade.side.sign
        pl = pl_quote * self._quote_to_account(instrument.quote)
        self._state.balance += pl
        trade.units -= units
        trade.realized_pl += pl
        fill_id = self._record(
            "ORDER_FILL",
            {
                "instrument": trade.instrument,
                "units": str(-units * trade.side.sign),
                "price": str(price),
                "reason": _OANDA_STYLE_REASON[reason],
                "tradesClosed" if trade.units == 0 else "tradeReduced": [
                    {
                        "tradeID": trade.id,
                        "units": str(-units * trade.side.sign),
                        "realizedPL": str(pl),
                    }
                ],
            },
            when,
        )
        if trade.units == 0:
            del self._state.trades[trade.id]
        return Fill(
            transaction_id=fill_id,
            time=when,
            instrument=trade.instrument,
            side=trade.side.opposite,
            units=units,
            price=price,
            trade_id=trade.id,
            reason=reason,
            client_id=trade.client_id,
            realized_pl=pl,
        )

    # ------------------------------------------------------------------ helpers

    def _slippage(self, instrument: Instrument) -> Decimal:
        extra = Decimal(0)
        if self._config.random_slippage_pips > 0:
            fraction = Decimal(str(round(self._rng.random(), 6)))
            extra = self._config.random_slippage_pips * fraction
        return (self._config.slippage_pips + extra) * instrument.pip_size

    def _quote_to_account(self, currency: str) -> Decimal:
        account = self._config.account_currency
        if currency == account:
            return Decimal(1)
        prices = self._state.prices
        if (direct := prices.get(f"{currency}_{account}")) is not None:
            return direct.mid
        if (inverse := prices.get(f"{account}_{currency}")) is not None:
            return 1 / inverse.mid
        raise DataIntegrityError(f"no {currency}/{account} quote to convert into {account}")

    def _margin_for(self, instrument: Instrument, units: Decimal, quote: Price) -> Decimal:
        base_value = units * quote.mid * self._quote_to_account(instrument.quote)
        return base_value * instrument.margin_rate

    def _margin(self, trade: _OpenTrade) -> Decimal:
        quote = self._state.prices.get(trade.instrument)
        if quote is None:
            return Decimal(0)
        try:
            return self._margin_for(self._instruments[trade.instrument], trade.units, quote)
        except DataIntegrityError:
            return Decimal(0)

    def _unrealized(self, trade: _OpenTrade) -> Decimal:
        quote = self._state.prices.get(trade.instrument)
        if quote is None:
            return Decimal(0)
        exit_price = quote.for_side(trade.side.opposite)
        pl_quote = (exit_price - trade.entry_price) * trade.units * trade.side.sign
        try:
            return pl_quote * self._quote_to_account(self._instruments[trade.instrument].quote)
        except DataIntegrityError:
            return Decimal(0)

    def _to_trade(self, trade: _OpenTrade) -> Trade:
        return Trade(
            id=trade.id,
            client_id=trade.client_id,
            instrument=trade.instrument,
            side=trade.side,
            units=trade.units,
            initial_units=trade.initial_units,
            entry_price=trade.entry_price,
            open_time=trade.open_time,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit,
            unrealized_pl=self._unrealized(trade),
            realized_pl=trade.realized_pl,
        )

    def _trade(self, trade_id: str) -> _OpenTrade:
        try:
            return self._state.trades[trade_id]
        except KeyError:
            raise BrokerRejectedError(
                "trade not found or already closed", status_code=404, code="TRADE_DOESNT_EXIST"
            ) from None

    def _record(self, kind: str, payload: dict[str, Any], when: datetime | None = None) -> str:
        tx_id = str(self._state.next_id)
        self._state.next_id += 1
        self._state.transactions.append(
            Transaction(id=tx_id, type=kind, time=when or self._clock.now(), payload=payload)
        )
        return tx_id

    def _next_transaction_id(self) -> str:
        return str(self._state.next_id)

    def _last_transaction_id(self) -> str | None:
        transactions = self._state.transactions
        return transactions[-1].id if transactions else None

    def _order_payload(self, order: OrderRequest, units: Decimal) -> dict[str, Any]:
        return {
            "instrument": order.instrument,
            "units": str(units * order.side.sign),
            "priceBound": str(order.price_bound),
            "stopLossOnFill": {"price": str(order.stop_loss)},
            "clientExtensions": {"id": order.client_id, "tag": order.strategy_id},
        }

    def _remember(self, client_id: str, result: OrderResult) -> None:
        if self._config.client_id_support is ClientIdSupport.NATIVE:
            self._state.orders_by_client_id[client_id] = result
        else:
            comment = client_id[: self._config.comment_limit]
            self._state.order_history.append(_OrderRecord(self._config.magic, comment, result))

    def _reject(self, order: OrderRequest, reason: str) -> OrderResult:
        # Rejected orders are not created, so they are not remembered (same as OANDA).
        log.info("paper order rejected", client_id=order.client_id, reason=reason)
        return OrderResult(status=OrderStatus.REJECTED, client_id=order.client_id, reason=reason)

    def _cancel(self, order: OrderRequest, order_id: str, reason: str) -> OrderResult:
        self._record("ORDER_CANCEL", {"orderID": order_id, "reason": reason})
        result = OrderResult(
            status=OrderStatus.CANCELLED,
            client_id=order.client_id,
            broker_order_id=order_id,
            reason=reason,
            last_transaction_id=self._last_transaction_id(),
        )
        self._remember(order.client_id, result)
        log.info("paper order cancelled", client_id=order.client_id, reason=reason)
        return result


_OANDA_STYLE_REASON = {
    FillReason.ENTRY: "MARKET_ORDER",
    FillReason.CLOSE: "MARKET_ORDER_TRADE_CLOSE",
    FillReason.STOP_LOSS: "STOP_LOSS_ORDER",
    FillReason.TAKE_PROFIT: "TAKE_PROFIT_ORDER",
    FillReason.TRAILING_STOP: "TRAILING_STOP_LOSS_ORDER",
    FillReason.POSITION_CLOSEOUT: "MARKET_ORDER_POSITION_CLOSEOUT",
    FillReason.MARGIN_CLOSEOUT: "MARKET_ORDER_MARGIN_CLOSEOUT",
    FillReason.OTHER: "OTHER",
}


def _average_price(trades: Sequence[_OpenTrade]) -> Decimal | None:
    units = sum((t.units for t in trades), Decimal(0))
    if units == 0:
        return None
    return sum((t.entry_price * t.units for t in trades), Decimal(0)) / units
