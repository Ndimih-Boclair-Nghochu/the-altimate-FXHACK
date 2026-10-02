from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog

from fxbot.config import ALLOW_LIVE_TRADING_ENV, ENV_PREFIX, get_settings
from fxbot.logging import HANDLER_NAME
from tests.fakes import FakeOandaCredentials


@pytest.fixture
def fake_oanda() -> FakeOandaCredentials:
    return FakeOandaCredentials()


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Keep tests independent of the developer's shell environment and ``.env`` file."""
    for name in list(os.environ):
        if name.upper().startswith(ENV_PREFIX) or name.upper() == ALLOW_LIVE_TRADING_ENV:
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """Undo ``configure_logging`` side effects so tests cannot leak logging state."""
    root = logging.getLogger()
    level = root.level
    yield
    for handler in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(handler)
    root.setLevel(level)
    structlog.reset_defaults()
