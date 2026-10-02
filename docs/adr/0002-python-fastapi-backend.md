# ADR 0002 — Python + FastAPI backend in a single async process

- Status: Accepted
- Date: 2026-10-02
- Stage: 0

## Context

The backend combines numerical work (indicators, backtests, scikit-learn models), long-lived
network I/O (price and transaction streams, REST calls), a typed HTTP/WebSocket API and a
database journal. It must be strictly typed, testable without the network, and simple to run on
one machine.

## Decision

- Python 3.11+ managed with uv; FastAPI + Pydantic v2 + pydantic-settings; SQLAlchemy 2 async
  with SQLite by default (Postgres via `FXBOT_DATABASE_URL`); httpx; numpy, pandas, scikit-learn;
  structlog. Quality: ruff (lint + format), mypy strict, pytest + pytest-asyncio + respx.
- The trading engine and the API run in **one process on one asyncio event loop**, started from
  the FastAPI lifespan, with **one uvicorn worker** (the `fxbot` CLI runs exactly one). An
  instance lock prevents a second engine on the same account.
- CPU-bound jobs (training, backtests, walk-forward) run in a process pool so the loop stays
  responsive.

## Consequences

- One deployable unit, no message broker, no inter-process protocol; the in-process event bus
  feeds the WebSocket directly.
- Horizontal scaling of the API is not possible without splitting the engine out. Acceptable for
  a single-operator system; the event bus + DB boundary keeps a later split feasible.
- Blocking calls on the loop are bugs; async DB/HTTP drivers and explicit timeouts are mandatory.
- SQLite needs WAL mode and a single writer process, which the single-worker rule guarantees.
- The pandas/scikit-learn ecosystem is available for research-to-production without porting.

## Alternatives considered

- **Node.js/TypeScript backend** — shared language with the frontend, but weak numerical/ML
  ecosystem.
- **Go or Rust engine** — faster and more robust concurrency, but ML and research tooling would
  live in a second language.
- **Django / Flask** — mature, but sync-first; streaming and WebSockets are more awkward.
- **Separate engine and API processes from day one** — cleaner isolation, but adds IPC, deployment
  and consistency work before it is needed. Revisit if the API must scale or be restarted
  independently.
