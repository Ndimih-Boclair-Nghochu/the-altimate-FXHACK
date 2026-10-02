from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest
from pydantic import SecretStr

from fxbot.logging import (
    HANDLER_NAME,
    REDACTED,
    configure_logging,
    get_logger,
    redact_sensitive,
    redact_text,
)
from tests.fakes import FakeOandaCredentials

OANDA = FakeOandaCredentials()


def redact(event: dict[str, Any]) -> dict[str, Any]:
    return dict(redact_sensitive(None, "info", event))


def json_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


@pytest.mark.parametrize(
    "key",
    [
        "token",
        "api_token",
        "oanda_api_token",
        "OANDA_API_TOKEN",
        "secret",
        "client_secret",
        "password",
        "db_passwd",
        "Authorization",
        "api_key",
        "apiKey",
        "x-api-key",
        "account_id",
        "oanda_account_id",
        "accountID",
    ],
)
def test_values_under_sensitive_keys_are_masked(key: str) -> None:
    assert redact({key: "plain-value"})[key] == REDACTED


def test_ordinary_values_are_left_alone() -> None:
    event = {"event": "order placed", "instrument": "EUR_USD", "units": 1000, "price": 1.0842}

    assert redact(dict(event)) == event


def test_unset_and_boolean_sensitive_values_stay_visible() -> None:
    event = {"oanda_api_token": None, "has_credentials": True, "token_valid": False}

    assert redact(dict(event)) == event


def test_nested_structures_are_redacted_without_mutating_the_input() -> None:
    headers = {"Authorization": f"Bearer {OANDA.api_token}", "Accept": "application/json"}
    event = {
        "request": {"headers": headers, "params": [{"password": "hunter2"}]},
        "urls": (f"/v3/accounts/{OANDA.account_id}/trades", "/v3/instruments"),
    }

    result = redact(event)

    assert result["request"]["headers"] == {"Authorization": REDACTED, "Accept": "application/json"}
    assert result["request"]["params"] == [{"password": REDACTED}]
    assert result["urls"] == (f"/v3/accounts/{REDACTED}/trades", "/v3/instruments")
    assert headers["Authorization"] == f"Bearer {OANDA.api_token}"


def test_secret_types_are_masked_under_any_key() -> None:
    assert redact({"value": SecretStr("hunter2")})["value"] == REDACTED


def test_exceptions_are_rendered_and_redacted() -> None:
    result = redact({"error": RuntimeError(f"rejected {OANDA.api_token}")})

    assert result["error"] == f"RuntimeError: rejected {REDACTED}"


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (f"token is {OANDA.api_token}", OANDA.api_token),
        (f"token is {OANDA.api_token.upper()}", OANDA.api_token.upper()),
        (f"GET /v3/accounts/{OANDA.account_id}/orders", OANDA.account_id),
        ("Authorization: Bearer abc.def-ghi_123", "abc.def-ghi_123"),
        ("postgresql+asyncpg://fx:hunter2@db:5432/fx", "hunter2"),
        ("https://example.test/feed?api_key=s3kr1t&format=json", "s3kr1t"),
        ('{"password": "hunter2", "user": "fx"}', "hunter2"),
        ("client_secret=abc123", "abc123"),
    ],
)
def test_credential_patterns_in_text_are_masked(text: str, secret: str) -> None:
    result = redact_text(text)

    assert secret not in result
    assert REDACTED in result


def test_text_redaction_is_idempotent() -> None:
    once = redact_text(f"token={OANDA.api_token} url=https://u:p@host Bearer abc")

    assert redact_text(once) == once


def test_text_without_credentials_is_unchanged() -> None:
    text = "EUR_USD closed at 1.08421 on 2026-10-02T21:00:00Z after 3 bars"

    assert redact_text(text) == text


def test_json_output_redacts_structlog_events() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    get_logger("fxbot.test").info(
        "placing order",
        instrument="EUR_USD",
        oanda_api_token=OANDA.api_token,
        url=f"https://api-fxpractice.oanda.com/v3/accounts/{OANDA.account_id}/orders",
    )

    OANDA.assert_absent_from(stream.getvalue())
    (record,) = json_lines(stream)
    assert record["event"] == "placing order"
    assert record["level"] == "info"
    assert record["logger"] == "fxbot.test"
    assert record["instrument"] == "EUR_USD"
    assert record["oanda_api_token"] == REDACTED
    assert "timestamp" in record


def test_stdlib_log_records_are_redacted() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    logging.getLogger("httpx").info(
        "HTTP Request: GET https://api-fxpractice.oanda.com/v3/accounts/%s/summary",
        OANDA.account_id,
    )

    OANDA.assert_absent_from(stream.getvalue())
    (record,) = json_lines(stream)
    assert record["logger"] == "httpx"
    assert REDACTED in record["event"]


def test_stdlib_extras_are_kept_except_uvicorn_color_duplicates() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    logging.getLogger("uvicorn.error").info(
        "Started server process [%d]",
        42,
        extra={"color_message": "Started server process [\x1b[36m%d\x1b[0m]", "worker": 1},
    )

    (record,) = json_lines(stream)
    assert record["event"] == "Started server process [42]"
    assert record["worker"] == 1
    assert "color_message" not in record


def test_tracebacks_are_redacted() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    try:
        raise RuntimeError(f"auth failed for {OANDA.api_token}")
    except RuntimeError:
        get_logger("fxbot.test").exception("request failed")

    OANDA.assert_absent_from(stream.getvalue())
    (record,) = json_lines(stream)
    assert "RuntimeError: auth failed for" in record["exception"]


def test_explicit_exc_info_is_rendered_and_redacted() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    error = RuntimeError(f"auth failed for {OANDA.api_token}")
    get_logger("fxbot.test").error("request failed", exc_info=error)

    OANDA.assert_absent_from(stream.getvalue())
    (record,) = json_lines(stream)
    assert record["exception"].startswith("RuntimeError: auth failed for")


def test_console_output_redacts_secrets() -> None:
    stream = io.StringIO()
    configure_logging("DEBUG", json=False, stream=stream)

    get_logger("fxbot.test").debug("connecting", api_token=OANDA.api_token)

    output = stream.getvalue()
    OANDA.assert_absent_from(output)
    assert "connecting" in output
    assert REDACTED in output


def test_log_level_filters_records() -> None:
    stream = io.StringIO()
    configure_logging("warning", json=True, stream=stream)

    log = get_logger("fxbot.test")
    log.info("hidden")
    log.warning("shown")

    assert [record["event"] for record in json_lines(stream)] == ["shown"]


def test_reconfiguring_replaces_the_handler() -> None:
    configure_logging(json=True, stream=io.StringIO())
    configure_logging(json=False, stream=io.StringIO())

    names = [handler.get_name() for handler in logging.getLogger().handlers]
    assert names.count(HANDLER_NAME) == 1
