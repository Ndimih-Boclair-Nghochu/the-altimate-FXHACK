"""OANDA v20 wire format: parsing JSON payloads into domain types and formatting values.

Prices, amounts and units arrive as JSON strings and are parsed straight to ``Decimal``.
Unknown fields are ignored (newer API versions add fields), missing required fields raise
``DataIntegrityError``. Reference: docs/research/02-oanda-v20-api-spec.md.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final, TypeVar

from pydantic import ValidationError

from fxbot.domain.enums import FillReason, Granularity, OrderStatus, Side, TradeState
from fxbot.domain.errors import DataIntegrityError
from fxbot.domain.models import (
    OHLC,
    AccountSummary,
    Candle,
    Fill,
    Financing,
    Instrument,
    OrderResult,
    Position,
    Price,
    Trade,
    Transaction,
)

# Identifiers that would let a log reader or API client correlate us with a person/account.
PRIVATE_FIELDS: Final = frozenset({"accountID", "userID", "requestID", "siteID", "divisionID"})

_RFC3339: Final = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$")

_FILL_REASONS: Final = {
    "MARKET_ORDER": FillReason.ENTRY,
    "MARKET_ORDER_TRADE_CLOSE": FillReason.CLOSE,
    "MARKET_ORDER_POSITION_CLOSEOUT": FillReason.POSITION_CLOSEOUT,
    "MARKET_ORDER_MARGIN_CLOSEOUT": FillReason.MARGIN_CLOSEOUT,
    "STOP_LOSS_ORDER": FillReason.STOP_LOSS,
    "TAKE_PROFIT_ORDER": FillReason.TAKE_PROFIT,
    "TRAILING_STOP_LOSS_ORDER": FillReason.TRAILING_STOP,
}

JsonObject = Mapping[str, Any]
_T = TypeVar("_T")


def parse_decimal(value: Any, field: str = "value") -> Decimal:
    if isinstance(value, bool) or value is None:
        raise DataIntegrityError(f"{field}: expected a decimal, got {type(value).__name__}")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise DataIntegrityError(f"{field}: not a decimal") from None
    if not result.is_finite():
        raise DataIntegrityError(f"{field}: not finite")
    return result


def parse_time(value: Any, field: str = "time") -> datetime:
    """Parse RFC3339 (nanoseconds truncated to microseconds) or UNIX seconds into UTC."""
    if not isinstance(value, str):
        raise DataIntegrityError(f"{field}: expected a timestamp string")
    match = _RFC3339.match(value)
    if match:
        whole, fraction = match.groups()
        micros = int((fraction or "0")[:6].ljust(6, "0"))
        return datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(microsecond=micros, tzinfo=UTC)
    seconds = parse_decimal(value, field)
    whole_seconds = int(seconds)
    micros = int((seconds - whole_seconds) * 1_000_000)
    return datetime.fromtimestamp(whole_seconds, tz=UTC).replace(microsecond=micros)


def format_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def format_decimal(value: Decimal, places: int) -> str:
    """Fixed-point string with exactly ``places`` decimals (never exponent notation)."""
    return f"{value:.{places}f}"


def _get(obj: JsonObject, key: str, context: str) -> Any:
    try:
        return obj[key]
    except (KeyError, TypeError):
        raise DataIntegrityError(f"{context}: missing field {key!r}") from None


def _id(value: Any) -> str:
    # IDs are strings of digits, but some payloads carry integers.
    return str(value)


def strip_private(payload: Any) -> Any:
    """Copy of ``payload`` without account/user/request identifiers, recursively."""
    if isinstance(payload, Mapping):
        return {k: strip_private(v) for k, v in payload.items() if k not in PRIVATE_FIELDS}
    if isinstance(payload, list):
        return [strip_private(item) for item in payload]
    return payload


def _validated(factory: type[_T], context: str, **fields: Any) -> _T:
    try:
        return factory(**fields)
    except ValidationError as exc:
        raise DataIntegrityError(f"{context}: {exc.errors(include_input=False)}") from None


def parse_instrument(obj: JsonObject) -> Instrument:
    max_units = obj.get("maximumOrderUnits")
    step = Decimal(1).scaleb(-int(obj.get("tradeUnitsPrecision", 0)))
    min_units = parse_decimal(obj.get("minimumTradeSize", "1"), "minimumTradeSize")
    return _validated(
        Instrument,
        "instrument",
        name=_get(obj, "name", "instrument"),
        pip_location=int(_get(obj, "pipLocation", "instrument")),
        display_precision=int(_get(obj, "displayPrecision", "instrument")),
        units_step=step,
        min_units=max(min_units, step),
        max_units=parse_decimal(max_units, "maximumOrderUnits") if max_units else None,
        margin_rate=parse_decimal(_get(obj, "marginRate", "instrument"), "marginRate"),
        financing=_financing(obj.get("financing")),
    )


_WEEKDAYS: Final = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


def _financing(obj: Any) -> Financing | None:
    if not isinstance(obj, Mapping):
        return None
    charged = {
        str(day.get("dayOfWeek")): int(day.get("daysCharged", 0))
        for day in obj.get("financingDaysOfWeek") or []
        if isinstance(day, Mapping)
    }
    days = tuple(
        charged.get(name, 1 if name not in ("SATURDAY", "SUNDAY") else 0) for name in _WEEKDAYS
    )
    return _validated(
        Financing,
        "instrument.financing",
        long_rate=parse_decimal(obj.get("longRate", "0"), "financing.longRate"),
        short_rate=parse_decimal(obj.get("shortRate", "0"), "financing.shortRate"),
        days_charged=days,
    )


def _ohlc(obj: JsonObject, context: str) -> OHLC:
    return _validated(
        OHLC,
        context,
        open=parse_decimal(_get(obj, "o", context), f"{context}.o"),
        high=parse_decimal(_get(obj, "h", context), f"{context}.h"),
        low=parse_decimal(_get(obj, "l", context), f"{context}.l"),
        close=parse_decimal(_get(obj, "c", context), f"{context}.c"),
    )


def parse_candle(obj: JsonObject, instrument: str, granularity: Granularity) -> Candle:
    """Parse a ``price=BA`` candlestick. The request's instrument is the source of truth."""
    if "bid" not in obj or "ask" not in obj:
        raise DataIntegrityError("candle: bid and ask prices are required (request price=BA)")
    return _validated(
        Candle,
        "candle",
        instrument=instrument,
        granularity=granularity,
        time=parse_time(_get(obj, "time", "candle")),
        bid=_ohlc(obj["bid"], "candle.bid"),
        ask=_ohlc(obj["ask"], "candle.ask"),
        volume=int(obj.get("volume", 0)),
        complete=bool(obj.get("complete", False)),
    )


def parse_price(obj: JsonObject) -> Price | None:
    """Top of book from a ``ClientPrice``. ``None`` when a side of the book is empty."""
    bids, asks = obj.get("bids") or [], obj.get("asks") or []
    if not bids or not asks:
        return None
    tradeable = obj.get("tradeable")
    if not isinstance(tradeable, bool):
        tradeable = obj.get("status") == "tradeable"
    return _validated(
        Price,
        "price",
        instrument=_get(obj, "instrument", "price"),
        time=parse_time(_get(obj, "time", "price")),
        bid=parse_decimal(_get(bids[0], "price", "price.bids"), "bid"),
        ask=parse_decimal(_get(asks[0], "price", "price.asks"), "ask"),
        tradeable=tradeable,
    )


def parse_account(obj: JsonObject, masked_id: str) -> AccountSummary:
    return _validated(
        AccountSummary,
        "account",
        masked_id=masked_id,
        currency=_get(obj, "currency", "account"),
        balance=parse_decimal(_get(obj, "balance", "account"), "balance"),
        nav=parse_decimal(_get(obj, "NAV", "account"), "NAV"),
        unrealized_pl=parse_decimal(obj.get("unrealizedPL", "0"), "unrealizedPL"),
        margin_used=parse_decimal(obj.get("marginUsed", "0"), "marginUsed"),
        margin_available=parse_decimal(obj.get("marginAvailable", "0"), "marginAvailable"),
        margin_closeout_percent=parse_decimal(
            obj.get("marginCloseoutPercent", "0"), "marginCloseoutPercent"
        ),
        open_trade_count=int(obj.get("openTradeCount", 0)),
        open_position_count=int(obj.get("openPositionCount", 0)),
        hedging_enabled=bool(obj.get("hedgingEnabled", False)),
        last_transaction_id=_id(obj["lastTransactionID"]) if "lastTransactionID" in obj else None,
    )


def _side_and_units(signed_units: Decimal) -> tuple[Side, Decimal]:
    return (Side.BUY if signed_units > 0 else Side.SELL), abs(signed_units)


def parse_trade(obj: JsonObject) -> Trade:
    current = parse_decimal(_get(obj, "currentUnits", "trade"), "currentUnits")
    initial = parse_decimal(obj.get("initialUnits", current), "initialUnits")
    side, units = _side_and_units(current if current != 0 else initial)
    stop, target = obj.get("stopLossOrder"), obj.get("takeProfitOrder")
    state = TradeState.OPEN if obj.get("state", "OPEN") == "OPEN" else TradeState.CLOSED
    return _validated(
        Trade,
        "trade",
        id=_id(_get(obj, "id", "trade")),
        client_id=(obj.get("clientExtensions") or {}).get("id"),
        instrument=_get(obj, "instrument", "trade"),
        side=side,
        units=units,
        initial_units=abs(initial),
        entry_price=parse_decimal(_get(obj, "price", "trade"), "price"),
        open_time=parse_time(_get(obj, "openTime", "trade"), "openTime"),
        stop_loss=parse_decimal(stop["price"], "stopLossOrder.price") if stop else None,
        take_profit=parse_decimal(target["price"], "takeProfitOrder.price") if target else None,
        unrealized_pl=parse_decimal(obj.get("unrealizedPL", "0"), "unrealizedPL"),
        realized_pl=parse_decimal(obj.get("realizedPL", "0"), "realizedPL"),
        financing=parse_decimal(obj.get("financing", "0"), "financing"),
        state=state,
    )


def trade_has_stop_loss(obj: JsonObject) -> bool:
    return bool(obj.get("stopLossOrder") or obj.get("guaranteedStopLossOrder"))


def parse_position(obj: JsonObject) -> Position:
    long, short = obj.get("long") or {}, obj.get("short") or {}
    long_units = abs(parse_decimal(long.get("units", "0"), "long.units"))
    short_units = abs(parse_decimal(short.get("units", "0"), "short.units"))
    long_avg, short_avg = long.get("averagePrice"), short.get("averagePrice")
    return _validated(
        Position,
        "position",
        instrument=_get(obj, "instrument", "position"),
        long_units=long_units,
        short_units=short_units,
        long_average_price=parse_decimal(long_avg, "long.averagePrice") if long_avg else None,
        short_average_price=parse_decimal(short_avg, "short.averagePrice") if short_avg else None,
        unrealized_pl=parse_decimal(obj.get("unrealizedPL", "0"), "unrealizedPL"),
    )


def parse_transaction(obj: JsonObject) -> Transaction:
    return _validated(
        Transaction,
        "transaction",
        id=_id(_get(obj, "id", "transaction")),
        type=str(_get(obj, "type", "transaction")),
        time=parse_time(_get(obj, "time", "transaction")),
        payload=strip_private(obj),
    )


def fill_reason(oanda_reason: Any) -> FillReason:
    return _FILL_REASONS.get(str(oanda_reason), FillReason.OTHER)


def fills_from_transaction(
    tx: JsonObject, client_id: str | None = None
) -> tuple[Fill | None, list[Fill]]:
    """Split an ``ORDER_FILL`` transaction into the trade it opened and the trades it closed."""
    context = "orderFillTransaction"
    tx_id = _id(_get(tx, "id", context))
    time = parse_time(_get(tx, "time", context))
    instrument = _get(tx, "instrument", context)
    reason = fill_reason(tx.get("reason"))
    fallback_price = tx.get("price")

    def build(part: JsonObject, *, opening: bool, commission: Decimal) -> Fill:
        side, units = _side_and_units(parse_decimal(_get(part, "units", context), "units"))
        price = part.get("price", fallback_price)
        return _validated(
            Fill,
            context,
            transaction_id=tx_id,
            time=time,
            instrument=instrument,
            side=side,
            units=units,
            price=parse_decimal(price, "price"),
            trade_id=_id(_get(part, "tradeID", context)),
            reason=FillReason.ENTRY if opening else reason,
            client_id=client_id,
            realized_pl=Decimal(0) if opening else parse_decimal(part.get("realizedPL", "0")),
            financing=parse_decimal(part.get("financing", "0"), "financing"),
            commission=commission,
            half_spread_cost=(
                parse_decimal(part["halfSpreadCost"], "halfSpreadCost")
                if "halfSpreadCost" in part
                else None
            ),
        )

    opened = tx.get("tradeOpened")
    closed_parts = list(tx.get("tradesClosed") or [])
    if tx.get("tradeReduced"):
        closed_parts.append(tx["tradeReduced"])
    # The transaction's commission is booked once: on the opened trade, else the first close.
    commission = parse_decimal(tx.get("commission", "0"), "commission")
    opened_fill = build(opened, opening=True, commission=commission) if opened else None
    closed_fills = [
        build(part, opening=False, commission=commission if i == 0 and not opened else Decimal(0))
        for i, part in enumerate(closed_parts)
    ]
    return opened_fill, closed_fills


def order_result(body: JsonObject, client_id: str) -> OrderResult:
    """Map a 201 order-create response (filled, cancelled or still pending)."""
    create = body.get("orderCreateTransaction") or {}
    common: dict[str, Any] = {
        "client_id": client_id,
        "broker_order_id": _id(create["id"]) if "id" in create else None,
        "last_transaction_id": (
            _id(body["lastTransactionID"]) if "lastTransactionID" in body else None
        ),
    }
    if fill_tx := body.get("orderFillTransaction"):
        opened, closed = fills_from_transaction(fill_tx, client_id)
        return _validated(
            OrderResult,
            "order",
            status=OrderStatus.FILLED,
            fill=opened,
            closed=tuple(closed),
            **common,
        )
    if cancel := body.get("orderCancelTransaction"):
        return _validated(
            OrderResult,
            "order",
            status=OrderStatus.CANCELLED,
            reason=str(cancel.get("reason", "CANCELLED")),
            **common,
        )
    return _validated(OrderResult, "order", status=OrderStatus.SUBMITTED, **common)


def reject_code(body: JsonObject | None) -> str | None:
    """Machine-readable reason from a 4xx body (``rejectReason`` or ``errorCode``)."""
    if not body:
        return None
    for value in body.values():
        if isinstance(value, Mapping) and "rejectReason" in value:
            return str(value["rejectReason"])
    code = body.get("errorCode")
    return str(code) if code else None
