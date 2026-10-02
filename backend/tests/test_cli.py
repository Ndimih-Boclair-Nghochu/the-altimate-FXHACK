from __future__ import annotations

import runpy
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI

from fxbot import __version__, cli
from tests.fakes import FakeOandaCredentials


class FakeUvicornRun:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, app: Any, **kwargs: Any) -> None:
        self.calls.append((app, kwargs))


@pytest.fixture
def uvicorn_run(monkeypatch: pytest.MonkeyPatch) -> FakeUvicornRun:
    fake = FakeUvicornRun()
    monkeypatch.setattr(uvicorn, "run", fake)
    return fake


def test_serves_the_app_on_configured_host_and_port(
    monkeypatch: pytest.MonkeyPatch, uvicorn_run: FakeUvicornRun
) -> None:
    monkeypatch.setenv("FXBOT_API_PORT", "8123")

    cli.main([])

    ((app, kwargs),) = uvicorn_run.calls
    assert isinstance(app, FastAPI)
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8123
    assert kwargs["log_config"] is None


def test_live_mode_logs_a_warning_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    uvicorn_run: FakeUvicornRun,
    fake_oanda: FakeOandaCredentials,
) -> None:
    env = {
        "FXBOT_TRADING_MODE": "live",
        "ALLOW_LIVE_TRADING": "true",
        "FXBOT_LIVE_TRADING_CONFIRMED": "true",
        "FXBOT_LOG_JSON": "true",
        **fake_oanda.env(),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    cli.main([])

    output = capsys.readouterr().out
    assert "real money" in output
    fake_oanda.assert_absent_from(output)
    assert len(uvicorn_run.calls) == 1


def test_invalid_configuration_exits_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    uvicorn_run: FakeUvicornRun,
) -> None:
    monkeypatch.setenv("FXBOT_TRADING_MODE", "live")

    with pytest.raises(SystemExit) as exc:
        cli.main([])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid configuration" in err
    assert "ALLOW_LIVE_TRADING" in err
    assert "Traceback" not in err
    assert uvicorn_run.calls == []


def test_python_dash_m_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["fxbot", "--version"])

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("fxbot", run_name="__main__")

    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out
