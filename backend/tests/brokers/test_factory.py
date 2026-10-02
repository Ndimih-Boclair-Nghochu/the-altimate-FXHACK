"""Broker factory: the second live-trading interlock and host pinning (SR-10, SR-11)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr

from fxbot.brokers.factory import build_broker, build_feed, build_oanda_client, checked_mode
from fxbot.brokers.hosts import OandaEnvironment, environment_for_mode, hosts_for
from fxbot.brokers.oanda.adapter import OandaBroker
from fxbot.brokers.oanda.feed import OandaFeed
from fxbot.brokers.paper import PaperBroker
from fxbot.config import DataFeedKind, Settings
from fxbot.data.candle_store import CandleStore
from fxbot.data.replay import ReplayFeed
from fxbot.data.synthetic import SyntheticFeed
from fxbot.domain.clock import SimClock
from fxbot.domain.enums import Mode
from fxbot.domain.errors import ConfigurationError, LiveTradingNotAllowedError
from fxbot.persistence.db import Database
from tests.fakes import FakeOandaCredentials

CREDS = FakeOandaCredentials()
NOW = datetime(2024, 3, 4, 12, tzinfo=UTC)


def unvalidated(**fields: Any) -> Settings:
    """Settings that bypassed validation, as a bug or a hostile caller could produce."""
    defaults: dict[str, Any] = {
        "trading_mode": Mode.PAPER,
        "allow_live_trading": False,
        "live_trading_confirmed": False,
        "live_confirm_account_id": None,
        "oanda_account_id": None,
        "oanda_api_token": None,
        "data_feed": DataFeedKind.SYNTHETIC,
    }
    return Settings.model_construct(**(defaults | fields))


def live(**overrides: Any) -> Settings:
    fields: dict[str, Any] = {
        "trading_mode": Mode.LIVE,
        "allow_live_trading": True,
        "live_trading_confirmed": True,
        "live_confirm_account_id": SecretStr(CREDS.account_id),
        "oanda_account_id": SecretStr(CREDS.account_id),
        "oanda_api_token": SecretStr(CREDS.api_token),
    }
    return unvalidated(**(fields | overrides))


async def test_paper_needs_no_credentials() -> None:
    broker = build_broker(Settings(), clock=SimClock(NOW))

    assert isinstance(broker, PaperBroker)


def test_practice_needs_both_credentials() -> None:
    for creds in ({}, {"oanda_account_id": SecretStr(CREDS.account_id)}):
        with pytest.raises(ConfigurationError, match="practice"):
            build_broker(unvalidated(trading_mode=Mode.PRACTICE, **creds))


async def test_practice_uses_the_practice_host() -> None:
    settings = unvalidated(
        trading_mode=Mode.PRACTICE,
        oanda_account_id=SecretStr(CREDS.account_id),
        oanda_api_token=SecretStr(CREDS.api_token),
    )

    broker = build_broker(settings)

    assert isinstance(broker, OandaBroker)
    assert broker.name == "oanda-practice"
    client = build_oanda_client(settings)
    assert client.environment is OandaEnvironment.PRACTICE
    assert str(client._rest.base_url).startswith(hosts_for(OandaEnvironment.PRACTICE).rest)
    await client.aclose()
    await broker.aclose()


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"allow_live_trading": False}, "ALLOW_LIVE_TRADING"),
        ({"allow_live_trading": "true"}, "ALLOW_LIVE_TRADING"),  # truthy is not True
        ({"live_trading_confirmed": False}, "FXBOT_LIVE_TRADING_CONFIRMED"),
        ({"live_confirm_account_id": None}, "FXBOT_LIVE_CONFIRM_ACCOUNT_ID is not set"),
        (
            {"live_confirm_account_id": SecretStr(CREDS.other_account_id)},
            "does not match FXBOT_OANDA_ACCOUNT_ID",
        ),
        ({"oanda_api_token": None}, "FXBOT_OANDA_API_TOKEN"),
        ({"oanda_api_token": SecretStr("")}, "FXBOT_OANDA_API_TOKEN"),
    ],
)
def test_live_is_refused_even_if_validation_was_bypassed(
    override: dict[str, Any], reason: str
) -> None:
    settings = live(**override)

    for build in (build_broker, build_feed, build_oanda_client):
        with pytest.raises(LiveTradingNotAllowedError, match=reason) as exc:
            build(settings)
        CREDS.assert_absent_from(str(exc.value))


async def test_live_with_every_gate_uses_the_live_host() -> None:
    broker = build_broker(live())
    client = build_oanda_client(live())

    assert isinstance(broker, OandaBroker) and broker.name == "oanda-live"
    assert client.environment is OandaEnvironment.LIVE
    assert "fxtrade" in str(client._rest.base_url)
    await client.aclose()
    await broker.aclose()


@pytest.mark.parametrize("mode", [Mode.PAPER, Mode.PRACTICE])
def test_paper_and_practice_never_resolve_to_the_live_host(mode: Mode) -> None:
    environment = environment_for_mode(mode)
    hosts = hosts_for(environment)

    assert environment is OandaEnvironment.PRACTICE
    assert "fxtrade" not in hosts.rest and "fxtrade" not in hosts.stream


def test_unknown_mode_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="unknown trading mode"):
        checked_mode(unvalidated(trading_mode="yolo"))


async def test_feeds_for_paper_mode(tmp_path: Any) -> None:
    clock = SimClock(NOW)

    assert isinstance(build_feed(Settings(), clock=clock), SyntheticFeed)
    with pytest.raises(ConfigurationError, match="candle store"):
        build_feed(unvalidated(data_feed=DataFeedKind.REPLAY), clock=clock)
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'f.db').as_posix()}")
    feed = build_feed(
        unvalidated(data_feed=DataFeedKind.REPLAY), clock=clock, store=CandleStore(database)
    )
    assert isinstance(feed, ReplayFeed)
    await database.dispose()

    with pytest.raises(ConfigurationError, match="credentials"):
        build_feed(unvalidated(data_feed=DataFeedKind.OANDA), clock=clock)
    oanda = build_feed(
        unvalidated(
            data_feed=DataFeedKind.OANDA,
            oanda_account_id=SecretStr(CREDS.account_id),
            oanda_api_token=SecretStr(CREDS.api_token),
        ),
        clock=clock,
    )
    assert isinstance(oanda, OandaFeed)
    await oanda.aclose()


async def test_practice_feed_is_oanda() -> None:
    settings = unvalidated(
        trading_mode=Mode.PRACTICE,
        oanda_account_id=SecretStr(CREDS.account_id),
        oanda_api_token=SecretStr(CREDS.api_token),
    )
    feed = build_feed(settings, clock=SimClock(NOW))

    assert isinstance(feed, OandaFeed)
    await feed.aclose()
