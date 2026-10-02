"""``OandaBroker``: the ``Broker`` protocol on top of OANDA v20.

Order rules (docs/SECURITY.md SR-14, SR-17):

- Market orders only, ``FOK``, with ``priceBound``, ``stopLossOnFill`` and the client id as
  both ``clientExtensions.id`` and ``tradeClientExtensions.id``.
- Prices are quantized to the instrument's precision and units rounded down to its step.
- ``submit_order`` first looks the client id up, so a resubmission returns the original
  outcome instead of a second order. The POST itself is sent once; after a timeout or 5xx the
  order is looked up again, and if that is inconclusive the result is ``UNKNOWN``.
- After every fill the trade is re-read; a trade without a broker-side stop gets one, or is
  closed if that fails.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from fxbot.brokers.base import BrokerCapabilities, ClientIdSupport
from fxbot.brokers.oanda.client import JsonDict, OandaClient
from fxbot.brokers.oanda.wire import (
    fills_from_transaction,
    format_decimal,
    order_result,
    parse_account,
    parse_instrument,
    parse_position,
    parse_price,
    parse_trade,
    parse_transaction,
    trade_has_stop_loss,
)
from fxbot.domain.enums import OrderStatus, PositionAccounting
from fxbot.domain.errors import (
    BrokerError,
    BrokerRejectedError,
    BrokerUnavailableError,
    ConfigurationError,
    RateLimitedError,
)
from fxbot.domain.masking import mask_account_id
from fxbot.domain.models import (
    AccountSummary,
    Fill,
    Instrument,
    OrderRequest,
    OrderResult,
    Position,
    Price,
    Trade,
    TransactionPage,
)
from fxbot.logging import get_logger

log = get_logger(__name__)

_COMMENT_LIMIT = 120


class OandaBroker:
    def __init__(self, client: OandaClient) -> None:
        self._client = client
        self._instruments: dict[str, Instrument] = {}
        self._hedging = False
        self._masked_id = "***"

    @property
    def name(self) -> str:
        return f"oanda-{self._client.environment.value}"

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            position_accounting=PositionAccounting.PER_TRADE,
            supports_hedging=self._hedging,
            fifo_required=False,
            supports_sl_on_fill=True,
            supports_tp_on_fill=True,
            supports_trailing_stop=True,
            supports_guaranteed_stop=False,
            client_id_support=ClientIdSupport.NATIVE,
            supports_price_streaming=True,
            supports_transaction_streaming=True,
            candle_price_sides=frozenset({"B", "A", "M"}),
            max_orders_per_second=20.0,
        )

    def __repr__(self) -> str:
        return f"OandaBroker(client={self._client!r})"

    # ------------------------------------------------------------------ lifecycle

    async def connect(self) -> None:
        """Refuse to run unless the token can see the configured account (SR-7)."""
        body = await self._client.list_accounts()
        listed = [a for a in body.get("accounts") or [] if isinstance(a, dict)]
        account = next(
            (a for a in listed if self._client.is_configured_account(str(a.get("id", "")))), None
        )
        if account is None:
            raise ConfigurationError("the configured OANDA account is not available to this token")
        if account.get("mt4AccountID"):
            raise ConfigurationError("MT4-linked OANDA accounts are not supported")
        self._masked_id = mask_account_id(str(account["id"]))
        summary = await self.get_account()
        await self.get_instruments()
        log.info(
            "connected to oanda",
            environment=self._client.environment.value,
            account=summary.masked_id,
            currency=summary.currency,
            nav=str(summary.nav),
            hedging=self._hedging,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ reads

    async def get_account(self) -> AccountSummary:
        body = await self._client.account_summary()
        summary = parse_account(body.get("account") or {}, self._masked_id)
        self._hedging = summary.hedging_enabled
        return summary

    async def get_instruments(self, names: Sequence[str] | None = None) -> list[Instrument]:
        body = await self._client.account_instruments(names)
        instruments = [parse_instrument(item) for item in body.get("instruments") or []]
        self._instruments.update({i.name: i for i in instruments})
        return instruments

    async def _instrument(self, name: str) -> Instrument:
        if name not in self._instruments:
            await self.get_instruments([name])
        try:
            return self._instruments[name]
        except KeyError:
            raise BrokerRejectedError(
                f"instrument {name} is not tradeable on this account"
            ) from None

    async def get_prices(self, instruments: Sequence[str]) -> list[Price]:
        body = await self._client.pricing(instruments)
        prices = [parse_price(item) for item in body.get("prices") or []]
        return [price for price in prices if price is not None]

    async def get_open_trades(self) -> list[Trade]:
        body = await self._client.open_trades()
        return [parse_trade(item) for item in body.get("trades") or []]

    async def get_positions(self) -> list[Position]:
        body = await self._client.open_positions()
        return [parse_position(item) for item in body.get("positions") or []]

    async def get_transactions_since(self, last_id: str | None) -> TransactionPage:
        if last_id is None:
            summary = await self.get_account()
            return TransactionPage(items=(), last_id=summary.last_transaction_id)
        body = await self._client.transactions_since(last_id)
        items = tuple(parse_transaction(item) for item in body.get("transactions") or [])
        new_last = body.get("lastTransactionID")
        return TransactionPage(items=items, last_id=str(new_last) if new_last else last_id)

    # ------------------------------------------------------------------ orders

    async def find_order(self, client_id: str) -> OrderResult | None:
        try:
            body = await self._client.get_order(f"@{client_id}")
        except BrokerRejectedError as exc:
            if exc.status_code == 404:
                return None
            raise
        order = body.get("order") or {}
        state = order.get("state")
        broker_order_id = str(order["id"]) if "id" in order else None
        if state == "FILLED" and order.get("fillingTransactionID"):
            tx = await self._client.get_transaction(str(order["fillingTransactionID"]))
            opened, closed = fills_from_transaction(tx.get("transaction") or {}, client_id)
            return OrderResult(
                status=OrderStatus.FILLED,
                client_id=client_id,
                broker_order_id=broker_order_id,
                fill=opened,
                closed=tuple(closed),
            )
        if state == "CANCELLED":
            reason = "CANCELLED"
            if order.get("cancellingTransactionID"):
                tx = await self._client.get_transaction(str(order["cancellingTransactionID"]))
                reason = str((tx.get("transaction") or {}).get("reason", reason))
            return OrderResult(
                status=OrderStatus.CANCELLED,
                client_id=client_id,
                broker_order_id=broker_order_id,
                reason=reason,
            )
        return OrderResult(
            status=OrderStatus.SUBMITTED, client_id=client_id, broker_order_id=broker_order_id
        )

    def _order_body(self, order: OrderRequest, instrument: Instrument) -> JsonDict:
        places = instrument.display_precision

        def price(value: Decimal) -> str:
            return format_decimal(instrument.round_price(value), places)

        units = instrument.round_units(order.units) * order.side.sign
        body: JsonDict = {
            "type": "MARKET",
            "instrument": order.instrument,
            "units": format_decimal(units, instrument.units_places),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "priceBound": price(order.price_bound),
            "stopLossOnFill": {"price": price(order.stop_loss), "timeInForce": "GTC"},
            "clientExtensions": {
                "id": order.client_id,
                "tag": order.strategy_id,
                "comment": f"signal={order.signal_id}"[:_COMMENT_LIMIT],
            },
            "tradeClientExtensions": {"id": order.client_id, "tag": order.strategy_id},
        }
        if order.take_profit is not None:
            body["takeProfitOnFill"] = {"price": price(order.take_profit), "timeInForce": "GTC"}
        return {"order": body}

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        instrument = await self._instrument(order.instrument)
        existing = await self.find_order(order.client_id)
        if existing is not None:
            log.info("order already known to the broker; not resending", client_id=order.client_id)
            return existing
        problem = instrument.size_problem(instrument.round_units(order.units))
        if problem:
            return OrderResult(
                status=OrderStatus.REJECTED, client_id=order.client_id, reason=problem
            )
        try:
            body = await self._client.create_order(self._order_body(order, instrument))
        except RateLimitedError:
            raise  # rejected before processing; nothing was created
        except BrokerUnavailableError:
            log.warning("order outcome unknown; looking it up", client_id=order.client_id)
            return await self._resolve_unknown(order.client_id)
        except BrokerRejectedError as exc:
            if exc.status_code in (401, 403):
                raise
            log.warning("order rejected", client_id=order.client_id, code=exc.code)
            return OrderResult(
                status=OrderStatus.REJECTED,
                client_id=order.client_id,
                reason=exc.code or f"HTTP {exc.status_code}",
            )
        result = order_result(body, order.client_id)
        if result.status is OrderStatus.CANCELLED:
            log.warning("order cancelled", client_id=order.client_id, reason=result.reason)
        if result.closed:
            log.error(
                "entry order reduced existing trades",
                client_id=order.client_id,
                trades=[f.trade_id for f in result.closed],
            )
        if result.fill is not None:
            await self._ensure_stop(result.fill.trade_id, order, instrument)
        return result

    async def _resolve_unknown(self, client_id: str) -> OrderResult:
        try:
            found = await self.find_order(client_id)
        except BrokerError:
            found = None
        return found or OrderResult(
            status=OrderStatus.UNKNOWN,
            client_id=client_id,
            reason="submit outcome unknown; resolve by client id before resubmitting",
        )

    async def _ensure_stop(
        self, trade_id: str, order: OrderRequest, instrument: Instrument
    ) -> None:
        """Fail-safe: every open trade must carry a broker-side stop."""
        try:
            trade = (await self._client.get_trade(trade_id)).get("trade") or {}
        except BrokerError as exc:
            log.warning("could not verify stop after fill", trade_id=trade_id, error=str(exc))
            return
        if trade.get("state", "OPEN") != "OPEN" or trade_has_stop_loss(trade):
            return
        log.error("filled trade has no stop; attaching one", trade_id=trade_id)
        try:
            await self.modify_trade_exits(trade_id, stop_loss=order.stop_loss)
        except BrokerError:
            log.critical("could not attach a stop; closing the trade", trade_id=trade_id)
            await self.close_trade(trade_id)

    async def modify_trade_exits(
        self,
        trade_id: str,
        *,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> None:
        if stop_loss is None and take_profit is None:
            return
        trade = parse_trade((await self._client.get_trade(trade_id)).get("trade") or {})
        instrument = await self._instrument(trade.instrument)
        places = instrument.display_precision
        body: JsonDict = {}
        if stop_loss is not None:
            stop = format_decimal(instrument.round_price(stop_loss), places)
            body["stopLoss"] = {"price": stop, "timeInForce": "GTC"}
        if take_profit is not None:
            target = format_decimal(instrument.round_price(take_profit), places)
            body["takeProfit"] = {"price": target, "timeInForce": "GTC"}
        response = await self._client.set_trade_orders(trade_id, body)
        rejected = [k for k in response if k.endswith("RejectTransaction")]
        if rejected:
            raise BrokerRejectedError(f"exit change rejected ({', '.join(sorted(rejected))})")
        if "stopLossOrderFillTransaction" in response:
            log.warning("new stop filled immediately; trade closed", trade_id=trade_id)

    async def close_trade(self, trade_id: str, units: Decimal | None = None) -> Fill:
        body: JsonDict = {"units": "ALL"}
        if units is not None:
            trade = parse_trade((await self._client.get_trade(trade_id)).get("trade") or {})
            instrument = await self._instrument(trade.instrument)
            body["units"] = format_decimal(instrument.round_units(units), instrument.units_places)
        response = await self._client.close_trade(trade_id, body)
        return _closing_fill(response, trade_id)

    async def close_all(self) -> list[Fill]:
        fills: list[Fill] = []
        for position in await self.get_positions():
            body: JsonDict = {}
            if position.long_units > 0:
                body["longUnits"] = "ALL"
            if position.short_units > 0:
                body["shortUnits"] = "ALL"
            if not body:
                continue
            try:
                response = await self._client.close_position(position.instrument, body)
            except BrokerError as exc:
                log.error(
                    "could not close position", instrument=position.instrument, error=str(exc)
                )
                continue
            for side in ("long", "short"):
                if fill_tx := response.get(f"{side}OrderFillTransaction"):
                    fills.extend(fills_from_transaction(fill_tx)[1])
                if cancel := response.get(f"{side}OrderCancelTransaction"):
                    log.error(
                        "position close cancelled",
                        instrument=position.instrument,
                        reason=str(cancel.get("reason")),
                    )
        return fills


def _closing_fill(response: dict[str, Any], trade_id: str) -> Fill:
    if fill_tx := response.get("orderFillTransaction"):
        for fill in fills_from_transaction(fill_tx)[1]:
            if fill.trade_id == trade_id:
                return fill
        raise BrokerRejectedError("close filled but did not reference the trade")
    cancel = response.get("orderCancelTransaction") or {}
    reason = str(cancel.get("reason", "CANCELLED"))
    raise BrokerRejectedError(f"trade close cancelled ({reason})", code=reason)
