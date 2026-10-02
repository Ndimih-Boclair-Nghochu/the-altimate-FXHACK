# ADR 0005 — Adaptive learning via meta-labeling and per-regime bandits

- Status: Accepted
- Date: 2026-10-02
- Stage: 0 (implemented in stage 4)

## Context

Strategy edge in FX is small and regime-dependent, and the number of closed trades is small.
The system should learn from its own outcomes without turning into an overfitted black box and
without any path that increases risk beyond the risk engine's caps. Results must be reproducible
in backtests.

## Decision

Keep the primary strategies rule-based and interpretable. Put learning on top of them:

1. **Meta-labeling.** Every signal (taken or not) is labeled with the triple-barrier method
   (stop, target, time barrier, net of costs) once its horizon has passed. Labeling all signals,
   not only executed trades, avoids selection bias. A calibrated scikit-learn classifier scores
   new signals from causal features; below threshold the signal is filtered; above it the score
   may scale size within `[0, max_multiplier]`. Until a minimum sample count, the model is a
   pass-through.
2. **Bandit allocation.** Discounted Thompson sampling per (regime, strategy) on net R-multiple
   rewards produces strategy weights with a floor (keeps exploring) and a cap (limits
   concentration). Weights become risk multipliers, not new risk.
3. **Drift detection.** PSI on feature distributions, rolling calibration (Brier), and
   Page-Hinkley on per-strategy R. Alerts are journaled and trigger challenger training.
4. **Champion/challenger.** Challengers are trained with purged + embargoed walk-forward CV,
   then shadow-score live signals. Promotion requires: minimum training and shadow sample sizes;
   OOS improvement over the champion by a set margin; performance clearly above a
   label-permutation baseline; bounded model complexity. At most one promotion per cooldown
   period; automatic rollback if post-promotion performance degrades past a threshold.
   Every step is recorded in `model_versions` and `risk_events`.

Hard rule: learning can only filter signals or reallocate a fixed risk budget; final per-trade
risk is always capped by `RiskManager`.

## Consequences

- Cold start is safe (pass-through model, equal weights) and the system behaves like the plain
  ensemble until it has data.
- Backtests must report learning-on and learning-off side by side, whatever the result.
- Model artifacts are pickled scikit-learn objects; they are written only by the trainer and
  loaded only after a SHA-256 check against `model_versions`.
- More moving parts to test: causality of features, purging, permutation guardrail, bandit
  convergence and adaptation (ROADMAP stage 4).
- Labels need later candles, so labeling runs as a scheduled sweep, not at trade close only.

## Alternatives considered

- **Direct price-direction prediction with ML** — low signal-to-noise, high overfitting risk,
  hard to explain; rejected as the primary signal source.
- **Reinforcement-learning trading agent** — sample-inefficient on the data available, opaque,
  and hard to constrain safely.
- **Static equal weights, no learning** — simplest and kept as the control arm in every backtest
  comparison.
- **Periodic re-optimisation of strategy parameters** — classic curve-fitting risk; parameter
  changes stay manual and versioned.
- **Full-information weighting (e.g. exponential weights) instead of a bandit** — viable because
  all signals are labeled; Thompson sampling chosen for its natural uncertainty handling with few
  samples per regime. Can be swapped behind `StrategyAllocator`.
