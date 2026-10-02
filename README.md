# Altimate FX

An algorithmic forex trading system with a multi-strategy engine, risk management, a
model that learns from the bot's own closed trades, and a web dashboard.

> **Risk warning.** Trading leveraged FX carries a high risk of loss, and most retail
> accounts lose money. No trading system can guarantee profits, this one included.
> Altimate FX runs in **paper mode** by default. Run it on a practice (demo) account for a
> long time before you consider live trading. Live trading needs several explicit
> opt-ins (see [docs/SECURITY.md](docs/SECURITY.md)).

## What it does

- **Broker connectivity.** Connects through a broker-agnostic interface. The first adapter
  is **OANDA v20** (REST and streaming, with free practice accounts). A built-in paper
  broker simulates fills so the system runs without an account.
- **Strategies.** A small ensemble of trend-following, mean-reversion and breakout
  strategies, each switched on or off by a market-regime classifier.
- **Risk management.** Every order passes volatility-based position sizing, ATR stops,
  daily and weekly loss limits, a drawdown circuit breaker, currency-exposure limits,
  spread and session filters, and a manual kill switch.
- **Adaptive learning.** A meta-labeling model scores each new signal using the bot's own
  closed trades. A bandit allocator shifts weight between strategies per regime. Drift
  detection and champion/challenger promotion guard against overfitting.
- **Dashboard.** Equity, positions, trades, strategy and model health, risk controls,
  backtests and settings.

## Project status

The project is built in stages, and each stage is tested and pushed before the next one
starts. See [docs/STATUS.md](docs/STATUS.md) for the current stage and
[docs/ROADMAP.md](docs/ROADMAP.md) for the full plan.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | Python trading engine and API (FastAPI) |
| `frontend/` | React dashboard |
| `docs/` | Brief, roadmap, architecture, security, research reports, ADRs |

## Quick start (development)

Backend (Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
cp .env.example .env      # paper mode needs no credentials
uv sync
uv run pytest
uv run fxbot              # API on http://127.0.0.1:8000
```

Frontend (Node 22):

```bash
cd frontend
npm ci
npm run dev               # dashboard on http://localhost:5173
```

With Docker:

```bash
docker compose up --build # dashboard on http://127.0.0.1:8080
```

## Documentation

- [Project brief](docs/PROJECT_BRIEF.md)
- [Roadmap](docs/ROADMAP.md) and [status](docs/STATUS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security](docs/SECURITY.md)
- [Research reports](docs/research/)
