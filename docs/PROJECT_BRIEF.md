# Altimate FX — Project Brief

This is the shared brief every contributor (human or agent) works from. If another doc
disagrees with this one, this one wins until it is updated.

## Goal

An algorithmic forex trading system that:

1. Connects to a real broker through a broker-agnostic interface (with capability flags).
   The primary adapter is **OANDA v20** (REST + streaming, free practice accounts). OANDA's
   API is not offered in every country or OANDA division, so a **cTrader Open API** adapter
   is planned next (stage 8). A built-in **paper broker** simulates fills locally so the
   whole system runs without any account.
2. Runs a **small ensemble of strategies**, gated by **market-regime detection**. Each
   strategy has a mode: `disabled`, `shadow` (signals logged and labelled, no orders) or
   `live`. Per the research (`docs/research/03-strategies.md`), only the H4 trend breakout
   defaults to `live`; mean reversion and session breakout start in `shadow` until they pass
   the promotion gates in `docs/research/06-backtesting-pitfalls.md`.
3. Enforces **strict risk management** on every order: volatility-based position sizing,
   ATR stops, daily/weekly loss limits, drawdown circuit breaker, currency-exposure limits,
   spread/session filters and a manual kill switch.
4. **Learns from its own history**: every signal (executed, filtered, shadow, historical) is
   labelled from market data; a meta-labeling model can only shrink or skip trades; a
   clamped bandit allocator shifts weight between strategies per regime from executed
   trades; drift detection and champion/challenger promotion guard against overfitting.
5. Is operated from a **clean, modern web dashboard** (live equity, positions, trades,
   strategy and model health, risk controls, backtests, settings).

## Non-negotiable principles

1. **Safety first.** The default mode is `paper`. Next is `practice` (OANDA demo). `live`
   requires `ALLOW_LIVE_TRADING=true` in the environment *and* an explicit confirmation in
   config. `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` must equal the configured live account id, and a
   live session starts with new entries paused until the operator resumes them. The kill
   switch flattens positions and halts new orders.
2. **Honesty.** No guaranteed profits, ever. Every performance number comes from a
   reproducible backtest or the trade journal. Never fabricate results.
3. **No lookahead bias, live/backtest parity.** Signals use only complete bars. Decision
   bars come from the broker's candles endpoint with bid and ask prices, never from
   aggregated stream ticks. The backtester runs the same strategy, risk and learning code
   as live and records how many configurations were tried.
4. **Testable by design.** Broker I/O sits behind interfaces. Tests never touch the network.
5. **Secrets stay server-side.** Loaded from env only, typed as `SecretStr`, never logged,
   never returned by the API, never sent to the frontend.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, uv, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 (async) + SQLite (Postgres-ready via `FXBOT_DATABASE_URL`), Alembic migrations (from stage 5), httpx, numpy, pandas, scikit-learn, river (drift detection), structlog |
| Backend quality | pytest, pytest-asyncio, respx, ruff (lint + format), mypy |
| Frontend | React + TypeScript (strict) + Vite + Tailwind CSS + TanStack Query + Zustand + React Router + lightweight-charts + lucide-react |
| Frontend quality | ESLint, Prettier, Vitest + Testing Library, API types generated from the backend OpenAPI schema (`openapi-typescript`) |
| Infra | Docker Compose, GitHub Actions CI |

## Repository layout

```
backend/
  pyproject.toml
  src/fxbot/
    config.py          settings (pydantic-settings)
    logging.py         structlog setup
    domain/            core models: Instrument, Candle, Price, Side, OrderRequest, Fill, Trade, Position, AccountSummary
    brokers/           base.py (Broker protocol), oanda/ (REST client, adapter, streaming), paper.py
    data/              candle store, historical downloader, synthetic data generator
    indicators/        vectorized indicators (numpy/pandas)
    regime/            market-regime classifier
    strategies/        Strategy protocol + trend / mean-reversion / breakout
    risk/              sizing, stops, limits, exposure, kill switch
    learning/          features, labeling, meta-model, bandit allocator, drift, model registry
    backtest/          event-driven backtester, metrics, walk-forward
    engine/            decision pipeline + order manager (stage 2), live orchestrator, reconciliation (stage 5)
    persistence/       SQLAlchemy models + repositories
    api/               FastAPI app, routers, WebSocket, auth
  tests/               mirrors src layout
frontend/              Vite React app
docs/
  PROJECT_BRIEF.md     this file
  ROADMAP.md           stages, acceptance criteria (PM)
  ARCHITECTURE.md      components, data flow, interfaces (PM)
  STATUS.md            stage tracker (PM)
  SECURITY.md          threat model + requirements (Security)
  RUNBOOK.md           operating guide (stage 7)
  research/            research reports (Research)
  adr/                 architecture decision records
.github/workflows/ci.yml
docker-compose.yml
```

## Stages

| # | Stage | Main owner |
|---|---|---|
| 0 | Foundation: research, roadmap, architecture, threat model, scaffolding, CI | all |
| 1 | Broker connectivity & market data (OANDA v20, paper broker, candle store) | backend |
| 2 | Indicators, regime detection, strategies, backtester, shared decision pipeline | backend |
| 3 | Risk management engine | backend |
| 4 | Adaptive learning system | backend |
| 5 | Live trading engine + REST/WebSocket API + auth | backend |
| 6 | Dashboard UI | frontend |
| 7 | Security hardening, deployment, docs, end-to-end paper run | security + all |
| 8 | cTrader Open API adapter (second broker) | backend |

Security reviews the work at the end of stages 1, 5, 6 and 7.
Each stage is built, tested (lint, types, tests, build all green), committed and pushed
before the next one starts.

## Quality gates (must pass before a stage is committed)

Backend (from `backend/`):

```
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Frontend (from `frontend/`):

```
npm ci
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

## Environment constraints for the build environment

- PyPI and npm are reachable. `raw.githubusercontent.com` is reachable.
- Broker APIs (`*.oanda.com`) and market-data sites (Yahoo, Dukascopy) are **blocked**, so
  broker integration is tested against recorded/mocked responses, and backtests in CI use
  synthetic data. Pinned public validation datasets on GitHub (`docs/research/07-data-sources.md`)
  are fetched on demand into the git-ignored `data/` folder for local validation.
- Default parameters for strategies, risk and learning come from
  `docs/research/00-summary.md` §2. Change them there (with reasons), not silently in code.
