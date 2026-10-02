# ADR 0005 — Adaptive learning via meta-labeling and per-regime bandits

- Status: Accepted (amended 2026-10-02 with the defaults of `docs/research/05-adaptive-learning.md`)
- Date: 2026-10-02
- Stage: 0 (implemented in stage 4)

## Context

Strategy edge in FX is small and regime-dependent, and outcomes are noisy: with a per-trade R
standard deviation of about 1.5, telling a +0.1R edge from zero needs roughly 600 trades
(R05 §1). The system should learn from its own history without becoming an overfitted black box
and without any path that increases risk beyond the risk engine's caps. Results must be
reproducible in backtests.

## Decision

Keep the primary strategies rule-based and interpretable. Put learning on top of them:

1. **Label every signal from market data.** Executed, filtered, shadow (ADR 0006) and
   historical backtest signals are all labelled by simulating the strategy's own exit policy on
   bid/ask bars (strategy-specific triple barrier, costs included, stop first on ambiguous bars).
   Labels do not depend on our fills, so filtering does not censor the training set — the main
   defence against feedback loops. Overlapping labels get average-uniqueness sample weights.
2. **Meta-labeling (shrink or skip only).** Champion = pass-through or logistic regression;
   challenger = HistGradientBoosting with conservative settings; calibrated; purged/embargoed
   5-fold CV and monthly walk-forward; ≤ 20 configurations per retrain, counted. Size rule
   `m_meta = clip((p̂ − p*) / 0.15, 0, 1)`, skip below 0.2, never above 1. No own-P&L features.
   Pass-through until ≥ 300 labelled events per strategy; day-1 bootstrap from historical
   backtest signals.
3. **Allocation.** Discounted Normal-Inverse-Gamma Thompson sampling (γ = 0.99, μ₀ = 0, κ₀ = 10,
   σ₀ = 1.5R) per strategy and regime cell `(trend, vol)` with hierarchical pooling and a cash
   arm; `m_strategy = clip(N_active × P_best, 0.5, 1.5)`, 1.0 below 20 observations. It learns
   only from executed closed trades, so it reflects real execution. Demotes a strategy to shadow
   if P(μ > 0) < 0.10 after ≥ 50 trades.
4. **Drift detection with honest limits.** river `PageHinkley` on per-trade R (warning, halve
   `m_strategy`), `ADWIN` on Brier error (retrain, pass-through meanwhile), PSI on features,
   `PageHinkley` on realized − modeled cost (immediate alert). P&L detectors are slow by nature
   (R05 §7.1); fast protection comes from the risk engine.
5. **Champion/challenger gates** (R05 §8.1): ≥ 3 months and ≥ 150 events in an unseen evaluation
   window; log-loss −1% with a block-bootstrap CI excluding 0; Brier not worse; calibration
   slope in [0.8, 1.2]; must beat the champion **and** pass-through economically; consistent
   across folds; no single dominant feature; PBO < 0.3 when ≥ 4 candidates; 14-day shadow scoring;
   14-day cooldown; automatic rollback. Every step is recorded in `model_versions`,
   `model_scores` and `risk_events`.

Hard rule: learning can only filter signals or move a strategy's multiplier within [0.5, 1.5];
the risk engine caps the final per-trade risk at 1.0% NAV and applies every limit after it.
Promoting a strategy to live or changing the feature set needs manual approval.

## Consequences

- Cold start is safe (pass-through, multipliers 1.0) and the system behaves like the plain
  ensemble until it has data.
- The labeler must reuse the strategies' exit policies and the paper-broker fill rules, or labels
  and realized trades diverge; persistent divergence is treated as a cost-model alert.
- Backtests report learning-on and learning-off side by side, whatever the result.
- Model artifacts are pickled scikit-learn objects written only by the trainer and loaded only
  after a SHA-256 check (SR-43).
- New dependency: `river` (drift detectors only). LightGBM stays optional.
- Labeling needs later bars, so it runs as a scheduled sweep, not at signal time.

## Alternatives considered

- **Learn only from closed live trades.** Far too slow (R05 §1) and biased towards the trades
  the filter already liked.
- **Direct price-direction prediction with ML** — low signal-to-noise, high overfitting risk,
  hard to explain.
- **Reinforcement-learning trading agent** — sample-inefficient, opaque, hard to constrain.
- **Online updates of the classifier after each trade** — chases noise, cannot be validated
  before acting, not reproducible.
- **Unclamped or undiscounted Thompson sampling** (e.g. river's `ThompsonSampling`) — swings
  allocations on noise and cannot follow regime change.
- **Static equal weights, no learning** — kept as the control arm in every comparison.
