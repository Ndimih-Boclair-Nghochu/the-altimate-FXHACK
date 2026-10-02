"""Fake data and test doubles shared across the test suite."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FakeOandaCredentials:
    """Credentials shaped like real OANDA ones, so redaction patterns are exercised."""

    account_id: str = "101-004-1234567-001"
    api_token: str = "0123456789abcdef0123456789abcdef-fedcba9876543210fedcba9876543210"

    def env(self) -> dict[str, str]:
        return {
            "FXBOT_OANDA_ACCOUNT_ID": self.account_id,
            "FXBOT_OANDA_API_TOKEN": self.api_token,
        }

    def assert_absent_from(self, text: str) -> None:
        assert self.account_id not in text
        assert self.api_token not in text
