from __future__ import annotations

import runpy
from pathlib import Path
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
    env = {**fake_oanda.live_env(), "FXBOT_LOG_JSON": "true"}
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


# ------------------------------------------------------------------------- data commands


def test_data_fetch_validation_list(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["data", "fetch-validation", "--list"])

    out = capsys.readouterr().out
    assert "lean-oanda-eurusd-h1\tEUR_USD\tH1\tlean-oanda" in out


def test_data_fetch_validation_downloads_and_loads(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from fxbot.data import validation
    from tests.data.test_validation import LEAN_ROWS, install, lean_zip

    spec = install(monkeypatch, tmp_path / "data", "lean-oanda-eurusd-h1", lean_zip(LEAN_ROWS))

    cli.main(["data", "fetch-validation", "--dataset", spec.name, "--load"])

    out = capsys.readouterr().out
    assert f"present    {spec.files[0].filename}" in out
    assert f"loaded     {spec.name}: 2 candles, 0 rows rejected" in out
    assert (tmp_path / "data" / "fxbot.db").exists()
    assert validation.DATASETS[spec.name] is spec


def test_data_fetch_downloads_into_the_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    import respx

    from fxbot.data import commands
    from tests.support import PRACTICE, practice_client

    router = respx.Router(base_url=PRACTICE.rest)
    router.get("/v3/instruments/EUR_USD/candles").respond(
        json={
            "candles": [
                {
                    "time": "2024-03-04T00:00:00.000000000Z",
                    "bid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.1"},
                    "ask": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.1"},
                    "volume": 1,
                    "complete": True,
                }
            ]
        }
    )
    monkeypatch.setattr(commands, "build_oanda_client", lambda settings: practice_client(router))

    cli.main(["data", "fetch", "--instrument", "EUR_USD", "--from", "2024-03-04"])

    assert "stored 1 EUR_USD H1 candles" in capsys.readouterr().out
    assert (tmp_path / "data" / "fxbot.db").exists()


def test_data_fetch_without_credentials_fails_cleanly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["data", "fetch", "--instrument", "EUR_USD", "--from", "2024-03-04T00:00+02:00"])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "credentials missing" in err and "Traceback" not in err


@pytest.mark.parametrize(
    "argv",
    [
        ["data", "fetch", "--instrument", "eurusd", "--from", "2024-01-01"],
        ["data", "fetch", "--instrument", "EUR_USD", "--from", "yesterday"],
        ["data", "fetch", "--instrument", "EUR_USD", "--from", "2024-01-01", "--granularity", "D"],
    ],
)
def test_data_fetch_validates_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)

    assert exc.value.code == 2
