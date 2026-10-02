"""Low-level OANDA v20 REST client.

Security properties (docs/SECURITY.md SR-3, SR-6, SR-7, SR-11, SR-17):

- The token is unwrapped once, into the httpx client's default ``Authorization`` header, and is
  never put in a URL. httpx masks that header in its own ``repr``.
- Hosts come from ``hosts.py`` by environment; there is no URL parameter. Tests inject an httpx
  transport instead.
- TLS verification on, redirects never followed, explicit timeouts on every client.
- Every account-scoped path is built from the configured account id in one method.
- Only GET requests are retried (backoff + jitter, ``Retry-After`` honoured on 429). Requests
  that create or change orders and trades are sent exactly once.
- Error messages name the endpoint, never the URL, headers or body.
"""

from __future__ import annotations

import asyncio
import hmac
import random
import re
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Final

import httpx
from pydantic import SecretStr

from fxbot import __version__
from fxbot.brokers.backoff import Backoff, Sleep, TokenBucket
from fxbot.brokers.hosts import OandaEnvironment, hosts_for
from fxbot.brokers.oanda.wire import reject_code
from fxbot.domain.errors import (
    BrokerAccountMismatchError,
    BrokerAuthError,
    BrokerRejectedError,
    BrokerUnavailableError,
    RateLimitedError,
)
from fxbot.logging import get_logger, redact_text

log = get_logger(__name__)

JsonDict = dict[str, Any]

DEFAULT_TIMEOUT: Final = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
# Streams send a heartbeat about every 5 s; the feed's own watchdog (stale_after) is tighter.
DEFAULT_STREAM_TIMEOUT: Final = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_MAX_RETRY_AFTER: Final = 60.0
_MAX_ERROR_MESSAGE: Final = 200

_INSTRUMENT: Final = re.compile(r"^[A-Z]{3}_[A-Z]{3}$")
_TRANSACTION_ID: Final = re.compile(r"^[0-9]{1,20}$")
# A trade/order specifier is an OANDA id or "@" + our client id.
_SPECIFIER: Final = re.compile(r"^(?:[0-9]{1,20}|@[A-Za-z0-9_-]{1,32})$")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    backoff: Backoff = field(default_factory=Backoff)


def _checked(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {what}")
    return value


def _account_ids(payload: Any) -> Iterator[str]:
    """Every ``accountID`` value, and ``account.id``, anywhere in a response."""
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key == "accountID" and isinstance(value, str | int):
                    yield str(value)
                elif key == "account" and isinstance(value, dict) and "id" in value:
                    yield str(value["id"])
                if isinstance(value, dict | list):
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)


def _instrument_list(names: Sequence[str]) -> str:
    if not names:
        raise ValueError("at least one instrument is required")
    return ",".join(_checked(_INSTRUMENT, name, "instrument") for name in names)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    try:
        return min(_MAX_RETRY_AFTER, max(0.0, float(raw))) if raw is not None else None
    except ValueError:
        return None


def _error_body(response: httpx.Response) -> JsonDict | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def raise_for_status(response: httpx.Response, endpoint: str) -> None:
    """Map a non-2xx response to a domain error. Never includes URL, headers or token."""
    status = response.status_code
    if status < 300:
        return
    request_id = response.headers.get("RequestID")
    body = _error_body(response)
    code = reject_code(body)
    message = redact_text(str((body or {}).get("errorMessage", "")))[:_MAX_ERROR_MESSAGE]
    log.warning(
        "oanda request failed",
        endpoint=endpoint,
        status=status,
        code=code,
        request_id=request_id,
    )
    text = f"OANDA {endpoint} failed with HTTP {status}" + (f" ({code})" if code else "")
    if message:
        text += f": {message}"
    if status == 429:
        raise RateLimitedError(text, endpoint=endpoint, retry_after=_retry_after(response))
    if status in (401, 403):
        raise BrokerAuthError(text, endpoint=endpoint, status_code=status, code=code)
    if status >= 500:
        raise BrokerUnavailableError(text, endpoint=endpoint)
    raise BrokerRejectedError(text, endpoint=endpoint, status_code=status, code=code)


class OandaClient:
    """One instance per process and account. Call ``aclose()`` when done."""

    def __init__(
        self,
        *,
        environment: OandaEnvironment,
        account_id: SecretStr,
        api_token: SecretStr,
        transport: httpx.AsyncBaseTransport | None = None,
        stream_transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        stream_timeout: httpx.Timeout = DEFAULT_STREAM_TIMEOUT,
        requests_per_second: float = 20.0,
        retry: RetryPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if len(account_id) == 0 or len(api_token) == 0:
            raise ValueError("OANDA account id and API token are required")
        self.environment = OandaEnvironment(environment)
        hosts = hosts_for(self.environment)
        self._account_id = account_id
        headers = {
            # SR-3: the only place the token is unwrapped; it lives in the client's headers.
            "Authorization": f"Bearer {api_token.get_secret_value()}",
            "Accept-Datetime-Format": "RFC3339",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": f"altimate-fx/{__version__}",
        }
        common: dict[str, Any] = {
            "headers": headers,
            "follow_redirects": False,
            "verify": True,
            "limits": httpx.Limits(max_connections=10, max_keepalive_connections=5),
        }
        self._rest = httpx.AsyncClient(
            base_url=hosts.rest, timeout=timeout, transport=transport, **common
        )
        self._stream = httpx.AsyncClient(
            base_url=hosts.stream,
            timeout=stream_timeout,
            transport=stream_transport or transport,
            **common,
        )
        self._bucket = TokenBucket(requests_per_second, sleep=sleep)
        self._retry = retry or RetryPolicy()
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 - backoff jitter, not cryptography

    def __repr__(self) -> str:
        return f"OandaClient(environment={self.environment.value!r})"

    async def aclose(self) -> None:
        await self._rest.aclose()
        await self._stream.aclose()

    # ---------------------------------------------------------------- account scoping

    def _account_path(self, suffix: str = "") -> str:
        # SR-7: every account-scoped request addresses the configured account only.
        return f"/v3/accounts/{self._account_id.get_secret_value()}{suffix}"

    def is_configured_account(self, account_id: str) -> bool:
        return hmac.compare_digest(
            account_id.encode(), self._account_id.get_secret_value().encode()
        )

    def check_account_fields(self, payload: Any, endpoint: str) -> None:
        """Raise if any account id in ``payload`` is not the configured account (SR-7)."""
        for account_id in _account_ids(payload):
            if not self.is_configured_account(account_id):
                log.error("broker response for another account", endpoint=endpoint)
                raise BrokerAccountMismatchError(
                    f"OANDA {endpoint} returned data for a different account", endpoint=endpoint
                )

    # ---------------------------------------------------------------- transport

    async def _send(
        self,
        method: str,
        endpoint: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: JsonDict | None = None,
    ) -> JsonDict:
        await self._bucket.acquire()
        try:
            response = await self._rest.request(method, path, params=params, json=json_body)
        except httpx.TimeoutException:
            raise BrokerUnavailableError(f"OANDA {endpoint} timed out", endpoint=endpoint) from None
        except httpx.TransportError as exc:
            raise BrokerUnavailableError(
                f"OANDA {endpoint} connection failed ({type(exc).__name__})", endpoint=endpoint
            ) from None
        raise_for_status(response, endpoint)
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise BrokerUnavailableError(
                f"OANDA {endpoint} returned malformed JSON", endpoint=endpoint
            )
        if path.startswith("/v3/accounts/"):
            self.check_account_fields(body, endpoint)
        return body

    async def get(
        self, endpoint: str, path: str, params: Mapping[str, str] | None = None
    ) -> JsonDict:
        """GET with retries on timeouts, connection errors, 5xx and 429."""
        attempts = max(1, self._retry.max_attempts)
        for attempt in range(attempts):
            try:
                return await self._send("GET", endpoint, path, params=params)
            except BrokerUnavailableError as exc:
                if attempt == attempts - 1:
                    raise
                delay = self._retry.backoff.delay(attempt, self._rng)
                if isinstance(exc, RateLimitedError) and exc.retry_after is not None:
                    delay = max(delay, exc.retry_after)
                log.info("retrying oanda request", endpoint=endpoint, attempt=attempt + 1)
                await self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    async def send_once(self, method: str, endpoint: str, path: str, body: JsonDict) -> JsonDict:
        """POST/PUT exactly once. The caller resolves an unknown outcome; never retry here."""
        return await self._send(method, endpoint, path, json_body=body)

    @asynccontextmanager
    async def open_stream(
        self, endpoint: str, path: str, params: Mapping[str, str]
    ) -> AsyncIterator[httpx.Response]:
        """Open a streaming GET on the stream host. Raises domain errors for non-2xx."""
        await self._bucket.acquire()
        try:
            async with self._stream.stream("GET", path, params=params) as response:
                if response.status_code >= 300:
                    await response.aread()
                    raise_for_status(response, endpoint)
                yield response
        except httpx.TimeoutException:
            raise BrokerUnavailableError(f"OANDA {endpoint} timed out", endpoint=endpoint) from None
        except httpx.TransportError as exc:
            raise BrokerUnavailableError(
                f"OANDA {endpoint} connection failed ({type(exc).__name__})", endpoint=endpoint
            ) from None

    # ---------------------------------------------------------------- endpoints (reads)

    async def list_accounts(self) -> JsonDict:
        # The only request not scoped to the configured account: the start-up check (SR-7).
        return await self.get("accounts", "/v3/accounts")

    async def account_summary(self) -> JsonDict:
        return await self.get("account_summary", self._account_path("/summary"))

    async def account_instruments(self, names: Sequence[str] | None = None) -> JsonDict:
        params = {"instruments": _instrument_list(names)} if names else None
        return await self.get("instruments", self._account_path("/instruments"), params)

    async def candles(self, instrument: str, params: Mapping[str, str]) -> JsonDict:
        name = _checked(_INSTRUMENT, instrument, "instrument")
        return await self.get("candles", f"/v3/instruments/{name}/candles", params)

    async def pricing(self, instruments: Sequence[str]) -> JsonDict:
        params = {"instruments": _instrument_list(instruments)}
        return await self.get("pricing", self._account_path("/pricing"), params)

    async def get_order(self, specifier: str) -> JsonDict:
        spec = _checked(_SPECIFIER, specifier, "order specifier")
        return await self.get("order", self._account_path(f"/orders/{spec}"))

    async def open_trades(self) -> JsonDict:
        return await self.get("open_trades", self._account_path("/openTrades"))

    async def get_trade(self, specifier: str) -> JsonDict:
        spec = _checked(_SPECIFIER, specifier, "trade specifier")
        return await self.get("trade", self._account_path(f"/trades/{spec}"))

    async def open_positions(self) -> JsonDict:
        return await self.get("open_positions", self._account_path("/openPositions"))

    async def transactions_since(self, transaction_id: str) -> JsonDict:
        tx_id = _checked(_TRANSACTION_ID, transaction_id, "transaction id")
        return await self.get(
            "transactions_since", self._account_path("/transactions/sinceid"), {"id": tx_id}
        )

    async def get_transaction(self, transaction_id: str) -> JsonDict:
        tx_id = _checked(_TRANSACTION_ID, transaction_id, "transaction id")
        return await self.get("transaction", self._account_path(f"/transactions/{tx_id}"))

    # ---------------------------------------------------------------- endpoints (writes)

    async def create_order(self, order: JsonDict) -> JsonDict:
        return await self.send_once("POST", "create_order", self._account_path("/orders"), order)

    async def close_trade(self, specifier: str, body: JsonDict) -> JsonDict:
        spec = _checked(_SPECIFIER, specifier, "trade specifier")
        return await self.send_once(
            "PUT", "close_trade", self._account_path(f"/trades/{spec}/close"), body
        )

    async def set_trade_orders(self, specifier: str, body: JsonDict) -> JsonDict:
        spec = _checked(_SPECIFIER, specifier, "trade specifier")
        return await self.send_once(
            "PUT", "trade_orders", self._account_path(f"/trades/{spec}/orders"), body
        )

    async def close_position(self, instrument: str, body: JsonDict) -> JsonDict:
        name = _checked(_INSTRUMENT, instrument, "instrument")
        return await self.send_once(
            "PUT", "close_position", self._account_path(f"/positions/{name}/close"), body
        )

    # ---------------------------------------------------------------- streams

    def pricing_stream(
        self, instruments: Sequence[str]
    ) -> AbstractAsyncContextManager[httpx.Response]:
        return self.open_stream(
            "pricing_stream",
            self._account_path("/pricing/stream"),
            {"instruments": _instrument_list(instruments), "snapshot": "true"},
        )

    def transaction_stream(self) -> AbstractAsyncContextManager[httpx.Response]:
        return self.open_stream(
            "transaction_stream", self._account_path("/transactions/stream"), {}
        )
