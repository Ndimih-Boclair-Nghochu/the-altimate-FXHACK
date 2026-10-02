# Altimate FX — Roadmap

Scope and acceptance criteria for stages 0–8, including stage 1b. `docs/PROJECT_BRIEF.md` wins on any conflict.
Design details live in `docs/ARCHITECTURE.md`; progress lives in `docs/STATUS.md`.

## How to read this

- A stage is **done** when every acceptance box below is checked, the Definition of Done
  holds, and `docs/STATUS.md` records the commit/PR.
- Backend test paths are relative to `backend/tests/` (mirrors `src/fxbot/`). Frontend tests are
  co-located under `frontend/src/`. Test file names are binding; rename them here first.
- Stages are sequential (brief). Prototyping the next stage against mocks is fine, but nothing
  from stage N+1 is committed before stage N is done.
- Default parameters come from `docs/research/00-summary.md` §2 (brief). References such as
  `R03 §5.2` mean `docs/research/03-strategies.md` section 5.2; `SR-n` refers to
  `docs/SECURITY.md`. Change a default in the research summary (with reasons) and here, never
  silently in code.

## Definition of Done (every stage)

- [ ] Backend gates green from `backend/`: `uv sync`, `uv run ruff check .`,
      `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest`.
- [ ] Frontend gates green from `frontend/` whenever frontend code changed:
      `npm ci`, `npm run lint`, `npm run typecheck`, `npm test -- --run`, `npm run build`.
- [ ] CI (`.github/workflows/ci.yml`) green on the pushed commit, including the security job.
- [ ] No test opens a real network socket (guard in `tests/conftest.py`); broker I/O is tested
      with `respx` against fixtures in `tests/fixtures/<broker>/`, with the fake `MetaTrader5`
      module (stage 1b), or with a fake WebSocket server (stage 8).
      Tests that need real market data are marked `real_data` and skip when
      `data/validation/` is absent; CI uses synthetic data only.
- [ ] No secret in logs, exceptions, API responses, fixtures or the frontend bundle. Fixtures use
      the canonical fake credentials from `.gitleaks.toml`.
- [ ] Decision code (`indicators/`, `regime/`, `strategies/`, `risk/`, `learning/`,
      `engine/pipeline.py`) reads time only from an injected `Clock` and uses complete bars only.
- [ ] Security requirements listed for the stage in SECURITY.md §7 are met.
- [ ] `ARCHITECTURE.md` updated if an interface changed; `STATUS.md` row and decisions log updated.
- [ ] Security review done and findings fixed or tracked (stages 1, 1b, 5, 6, 7; recommended for 8).
- [ ] Committed and pushed; commit/PR linked in `STATUS.md`.

## Overview

| # | Stage | Owner(s) | Depends on | Security review |
|---|---|---|---|---|
| 0 | Foundation | all (lead integrates) | — | — |
| 1 | Broker connectivity & market data | backend | 0 | yes |
| 1b | MetaTrader 5 adapter (+ optional local bridge) | backend | 1 | yes |
| 2 | Indicators, regime, strategies, backtester, shared decision pipeline | backend | 1, 1b | — |
| 3 | Risk management engine | backend | 2 | — |
| 4 | Adaptive learning | backend | 2, 3 | — |
| 5 | Live engine + REST/WS API + auth | backend | 1–4 | yes |
| 6 | Dashboard UI | frontend | 5 | yes |
| 7 | Hardening, deployment, docs, E2E paper run | security + all | 1–6 | yes (final) |
| 8 | cTrader Open API adapter (**optional**) | backend | 1, 5 | recommended (new credentials, new host) |

Persistence tables are introduced with the stage that first needs them (`create_all` until
stage 5, Alembic migrations from stage 5):
1 → `instruments`, `datasets`, `candles`; 2 → `backtest_runs`, `backtest_trials`;
3 → `risk_events`, `settings`; 4 → `signals`, `labels`, `model_versions`, `model_scores`,
`bandit_state`, `strategy_evaluations`; 5 → `orders`, `trades`, `equity_snapshots`
(+ `sessions` if sessions persist, SR-27).

---

## Stage 0 — Foundation

**Status.** Done (see `docs/STATUS.md`). Kept for traceability.

**Objective.** Shared understanding and empty-but-green skeletons so stage 1 starts on solid ground.

**In scope.** Research reports; roadmap, architecture, status, ADRs; threat model; backend and
frontend scaffolds with all quality gates wired; CI.
**Out of scope.** Any trading, broker or data logic; auth; deployment hardening (stage 7);
real UI pages.

**Deliverables.**

| Item | Owner |
|---|---|
| `docs/research/*` (strategy evidence, regime detection, risk sizing, meta-labeling/bandits, OANDA v20 notes) | research |
| `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md`, `docs/adr/0001`–`0005` | PM |
| `docs/SECURITY.md` (threat model, secret handling, auth, live interlock requirements) | security |
| `backend/pyproject.toml`, `backend/uv.lock`, `src/fxbot/` with every package from the brief layout (importable, empty where not yet built), `config.py`, `logging.py`, `cli.py` (`fxbot` entry point), `api/app.py` with `GET /api/health`, `backend/.env.example`, `backend/Dockerfile` | backend |
| `frontend/` Vite + React + TS strict + Tailwind + ESLint + Prettier + Vitest; deps from the brief installed; app shell with router and placeholder routes for the 7 pages | frontend |
| `.github/workflows/ci.yml` running both gate sets on push and PR | lead (backend/frontend supply their jobs) |
| Root `.gitignore`, project `README.md` replacing the original placeholder, `docker-compose.yml` skeleton | lead |
| `.gitleaks.toml` secret-scanning config | security |

**Acceptance criteria.**

- [ ] All PM, research and security docs above exist and are cross-linked from `README.md`.
- [ ] `tests/test_config.py`: default `Settings()` has mode `paper`; secrets are `SecretStr` and
      never rendered; `practice` needs credentials; `live` refused unless `ALLOW_LIVE_TRADING`,
      `FXBOT_LIVE_TRADING_CONFIRMED` and credentials are all set; `.env.example` documents every
      setting with safe defaults.
- [ ] `tests/test_logging.py`: secret-named keys, `SecretStr` values, credential patterns in text
      and tracebacks are masked in console and JSON output.
- [ ] `tests/test_api_health.py`: `GET /api/health` → 200 with `status: ok`, version and mode;
      no auth needed; no secret in the response.
- [ ] `tests/test_cli.py`: invalid configuration exits non-zero without echoing secrets.
- [ ] `tests/conftest.py` network guard: a test that opens a socket fails (self-test included).
- [ ] mypy runs in strict mode on `src/`; ruff config committed.
- [ ] `frontend/src/App.test.tsx`: shell renders; nav links for Overview, Trades, Strategies,
      Learning, Risk, Backtests, Settings present.
- [ ] CI runs on a PR and is green for both jobs.
- [ ] ADRs 0001–0005 accepted (or amended) by the lead.

**Risks.** Agents diverge on names → ARCHITECTURE.md interface sketches are the reference;
scaffold over-reaches into stage 1 → keep stubs empty; lockfiles missing → CI not reproducible.

---

## Stage 1 — Broker connectivity & market data

**Objective.** Talk to OANDA v20 and the paper broker through one capability-aware `Broker`
protocol, and build a provenance-tracked candle store with bid and ask prices, all testable
offline.

**In scope.** Domain models; `Broker` + `MarketDataFeed` protocols with capability flags; OANDA
REST client, adapter, pricing and transaction streams; paper broker; synthetic and replay feeds;
candle store, OANDA downloader, validation-data fetcher, resampling; account-bound live
interlock in config and broker factory (SR-9 – SR-11).
**Out of scope.** Indicators, strategies, risk rules, order lifecycle management, the live bar
poller (stage 5), API beyond health, UI. Non-market order types. MT5 (stage 1b), cTrader (stage 8).

**Deliverables** (`backend/src/fxbot/`).

- `domain/models.py` — `Instrument` (pip location, display and units precision, min trade size,
  margin rate, financing rates and days), `Candle` with **bid and ask OHLC** (mid derived),
  `Price`, `OrderRequest`, `OrderResult`, `Fill`, `Trade`, `Position`, `AccountSummary`,
  `Transaction`. `Decimal` money, tz-aware UTC, non-finite values rejected (SR-14).
- `domain/enums.py`, `domain/clock.py` (`Clock`, `SystemClock`, `SimClock`), `domain/errors.py`
  (`BrokerUnavailableError`, `BrokerRejectedError`, `RateLimitedError`, `FeedStaleError`,
  `DataIntegrityError`, `LiveTradingNotAllowedError`).
- `brokers/base.py` — `Broker`, `MarketDataFeed`, `BrokerCapabilities` (`supports_sl_on_fill`,
  `supports_trailing_stop`, `supports_hedging`, `fifo_required`, `position_accounting`
  (`per_trade` / `netting`), `units_step`, `min_units`, `max_units`, `max_orders_per_second`,
  `candle_price_sides`) (R01 §4, ARCHITECTURE §4).
- `brokers/hosts.py` — the only mode → host mapping (SR-11). `brokers/factory.py` —
  `build_broker(settings)`, `build_feed(settings)`; re-checks the live interlock.
- `config.py` — `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` must equal `FXBOT_OANDA_ACCOUNT_ID` for `live`
  (SR-10; the bare `FXBOT_LIVE_TRADING_CONFIRMED` boolean is not sufficient on its own);
  `FXBOT_DATA_FEED` (`synthetic` / `replay` / `oanda`, paper only); `FXBOT_DATA_DIR`.
- `brokers/oanda/client.py` — own thin httpx client (no SDK), shared keep-alive client,
  token bucket 20 req/s, retries with backoff + jitter for GETs only, never for order POSTs
  (SR-17), pydantic models that ignore unknown fields (R02 §5, §11).
- `brokers/oanda/adapter.py` — `OandaBroker`: signed units, precision rounding (R02 §8),
  `clientExtensions.id` / `tradeClientExtensions.id` with prefix `afx-`, `stopLossOnFill`,
  `priceBound`, account lock to the configured account (SR-7), capability flags.
- `brokers/oanda/streaming.py` — exactly one pricing stream and one transaction stream; heartbeat
  watchdog; reconnect 1 s doubling to 30 s with jitter, ≤ 2 connections/s (R02 §5).
- `brokers/oanda/feed.py` — `OandaFeed`: **decision bars from the candles endpoint**
  (`price=BA`, `smooth=false`, `includeFirst=false`, `count ≤ 5000`, complete candles only);
  the price stream is for monitoring, spread and stale-price checks and paper fills only.
- `brokers/paper.py` — `PaperBroker`: tick-driven (live paper) or bar-driven (backtests) price
  source; buys at ask, sells at bid; long SL/TP trigger on bid, short on ask; gaps fill at the
  open; OANDA-like netting (non-hedging); transaction log with IDs; capability flags.
- `data/candle_store.py` (upserts keyed by instrument, granularity, time; provenance via
  `datasets`: source, price side, smoothed, tz of origin, SHA-256, licence note),
  `data/downloader.py` (`fxbot data fetch --source oanda --instrument … --granularity …
  --from … --price BA`, resumable, R07 §5),
  `data/validation.py` (`fxbot data fetch-validation`: pinned LEAN and ejtraderLabs URLs from
  R07 §3, SHA-256 verified, into git-ignored `data/validation/`; loaders per R07 §4),
  `data/resample.py` (H1 → H4/D1 aligned to 17:00 New York, label left, DST-safe),
  `data/synthetic.py` (seeded GBM + stochastic vol, trend segments, regime switches,
  hour-of-week spread, weekend gaps; emits BA candles and ticks), `data/replay.py`.
- `persistence/db.py`, `persistence/models.py` (`instruments`, `datasets`, `candles`),
  `persistence/repositories.py`.
- `tests/fixtures/oanda/*.json` — payloads from R02 (filled, `MARKET_HALTED` cancel,
  precision reject, close trade, dependent orders, positions, BA candles, pricing, stream lines).

**Acceptance criteria.**

- [ ] `tests/domain/test_models.py`: Decimal round-trips; NaN/inf rejected; pip size from
      `pip_location`; units > 0; naive datetimes rejected; `Candle.mid` derived from bid/ask;
      `bid ≤ ask` enforced.
- [ ] `tests/brokers/oanda/test_client.py` (respx): account summary, instruments, BA candles
      (pagination, `complete=false` dropped, `includeFirst=false`), market order with SL on fill
      and `priceBound`, close trade, open trades/positions, transactions since ID; 4xx →
      `BrokerRejectedError` without retry; 5xx/timeout on GET → retried then
      `BrokerUnavailableError`; an order POST is never retried; 429 honours `Retry-After`.
- [ ] `tests/brokers/oanda/test_streaming.py`: PRICE, HEARTBEAT, unknown type, blank line,
      malformed JSON (logged, skipped), stall → `FeedStaleError`; reconnect backoff bounds.
- [ ] `tests/brokers/oanda/test_account_lock.py`: requests only target the configured account;
      a response for another account raises (SR-7).
- [ ] `tests/brokers/test_broker_contract.py`: one parametrized suite passes for `PaperBroker`
      and mocked `OandaBroker` (and later the stage 1b and 8 adapters): capabilities exposed;
      submit → fill → open trade visible → close → transaction recorded; same `client_id`
      twice → one trade; every fill has a stop.
- [ ] `tests/brokers/test_paper.py`: fills on the correct side of the spread plus slippage;
      long stop on bid low, short stop on ask high; gap through stop fills at open; netting
      reduces before opening; P&L converted for `USD_JPY` and `EUR_GBP` in a USD account;
      deterministic with a seed.
- [ ] `tests/brokers/test_factory.py`: `paper` needs no credentials; `practice` needs both;
      `live` refused without `ALLOW_LIVE_TRADING=true` or with `FXBOT_LIVE_CONFIRM_ACCOUNT_ID`
      missing or different from the account ID, even if `Settings` validation was bypassed;
      `paper`/`practice` can never resolve to an `fxtrade` host (SR-11).
- [ ] `tests/data/test_candle_store.py`: upsert idempotent; range query ordered; gaps and
      duplicates flagged, never forward-filled; provenance stored.
- [ ] `tests/data/test_resample.py`: H1 → H4/D1 aligned to 17:00 New York across the US and EU
      DST transitions; a bar is available only after its end.
- [ ] `tests/data/test_validation.py`: loaders parse inline LEAN and ejtrader samples (scaling,
      time zone); a SHA-256 mismatch is refused; untrusted rows failing SR-44 checks rejected.
- [ ] `tests/data/test_synthetic.py`: same seed → identical series; OHLC and bid ≤ ask invariants;
      weekend gaps present; regime segments distinguishable.
- [ ] `tests/data/test_downloader.py` (respx): resumes from last stored candle; stores only
      complete candles with `price=BA`.
- [ ] `tests/test_secrets.py`: with `FXBOT_OANDA_API_TOKEN` set to a sentinel, the sentinel never
      appears in captured logs, exception messages or `repr` of client/settings objects.
- [ ] Manual (user machine, not CI): `fxbot data fetch` pulls real practice BA candles;
      `fxbot data fetch-validation` downloads and verifies the pinned files.

**Risks.** Fixtures drift from the real API (models ignore unknown fields; manual practice
smoke test); OANDA live API unavailable for the user's entity (R01 §3 → MT5 in stage 1b,
availability doc in stage 7); FIFO/no-hedging accounts (capability flag, stage 3 caps); LEAN validation files
are smoothed, so no gap analysis on them (R07 §3.1); validation-data licences unclear (never
committed).

---

## Stage 1b — MetaTrader 5 adapter

**Objective.** Let the user trade through a regulated MT5 broker that accepts their country
(ADR 0007), behind the same `Broker` protocol and safety rules, while the backend keeps running
on Linux if needed.

**In scope.** `brokers/mt5/` adapter with two transports — `direct` (the `MetaTrader5` package
in-process, backend on Windows) and `bridge` (an optional, minimal, authenticated local bridge
running next to the MT5 terminal on Windows or Wine, reached from a Linux/Docker backend);
MT5 demo as `practice` and MT5 real as `live` under the same interlock; MT5 history download;
setup guide. Details that depend on `docs/research/08-metatrader5.md` (once it lands) are
marked *(R08)* and follow that report.
**Out of scope.** MT4; MQL5 Expert Advisors; server-side trailing stops (MT5 trailing runs in the
terminal, so trailing stays client-managed); multi-terminal routing; MetaApi or other cloud
bridges (ADR 0007).

**Deliverables.**

- `brokers/mt5/adapter.py` — `Mt5Broker` + `Mt5Feed` implementing `Broker` / `MarketDataFeed`:
  - **symbol mapping** from config (`EUR_USD` ↔ broker name with suffix, e.g. `EURUSD.r`),
    validated against the terminal's symbol list at start-up;
  - **lots ↔ units** via contract size, rounded **down** to volume step, refused below the
    minimum and above the maximum volume (sizing skips the trade, never rounds risk up);
  - **ask derived from bid + spread** for MT5 bars (bid-based OHLC plus a spread value, or the
    R06 §2 spread model) *(R08)*, with the dataset marked accordingly;
  - **broker server time → UTC** with an explicit, tested rule (configured or detected offset,
    re-checked around DST changes) *(R08)*; H4/D1 decision bars resampled from UTC-converted H1
    to the 17:00 New York alignment unless the server clock is verified NY-close aligned;
  - complete bars only (the current forming bar is always dropped);
  - **idempotency via magic number + comment**: every order carries the bot's magic number and
    a short client-ID token in the comment; after a timeout the adapter searches open positions,
    orders and deal history by magic + token before any re-submit (SR-17); comment length and
    broker rewriting handled *(R08)*;
  - **filling-mode selection** from the symbol's allowed modes (FOK, then IOC, then RETURN)
    *(R08)*;
  - **stops-level validation**: SL/TP distance ≥ the symbol's stops level and outside the freeze
    level before sending; SL attached in the same deal request;
  - **netting/hedging capability** from the account margin mode → `BrokerCapabilities`
    (netting accounts: one position per instrument);
  - **client-managed trailing stops** (`supports_trailing_stop = False`; the engine moves SL on
    bar close via SL/TP modification);
  - **a single worker thread** for every MT5 call (the package is blocking and not thread-safe);
    asyncio code awaits it through a dedicated one-thread executor;
  - price monitor by polling the latest tick (no push stream), with stale-quote detection;
  - return-code mapping to `BrokerRejectedError` / `BrokerUnavailableError` / `RateLimitedError`.
- `brokers/mt5/bridge/` *(optional)* — `server.py` (runs on the Windows/Wine host:
  `fxbot mt5-bridge`), `client.py` (transport used by the adapter). Requirements:
  - allowlisted operations only, one per adapter need (account, symbols, rates, tick, positions,
    orders, deals, order check, order send, SL/TP modify, close); **no generic RPC or code
    execution**;
  - authenticated every request (shared secret as `SecretStr`, with timestamp + nonce against
    replay, or mTLS) *(final mechanism per SECURITY.md and R08)*;
  - binds to `127.0.0.1` or a private tunnel/VPN interface only, never a public interface;
    TLS whenever it leaves the host;
  - Pydantic-validated requests with bounds, request-size and rate limits, its own audit log;
  - refuses to act on any MT5 login other than the configured one.
- `config.py` — `FXBOT_BROKER` (`oanda` / `mt5`; paper ignores it), MT5 settings (login,
  password as `SecretStr` if the terminal is not already logged in, server name, terminal path,
  magic number, symbol map, transport, bridge address and secret); the account-ID check becomes
  broker-aware so that `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` must equal the **MT5 login** in `live`.
- `brokers/factory.py` — MT5 trading mode check: `practice` only on an MT5 **demo** account,
  `live` only on a **real** account (from the account's trade mode), re-checked on every
  (re)connect; `paper` never touches MT5. This replaces host pinning (SR-11) for MT5.
- `data/downloader.py` — `fxbot data fetch --source mt5 …` (bid + spread history, UTC, provenance).
- `pyproject.toml` — `MetaTrader5` as an optional, Windows-only extra (`fxbot[mt5]`, platform
  marker); SR-50 justification.
- `tests/fakes/fake_mt5.py` — a faithful fake `MetaTrader5` module: same function names,
  constants, named-tuple results, `last_error()`, return codes; simulates fills, requotes,
  invalid stops, invalid filling mode, market closed, insufficient margin, timeouts, server-time
  offset with DST, netting vs hedging accounts, volume steps and comment truncation.
- `docs/MT5_SETUP.md` — setup guide for (a) a Windows PC and (b) a Windows VPS: install the
  broker's MT5 terminal, log in to a demo account, enable algorithmic trading, keep the terminal
  running and logged in (auto-start, no sleep), clock sync, Python and `fxbot[mt5]`, choosing
  `direct` vs `bridge`, bridge secret and tunnel (no public port), RDP hardening on the VPS,
  verification steps, and moving from demo to real under the interlock.

**Acceptance criteria.**

- [ ] `tests/brokers/test_broker_contract.py` passes unchanged for `Mt5Broker` with the fake
      module, for both the `direct` transport and the `bridge` transport (bridge server and
      client wired in-process, no network).
- [ ] `tests/brokers/mt5/test_volume.py`: units → lots rounds down to the volume step; below min
      → skip; above max → reject; units reported back equal lots × contract size.
- [ ] `tests/brokers/mt5/test_time.py`: server time → UTC across both DST transitions; H4/D1
      resampled to 17:00 New York; forming bar never returned.
- [ ] `tests/brokers/mt5/test_prices.py`: ask = bid + spread for bars; tick bid/ask used for the
      monitor; crossed or stale quotes rejected (SR-18).
- [ ] `tests/brokers/mt5/test_orders.py`: filling mode chosen from symbol flags; SL inside the
      stops or freeze level rejected before sending; SL attached in the deal request; each
      return code maps to the right error; a timed-out order is found by magic + comment and
      never duplicated; positions without the bot's magic are treated as external (never
      touched, counted in exposure).
- [ ] `tests/brokers/mt5/test_capabilities.py`: netting account → one position per instrument,
      hedging account → per-trade tracking; `supports_trailing_stop` is false and the engine's
      trailing modifications go through SL/TP modify.
- [ ] `tests/brokers/mt5/test_threading.py`: all MT5 calls run on the single worker thread;
      concurrent async callers are serialized.
- [ ] `tests/brokers/test_factory.py`: `practice` refused on a real account and `live` refused on
      a demo account; `live` needs `ALLOW_LIVE_TRADING=true` and `FXBOT_LIVE_CONFIRM_ACCOUNT_ID`
      equal to the MT5 login; the check repeats after a reconnect to a different login.
- [ ] `tests/brokers/mt5/test_bridge_security.py`: unauthenticated, replayed, expired or tampered
      requests rejected; unknown operations rejected; oversized bodies rejected; refuses a
      non-loopback bind unless explicitly configured for a private interface; the bridge secret
      and MT5 password never appear in logs or responses (SR-4, SR-5).
- [ ] `tests/test_secrets.py` extended to the MT5 password and bridge secret.
- [ ] Manual (user's machine): against an MT5 **demo** account, via the chosen transport — the
      contract-suite smoke script places, modifies and closes a minimum-volume trade with SL on
      fill; history download works; reconciliation after a restart is clean; a forced timeout
      does not duplicate the order. Results recorded in `docs/STATUS.md`.
- [ ] `docs/MT5_SETUP.md` followed end to end by someone who did not write it.
- [ ] Security review of the adapter and bridge (new trust boundary); SECURITY.md updated.

**Risks.** The fake module drifting from real terminal behaviour (manual demo acceptance, R08
fixtures); the bridge becoming a remote order-entry endpoint (allowlist, auth, loopback/tunnel
only, security review); terminal not running or logged out (health check pauses entries);
broker server time and symbol conventions vary by broker; coarse volume steps (often 0.01 lot =
1,000 units) make small-account sizing skip trades; bid-only bars make costs approximate
(spread model, cost-drift monitor); broker comment rewriting weakens idempotency (deal-history
search by magic, R08).

---

## Stage 2 — Indicators, regime detection, strategies, backtester, shared decision pipeline

**Objective.** Generate signals from complete bars and evaluate them in an event-driven
backtester that runs the same decision code as live, with honest statistics about overfitting.

**In scope.** Indicators; 2-D regime classifier; three strategies with modes; `DecisionPipeline`
including the shadow path; basic order manager; risk stub; backtester with bid/ask fills, cost
model, trial registry, overfitting statistics and robustness tests (R06 §8 checklist).
**Out of scope.** Full risk rules (stage 3; the stage 3 checklist items below that need them);
learning (stage 4); live engine, API, UI. Parameter optimisation (parameters are a-priori, R03 §5).

**Defaults** (00 §2.1, R03 §5). Universe EUR_USD, GBP_USD, USD_JPY, AUD_USD (no CHF pairs).
Indicators on mid prices of complete bars; fills on bid/ask.

| Item | Default |
|---|---|
| Regime trend label | `TREND`: ADX(14) ≥ 25 and ER(20) ≥ 0.30; `RANGE`: ADX(14) < 20 and ER(20) < 0.20; `NEUTRAL` otherwise; `UNDEFINED` during warm-up |
| Regime vol bucket | ATR(14)/close percentile over 120 days: `LOW` < 0.25 ≤ `NORMAL` < 0.75 ≤ `HIGH` < 0.95 ≤ `EXTREME` |
| Hysteresis | a label must hold 2 consecutive complete bars before it switches; no new entries in `EXTREME` |
| `trend_breakout_h4` (mode **live**) | H4 bars aligned to 17:00 NY; Donchian entry 55 / exit 20; D1 TSMOM(126) direction filter (D1 aligned to 17:00 NY, usable after D1 close); ATR(20); initial stop 2.5 ATR; chandelier 3.0 ATR, never loosened; time stop 120 bars without new high-water mark; `priceBound` 0.1 ATR; allowed in TREND/NEUTRAL/RANGE × LOW/NORMAL/HIGH (R03 §5.2) |
| `mean_reversion_h1` (mode **shadow**) | H1 RANGE, H4 ADX < 25, vol LOW/NORMAL; close beyond SMA20 ± 2.0σ with RSI14 < 30 / > 70; stop 1.5 ATR14; TP SMA20 if ≥ 1R else skip; time stop 24 bars; spread ≤ 10% of stop (R03 §5.3) |
| `session_breakout_h1` (mode **shadow**) | Asian range 00:00–06:59 UTC, width 0.3–1.5 × ATR14·√7; entry 07:00–11:59 UTC on an H1 close beyond range ± 0.1 ATR; stop opposite side (cap 1.5 × ATR14·√7); TP 1.5R; flat 16:00 UTC; one trade/pair/day; GBP_USD, EUR_USD, USD_JPY (R03 §5.4) |

**Deliverables.**

- `indicators/` — Wilder ATR and ADX, Kaufman ER, SMA, EMA, RSI, Bollinger σ, Donchian, ATR
  percentile (trailing only), TSMOM sign. Pure numpy/pandas.
- `regime/` — `TrendLabel`, `VolBucket`, `RegimeState(trend, vol, inputs)`,
  `RuleBasedRegimeClassifier` with hysteresis, per instrument and timeframe.
- `strategies/` — `Strategy`, `StrategyMode` (`disabled` / `shadow` / `live`, ADR 0006),
  `Signal`, multi-timeframe `BarContext`; `trend_breakout_h4.py`, `mean_reversion_h1.py`,
  `session_breakout_h1.py`; `registry.py` with default modes. Each strategy implements entries
  (`on_bar`) and its exit policy (`manage`: trailing stop, exit signal, time stop), which the
  backtester, the live engine and the stage 4 labeler all reuse.
- `engine/pipeline.py` — `DecisionPipeline`: live-mode signals go regime → meta (pass-through) →
  allocator (pass-through) → risk; shadow-mode signals are recorded with features and a
  pre-trade-filter dry run (`executable` flag) and never produce an `ApprovedOrder`.
- `engine/order_manager.py` (basic), `risk/manager.py` (`BasicRiskManager` stub, `ApprovedOrder`),
  `persistence/journal.py` (`TradeJournal`, `InMemoryTradeJournal`).
- `backtest/engine.py` (`Backtester` with a bar-view object that blocks access past `t`,
  configurable extra latency in bars), `backtest/costs.py` (spread from BA candles, hour-of-week
  fallback table, slippage, financing at 17:00 NY from instrument rates and `daysCharged`,
  commission, cost multipliers), `backtest/metrics.py` (R06 §7), `backtest/overfitting.py`
  (PSR, DSR, MinBTL, CSCV/PBO with S = 16; `statistics.NormalDist`, no SciPy),
  `backtest/robustness.py` (trade reshuffle Monte Carlo, stationary block bootstrap, random-entry
  benchmark, cost and delay stress, ±20% parameter perturbation, per-year/per-pair split),
  `backtest/trials.py` (trial registry: every configuration run is counted per strategy family),
  `backtest/walk_forward.py`, `backtest/report.py`, CLI `fxbot backtest …`;
  `backtest_runs`, `backtest_trials` tables.

**Acceptance criteria** (engine, data and statistics items mirror R06 §8).

- [ ] `tests/indicators/test_indicators.py`: hand-computed reference values (Wilder smoothing);
      NaN only during warm-up.
- [ ] `tests/test_future_scramble.py`: for random cut points `t`, replacing all data after `t`
      with noise leaves every indicator, regime label, signal and feature at ≤ `t` unchanged
      (R06 §1); a deliberately leaking fixture strategy is caught.
- [ ] `tests/regime/test_classifier.py`: thresholds as above; 2-bar hysteresis (one-bar flip
      ignored); `EXTREME` blocks new entries; `UNDEFINED` until 120 days of ATR history.
- [ ] `tests/strategies/test_trend_breakout_h4.py`, `test_mean_reversion_h1.py`,
      `test_session_breakout_h1.py`: handcrafted bars produce the expected entry, stop, trail,
      exit and time stop; gating per R03 §5.5; D1 TSMOM not used before the D1 close.
- [ ] `tests/strategies/test_modes.py`: defaults are S1 `live`, S2/S3 `shadow`; `disabled`
      strategies are not evaluated; shadow decisions have outcome `SHADOW`, an `executable`
      flag, and never reach `OrderManager`.
- [ ] `tests/backtest/test_fills.py` (5-bar known-answer fixture, R06 §8): next-open fill on the
      correct side; long stop hit by bid low; short TP hit by ask low; gap through stop fills at
      open; same bar touches stop and TP → stop; financing over a Wednesday; extra latency
      shifts fills by N bars.
- [ ] `tests/backtest/test_entry_bar_regression.py`: for intrabar entries the entry bar's range is
      not used for stop/TP except a close beyond the stop (squeeze bug, R03 §4); for next-open
      market entries the whole entry bar is post-entry and is checked. Ambiguous bars counted.
- [ ] `tests/backtest/test_null_data.py`: on GBM/random-walk data every strategy has ≈ 0 gross and
      < 0 net expectancy; on trend-injected data the trend strategy is profitable (R06 §5).
- [ ] `tests/backtest/test_determinism.py`: same inputs + seed → byte-identical report; report
      carries data hash, config hash, code commit, seeds, trial count.
- [ ] `tests/backtest/test_metrics.py`: R06 §7 metrics match hand-computed series; Sharpe
      convention stated.
- [ ] `tests/backtest/test_overfitting.py`: PSR/DSR reproduce the R06 §4.2 worked example
      (PSR(0) ≈ 0.978, DSR ≈ 0.47 for N = 10); MinBTL matches R06 §4.3 (7 → ≈ 1.9 y,
      45 → ≈ 5.0 y, 100 → ≈ 6.4 y); PBO ≈ 0.5 on pure-noise candidates and low when one
      candidate is genuinely better.
- [ ] `tests/backtest/test_robustness.py`: reshuffle preserves expectancy and reports
      p50/p95 max drawdown and losing streak; random-entry benchmark uses identical exits and
      trade count; cost stress (spread × 1.5/× 2, slippage + 0.5/+ 1.0 pip) and +1-bar delay
      reported; seeded.
- [ ] `tests/backtest/test_trials.py`: every run increments the family's trial count; DSR uses
      the registry count, not a caller-supplied number.
- [ ] `tests/backtest/test_walk_forward.py`: train and test never overlap; purge/embargo respected.
- [ ] `tests/engine/test_pipeline.py`: one `Decision` per signal including filtered, rejected and
      shadow ones, with reasons; identical inputs → identical outputs.
- [ ] `tests/test_no_wallclock.py`: no `datetime.now(`, `datetime.utcnow(`, `time.time(` in
      decision-code packages.
- [ ] Demonstrate in CI: `fxbot backtest --strategies all --synthetic --seed 42` finishes in
      < 60 s; report includes costs by component, PSR/DSR with trial count, Monte-Carlo
      drawdown bands and stress results.
- [ ] Demonstrate locally (`real_data`): S1 on the LEAN OANDA EUR/USD set (H1 → H4) and the
      ejtrader EUR/USD, GBP/USD, USD/JPY sets; dataset provenance in the report. Results are
      sanity checks, never quoted as performance (brief principle 2).

**Risks.** Lookahead through resampling or alignment (future-scramble test, DST tests);
optimistic same-bar handling (known-answer fixture); overfitting by repeated runs (trial
registry, DSR/PBO); synthetic results mistaken for evidence (report labels data source);
backtest/live divergence (shared pipeline and exit policy, parity test in stage 5).

---

## Stage 3 — Risk management engine

**Objective.** No order reaches a broker without passing a deterministic, auditable risk check;
losses are bounded by layered limits, a drawdown ladder and a kill switch; the backtester uses
the same engine.

**In scope.** Sizing, stops, portfolio caps, exposure and correlation clusters, vol-target
overlay, loss limits, drawdown ladder, margin guard, health breakers, filters (spread, rollover,
Friday, weekend gap, news, holidays, stale price), kill switch core, fat-finger values (SR-15),
persistence of risk state and events, backtester integration.
**Out of scope.** Learning-driven multipliers (stage 4 supplies them, bounded); API/UI controls
(stages 5–6); automatic news-calendar download (manual/CSV calendar first).

**Defaults** (00 §2.2, R04 §9). Equity = NAV; trading day starts 17:00 New York.

| Key | Default |
|---|---|
| Risk per trade | 0.50% paper/practice; **0.25% in live phase 1**; ≤ 1.00% after all multipliers |
| Multipliers | `m_strategy` ∈ [0.5, 1.5], `m_meta` ∈ [0, 1], `m_drawdown` ∈ {1, 0.75, 0.5, 0} |
| Open risk / same-currency risk / cluster risk | 2.0% / 1.0% / 1.0% (cluster: 60-day ρ_eff > 0.7, recomputed daily at 17:00 NY) |
| Positions | max 4 (3 in live phase 1); 1 per strategy × instrument; 2 per instrument; opposite-direction conflicts blocked and logged; 1 per instrument when `fifo_required` or the account nets positions (MT5 netting) |
| Leverage | internal gross 5:1; net per currency ≤ 3 × equity; regulatory caps 30:1 majors / 20:1 minors as upper bound, `min(cap, 1/marginRate)` |
| Vol overlay | scale new entries by `10% / est. annualized portfolio vol` when above 10% (60-day EWMA, λ ≈ 0.97) |
| Loss limits | daily −2% (resets 17:00 NY), weekly −4% (resets Sun 17:00 NY): no new entries |
| Drawdown ladder (from peak NAV) | −5% → ×0.75 (recover above −2.5%); −8% → ×0.5 (recover above −5%); −12% → halt, manual re-arm; −20% → kill switch |
| Margin guard | `marginCloseoutPercent ≥ 0.5` or `MARGIN_CALL_ENTER` → kill switch |
| Health breakers | stale prices > 30 s, stream down > 60 s, 3 consecutive order errors → pause entries, auto-resume after 5 min healthy; reconciliation mismatch → manual |
| Stops | on fill; distance ≥ max(5 × spread, broker minimum); 1R is all-in (ask/bid entry + exit half-spread) |
| Spread filter | caps EUR_USD 2.5, GBP_USD 3.0, USD_JPY 2.5, AUD_USD 3.0, others 3.0–3.5 pips; ≤ 2.5 × 4-week hour-of-week median; ≤ 10% of stop |
| Time filters | rollover blackout 16:45–17:30 NY; no entries after Fri 15:00 NY (S2/S3 flat by 15:30); Dec 24 17:00 → Jan 2 17:00 NY no entries; half risk on US/UK bank holidays |
| Weekend gap budget | Σ units × QHC × gap_p99 ≤ 1.0% of equity (gap_p99 = 2 × measured p95, ≈ 70 pips EUR/USD); else reduce S1 on Friday 15:00 NY |
| News blackout | no entries 30 min before to 30 min after high-impact events for affected currencies; S2/S3 flat 15 min before. Calendar: manual config/CSV first; if missing, fail safe with windows around 08:30 and 14:00 ET |
| Price health | quote age ≤ 10 s, `tradeable`, bid < ask, no jump > 10 × ATR without confirmation |
| Kelly cap | after ≥ 100 closed trades (live + shadow): risk ≤ 0.25 × Kelly at the lower 80% bound; lower bound ≤ 0 → demote to shadow |
| Excluded | CHF pairs until the system is mature |

**Deliverables** (`risk/`). `sizing.py` (fixed-fractional with QHC from
`quoteHomeConversionFactors`, units rounded down, multipliers then cap), `stops.py`,
`portfolio.py` (positions, open risk, conflicts, FIFO), `exposure.py` (currency legs, clusters,
leverage, vol overlay), `limits.py` (loss limits, drawdown ladder, margin guard, health breakers),
`filters.py` (spread, rollover, Friday, weekend gap, holidays, price health),
`calendar.py` (news events from config/CSV, fail-safe windows), `kill_switch.py`,
`fat_finger.py` (SR-15 values, independent of the sizing code; enforced by `OrderManager` in
stage 5), `manager.py` (`DefaultRiskManager`, hard caps in code, `pre_trade_filters` for shadow
dry runs), `risk_events` and `settings` tables. The backtester switches to `DefaultRiskManager`.

**Acceptance criteria.**

- [ ] `tests/risk/test_sizing.py`: R04 §2.4 example reproduces 8,250 units; `USD_JPY` and
      `EUR_GBP` conversions; units round down; below `min_units` → skip; product of multipliers
      capped at 1.0%; live phase 1 uses 0.25%.
- [ ] `tests/risk/test_stops.py`: stop on the correct side, ≥ max(5 × spread, broker min);
      no stop → reject; chandelier never loosens.
- [ ] `tests/risk/test_portfolio.py`: position caps; same strategy × instrument twice rejected;
      third trade on an instrument rejected; opposite-direction conflict blocked and logged;
      `fifo_required` or `position_accounting = netting` → one per instrument; FIFO →
      oldest-first closes.
- [ ] `tests/risk/test_exposure.py`: R04 §5.1 example (long EUR_USD + short USD_CHF = 1.0%
      short USD at the limit); cluster cap with ρ_eff > 0.7; gross 5:1; risk-reducing orders allowed.
- [ ] `tests/risk/test_limits.py`: daily/weekly limits with 17:00 NY and Sunday resets; every
      ladder step and its recovery threshold; −12% halt needs manual re-arm; −20% and margin
      guard engage the kill switch; health breakers pause and auto-resume after 5 min.
- [ ] `tests/risk/test_filters.py`: each spread rule; rollover, Friday, holiday windows; weekend
      gap budget; stale/non-tradeable/crossed quotes; news blackout from a CSV calendar and the
      fail-safe windows when the calendar is missing.
- [ ] `tests/risk/test_kill_switch.py`: engage idempotent, persisted, survives restart, blocks
      every intent; release requires actor, reason and typed confirmation flag; audited.
- [ ] `tests/risk/test_fat_finger.py`: each SR-15 check, including a ×100 JPY pip-value bug
      caught independently of `sizing.py`; NaN never passes a limit check (SR-14).
- [ ] `tests/risk/test_manager.py`: every rejection has a reason code; deterministic;
      settings above SR-15 hard caps refused; shadow dry run never creates an `ApprovedOrder`.
- [ ] `tests/risk/test_approved_order.py`: `ApprovedOrder` constructible only inside `risk/`
      (SR-13).
- [ ] `tests/backtest/test_risk_integration.py` (R06 §8): backtester filters and sizing go through
      `DefaultRiskManager` with historical QHC; a synthetic crash walks the ladder and halts;
      results identical whether risk runs inside the backtester or the pipeline.

**Risks.** Currency-conversion errors (worked examples, fat-finger backstop); breakers firing on
normal variance (thresholds sized against R04 §3.1 streak tables); gaps through stops (accepted,
gap budget, CHF excluded); missing news calendar (fail-safe windows); runtime loosening of limits
(hard caps, `confirm`, audit — SR-35).

---

## Stage 4 — Adaptive learning system

**Objective.** Learn from every signal the system produces — executed, filtered, shadow and
historical — to filter trades and reallocate a bounded risk budget, with gates that make
learning from noise unlikely and every change reversible.

**In scope.** Labeling of all signals from market data, sample weights, purged/embargoed CV and
walk-forward, meta-model (champion/challenger), discounted NIG Thompson allocator with cash arm,
river-based drift monitors, model registry, meta-model promotion gates, strategy shadow → live
gate evaluation, learning scheduler, day-1 bootstrap from historical signals.
**Out of scope.** Learning that changes strategy logic or parameters; online updates of the
classifier; automatic strategy promotion (always manual approval); LightGBM (optional later);
UI (stage 6).

**Defaults** (00 §2.3, R05 §10).

| Key | Default |
|---|---|
| Labels | strategy-specific triple barrier: the strategy's own exit policy simulated on BA bars, costs included; stop first on ambiguous bars; stored `R_net`, `y`, exit reason, bars held, MAE/MFE (R), `t_end` |
| Training data | ≥ 300 labelled events per strategy (500 preferred); bootstrap from historical backtest signals; average-uniqueness sample weights |
| CV | PurgedKFold k = 5, embargo = max(holding period, 1% of n); walk-forward expanding window, monthly |
| Models | champion = pass-through or LR(C = 0.5); challenger = HistGradientBoosting(depth 3, 8 leaves, min_leaf ≥ 50, lr 0.05, ≤ 300 iters, early stop on a purged split); isotonic calibration if n_valid ≥ 1,000 else sigmoid; ≤ 20 configs per retrain, recorded |
| Size rule | `m_meta = clip((p̂ − p*) / 0.15, 0, 1)`; skip if < 0.2; never > 1 |
| Allocator | discounted NIG Thompson, γ = 0.99, μ₀ = 0, κ₀ = 10, α₀ = 3, σ₀ = 1.5R; cash arm; cells = (trend, vol) with hierarchical pooling; `m_strategy = clip(N_active × P_best, 0.5, 1.5)`; 1.0 below 20 obs; learns from executed trades only; demote to shadow if P(μ > 0) < 0.10 after ≥ 50 trades |
| Drift (river) | P&L: PageHinkley(min_instances=30, delta=0.15, threshold=60, alpha=0.999, mode="down") → warning, halve `m_strategy`; model: ADWIN(0.002) on Brier error → retrain, pass-through until promoted; features: PSI > 0.25 on ≥ 3 key features weekly; costs: PageHinkley up on realized − modeled cost → immediate alert; label base rate: ADWIN, informational |
| Meta promotion | eval window ≥ 3 months and ≥ 150 events; log-loss −1% with paired block-bootstrap 90% CI > 0; Brier not worse; calibration slope in [0.8, 1.2]; beats champion and pass-through (lower 80% bound ≥ 0); same sign in ≥ 4/5 folds; no feature > 50% importance; PBO < 0.3 if ≥ 4 candidates; 14-day shadow; 14-day cooldown; auto-rollback if worse by > 2 SE over the next 50 events |
| Strategy promotion (shadow → live) | ≥ 200 OOS trades over ≥ 2 years and ≥ 3 pairs; PSR(0) ≥ 0.95; DSR ≥ 0.90 with registry trial count; positive at 1.5× costs and with +1-bar delay; PBO < 0.3 if parameters were selected; no year/pair > 50% of R; live-shadow drawdown within MC p95; **manual approval** (R06 §6) |
| Schedule | retrain weekly Sunday 18:00 NY and on drift triggers; labeling sweep as barriers mature |

**Deliverables** (`learning/`, module map R05 §9). `features.py` (versioned schema; no own-P&L
features), `labeling.py` (reuses the strategy `manage` policy and the `PaperBroker` fill rules),
`weights.py`, `cv.py`, `meta_model.py` (`PassThrough`, LR, HGB, calibration, size rule),
`trainer.py`, `bandit.py` (`DiscountedNIGThompson`, `CashArm`, numpy only, seeded),
`drift.py` (river wrappers + PSI), `registry.py` (artifact SHA-256, data-snapshot hash, schema
version, commit, seed), `promotion.py` (meta gates, strategy gate evaluator), `scheduler.py`
(`LearningScheduler`); tables `signals`, `labels`, `model_versions`, `model_scores`,
`bandit_state`, `strategy_evaluations`; `river` added (SR-50 justification).

**Acceptance criteria.**

- [ ] `tests/learning/test_labeling.py`: handcrafted bid/ask paths give stop/TP/trail/time/signal
      exits with correct `R_net` (costs included); unlabeled until `t_end`; shadow, filtered and
      halted signals all labelled; label for an executed backtest trade equals its realized R.
- [ ] `tests/learning/test_features.py`: future-scramble invariant; schema version mismatch at
      scoring raises; schema contains no own-P&L, drawdown or account-size feature.
- [ ] `tests/learning/test_weights.py` and `test_cv.py`: uniqueness on overlapping windows; no
      training event overlaps a test window; embargo respected; walk-forward monthly splits.
- [ ] `tests/learning/test_meta_model.py`: pass-through below 300 events; `m_meta` rule, skip
      below 0.2, never > 1; planted-signal synthetic data → OOS AUC > 0.6; deterministic.
- [ ] `tests/learning/test_promotion.py`: each meta gate can fail on its own; pure-noise labels →
      challenger rejected and pass-through stays champion; shadow period and cooldown enforced;
      rollback restores the previous champion; decisions written to `model_versions` and
      `risk_events`.
- [ ] `tests/learning/test_strategy_gates.py`: gate report for each R06 §6 item; a strategy
      failing any gate cannot be promoted; passing all gates still needs manual approval.
- [ ] `tests/learning/test_bandit.py`: converges on stationary arms; adapts after a mid-stream
      mean switch; all-negative arms push mass to cash and multipliers to 0.5; clamp and
      min-obs rules; shadow labels do not update it; demotion rule fires; seeded runs identical.
- [ ] `tests/learning/test_drift.py`: each monitor with its defaults fires on a synthetic change and
      maps to its action; PSI flags a shifted distribution, not an identical one.
- [ ] `tests/learning/test_registry.py`: tampered artifact refused (SR-43); path outside the
      models directory refused; reproducibility tuple stored.
- [ ] `tests/engine/test_pipeline_learning.py`: for any p̂ and posterior, final risk ≤ base risk ×
      1.5 and ≤ 1.0% NAV; `learning/` imports nothing from `brokers/` or the order manager (SR-20).
- [ ] Demonstrate: bootstrap a first model from historical synthetic signals; walk-forward report
      shows learning-on and learning-off side by side, whatever the result.

**Risks.** Too few events (R05 §1: +0.1R needs ~600 trades → shadow and historical labels,
pooling, clamps); slow P&L drift detection (input and cost monitors, risk-engine breakers);
feedback loops (label everything, meta only shrinks, no P&L-state features); overfitting by
search (budget, trial counts, PBO); pickle loading (SR-43).

---

## Stage 5 — Live trading engine + REST/WebSocket API + auth

**Objective.** Run the shared pipeline continuously against the broker, survive restarts and
disconnects, and expose state and controls through an authenticated API.

**In scope.** Engine orchestrator, bar poller, price monitor, hardened order manager
(fat-finger and order-rate limits), reconciliation, event bus, scheduler, instance lock, SQL
trade journal, Alembic baseline, FastAPI routers, WebSocket channels, auth and browser
protections (SR-24 – SR-37), live start-up gates (SR-12), kill-switch CLI.
**Out of scope.** UI (stage 6); Docker/deployment hardening (stage 7); multi-user or
multi-account; additional brokers (stages 1b, 8).

**Deliverables.**

- `engine/engine.py` (`TradingEngine`), `engine/bar_poller.py` (at each H1/H4/D1 boundary +
  2–5 s fetch the just-closed BA candles, complete only, retry until complete or timeout),
  `engine/price_monitor.py` (stream → spread, quote age, `tradeable`, paper fills),
  `engine/order_manager.py` (state machine, `afx-` client IDs, UNKNOWN resolution, SR-15
  fat-finger and SR-16 order-rate checks, flatten-all), `engine/reconciliation.py` (R02 §9),
  `engine/events.py`, `engine/scheduler.py` (17:00 NY rollover, reconciliation, equity
  snapshots, labeling sweep, retrain and gate checks, cluster recompute), `engine/lock.py`.
- `persistence/journal.py` `SqlTradeJournal`; `orders`, `trades`, `equity_snapshots` tables;
  Alembic baseline migration for all tables.
- `api/app.py` (lifespan starts/stops engine), `api/auth.py` (argon2id password hash, opaque
  session cookie, login throttling — SR-26 – SR-28), `api/security.py` (CSRF Origin check,
  trusted hosts, headers, error handler — SR-29 – SR-36), `api/deps.py`, `api/schemas.py`,
  `api/ws.py`, `api/routers/` for every endpoint in ARCHITECTURE §8.
- CLI: `fxbot hash-password`, `fxbot kill-switch engage --reason …` (SR-19, SR-26).

**Acceptance criteria.**

- [ ] `tests/engine/test_bar_poller.py`: polls after each boundary; incomplete candles retried,
      never emitted; missing candles backfilled; bars identical to `fxbot data fetch` output for
      the same period; stream ticks never create bars.
- [ ] `tests/engine/test_engine_paper.py`: synthetic feed + `PaperBroker` + `SimClock` run N bars:
      signal → risk → order → fill → journal → closed trade → label → bandit update, all persisted;
      shadow signals labelled but never ordered.
- [ ] `tests/engine/test_parity.py`: the same bars through `TradingEngine` (paper, sim clock) and
      `Backtester` give identical decisions and trades (R06 §8, brief principle 3).
- [ ] `tests/engine/test_order_manager.py`: duplicate submit with same client ID → one order;
      timeout → UNKNOWN → transactions searched by client ID; re-submit with the same ID only if
      not found after 10 s and the signal and bar are unchanged; POST never auto-retried; SR-15
      and SR-16 limits enforced; kill switch checked before every submit.
- [ ] `tests/engine/test_reconciliation.py`: `afx-` trade unknown locally → adopted; foreign trade
      → flagged external, never touched, counted in exposure, alert; local trade missing at broker
      → closed from the broker's transaction; own trade without stop → stop attached or closed,
      `CRITICAL`; runs at start before entries; unresolved `CRITICAL` keeps entries paused.
- [ ] `tests/engine/test_interlock.py`: engine refuses `live` unless SR-10 and SR-12 gates hold;
      in `live` starts with `live_startup` pause until an operator resumes; mode, host, account
      and credentials cannot be changed through the API (SR-9).
- [ ] `tests/engine/test_kill_switch_e2e.py`: API and CLI engage flatten all paper positions,
      reject later signals, broadcast on `risk`, survive restart; CLI path honoured within ≤ 2 s.
- [ ] `tests/engine/test_restart.py`: stop mid-session and start again → state, bandit and ladder
      reloaded, reconciliation clean, no duplicate orders.
- [ ] `tests/engine/test_feed_health.py`: stale stream or quote pauses entries and auto-resumes
      after 5 min healthy; candle polling failures backfilled before decisions resume.
- [ ] `tests/engine/test_instance_lock.py`: a second engine on the same data directory refuses
      to start.
- [ ] `tests/api/test_auth_required.py`: enumerates `app.routes`; every route except
      `/api/health` and `/api/auth/login` returns 401 without a session; WS closes with 1008.
- [ ] `tests/api/test_auth.py`: argon2id verify and rehash; cookie flags; idle and absolute
      expiry; logout revokes; throttling returns 429; CSRF Origin check returns 403; untrusted
      `Host` returns 400; 422 bodies never echo input (SR-26 – SR-34).
- [ ] `tests/api/test_no_secret_leak.py`: sentinel token never appears in any GET response,
      WS snapshot or captured log.
- [ ] `tests/api/test_settings.py`: values beyond hard caps → 422; loosening needs `confirm`;
      secrets not readable or writable; before/after audited (SR-35).
- [ ] `tests/api/test_strategy_modes.py`: demotion always allowed; promotion to `live` refused
      unless the latest gate evaluation passed, and requires `confirm` and a reason; audited.
- [ ] `tests/api/test_ws.py`: handshake auth and Origin check before accept; subscribe /
      unsubscribe / ping only, 4 KiB cap; per-connection `seq` increasing; connection cap.
- [ ] `tests/api/test_routers.py`: each endpoint returns its schema; Decimals as strings;
      `/api/expectations` returns the reference backtest's R distribution and MC drawdown bands.
- [ ] Manual (user machine): practice mode runs ≥ 1 trading session against the user's broker
      demo (MT5 demo; OANDA practice where available) with zero unresolved reconciliation
      discrepancies and every trade protected by a stop.

**Risks.** Concurrency between reconciliation and orders (single trading lock); duplicate orders
on timeout (client-ID search, same-ID resubmit only under R02 §9 conditions); candle endpoint
latency at boundaries (2–5 s delay, retries); two engines on one account (instance lock, one
worker); event-loop blocking (process pool); auth gaps (security review).

---

## Stage 6 — Dashboard UI

**Objective.** A clean, fast operator dashboard showing live state with honest provenance and
expectations, and safe controls.

**In scope.** App shell, login, seven pages, typed API client with generated types, WebSocket
client, charts, strategy-mode controls, expected-vs-realized views.
**Out of scope.** Mobile-first layouts (desktop ≥ 1280 px primary, usable on tablet);
multi-user admin; editing secrets; switching the trading mode to `live` from the UI.

**Deliverables** (`frontend/src/`). `api/` (client, resource modules, 401 handling, types
generated from the backend OpenAPI schema with `openapi-typescript`), `lib/ws.ts` (reconnecting,
resubscribing WS client), `stores/` (Zustand: session state, live data, UI prefs — no
credentials, SR-38), `components/` (AppShell, ModeBadge, StrategyModeBadge, ConnectionStatus,
KillSwitchControl, ConfirmDialog, DataTable, StatCard, EquityChart, Meter, RDistributionChart,
DrawdownBandChart), `pages/` below, `routes.tsx`.

**Pages.**

| Page | Must show / do |
|---|---|
| Overview | Equity curve with range selector; realized + unrealized P&L (today, week, all); account (balance, NAV, margin used/available); open positions live via WS (instrument, side, units, entry, price, P&L, SL/TP, strategy, age); engine and feed status; **live drawdown and its percentile within the reference backtest's Monte-Carlo bands** (00 §4.3) |
| Trades | Server-paginated history; filters (instrument, strategy, side, outcome, exit reason, regime, date range) synced to URL; per-trade detail: signal → risk decision → order → fill → exit timeline, SL/TP and trail history, R-multiple, MAE/MFE, regime (trend × vol), meta score + model version, allocator multiplier, simulated label vs realized R, candle chart with entry/exit markers |
| Strategies | Per strategy: **mode** (`disabled` / `shadow` / `live`, clearly separated from the trading mode), performance (trades, win rate, expectancy R, profit factor, max DD) overall and by regime cell, live and shadow kept apart; **expected vs realized R distribution** from the reference backtest (00 §4.3); promotion gate report (R06 §6) with promote (manual approval) and demote actions; current regime per instrument (trend × vol); bandit multipliers per cell and history |
| Learning | Model versions with status (champion/challenger/retired/rejected), metrics, training window, sample count, reproducibility tuple; champion vs challenger and vs pass-through on the evaluation window; each promotion gate with pass/fail; drift monitors (P&L, Brier, PSI, cost) with alerts; manual promote/rollback/retrain (confirmed, still gated server-side) |
| Risk | Each limit vs current usage (daily/weekly loss, open risk, currency and cluster risk, positions, leverage, margin); drawdown-ladder step and multiplier; live phase; entry-pause reasons; active filters (rollover, Friday, news window); risk event log; kill switch engage/release; pause/resume entries |
| Backtests | Start a run (strategies and modes, instruments, range, data source, seed, cost model, stress options); progress via WS; results: metrics, equity + drawdown chart, trades, costs by component, PSR/DSR with trial count, PBO when applicable, Monte-Carlo bands, stress results, provenance |
| Settings | Trading mode read-only with how-to-change note; instruments; risk params within server hard caps (loosening shows old → new and needs confirm); paper data feed; news calendar upload/edit (CSV); secrets shown only as configured / not configured |

**Acceptance criteria.**

- [ ] `pages/*/*.test.tsx` for every page: loading, empty, error and populated states with a
      mocked API client.
- [ ] `pages/Overview/Overview.test.tsx`: a WS `positions` event updates the table without
      refetch; drawdown percentile shown with its reference backtest run ID.
- [ ] `pages/Trades/Trades.test.tsx`: filters round-trip through the URL; detail view renders
      the full decision timeline including label vs realized R.
- [ ] `pages/Strategies/Strategies.test.tsx`: strategy mode badges render distinctly from the
      trading-mode badge; promote is disabled while any gate fails and otherwise opens a
      confirm dialog with old → new mode and a reason field; demote needs one confirm; expected
      vs realized R chart renders with provenance; shadow results labelled "shadow (no orders)".
- [ ] `pages/Risk/Risk.test.tsx`: kill switch engages in at most two clicks (button + confirm,
      no typing, per SR-40); release requires typed confirmation; buttons disabled while the
      request is in flight; ladder step and pause reasons shown.
- [ ] `pages/Settings/Settings.test.tsx`: no input exists for any secret; trading mode is not
      editable; out-of-range risk value shows the server's 422 message; loosening shows old → new.
- [ ] `pages/Backtests/Backtests.test.tsx`: results show data source, seed, cost model, trial
      count and DSR.
- [ ] `lib/ws.test.ts`: reconnects with backoff, resubscribes, drops out-of-order `seq`.
- [ ] `api/client.test.ts`: 401 → session cleared and one redirect to login; requests use
      `credentials: "same-origin"` and never build an `Authorization` header.
- [ ] CI fails if the generated API types are out of date with the backend OpenAPI schema.
- [ ] Mode badge visible on every page; trading mode `live` rendered in a distinct
      high-contrast style.
- [ ] Every performance number shows its provenance (journal mode, live vs shadow, or backtest
      run ID).
- [ ] P&L sign conveyed by text (+/−), not colour alone; all controls keyboard reachable.
- [ ] Build check: `dist/` contains no `OANDA_` strings or token-like values; only `VITE_`
      variables are read in source; no inline scripts (SR-39).

**Risks.** "Strategy mode live" confused with "trading mode live" (distinct wording and badges);
expectations read as promises (show bands and provenance, never targets); WS flood re-rendering
charts (throttle server-side, batch client-side); accidental destructive clicks (confirm dialogs).

---

## Stage 7 — Security hardening, deployment, docs, end-to-end paper run

**Objective.** A clean clone becomes a running, hardened paper-trading system with one command,
proven by an observed end-to-end run, with honest user documentation for the road to practice
and live.

**In scope.** Fixes from security reviews; container images; docker compose; CI extensions;
runbook, broker availability check and README; E2E paper run with drills.
**Out of scope.** Enabling `live` trading (the user's decision, on their machine); cloud hosting.

**Deliverables.** Final `backend/Dockerfile` (slim, non-root, single worker, healthcheck),
`frontend/Dockerfile` (multi-stage build → nginx), `frontend/nginx.conf` (SPA, `/api` and `/ws`
proxy, security headers, `X-Forwarded-For $remote_addr`), final `docker-compose.yml` (backend not
published, nginx on 127.0.0.1, `fxbot-data` volume, hardening options — SR-24, SR-51), final
`backend/.env.example`, CI image-build + compose-smoke job, `docs/RUNBOOK.md` (start/stop,
backups, kill switch incl. out-of-band path and flattening from the MT5 terminal, MT5 terminal
and bridge health, incident steps, rollout phases paper → practice →
small live with the exit criteria of 00 §4.4, go-live checklist), **`docs/BROKER_AVAILABILITY.md`**
(user-facing check from R01 §3: entity and regulator, API or algorithmic-trading access for that
entity, leverage and negative balance protection, local law; which adapter to use — OANDA,
MT5 (stage 1b, `docs/MT5_SETUP.md`) or the optional cTrader adapter),
updated `README.md` (risk warning, honest expectations from 00 §4) and `docs/SECURITY.md`
(security), final `docs/STATUS.md`.

**Acceptance criteria.**

- [ ] All security-review findings from stages 1, 5, 6 closed or explicitly accepted in
      `docs/SECURITY.md`.
- [ ] From a clean clone: `cp backend/.env.example backend/.env`, set the dashboard password hash,
      `docker compose up -d --build` → dashboard on `http://127.0.0.1:8080`, login works, mode
      `paper`, synthetic feed running.
- [ ] CI compose-smoke job: images build, stack starts, `GET /api/health` via nginx returns 200.
- [ ] Containers run as non-root with read-only root FS where possible; the backend port is not
      published; nginx publishes on 127.0.0.1 only; nginx sends the SR-32 headers.
- [ ] E2E paper soak ≥ 24 h real time (synthetic feed): zero unhandled exceptions, zero
      unresolved reconciliation discrepancies, every trade had a stop.
- [ ] Accelerated E2E run: ≥ 1 simulated year of synthetic data through `TradingEngine` with
      `SimClock` and the API, ≥ 50 trades; journal P&L equals paper balance change exactly;
      replaying the same bars through the backtester reproduces every trade (00 §4.4 paper exit
      criterion).
- [ ] Restart drill: `docker compose restart backend` mid-run → state recovered, no duplicate
      orders, positions reconciled.
- [ ] Kill-switch drill: engage from the UI → flat within 5 s, no new orders until release; CLI
      and `docker compose stop backend` paths documented and tried once.
- [ ] Fault-injection drills: stale feed, candle-poll failure, broker 5xx on submit, drawdown
      ladder steps — each pauses or de-risks as specified and recovers.
- [ ] Backup/restore of the SQLite volume documented and tested once (SR-54).
- [ ] `README.md` quick start and `BROKER_AVAILABILITY.md` verified by someone who did not write them.

**Risks.** Long-run issues (memory growth, log volume, DB growth) only show in the soak; nginx WS
proxy misconfiguration; OANDA practice soak and the ≥ 3-month practice phase can only run on the
user's machine.

---

## Stage 8 — cTrader Open API adapter (optional)

**Status.** Optional since the user trades through MT5 (stage 1b, ADR 0007). Build it only if a
user needs a cTrader broker.

**Objective.** Offer a further regulated alternative behind the same `Broker` protocol, without
touching strategy, risk or learning code.

**In scope.** cTrader Open API adapter over **JSON on WebSocket (port 5036)**, OAuth2 account
authorization, symbol mapping, historical trendbars for candles, spot subscription for the price
monitor, execution events for fills and reconciliation, capability flags, contract-suite
compliance, host pinning and the live interlock for cTrader accounts.
**Out of scope.** Protobuf transport (port 5035); Interactive Brokers; multi-broker routing in
one process.

**Deliverables.** `brokers/ctrader/` (`client.py` asyncio WebSocket JSON client with heartbeats,
reconnect and `retryAfter` handling; `auth.py` OAuth2 token storage and refresh with `SecretStr`;
`adapter.py` `CTraderBroker`; `feed.py` `CTraderFeed`; `symbols.py`), `brokers/hosts.py` entries
for `demo.ctraderapi.com` / `live.ctraderapi.com`, `FXBOT_BROKER=ctrader`,
cTrader credential settings, `tests/fixtures/ctrader/*.json`, `websockets` dependency with an
SR-50 justification, docs update (`BROKER_AVAILABILITY.md`, RUNBOOK).

**Acceptance criteria.**

- [ ] `tests/brokers/test_broker_contract.py` passes unchanged for `CTraderBroker` against a fake
      WebSocket server fed with fixtures.
- [ ] `tests/brokers/ctrader/test_protocol.py`: prices and relative SL/TP in 1/100000 of a price
      unit, volume in 0.01 units, absolute SL/TP never sent for MARKET orders; `clientOrderId`
      ≤ 50 chars and `label` ≤ 100 carry the `afx-` idempotency key; rate limits 50 req/s and
      5 req/s historical respected; `BLOCKED_PAYLOAD_TYPE` honours `retryAfter` (R01 §2).
- [ ] `tests/brokers/ctrader/test_auth.py`: tokens refreshed before expiry; tokens never logged,
      returned or stored in the DB; refresh failure pauses entries.
- [ ] `tests/brokers/ctrader/test_candles.py`: trendbars converted to complete `Candle`s; if the
      API provides only one price side, the missing side is derived with the R06 §2 spread
      model and the dataset is marked accordingly.
- [ ] `tests/brokers/test_factory.py`: `practice` → demo host, `live` → live host; the account-
      bound live confirmation applies to the cTrader account ID; no free-form hosts (SR-10, SR-11).
- [ ] Capability flags reflect the account (hedging vs netting, volume step, minimum volume) and
      stage 3 caps adapt (`fifo_required`, `units_step` rounding).
- [ ] Manual (user machine): demo account session with zero unresolved reconciliation
      discrepancies and every trade protected by a stop.

**Risks.** OAuth app registration and token lifecycle (refresh failures); 1,000-unit volume
steps at many brokers make small-account sizing coarse (R01 §2); per-broker symbol names and
costs; candle price-side differences vs OANDA BA data affecting parity; no recorded fixtures yet.
