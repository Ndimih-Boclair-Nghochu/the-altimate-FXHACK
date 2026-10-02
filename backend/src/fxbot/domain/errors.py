"""Domain exceptions.

Messages must never contain credentials, account ids, request headers or full broker URLs:
they end up in logs and, later, in API error bodies. Name the endpoint or instrument instead.
"""

from __future__ import annotations


class FxbotError(Exception):
    """Base class for all fxbot errors."""


class ConfigurationError(FxbotError):
    """Settings are missing or inconsistent for the requested operation."""


class LiveTradingNotAllowedError(ConfigurationError):
    """A live broker was requested without every part of the live-trading interlock."""


class BrokerError(FxbotError):
    """Base class for broker failures."""

    def __init__(self, message: str, *, endpoint: str | None = None) -> None:
        super().__init__(message)
        self.endpoint = endpoint


class BrokerUnavailableError(BrokerError):
    """Timeout, 5xx or connection failure. Retryable for reads; order outcome is unknown."""


class RateLimitedError(BrokerUnavailableError):
    """The broker answered 429. ``retry_after`` is in seconds when the broker said so."""

    def __init__(
        self, message: str, *, endpoint: str | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message, endpoint=endpoint)
        self.retry_after = retry_after


class BrokerRejectedError(BrokerError):
    """The broker refused the request (4xx). Never retried unchanged."""

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, endpoint=endpoint)
        self.status_code = status_code
        self.code = code


class BrokerAccountMismatchError(BrokerError):
    """A broker response referred to an account other than the configured one (SR-7)."""


class BrokerAuthError(BrokerRejectedError):
    """401/403: the token is invalid or not allowed to do this. Stop and alert; do not loop."""


class FeedStaleError(FxbotError):
    """No price or heartbeat arrived within the feed's ``stale_after`` window."""


class DataIntegrityError(FxbotError):
    """Market data failed validation: out of order, duplicated, inconsistent or non-finite."""
