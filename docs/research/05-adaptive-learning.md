# 05 — Learning safely from past trades

Status: research input for Stage 4 (adaptive learning).

**Summary.**

- Learning is a **filter and allocator on top of rule-based strategies**, never a price predictor and never a risk-limit override.
- Components:
  1. **Labels** for *every* strategy signal (live, filtered and shadow) computed from market data with the strategy's own exit rules (a strategy-specific triple barrier). This removes the main feedback-loop bias.
  2. A **meta-labeling classifier** (logistic regression baseline, gradient-boosted trees challenger) that can only **shrink or skip** trades.
  3. A **discounted Thompson-sampling allocator** per regime that moves risk multipliers within [0.5, 1.5].
  4. **Drift detection**, with honest limits: P&L-based detectors are slow. Our simulation needed ~100–350 trades to detect a 0.3R drop.
  5. **Champion/challenger** promotion with purged walk-forward validation and statistical gates.
- The hard truth driving every default: with per-trade R standard deviation ≈ 1.2–1.9, distinguishing an edge of +0.1R from zero needs **≈ 400–1,000 trades**.

---

## 1. Sample-size arithmetic (read this first)

To show that mean R per trade μ > 0 with one-sided 95% confidence, n ≈ (1.645 · σ / μ)². With σ = 1.5R (typical for trend payoffs. Our simulated trend payoff had σ ≈ 1.7–1.9R):

| True edge μ (R/trade) | n needed (σ = 1.5) | At 80 trades/yr (S1 on 4 pairs) |
|---|---|---|
| 0.30 | 68 | ~10 months |
| 0.20 | 152 | ~2 years |
| 0.10 | 609 | ~7.5 years |
| 0.05 | 2,435 | decades |

Implications:

- Per-regime-cell statistics (12 cells) are mostly noise for years. Pool them hierarchically (§6).
- "Learning from closed trades" of a single live strategy is far too slow on its own. Hence the use of **shadow signals** and **historical backtest signals** labelled the same way, which multiply the sample size without risking capital.
- Every adaptive component needs priors, shrinkage and clamps.

## 2. Labels: strategy-specific triple barrier

Triple-barrier method (López de Prado, *Advances in Financial Machine Learning* (AFML), 2018, ch. 3): for each event at time t₀, set an upper barrier (profit-taking), a lower barrier (stop-loss) and a vertical barrier (max holding time). The label is determined by which barrier is touched first.

Our variant (recommended): **simulate the strategy's real exit logic** on bid/ask bars, so the label equals what the trade would have earned.

- Lower barrier = the initial stop, and the trailing stop as it updates.
- Upper barrier = TP (S2, S3) or the trailing exit (S1).
- Vertical barrier = the strategy time stop (S1: 120 H4 bars. S2: 24 H1 bars. S3: 16:00 UTC).
- Costs: spread from bid/ask bars, plus modeled slippage, plus financing.
- Stored per event: `R_net` (float), `y = 1 if R_net > 0 else 0`, `exit_reason ∈ {stop, tp, trail, time, signal}`, `bars_held`, `MAE_R`, `MFE_R`, `t_end` (label end time, needed for purging).
- Same-bar ambiguity (stop and target touched in the same bar): assume the **stop was hit first** (conservative). Count how often it happens.

Why this matters:

- Labels come from **market data, not from our fills**. So signals the meta-model rejected, signals in shadow mode, and signals during halts all get labels. The model is trained on the full signal population, not only on trades it already liked. That is the main protection against feedback loops (§8).
- Executed trades provide a second source of truth: compare realized R with the simulated label for the same signal. Persistent divergence means the cost/slippage model is wrong. That is a high-priority alert, not a learning signal.

**Sample weights for overlapping labels** (AFML ch. 4): events whose label windows overlap are not independent. Weight each event by its *average uniqueness* ū_i = mean over t ∈ [t₀,i, t_end,i] of 1/c_t, where c_t is the number of concurrent label windows at bar t. Normalize the weights to sum to n. Use them in training (`sample_weight`) and in evaluation.

## 3. Meta-labeling

AFML ch. 3.6: a primary model decides the **side** (here: the rule-based strategies). A secondary ("meta") model predicts the probability that the primary's signal will be profitable, and is used to **filter and size**. López de Prado argues this raises precision (fewer false positives) and keeps the primary logic interpretable. There is no FX-specific published evidence that it adds net value, so **treat it as a hypothesis that must beat a pass-through baseline** (§7).

### 3.1 Decision rule

- Break-even probability for the strategy: p* = |avg loss R| / (avg win R + |avg loss R|). Estimate it from the training labels with shrinkage toward the strategy's historical value. For S1 with avg win ≈ 2.5R and loss ≈ 1R, p* ≈ 0.29. For S2 with win ≈ 1R and loss ≈ 1R, p* ≈ 0.5.
- `m_meta = clip((p̂ − p*) / 0.15, 0, 1)`. Skip the trade if `m_meta < 0.2`. Full size only when p̂ ≥ p* + 0.15.
- This mapping is deliberately simple and monotone. AFML's bet-sizing formula 2Φ(z) − 1 assumes a 0.5 threshold, which does not fit low-hit-rate trend strategies.
- The meta-model **never increases size above 1.0×**.

### 3.2 Features (all computable at signal time from closed bars and current quotes)

| Group | Features |
|---|---|
| Signal | strategy id, side, stop distance / ATR, breakout distance / ATR (S1/S3), z-score vs band (S2), bars since last signal |
| Trend | ADX(14) on H1/H4/D1, ER(20) on H1/H4, TSMOM sign × \|return\| / vol for 21/63/126 days, (close − EMA50)/ATR, (EMA50 − EMA200)/ATR |
| Volatility | ATR percentile (120 days), ATR(14)/ATR(100) ratio, realized vol 1d/20d, Parkinson range vol |
| Mean-reversion / persistence | variance ratio VR(2) and VR(8) on 256 H1 returns, rolling Hurst (R/S, 512 bars). These are noisy, so they go to the model, not into gates |
| Costs & time | spread (pips), spread / stop, spread / hour-of-week median, NY hour (sin/cos), weekday, minutes to next high-impact event, session flags (Asia/London/NY/overlap), holiday flag |
| Cross-pair | USD basket return (mean of USD-major returns, sign-adjusted) over 1/5/20 days, correlation of the pair with the USD basket (60 days), number of majors in the same TSMOM direction |
| Carry | financing long/short rate for the trade side (annualized), expected financing over the median holding time in R |

Excluded on purpose:

- Anything from the signal bar's future (e.g. the next bar's open), or daily features from an unclosed D1 bar.
- **Own P&L state** (current drawdown, recent win streak, account size). These create reflexive loops: the model learns "after losses, skip", which interacts with the risk engine's own drawdown rules.
- Raw price levels (non-stationary).

Feature engineering lives in `learning/features.py` with a **versioned feature schema** (name, definition hash, version). The model registry stores the schema version, and a model refuses to score if it does not match.

### 3.3 Models and libraries

| Option | Pros | Cons | Use |
|---|---|---|---|
| `sklearn.linear_model.LogisticRegression` (L2, standardized features) | Stable, calibrated-ish, interpretable, tiny-data friendly | Linear | **Baseline champion** |
| `sklearn.ensemble.HistGradientBoostingClassifier` | Nonlinear interactions, native NaN handling, early stopping, no extra dependency (scikit-learn is already in the stack) | Overfits easily on small n. Needs calibration | **Default challenger** |
| `lightgbm.LGBMClassifier` (4.7.0, 2026-07) | Fast, mature, many regularization knobs | Extra dependency (needs the OpenMP runtime, e.g. `libgomp1`, in slim Docker images. Check). More knobs = more overfitting opportunities | Optional challenger once n > 2,000 |
| `river` (0.26.1, 2026-08, Python ≥ 3.11) online models | True incremental updates, built-in drift detectors (`drift.ADWIN`, `drift.PageHinkley`, `drift.KSWIN`), bandit policies | Online models are hard to validate with purged CV. Weaker accuracy on small tabular data | **Drift detectors and online statistics only** |

Default hyperparameters (opinion, conservative):

- LR: `C=0.5`, `class_weight=None`, `max_iter=1000`.
- HGB: `max_depth=3`, `max_leaf_nodes=8`, `min_samples_leaf=max(50, n//20)`, `learning_rate=0.05`, `max_iter=300`, `early_stopping=True`, `validation_fraction` taken from a **purged** split (do not use the built-in random split: pass a custom validation set), `l2_regularization=1.0`, `random_state` fixed.
- Calibration: isotonic if n_valid ≥ 1,000, else sigmoid (Platt), fitted on purged out-of-fold predictions only.
- Search budget: at most **20** hyperparameter configurations per retrain. Record the number of trials (it feeds the deflated Sharpe in `06`).

## 4. Validation: purged, embargoed, walk-forward

- **Purged k-fold** (AFML ch. 7): when a fold is used for testing, remove from training every event whose label window [t₀, t_end] overlaps any test event's window.
- **Embargo**: additionally drop training events that start within h bars after the test fold. Default h = max(strategy max holding period, 1% of the sample).
- k = 5 for model selection.
- **Walk-forward** for final evaluation: expanding window, retrain monthly, score the next month, concatenate the out-of-sample predictions. Policy metrics are computed only on these walk-forward predictions.
- **Combinatorial purged CV** (AFML ch. 12) to get a distribution of out-of-sample performance and the probability of backtest overfitting (PBO) when comparing several candidate configurations (`06` §4).
- Implementation note: purged/embargoed CV is ~80 lines with numpy/pandas and an `IntervalIndex` of label windows. Implement it in `learning/cv.py` with unit tests on synthetic overlapping labels (test that no train event overlaps a test window and that the embargo is respected). Avoid depending on `mlfinlab` (licensing changed to commercial).

Metrics:

- Probabilistic: log-loss, Brier, ROC-AUC, calibration slope/intercept.
- Policy (what matters): coverage (% signals kept), mean R of kept vs all signals, Sharpe of the kept-trade stream, max drawdown in R, PSR (`06`).

## 5. Online learning: what to update online and what not

- **Do not** update the production classifier after every trade. Online updates on tiny, noisy, overlapping samples chase noise, cannot be validated before they act, and make results irreproducible.
- **Do** update online:
  1. bandit posteriors (§6);
  2. drift detectors (§7);
  3. running cost statistics (spread, slippage, `halfSpreadCost` vs model);
  4. per-strategy running expectancy for the dashboard.
- Retrain the meta-model in **batch** on a schedule (weekly) or on a drift trigger. That produces a *challenger*. Promotion follows §8.

## 6. Strategy allocation: discounted Thompson sampling per regime

**Arms:** the live-enabled strategies, plus a **cash arm** with reward fixed at 0. If every strategy looks negative, probability mass flows to cash and all multipliers shrink.

**Context:** the regime cell `(trend_label, vol_label)` of the instrument at signal time (`03` §5.1). 12 cells. To fight the sample-size problem, use **hierarchical pooling**: each cell's prior is the strategy's global posterior, with its weight capped at κ_prior = 10 pseudo-observations.

**Reward:** realized net R of each closed trade. Shadow and backtest labels update a separate "evidence" posterior used for promotion decisions (`06` §6), not the live allocator. The allocator only learns from live (paper/practice/live) closed trades, so it reflects real execution.

**Posterior:** Normal with unknown mean and variance (Normal-Inverse-Gamma).

- Sufficient statistics (n, Σx, Σx²) per (strategy, cell) and per strategy globally.
- **Discounting** (non-stationarity): before each update multiply n, Σx, Σx² by γ. Default **γ = 0.99**, effective memory ≈ 1/(1−γ) = 100 trades.
- This follows the discounted Thompson sampling idea of Raj & Kalyani (2017), "Taming non-stationary bandits: A Bayesian approach", arXiv:1707.09727, and the discounted/sliding-window UCB line of Garivier & Moulines (2011).
- Global prior: μ₀ = 0 (no edge assumed), κ₀ = 10, α₀ = 3, β₀ = 2·σ₀² with σ₀ = 1.5R (so E[σ²] = σ₀²).
- Sampling: σ² ~ InvGamma(α, β), μ ~ N(m, σ²/κ).

**Allocation step** (on every new signal, or cached per bar):

1. Draw 2,000 posterior samples of μ for each active strategy in the signal's cell, plus cash (μ = 0).
2. P_best(s) = fraction of draws in which s has the highest μ.
3. `m_strategy(s) = clip(N_active × P_best(s), 0.5, 1.5)` if the strategy has ≥ 20 effective live observations in the cell. Otherwise use the global-level P_best. If it has < 20 observations globally, use `m_strategy = 1.0` (prior only).
4. Demotion: if P(μ_s > 0 | global posterior) < 0.10 with ≥ 50 effective live trades → the strategy goes to **shadow** and an alert is raised. Re-promotion requires the `06` §6 gates.

Why the clamps:

- With σ ≈ 1.5R and 100 effective trades, the posterior SE of μ is ≈ 0.15R, as large as the edges we hope for.
- Unclamped Thompson sampling would swing allocations on noise. The [0.5, 1.5] range limits the damage of a wrong posterior to ±50% of base risk. The risk engine caps still apply on top.

`river.bandit.ThompsonSampling` exists (0.26.1) but has **no discounting** and is built around a single distribution object. Implement the ~60-line Normal-Inverse-Gamma version ourselves in `learning/bandit.py` (numpy only, seeded RNG). Test it on synthetic arms with a mid-stream mean switch.

## 7. Drift detection

### 7.1 Evidence: P&L-based detectors are slow (our simulation)

Simulated per-trade R stream (36–38% winners, σ ≈ 1.7R) whose mean drops from +0.15R to −0.15R, 200 runs per setting, river 0.26.1:

| Detector (river) | False alarms within 1,000 pre-change trades | Median delay after the change | Detected within 400 trades |
|---|---|---|---|
| `ADWIN(delta=0.002)` (default) | 1% (within 2,000) | > 400 | 18% |
| `PageHinkley(delta=0.15, threshold=40, alpha=0.999, mode="down")` | 29% | 96 trades | 99% |
| `PageHinkley(delta=0.15, threshold=40, alpha=1.0, mode="down")` | 14% | 166 trades | 90% |
| `PageHinkley(delta=0.15, threshold=60, alpha=0.999, mode="down")` | 8% | 220 trades | 85% |
| `PageHinkley(delta=0.05, threshold=30, alpha=1.0, mode="down")` | 95% (within 2,000) | 76 trades | 100% |

Conclusion: on realistic trade-outcome noise, any detector that reacts within ~100 trades also raises frequent false alarms. P&L drift detection is a **slow warning system**. Fast protection comes from the risk engine (loss limits, drawdown ladder) and from monitoring **inputs**, which are much less noisy.

### 7.2 Default monitors

| Monitor | Signal | Detector (defaults) | Action |
|---|---|---|---|
| Strategy P&L drift | per-trade net R (live), per strategy | `PageHinkley(min_instances=30, delta=0.15, threshold=60, alpha=0.999, mode="down")` | **Warning**: halve `m_strategy` for that strategy, open a review. Not an automatic shutdown |
| Meta-model degradation | per-event Brier error (p̂ − y)² on new labels | `ADWIN(delta=0.002)` (river: `update(x)`, then `drift_detected`) | Trigger a challenger retrain. If the error mean rose, set `m_meta = 1` pass-through until the new model is promoted |
| Feature drift | each key feature's distribution vs the training window | Population Stability Index weekly. PSI > 0.25 on ≥ 3 key features, or `river.drift.KSWIN` on the 5 most important features | Retrain trigger + alert |
| Cost drift | realized `halfSpreadCost` and slippage per fill vs the backtest cost model | CUSUM / `PageHinkley(mode="up")` on (realized − modeled) cost in pips | **Immediate alert**. Costs are directly observable and change the edge one-for-one |
| Label drift | base rate of y = 1 per strategy | `ADWIN` | Informational. Recalibrate p* |

## 8. Champion/challenger promotion and guardrails

### 8.1 Promotion gates (all must pass)

1. **Data:** challenger trained on data ending ≥ 1 embargo before the **evaluation window**: the most recent ≥ 3 months with ≥ 150 labelled events, unseen by both champion and challenger. A separate **final holdout** (the most recent 6 months at system start-up) is never used for any tuning.
2. **Probabilistic:** log-loss improvement ≥ 1% vs champion with a paired-bootstrap (1,000 resamples, block bootstrap by week) 90% CI excluding 0. Brier not worse. Calibration slope in [0.8, 1.2].
3. **Economic:** kept-trade policy (§3.1) has higher mean R × coverage than the champion's. The bootstrap lower 80% bound of the difference is ≥ 0. Also the challenger must beat **pass-through** (no filter) on the same window. If no model beats pass-through, pass-through is the champion.
4. **Robustness:** across the 5 purged folds, the sign of the improvement is the same in ≥ 4. No single feature has > 50% of permutation importance. Top-5 features overlap ≥ 3 with the previous model's (or the change is explained in the review).
5. **Multiple testing:** the number of configurations tried is recorded. If ≥ 4 candidates were compared, PBO (CSCV, `06` §4) must be < 0.3.
6. **Operational:** challenger runs in shadow (scoring live signals without acting) for ≥ 2 weeks. At most one promotion per 14 days. Automatic rollback to the previous champion if, over the next 50 labelled events, its log-loss is worse than the previous champion's by more than 2 bootstrap standard errors.

### 8.2 Guardrails against overfitting and feedback loops

- **Label everything from market data** (§2), so filtering does not censor the training set.
- **The meta-model only shrinks.** The bandit multiplier is clamped to [0.5, 1.5]. The risk engine applies its hard caps after both. No learned component can raise risk above `risk.per_trade_pct_max`.
- **No P&L-state features** (§3.2).
- **Frozen, versioned features.** A training run is reproducible from (data snapshot hash, feature schema version, code commit, seed). The registry stores all four plus metrics.
- **Search budgets** (≤ 20 configs per retrain) and trial counting for deflated Sharpe.
- **Coverage alarms:** if the model keeps < 30% or > 95% of signals for a strategy over 50 signals, alert (degenerate model or useless filter).
- **Exploration is not needed with real money:** the shadow labels already provide outcomes for skipped signals. Execution-cost learning uses only executed trades and feeds the cost model, not the classifier.
- **Human in the loop for structural changes:** promoting a strategy from shadow to live, or changing feature sets, requires a manual approval in the UI (journaled).

## 9. Concrete design (module map)

```
learning/
  features.py     FeatureSchema(version), compute_features(signal, market_snapshot) -> dict
  labeling.py     simulate_exit(strategy, signal, bars_bid_ask) -> Label(R_net, y, t_end, exit_reason, MAE, MFE)
  weights.py      average_uniqueness(label_windows) -> np.ndarray
  cv.py           PurgedKFold(n_splits=5, embargo_bars), walk_forward_splits(...)
  meta_model.py   MetaModel(fit, predict_proba, size_multiplier(p, p_star)), PassThrough
  bandit.py       DiscountedNIGThompson(gamma=0.99, prior=..., clamp=(0.5, 1.5)), CashArm
  drift.py        wrappers around river.drift.ADWIN / PageHinkley / KSWIN + PSI
  registry.py     ModelRegistry (SQL table: id, kind, version, schema_version, data_hash, commit, metrics_json, status=champion|challenger|retired, created_at)
  scheduler.py    weekly retrain job, drift-triggered retrain, promotion evaluation
```

Data flow per signal: strategy emits a `Signal` → features computed and stored → meta-model scores → bandit multiplier → risk engine sizes/vetoes → order (or none) → the label job later computes the triple-barrier `Label` for the signal (executed or not) → the drift monitors and bandit (closed live trades only) update.

Persistence: tables `signals`, `signal_features` (JSON + schema version), `labels`, `trades` (FK signal_id), `models`, `model_scores` (signal_id, model_id, p̂), `bandit_state` (strategy, cell, n, sx, sxx, updated_at), `drift_events`.

Bootstrapping on day 1: run the backtester over the historical data to generate **historical signals + labels** for all strategies. That gives hundreds to thousands of labelled events, enough to train and evaluate a first meta-model under purged walk-forward *before* any live trade. Live/shadow labels are appended as they mature.

## 10. Default parameter table

| Key | Default |
|---|---|
| `learning.min_events_to_train` | 300 per strategy (500 preferred) |
| `learning.max_features` | min(30, n_events / 20) |
| `learning.cv` | PurgedKFold k=5, embargo = max(holding_period, 1% of n) |
| `learning.walk_forward` | expanding window, monthly retrain/score |
| `learning.retrain_schedule` | weekly (Sunday 18:00 NY) + drift triggers |
| `learning.models` | champion: pass-through or LR(C=0.5). Challenger: HGB(depth 3, 8 leaves, min_leaf ≥ 50, lr 0.05, 300 iters, early stop on purged split) |
| `learning.calibration` | isotonic if n_valid ≥ 1,000, else sigmoid |
| `learning.hparam_budget` | 20 configs per retrain |
| `meta.size_rule` | m_meta = clip((p̂ − p*) / 0.15, 0, 1). Skip if < 0.2 |
| `bandit.gamma` | 0.99 |
| `bandit.prior` | μ₀ = 0, κ₀ = 10, α₀ = 3, σ₀ = 1.5R |
| `bandit.clamp` | [0.5, 1.5] |
| `bandit.min_obs_cell` / `min_obs_global` | 20 / 20 |
| `bandit.demote_rule` | P(μ > 0) < 0.10 with ≥ 50 effective trades → shadow |
| `drift.pnl` | PageHinkley(min_instances=30, delta=0.15, threshold=60, alpha=0.999, mode="down") → warning |
| `drift.model` | ADWIN(delta=0.002) on Brier error |
| `drift.features` | PSI > 0.25 on ≥ 3 key features, weekly |
| `promotion.eval_window` | ≥ 3 months and ≥ 150 events |
| `promotion.min_logloss_gain` | 1% with bootstrap 90% CI > 0 |
| `promotion.cooldown_days` | 14 |
| `promotion.shadow_days` | 14 |
| `promotion.rollback` | worse by > 2 SE over the next 50 events |

## 11. Sources

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Ch. 3 (triple barrier, meta-labeling), ch. 4 (sample weights / uniqueness), ch. 7 (purged k-fold, embargo), ch. 10 (bet sizing), ch. 12 (CPCV), ch. 14 (backtest statistics).
- Raj, V. & Kalyani, S. (2017). Taming non-stationary bandits: A Bayesian approach. arXiv:1707.09727. https://arxiv.org/pdf/1707.09727
- Qi, H. et al. (2023). Discounted Thompson Sampling for Non-Stationary Bandit Problems. arXiv:2305.10718. https://arxiv.org/pdf/2305.10718
- Garivier, A. & Moulines, E. (2011). On upper-confidence bound policies for switching bandit problems. ALT 2011.
- Russo, D. et al. (2018). A Tutorial on Thompson Sampling. Foundations and Trends in ML.
- Bifet, A. & Gavaldà, R. (2007). Learning from time-changing data with adaptive windowing (ADWIN). SIAM SDM. (Referenced in the river `ADWIN` docstring.)
- Page, E. S. (1954). Continuous inspection schemes. Biometrika 41. (Referenced in the river `PageHinkley` docstring.)
- river 0.26.1 (PyPI, 2026-08-21, requires Python ≥ 3.11): `river.drift.ADWIN(delta=0.002, clock=32, max_buckets=5, min_window_length=5, grace_period=10)`, `river.drift.PageHinkley(min_instances=30, delta=0.005, threshold=50.0, alpha=0.9999, mode="both")` defaults, `river.bandit.ThompsonSampling` (no discounting). Inspected from the wheel: https://pypi.org/project/river/
- scikit-learn 1.9.1 (PyPI, 2026-09-10, Python ≥ 3.11). LightGBM 4.7.0 (PyPI, 2026-07-18).
- Drift simulation and sample-size table: our computation (this document, §1 and §7.1).
