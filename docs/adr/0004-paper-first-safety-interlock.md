# ADR 0004 — Paper-first modes and the live-trading interlock

- Status: Accepted
- Date: 2026-10-02
- Stage: 0 (implemented in stages 1, 3 and 5)
- Amended: 2026-10-02 — account-bound confirmation moved to stage 1 (SR-10)

## Context

A bug, a misconfiguration or a compromised dashboard must not be able to put real money at risk.
The brief requires `paper` by default, `practice` next, and `live` only with
`ALLOW_LIVE_TRADING=true` in the environment *and* an explicit confirmation in config, plus a
kill switch that flattens positions and halts new orders.

## Decision

- Three modes: `paper` (local `PaperBroker`, no account), `practice` (OANDA practice host or an
  MT5 demo account), `live` (OANDA live host or an MT5 real account). Default `paper`. Mode is
  read at start-up only; the API cannot change it.
- `live` requires `ALLOW_LIVE_TRADING=true` (env only, no prefix), OANDA credentials, and the
  explicit config confirmation `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` equal to the live account
  (`FXBOT_OANDA_ACCOUNT_ID`, or the MT5 login per ADR 0007), so a confirmation cannot silently
  carry over to a different account (SR-10). Implemented in
  `config.py` and `brokers/factory.py` in stage 1, re-checked by the engine in stage 5. The
  scaffold's bare `FXBOT_LIVE_TRADING_CONFIRMED` boolean is not sufficient on its own.
- The check runs three times: settings validation, `brokers/factory.py` (refuses to build a live
  client), and `TradingEngine.start()`.
- In `live`, the engine starts with entries paused (`live_startup`, stage 5, SR-12): it
  reconciles and observes but opens nothing until the operator resumes entries from the
  dashboard.
- `live` starts in **live phase 1**: 0.25% risk per trade and at most 3 positions (R04 §9).
  Raising them is a loosening change that needs `confirm` and is audited (SR-35).
- Broker hosts are selected by mode in one module (`brokers/hosts.py`), never by a free-form
  URL outside tests (SR-11). The same rules apply to the optional cTrader adapter (stage 8).
  MT5 has no host to pin: the adapter checks on every connect that the login is the configured
  one and that the account trade mode is demo for `practice` and real for `live` (ADR 0007).
- Every order carries a broker-side stop on fill. The kill switch sets a persisted pause reason,
  calls `close_all`, and retries until reconciliation confirms the account is flat. Release is
  manual and audited.
- The UI shows the mode on every page; `live` uses a distinct high-contrast badge.

## Consequences

- Going live is a deliberate, multi-step act on the host (env + config + restart + operator
  resume); it cannot be done from the browser.
- Tests must cover each refusal path (`tests/brokers/test_factory.py`,
  `tests/engine/test_interlock.py`) and kill-switch persistence across restarts.
- Strategy modes (ADR 0006) are separate from the trading mode; promoting a strategy to `live`
  never changes the trading mode.
- Slight friction for practice → live, which is intended.
- Restarting in `live` always requires an operator to resume entries.

## Alternatives considered

- **Single `LIVE=true` flag** — one mistaken env var away from real trading; rejected.
- **Live toggle in the dashboard** — a stolen session or XSS could enable live trading; rejected.
- **Separate live build/binary** — strong isolation but doubles build and test paths; the
  runtime interlock plus host pinning gives most of the benefit.
- **Flatten on every shutdown** — would realise losses on routine restarts; broker-side stops
  bound risk instead.
