# ADR 0004 — Paper-first modes and the live-trading interlock

- Status: Accepted
- Date: 2026-10-02
- Stage: 0 (implemented in stages 1, 3 and 5)

## Context

A bug, a misconfiguration or a compromised dashboard must not be able to put real money at risk.
The brief requires `paper` by default, `practice` next, and `live` only with
`ALLOW_LIVE_TRADING=true` in the environment *and* an explicit confirmation in config, plus a
kill switch that flattens positions and halts new orders.

## Decision

- Three modes: `paper` (local `PaperBroker`, no account), `practice` (OANDA demo host), `live`
  (OANDA live host). Default `paper`. Mode is read at start-up only; the API cannot change it.
- `live` requires `ALLOW_LIVE_TRADING=true` (env only, no prefix),
  `FXBOT_LIVE_TRADING_CONFIRMED=true` and OANDA credentials (implemented in `fxbot/config.py`).
- *Accepted, implemented in stage 5:* also require `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` equal to
  `FXBOT_OANDA_ACCOUNT_ID`, so a confirmation cannot silently carry over to a different account.
- The check runs three times: settings validation, `brokers/factory.py` (refuses to build a live
  client), and `TradingEngine.start()`.
- *Accepted, implemented in stage 5:* in `live`, the engine starts with entries paused (`live_startup`): it
  reconciles and observes but opens nothing until the operator resumes entries from the
  dashboard.
- Broker hosts are selected by mode, never by a free-form URL outside tests.
- Every order carries a broker-side stop on fill. The kill switch sets a persisted pause reason,
  calls `close_all`, and retries until reconciliation confirms the account is flat. Release is
  manual and audited.
- The UI shows the mode on every page; `live` uses a distinct high-contrast badge.

## Consequences

- Going live is a deliberate, multi-step act on the host (env + config + restart + operator
  resume); it cannot be done from the browser.
- Tests must cover each refusal path (`tests/brokers/test_factory.py`,
  `tests/engine/test_interlock.py`) and kill-switch persistence across restarts.
- Slight friction for practice → live, which is intended.
- Restarting in `live` always requires an operator to resume entries.

## Alternatives considered

- **Single `LIVE=true` flag** — one mistaken env var away from real trading; rejected.
- **Live toggle in the dashboard** — a stolen session or XSS could enable live trading; rejected.
- **Separate live build/binary** — strong isolation but doubles build and test paths; the
  runtime interlock plus host pinning gives most of the benefit.
- **Flatten on every shutdown** — would realise losses on routine restarts; broker-side stops
  bound risk instead.
