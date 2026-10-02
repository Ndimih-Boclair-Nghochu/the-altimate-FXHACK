"""Core value types. Money and prices are ``Decimal``, never ``float``; times are tz-aware UTC.

Every numeric field rejects NaN and infinity (``nan > limit`` is always false, so a NaN would
slip past "reject if above the limit" checks downstream), and floats are refused outright so
binary rounding cannot leak into prices. Models are immutable.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import Annotated, Any, Final, Literal, Self

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from fxbot.domain.calendar import bar_close_time, ensure_utc
from fxbot.domain.enums import AskSource, FillReason, Granularity, OrderStatus, Side, TradeState

INSTRUMENT_PATTERN: Final = r"^[A-Z]{3}_[A-Z]{3}$"
CURRENCY_PATTERN: Final = r"^[A-Z]{3}$"
# Our orders' idempotency key. Sent as OANDA clientExtensions.id (max 32 characters) or in the
# MT5 order comment (about 31), so short ASCII. The prefix marks trades this system opened.
CLIENT_ID_PREFIX: Final = "afx-"
CLIENT_ID_PATTERN: Final = r"^afx-[A-Za-z0-9_-]{1,27}$"
LABEL_PATTERN: Final = r"^[A-Za-z0-9_.:-]{1,64}$"
BROKER_ID_PATTERN: Final = r"^[0-9]{1,20}$"

_TWO: Final = Decimal(2)


def _reject_float(value: Any) -> Any:
    if isinstance(value, float | bool):
        raise ValueError(f"{type(value).__name__} is not accepted here; use Decimal, int or str")
    return value


def _require_finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("value must be finite")
    return value


Dec = Annotated[Decimal, BeforeValidator(_reject_float), AfterValidator(_require_finite)]
PositiveDec = Annotated[Dec, Field(gt=0)]
NonNegativeDec = Annotated[Dec, Field(ge=0)]
UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc)]
InstrumentName = Annotated[str, Field(pattern=INSTRUMENT_PATTERN)]
BrokerId = Annotated[str, Field(pattern=BROKER_ID_PATTERN)]


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


def make_client_id(*parts: str) -> str:
    """Deterministic client id for an order, e.g. ``make_client_id(signal_id, str(attempt))``."""
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
    return f"{CLIENT_ID_PREFIX}{digest[:24]}"


class Financing(DomainModel):
    """Overnight financing, as published by the broker."""

    long_rate: Dec  # annualised rate for long positions, e.g. -0.0153
    short_rate: Dec
    # Days charged when a position is held over the 17:00 New York rollover, Monday..Sunday.
    days_charged: tuple[int, int, int, int, int, int, int] = (1, 1, 1, 1, 1, 0, 0)


class Instrument(DomainModel):
    """Trading specification of one instrument, under its canonical name (``EUR_USD``).

    Sizes are always in units of the base currency. Brokers that trade lots (MT5) describe
    them with ``contract_size`` (units per lot) and express their volume step and limits in
    units here, so every adapter rounds and validates the same way.
    """

    name: InstrumentName
    pip_location: int = Field(ge=-10, le=10)
    display_precision: int = Field(ge=0, le=10)  # price decimals (MT5 ``digits``)
    units_step: PositiveDec = Decimal(1)
    min_units: PositiveDec = Decimal(1)
    max_units: PositiveDec | None = None
    contract_size: PositiveDec = Decimal(1)  # units per broker lot; 1 = broker trades units
    min_stop_distance: NonNegativeDec = Decimal(0)  # price units (MT5 ``trade_stops_level``)
    margin_rate: Annotated[Dec, Field(gt=0, le=1)]
    financing: Financing | None = None

    @property
    def base(self) -> str:
        return self.name[:3]

    @property
    def quote(self) -> str:
        return self.name[4:]

    @property
    def pip_size(self) -> Decimal:
        return Decimal(1).scaleb(self.pip_location)

    @property
    def tick_size(self) -> Decimal:
        return Decimal(1).scaleb(-self.display_precision)

    def round_price(self, price: Decimal, rounding: str = ROUND_HALF_EVEN) -> Decimal:
        """Quantize to the broker's price precision (too many decimals get the order rejected)."""
        return price.quantize(self.tick_size, rounding=rounding)

    @property
    def units_places(self) -> int:
        """Decimals needed to write a multiple of ``units_step``."""
        exponent = self.units_step.normalize().as_tuple().exponent
        return max(0, -exponent) if isinstance(exponent, int) else 0

    def round_units(self, units: Decimal) -> Decimal:
        """Round toward zero to a multiple of ``units_step``, so an order is never oversized."""
        steps = (units / self.units_step).to_integral_value(rounding=ROUND_DOWN)
        return (steps * self.units_step).quantize(Decimal(1).scaleb(-self.units_places))

    def size_problem(self, units: Decimal) -> str | None:
        """Why ``units`` cannot be sent as is, or ``None`` if it can."""
        if not units.is_finite() or units <= 0:
            return "units must be a positive finite number"
        if units < self.min_units:
            return f"units below the instrument minimum ({self.min_units})"
        if self.max_units is not None and units > self.max_units:
            return f"units above the instrument maximum ({self.max_units})"
        if self.round_units(units) != units:
            return f"units are not a multiple of the step ({self.units_step})"
        return None

    def to_lots(self, units: Decimal) -> Decimal:
        return units / self.contract_size

    def from_lots(self, lots: Decimal) -> Decimal:
        return lots * self.contract_size

    def stop_distance_problem(self, reference: Decimal, stop: Decimal) -> str | None:
        """Why a stop or target at ``stop`` is too close to ``reference``, if it is."""
        if abs(reference - stop) < self.min_stop_distance:
            return f"stop distance below the broker minimum ({self.min_stop_distance})"
        return None

    def to_pips(self, distance: Decimal) -> Decimal:
        return distance / self.pip_size


class OHLC(DomainModel):
    open: PositiveDec
    high: PositiveDec
    low: PositiveDec
    close: PositiveDec

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("inconsistent OHLC: high/low must bracket open and close")
        return self


class Candle(DomainModel):
    """One bar with bid and ask OHLC. ``time`` is the bar's open time.

    Long stops and targets trigger on the bid, short ones on the ask; keep both sides so
    simulations pay the spread where a real fill would.
    """

    instrument: InstrumentName
    granularity: Granularity
    time: UtcDatetime
    bid: OHLC
    ask: OHLC
    volume: int = Field(default=0, ge=0)  # tick volume
    complete: bool = True
    ask_source: AskSource = AskSource.QUOTED

    @classmethod
    def from_bid_and_spread(
        cls,
        *,
        instrument: str,
        granularity: Granularity,
        time: datetime,
        bid: OHLC,
        spread: Decimal,
        volume: int = 0,
        complete: bool = True,
        ask_source: AskSource = AskSource.BAR_SPREAD,
    ) -> Candle:
        """Build a candle from bid OHLC plus one spread (price units) applied to every point.

        For sources that only report bid bars, e.g. MT5 rates (``spread`` in points times the
        symbol's point size) or bid-only datasets with a modelled spread.
        """
        if not spread.is_finite() or spread < 0:
            raise ValueError("spread must be a non-negative finite number")
        ask = OHLC(
            open=bid.open + spread,
            high=bid.high + spread,
            low=bid.low + spread,
            close=bid.close + spread,
        )
        return cls(
            instrument=instrument,
            granularity=granularity,
            time=time,
            bid=bid,
            ask=ask,
            volume=volume,
            complete=complete,
            ask_source=ask_source,
        )

    @model_validator(mode="after")
    def _check_spread(self) -> Self:
        bid, ask = self.bid, self.ask
        if ask.open < bid.open or ask.close < bid.close or ask.high < bid.high or ask.low < bid.low:
            raise ValueError("crossed candle: ask prices must not be below bid prices")
        return self

    @property
    def mid(self) -> OHLC:
        bid, ask = self.bid, self.ask
        return OHLC.model_construct(
            open=(bid.open + ask.open) / _TWO,
            high=(bid.high + ask.high) / _TWO,
            low=(bid.low + ask.low) / _TWO,
            close=(bid.close + ask.close) / _TWO,
        )

    @property
    def spread_open(self) -> Decimal:
        return self.ask.open - self.bid.open

    @property
    def spread_close(self) -> Decimal:
        return self.ask.close - self.bid.close

    @property
    def close_time(self) -> datetime:
        return bar_close_time(self.time, self.granularity)


class Price(DomainModel):
    """Top-of-book quote."""

    instrument: InstrumentName
    time: UtcDatetime
    bid: PositiveDec
    ask: PositiveDec
    tradeable: bool = True

    @model_validator(mode="after")
    def _check_spread(self) -> Self:
        if self.ask < self.bid:
            raise ValueError("crossed quote: ask below bid")
        return self

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / _TWO

    def for_side(self, side: Side) -> Decimal:
        """Price a market order on ``side`` would fill at: ask to buy, bid to sell."""
        return self.ask if side is Side.BUY else self.bid


class OrderRequest(DomainModel):
    """A market order with a mandatory broker-side stop and a worst acceptable fill price."""

    client_id: str = Field(pattern=CLIENT_ID_PATTERN)
    instrument: InstrumentName
    side: Side
    units: PositiveDec
    stop_loss: PositiveDec
    take_profit: PositiveDec | None = None
    price_bound: PositiveDec
    strategy_id: str = Field(pattern=LABEL_PATTERN)
    signal_id: str = Field(pattern=LABEL_PATTERN)

    @model_validator(mode="after")
    def _check_levels(self) -> Self:
        sign = self.side.sign
        # The stop must be on the losing side of any acceptable fill (≤ price_bound for a buy).
        if (self.price_bound - self.stop_loss) * sign <= 0:
            raise ValueError("stop_loss is on the wrong side of price_bound for this side")
        if self.take_profit is not None and (self.take_profit - self.stop_loss) * sign <= 0:
            raise ValueError("take_profit is on the wrong side of stop_loss for this side")
        return self


class Fill(DomainModel):
    """A fill against one trade. ``side`` is the fill's direction: closing a long is a SELL."""

    transaction_id: BrokerId
    time: UtcDatetime
    instrument: InstrumentName
    side: Side
    units: PositiveDec
    price: PositiveDec
    trade_id: BrokerId
    reason: FillReason
    client_id: str | None = None
    realized_pl: Dec = Decimal(0)
    financing: Dec = Decimal(0)
    commission: Dec = Decimal(0)
    half_spread_cost: Dec | None = None


class OrderResult(DomainModel):
    status: OrderStatus
    client_id: str = Field(pattern=CLIENT_ID_PATTERN)
    broker_order_id: BrokerId | None = None
    fill: Fill | None = None
    # Trades this order reduced or closed instead of opening (should never happen for entries).
    closed: tuple[Fill, ...] = ()
    reason: str | None = None
    last_transaction_id: BrokerId | None = None

    @model_validator(mode="after")
    def _check_fill(self) -> Self:
        if self.status is OrderStatus.FILLED and self.fill is None and not self.closed:
            raise ValueError("a filled order needs a fill")
        if self.status is not OrderStatus.FILLED and (self.fill is not None or self.closed):
            raise ValueError("only filled orders carry fills")
        return self


class Trade(DomainModel):
    id: BrokerId
    client_id: str | None = None  # whatever the broker holds; only ours carry the prefix
    instrument: InstrumentName
    side: Side
    units: PositiveDec
    initial_units: PositiveDec
    entry_price: PositiveDec
    open_time: UtcDatetime
    stop_loss: PositiveDec | None = None
    take_profit: PositiveDec | None = None
    unrealized_pl: Dec = Decimal(0)
    realized_pl: Dec = Decimal(0)
    financing: Dec = Decimal(0)
    state: TradeState = TradeState.OPEN

    @property
    def is_ours(self) -> bool:
        return bool(self.client_id and self.client_id.startswith(CLIENT_ID_PREFIX))


class Position(DomainModel):
    instrument: InstrumentName
    long_units: NonNegativeDec = Decimal(0)
    short_units: NonNegativeDec = Decimal(0)
    long_average_price: PositiveDec | None = None
    short_average_price: PositiveDec | None = None
    unrealized_pl: Dec = Decimal(0)

    @property
    def net_units(self) -> Decimal:
        return self.long_units - self.short_units


class AccountSummary(DomainModel):
    masked_id: str
    currency: str = Field(pattern=CURRENCY_PATTERN)
    balance: Dec
    nav: Dec
    unrealized_pl: Dec
    margin_used: NonNegativeDec
    margin_available: Dec
    margin_closeout_percent: NonNegativeDec = Decimal(0)
    open_trade_count: int = Field(ge=0)
    open_position_count: int = Field(ge=0)
    hedging_enabled: bool = False
    last_transaction_id: BrokerId | None = None


class Transaction(DomainModel):
    """A broker transaction. ``payload`` is the broker's record without account/user ids."""

    id: BrokerId
    type: str
    time: UtcDatetime
    payload: dict[str, Any] = Field(default_factory=dict)


class TransactionPage(DomainModel):
    items: tuple[Transaction, ...] = ()
    last_id: BrokerId | None = None


class Dataset(DomainModel):
    """Where a set of candles came from (research 07 §4). Stored with every candle."""

    name: str = Field(pattern=r"^[A-Za-z0-9_.:=+-]{1,128}$")
    source: str = Field(min_length=1, max_length=64)
    price_side: Literal["BA", "B", "M"]
    ask_source: AskSource
    smoothed: bool = False
    tz_origin: str = Field(default="UTC", max_length=64)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    licence_note: str | None = Field(default=None, max_length=500)
