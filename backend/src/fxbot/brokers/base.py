"""Broker-agnostic interfaces. Adapters (paper, OANDA, later MT5 and cTrader) implement these.

The protocols are async and say nothing about transport: an adapter may talk HTTP, a socket,
or a synchronous SDK run on a dedicated worker thread.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from fxbot.domain.enums import Granularity, PositionAccounting
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
    TransactionPage,
)


class ClientIdSupport(StrEnum):
    """How a broker lets us find an order again by our own ``client_id`` (idempotency)."""

    NATIVE = "native"  # stored and indexed by the broker (OANDA ``clientExtensions.id``)
    COMMENT = "comment"  # kept in an order comment + bot id, found by scanning history (MT5)
    NONE = "none"  # not recoverable; the order manager must reconcile by other means


@dataclass(frozen=True, slots=True)
class BrokerCapabilities:
    """What an adapter/account supports. Risk and order management adapt to these.

    Size limits (units step, minimum, maximum) and the minimum stop distance are per
    instrument and live on ``Instrument``.
    """

    position_accounting: PositionAccounting
    supports_hedging: bool  # opposite trades on one instrument may coexist
    fifo_required: bool  # positions must be reduced oldest first (US/NFA accounts)
    supports_sl_on_fill: bool  # the stop is attached to the entry order itself
    supports_tp_on_fill: bool
    supports_trailing_stop: bool  # server-side; if False the engine trails on bar close
    supports_guaranteed_stop: bool
    client_id_support: ClientIdSupport
    supports_price_streaming: bool  # pushed quotes; otherwise the feed polls
    supports_transaction_streaming: bool
    candle_price_sides: frozenset[str]  # "B", "A", "M"; MT5 bars are bid + spread
    max_orders_per_second: float | None = None


class Broker(Protocol):
    """Account and order operations. The broker is the source of truth for positions."""

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> BrokerCapabilities: ...

    async def connect(self) -> None:
        """Verify credentials and the configured account; load instrument specs."""
        ...

    async def aclose(self) -> None: ...

    async def get_account(self) -> AccountSummary: ...

    async def get_instruments(self, names: Sequence[str] | None = None) -> list[Instrument]: ...

    async def get_prices(self, instruments: Sequence[str]) -> list[Price]:
        """Current top-of-book quotes (a snapshot, not a stream)."""
        ...

    async def get_open_trades(self) -> list[Trade]: ...

    async def get_positions(self) -> list[Position]: ...

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Send a market order. Idempotent on ``order.client_id``; never retried internally.

        Returns ``UNKNOWN`` when the outcome cannot be established (timeout, 5xx); resolve it
        with ``find_order`` before any resubmission.
        """
        ...

    async def find_order(self, client_id: str) -> OrderResult | None:
        """Outcome of an earlier submission, or ``None`` if the broker has no such order."""
        ...

    async def modify_trade_exits(
        self,
        trade_id: str,
        *,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> None:
        """Replace the stop and/or target of an open trade. ``None`` leaves a level unchanged."""
        ...

    async def close_trade(self, trade_id: str, units: Decimal | None = None) -> Fill:
        """Close a trade fully (``units=None``) or partially."""
        ...

    async def close_all(self) -> list[Fill]:
        """Close every open position. Callers must confirm flatness with ``get_positions``."""
        ...

    async def get_transactions_since(self, last_id: str | None) -> TransactionPage:
        """Transactions newer than ``last_id``; with ``None``, only the current last id."""
        ...


class MarketDataFeed(Protocol):
    """Market data: closed candles for decisions, live prices for monitoring and fills."""

    async def get_candles(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Candle]:
        """Complete candles with ``start <= time < end``, ascending."""
        ...

    def bars(
        self,
        instruments: Sequence[str],
        granularity: Granularity,
        since: datetime | None = None,
    ) -> AsyncIterator[Candle]:
        """Each newly completed candle once, in time order, as it closes (decision bars)."""
        ...

    def stream_prices(self, instruments: Sequence[str]) -> AsyncIterator[Price]:
        """Live quotes. Raises ``FeedStaleError`` if nothing arrives within ``stale_after``."""
        ...

    async def aclose(self) -> None: ...
