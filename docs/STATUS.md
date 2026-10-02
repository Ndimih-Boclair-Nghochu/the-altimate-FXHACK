# Altimate FX — Status

Stage tracker for `docs/ROADMAP.md`. Update the row (status, PR/commit, notes) when a stage
changes state. Status values: `not started`, `in progress`, `in review`, `done`, `blocked`.

## Stages

| # | Stage | Status | Owner | PR / commit | Notes |
|---|---|---|---|---|---|
| 0 | Foundation | in progress | all (lead integrates) | — | See checklist below |
| 1 | Broker connectivity & market data | not started | backend | — | Security review at end |
| 2 | Indicators, regime, strategies, backtester | not started | backend | — | Includes shared `DecisionPipeline` + basic `OrderManager` |
| 3 | Risk management engine | not started | backend | — | |
| 4 | Adaptive learning | not started | backend | — | |
| 5 | Live engine + REST/WS API + auth | not started | backend | — | Security review at end |
| 6 | Dashboard UI | not started | frontend | — | Security review at end |
| 7 | Hardening, deployment, docs, E2E paper run | not started | security + all | — | Final security review |

### Stage 0 checklist

| Item | Owner | Status |
|---|---|---|
| Research reports (`docs/research/`) | research | in progress |
| `ROADMAP.md`, `ARCHITECTURE.md`, `STATUS.md`, ADRs 0001–0005 | PM | drafted, awaiting lead review |
| `SECURITY.md` threat model | security | in progress |
| Backend scaffold + gates green | backend | in progress |
| Frontend scaffold + gates green | frontend | in progress |
| CI workflow green on PR | lead | not started |
| `README.md` replaced, `.env.example`, `.gitignore` | lead | not started |

## Decisions log

Newest first. Significant or hard-to-reverse decisions also get an ADR in `docs/adr/`.

| Date | Decision | Ref |
|---|---|---|
| 2026-10-02 | Schema: `create_all` until stage 5, then Alembic migrations | lead |
| 2026-10-02 | Frontend API types generated from the backend OpenAPI schema with `openapi-typescript` | lead |
| 2026-10-02 | OANDA v20 primary broker behind `Broker`/`MarketDataFeed` protocols; `PaperBroker` default | ADR 0001 |
| 2026-10-02 | Python/FastAPI backend; engine and API in one asyncio process, one uvicorn worker, instance lock | ADR 0002 |
| 2026-10-02 | Env vars use the `FXBOT_` prefix except `ALLOW_LIVE_TRADING` (brief's `DATABASE_URL` is `FXBOT_DATABASE_URL`) | `backend/src/fxbot/config.py` |
| 2026-10-02 | React + Vite SPA served by nginx, same-origin `/api` and `/ws` | ADR 0003 |
| 2026-10-02 | Live interlock: `ALLOW_LIVE_TRADING=true` + `FXBOT_LIVE_TRADING_CONFIRMED=true` + credentials, checked in config (done), broker factory and engine. Accepted: `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` must match the live account id; live starts with entries paused | ADR 0004 |
| 2026-10-02 | Learning = meta-labeling filter + per-regime Thompson-sampling allocator + drift + guarded champion/challenger; learning never raises risk above caps | ADR 0005 |
| 2026-10-02 | Shared `engine/pipeline.py` (`DecisionPipeline`) and basic `engine/order_manager.py` are built in stage 2 so backtests run the same code as live; stage 5 hardens them | ARCHITECTURE §3 |
| 2026-10-02 | Backtest fills: next-bar open ± half spread + slippage; stop wins when SL and TP touch in one bar; gaps fill at open | ARCHITECTURE §3.2 |
| 2026-10-02 | Trading day rolls at 17:00 America/New_York for loss limits and reporting | ARCHITECTURE §10 |
| 2026-10-02 | One open trade per instrument (FIFO-safe on all OANDA account types) | ROADMAP stage 3 |
| 2026-10-02 | Every signal is labeled (triple barrier), not only executed trades, to avoid selection bias | ADR 0005 |

### Open decisions

| Topic | Options | Needed by |
|---|---|---|
| Auth mechanism | Per `docs/SECURITY.md` (session cookie vs. bearer token, password hashing library) | Stage 5 |
| Default instruments, granularity, risk numbers | From `docs/research/`; ROADMAP placeholders until then | Stage 2–3 |
