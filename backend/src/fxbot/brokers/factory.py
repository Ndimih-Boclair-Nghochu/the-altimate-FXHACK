"""Build brokers and market-data feeds from settings.

This is the second of three live-trading interlock checks (ADR 0004, SR-10): it re-runs the
checks on the settings it is given, so a ``Settings`` object that skipped validation (e.g.
built with ``model_construct``) still cannot produce a live broker. Hosts come only from
``brokers/hosts.py`` by mode (SR-11).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Final

import httpx

from fxbot.brokers.base import Broker, MarketDataFeed
from fxbot.brokers.hosts import OandaEnvironment, environment_for_mode
from fxbot.brokers.oanda.adapter import OandaBroker
from fxbot.brokers.oanda.client import OandaClient
from fxbot.brokers.oanda.feed import OandaFeed
from fxbot.brokers.paper import PaperBroker
from fxbot.config import (
    DataFeedKind,
    Settings,
    live_refusal_message,
    live_trading_problems,
    missing_oanda_credentials,
)
from fxbot.data.candle_store import CandleStore
from fxbot.data.replay import ReplayFeed
from fxbot.data.synthetic import SyntheticConfig, SyntheticFeed
from fxbot.domain.clock import Clock, SystemClock
from fxbot.domain.enums import Granularity, Mode
from fxbot.domain.errors import ConfigurationError, LiveTradingNotAllowedError

# Default instrument universe (research 00 §2.1).
DEFAULT_UNIVERSE: Final = ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD")
_SYNTHETIC_HISTORY_BARS: Final = 2_000
_SYNTHETIC_FUTURE_BARS: Final = 24 * 5 * 4  # four trading weeks of H1 bars ahead


def checked_mode(settings: Settings) -> Mode:
    """The trading mode, after re-checking every requirement for it."""
    try:
        mode = Mode(str(getattr(settings, "trading_mode", "")))
    except ValueError:
        raise ConfigurationError("unknown trading mode") from None
    if mode is Mode.LIVE:
        problems = live_trading_problems(settings)
        if problems:
            raise LiveTradingNotAllowedError(live_refusal_message(problems))
    elif mode is Mode.PRACTICE:
        missing = missing_oanda_credentials(settings)
        if missing:
            raise ConfigurationError(
                "trading_mode 'practice' needs OANDA credentials; missing: " + ", ".join(missing)
            )
    return mode


def build_oanda_client(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    stream_transport: httpx.AsyncBaseTransport | None = None,
) -> OandaClient:
    """OANDA client on the host fixed by the mode: live only in a fully interlocked live mode."""
    mode = checked_mode(settings)
    missing = missing_oanda_credentials(settings)
    if missing:
        raise ConfigurationError("OANDA credentials missing: " + ", ".join(missing))
    environment = environment_for_mode(mode)
    if environment is OandaEnvironment.LIVE and mode is not Mode.LIVE:  # pragma: no cover
        raise LiveTradingNotAllowedError("refusing to use the live host outside live mode")
    account_id, api_token = settings.oanda_account_id, settings.oanda_api_token
    if account_id is None or api_token is None:  # pragma: no cover - checked above
        raise ConfigurationError("OANDA credentials missing")
    return OandaClient(
        environment=environment,
        account_id=account_id,
        api_token=api_token,
        transport=transport,
        stream_transport=stream_transport,
    )


def build_broker(
    settings: Settings,
    *,
    clock: Clock | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Broker:
    mode = checked_mode(settings)
    if mode is Mode.PAPER:
        return PaperBroker(clock=clock or SystemClock())
    return OandaBroker(build_oanda_client(settings, transport=transport))


def build_feed(
    settings: Settings,
    *,
    clock: Clock | None = None,
    store: CandleStore | None = None,
    instruments: Sequence[str] = DEFAULT_UNIVERSE,
    transport: httpx.AsyncBaseTransport | None = None,
) -> MarketDataFeed:
    mode = checked_mode(settings)
    clock = clock or SystemClock()
    if mode is not Mode.PAPER:
        return OandaFeed(
            build_oanda_client(settings, transport=transport), clock=clock, owns_client=True
        )
    kind = DataFeedKind(str(getattr(settings, "data_feed", DataFeedKind.SYNTHETIC)))
    if kind is DataFeedKind.OANDA:
        # Read-only market data from the practice host (environment_for_mode(PAPER)).
        client = build_oanda_client(settings, transport=transport)
        return OandaFeed(client, clock=clock, owns_client=True)
    if kind is DataFeedKind.REPLAY:
        if store is None:
            raise ConfigurationError("data_feed 'replay' needs a candle store")
        return ReplayFeed(store, clock=clock)
    start = clock.now() - timedelta(hours=_SYNTHETIC_HISTORY_BARS)
    config = SyntheticConfig(
        granularity=Granularity.H1,
        start=start,
        bars=_SYNTHETIC_HISTORY_BARS + _SYNTHETIC_FUTURE_BARS,
    )
    return SyntheticFeed(instruments, clock=clock, base=config)
