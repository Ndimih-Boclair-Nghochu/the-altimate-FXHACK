# fxbot: Altimate FX backend

Python service that runs the Altimate FX trading system: broker adapters, market data,
strategies, risk management, adaptive learning and the REST/WebSocket API used by the
dashboard. See [`docs/PROJECT_BRIEF.md`](../docs/PROJECT_BRIEF.md) for goals and principles.

> **Status:** Stage 1. Broker connectivity (OANDA v20 and a local paper broker) and the market
> data layer are in place. There is no strategy or trading engine yet, and the API only exposes
> `GET /api/health`.

## Requirements

- Python 3.11+ on Linux, macOS or Windows
- [uv](https://docs.astral.sh/uv/) 0.8+

## Install

```bash
cd backend
uv sync            # creates .venv with runtime + dev dependencies from uv.lock
```

## Configure

All configuration comes from environment variables, optionally via a `.env` file in the
working directory. Real environment variables win over `.env`.

```bash
cp .env.example .env
```

Every variable is documented in [`.env.example`](.env.example). The important ones:

| Variable | Default | Notes |
|---|---|---|
| `FXBOT_TRADING_MODE` | `paper` | `paper` (simulated, no account), `practice` (OANDA demo), `live` (real money) |
| `ALLOW_LIVE_TRADING` | `false` | No prefix on purpose. Required for `live` |
| `FXBOT_LIVE_TRADING_CONFIRMED` | `false` | Second confirmation, also required for `live` |
| `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` | unset | Must equal `FXBOT_OANDA_ACCOUNT_ID` for `live` |
| `FXBOT_OANDA_ACCOUNT_ID`, `FXBOT_OANDA_API_TOKEN` | unset | Required for `practice` and `live` |
| `FXBOT_DATA_FEED` | `synthetic` | Paper mode prices: `synthetic`, `replay` (candle store) or `oanda` (read-only) |
| `FXBOT_DATA_DIR` | `data` | SQLite database, validation datasets; git-ignored |
| `FXBOT_DATABASE_URL` | empty | Empty means SQLite at `<FXBOT_DATA_DIR>/fxbot.db`; passwords in the URL are refused |
| `FXBOT_API_HOST` / `FXBOT_API_PORT` | `127.0.0.1` / `8000` | |
| `FXBOT_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated or JSON array |
| `FXBOT_LOG_LEVEL` / `FXBOT_LOG_JSON` | `INFO` / `false` | JSON logs for production |

The process refuses to start if the mode's requirements are not met. `live` needs
`ALLOW_LIVE_TRADING=true`, `FXBOT_LIVE_TRADING_CONFIRMED=true`, both OANDA credentials and
`FXBOT_LIVE_CONFIRM_ACCOUNT_ID` equal to the account id. The broker factory checks all of this
again before it builds a live client. OANDA hosts are fixed by mode in
`src/fxbot/brokers/hosts.py`; no setting accepts a broker URL.

Secrets are typed `SecretStr`. They never appear in `repr`, logs or API responses, and the
log pipeline also masks anything that looks like an OANDA token, account id, bearer token,
URL password or `key=value` credential.

## Run

```bash
uv run fxbot                 # or: uv run python -m fxbot
curl http://127.0.0.1:8000/api/health
# {"status":"ok","version":"0.1.0","mode":"paper"}
```

Interactive API docs: <http://127.0.0.1:8000/api/docs>.

For auto-reload during development (this uses uvicorn's default logging instead of fxbot's):

```bash
uv run uvicorn fxbot.api.app:create_app --factory --reload
```

## Market data

```bash
# OANDA history (needs credentials; practice host unless the mode is live). Resumable:
# re-running continues after the last stored candle. Coarser bars are built from H1.
uv run fxbot data fetch --instrument EUR_USD --granularity H1 --from 2020-01-01

# Pinned public validation datasets (QuantConnect LEAN OANDA bid/ask H1, ejtraderLabs MT5
# exports), SHA-256 verified, into <FXBOT_DATA_DIR>/validation/. --load also stores them.
uv run fxbot data fetch-validation --list
uv run fxbot data fetch-validation --load
```

- Candles carry **bid and ask** OHLC (mid is derived) and record how the ask was obtained
  (`quoted`, `bar_spread`, `model_spread`, `synthetic`). Each set of candles belongs to a
  dataset with provenance (source, price side, smoothing, time zone of origin, SHA-256, licence
  note); datasets never overwrite each other.
- H2/H4/D/W bars are always built from H1 with the 17:00 New York alignment, for every source.
- Validation data is untrusted input: rows are validated and a file with more than 0.1% bad
  rows is refused. Never commit these files; their licences are unclear.
- CI and paper mode default to the seeded synthetic generator (regime switches, spreads that
  widen at the 17:00 New York rollover, weekend gaps). Do not judge strategies on it.

## Test and quality gates

These are the backend quality gates from the project brief; run them from `backend/` before committing.

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest            # includes coverage; fails below 85%
```

Tests never touch the network. Broker I/O is mocked with `respx`.

## Docker

```bash
docker build -t fxbot-backend backend/
docker run --rm -p 127.0.0.1:8000:8000 --env-file backend/.env fxbot-backend
```

The image runs as an unprivileged user, binds `0.0.0.0` inside the container only (via
`FXBOT_API_HOST`), logs JSON, and keeps the SQLite database in the `/app/data` volume.
To build behind a registry mirror, override the uv image with
`--build-arg UV_IMAGE=<mirror>/astral-sh/uv:0.8`.

## Layout

```
src/fxbot/
  config.py      Settings (pydantic-settings), live interlock checks
  logging.py     structlog setup and secret redaction
  cli.py         `fxbot` entry point: serve, data fetch, data fetch-validation
  domain/        models (Decimal, UTC), enums, errors, clock, market calendar, server time
  brokers/       Broker / MarketDataFeed protocols, capabilities, hosts, factory, paper broker
    oanda/       v20 REST client, adapter, streams, feed, wire format
  data/          candle store, downloader, validation datasets, resampling, spreads,
                 synthetic and replay feeds
  persistence/   SQLAlchemy engine, models (instruments, datasets, candles), repositories
  api/           FastAPI app factory, dependencies, routers
tests/           mirrors src/; fixtures/oanda/ holds v20 payloads with fake ids only
```
