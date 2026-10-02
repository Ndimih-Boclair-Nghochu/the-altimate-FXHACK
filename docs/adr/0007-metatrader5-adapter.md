# ADR 0007 — MetaTrader 5 adapter (stage 1b)

- Status: Accepted
- Date: 2026-10-02
- Stage: 1b (between stages 1 and 2)
- Related: ADR 0001 (broker interface), ADR 0004 (interlock), `docs/research/01-broker-platforms.md`,
  `docs/research/08-metatrader5.md` (in progress; this ADR is amended if it changes anything)

## Context

- The user lives in **Cameroon** and will trade through **MetaTrader 5**.
- OANDA's v20 REST API is reportedly not offered to OANDA Global Markets or OANDA TMS accounts.
  Global Markets is the entity that usually serves countries outside OANDA's main regulated
  regions, and some African countries are not onboarded at all (R01 §3). OANDA can stay useful
  for development data and practice where available, but not as the user's live broker.
- MT5 is the most widely offered retail platform, including at regulated brokers that accept
  African residents (R01 §1). cTrader availability for the user is unconfirmed; Interactive
  Brokers lists Cameroon but is costly for small accounts (USD 2 minimum commission, daily
  gateway re-authentication).
- The official `MetaTrader5` Python package talks over IPC to a running MT5 terminal and ships
  **Windows-only** wheels (R01 §1). Our stack runs on Linux/Docker, and tests must never touch
  the network or the real terminal (brief principle 4).

## Decision

- Add a **MetaTrader 5 adapter** (`brokers/mt5/`) as **stage 1b**, implementing the same
  `Broker` / `MarketDataFeed` protocols and passing the same parametrized contract suite.
- Two transports behind one adapter:
  - `direct`: the `MetaTrader5` package in-process, when the backend runs on Windows;
  - `bridge`: an optional, minimal, **authenticated local bridge** (`fxbot mt5-bridge`) that runs
    next to the terminal on Windows (or Wine) and exposes only an allowlist of operations the
    adapter needs. It binds to loopback or a private tunnel interface, never a public one.
- The adapter owns all MT5 specifics: symbol mapping; lots ↔ units with volume step, minimum
  and maximum; ask derived from bid + spread; broker server time → UTC; idempotency via magic
  number + comment lookup; filling-mode selection; stops-level validation; netting/hedging as
  capabilities; client-managed trailing stops (MT5 trailing stops run in the terminal, not on
  the server); a single worker thread for every MT5 call.
- **Modes and interlock.** `practice` = OANDA practice **or** MT5 demo; `live` = OANDA live
  **or** MT5 real. MT5 has no host to pin, so the adapter verifies the connected account at
  start-up and after every reconnect: the login equals the configured login, and the account
  trade mode is demo for `practice` and real for `live`. `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` must
  equal the MT5 login in `live`. Everything else in ADR 0004 applies unchanged (env flag,
  `live_startup` pause, live phase-1 risk, kill switch).
- Tests use a **faithful fake `MetaTrader5` module**; acceptance includes a manual session on the
  user's MT5 demo account. Setup is documented for a Windows PC and a Windows VPS
  (`docs/MT5_SETUP.md`).
- The cTrader adapter (stage 8) becomes optional.

## Consequences

- **Windows dependency.** A Windows machine or VPS must run the MT5 terminal continuously,
  logged in, with algorithmic trading enabled and the clock synchronized. A terminal that is
  closed, logged out or disconnected pauses entries; open positions keep their broker-side stops.
- **Bridge security.** The bridge is a new trust boundary that can place orders. It must be
  authenticated, replay-protected, allowlisted, size- and rate-limited, audited, refuse any login
  other than the configured one, and never be exposed publicly. It gets its own security review
  and threat-model entry in `docs/SECURITY.md`.
- **Fidelity limits.** MT5 bars are bid-based with a spread value, so ask prices and costs are
  approximate; broker server time and D1 alignment vary by broker, so H4/D1 decision bars are
  resampled to 17:00 New York; brokers may rewrite order comments, which weakens comment-based
  idempotency (deal-history search by magic number compensates).
- **Sizing granularity.** Many MT5 brokers trade in 0.01-lot steps (1,000 units), so small
  accounts at 0.25–0.5% risk will skip some trades rather than round risk up.
- **Testing gap.** A fake module can drift from real terminal behaviour; the manual demo
  acceptance and recorded behaviours from the research report reduce, not remove, that risk.
- New optional, Windows-only dependency `MetaTrader5` (extra `fxbot[mt5]`), justified per SR-50.
- Paper mode and all strategy, risk and learning code are unaffected.

## Alternatives considered

- **MetaApi (cloud MT4/MT5 API).** Linux-native REST/WebSocket and no Windows host to manage,
  but a paid third-party service that holds the trading-account credentials and sits in the
  order path; adds cost, custody and availability risk outside our control. Rejected for now.
- **cTrader Open API.** Clean JSON over WebSocket and Linux-native, but depends on a cTrader
  broker that accepts the user; kept as the optional stage 8.
- **Wine-only (MT5 terminal under Wine, e.g. `mt5linux`).** Avoids Windows, but is unsupported
  by MetaQuotes and the broker, fragile across terminal updates, and `mt5linux` exposes a
  general-purpose RPyC server (remote Python execution) instead of an allowlisted API. Wine may
  still host the terminal behind our bridge, at the user's risk.
- **MQL5 Expert Advisor talking to the backend.** Runs inside the terminal without Python, but
  moves logic into a second language and makes testing and parity harder.
- **Interactive Brokers.** Serves Cameroon, but small-account costs and the gateway
  re-authentication model are poor fits (R01 §2).
