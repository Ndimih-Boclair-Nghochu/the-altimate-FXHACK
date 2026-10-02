# fxbot: Altimate FX backend

Python service that runs the Altimate FX trading system: broker adapters, market data,
strategies, risk management, adaptive learning and the REST/WebSocket API used by the
dashboard. See [`docs/PROJECT_BRIEF.md`](../docs/PROJECT_BRIEF.md) for goals and principles.

> **Status:** Stage 0 scaffold. The API only exposes `GET /api/health`; no trading logic yet.

## Requirements

- Python 3.11+
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
| `FXBOT_OANDA_ACCOUNT_ID`, `FXBOT_OANDA_API_TOKEN` | unset | Required for `practice` and `live` |
| `FXBOT_API_HOST` / `FXBOT_API_PORT` | `127.0.0.1` / `8000` | |
| `FXBOT_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated or JSON array |
| `FXBOT_LOG_LEVEL` / `FXBOT_LOG_JSON` | `INFO` / `false` | JSON logs for production |

The process refuses to start if the mode's requirements are not met. `live` needs
`ALLOW_LIVE_TRADING=true`, `FXBOT_LIVE_TRADING_CONFIRMED=true` and both OANDA credentials.

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
  config.py      Settings (pydantic-settings) and get_settings()
  logging.py     structlog setup and secret redaction
  cli.py         `fxbot` entry point (uvicorn)
  api/           FastAPI app factory, dependencies, routers
  domain/ brokers/ data/ indicators/ regime/ strategies/
  risk/ learning/ backtest/ engine/ persistence/    (filled in by later stages)
tests/           mirrors src/; shared fakes live in tests/fakes.py
```
