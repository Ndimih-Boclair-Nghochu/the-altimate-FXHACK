from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from fxbot import __version__
from fxbot.api.app import create_app
from fxbot.config import Settings
from fxbot.domain.enums import Mode
from tests.fakes import FakeOandaCredentials

ClientFactory = Callable[[Settings], AsyncClient]


@pytest.fixture
def client_for() -> ClientFactory:
    def make(settings: Settings) -> AsyncClient:
        transport = ASGITransport(app=create_app(settings))
        return AsyncClient(transport=transport, base_url="http://testserver")

    return make


@pytest.fixture
def practice_settings(fake_oanda: FakeOandaCredentials) -> Settings:
    return Settings(
        trading_mode=Mode.PRACTICE,
        oanda_account_id=SecretStr(fake_oanda.account_id),
        oanda_api_token=SecretStr(fake_oanda.api_token),
    )


async def test_health_reports_status_version_and_mode(client_for: ClientFactory) -> None:
    async with client_for(Settings()) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "mode": "paper"}


async def test_health_reports_live_mode(
    monkeypatch: pytest.MonkeyPatch, client_for: ClientFactory, fake_oanda: FakeOandaCredentials
) -> None:
    for name, value in fake_oanda.live_env().items():
        monkeypatch.setenv(name, value)
    settings = Settings()

    async with client_for(settings) as client:
        response = await client.get("/api/health")

    assert response.json()["mode"] == "live"


@pytest.mark.parametrize("path", ["/api/health", "/api/openapi.json", "/api/docs"])
async def test_responses_never_contain_secrets(
    client_for: ClientFactory,
    practice_settings: Settings,
    fake_oanda: FakeOandaCredentials,
    path: str,
) -> None:
    async with client_for(practice_settings) as client:
        response = await client.get(path)

    assert response.status_code == 200
    fake_oanda.assert_absent_from(response.text)
    fake_oanda.assert_absent_from(str(response.headers))


async def test_create_app_defaults_to_process_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FXBOT_LOG_LEVEL", "DEBUG")

    app = create_app()

    assert app.state.settings.log_level == "DEBUG"


async def test_cors_allows_configured_origin(client_for: ClientFactory) -> None:
    settings = Settings(cors_origins=["http://localhost:5173"])
    preflight = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    }

    async with client_for(settings) as client:
        response = await client.options("/api/health", headers=preflight)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_cors_rejects_unknown_origin(client_for: ClientFactory) -> None:
    preflight = {
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "GET",
    }

    async with client_for(Settings()) as client:
        response = await client.options("/api/health", headers=preflight)
        simple = await client.get("/api/health", headers={"Origin": "https://evil.example"})

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-origin" not in simple.headers
