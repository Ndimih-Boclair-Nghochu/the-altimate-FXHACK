# Altimate FX — Status

Stage tracker for `docs/ROADMAP.md`. Update the row (status, PR/commit, notes) when a stage
changes state. Status values: `not started`, `in progress`, `in review`, `done`, `blocked`.

## Stages

| # | Stage | Status | Owner | PR / commit | Notes |
|---|---|---|---|---|---|
| 0 | Foundation | done | all (lead integrates) | `fcb5246..af30c30` on `claude/sweet-goodall-5rr9ze` | Research 00–07, brief updated with research decisions, threat model, scaffolds, CI |
| 1 | Broker connectivity & market data | in progress | backend | — | BA candles from candles endpoint, capability flags, account-bound live confirmation, validation fetcher; security review at end |
| 1b | MetaTrader 5 adapter (+ optional local bridge) | not started | backend | — | User trades via MT5 from Cameroon (ADR 0007); fake `MetaTrader5` module; manual MT5 demo acceptance; `docs/MT5_SETUP.md`; security review at end; aligns with research 08 when it lands |
| 2 | Indicators, regime, strategies, backtester, shared decision pipeline | not started | backend | — | Strategy modes; R06 §8 checklist is the acceptance test |
| 3 | Risk management engine | not started | backend | — | Defaults from research 00 §2.2 |
| 4 | Adaptive learning | not started | backend | — | Label every signal; `river` for drift |
| 5 | Live engine + REST/WS API + auth | not started | backend | — | Alembic baseline; security review at end |
| 6 | Dashboard UI | not started | frontend | — | Generated API types; expected vs realized views; security review at end |
| 7 | Hardening, deployment, docs, E2E paper run | not started | security + all | — | Adds RUNBOOK and BROKER_AVAILABILITY docs; final security review |
| 8 | cTrader Open API adapter (optional) | not started | backend | — | Optional since MT5 is the user's broker (ADR 0007) |

## Decisions log

Newest first. Significant or hard-to-reverse decisions also get an ADR in `docs/adr/`.
Rows marked *superseded* are kept for history.

| Date | Decision | Ref |
|---|---|---|
| 2026-10-02 | Pause entries after 3 consecutive order errors (the stricter value; SR-16 to be aligned) | lead |
| 2026-10-02 | Holdouts: 12 months untouched for strategy promotion (R06 §4.5); 6 months for meta-model evaluation (R05 §8.1) | lead |
| 2026-10-02 | Keep `FXBOT_LIVE_TRADING_CONFIRMED` as an extra gate alongside `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` | lead |
| 2026-10-02 | Allocator outputs per-strategy multipliers clamped to [0.5, 1.5], always inside the hard risk caps (SR-20 to be aligned) | lead |
| 2026-10-02 | Backtester checks stops on the entry bar after a next-open fill (research 03's simulator skipped this) | lead |
| 2026-10-02 | User is in Cameroon and trades through MetaTrader 5: new stage 1b (MT5 adapter, `direct` and optional authenticated `bridge` transport); `practice` = OANDA practice or MT5 demo, `live` = OANDA live or MT5 real under the same interlock, with the live confirmation matching the MT5 login and the account trade mode checked on every connect; cTrader (stage 8) optional | ADR 0007 |
| 2026-10-02 | Universe EUR_USD, GBP_USD, USD_JPY, AUD_USD; CHF pairs excluded; no M15 trading, no stand-alone carry, no grid/martingale | research 00 §1.2, §2.1 |
| 2026-10-02 | Strategy modes `disabled` / `shadow` / `live`; only `trend_breakout_h4` live by default; `mean_reversion_h1`, `session_breakout_h1` in shadow; shadow → live needs R06 §6 gates + manual approval | ADR 0006 |
| 2026-10-02 | Regime = trend label (TREND/RANGE/NEUTRAL, UNDEFINED in warm-up) × vol bucket (LOW/NORMAL/HIGH/EXTREME), 2-bar hysteresis, no entries in EXTREME; replaces the single `Regime` enum | research 03 §5.1, ARCHITECTURE §4 |
| 2026-10-02 | Decision bars come from the OANDA candles endpoint (`price=BA`, complete only, polled at boundary + 2–5 s); the stream is for monitoring, spread, staleness and paper fills | research 00 §3.8, ARCHITECTURE §3.1 |
| 2026-10-02 | `Candle` stores bid and ask OHLC with dataset provenance; mid is derived | research 00 §3.9 |
| 2026-10-02 | `Broker` protocol carries capability flags (incl. `position_accounting` for MT5 netting); cTrader Open API adapter is stage 8 (optional); user-facing broker availability check in stage 7 | research 01 §4, ADR 0001 (amended) |
| 2026-10-02 | `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` implemented in config + factory in stage 1 (moved from stage 5) | SR-10, ADR 0004 (amended) |
| 2026-10-02 | Backtester: bid/ask fills, conservative same-bar handling, financing, shared risk engine, trial registry, PSR/DSR, PBO, Monte-Carlo drawdowns, cost/delay stress | research 06 §8, ROADMAP stage 2 |
| 2026-10-02 | Validation datasets: pinned LEAN OANDA bid/ask H1 and ejtraderLabs MT5 sets via `fxbot data fetch-validation`, SHA-256 verified, git-ignored; CI stays synthetic | research 07 §3 |
| 2026-10-02 | Risk defaults: 0.5% per trade (0.25% live phase 1), ≤ 1.0% after multipliers; open/currency/cluster 2/1/1%; drawdown ladder −5/−8/−12/−20%; filters per research 04 | research 00 §2.2, ROADMAP stage 3 |
| 2026-10-02 | Positions: max 4 (3 live phase 1), 1 per strategy × instrument, 2 per instrument, opposite directions blocked, 1 per instrument when `fifo_required` | research 04 §5.3 |
| 2026-10-02 | Learning: label every signal from market data; meta-model only shrinks or skips; discounted NIG Thompson allocator with cash arm clamped to [0.5, 1.5], learns from executed trades only; river drift detectors; R05 §8 promotion gates | ADR 0005 (amended) |
| 2026-10-02 | News blackout: manual config/CSV calendar first, fail-safe windows when missing; automatic source to be decided | ROADMAP stage 3 |
| 2026-10-02 | Reconciliation and resubmit follow R02 §9: adopt only `afx-` trades, never touch external ones, re-submit an UNKNOWN order only with the same client ID after a 10 s search | ARCHITECTURE §10 |
| 2026-10-02 | Schema: `create_all` until stage 5, then Alembic migrations | lead |
| 2026-10-02 | Frontend API types generated from the backend OpenAPI schema with `openapi-typescript` | lead |
| 2026-10-02 | Auth: argon2id operator password, opaque session cookie, CSRF Origin check, trusted hosts | SR-26 – SR-31 |
| 2026-10-02 | OANDA v20 primary broker behind `Broker`/`MarketDataFeed` protocols; `PaperBroker` default | ADR 0001 |
| 2026-10-02 | Python/FastAPI backend; engine and API in one asyncio process, one uvicorn worker, instance lock | ADR 0002 |
| 2026-10-02 | Env vars use the `FXBOT_` prefix except `ALLOW_LIVE_TRADING` | `backend/src/fxbot/config.py` |
| 2026-10-02 | React + Vite SPA served by nginx, same-origin `/api` and `/ws` | ADR 0003 |
| 2026-10-02 | Live interlock checked in config, broker factory and engine; live starts with entries paused (`live_startup`) | ADR 0004 |
| 2026-10-02 | Shared `engine/pipeline.py` (`DecisionPipeline`) and basic `engine/order_manager.py` are built in stage 2 so backtests run the same code as live; stage 5 hardens them | ARCHITECTURE §3 |
| 2026-10-02 | Trading day rolls at 17:00 America/New_York; week at Sunday 17:00 NY | ARCHITECTURE §10 |
| 2026-10-02 | *Superseded:* backtest fills at next-bar open ± half spread (now bid/ask sides per R06 §8) | — |
| 2026-10-02 | *Superseded:* one open trade per instrument (now research 04 §5.3 caps) | — |
| 2026-10-02 | *Superseded:* allocator weights summing to 1 (now multipliers clamped to [0.5, 1.5]) | — |

### Open decisions

| Topic | Options | Needed by |
|---|---|---|
| Automatic news calendar source | Built-in recurring schedule only vs. optional cached ForexFactory export (licence unclear, rate-limited, R04 §6.5) | Stage 3 (manual/CSV first) |
| cTrader candle price side | Verify whether trendbars give bid only; if so derive ask with the R06 §2 spread model | Stage 8 |
| MT5 bridge protocol and auth | HTTP + HMAC (timestamp, nonce) vs. mTLS; transport for topology 2 vs. 3 | Stage 1b (research 08, security) |
| MT5 server-time rule and bar spread semantics | Configured offset vs. detected; which spread value MT5 bars carry | Stage 1b (research 08) |
| Account-ID format check in `config.py` | Currently OANDA-only regex; must accept MT5 logins when `FXBOT_BROKER=mt5` | Stage 1b |
