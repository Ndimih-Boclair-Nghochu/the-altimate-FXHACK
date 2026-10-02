"""Application settings, loaded from environment variables and an optional ``.env`` file.

Every setting uses the ``FXBOT_`` prefix except ``ALLOW_LIVE_TRADING``, which is read
verbatim so that enabling real-money trading is a deliberate, separately audited switch.
"""

from __future__ import annotations

import hmac
import json
import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from fxbot.domain.enums import Mode

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

ENV_PREFIX: Final = "FXBOT_"
ALLOW_LIVE_TRADING_ENV: Final = "ALLOW_LIVE_TRADING"
ACCOUNT_ID_ENV: Final = f"{ENV_PREFIX}OANDA_ACCOUNT_ID"
API_TOKEN_ENV: Final = f"{ENV_PREFIX}OANDA_API_TOKEN"
LIVE_CONFIRMED_ENV: Final = f"{ENV_PREFIX}LIVE_TRADING_CONFIRMED"
LIVE_CONFIRM_ACCOUNT_ENV: Final = f"{ENV_PREFIX}LIVE_CONFIRM_ACCOUNT_ID"

_ACCOUNT_ID_RE: Final = re.compile(r"^\d{3}-\d{3}-\d{1,12}-\d{3}$")


class DataFeedKind(StrEnum):
    """Where paper mode gets prices from."""

    SYNTHETIC = "synthetic"
    REPLAY = "replay"  # candles already in the local candle store
    OANDA = "oanda"  # OANDA practice prices, read-only (needs practice credentials)


class Settings(BaseSettings):
    """Typed runtime configuration. Secrets are ``SecretStr`` and never rendered in clear."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        # The .env file may be shared with docker compose; unrelated keys are not errors.
        extra="ignore",
        # Validation errors must never echo raw input: it may contain credentials.
        hide_input_in_errors=True,
        frozen=True,
    )

    trading_mode: Mode = Mode.PAPER
    # The alias is spelled out (not the constant) so the pydantic mypy plugin can see it.
    allow_live_trading: bool = Field(default=False, validation_alias="ALLOW_LIVE_TRADING")
    live_trading_confirmed: bool = False
    # Must equal the OANDA account id in live mode, so a confirmation given for one account
    # cannot silently carry over to another.
    live_confirm_account_id: SecretStr | None = None

    oanda_account_id: SecretStr | None = None
    oanda_api_token: SecretStr | None = None

    data_feed: DataFeedKind = DataFeedKind.SYNTHETIC
    # Database, validation datasets and (later) model artefacts. Relative to the working dir.
    data_dir: Path = Path("data")
    # Default: SQLite at <data_dir>/fxbot.db. No password in the URL: secrets only come from
    # SecretStr settings (use the driver's own mechanism, e.g. a Postgres passfile).
    database_url: str | None = None

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    log_level: LogLevel = "INFO"
    log_json: bool = False

    @field_validator(
        "oanda_account_id", "oanda_api_token", "live_confirm_account_id", mode="before"
    )
    @classmethod
    def _blank_secret_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("oanda_account_id", "live_confirm_account_id", mode="before")
    @classmethod
    def _check_account_id_format(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip() and not _ACCOUNT_ID_RE.fullmatch(value.strip()):
            raise ValueError("not an OANDA account id (expected NNN-NNN-NNNNNNN-NNN)")
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_url_is_unset(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_url")
    @classmethod
    def _reject_password_in_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            url = make_url(value)
        except ArgumentError:
            raise ValueError("not a valid SQLAlchemy database URL") from None
        if url.password:
            raise ValueError("database_url must not contain a password")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: Any) -> Any:
        """Accept a JSON array or a comma-separated string."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check_trading_mode(self) -> Self:
        if self.trading_mode is Mode.LIVE:
            problems = live_trading_problems(self)
            if problems:
                raise ValueError(live_refusal_message(problems))
            return self
        missing = missing_oanda_credentials(self)
        if self.trading_mode is Mode.PRACTICE and missing:
            raise ValueError(
                "trading_mode 'practice' needs OANDA practice credentials; missing: "
                + ", ".join(missing)
            )
        if self.trading_mode is Mode.PAPER and self.data_feed is DataFeedKind.OANDA and missing:
            raise ValueError(
                "data_feed 'oanda' needs OANDA practice credentials; missing: " + ", ".join(missing)
            )
        return self

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        # as_posix() keeps Windows paths valid in the URL (sqlite+aiosqlite:///C:/...).
        return f"sqlite+aiosqlite:///{(self.data_dir / 'fxbot.db').resolve().as_posix()}"

    @property
    def has_oanda_credentials(self) -> bool:
        return not missing_oanda_credentials(self)


def _is_set(secret: object) -> bool:
    return isinstance(secret, SecretStr) and len(secret) > 0


def secret_equals(left: object, right: object) -> bool:
    """Constant-time comparison of two ``SecretStr`` values; False if either is unset.

    Besides the broker client, this is the only place that unwraps a secret, and only to
    compare it: the clear value is never stored or returned.
    """
    if not (isinstance(left, SecretStr) and isinstance(right, SecretStr)):
        return False
    if len(left) == 0 or len(right) == 0:
        return False
    return hmac.compare_digest(left.get_secret_value().encode(), right.get_secret_value().encode())


def missing_oanda_credentials(settings: Settings) -> list[str]:
    """Names of the OANDA credential variables that are not set."""
    return [
        env
        for env, field in ((ACCOUNT_ID_ENV, "oanda_account_id"), (API_TOKEN_ENV, "oanda_api_token"))
        if not _is_set(getattr(settings, field, None))
    ]


def live_trading_problems(settings: Settings) -> list[str]:
    """Every unmet live-trading requirement. Empty means live trading may proceed.

    Written defensively (``is True``, ``getattr``) because the broker factory re-runs it on
    settings that may have bypassed validation, e.g. built with ``model_construct``.
    """
    problems: list[str] = []
    if getattr(settings, "allow_live_trading", False) is not True:
        problems.append(f"{ALLOW_LIVE_TRADING_ENV}=true is not set in the environment")
    if getattr(settings, "live_trading_confirmed", False) is not True:
        problems.append(f"{LIVE_CONFIRMED_ENV}=true is not set")
    missing = missing_oanda_credentials(settings)
    problems.extend(f"{name} is not set" for name in missing)
    confirm = getattr(settings, "live_confirm_account_id", None)
    if not _is_set(confirm):
        problems.append(f"{LIVE_CONFIRM_ACCOUNT_ENV} is not set")
    elif ACCOUNT_ID_ENV not in missing and not secret_equals(
        confirm, getattr(settings, "oanda_account_id", None)
    ):
        problems.append(f"{LIVE_CONFIRM_ACCOUNT_ENV} does not match {ACCOUNT_ID_ENV}")
    return problems


def live_refusal_message(problems: list[str]) -> str:
    return "refusing to start in trading_mode 'live' (real money): " + "; ".join(problems)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once (``get_settings.cache_clear()`` reloads)."""
    return Settings()
