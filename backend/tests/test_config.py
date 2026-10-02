from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from fxbot.config import (
    ALLOW_LIVE_TRADING_ENV,
    ENV_PREFIX,
    DataFeedKind,
    Settings,
    get_settings,
    live_trading_problems,
    secret_equals,
)
from fxbot.domain.enums import Mode
from tests.fakes import FakeOandaCredentials


def set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def live_env(fake_oanda: FakeOandaCredentials) -> dict[str, str]:
    """Every variable live trading needs; tests remove or change one at a time."""
    return fake_oanda.live_env()


def test_defaults_are_safe(tmp_path: Path) -> None:
    settings = Settings()

    assert settings.trading_mode is Mode.PAPER
    assert settings.allow_live_trading is False
    assert settings.live_trading_confirmed is False
    assert settings.live_confirm_account_id is None
    assert settings.oanda_account_id is None
    assert settings.oanda_api_token is None
    assert settings.has_oanda_credentials is False
    assert settings.data_feed is DataFeedKind.SYNTHETIC
    assert settings.data_dir == Path("data")
    assert settings.database_url is None
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.log_level == "INFO"
    assert settings.log_json is False


def test_default_database_is_sqlite_in_the_data_dir(tmp_path: Path) -> None:
    url = Settings().resolved_database_url

    assert url.startswith("sqlite+aiosqlite:///")
    assert url.endswith((tmp_path / "data" / "fxbot.db").resolve().as_posix())


def test_explicit_database_url_wins() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")

    assert settings.resolved_database_url == "sqlite+aiosqlite:///:memory:"


@pytest.mark.parametrize(
    "url",
    ["postgresql+asyncpg://fx:hunter2@db/fx", "not a url"],
    ids=["password-in-url", "garbage"],
)
def test_unsafe_or_invalid_database_urls_are_refused(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("FXBOT_DATABASE_URL", url)

    with pytest.raises(ValidationError, match="database_url") as exc:
        Settings()

    assert "hunter2" not in str(exc.value)


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(
        monkeypatch,
        {
            "FXBOT_API_PORT": "9001",
            "FXBOT_LOG_LEVEL": "debug",
            "FXBOT_LOG_JSON": "true",
            "FXBOT_DATA_FEED": "replay",
            "FXBOT_DATA_DIR": "elsewhere",
        },
    )

    settings = Settings()

    assert settings.api_port == 9001
    assert settings.log_level == "DEBUG"
    assert settings.log_json is True
    assert settings.data_feed is DataFeedKind.REPLAY
    assert settings.data_dir == Path("elsewhere")


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
    (tmp_path / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")

    settings = Settings()

    assert settings.trading_mode is Mode.PRACTICE
    assert settings.oanda_api_token is not None
    assert settings.oanda_api_token.get_secret_value() == fake_oanda.api_token


def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FXBOT_TRADING_MODE", "yolo")

    with pytest.raises(ValidationError, match="trading_mode"):
        Settings()


def test_rejects_malformed_account_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FXBOT_OANDA_ACCOUNT_ID", "not-an-account")

    with pytest.raises(ValidationError, match="not an OANDA account id"):
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

    assert settings.trading_mode is Mode.PRACTICE
    assert settings.has_oanda_credentials


def test_paper_with_oanda_data_feed_needs_credentials(
    monkeypatch: pytest.MonkeyPatch, fake_oanda: FakeOandaCredentials
) -> None:
    monkeypatch.setenv("FXBOT_DATA_FEED", "oanda")

    with pytest.raises(ValidationError, match="data_feed 'oanda'"):
        Settings()

    set_env(monkeypatch, fake_oanda.env())
    assert Settings().data_feed is DataFeedKind.OANDA


@pytest.mark.parametrize(
    ("unset", "reason"),
    [
        ("ALLOW_LIVE_TRADING", "ALLOW_LIVE_TRADING=true"),
        ("FXBOT_LIVE_TRADING_CONFIRMED", "FXBOT_LIVE_TRADING_CONFIRMED=true"),
        ("FXBOT_LIVE_CONFIRM_ACCOUNT_ID", "FXBOT_LIVE_CONFIRM_ACCOUNT_ID is not set"),
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


def test_live_is_refused_when_confirmation_names_another_account(
    monkeypatch: pytest.MonkeyPatch, live_env: dict[str, str], fake_oanda: FakeOandaCredentials
) -> None:
    set_env(monkeypatch, {**live_env, "FXBOT_LIVE_CONFIRM_ACCOUNT_ID": fake_oanda.other_account_id})

    with pytest.raises(ValidationError, match="does not match FXBOT_OANDA_ACCOUNT_ID") as exc:
        Settings()

    fake_oanda.assert_absent_from(str(exc.value))
    assert fake_oanda.other_account_id not in str(exc.value)


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

    assert settings.trading_mode is Mode.LIVE
    assert live_trading_problems(settings) == []


def test_live_checks_hold_for_settings_that_skipped_validation(
    fake_oanda: FakeOandaCredentials,
) -> None:
    # Truthy non-booleans must not pass for "true".
    unvalidated = Settings.model_construct(
        trading_mode=Mode.LIVE,
        allow_live_trading="false",  # type: ignore[arg-type]
        live_trading_confirmed=1,  # type: ignore[arg-type]
        oanda_account_id=SecretStr(fake_oanda.account_id),
        oanda_api_token=SecretStr(fake_oanda.api_token),
        live_confirm_account_id=SecretStr(fake_oanda.other_account_id),
    )

    problems = live_trading_problems(unvalidated)

    assert len(problems) == 3
    assert any("does not match" in p for p in problems)


def test_secret_equals_is_strict() -> None:
    assert secret_equals(SecretStr("a"), SecretStr("a"))
    assert not secret_equals(SecretStr("a"), SecretStr("b"))
    assert not secret_equals(SecretStr(""), SecretStr(""))
    assert not secret_equals("a", SecretStr("a"))
    assert not secret_equals(None, None)


def test_secrets_are_not_rendered(
    monkeypatch: pytest.MonkeyPatch, live_env: dict[str, str], fake_oanda: FakeOandaCredentials
) -> None:
    set_env(monkeypatch, live_env)

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
    monkeypatch: pytest.MonkeyPatch, live_env: dict[str, str], fake_oanda: FakeOandaCredentials
) -> None:
    del live_env["ALLOW_LIVE_TRADING"]
    set_env(monkeypatch, live_env)

    with pytest.raises(ValidationError) as exc:
        Settings()

    # str() is what reaches logs and the console. Note that ValidationError.errors() still
    # carries the raw input; call it with include_input=False wherever it is surfaced.
    fake_oanda.assert_absent_from(str(exc.value))


def test_settings_are_immutable() -> None:
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.trading_mode = Mode.LIVE  # type: ignore[misc]


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
        for line in example.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }

    expected = {
        ALLOW_LIVE_TRADING_ENV if name == "allow_live_trading" else f"{ENV_PREFIX}{name.upper()}"
        for name in Settings.model_fields
    }
    assert documented == expected
    assert Settings(_env_file=example) == Settings(_env_file=None)
