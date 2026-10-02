# ADR 0001 — OANDA v20 as primary broker, behind a broker-agnostic interface

- Status: Accepted
- Date: 2026-10-02
- Stage: 0 (implemented in stage 1)

## Context

The system must trade real FX through a broker while staying testable offline. Requirements:
a free demo account, a documented HTTP API with price streaming, programmatic order placement
with attached stops, transaction history for reconciliation, and no desktop terminal or gateway
process. The build environment blocks `*.oanda.com`, so no test can rely on reaching the broker.

## Decision

- Define `Broker` and `MarketDataFeed` protocols in `fxbot/brokers/base.py` (ARCHITECTURE §4).
  All engine, risk and backtest code depends only on these.
- Implement `OandaBroker` / `OandaFeed` in `fxbot/brokers/oanda/` over httpx: REST for account,
  instruments, candles, orders, trades and transactions; HTTP streaming for prices and
  transactions.
- Use OANDA features that make the system safer: `stopLossOnFill` on every market order,
  `clientExtensions.id` as the idempotency key (order lookup by client ID), `priceBound` as a
  slippage guard, transaction IDs for incremental reconciliation.
- Ship `PaperBroker` (`fxbot/brokers/paper.py`) implementing the same protocol, used for paper
  mode and backtests.
- Practice vs live host is chosen by mode in `brokers/factory.py`, never by free-form URL.

## Consequences

- Broker tests run against `respx` fixtures (`tests/fixtures/oanda/`) and a shared contract suite
  run against both brokers. Fixtures can drift from the real API; a manual practice smoke test
  on the user's machine is part of stages 1 and 5.
- OANDA specifics (signed units, per-instrument price/units precision, FIFO and no-hedging rules
  on some account types) stay inside the adapter. To stay FIFO-safe on every account type, risk
  allows one open trade per instrument (stage 3).
- Account availability and leverage vary by jurisdiction; the user is responsible for opening
  an account.
- Adding another broker means one new adapter plus passing the contract suite.

## Alternatives considered

- **Interactive Brokers API** — broad market access, but needs a running TWS/IB Gateway process
  and a more complex session model; heavier to test and deploy.
- **MetaTrader 5 (Python package)** — popular with retail brokers, but the terminal and package
  are Windows-bound; poor fit for a Linux container.
- **cTrader Open API** — capable, but OAuth app registration and a protobuf/socket protocol add
  integration cost for little gain at this stage.
- **FIX via a prime/retail FIX gateway** — standard but requires a commercial relationship and
  session infrastructure.
- **Paper-only** — rejected: the goal includes real broker connectivity; paper remains the default.
