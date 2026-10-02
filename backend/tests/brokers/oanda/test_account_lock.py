"""SR-7: the adapter only ever addresses, and only accepts data for, the configured account."""

from __future__ import annotations

import httpx
import pytest
import respx

from fxbot.brokers.oanda.adapter import OandaBroker
from fxbot.domain.errors import BrokerAccountMismatchError, ConfigurationError
from tests.fake_oanda import FakeOandaServer
from tests.support import ACCOUNT_PATH, CREDENTIALS, PRACTICE, fixture, practice_client


async def test_every_request_targets_the_configured_account() -> None:
    server = FakeOandaServer()
    server.set_price("EUR_USD", "1.10000", "1.10010")
    broker = OandaBroker(practice_client(server.router()))

    await broker.connect()
    await broker.get_open_trades()
    await broker.get_positions()
    await broker.get_transactions_since("100")
    await broker.find_order("afx-none")

    paths = [request.url.path for request in server.requests]
    assert paths[0] == "/v3/accounts"  # the start-up check is the only unscoped request
    assert all(path.startswith(f"{ACCOUNT_PATH}/") for path in paths[1:])


async def test_connect_refuses_an_account_the_token_cannot_see() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    router.get("/v3/accounts").respond(
        json={"accounts": [{"id": CREDENTIALS.other_account_id, "tags": []}]}
    )
    broker = OandaBroker(practice_client(router))

    with pytest.raises(ConfigurationError, match="not available to this token"):
        await broker.connect()


async def test_connect_refuses_mt4_linked_accounts() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    router.get("/v3/accounts").respond(
        json={"accounts": [{"id": CREDENTIALS.account_id, "mt4AccountID": 1, "tags": []}]}
    )

    with pytest.raises(ConfigurationError, match="MT4"):
        await OandaBroker(practice_client(router)).connect()


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/summary", {"account": {"id": CREDENTIALS.other_account_id}}),
        (
            "/transactions/sinceid",
            {"transactions": [{"id": "1", "accountID": CREDENTIALS.other_account_id}]},
        ),
    ],
    ids=["summary", "transactions"],
)
async def test_response_for_another_account_raises(path: str, body: dict[str, object]) -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    router.get(f"{ACCOUNT_PATH}{path}").respond(json=body)
    broker = OandaBroker(practice_client(router))

    with pytest.raises(BrokerAccountMismatchError) as exc:
        if path == "/summary":
            await broker.get_account()
        else:
            await broker.get_transactions_since("0")

    CREDENTIALS.assert_absent_from(str(exc.value))
    assert CREDENTIALS.other_account_id not in str(exc.value)


async def test_matching_account_ids_are_accepted() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    router.get(f"{ACCOUNT_PATH}/summary").respond(json=fixture("account_summary.json"))

    account = await OandaBroker(practice_client(router)).get_account()

    assert account.currency == "EUR"


def test_client_builds_paths_only_for_its_account() -> None:
    client = practice_client(respx.Router(base_url=PRACTICE.rest))

    assert client._account_path("/summary") == f"{ACCOUNT_PATH}/summary"
    assert client.is_configured_account(CREDENTIALS.account_id)
    assert not client.is_configured_account(CREDENTIALS.other_account_id)
    assert isinstance(client._rest, httpx.AsyncClient)
