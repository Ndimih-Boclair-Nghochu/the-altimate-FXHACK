# ADR 0001 — OANDA v20 as primary broker, behind a broker-agnostic interface

- Status: Accepted
- Date: 2026-10-02
- Stage: 0 (implemented in stage 1)
- Amended: 2026-10-02 — capability flags, candles-endpoint decision bars, cTrader as stage 8
  (`docs/research/01-broker-platforms.md`, `02-oanda-v20-api-spec.md`)

## Context

The system must trade real FX through a broker while staying testable offline. Requirements:
a free demo account, a documented HTTP API with price streaming, programmatic order placement
with attached stops, transaction history for reconciliation, and no desktop terminal or gateway
process. The build environment blocks `*.oanda.com`, so no test can rely on reaching the broker.

## Decision

- Define `Broker` and `MarketDataFeed` protocols in `fxbot/brokers/base.py` (ARCHITECTURE §4),
  with **capability flags** (`supports_sl_on_fill`, `supports_trailing_stop`, `supports_hedging`,
  `fifo_required`, `units_step`, `min_units`, `max_orders_per_second`, candle price sides) so no
  OANDA concept leaks into engine, risk or backtest code.
- Implement `OandaBroker` / `OandaFeed` in `fxbot/brokers/oanda/` with our own thin httpx client
  (the official SDKs are unmaintained since 2018): REST for account, instruments, candles,
  orders, trades and transactions; HTTP streaming for prices and transactions.
- Decision bars come from the candles endpoint with `price=BA`, complete candles only. The
  pricing stream (at most 4 prices/s per instrument, last-in-window) is for monitoring, spread
  and staleness checks and paper fills, never for building bars.
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
  on some account types) stay inside the adapter and surface only as capability flags; with
  `fifo_required` the risk engine allows one open trade per instrument (stage 3).
- **Availability caveat:** OANDA's v20 REST API is reportedly not offered to OANDA Global Markets
  or OANDA TMS accounts, and some countries are not onboarded at all (R01 §3). Users may be able
  to develop on practice but not trade live. This applies to the current user (Cameroon), who
  trades through **MetaTrader 5** (stage 1b, ADR 0007). Stage 7 ships a user-facing broker
  availability check; an optional **cTrader Open API** adapter (stage 8) remains possible behind
  the same protocol and contract suite.
- Adding another broker means one new adapter plus passing the contract suite.

## Alternatives considered

- **Interactive Brokers API** — broad market access, but needs a running TWS/IB Gateway process
  with daily re-authentication, and a USD 2 minimum commission hurts small accounts; reconsider
  above roughly USD 25k (R01 §2).
- **MetaTrader 5 (Python package)** — the most widely offered retail platform, but the terminal
  and package are Windows-only. Not chosen as the primary adapter, but added as the user's live
  broker in stage 1b with an optional Windows-side bridge (ADR 0007).
- **cTrader Open API** — broker-neutral and Linux-friendly (JSON over WebSocket), but needs
  OAuth app registration and coarser volume steps at many brokers. Optional stage 8.
- **FIX via a prime/retail FIX gateway** — standard but requires a commercial relationship and
  session infrastructure.
- **FXCM** — `fxcmpy` was removed from PyPI and ForexConnect has no Linux wheels for
  Python ≥ 3.8; not viable.
- **Paper-only** — rejected: the goal includes real broker connectivity; paper remains the default.
