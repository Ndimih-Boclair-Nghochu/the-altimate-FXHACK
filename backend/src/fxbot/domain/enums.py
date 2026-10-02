"""Enumerations shared across the domain."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Literal


class Mode(StrEnum):
    """Trading mode. Fixed at process start; see ``fxbot.config``."""

    PAPER = "paper"
    PRACTICE = "practice"
    LIVE = "live"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> Literal[1, -1]:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class Granularity(StrEnum):
    """Candle granularities (OANDA codes). Intraday bars of 2h and more align to 17:00 New York."""

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H2 = "H2"
    H4 = "H4"
    H6 = "H6"
    H8 = "H8"
    H12 = "H12"
    D = "D"
    W = "W"

    @property
    def duration(self) -> timedelta:
        return _DURATIONS[self]

    @property
    def seconds(self) -> int:
        return int(self.duration.total_seconds())


_DURATIONS: dict[Granularity, timedelta] = {
    Granularity.M1: timedelta(minutes=1),
    Granularity.M5: timedelta(minutes=5),
    Granularity.M15: timedelta(minutes=15),
    Granularity.M30: timedelta(minutes=30),
    Granularity.H1: timedelta(hours=1),
    Granularity.H2: timedelta(hours=2),
    Granularity.H4: timedelta(hours=4),
    Granularity.H6: timedelta(hours=6),
    Granularity.H8: timedelta(hours=8),
    Granularity.H12: timedelta(hours=12),
    Granularity.D: timedelta(days=1),
    Granularity.W: timedelta(weeks=1),
}


class OrderStatus(StrEnum):
    """Order lifecycle. Brokers return FILLED, CANCELLED, REJECTED, SUBMITTED or UNKNOWN."""

    PENDING = "pending"  # persisted locally, not yet sent (order manager, stage 5)
    SUBMITTED = "submitted"  # accepted by the broker, not yet filled
    FILLED = "filled"
    CANCELLED = "cancelled"  # accepted, then cancelled by the broker (e.g. FOK, halted market)
    REJECTED = "rejected"  # refused by the broker; nothing was created
    UNKNOWN = "unknown"  # outcome not known (timeout, 5xx); resolve by client id, never resend


class FillReason(StrEnum):
    """Why a fill happened, independent of broker vocabulary."""

    ENTRY = "entry"
    CLOSE = "close"  # explicit trade close requested by us
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    POSITION_CLOSEOUT = "position_closeout"
    MARGIN_CLOSEOUT = "margin_closeout"
    OTHER = "other"


class ExitReason(StrEnum):
    """Why a trade was closed, as recorded in the journal."""

    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    STRATEGY = "strategy"
    TIME_BARRIER = "time_barrier"
    MANUAL = "manual"
    KILL_SWITCH = "kill_switch"
    MARGIN_CLOSEOUT = "margin_closeout"
    EXTERNAL = "external"


class TradeState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class AskSource(StrEnum):
    """How a candle's ask side was obtained. Simulations should know when it is modelled."""

    QUOTED = "quoted"  # real ask OHLC from the source (OANDA price=BA, LEAN bid/ask files)
    BAR_SPREAD = "bar_spread"  # bid OHLC + the bar's spread reported by the source (MT5 rates)
    MODEL_SPREAD = "model_spread"  # bid OHLC + a modelled spread (bid-only datasets)
    SYNTHETIC = "synthetic"  # generated data


class PositionAccounting(StrEnum):
    """How the broker books positions."""

    PER_TRADE = "per_trade"  # each fill opens its own trade/ticket (OANDA, MT5 hedging)
    NETTING = "netting"  # one net position per instrument (MT5 netting accounts)
