# Stage 1 security review: findings, fixes and suggested tests

Scope:
- Commit `37f3aeb` ("Stage 1: broker connectivity and market data"), reviewed on `0a6361a`.
- Code reviewed: `backend/src/fxbot/{domain,brokers,data,persistence}`, `config.py`, `logging.py`,
  `cli.py`, and their tests.
- Checklist: `docs/security/review-checklist.md` sections 0 and 1.

The summary and status of each finding live in `docs/SECURITY.md` §11. This file holds the detail
the backend agent needs to fix them.

How the probes were run: every suggested test below was run against `37f3aeb` from outside the
repository, with the repo's `tests/conftest.py` loaded as a plugin, and fails for the reason
given. Once the test is copied into `backend/tests/`, plain `uv run pytest` runs it:

```sh
cd backend && PYTHONPATH=$PWD uv run --frozen pytest /path/to/probe.py -c pyproject.toml --rootdir . -p tests.conftest -o addopts=""
```

Checklist results:
- **Clean:** 0-1 to 0-9 and 1-1 to 1-20. Gitleaks (history and working tree), the fixture guard,
  `pip-audit` (all groups) and `npm audit` all report nothing; 353 tests pass with 96.8 % coverage.
- **Item 1-2** has four hits, all justified:
  - `client.py:163` builds the auth header;
  - `client.py:199` builds the account path;
  - `client.py:203` and `config.py:181` are constant-time compares.
- **Item 1-13:** the client ID, `stopLossOnFill`, `priceBound` and FOK are all present.

---

## F1-1 (High): exceptions after an accepted order POST escape `submit_order`

**Location:**
- `backend/src/fxbot/brokers/oanda/adapter.py:257-268`: post-POST parsing and protection.
- `adapter.py:293-297`: `_ensure_stop`. Its `except BrokerError` is too narrow, and the fallback
  `close_trade` is unguarded.

**Failure scenarios (all reproduced):**

1. The order fills without a stop. Then `PUT /trades/{id}/orders` fails (503) and the fallback
   `PUT /trades/{id}/close` fails (503). `BrokerUnavailableError` escapes `submit_order`.
2. The second trade read inside `modify_trade_exits` is unparseable. `DataIntegrityError` is not a
   `BrokerError`, so it escapes `_ensure_stop` **without the close fallback ever running**.
3. The 201 response has a non-finite price, or a field `order_result` rejects. `DataIntegrityError`
   escapes after the order has filled. (A 201 naming another account raises
   `BrokerAccountMismatchError` in the same place.)

**Impact:** the caller gets an exception for an order that **filled**. The fill and trade ID are
lost. In cases 1 and 2 the position may have no broker-side stop, and the only record is a log line.
A Stage 5 order manager that treats the exception as "failed" journals nothing, so reconciliation
later sees a local trade it never knew about.

**Fix:**
- Once the POST may have been processed, `submit_order` must not raise, except for auth errors and
  the account mismatch (fatal).
- Parse the 201 inside `try/except Exception`. On failure, log at ERROR and
  `return await self._resolve_unknown(client_id)`, which yields FILLED, CANCELLED or UNKNOWN by
  client-ID lookup.
- `_ensure_stop` catches `Exception` (not only `BrokerError`) around both the attach and the
  close. It never raises, and reports a protection outcome (see F1-2).
- Contract for Stage 5 (SR-17): `OrderManager` persists the order before sending (as the
  architecture already says). It treats **any** exception from `submit_order` as `UNKNOWN` and
  reconciles before anything else. `BrokerAccountMismatchError` engages the kill switch.

**Suggested tests:**

```python
# backend/tests/brokers/oanda/test_order_protection.py  (rename Protection/fields to match the fix)
from __future__ import annotations

import logging
from decimal import Decimal as D

import pytest
import respx

from fxbot.brokers.oanda.adapter import OandaBroker
from fxbot.domain.enums import OrderStatus, Protection, Side  # Protection: proposed, see F1-2
from fxbot.domain.models import OrderRequest
from tests.fake_oanda import FakeOandaServer
from tests.support import ACCOUNT_PATH, PRACTICE, fixture, practice_client

CLIENT_ID = "afx-7f3c2a"


def market_order(**overrides: object) -> OrderRequest:
    fields: dict[str, object] = {
        "client_id": CLIENT_ID, "instrument": "EUR_USD", "side": Side.BUY, "units": D("12000"),
        "stop_loss": D("1.160104"), "take_profit": D("1.171496"), "price_bound": D("1.164"),
        "strategy_id": "trend_breakout_h4", "signal_id": "2024-03-04T12:00Z",
    }
    fields.update(overrides)
    return OrderRequest(**fields)  # type: ignore[arg-type]


def unprotected_trade() -> dict[str, object]:
    return fixture("open_trades.json")["trades"][1] | {"id": "23", "instrument": "EUR_USD"}


def filled_router() -> respx.Router:
    router = respx.Router(base_url=PRACTICE.rest)
    router.get(f"{ACCOUNT_PATH}/orders/@{CLIENT_ID}").respond(404, json={})
    router.get(f"{ACCOUNT_PATH}/instruments").respond(json=fixture("instruments.json"))
    router.post(f"{ACCOUNT_PATH}/orders").respond(201, json=fixture("order_filled.json"))
    return router


async def test_fill_is_returned_when_attach_and_close_both_fail() -> None:
    router = filled_router()
    router.get(f"{ACCOUNT_PATH}/trades/23").respond(json={"trade": unprotected_trade()})
    router.put(f"{ACCOUNT_PATH}/trades/23/orders").respond(503, json={"errorMessage": "down"})
    router.put(f"{ACCOUNT_PATH}/trades/23/close").respond(503, json={"errorMessage": "down"})
    broker = OandaBroker(practice_client(router, attempts=1))

    result = await broker.submit_order(market_order())  # 37f3aeb: BrokerUnavailableError

    assert result.status is OrderStatus.FILLED and result.fill is not None
    assert result.protection is Protection.UNPROTECTED


async def test_close_fallback_runs_for_any_attach_failure() -> None:
    router = filled_router()
    router.get(f"{ACCOUNT_PATH}/trades/23").side_effect = [
        respx.MockResponse(json={"trade": unprotected_trade()}),
        respx.MockResponse(json={"trade": {"id": "23"}}),  # unparseable on the second read
    ]
    close_body = fixture("trade_close.json")
    close_body["orderFillTransaction"]["tradesClosed"][0]["tradeID"] = "23"
    close = router.put(f"{ACCOUNT_PATH}/trades/23/close").respond(json=close_body)
    broker = OandaBroker(practice_client(router, attempts=1))

    result = await broker.submit_order(market_order())  # 37f3aeb: DataIntegrityError, no close

    assert close.called
    assert result.protection is Protection.CLOSED


async def test_unreadable_201_is_resolved_by_lookup() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    router.get(f"{ACCOUNT_PATH}/orders/@{CLIENT_ID}").side_effect = [
        respx.MockResponse(404, json={}),
        respx.MockResponse(json=fixture("order_by_client_id_filled.json")),
    ]
    router.get(f"{ACCOUNT_PATH}/instruments").respond(json=fixture("instruments.json"))
    router.get(f"{ACCOUNT_PATH}/transactions/23").respond(
        json={"transaction": fixture("order_filled.json")["orderFillTransaction"]}
    )
    broken = fixture("order_filled.json")
    broken["orderFillTransaction"]["price"] = "NaN"
    broken["orderFillTransaction"]["tradeOpened"]["price"] = "NaN"
    router.post(f"{ACCOUNT_PATH}/orders").respond(201, json=broken)
    router.get(f"{ACCOUNT_PATH}/trades/23").respond(
        json={"trade": unprotected_trade() | {"stopLossOrder": {"price": "1.16010"}}}
    )
    broker = OandaBroker(practice_client(router, attempts=1))

    result = await broker.submit_order(market_order())  # 37f3aeb: DataIntegrityError

    assert result.status is OrderStatus.FILLED
```

---

## F1-2 (High): stop verification is skipped on the lookup paths and silent when it fails

**Location:**
- `adapter.py:232-235`: an order already known to the broker is returned without a check.
- `adapter.py:245-247` and `270-279`: a fill resolved by client-ID lookup after a timeout or 5xx
  is returned without a check.
- `adapter.py:286-289`: an unreadable trade is logged at WARNING and the function returns.
- `adapter.py:266-268`: the result says `FILLED` even when `_ensure_stop` closed the trade. The
  existing test `test_fill_whose_stop_cannot_be_attached_is_closed` asserts exactly that.

**Failure scenario (reproduced with `FakeOandaServer`):**
1. The POST times out *after* the broker filled the order but dropped the stop
   (`fail_next_order="timeout_after"`, `drop_stop_on_fill=True`).
2. `_resolve_unknown` finds the fill and returns `FILLED`.
3. `_ensure_stop` never runs, so the position has no stop.

The design rule "every position has a broker-side stop" (ARCHITECTURE §1.3) silently fails. For
OANDA this is unlikely because `stopLossOnFill` is atomic. For MT5, whether brokers keep SL on
Market-Execution deals is unverified (research 08 §A.8), and Stage 1b will reuse this pattern.

**Fix:**
- Verify protection for **every** `FILLED` result, whichever path produced it: fresh, already
  existing, or resolved by lookup.
- Add a protection outcome to `OrderResult`, for example
  `Protection = VERIFIED | ATTACHED | CLOSED | UNPROTECTED | UNVERIFIED`. When the trade was
  closed, carry the closing fill.
- Log `UNVERIFIED` and `UNPROTECTED` at CRITICAL. Stage 5 pauses entries and re-verifies or
  flattens. `CLOSED` must not be journaled as an open trade.
- Fix sketch:

```python
async def _protect(self, fill: Fill, order: OrderRequest) -> tuple[Protection, Fill | None]:
    try:
        trade = (await self._client.get_trade(fill.trade_id)).get("trade") or {}
    except Exception:  # noqa: BLE001 - fail-safe: report, never raise
        log.critical("could not verify the stop after a fill", trade_id=fill.trade_id)
        return Protection.UNVERIFIED, None
    if trade.get("state", "OPEN") != "OPEN":
        return Protection.CLOSED, None
    if trade_has_stop_loss(trade):
        return Protection.VERIFIED, None
    try:
        await self.modify_trade_exits(fill.trade_id, stop_loss=order.stop_loss)
        return Protection.ATTACHED, None
    except Exception:  # noqa: BLE001
        log.critical("could not attach a stop; closing the trade", trade_id=fill.trade_id)
    try:
        return Protection.CLOSED, await self.close_trade(fill.trade_id)
    except Exception:  # noqa: BLE001
        log.critical("trade has no stop and could not be closed", trade_id=fill.trade_id)
        return Protection.UNPROTECTED, None
```

**Suggested tests** (same module as F1-1):

```python
async def test_fill_resolved_after_timeout_is_still_protected() -> None:
    server = FakeOandaServer()
    server.set_price("EUR_USD", "1.16300", "1.16310")
    server.drop_stop_on_fill = True
    server.fail_next_order = "timeout_after"
    broker = OandaBroker(practice_client(server.router(), attempts=1))

    result = await broker.submit_order(market_order())

    assert result.status is OrderStatus.FILLED and result.fill is not None
    assert server.trades[result.fill.trade_id].stop_loss is not None  # 37f3aeb: None
    assert result.protection is Protection.ATTACHED


async def test_unverifiable_stop_is_reported(caplog: pytest.LogCaptureFixture) -> None:
    router = filled_router()
    router.get(f"{ACCOUNT_PATH}/trades/23").respond(503, json={"errorMessage": "down"})
    broker = OandaBroker(practice_client(router, attempts=1))

    with caplog.at_level(logging.WARNING):
        result = await broker.submit_order(market_order())

    assert result.protection is Protection.UNVERIFIED          # 37f3aeb: no signal at all
    assert any(r.levelno >= logging.CRITICAL for r in caplog.records)
```

---

## F1-3 (Medium): `ALLOW_LIVE_TRADING` is accepted from `.env`

**Location:**
- `backend/src/fxbot/config.py:49` (`env_file=".env"`) together with `config.py:60`
  (`validation_alias="ALLOW_LIVE_TRADING"`). pydantic-settings' dotenv source matches the alias.
- `backend/.env.example:17` lists `ALLOW_LIVE_TRADING=false` next to the other gates.

**Failure scenario (reproduced):** one `.env` file holds every live gate:
- `FXBOT_TRADING_MODE=live`
- `ALLOW_LIVE_TRADING=true`
- `FXBOT_LIVE_TRADING_CONFIRMED=true`
- `FXBOT_LIVE_CONFIRM_ACCOUNT_ID=<id>`
- the credentials

`Settings()` validates it as live.

Going live then becomes "edit one file". That file is the one operators copy between machines,
paste into support chats, and receive from "account managers" (§5 T-43). The brief requires the
flag *in the environment*, as a separate deliberate act.

**Fix:**
- Read `ALLOW_LIVE_TRADING` only from the process environment. Override
  `settings_customise_sources` to wrap the dotenv source and drop that key, or have
  `live_trading_problems()` check `os.environ.get("ALLOW_LIVE_TRADING")` directly. The broker
  factory re-runs the same check.
- If the file contains the key, log a WARNING that it is ignored.
- Remove the key from `.env.example`. Document how to set it for a live session or service
  (SR-68: in the service's environment, never in files under the repo).

**Suggested tests** (`backend/tests/test_config.py`):

```python
def test_allow_live_trading_is_ignored_in_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ALLOW_LIVE_TRADING=true\n", encoding="utf-8")
    assert Settings().allow_live_trading is False                     # 37f3aeb: True


def test_single_dotenv_cannot_enable_live(tmp_path, monkeypatch, fake_oanda) -> None:
    monkeypatch.chdir(tmp_path)
    lines = fake_oanda.live_env() | {"FXBOT_LIVE_CONFIRM_ACCOUNT_ID": fake_oanda.account_id}
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in lines.items()), "utf-8")
    with pytest.raises(ValueError, match="ALLOW_LIVE_TRADING"):       # 37f3aeb: no error
        Settings()
```

---

## F1-4 (Medium on Windows, Low on POSIX): data files are not private

**Location:**
- `backend/src/fxbot/persistence/db.py:41`: `mkdir(mode=0o700)` only affects the leaf directory.
  The DB file is created by SQLite with the process umask.
- `backend/src/fxbot/data/validation.py:249,270`: `chmod(0o600)` and `mkdir(mode=0o700)`.
- On Windows, `chmod` only toggles the read-only flag and `mode=` is ignored.

**Failure scenarios:**
- POSIX (reproduced): `fxbot.db`, `fxbot.db-wal` and `fxbot.db-shm` are created `0644`, readable
  by every local user.
- Windows VPS: a folder like `C:\fxbot` created by an administrator inherits ACLs that typically
  let local users read it. The same goes for `.env` (token, bridge secret) and the journal.
  From Stage 5 the journal holds balances, positions and sessions. From Stage 1b the bridge
  secret is the right to place orders (T-42, SR-68).

**Fix:**
- POSIX:
  - in `_prepare_sqlite_file`, create the DB file first with
    `os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)`. SQLite gives `-wal`/`-shm` the database
    file's permissions;
  - set `os.umask(0o077)` at the start of `cli.main` (covers logs, backups and later files).
- Windows: `0o600` gives false assurance. Document an explicit ACL in `docs/MT5_SETUP.md`
  (SR-68). SHOULD add a start-up check in live mode that warns when `.env` or `FXBOT_DATA_DIR`
  grants access to `Users`, `Everyone` or `Authenticated Users` (parse `icacls` output, or use
  pywin32 if it is added).

**Suggested test** (`backend/tests/persistence/test_db.py`):

```python
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes; Windows uses ACLs")
async def test_sqlite_files_are_owner_only(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'data' / 'fxbot.db').as_posix()}")
    await db.create_all()
    async with db.session() as session:
        await session.execute(sqlalchemy.text("select 1"))
        modes = {f.name: stat.S_IMODE(f.stat().st_mode) for f in (tmp_path / "data").iterdir()}
    await db.dispose()
    assert all(mode & 0o077 == 0 for mode in modes.values()), modes   # 37f3aeb: 0o644
```

---

## F1-5 (Low): the start-up account check is opt-in

**Location:** `adapter.py:95-116`. `OandaBroker.connect()` runs the SR-7 account-visibility check
and the MT4 refusal. Nothing in `src/` calls it, and `submit_order`, `close_trade` and `close_all`
work on a broker that never connected.

**Scenario:** an engine or CLI path (for example a future "close all" command) builds the broker
with `build_broker()` and trades without `connect()`. The per-response account check (SR-7) still
protects against data for another account. But the MT4-linked-account refusal and the logged
start-up identity (masked ID, currency, NAV) are skipped. For MT5 the equivalent check is the
interlock itself (SR-60), so this pattern must not carry over.

**Fix:** keep a `_connected` flag. Trading methods raise `ConfigurationError` until `connect()`
succeeds. Stage 5 calls `connect()` at start and after every reconnect.

```python
async def test_trading_requires_connect() -> None:
    server = FakeOandaServer()
    server.set_price("EUR_USD", "1.16300", "1.16310")
    broker = OandaBroker(practice_client(server.router()))
    with pytest.raises(ConfigurationError):                           # 37f3aeb: order placed
        await broker.submit_order(market_order())
```

---

## F1-6 (Info): the expected 404 on client-ID lookup is logged as a WARNING on every order

**Location:** `client.py:119` (`raise_for_status` logs every non-2xx at WARNING), reached from
`adapter.py:171` on each submit.

**Impact:** every order emits `oanda request failed … status=404`. Real warnings, such as the
`_ensure_stop` ones before F1-2 is fixed, drown in routine noise, and the ops habit becomes
ignoring WARNINGs.

**Fix:** log 4xx at DEBUG when the caller expects it. For example, `find_order` passes
`expected_status={404}`, or `raise_for_status` takes a log level.

---

## Notes for Stage 5 (no fix needed in Stage 1)

- `close_all` logs and skips positions it fails to close (`adapter.py:344-350`).
  `OrderManager.flatten_all` must re-read positions and retry until flat (SR-19).
- `OrderResult.closed` (an entry that reduced existing trades) is logged at ERROR. Stage 5 should
  treat it as a `CRITICAL` reconciliation event.

## Closed from Stage 0

- **F0-1:** the account-bound confirmation is implemented in `config.py` and in the broker
  factory. `FXBOT_LIVE_TRADING_CONFIRMED` is kept as an extra gate.
- **F0-2:** all actions are SHA-pinned, including the new Windows job.
- **F0-5:** a password in the database URL is refused.
- **F0-6:** the ROADMAP is aligned.
