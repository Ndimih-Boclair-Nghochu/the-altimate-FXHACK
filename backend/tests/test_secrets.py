"""Secret-leak sentinel (SR-3 to SR-6): the canonical fake token and account id are pushed
through every path that could print them; they must never come out."""

from __future__ import annotations

import io
import logging
from typing import Any

import httpx
import pytest
import respx
import uvicorn

from fxbot import cli
from fxbot.brokers.factory import build_broker, build_feed, build_oanda_client
from fxbot.brokers.oanda.adapter import OandaBroker
from fxbot.brokers.oanda.streaming import OandaPriceStream, OandaTransactionStream
from fxbot.config import Settings, get_settings
from fxbot.domain.errors import BrokerError
from fxbot.logging import configure_logging, get_logger
from tests.support import ACCOUNT_PATH, CREDENTIALS, PRACTICE, practice_client

SENTINELS = (CREDENTIALS.api_token, CREDENTIALS.account_id)


def assert_clean(text: str) -> None:
    for sentinel in SENTINELS:
        assert sentinel not in text
    assert CREDENTIALS.api_token[:16] not in text


@pytest.fixture
def practice_env(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("FXBOT_TRADING_MODE", "practice")
    for name, value in CREDENTIALS.env().items():
        monkeypatch.setenv(name, value)
    return Settings()


@pytest.fixture
def log_stream() -> io.StringIO:
    stream = io.StringIO()
    configure_logging("DEBUG", json=True, stream=stream)
    return stream


async def test_reprs_never_show_credentials(practice_env: Settings) -> None:
    client = build_oanda_client(practice_env)
    broker = build_broker(practice_env)
    feed = build_feed(practice_env)
    objects: list[Any] = [
        practice_env,
        practice_env.model_dump(),
        practice_env.model_dump_json(),
        client,
        client._rest.headers,  # httpx masks the Authorization header in its repr
        broker,
        feed,
        OandaPriceStream(client, ["EUR_USD"]),
        OandaTransactionStream(client),
    ]
    for item in objects:
        assert_clean(repr(item))
        assert_clean(str(item))
    await client.aclose()
    assert isinstance(broker, OandaBroker)
    await broker.aclose()
    await feed.aclose()


def test_log_events_records_and_tracebacks(log_stream: io.StringIO) -> None:
    log = get_logger("fxbot.test")
    log.info("configured", token=CREDENTIALS.api_token, account=CREDENTIALS.account_id)
    log.info(f"inline {CREDENTIALS.api_token} and {CREDENTIALS.account_id}")
    logging.getLogger("third.party").warning("auth header Bearer %s", CREDENTIALS.api_token)

    def failing() -> None:
        headers = {"Authorization": f"Bearer {CREDENTIALS.api_token}"}  # a local variable
        raise RuntimeError(f"request failed with {len(headers)} header(s)")

    try:
        failing()
    except RuntimeError:
        log.exception("unexpected failure")

    output = log_stream.getvalue()
    assert "unexpected failure" in output and "RuntimeError" in output
    assert_clean(output)


async def test_http_failures_do_not_leak(log_stream: io.StringIO) -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    # A hostile or buggy error body that echoes the token and the account id back.
    router.get(f"{ACCOUNT_PATH}/summary").respond(
        401,
        json={"errorMessage": f"bad token {CREDENTIALS.api_token} for {CREDENTIALS.account_id}"},
    )
    router.get(f"{ACCOUNT_PATH}/openTrades").mock(side_effect=httpx.ConnectError("reset"))
    broker = OandaBroker(practice_client(router, attempts=1))

    messages = []
    for call in (broker.get_account, broker.get_open_trades):
        with pytest.raises(BrokerError) as exc:
            await call()
        messages.append(str(exc.value))
        get_logger("fxbot.test").error("broker call failed", error=exc.value)

    for message in messages:
        assert_clean(message)
    assert_clean(log_stream.getvalue())
    # The token was sent where it belongs: the Authorization header, and nowhere else.
    request = router.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {CREDENTIALS.api_token}"
    assert CREDENTIALS.api_token not in str(request.url)


def test_cli_startup_logs_nothing_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Review checklist 1-4: paper mode, DEBUG logging, credentials present.
    monkeypatch.setenv("FXBOT_LOG_LEVEL", "DEBUG")
    for name, value in CREDENTIALS.env().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    get_settings.cache_clear()

    cli.main([])

    captured = capsys.readouterr()
    assert "starting api" in captured.out
    assert_clean(captured.out + captured.err)


def test_cli_refusal_prints_no_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Review checklist 1-12: live with a confirmation for a different account.
    env = CREDENTIALS.live_env() | {"FXBOT_LIVE_CONFIRM_ACCOUNT_ID": CREDENTIALS.other_account_id}
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit) as exc:
        cli.main([])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "does not match FXBOT_OANDA_ACCOUNT_ID" in err
    assert_clean(err)
    assert CREDENTIALS.other_account_id not in err
