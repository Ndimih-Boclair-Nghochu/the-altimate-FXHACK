from __future__ import annotations

import logging
import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _is_loopback(address: Any) -> bool:
    # AF_UNIX addresses are paths (str/bytes); inet addresses are (host, port, ...) tuples.
    if not isinstance(address, tuple):
        return True
    return str(address[0]) in _LOOPBACK_HOSTS


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that tries to reach a non-loopback host. Broker I/O must be mocked."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if not _is_loopback(address):
            raise RuntimeError(f"tests must not open network connections (attempted {address!r})")
        original_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        if not _is_loopback(address):
            raise RuntimeError(f"tests must not open network connections (attempted {address!r})")
        return original_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
