# ADR 0006 — Strategy modes and shadow trading

- Status: Accepted
- Date: 2026-10-02
- Stage: 0 (implemented in stages 2, 4, 5 and 6)

## Context

The brief originally listed trend following, mean reversion and breakout as peers. The research
does not support enabling all three:

- Only slow trend following has decent published evidence in FX; intraday rules mostly do not
  survive costs (R03 §1).
- Our bid/ask sanity checks: H1 mean reversion lost on all five datasets after costs; the
  Asian-range → London breakout was the best-looking result but turned negative with +1 pip of
  cost and decayed over time (R03 §4). The best of 10 configurations had PSR 0.98 but DSR 0.47
  (R06 §4.2).
- Learning needs far more outcomes than one live strategy produces: proving a +0.1R edge takes
  roughly 600 trades (R05 §1).

We still want the weaker strategies to produce evidence, both for their own promotion decision
and for the learning system, without risking capital.

## Decision

- Every strategy has a **mode**: `disabled`, `shadow` or `live` (`StrategyMode`). It is
  independent of the process **trading mode** (`paper` / `practice` / `live`): a strategy in mode
  `live` places orders in whatever trading mode the process runs, including paper.
- Defaults (00 §1.2): `trend_breakout_h4` = `live`; `mean_reversion_h1` and
  `session_breakout_h1` = `shadow`.
- **Shadow semantics.** The strategy runs on every bar like a live one. Its signals go through
  features and meta-model scoring and a pre-trade-filter dry run (`RiskManager.pre_trade_filters`)
  that sets an `executable` flag (e.g. false inside the rollover blackout). The decision is
  journaled with outcome `SHADOW` and labelled later from market data by the same exit policy.
  No `ApprovedOrder` is created, no risk state changes, and the bandit allocator does not learn
  from shadow outcomes (they feed promotion evidence and the meta-model only).
- **Promotion shadow → live** requires the strategy gates in R06 §6 (≥ 200 OOS trades over
  ≥ 2 years and ≥ 3 pairs, PSR(0) ≥ 0.95, DSR ≥ 0.90 with the registry trial count, positive at
  1.5× costs and with +1-bar delay, PBO < 0.3 when parameters were selected, no year or pair
  > 50% of R, live-shadow drawdown inside the Monte-Carlo p95) **and** a manual approval in the
  dashboard with `confirm` and a reason, audited (SR-35). Passing gates never promotes
  automatically.
- **Demotion** to `shadow` or `disabled` is always allowed: manually, or automatically when the
  allocator's P(μ > 0) < 0.10 after ≥ 50 executed trades (R05 §6) or the Kelly lower bound is
  ≤ 0 after ≥ 100 trades (R04 §2.3). Automatic demotions raise an alert.
- Modes are stored in the `settings` table; every change emits `StrategyModeChanged` and a
  `risk_events` row. Backtests take a mode map from their config and may evaluate a shadow
  strategy "as live" for gate evaluation; such runs are counted in the trial registry.

## Consequences

- The learning system gets labelled outcomes from all strategies from day one, and shadow
  strategies build an honest out-of-sample record for their own promotion.
- Shadow results are never presented as trading performance; the UI keeps live and shadow apart
  and labels shadow as "no orders".
- "Live" now has two meanings. The UI and API always qualify it ("trading mode" vs "strategy
  mode") and use different badges.
- Extra load: shadow strategies run on every bar and their signals must be labelled and stored.
  Labeling runs as a scheduled sweep in the process pool.
- Gate evaluation depends on an accurate trial registry; forgetting to count runs inflates DSR.

## Alternatives considered

- **Enable all three strategies (brief v1).** Rejected: the evidence says two of them are likely
  to lose after costs.
- **Drop mean reversion and session breakout.** Simpler, but loses cheap evidence for learning
  and any chance of discovering a regime-specific edge.
- **A boolean `enabled` flag.** No way to collect outcomes from disabled strategies.
- **Paper-trade weaker strategies in a separate process or account.** Real fills in paper are
  simulated anyway; a second engine doubles operations and breaks the single-instance design
  (ADR 0002). Shadow labels from market data give the same information.
- **Automatic promotion when gates pass.** Rejected: promoting a strategy increases risk and is a
  structural change; a human must approve it (R05 §8.2).
