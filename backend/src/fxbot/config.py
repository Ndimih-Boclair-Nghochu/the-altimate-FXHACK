"""Application settings, loaded from environment variables and an optional ``.env`` file.

Every setting uses the ``FXBOT_`` prefix except ``ALLOW_LIVE_TRADING``, which is read
verbatim so that enabling real-money trading is a deliberate, separately audited switch.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

TradingMode = Literal["paper", "practice", "live"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

ENV_PREFIX = "FXBOT_"
ALLOW_LIVE_TRADING_ENV = "ALLOW_LIVE_TRADING"


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

    trading_mode: TradingMode = "paper"
    # The alias is spelled out (not the constant) so the pydantic mypy plugin can see it.
    allow_live_trading: bool = Field(default=False, validation_alias="ALLOW_LIVE_TRADING")
    live_trading_confirmed: bool = False

    oanda_account_id: SecretStr | None = None
    oanda_api_token: SecretStr | None = None

    database_url: str = "sqlite+aiosqlite:///./data/fxbot.db"

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    log_level: LogLevel = "INFO"
    log_json: bool = False

    @field_validator("oanda_account_id", "oanda_api_token", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
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
        missing_credentials = [
            f"{ENV_PREFIX}{name.upper()}"
            for name in ("oanda_account_id", "oanda_api_token")
            if getattr(self, name) is None
        ]
        if self.trading_mode == "practice" and missing_credentials:
            raise ValueError(
                "trading_mode 'practice' needs OANDA practice credentials; missing: "
                + ", ".join(missing_credentials)
            )
        if self.trading_mode == "live":
            problems: list[str] = []
            if not self.allow_live_trading:
                problems.append(f"{ALLOW_LIVE_TRADING_ENV}=true is not set in the environment")
            if not self.live_trading_confirmed:
                problems.append(f"{ENV_PREFIX}LIVE_TRADING_CONFIRMED=true is not set")
            problems.extend(f"{name} is not set" for name in missing_credentials)
            if problems:
                raise ValueError(
                    "refusing to start in trading_mode 'live' (real money): " + "; ".join(problems)
                )
        return self

    @property
    def has_oanda_credentials(self) -> bool:
        return self.oanda_account_id is not None and self.oanda_api_token is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once (``get_settings.cache_clear()`` reloads)."""
    return Settings()
