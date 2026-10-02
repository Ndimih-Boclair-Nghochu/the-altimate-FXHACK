# 08 — MetaTrader 5: Python API reference, deployment, brokers for Cameroon, design implications

Status: research input for **Stage 1b** (MT5 adapter + local bridge). The user trades from
Cameroon on MetaTrader 5.

Same rules as the other reports: sources are cited, evidence is separated from opinion, and
anything not confirmed from a primary source is marked **UNVERIFIED**. No real logins,
passwords or account numbers appear here. Examples use obvious fakes (`login=12345678`), and
fields copied from public recordings are redacted.

**Summary.**

- **API.** The official `MetaTrader5` package is a thin IPC client (Windows named pipe) to a *running, logged-in* MT5 terminal on the same Windows machine.
  - Functions return a value, or `None` on failure, with the reason in `last_error()`.
  - Trading calls return an `OrderSendResult` whose `retcode` must be checked.
  - Bars are bid-based. Their `spread` column is (by community consensus) the bar's *minimum* spread.
  - Timestamps are the broker's **server clock** encoded as epoch seconds, despite the docs saying "UTC".
- **Deployment (recommended).**
  - One **Windows VPS** near the broker's servers runs the MT5 terminal, a **minimal authenticated "mt5-bridge" process bound to 127.0.0.1**, and our backend natively (no Docker).
  - The user's PC in Cameroon is only a browser.
  - This removes local power and internet outages from the trading path.
  - Never expose the bridge (or any RPyC/`mt5linux` server) to a network.
- **Brokers (opinion, caveats in §C).** Shortlist:
  - **Exness** (MT5, MTN/Orange Mobile Money reported for Cameroon, Seychelles entity);
  - **IC Markets or Pepperstone** (raw-spread MT5 accounts, strong group licences, offshore entity for Cameroon, no confirmed Mobile Money);
  - **HFM** as an alternative.
  - All of them will serve a Cameroon resident through an **offshore** entity with weaker protection than their EU/UK/AU entities.
- **Design.**
  - Build H4/D1 bars ourselves from H1 converted to UTC (New York close).
  - Use a conservative spread model, because ask = bid + bar spread is optimistic.
  - Require a **hedging** account.
  - Idempotency via `magic` + a ≤ 25-char `comment`.
  - Client-managed SL moves via `TRADE_ACTION_SLTP`.
  - A **minimum-equity check** (0.01-lot steps make 0.25% risk impossible on small accounts).
  - A faithful fake `MetaTrader5` module for tests.

---

## 0. Sources and trust

| Tag | Source | Use | Trust |
|---|---|---|---|
| [PKG] | `MetaTrader5` 5.0.6231 wheel from PyPI (`metatrader5-5.0.6231-cp311-cp311-win_amd64.whl`, uploaded 2026-09-27): `MetaTrader5/__init__.py` (all constants and their values), `METADATA`, and strings extracted from `_core.cp311-win_amd64.pyd` (function signatures, field names, error texts). https://pypi.org/project/MetaTrader5/ | Constants, signatures, error strings | **High** (the shipped artefact) |
| [DOC] | MQL5 Reference "Python Integration" pages and related MQL5 reference pages, read from the mirror `caoshuo594/mql5-help-mcp` (`MQL5_HELP/*.htm`, commit `5be8c67`, 2026-02-02), because `www.mql5.com` is blocked here. Official URLs follow the pattern https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py | Semantics, examples, recorded outputs | High (MetaQuotes text, via a mirror) |
| [BOOK] | "MQL5 Programming for Traders" (MetaQuotes book) ch. 7.9 Python, same mirror (`MQL5_Algo_Book/7_9_*`). Online: https://www.mql5.com/en/book/advanced/python | Python-API trading switch, examples | High |
| [REC] | Recorded outputs in public notebooks: QuantInsti webinars (`Automated Trading Using MT5 and Python.ipynb`), Quantreo `MetaTrader-5-AUTOMATED-TRADING-using-Python` (`03 Introduction .ipynb`, `04 Import financial data.ipynb`) | Real dtypes and field orders | High for shapes. Logins/names redacted here |
| [STUB] | `metatrader5-stubs` 0.1.3 (PyPI, 2026-07-20), unofficial PEP 561 stubs | Return types (`X \| None`) | Medium |
| [FORUM] | mql5.com forum threads and broker help pages, seen via web-search excerpts | Behaviour not in the reference | Medium–low, flagged |
| [OURS] | Our own computation on public datasets (`07-data-sources.md`) | Spread-derivation error, server-time convention | Reproducible |

---

## A. The `MetaTrader5` Python package: implementation reference

### A.1 Package facts

- Platform: **Windows only**. Wheels are `win_amd64` (also built for Python 3.6–3.14, `Requires-Python: >=3.6,<4`). Depends on `numpy>=1.7`. MIT licence. Author MetaQuotes [PKG].
- Transport: the compiled core talks to the terminal over a **Windows named pipe** (string `\\.\pipe\MT5.Terminal.` in the binary). It looks for installed terminals under `%APPDATA%\MetaQuotes\Terminal\`, reads `config\terminal.ini`, and can **launch `terminal64.exe`** itself (strings `"%s" /portable`, `Process create failed '%s'`, `Pipe server didn't answer in %u sec`, `MetaTrader 5 x64 not found`) [PKG].
- The module holds **one global connection** (functions are module-level, with no client object). One Python process = one terminal = one logged-in account. Multiple accounts need multiple terminal installations (portable mode, separate folders) and one process each (inference from the API shape. **UNVERIFIED** as an official statement).
- Requirements in the terminal (all confirmed in [DOC]/[BOOK]):
  - The **"Algo Trading"** button is on (`terminal_info().trade_allowed`), and `account_info().trade_allowed` / `trade_expert` are true.
  - Tools → Options → Expert Advisors → **"Disable automatic trading via external Python API"** is *unchecked*. [BOOK] 7.9: "When this option is enabled, trading function calls in a Python script will return error 10027 (TRADE_RETCODE_CLIENT_DISABLES_AT)."

### A.2 Connection lifecycle

```python
initialize(path=None, *, login=None, password=None, server=None, timeout=60000, portable=False) -> bool
login(login, *, password=None, server=None, timeout=60000) -> bool
shutdown() -> None
version() -> tuple[int, int, str] | None      # e.g. (500, 4120, '22 Dec 2023')
last_error() -> tuple[int, str]               # e.g. (1, 'Success'), (-2, 'Invalid "comment" argument')
```

From [DOC] `initialize` / `login`:

- `path` is the first, unnamed argument: the path to `terminal64.exe`. Without it the module "attempts to find the executable file on its own".
- `login` falls back to "the last trading account". `password` / `server` fall back to those "saved in the terminal database".
- `timeout` is the connection timeout in **milliseconds, default 60 000**. For `login`: "If the connection is not established within the specified time, the call is forcibly terminated and the exception is generated."
- `portable` (default False) launches the terminal in portable mode.
- "If required, the MetaTrader 5 terminal is launched to establish connection when executing the initialize() call."
- **OTP/certificate accounts** cannot be logged in from Python. Binary string: `Unsupported authorization mode, OTP or certificate password needed` [PKG].

**Recommendation (security):**

1. Log in **once, interactively**, in the terminal with "save password".
2. Call `initialize(path=<terminal64.exe>, portable=True)` **without** `login`/`password`, so our software never stores the master password.
3. If the login must be passed (e.g. after a terminal reinstall), read it from the Windows Credential Manager or an env var typed `SecretStr` in the bridge only, never from the backend.

`last_error()` codes (values from [PKG] `__init__.py`. Descriptions from [DOC] and the binary's error strings):

| Code | Constant | Meaning / binary text |
|---|---|---|
| 1 | `RES_S_OK` | success |
| −1 | `RES_E_FAIL` | generic fail ("Terminal: Call failed") |
| −2 | `RES_E_INVALID_PARAMS` | invalid arguments ("Terminal: Invalid params", or `Invalid "<field>" argument` for request fields, e.g. `Invalid "comment" argument`) |
| −3 | `RES_E_NO_MEMORY` | out of memory |
| −4 | `RES_E_NOT_FOUND` | "no history" / "Terminal: Not found" |
| −5 | `RES_E_INVALID_VERSION` | "Incompatible versions, please install the latest version of Terminal and Python module" |
| −6 | `RES_E_AUTH_FAILED` | authorization failed |
| −7 | `RES_E_UNSUPPORTED` | unsupported method |
| −8 | `RES_E_AUTO_TRADING_DISABLED` | auto-trading disabled ("Auto-Trading using Python API disabled in Terminal") |
| −10000 | `RES_E_INTERNAL_FAIL` | IPC general error ("IPC call failed") |
| −10001 | `RES_E_INTERNAL_FAIL_SEND` | IPC send failed |
| −10002 | `RES_E_INTERNAL_FAIL_RECEIVE` | IPC recv failed |
| −10003 | `RES_E_INTERNAL_FAIL_INIT` | IPC initialization failed |
| −10004 | `RES_E_INTERNAL_FAIL_CONNECT` | "No IPC connection". **The reference page lists −10003 for this constant. The shipped package defines −10004. Use the package value.** |
| −10005 | `RES_E_INTERNAL_FAIL_TIMEOUT` | IPC timeout |

Field reports of `(-10005, 'IPC timeout')` usually trace to: the terminal not started or not logged in, the Python-API trading switch, wrong `path` escaping, or Wine/Windows environment mismatch [FORUM: https://www.mql5.com/en/forum/443248 , https://github.com/gmag11/MetaTrader5-Docker/issues/15].

**Thread-safety and concurrency.**

- MetaQuotes documents nothing about thread-safety (**UNVERIFIED** either way). The module has process-global state and blocking IPC calls.
- Design rule: **all MT5 calls go through one dedicated worker thread** (a queue with per-call timeouts) in one process. The asyncio side awaits futures (`loop.run_in_executor(single_thread_executor, ...)`). Never call the module from several threads.
- The 2023 version of `aiomql` we inspected (an async wrapper, Vik2009 fork) simply calls `asyncio.to_thread` per call without a lock. Newer releases (4.x) may differ. Do not copy that pattern.

**Disconnects and reconnects (design, partly UNVERIFIED).**

- *Terminal ↔ broker* link lost: `terminal_info().connected == False`. The terminal reconnects to the trade server by itself. Python calls still work against cached data. Trading calls return `TRADE_RETCODE_CONNECTION` (10031) or time out. Action: pause entries and poll `connected` every 5 s.
- *Python ↔ terminal* IPC lost (terminal crashed, restarted or updated): calls return `None` with −10001…−10005. Action: `shutdown()`, then `initialize(path, portable=True)` with backoff (1 s → 60 s), then **full reconciliation** (§D.5) before resuming.
- Terminal auto-update can restart the terminal. Treat it like a crash.
- Watchdog: every 10 s call `terminal_info()` and `account_info()`. Two consecutive failures → reconnect procedure.

### A.3 `account_info()` → `AccountInfo | None`

Field order from the recorded `_asdict()` output in [DOC]/[REC] (values illustrative, from a MetaQuotes demo):

```text
login, trade_mode, leverage, limit_orders, margin_so_mode, trade_allowed, trade_expert,
margin_mode, currency_digits, fifo_close, balance, credit, profit, equity, margin,
margin_free, margin_level, margin_so_call, margin_so_so, margin_initial, margin_maintenance,
assets, liabilities, commission_blocked, name, server, currency, company
```

```text
AccountInfo(login=<redacted>, trade_mode=0, leverage=100, limit_orders=200, margin_so_mode=0,
 trade_allowed=True, trade_expert=True, margin_mode=2, currency_digits=2, fifo_close=False,
 balance=9681.25, credit=0.0, profit=0.0, equity=9681.25, margin=0.0, margin_free=9681.25,
 margin_level=0.0, margin_so_call=50.0, margin_so_so=30.0, margin_initial=0.0,
 margin_maintenance=0.0, assets=0.0, liabilities=0.0, commission_blocked=0.0,
 name='<redacted>', server='MetaQuotes-Demo', currency='EUR', company='MetaQuotes Software Corp.')
```
Source: [REC] Quantreo `03 Introduction .ipynb`.

| Field | Meaning / values [PKG] | Our use |
|---|---|---|
| `trade_mode` | 0 `ACCOUNT_TRADE_MODE_DEMO`, 1 `CONTEST`, 2 `REAL` | **Safety interlock:** `practice` mode requires 0. `live` requires 2 and `login == FXBOT_LIVE_CONFIRM_ACCOUNT_ID` |
| `margin_mode` | 0 `RETAIL_NETTING`, 1 `EXCHANGE`, 2 `RETAIL_HEDGING` | Require 2 (§D.6) |
| `leverage` | account leverage (int) | Informational. Our caps apply regardless |
| `trade_allowed` / `trade_expert` | trading allowed for the account / for experts (algos) | Both must be True |
| `fifo_close` | FIFO closing rule | Must be False (else retcode 10045 risk) |
| `limit_orders` | max pending orders | — |
| `margin_so_mode` | 0 `PERCENT`, 1 `MONEY` | Interpret `margin_so_call` / `margin_so_so` |
| `margin_so_call` / `margin_so_so` | margin-call and stop-out levels (here 50% / 30%) | Our guard halts far earlier |
| `balance`, `equity`, `profit`, `margin`, `margin_free`, `margin_level` | money in `currency` | NAV = `equity` |
| `currency`, `currency_digits` | account currency, decimals | Home currency for sizing |
| `server`, `company` | trade server name, broker | Journal provenance |

### A.4 `terminal_info()` → `TerminalInfo | None`

Fields [STUB] / [DOC]: `community_account, community_connection, connected, dlls_allowed,
trade_allowed, tradeapi_disabled, email_enabled, ftp_enabled, notifications_enabled, mqid,
build, maxbars, codepage, ping_last, community_balance, retransmission, company, name,
language, path, data_path, commondata_path`.

| Field | Meaning [DOC] `terminalstatus` | Our use |
|---|---|---|
| `connected` | "Connection to a trade server" | Health. False → pause entries |
| `trade_allowed` | "Permission to trade" = the **Algo Trading** button | Must be True |
| `tradeapi_disabled` | Presumably the "Disable automatic trading via external Python API" option (**UNVERIFIED** mapping) | Must be False |
| `maxbars` | "The maximal bars count on the chart" (the "Max. bars in chart" setting) | Limits history (§A.8) |
| `ping_last` | "last known value of a ping to a trade server in **microseconds**" | Latency metric (divide by 1,000 for ms) |
| `retransmission` | % of resent TCP packets for the whole machine, refreshed once per minute | Network quality hint |
| `build` | terminal build | Log. Alert on change (auto-update) |
| `path`, `data_path` | install and data folders | Bridge config check |

### A.5 Symbols: `symbol_info`, `symbol_info_tick`, `symbol_select`, `symbols_get`

```python
symbol_select(symbol, enable=True) -> bool          # add to (or remove from) Market Watch
symbol_info(symbol) -> SymbolInfo | None
symbol_info_tick(symbol) -> Tick | None
symbols_get(group="*") -> tuple[SymbolInfo, ...] | None   # group masks: "*USD*", "*, !EUR"
symbols_total() -> int
```

A symbol must be **selected in Market Watch** to receive live ticks. Call `symbol_select(s, True)` at start-up for every traded symbol ([DOC] `order_send` example does this when `symbol_info(s).visible` is false).

Recorded EURUSD `symbol_info` (MetaQuotes-Demo, 2022) [REC Quantreo]. Key fields:

```text
SymbolInfo(custom=False, chart_mode=0, select=True, visible=True, ..., time=1647042897, digits=5,
 spread=15, spread_float=True, ticks_bookdepth=10, trade_calc_mode=0, trade_mode=4, ...,
 trade_stops_level=0, trade_freeze_level=0, trade_exemode=1, swap_mode=1, swap_rollover3days=3,
 margin_hedged_use_leg=False, expiration_mode=15, filling_mode=1, order_mode=127, ...,
 bid=1.09137, ask=1.09152, ..., point=1e-05, trade_tick_value=0.9161536206391089,
 trade_tick_value_profit=0.9161536206391089, trade_tick_value_loss=0.9162795385616245,
 trade_tick_size=1e-05, trade_contract_size=100000.0, ..., volume_min=0.01, volume_max=500.0,
 volume_step=0.01, volume_limit=0.0, swap_long=-0.7, swap_short=-1.0, ...,
 session_open=1.09845, session_close=1.09859, ..., margin_hedged=100000.0, ...,
 currency_base='EUR', currency_profit='USD', currency_margin='EUR', ... name='EURUSD', path='Forex\\EURUSD')
```

The full field list (≈ 95 fields) is in [DOC] `mt5symbolinfo_py` and the stubs. Fields we use:

| Field | Meaning [DOC] `marketinfoconstants` | Use |
|---|---|---|
| `digits`, `point` | price decimals. "Symbol point value" (1e-5 for EURUSD, 1e-3 for USDJPY) | Rounding. All "points" fields × `point` = price |
| `trade_tick_size`, `trade_tick_value(_profit/_loss)` | min price change. Its value per 1 lot in **account currency** | Sizing: loss per lot = \|entry−stop\| / tick_size × `trade_tick_value_loss` (cross-check with `order_calc_profit`) |
| `trade_contract_size` | units per lot (100,000 for FX) | units = lots × contract size |
| `volume_min/max/step`, `volume_limit` | lot limits. `volume_limit` = max aggregate one-direction volume | Quantize lots **down** to `volume_step` |
| `spread` (int, **points**), `spread_float` | current spread. Floating flag | Spread filter = `spread × point` |
| `trade_stops_level` | "Minimal indention in **points** from the current close price to place Stop orders" | SL/TP distance check |
| `trade_freeze_level` | "Distance to freeze trade operations in points" | No SL/TP modification inside it |
| `trade_mode` | 0 DISABLED, 1 LONGONLY, 2 SHORTONLY, 3 CLOSEONLY, **4 FULL** | Must be 4 for new entries |
| `trade_exemode` | 0 REQUEST, 1 INSTANT, **2 MARKET**, 3 EXCHANGE | Decides required fields and filling (§A.10) |
| `filling_mode` | **bit flags**: `SYMBOL_FILLING_FOK = 1`, `SYMBOL_FILLING_IOC = 2`, `SYMBOL_FILLING_BOC = 4` (MQL5 constants, not exported by the Python package) | Pick `type_filling` (§A.10) |
| `order_mode`, `expiration_mode` | flags of allowed order types / expirations | — |
| `swap_mode`, `swap_long`, `swap_short`, `swap_rollover3days` | swap calculation mode (0 disabled, 1 points, 2 ccy symbol, 3 ccy margin, 4 ccy deposit, 5–6 interest %, 7–8 reopen). Long/short swap values. "The day of week to charge 3-day swap rollover" (0 = Sunday … 3 = Wednesday) | Financing model in the backtester. Convert by `swap_mode` |
| `chart_mode` | 0 `SYMBOL_CHART_MODE_BID`, 1 `LAST` | Bars are **bid** bars when 0 |
| `currency_base/profit/margin`, `path`, `description` | — | Symbol mapping (§D.7) |
| `session_open`, `session_close` | **prices** (session open/close price), not times | Do not use as a schedule |
| `time` | time of last quote (server clock, §A.12) | Staleness check |

**Trading sessions:** the MQL5 functions `SymbolInfoSessionTrade/Quote` have **no Python equivalent** in the package (they are absent from the binary's function list). Derive trading hours from tick activity and handle `TRADE_RETCODE_MARKET_CLOSED` (10018).

`Tick` = `(time, bid, ask, last, volume, time_msc, flags, volume_real)`. Recorded:
`Tick(time=1585070338, bid=1.17264, ask=1.17279, last=0.0, volume=0, time_msc=1585070338728, flags=2, volume_real=0.0)` [DOC].

### A.6 Bars: `copy_rates_from`, `copy_rates_from_pos`, `copy_rates_range`

```python
copy_rates_from(symbol, timeframe, date_from, count) -> np.ndarray | None      # bars with time <= date_from
copy_rates_from_pos(symbol, timeframe, start_pos, count) -> np.ndarray | None  # start_pos 0 = current bar
copy_rates_range(symbol, timeframe, date_from, date_to) -> np.ndarray | None   # date_from <= time <= date_to
```

- **dtype** (recorded [REC QuantInsti]): `[('time','<i8'), ('open','<f8'), ('high','<f8'), ('low','<f8'), ('close','<f8'), ('tick_volume','<u8'), ('spread','<i4'), ('real_volume','<u8')]`. Rows are in **ascending time**. The **last row of `copy_rates_from_pos(.., 0, n)` is the current, unfinished bar**. Drop it, or keep only bars with `time + tf ≤ server_now`.
- **`time`** = bar **open** time ([DOC] MqlRates "Period start time"), in the server clock (§A.12).
- **Prices are bid** when `chart_mode == 0` (normal for FX).
- **`spread`** is in **points**. MetaQuotes does not document how it is aggregated. MQL5 community consensus is that it is the **minimum** spread seen during the bar [FORUM: https://www.mql5.com/en/forum/266519 , https://tickstory.com/forum/viewtopic.php?t=2964] (**UNVERIFIED** officially). Some brokers store 0 on D1 (the recorded EURAUD D1 rows have `spread=0`).
- `tick_volume` = number of ticks. `real_volume` = 0 for OTC FX.
- Timeframe constants [PKG]: `TIMEFRAME_M1=1, M2=2, M3=3, M4=4, M5=5, M6=6, M10=10, M12=12, M15=15, M20=20, M30=30, H1=0x4001, H2=0x4002, H3=0x4003, H4=0x4004, H6=0x4006, H8=0x4008, H12=0x400C, D1=0x4018, W1=0x8001, MN1=0xC001`.
- **History depth**:
  - [DOC]: "MetaTrader 5 terminal provides bars only within a history available to a user on charts. The number of bars available to users is set in the 'Max. bars in chart' parameter." The default is reported as 100,000 bars [FORUM excerpt]. Set it to *Unlimited* on the bridge host before backfilling.
  - MT5 stores history as **M1 bars** and builds other timeframes from them [FORUM excerpt]. Depth is broker-specific. Check `copy_rates_range` coverage per symbol.
  - The first request may trigger a download from the server and return partial data (MQL5 `CopyRates` notes). **Retry until the bar count is stable**.
- Date arguments: pass timezone-aware `datetime` in UTC or integer epoch seconds. The module compares them against the (server-clock) bar times as-is, so to request "server 2024-01-02 00:00" pass `datetime(2024,1,2,tzinfo=UTC)` (§A.12).

### A.7 Ticks: `copy_ticks_from`, `copy_ticks_range`

```python
copy_ticks_from(symbol, date_from, count, flags) -> np.ndarray | None
copy_ticks_range(symbol, date_from, date_to, flags) -> np.ndarray | None
```

- **dtype** (recorded [REC Quantreo]): `[('time','<i8'), ('bid','<f8'), ('ask','<f8'), ('last','<f8'), ('volume','<u8'), ('time_msc','<i8'), ('flags','<u4'), ('volume_real','<f8')]`.
- Copy flags [PKG]: `COPY_TICKS_ALL = -1`, `COPY_TICKS_INFO = 1` (bid/ask changes, what FX needs), `COPY_TICKS_TRADE = 2`.
- Tick flags: `TICK_FLAG_BID = 0x02`, `ASK = 0x04`, `LAST = 0x08`, `VOLUME = 0x10`, `BUY = 0x20`, `SELL = 0x40`.
- The terminal keeps **4,096** recent ticks per symbol in a fast cache. Older ticks come from disk/server. The first call starts tick-database synchronization and may return what is ready after **45 s** ([DOC] `CopyTicks`, MQL5 context).
- Tick history depth on broker servers is often much shorter than bar history (**UNVERIFIED** per broker).

### A.8 `order_check` and `order_send`

```python
order_check(request: dict) -> OrderCheckResult | None
order_send(request: dict) -> OrderSendResult | None
order_calc_margin(action, symbol, volume, price) -> float | None
order_calc_profit(action, symbol, volume, price_open, price_close) -> float | None
```

**Request dict** (`MqlTradeRequest`, [DOC] `mqltraderequest`, keys as in the binary):

| Key | Type | Notes |
|---|---|---|
| `action` | int | `TRADE_ACTION_DEAL=1` (market), `PENDING=5`, `SLTP=6` (modify position SL/TP), `MODIFY=7` (pending), `REMOVE=8` (delete pending), `CLOSE_BY=10` [PKG] |
| `magic` | int | "EA ID". We use one value per system + strategy (§D.4) |
| `order` | int | pending-order ticket (MODIFY/REMOVE) |
| `symbol` | str | broker symbol name |
| `volume` | float | **lots** (multiple of `volume_step`) |
| `price` | float | required for Instant/Request execution. "Market orders of symbols, whose execution type is 'Market Execution' ... do not require specification of price" |
| `stoplimit` | float | stop-limit orders only |
| `sl`, `tp` | float | absolute prices. 0.0 = none |
| `deviation` | int | "maximal price deviation, specified in **points**". Listed as required only for Instant/Request execution. Under **Market Execution** the required fields are only `action, symbol, volume, type, type_filling` (so a deviation cap is not guaranteed there: inference, **UNVERIFIED**) |
| `type` | int | `ORDER_TYPE_BUY=0`, `SELL=1`, `BUY_LIMIT=2`, `SELL_LIMIT=3`, `BUY_STOP=4`, `SELL_STOP=5`, `BUY_STOP_LIMIT=6`, `SELL_STOP_LIMIT=7`, `CLOSE_BY=8` |
| `type_filling` | int | `ORDER_FILLING_FOK=0`, `IOC=1`, `RETURN=2`, `BOC=3`. **Always set explicitly** |
| `type_time` | int | `ORDER_TIME_GTC=0`, `DAY=1`, `SPECIFIED=2`, `SPECIFIED_DAY=3` |
| `expiration` | int | for `SPECIFIED` |
| `comment` | str | **≤ 31 characters**, otherwise `order_send` returns `None` with `last_error() == (-2, 'Invalid "comment" argument')` (field report: https://github.com/rellis3/MacroFXModel/pull/1468). Brokers may overwrite/append (e.g. `[sl]`, `[tp]`) [FORUM]. **Keep ≤ 25 chars** |
| `position` | int | position ticket. **Required on hedging accounts to close or modify a specific position** ("When modifying or closing a position in the hedging system, make sure to specify its ticket") |
| `position_by` | int | opposite position for CLOSE_BY |

**Choosing `type_filling`** ([DOC] filling table):

- Market Execution (`trade_exemode == 2`): FOK/IOC only "if set in the symbol settings". RETURN is "disabled regardless of the symbol settings".
- Instant/Request execution: FOK, IOC and RETURN all allowed.
- Algorithm: if `filling_mode & 1` → FOK. Elif `filling_mode & 2` → IOC. Elif `exemode != 2` → RETURN. Else refuse.
- On retcode 10030 (`INVALID_FILL`) re-read `symbol_info` and retry **once** with the next allowed mode.
- Our partial-fill policy: FOK preferred. With IOC, handle `TRADE_RETCODE_DONE_PARTIAL` (10010) by sizing the SL to the filled volume (the position's SL applies to the whole position anyway).

**SL/TP on a market order.** MT5 accepts `sl`/`tp` in a `TRADE_ACTION_DEAL` request (the [DOC] Python example sends them). Whether a given broker rejects or strips them under Market Execution is **UNVERIFIED**. Defensive sequence:

1. send the DEAL with `sl`;
2. read the position (`positions_get(ticket=result.order)`) and verify `sl` is set;
3. if not, send `TRADE_ACTION_SLTP` immediately;
4. if that fails twice, close the position.

**Result structures** ([STUB], [DOC]):

- `OrderSendResult(retcode, deal, order, volume, price, bid, ask, comment, request_id, retcode_external, request)`. `deal` = deal ticket (for DEAL). `order` = order ticket. `request` is the echoed `TradeRequest` named tuple. `comment` is the broker's text (e.g. "Request executed").
- Recorded close result [DOC]: `retcode=10009, deal=…, order=…, volume=0.1, price=108.015, bid=108.015, ask=108.02, comment='Request executed', request_id=55, retcode_external=0`.
- `OrderCheckResult(retcode, balance, equity, profit, margin, margin_free, margin_level, comment, request)`. For `order_check`, **`retcode == 0` means the check passed** (recorded: `retcode=0 ... comment='Done'`).
- **Position ticket.** For a market order that opens a position, the position ticket "as a rule" equals the opening order ticket (`result.order`) [DOC]. Confirm by `positions_get(ticket=result.order)` and fall back to searching by `magic` + `comment`.

**Return-code table** (values [PKG]. Texts [DOC] `enum_trade_return_codes`. Classification = our policy, opinion):

| Code | Constant | Text | Class → action |
|---|---|---|---|
| 10009 | DONE | Request completed | ✅ success |
| 10008 | PLACED | Order placed | ✅ (pending orders) |
| 10010 | DONE_PARTIAL | Only part of the request was completed | ✅ partial: reconcile volume |
| 10025 | NO_CHANGES | No changes in request | ✅ no-op (SLTP already at that value) |
| 10004 | REQUOTE | Requote | 🔁 retry ≤ 2 with a fresh price, same bar only |
| 10020 | PRICE_CHANGED | Prices changed | 🔁 retry ≤ 2 with a fresh price |
| 10021 | PRICE_OFF | There are no quotes to process the request | 🔁 retry after 1–5 s. Stale-price alert |
| 10024 | TOO_MANY_REQUESTS | Too frequent requests | 🔁 back off (≥ 1 s) |
| 10028 | LOCKED | Request locked for processing | 🔁 short back-off, then reconcile |
| 10029 | FROZEN | Order or position frozen | ⏸ price inside the freeze level: retry on a later bar |
| 10012 | TIMEOUT | Request canceled by timeout | ❓ **ambiguous → reconcile before any retry** |
| 10031 | CONNECTION | No connection with the trade server | ❓ ambiguous → pause entries, reconcile |
| 10011 | ERROR | Request processing error | ❓ reconcile, then alert |
| — | `None` result | IPC/argument failure (`last_error()`) | ❓ IPC codes → reconnect + reconcile. −2 → bug, no retry |
| 10013 | INVALID | Invalid request | ⛔ bug: no retry |
| 10014 | INVALID_VOLUME | Invalid volume | ⛔ fix quantization |
| 10015 | INVALID_PRICE | Invalid price | ⛔ |
| 10016 | INVALID_STOPS | Invalid stops | ⛔ recompute with `trade_stops_level`. One retry |
| 10022 | INVALID_EXPIRATION | — | ⛔ |
| 10030 | INVALID_FILL | Invalid order filling type | ⛔ switch filling. One retry |
| 10035 | INVALID_ORDER | Incorrect or prohibited order type | ⛔ |
| 10038 | INVALID_CLOSE_VOLUME | Close volume exceeds position volume | ⛔ reconcile volume |
| 10032 | ONLY_REAL | Allowed only for live accounts | ⛔ |
| 10006 | REJECT | Request rejected | ⛔ log, no automatic retry |
| 10007 | CANCEL | Request canceled by trader | ⛔ |
| 10017 | TRADE_DISABLED | Trade is disabled | 🛑 halt symbol, alert |
| 10018 | MARKET_CLOSED | Market is closed | ⏸ wait for the session (weekend/holiday) |
| 10019 | NO_MONEY | Not enough money | 🛑 halt, alert (risk-engine bug or drawdown) |
| 10026 | SERVER_DISABLES_AT | Autotrading disabled by server | 🛑 halt, alert |
| 10027 | CLIENT_DISABLES_AT | Autotrading disabled by client terminal | 🛑 halt. The Algo Trading button is off or the Python-API trading switch is disabled [BOOK] |
| 10033 | LIMIT_ORDERS | Pending-order limit reached | 🛑 |
| 10034 | LIMIT_VOLUME | Symbol volume limit reached | 🛑 |
| 10040 | LIMIT_POSITIONS | Position-count limit reached | 🛑 |
| 10042 / 10043 / 10044 | LONG_ONLY / SHORT_ONLY / CLOSE_ONLY | Symbol restricted | 🛑 skip symbol |
| 10045 | FIFO_CLOSE | FIFO rule | 🛑 (should not occur, `fifo_close` must be False) |
| 10046 | HEDGE_PROHIBITED | Opposite positions disabled | 🛑. **Not defined in the Python package** (docs only). Compare the raw int |
| 10036 | POSITION_CLOSED | Position already closed | ✅ for a close request: reconcile and mark closed |
| 10039 | CLOSE_ORDER_EXIST | A close order already exists | ⏸ wait, reconcile |
| 10041 | REJECT_CANCEL | Pending activation rejected | — |
| 10023 | ORDER_CHANGED | Order state changed | reconcile |

Requote/price-changed retries must never chase price beyond our `max_slippage` (0.1 × ATR, `04` §9). Check the actual fill price after every DEAL. If slippage > 2× the limit, alert. A post-fill "close if absurd" rule is opinion and left as config (off by default).

### A.9 Positions, orders, history

```python
positions_total() -> int
positions_get(*, symbol=None, group=None, ticket=None) -> tuple[TradePosition, ...] | None
orders_total() -> int
orders_get(*, symbol=None, group=None, ticket=None) -> tuple[TradeOrder, ...] | None
history_orders_total(date_from, date_to) -> int | None
history_orders_get(date_from=None, date_to=None, *, group=None, ticket=None, position=None) -> tuple[TradeOrder, ...] | None
history_deals_total(date_from, date_to) -> int | None
history_deals_get(date_from=None, date_to=None, *, group=None, ticket=None, position=None) -> tuple[TradeDeal, ...] | None
```

Signatures are from the binary's docstrings [PKG], e.g. `history_deals_get([date_from, date_to, [group="GROUP"]],[position=POSITION],[ticket=TICKET])`. Return `None` on error. When there is nothing to return they are expected to return an **empty tuple** (**UNVERIFIED**). The [DOC] examples test `== None` for "no positions". **Treat `None` as an error only if `last_error()[0] != 1`.**

Group masks: comma-separated conditions, `*` wildcard, `!` exclusion, applied in order (`"*, !EUR"`) [DOC].

Named-tuple fields (order from [STUB], matching the binary strings and the [DOC] tables):

- `TradePosition(ticket, time, time_msc, time_update, time_update_msc, type, magic, identifier, reason, volume, price_open, sl, tp, price_current, swap, profit, symbol, comment, external_id)`. `type`: 0 BUY, 1 SELL. `reason`: 0 CLIENT, 1 MOBILE, 2 WEB, **3 EXPERT** (Python/EA). `identifier` = position ID (stable across partial closes). `ticket` usually equals `identifier`.
- `TradeOrder(ticket, time_setup, time_setup_msc, time_done, time_done_msc, time_expiration, type, type_time, type_filling, state, magic, position_id, position_by_id, reason, volume_initial, volume_current, price_open, sl, tp, price_current, price_stoplimit, symbol, comment, external_id)`. `state` 0 STARTED … 4 FILLED, 5 REJECTED, 6 EXPIRED. `reason` adds 4 SL, 5 TP, 6 SO.
- `TradeDeal(ticket, order, time, time_msc, type, entry, magic, position_id, reason, volume, price, commission, swap, profit, fee, symbol, comment, external_id)`:
  - `type`: 0 BUY, 1 SELL, 2 BALANCE, 3 CREDIT, 4 CHARGE, 5 CORRECTION, 6 BONUS, 7–11 COMMISSION variants, 12 INTEREST, …, 17 TAX.
  - `entry`: **0 IN, 1 OUT, 2 INOUT (reverse), 3 OUT_BY**.
  - `reason`: 0 CLIENT, 1 MOBILE, 2 WEB, **3 EXPERT, 4 SL, 5 TP, 6 SO (stop-out)**, 7 ROLLOVER, 8 VMARGIN, 9 SPLIT.
  - `position_id` links all deals of a position.
  - `commission` = "Deal commission". `swap` = "Cumulative swap on close". `profit` = "Deal profit". `fee` = "Fee for making a deal charged immediately after performing a deal" [DOC `dealproperties`].

**Trade reconstruction:**

1. Group deals by `position_id`.
2. The entry deal has `entry == 0`. Exit deal(s) have `entry ∈ {1, 3}`.
3. Realized P/L = Σ(`profit + swap + commission + fee`) over the position's deals. Commission is often split between entry and exit deals (**UNVERIFIED** per broker).
4. The exit cause comes from the exit deal's `reason` (4 SL, 5 TP, 3 our close, 6 stop-out).
5. Balance/credit deals (`type` 2/3) are deposits and withdrawals. Journal them separately: they change equity without being P/L.

### A.10 Server time vs UTC (important)

What the documentation says ([DOC] `copy_rates_from`, `copy_ticks_from`): "MetaTrader 5 stores tick and bar open time in UTC time zone (without the shift)... Data received from the MetaTrader 5 terminal has UTC time."

What the evidence shows:

1. Recorded EURAUD **D1** bars [REC QuantInsti] start exactly at 00:00 of each weekday, with **no Sunday bars** (e.g. `1716508800` = Fri 2024-05-24 00:00, next `1716768000` = Mon 2024-05-27 00:00). A broker whose day starts at the New York close (17:00 NY = 21:00/22:00 UTC) can only produce midnight-aligned D1 bars without Sunday bars if the stamps are its **server wall clock**.
2. The recorded `symbol_info().time = 1647042897` is Friday 2022-03-11 **23:54:57** "UTC". The FX market closes at 17:00 New York = 22:00 UTC in March, so this is a server-clock (UTC+2) stamp.
3. The ejtraderLabs MT5 export (`07` §3.2) [OURS]: in 485 weeks, the first bar of the week is **Monday 00:00** (482 times) and the last is Friday 22:00–23:00. This holds **even in the March weeks when US and EU daylight-saving dates differ** (2013–2021 checked). So that server clock = **New York time + 7 h**, i.e. UTC+2 in winter and UTC+3 in summer, following **US** DST.
4. A 2026 forum thread is titled "MetaQuotes-Demo build 6182: Python timestamps appear 3 hours ahead of UTC" (https://www.mql5.com/en/forum/515951, excerpt only).

**Conclusion (evidence-based, not officially documented).** Treat every MT5 timestamp (bars, ticks, `symbol_info.time`, positions, orders, deals) as **broker server wall-clock time encoded as epoch seconds**. Most FX brokers use "New York + 7 h" so that 00:00 server = 17:00 New York (**UNVERIFIED** per broker → detect).

**Detection algorithm (bridge start-up + daily):**

1. **Live offset.** During market hours, for 3 liquid symbols, read `symbol_info_tick(s).time_msc` and the host's NTP-synced UTC clock. `offset = round_to_15min(tick_time − utc_now)`, accepting only ticks younger than 60 s (by the local receive clock). The values must agree across symbols. This gives the current offset (e.g. +3 h in summer).
2. **Rule check over history.**
   - Fetch H1 bars for the last 3 years. For each week, take the first bar's server time T_first.
   - Compute `k = T_first − (Sunday 17:00 America/New_York of that week)` in hours.
   - If `k` is constant (typically 7), the rule is "server = America/New_York + k". If it toggles in March/October–November only, the server follows EU DST. If it varies otherwise, flag it and fall back to the live offset plus a manual config.
3. Store `server_tz_rule = {"base": "America/New_York", "shift_hours": 7}` (or `{"fixed_utc_offset_hours": 2}`). Convert every timestamp with it: `utc = (server_naive − shift).replace(tzinfo=NY).astimezone(UTC)`.
4. Unit-test the converter across the US and EU DST transition dates (`06` §8).

Passing dates **into** `copy_rates_range` etc.: convert our UTC window to server wall clock with the inverse rule and pass it as a UTC-tagged datetime (the API compares raw values).

---

## B. Running it: deployment options for a user in Cameroon

### B.1 Local reliability context (evidence)

- Electricity: Cameroon's grid has recurring outages. Douala (Mar 2025: half the city without power 06:00–18:00 for maintenance). Load-shedding schedules in northern regions (Jan 2026). About 40% of customers in Littoral and West affected when two plants withdrew capacity (Jun 2026). Utility restructuring (ENEO → state-owned SOCADEL, May 2026). Sources: https://africanarguments.org/2026/08/cameroon-has-the-power-it-cannot-deliver-it/ , https://www.businessincameroon.com/energy/2001-15625-cameroon-power-utility-warns-of-up-to-10-hour-outages-in-northern-regions , https://www.businessincameroon.com/energy/0306-16270-cameroon-s-power-crisis-exposes-the-financial-fault-lines-of-the-electricity-sector
- Internet stability and regional shutdowns: not researched in depth here (**UNVERIFIED** for current conditions). Assume interruptions are possible.
- MT5 must stay logged in 24/5. Built-in trailing stops are **client-side**: they only work while the terminal runs ("Stop Loss and Take Profit orders sit server-side ... trailing stops don't", https://www.mql5.com/en/forum/222326 and broker guides). Our own SL moves (§D.5) need our process running too.

**Implication:** a home PC in Cameroon should not be in the trading path. Server-side SL/TP protect open positions during an outage, but entries, SL moves, reconciliation and the kill switch need a machine that stays up.

### B.2 Options

| Option | How | Pros | Cons / risks |
|---|---|---|---|
| **1. Everything on a Windows PC at home** | MT5 + Python + backend on the user's PC | Free. Simplest to start (paper/practice) | Power cuts, internet drops, PC sleep/updates. Not acceptable for live 24/5 |
| **2. Windows VPS** (recommended) | Rented Windows Server VPS (2 vCPU, 4 GB RAM is comfortable) in London/Amsterdam/New York near the broker's MT5 servers | 24/5 uptime, low latency to the broker (VPS vendors cite ~1–5 ms in the same data centre as the broker; LD4/NY4 marketing figures), independent of Cameroonian power | Cost **~USD 8–35/month** depending on vendor and Windows licensing (e.g. Contabo ≈ USD 25–35 after licence and RAM upgrade. Entry plans from ~USD 8–10 incl. Windows at some vendors: third-party comparisons, **UNVERIFIED** current prices). **Several brokers give a free VPS** above a balance/volume threshold: reported Exness ≥ USD 500 balance, IC Markets ≥ USD 2,000 or 15 lots/month, Pepperstone ≥ USD 500 equity and 15–20 lots/month, FBS first month with USD 450 (all **UNVERIFIED**, changing). Check whether a broker VPS lets you install Python and our software (often yes for full Windows VPS, **UNVERIFIED**) |
| 2b. **MQL5 Virtual Hosting** (MetaQuotes) | One-click from the terminal, ~USD 13–15/month | Cheap, integrated | **Cannot run Python** (and no DLLs. Scripts are not migrated, only charts with EAs). Not usable for us |
| **3. Linux/Docker + Wine bridge** | MT5 runs under Wine. A Windows-Python RPyC server inside Wine exposes the `MetaTrader5` module to Linux Python. Projects: `mt5linux` (lucas-campagna, 1.1.1, 2026-08, now ships a prebuilt `mt5server.exe`), `pymt5linux` (1.0, 2025-04), Docker image `gmag11/metatrader5_vnc` (last commit 2025-12-20, KasmVNC web UI on :3000, RPyC on :8001) | Keeps everything on Linux/Docker. Fine for **local experiments with a demo account** | (a) **Security:** `mt5linux` uses **RPyC classic mode** (`rpyc.classic.connect`, `conn.eval(code)`), which gives **arbitrary remote code execution** to anyone who reaches the port. The gmag11 image starts it with `--host 0.0.0.0` and publishes `-p 8001:8001` with **no authentication**. mt5linux's own container runs x11vnc with `-nopw` unless a password is set. (b) **Reliability:** Wine compatibility issues and IPC timeouts are reported (gmag11 issue #15). (c) Supply chain: prebuilt `mt5server.exe` binary, auto-installed Python 3.9 and pinned old `MetaTrader5==5.0.36` in the gmag11 script. **Not recommended for live** |
| **4. MetaApi cloud** (metaapi.cloud) | SaaS runs the terminal for you. REST/WebSocket SDK (`metaapi-cloud-sdk` 29.1.1) | No Windows to manage | **You hand over your MT5 trading (master) password** to a third party (credential custody). Usage-based pricing (subscription tiers reported from ~USD 30/month plus per-account fees, **UNVERIFIED**). Vendor lock-in and an extra failure point. Not compatible with "secrets stay server-side" |

### B.3 Recommended primary deployment

**One Windows VPS** (Windows Server, near the broker's MT5 server region; ask the broker which data centre) running three things:

1. **MT5 terminal**, portable install in e.g. `C:\fxbot\mt5\`. Logged in once interactively with "save password". **Algo Trading on**, "Disable automatic trading via external Python API" unchecked, "Max bars in chart" = Unlimited. Auto-start at boot (Task Scheduler, run whether user is logged on or not, **UNVERIFIED** that the terminal works without an interactive session; a common practice is auto-logon of a dedicated Windows user).
2. **`mt5-bridge`**: a small Windows-Python process (our code, Stage 1b) that owns the `MetaTrader5` module. It exposes a **minimal, allow-listed HTTP API on 127.0.0.1 only**.
3. **Our backend** (FastAPI, uv), running **natively on Windows** as a service (e.g. NSSM or Task Scheduler). Its `MT5Broker` adapter is a pure HTTP client of the bridge, so it is testable on Linux CI with respx. The dashboard is served by the backend and reached over HTTPS with our auth, or only through an SSH tunnel / Tailscale (preferred: no public port).

Why a separate bridge process even on the same machine (opinion):

- It isolates the global, blocking, Windows-only module.
- The backend can restart without touching the terminal connection.
- The backend stays platform-independent and Linux-testable.
- The same bridge also serves a later topology where the backend runs on Linux (connected over WireGuard/Tailscale, never over the public internet).

Why not Docker on the VPS: Windows Server VPSes usually cannot run Docker Desktop/WSL2 (nested virtualization), **UNVERIFIED** per vendor. Our backend must therefore **run natively on Windows**. Implications: no Linux-only dependencies (`uvloop` is unavailable on Windows; uvicorn falls back to the default loop), use `pathlib`, no `fork`, and add a Windows job to CI (§D.10).

Fallback (development): a Windows PC at home for `paper`/`practice`, plus the Linux/Docker stack unchanged with the paper broker. The Wine image only for local demo experiments, bound to `127.0.0.1`.

### B.4 Bridge security requirements

1. **Bind `127.0.0.1` only.** Refuse to start if configured otherwise. Check the `Host` header against an allow-list (DNS-rebinding defence).
2. **Authentication:** a random ≥ 32-byte bearer token, from an env var / Windows Credential Manager. `SecretStr`, compared in constant time, never logged, rotated on reinstall. Optional HMAC over method + path + body + timestamp, ±30 s window, to stop replay.
3. **Allow-listed endpoints only**: `GET /health`, `GET /account`, `GET /symbols/{s}`, `GET /tick/{s}`, `GET /rates`, `GET /ticks`, `GET /positions`, `GET /orders`, `GET /history/deals`, `GET /history/orders`, `POST /order/check`, `POST /order/send` (actions **DEAL and SLTP only** in Stage 1b; PENDING/MODIFY/REMOVE refused), `POST /reconnect`. **No generic eval, no RPyC, no pass-through of arbitrary module calls.**
4. **Validation in the bridge** (defence in depth): symbol allow-list, `volume ≤ max_lots`, `comment` ≤ 25 chars ASCII, `magic` in our range, `deviation` bounded, mandatory `sl` on DEAL opens, a `live` flag that must match `account_info().trade_mode` (0 for practice, 2 for live).
5. **Idempotency store**: `POST /order/send` requires an `Idempotency-Key` (our client id). The bridge stores key → result for 7 days (SQLite) and returns the stored result on a repeat.
6. **Single worker thread** for all MT5 calls. Per-call timeout (default 30 s for trading calls, 10 s for reads).
7. **Logs** contain request ids, retcodes and timings, never the token, password or full account number (mask the login to the last 3 digits).
8. Windows hygiene: a dedicated non-admin user, Windows Firewall with no inbound rules except RDP restricted by IP/VPN (or no RDP; use the vendor console), automatic Windows updates scheduled for the weekend.

---

## C. Brokers that offer MT5 to a Cameroon resident

**Read this first.**

- Almost every international broker serves Cameroon through an **offshore** entity: Seychelles FSA, Bahamas SCB, Belize FSC, Mauritius FSC, St Vincent & Grenadines (SVG companies are *registered*, not regulated, for FX), BVI FSC, Comoros/Mwali MISA.
- The broker's FCA/ASIC/CySEC licences **do not protect you**: no FSCS/ICF compensation, and leverage caps and negative-balance protection may differ. Third-party sites that say "Cameroonian traders can safely access the broker under ASIC/CySEC" are wrong about which entity you contract with.
- Facts below are from broker help pages and comparison sites seen through search excerpts. They change often. Treat every cell as **"reported, verify"** unless it cites a regulator.

### C.1 Comparison (reported, 2025–2026)

| Broker | Accepts Cameroon? | Entity likely serving Cameroon (regulator) | Group top-tier licences | MT5 + free demo | EUR/USD cost by account (reported) | Min deposit | Local payments | MT5 symbol naming | Hedging | NBP | Public warnings / enforcement found |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Exness** | Yes (several comparison sites; Exness offers Mobile Money "in Africa") | Exness (SC) Ltd, **Seychelles FSA** (most of Africa outside ZA/KE, reported) | CySEC, FCA (UK entity), FSCA, others | Yes | Standard: spread-only, "from 0.3" (avg higher, **UNVERIFIED**). Raw Spread: from 0.0 + **USD 3.50/lot/side**. Zero: 0.0 on top pairs + commission. Pro: from 0.1, no commission | Standard: no fixed minimum (payment-method dependent, ~USD 10). Pro/Raw/Zero: USD 200 | **MTN MoMo and Orange Money reported** for Cameroon (help article "How to deposit and withdraw with Mobile Money in Africa"). Cards, bank, crypto, e-wallets | Suffixes per account type (Exness help centre): Standard **`m`** (`EURUSDm`), Standard Cent `c`, Zero `z`, Raw Spread/Pro none | Yes (MT5 hedging, reported) | Claimed | **Philippines SEC advisory (Dec 2025)** vs Exness Global Ltd for operating there unlicensed. Listed on the **RBI (India) alert list** |
| **XM** | Yes (reported) | XM Global Ltd, **Belize FSC** (also FSC Mauritius mentioned) | CySEC, DFSA, FSCA | Yes | Standard ~1.6 "from". Ultra Low ~0.8. Zero 0.0 + USD 3.50/side | USD 5 | **Mobile Money not available** per one comparison site (**UNVERIFIED**). Cards, bank, e-wallets | Account-dependent suffixes (**UNVERIFIED**) | Reported yes | Claimed | RBI alert list |
| **HFM (HotForex)** | Reported yes (Africa-focused) | HF Markets (SV) Ltd (**SVG, registered not regulated**) and/or HF Markets (Seychelles) FSA. MT4/MT5 reported only under the SV registration | FCA, CySEC, FSCA, DFSA | Yes | Premium ~1.2 from, no commission. Zero 0.0 + ~USD 6 round turn. Pro 0.6 from | USD 0 (Pro USD 100) | Mobile money (M-Pesa, MTN) reported for some African countries. **Cameroon UNVERIFIED** | **UNVERIFIED** | Yes | Claimed for all entities | **Philippines SEC advisory (Dec 2025)** |
| **IC Markets** | Reported yes | Raw Trading Ltd (**Seychelles FSA**) or IC Markets Ltd (**Bahamas SCB**) | ASIC, CySEC | Yes | Raw: ~0.0–0.2 + USD 3.50/side. Standard: spread-only ~0.8–1.0 (**UNVERIFIED** averages) | USD 200 | Cards, bank, e-wallets, crypto. **Mobile Money not found** | Usually none (**UNVERIFIED**) | Yes | **UNVERIFIED** for offshore entity | None found in this search |
| **Pepperstone** | Reported yes (**UNVERIFIED**) | Pepperstone Markets Ltd (**Bahamas SCB**) or Pepperstone International (**Seychelles FSA**) | ASIC, FCA, CySEC, BaFin, DFSA, **CMA Kenya** | Yes | Razor: ~0.0–0.2 + ~USD 3.50/side. Standard ~1.0–1.1 | USD 0 (USD 200 suggested) | Cards, bank, e-wallets. **Mobile Money not found** | **UNVERIFIED** | Yes | **UNVERIFIED** offshore | FCA warning about a **clone** site impersonating Pepperstone ("Pepperforeign"): a clone risk, not an action against Pepperstone |
| **FxPro** | Reported yes | FxPro Global Markets (**Bahamas SCB**) | FCA, CySEC, FSCA | Yes | **UNVERIFIED** | ~USD 100 (**UNVERIFIED**) | **UNVERIFIED** | **UNVERIFIED** | Yes | Claimed | None found |
| **Tickmill** | Reported yes (**UNVERIFIED**) | Tickmill Ltd, **Seychelles FSA (SD008)** | FCA, CySEC, FSCA, DFSA, Labuan | Yes | Raw ≈ 0.0 + commission. Classic spread-only (**UNVERIFIED** numbers) | ~USD 100 (**UNVERIFIED**) | **UNVERIFIED** | **UNVERIFIED** | Yes | **UNVERIFIED** | None found |
| **AvaTrade** | Yes: Cameroon not on its "not accepted" list (reported) | Offshore entity for Africa (BVI, **UNVERIFIED**) | CBI (IE), ASIC, FSCA, JFSA, others | Yes | Fixed-ish spread ~0.9 | USD 100 | **UNVERIFIED** | **UNVERIFIED** | Yes | Claimed (retail) | None found |
| **Admirals** | Not on its restricted list (reported) | Admirals SC Ltd (Seychelles FSA, **UNVERIFIED**) | CySEC, FSCA, others (UK/AU status **UNVERIFIED**) | Yes | **UNVERIFIED** | **UNVERIFIED** | **UNVERIFIED** | **UNVERIFIED** | Yes | **UNVERIFIED** | None found |
| **FBS** | Reported yes | FBS Markets Inc, **Belize FSC** (licence IFSC/000102/124 reported) | CySEC entity (status **UNVERIFIED**) | Yes | **UNVERIFIED** | **UNVERIFIED** | Mobile money in some African countries (**UNVERIFIED** for Cameroon) | **UNVERIFIED** | — | — | None found (insufficient verified information) |
| **Octa** | Reported yes | Octa Markets Ltd, **Mwali/Comoros MISA** (licence T2023320 reported) | FSC Mauritius, CySEC | Yes | Spread-only (**UNVERIFIED**) | **UNVERIFIED** | **UNVERIFIED** | **UNVERIFIED** | — | — | **RBI alert list**. Reported Indian Enforcement Directorate case with ~USD 300M+ assets seized. CySEC reportedly suspended the voting rights of its controlling shareholder |
| **Deriv** | Reported yes | Deriv (SVG) LLC (**unregulated SVG**), Deriv (BVI) Ltd BVI FSC, Vanuatu, Labuan | MFSA (EU, limited) | Yes | **UNVERIFIED** | Low | Local payment agents (**UNVERIFIED**) | — | — | — | Best known for **synthetic indices** (broker-generated, not real markets). Out of scope for us |

Sources (for the table): Exness suffixes https://get.exness.help/hc/en-us/articles/360014560220-Account-type-suffixes ; Exness Mobile Money https://get.exness.help/hc/en-us/articles/360021938311-How-to-deposit-and-withdraw-with-Mobile-Money-in-Africa ; Exness account types (third-party summaries) https://brokersway.com/reviews/exness/account-types/ ; XM https://www.compareforexbrokers.com/reviews/xm-review/ , https://brokersway.com/reviews/xm/cameroon/ ; HFM https://www.compareforexbrokers.com/reviews/hfm/ , https://www.asktraders.com/learn-to-trade/guides/hotforex-mt4/ ; IC Markets / Pepperstone / FxPro entities https://www.compareforexbrokers.com/reviews/ic-markets-review/ , https://www.fxempire.com/brokers/compare/icmarkets-vs-pepperstone ; Tickmill https://www.tickmill.com/about/licences-and-regulation ; AvaTrade https://support.avatrade.com/hc/en-us/articles/360017588538-Does-AvaTrade-accept-traders-worldwide ; Octa https://www.compareforexbrokers.com/reviews/octafx/ , https://www.forexbroker.tips/xm-vs-fbs-vs-octa-safety-comparison/ ; FBS https://en.wikipedia.org/wiki/FBS_(brokerage) ; Deriv https://www.fxempire.com/brokers/deriv ; Philippines SEC advisory https://bitpinas.com/regulation/sec-exness/ , https://business.inquirer.net/567948/sec-warns-investing-public-vs-exness-global-hf-markets ; RBI alert list https://rbi.org.in/scripts/bs_viewcontent.aspx?Id=4235 ; FCA clone warning https://fxnewsgroup.com/forex-news/regulatory/fca-warns-against-pepperstone-clone-firm/ ; Mobile Money comparisons https://www.fxleaders.com/forex-brokers/forex-brokers-accepting-mobile-money/ , https://camiforex.com/icmarkets-vs-exness-vs-xm/ ; Cameroon availability lists https://brokerchooser.com/best-brokers/best-forex-brokers/cameroon , https://www.fxleaders.com/forex-brokers/forex-brokers-by-country/forex-brokers-cameroon/ ; free VPS conditions https://investingoal.com/forex/broker/free-vps/ , https://www.fxleaders.com/forex-brokers/vps-hosting-forex-brokers/

### C.2 Local regulatory context (Cameroon / CEMAC)

- **COSUMAF** (Commission de Surveillance du Marché Financier de l'Afrique Centrale) has been the single securities regulator for the six CEMAC countries since 2019. Reportedly its mandate does not expressly cover offshore online FX/CFD brokers, and there is no local licensing regime or compensation scheme for them. COSUMAF warned in 2021 about illegal investment firms promising returns up to 500% and named 20 such firms. Sources: https://en.wikipedia.org/wiki/Central_African_Financial_Market_Supervisory_Commission , https://www.daytrading.com/cm/forex (secondary). Practical meaning: **no local regulator will help recover funds from an offshore broker.**
- **BEAC foreign-exchange regulation** (CEMAC Regulation of 21 Dec 2018, in force March 2019, with BEAC instructions), as summarized by law firms:
  - transfers abroad up to **CFAF 1 million per month per person** follow a simplified regime;
  - larger transfers need supporting documents;
  - outgoing **portfolio investment above CFAF 20 million** needs prior authorization.
  - Sources: https://www.lexology.com/library/detail.aspx?g=8804916d-19da-4672-856c-7f9f2dbf704d , BEAC regulation PDF https://www.beac.int/wp-content/uploads/2020/06/REGULATION_compressed.pdf .
  - Funding an offshore broker account is a transfer abroad. **How these rules apply to retail broker deposits (via Mobile Money or card) is not something this research can confirm. Ask a bank or local adviser.**
- **Taxes:** no solid source found on the tax treatment of FX/CFD gains for Cameroonian residents. Keep complete records (the journal exports them) and ask a local tax adviser.

### C.3 Scam patterns aimed at African retail traders (short)

- **Fake "account managers"** (Telegram/WhatsApp/Facebook) who ask for your MT5 **master password**, or for deposits to a personal Mobile Money number, promising fixed monthly returns. Rule: **never share the master password**. The read-only *investor password* is enough for anyone who only needs to watch.
- **Signal sellers / "copy my trades" groups** with screenshots of profits (easily faked) and paid VIP tiers.
- **Clone brokers:** websites copying a real broker's name and licence number with a different domain (e.g. the FCA's warning about a Pepperstone clone). Always reach the broker from the regulator's register entry, not from links in messages.
- **Ponzi "forex investment" schemes** promising 20–500% returns (COSUMAF 2021 warning. Ghana and Nigeria regulators publish similar warnings): https://www.brokertoolshub.com/scam-tracker , https://www.dailymaverick.co.za/article/2024-07-07-fraudsters-use-telegram-app-to-offer-bogus-investment-opportunities/
- **"Recovery" scams** targeting previous victims ("pay a fee and we recover your money").
- **Withdrawal blocks:** "pay tax/fees before you can withdraw". A legitimate broker deducts fees from the balance and does not ask for new money to release a withdrawal.

### C.4 Recommendation (opinion, with caveats)

1. **Exness** (MT5, preferably a **Raw Spread** account for transparent costs, or **Standard** if the minimum matters). Best fit for local payments (MTN MoMo / Orange Money reported for Cameroon) and small minimums. Large broker with top-tier group licences.
   - The Cameroon client contract will be with the **Seychelles** entity.
   - It has regulator advisories in other jurisdictions (Philippines, India).
   - It markets very high leverage. Set account leverage to the lowest offered and rely on our 5:1 internal cap.
2. **IC Markets** or **Pepperstone** (MT5 Raw/Razor). Strongest group regulation and low, transparent raw-spread pricing.
   - Offshore entity (Seychelles/Bahamas) for Cameroon.
   - No confirmed Mobile Money, so funding likely means a card/bank transfer subject to BEAC rules.
   - IC Markets requires USD 200 minimum.
   - Cameroon acceptance must be confirmed at sign-up.
3. **HFM** as an alternative to Exness if its Mobile Money works for Cameroon. Note the MT5 offering is reportedly under the SVG-registered entity, which is the weakest form of oversight in this list.

Not recommended:

- **Deriv**: synthetic-index focus, SVG entity.
- **Octa**: enforcement-related reports.
- **FBS**: excluded only for lack of verifiable information, not because of proven wrongdoing.

### C.5 Checklist: how the user can verify a broker themselves

1. **Identify the legal entity.** Download the Client Agreement shown at sign-up for *your* country. Note the exact company name, registration number and licence number.
2. **Check the regulator's own register** (not the broker's site): Seychelles FSA, Bahamas SCB, Mauritius FSC, Belize FSC, BVI FSC. Confirm the **website domain** listed there matches the one you use (clone check). Also search IOSCO I-SCAN (https://www.iosco.org/i-scan/) and the FCA warning list for the brand.
3. **Open the MT5 demo first.** Note the demo and live **server names** (they should match the broker's own documentation). In the terminal or via our health check, confirm:
   - `margin_mode = 2` (hedging);
   - EURUSD `trade_contract_size = 100000`, `volume_step`, `trade_stops_level`, `filling_mode`, `swap_long/short`, `swap_rollover3days`;
   - typical spread at 07:00, 12:00 and 17:00 New York.
4. **Test money flow with a small amount:** deposit by the method you will really use (e.g. Mobile Money), then **withdraw** part of it back to the same method. Time it and note every fee and the XAF↔USD conversion rate. Do not deposit more until a withdrawal has succeeded.
5. **Read the terms** for negative-balance protection, inactivity fees, bonus clauses (avoid bonuses: they often lock withdrawals), and whether algorithmic/API trading and VPS use are allowed.
6. **Set the lowest leverage** offered on the account.
7. **Keep records** (statements, transfer receipts) for tax and BEAC purposes.
8. **Red flags, stop immediately:**
   - guaranteed returns;
   - unsolicited contact;
   - requests for your master password or for payment to a personal number;
   - "fees" required before a withdrawal;
   - pressure to deposit more;
   - a domain that differs from the regulator's register.

---

## D. Implications for our design

### D.1 Bar alignment (H4/D1)

- MT5 builds H4/D1 in **server time**. For "NY + 7 h" brokers (§A.10), server 00:00 = 17:00 New York, so broker D1 and H4 (00, 04, …, 20 server = 17, 21, 01, 05, 09, 13 NY) **match our New-York-close convention** (`03` §5, `06` §1). For brokers on other clocks they do not (e.g. a Sunday D1 bar, H4 bars at UTC multiples).
- **Rule:** fetch **H1** bars (and M1/M15 where needed), convert to UTC with the detected server-time rule, and **aggregate H4/D1 ourselves** with the 17:00 New York boundary. Never consume broker D1/H4 directly. This keeps signals identical across OANDA, MT5 brokers and the pinned datasets.
- Unit-test the aggregation around US/EU DST transitions.

### D.2 Ask derivation from bid + spread (accuracy)

MT5 bars are bid bars with one `spread` value (points, likely the bar minimum). Deriving `ask_high = bid_high + spread × point` under-states the ask side.

**Evidence [OURS]** (FXCM M1 bid/ask, one month each: GBP/USD Feb 2012, USD/JPY Feb 2013, aggregated to H1; `bid_high + min M1 spread` vs the true ask high):

| Pair | Median under-statement | p90 | p99 | Share of bars > 0.5 pip |
|---|---|---|---|---|
| GBP/USD | 0.50 pip | 1.20 | 3.40 | 53% |
| USD/JPY | 0.30 pip | 0.70 | 2.54 | 19% |

Using `max(bar min-spread, rolling 20-day median spread)` instead reduces the median error to about 0 (p90 ≤ 0.3 pip), but the p99 stays at 2–3 pips (spread spikes). Caveats: one month per pair, FXCM data, older years.

Rules:

1. In the backtester and the labeler, short stops/TPs and long entries use `ask = bid + max(bar_spread, spread_profile[instrument, hour_of_week])`. The profile is built from MT5 tick history (`copy_ticks_range`, `COPY_TICKS_INFO`) where available, else from our own live spread log.
2. Report the "ambiguous by spread" bars (where the decision flips within ±1 p99 error) in the backtest report.
3. For live, record `symbol_info_tick` bid/ask at every decision and fill, so the spread model is calibrated from our own broker over time.

### D.3 History depth for backtests vs the pinned datasets

- Broker MT5 history: bid-only M1-derived bars, depth broker-specific, limited by "Max bars in chart" (default reportedly 100k bars: ~16 years of H1, ~4 years of M15). Ticks are often shallower.
- Use the **broker's own MT5 H1 history** for broker-specific validation (same feed as live), downloaded through the bridge into the candle store with `source="mt5:<server>"`, `price_side="B"`, `spread="bar_min_points"`.
- Keep using the **pinned datasets** (`07` §3) for cross-source checks, and the LEAN OANDA bid/ask set for spread realism.
- The ejtraderLabs set is itself an MT5 export following the "NY + 7 h" clock (§A.10).
- Record `server`, timezone rule and `maxbars` in the dataset metadata.

### D.4 Idempotency with `magic` and `comment`

MT5 has no client-order-id field. Use:

- **`magic`** = `AFX_BASE + strategy_index` (e.g. 7,310,001 for S1), a fixed integer range so reconciliation can tell our positions from manual ones.
- **`comment`** = `"afx:" + base32(sha256(client_id))[:12]` = 16 chars ASCII. Within the 31-char limit, with room for broker suffixes like `[sl …]`. Store the full `client_id` ↔ short id mapping in our DB.
- **Submit path:**
  1. Persist the intent (`client_id`, short id, request) **before** sending.
  2. Send.
  3. On any ambiguous outcome (`None` with IPC error, 10012, 10031, 10011, bridge timeout): **reconcile** before deciding. Search `positions_get(symbol=…)` and `history_deals_get(t_submit − 5 min, now)` / `history_orders_get(...)` for our `magic` and comment prefix.
  4. Found → adopt the result. Not found after 10 s → treat as not sent; a re-send reuses the same `client_id`.
- The bridge's own idempotency store (§B.4) catches retries of the same HTTP request.
- **Broker-modified comments:** match on `magic` + symbol + side + volume + time window when the comment no longer matches.

### D.5 Client-managed trailing stops and reconciliation

- Use **server-side SL/TP** (the `sl`/`tp` of the position) for protection. Do **not** use MT5's built-in trailing stop (client-side, dies with the terminal).
- Our chandelier/break-even logic (`04` §3) runs on bar close and sends `TRADE_ACTION_SLTP` with `position=<ticket>`, `symbol`, `sl` (and the unchanged `tp`), only when the new SL is tighter by ≥ 1 tick.
- Respect `trade_stops_level` (new SL at least `stops_level × point` away from the current bid for longs / ask for shorts) and `trade_freeze_level` (if price is within it, retcode 10029: retry next bar).
- 10025 NO_CHANGES = success.
- Round SL to `digits`. Use Python `round(x, digits)` on a `Decimal`-derived value. MT5 takes floats, so exact decimal strings do not apply. Never send more decimals than `digits`.
- **Reconciliation on start-up/reconnect:** `positions_get()` vs DB. Unknown positions with our `magic` → adopt. Others → "external", never touch. DB positions missing at the broker → fetch closing deals with `history_deals_get(position=<id>)`. Every position must have `sl > 0`, else set it or close.

### D.6 Netting accounts vs "one trade per instrument"

- **Netting** (`margin_mode = 0`): one position per symbol. A second order in the same direction **increases** it (one shared SL/TP). An opposite order **reduces or reverses** it (`DEAL_ENTRY_INOUT`). Two strategies on one symbol would silently merge.
- **Hedging** (`margin_mode = 2`): each market order creates its own position with its own SL/TP and ticket. That matches our trade-level model. Closing requires `position=<ticket>`. **Without it an opposite order opens a new hedge position.**
- **Decision:**
  - Stage 1b **requires a hedging account**. The adapter's capability flags report `supports_hedging=True` and `position_per_trade=True`.
  - On a netting account, the adapter refuses `live` and, in `practice`, enforces **max 1 open trade per instrument across all strategies** (the risk engine reads `capabilities.netting`).
  - Closes always send exact volume + `position`.
- `fifo_close = True` accounts (US-style) are unsupported.

### D.7 Symbol mapping

- Canonical instrument `EUR_USD` ↔ broker symbol. Discover with `symbols_get(group="*EURUSD*")` and filter on:
  - `currency_base == "EUR"` and `currency_profit == "USD"`;
  - `trade_calc_mode == SYMBOL_CALC_MODE_FOREX (0)`;
  - `trade_mode == 4` (full);
  - `trade_contract_size == 100000`;
  - prefer `path` under a Forex folder.
- Broker suffixes vary by account type (Exness Standard `EURUSDm`, Zero `EURUSDz`, Raw none). Some brokers use `.r`, `.ecn`, `#`, `pro`.
- Store the resolved mapping in config, require operator confirmation on first run, and re-validate at every start (fail closed if the symbol vanished or its spec changed).
- `pip_size = 10 × point` for 5/3-digit FX quotes (`point` 1e-5 / 1e-3). Store both `point` and `pip`, and do not assume.

### D.8 Lot granularity → minimum equity (new risk constraint)

MT5 volumes are lots with `volume_min = volume_step = 0.01` (1,000 units) on standard accounts (recorded EURUSD spec). With our ATR stops, the smallest possible trade may already exceed the risk budget:

```
min_risk = volume_step × contract_size × stop_distance × QHC
required_equity = min_risk / risk_per_trade
```

EUR/USD, S1 stop ≈ 60 pips (2.5 × ATR(20,H4), `04` §2.4): `0.01 × 100000 × 0.0060 = USD 6`.
At 0.5% risk → **equity ≥ USD 1,200**. At 0.25% (live phase 1) → **≥ USD 2,400**. Below that, the
quantized size rounds to 0 and the trade is skipped. Rounding up would breach the risk limit,
so never round up.

Implications:

- The risk engine must compute this from live symbol specs and **surface it on the dashboard** ("account too small for S1 at current risk settings").
- Cent/micro accounts offer smaller minimum sizes (contract sizes vary by broker, **UNVERIFIED**), but availability on MT5 varies (Exness Standard Cent is reportedly MT4-only; **UNVERIFIED** for others).
- Do not lower the stop distance to fit the account. That changes the strategy.

### D.9 Faithful fake `MetaTrader5` module (tests)

The backend's `MT5Broker` adapter is tested with respx against the bridge API. The **bridge** is tested on Linux CI with an injected fake module (`mt5 = importlib.import_module(settings.mt5_module)`; default `"MetaTrader5"` on Windows, `"tests.fakes.fake_mt5"` in tests). Fake spec:

**Surface (module-level functions, same names, argument styles and return types):**

- Lifecycle: `initialize(path=None, *, login=None, password=None, server=None, timeout=60000, portable=False) -> bool`, `login(login, *, password=None, server=None, timeout=60000) -> bool`, `shutdown() -> None`, `version() -> tuple[int,int,str] | None`, `last_error() -> tuple[int,str]`.
- Info: `account_info() -> AccountInfo | None`, `terminal_info() -> TerminalInfo | None`.
- Symbols: `symbols_total() -> int`, `symbols_get(group=None) -> tuple[SymbolInfo, ...] | None`, `symbol_info(s) -> SymbolInfo | None`, `symbol_info_tick(s) -> Tick | None`, `symbol_select(s, enable=True) -> bool`.
- Data: `copy_rates_from/_from_pos/_range(...) -> np.ndarray | None` (exact rates dtype, §A.6), `copy_ticks_from/_range(...) -> np.ndarray | None` (exact ticks dtype, §A.7).
- Trading: `order_calc_margin(...) -> float | None`, `order_calc_profit(...) -> float | None`, `order_check(dict) -> OrderCheckResult | None`, `order_send(dict) -> OrderSendResult | None`.
- State: `positions_total() -> int`, `positions_get(*, symbol=None, group=None, ticket=None)`, `orders_total()`, `orders_get(...)`, `history_orders_total/get(...)`, `history_deals_total/get(...)`.
- Named tuples with the **exact field order** from §A.3–A.9 and a working `._asdict()`.
- Constants: a vendored copy of every constant in `MetaTrader5/__init__.py` 5.0.6231 (§A), plus `TRADE_RETCODE_HEDGE_PROHIBITED = 10046` defined only in the fake's test helpers, so production code must use the raw int.

**Behaviour to emulate:**

1. Before `initialize()` (or after `shutdown()`): data and trading calls return `None` and `last_error() == (-10004, 'No IPC connection')` (exact code **UNVERIFIED**. Keep it configurable).
2. On success, `last_error() == (1, 'Success')`. Empty results return `()` / an empty array, **not** `None`.
3. Unknown symbol → `None` with `(-4, 'Terminal: Not found')` (**UNVERIFIED** exact pair).
4. Bad request field types / unknown keys → `None` with `(-2, 'Invalid "<field>" argument')`. `comment` longer than 31 chars → `None` with `(-2, 'Invalid "comment" argument')`.
5. **Failure injection queue:** next call returns `None` with any IPC code (−10001…−10005), or `order_send` returns a given retcode (10004 requote with new bid/ask, 10012 timeout **after** actually creating the position, to test reconciliation, 10027 algo trading off, 10018 market closed, 10019 no money, 10030 invalid fill).
6. **Execution semantics:**
   - `trade_exemode` (market vs instant) decides the required fields;
   - `filling_mode` flags are validated (10030);
   - `volume` must be a multiple of `volume_step` within min/max (10014);
   - `sl`/`tp` must respect `trade_stops_level` (10016);
   - `trade_freeze_level` → 10029;
   - `trade_mode` / market-hours calendar → 10018;
   - **hedging vs netting position accounting**, including reversal (`DEAL_ENTRY_INOUT`) on netting and new-position-on-missing-`position` on hedging.
7. **Price process:** a scripted tick sequence (bid/ask) per symbol. Advancing the clock triggers SL/TP closes, creating `TradeDeal(entry=1, reason=4/5, comment="[sl …]"/"[tp …]")` (exact broker comment format **UNVERIFIED**; make it configurable). Commissions and swaps are applied per config (`swap_rollover3days`).
8. **Server clock:** all emitted times use a configurable rule (default "America/New_York + 7 h"), so the bridge's time-detection code is exercised, including DST weeks.
9. **Rates:** generated from the tick script or from a fixture CSV. The last row is the unfinished current bar. `spread` = bar minimum in points.
10. Determinism: seeded RNG and no wall-clock reads (use the injected `Clock` from `domain/clock.py`).

Golden recordings: save JSON snapshots of real bridge responses from a **demo** account (logins masked) as fixtures under `backend/tests/fixtures/mt5/` (gitleaks allow-listed path). Assert that the fake produces identical shapes.

### D.10 Other adapter rules

- **Capability flags** (from `01` §4): `units_step` = `volume_step × contract_size` per symbol, `supports_sl_on_fill=True` (verify per broker, §A.8), `supports_trailing_stop=False` (we trail client-side), `supports_hedging` from `margin_mode`, `max_orders_per_second=1` (opinion; MT5 has no documented API rate limit, but 10024 exists).
- **Order frequency:** ≤ 1 trading request per second per account, with a jittered 1–3 s pause between retries.
- **Financing model:** from `swap_mode`, `swap_long/short` and `swap_rollover3days` (not hard-coded Wednesday).
- **Safety interlock:** `account_info().trade_mode` must be 0 in `practice` and 2 in `live`. In `live`, `login` must equal `FXBOT_LIVE_CONFIRM_ACCOUNT_ID`, and entries start paused (brief principle 1).
- **CI:** add a Windows job that runs the bridge's unit tests with the fake module (and, optionally, imports the real `MetaTrader5` wheel to check constants match the vendored copy). Keep the backend Windows-compatible (§B.3).

---

## E. UNVERIFIED items (to confirm on a demo account early in Stage 1b)

| Item | How to confirm |
|---|---|
| Server-clock timestamps and the "NY + 7 h" rule for the chosen broker | §A.10 detection on the demo server. Compare with a UTC reference |
| `spread` column = bar minimum spread | Compare `copy_rates_range` spreads with `copy_ticks_range` for the same hours |
| Empty results return `()` rather than `None` | Call `positions_get()` with no positions. Check `last_error()` |
| `last_error()` code before `initialize()` / unknown symbol | Call without initializing / with a bogus symbol |
| SL/TP accepted on Market-Execution DEAL requests at the broker | `order_check` + demo `order_send` with `sl`, then `positions_get` |
| Default and exact behaviour of `deviation` under Market Execution | Demo fills during news vs requested price |
| `tradeapi_disabled` ↔ "Disable automatic trading via external Python API" | Toggle the option, read `terminal_info()` |
| Terminal runs unattended after a VPS reboot without interactive logon | Reboot test on the VPS |
| Broker comment rewriting on SL/TP exits | Let a demo trade hit SL. Read the deal comment |
| Broker facts in §C (acceptance, entity, payments, suffixes, costs) | User checklist §C.5 |
| Thread-safety of the module | Not needed if §A.2's single-worker rule is followed |

## F. Sources (additional to those inline)

- PyPI `MetaTrader5` 5.0.6231: https://pypi.org/project/MetaTrader5/ (wheel inspected locally)
- MQL5 Python integration reference (official URLs, read via mirror https://github.com/caoshuo594/mql5-help-mcp): `initialize` https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py , `login` …/mt5login_py , `last_error` …/mt5lasterror_py , `account_info` …/mt5accountinfo_py , `terminal_info` …/mt5terminalinfo_py , `symbol_info` …/mt5symbolinfo_py , `symbol_info_tick` …/mt5symbolinfotick_py , `symbol_select` …/mt5symbolselect_py , `copy_rates_from` …/mt5copyratesfrom_py , `copy_ticks_from` …/mt5copyticksfrom_py , `order_check` …/mt5ordercheck_py , `order_send` …/mt5ordersend_py , `positions_get` …/mt5positionsget_py , `history_deals_get` …/mt5historydealsget_py ; MQL5 constants: trade return codes https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes , MqlTradeRequest https://www.mql5.com/en/docs/constants/structures/mqltraderequest , MqlTradeResult https://www.mql5.com/en/docs/constants/structures/mqltraderesult , symbol properties https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants , terminal properties https://www.mql5.com/en/docs/constants/environment_state/terminalstatus , deal properties https://www.mql5.com/en/docs/constants/tradingconstants/dealproperties , MqlRates https://www.mql5.com/en/docs/constants/structures/mqlrates , CopyTicks https://www.mql5.com/en/docs/series/copyticks
- MQL5 book, Python chapter: https://www.mql5.com/en/book/advanced/python (7.9.1 Python API trading switch, 7.9.6 terminal_info, 7.9.9 reading quotes)
- Recorded outputs: https://github.com/QuantInsti/webinars ("Automated Trading Using MT5 and Python"), https://github.com/Quantreo/MetaTrader-5-AUTOMATED-TRADING-using-Python
- Stubs: https://pypi.org/project/metatrader5-stubs/
- Comment-length field report: https://github.com/rellis3/MacroFXModel/pull/1468
- Bar spread semantics (community): https://www.mql5.com/en/forum/266519 , https://tickstory.com/forum/viewtopic.php?t=2964
- Max bars / M1 storage: https://www.mql5.com/en/book/advanced/python/python_copyrates , https://www.mql5.com/en/forum/342007
- Timestamp report: https://www.mql5.com/en/forum/515951
- IPC timeout reports: https://www.mql5.com/en/forum/443248 , https://github.com/gmag11/MetaTrader5-Docker/issues/15
- Trailing stop is client-side: https://www.mql5.com/en/forum/222326
- Linux bridges: https://github.com/lucas-campagna/mt5linux (inspected: `rpyc.classic.connect`, `conn.eval`), https://github.com/gmag11/MetaTrader5-Docker (inspected: `--host 0.0.0.0`, `-p 8001:8001`), https://pypi.org/project/pymt5linux/ , https://pypi.org/project/aiomql/
- MQL5 VPS limits (no Python/DLL): https://www.mql5.com/en/forum/509181 , https://www.marginvps.com/blog/mql5-virtual-hosting-vs-forex-vps/
- VPS pricing/latency (vendor/third-party): https://www.vpsforextrader.com/blog/cheapest-mt5-vps-hosting/ , https://cybernews.com/best-web-hosting/contabo-review/pricing/ , https://newyorkcityservers.com/blog/equinix-datacenter-history-for-financial-trading
- MetaApi: https://metaapi.cloud/ , https://pypi.org/project/metaapi-cloud-sdk/ , pricing summary https://www.metatraderapi.net/blog/metatrader-api-vs-metaapi/
- FXCM M1 bid/ask fixtures used in §D.2: https://github.com/nautechsystems/nautilus_trader (`test_data/fxcm/`)
