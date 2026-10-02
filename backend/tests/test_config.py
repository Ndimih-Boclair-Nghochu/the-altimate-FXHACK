from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from fxbot.config import ALLOW_LIVE_TRADING_ENV, ENV_PREFIX, Settings, get_settings
from tests.fakes import FakeOandaCredentials


def set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def live_env(fake_oanda: FakeOandaCredentials) -> dict[str, str]:
    """Every variable live trading needs; tests remove one at a time."""
    return {
        "FXBOT_TRADING_MODE": "live",
        "ALLOW_LIVE_TRADING": "true",
        "FXBOT_LIVE_TRADING_CONFIRMED": "true",
        **fake_oanda.env(),
    }


def test_defaults_are_safe() -> None:
    settings = Settings()

    assert settings.trading_mode == "paper"
    assert settings.allow_live_trading is False
    assert settings.live_trading_confirmed is False
    assert settings.oanda_account_id is None
    assert settings.oanda_api_token is None
    assert settings.has_oanda_credentials is False
    assert settings.database_url == "sqlite+aiosqlite:///./data/fxbot.db"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.log_level == "INFO"
    assert settings.log_json is False


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(
        monkeypatch,
        {
            "FXBOT_API_PORT": "9001",
            "FXBOT_LOG_LEVEL": "debug",
            "FXBOT_LOG_JSON": "true",
            "FXBOT_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        },
    )

    settings = Settings()

    assert settings.api_port == 9001
    assert settings.log_level == "DEBUG"
    assert settings.log_json is True
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"


@pytest.mark.parametrize(
    "raw",
    ["http://a.test, http://b.test", '["http://a.test", "http://b.test"]'],
    ids=["comma-separated", "json"],
)
def test_cors_origins_accept_csv_or_json(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("FXBOT_CORS_ORIGINS", raw)

    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_reads_dotenv_file_in_working_directory(
    tmp_path: Path, fake_oanda: FakeOandaCredentials
) -> None:
    lines = ["FXBOT_TRADING_MODE=practice", "UNRELATED_SETTING=ignored"]
    lines += [f"{name}={value}" for name, value in fake_oanda.env().items()]
    (tmp_path / ".env").write_text("\n".join(lines) + "\n")

    settings = Settings()

    assert settings.trading_mode == "practice"
    assert settings.oanda_api_token is not None
    assert settings.oanda_api_token.get_secret_value() == fake_oanda.api_token


def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FXBOT_TRADING_MODE", "yolo")

    with pytest.raises(ValidationError, match="trading_mode"):
        Settings()


def test_allow_live_trading_is_read_without_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FXBOT_ALLOW_LIVE_TRADING", "true")
    assert Settings().allow_live_trading is False

    monkeypatch.setenv("ALLOW_LIVE_TRADING", "true")
    assert Settings().allow_live_trading is True


@pytest.mark.parametrize("provided", ["none", "FXBOT_OANDA_ACCOUNT_ID", "FXBOT_OANDA_API_TOKEN"])
def test_practice_requires_both_credentials(
    monkeypatch: pytest.MonkeyPatch, fake_oanda: FakeOandaCredentials, provided: str
) -> None:
    monkeypatch.setenv("FXBOT_TRADING_MODE", "practice")
    if provided != "none":
        monkeypatch.setenv(provided, fake_oanda.env()[provided])

    with pytest.raises(ValidationError, match="practice") as excinfo:
        Settings()

    missing = {"FXBOT_OANDA_ACCOUNT_ID", "FXBOT_OANDA_API_TOKEN"} - {provided}
    for name in missing:
        assert name in str(excinfo.value)


def test_blank_credentials_count_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(
        monkeypatch,
        {
            "FXBOT_TRADING_MODE": "practice",
            "FXBOT_OANDA_ACCOUNT_ID": "",
            "FXBOT_OANDA_API_TOKEN": "   ",
        },
    )

    with pytest.raises(ValidationError, match="practice"):
        Settings()


def test_practice_with_credentials_is_accepted(
    monkeypatch: pytest.MonkeyPatch, fake_oanda: FakeOandaCredentials
) -> None:
    set_env(monkeypatch, {"FXBOT_TRADING_MODE": "practice", **fake_oanda.env()})

    settings = Settings()

    assert settings.trading_mode == "practice"
    assert settings.has_oanda_credentials


@pytest.mark.parametrize(
    ("unset", "reason"),
    [
        ("ALLOW_LIVE_TRADING", "ALLOW_LIVE_TRADING=true"),
        ("FXBOT_LIVE_TRADING_CONFIRMED", "FXBOT_LIVE_TRADING_CONFIRMED=true"),
        ("FXBOT_OANDA_ACCOUNT_ID", "FXBOT_OANDA_ACCOUNT_ID"),
        ("FXBOT_OANDA_API_TOKEN", "FXBOT_OANDA_API_TOKEN"),
    ],
)
def test_live_is_refused_unless_every_gate_is_set(
    monkeypatch: pytest.MonkeyPatch, live_env: dict[str, str], unset: str, reason: str
) -> None:
    del live_env[unset]
    set_env(monkeypatch, live_env)

    with pytest.raises(ValidationError, match="refusing to start in trading_mode 'live'") as exc:
        Settings()

    assert reason in str(exc.value)


@pytest.mark.parametrize("value", ["false", "0", "no"])
def test_live_is_refused_when_allow_live_trading_is_false(
    monkeypatch: pytest.MonkeyPatch, live_env: dict[str, str], value: str
) -> None:
    set_env(monkeypatch, {**live_env, "ALLOW_LIVE_TRADING": value})

    with pytest.raises(ValidationError, match="ALLOW_LIVE_TRADING"):
        Settings()


def test_live_with_every_gate_set_is_accepted(
    monkeypatch: pytest.MonkeyPatch, live_env: dict[str, str]
) -> None:
    set_env(monkeypatch, live_env)

    settings = Settings()

    assert settings.trading_mode == "live"
    assert settings.allow_live_trading is True
    assert settings.live_trading_confirmed is True
    assert settings.has_oanda_credentials


def test_secrets_are_not_rendered(
    monkeypatch: pytest.MonkeyPatch, fake_oanda: FakeOandaCredentials
) -> None:
    set_env(monkeypatch, {"FXBOT_TRADING_MODE": "practice", **fake_oanda.env()})

    settings = Settings()

    for text in (
        repr(settings),
        str(settings),
        settings.model_dump_json(),
        str(settings.model_dump()),
    ):
        fake_oanda.assert_absent_from(text)
    assert settings.oanda_api_token is not None
    assert settings.oanda_api_token.get_secret_value() == fake_oanda.api_token


def test_validation_errors_do_not_echo_secrets(
    monkeypatch: pytest.MonkeyPatch, live_env: dict[str, str]
) -> None:
    del live_env["ALLOW_LIVE_TRADING"]
    set_env(monkeypatch, live_env)

    with pytest.raises(ValidationError) as exc:
        Settings()

    # str() is what reaches logs and the console. Note that ValidationError.errors() still
    # carries the raw input; call it with include_input=False wherever it is surfaced.
    FakeOandaCredentials().assert_absent_from(str(exc.value))


def test_settings_are_immutable() -> None:
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.trading_mode = "live"  # type: ignore[misc]


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    first = get_settings()
    monkeypatch.setenv("FXBOT_API_PORT", "9999")

    assert get_settings() is first

    get_settings.cache_clear()
    assert get_settings().api_port == 9999


def test_env_example_documents_every_setting_with_safe_defaults() -> None:
    example = Path(__file__).parents[1] / ".env.example"
    documented = {
        line.split("=", 1)[0]
        for line in example.read_text().splitlines()
        if line and not line.startswith("#")
    }

    expected = {
        ALLOW_LIVE_TRADING_ENV if name == "allow_live_trading" else f"{ENV_PREFIX}{name.upper()}"
        for name in Settings.model_fields
    }
    assert documented == expected
    assert Settings(_env_file=example) == Settings(_env_file=None)
