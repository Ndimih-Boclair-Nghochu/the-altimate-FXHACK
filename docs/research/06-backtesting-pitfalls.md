# 06 — Backtesting pitfalls and the checklist for our backtester

Status: research input for Stage 2 (backtester, metrics, walk-forward) and for the promotion
gates used by `03` and `05`.

**Summary.**

- Most retail FX backtests are wrong in one of three ways: (1) they peek at the future, (2) they fill at mid prices or ignore the spread, rollover and gaps, or (3) they report the best of many tried configurations as if it were the only one.
- Our own sanity checks show the size of these effects:
  - a same-bar stop-handling bug turned a ≈ −0.03 R/trade strategy into −0.9 R/trade;
  - +1 pip of cost turned a Sharpe 0.55 portfolio into −0.03;
  - deflating the best of 10 tried configurations turned a PSR of 0.98 into a DSR of 0.47.
- The checklist in §8 is the acceptance test for the backtester.

---

## 1. Lookahead bias

| Pitfall | Rule for our code |
|---|---|
| Using the current (unfinished) bar | Strategies receive only bars with `complete == true` (`02` §6.4). Indicator value at bar *t* uses data ≤ close of *t*. Orders execute at the **open of t+1** or later. |
| Resampling labels | When aggregating (H1 → H4/D1), label each bar by its **start** and make it available only after its **end**. In pandas, `resample(..., label="left", closed="left")`, then shift availability by one bar. Unit-test with a bar that spans a DST change. |
| Daily bar alignment | FX "day" = 17:00 New York → 17:00 NY (OANDA default `dailyAlignment=17`, `alignmentTimezone=America/New_York`). A D1 signal is usable from 17:00 NY of that day onward, never earlier. |
| Time zones | Store everything in UTC. Known source conventions (`07`): OANDA API = UTC (RFC3339 `Z`). HistData = **EST without DST** (fixed UTC−5). FXCM samples = UTC. LEAN OANDA files = UTC. LEAN FXCM = UTC−05 fixed. MT5 exports = **broker server time** (often EET with US-DST switching). Wrong zones shift sessions (rollover, London open) by 1–7 hours. |
| Normalization leakage | Feature scalers, percentiles (e.g. ATR percentile) and z-scores use **trailing windows only**. Never fit a scaler on the full dataset. |
| Filling at the signal bar's close | Not possible live, because the close is only known when the bar ends. Use next-open fills, or the close + latency for live-parity mode. |
| "Future-scramble" invariant | **Test:** for random cut points *t*, replace all data after *t* with noise and assert that every signal and indicator value ≤ *t* is unchanged. This catches most lookahead bugs automatically. |

## 2. Prices: bid/ask vs mid, smoothing, gaps

- **Buy at the ask, sell at the bid.** A mid-price backtest understates cost by one half-spread per side. Our checks show it matters most at H1 (`03` §4: H1 mean reversion ≈ 0 R before costs, −0.06 to −0.22 R after).
- **Stops and targets trigger on the side that would fill them** (OANDA `triggerCondition=DEFAULT` compares the ask for long orders and the bid for short orders, `02` §6.10):
  - long stop-loss triggers when the **bid low ≤ stop**; long take-profit when the **bid high ≥ TP**;
  - short stop-loss triggers when the **ask high ≥ stop**; short take-profit when the **ask low ≤ TP**.
- **Gaps:** if the bar opens beyond the stop, fill at the open (worse than the stop), not at the stop price.
- **Smoothed candles hide gaps.** OANDA's `smooth=true` and the QuantConnect/LEAN OANDA files set open = previous close. We measured: 100% of bars in the LEAN EUR/USD H1 file have bid open == previous bid close. Weekend gaps then disappear. Measured on unsmoothed MT5 data instead: EUR/USD weekend gap median 5.8 pips, p95 35.6, max 178. Always download with `smooth=false` (the default).
- **Bid/ask candle highs/lows are not simultaneous.** The ask high and the bid high can occur at different times. This is fine for trigger checks as above. Do not compute spreads from high−low differences.
- **Spread varies by time.** Measured median EUR/USD spread is 1.2–1.3 pips most hours, 2.5 at 17:00 NY. Use real bid/ask candles. If only mid/bid is available, use an **hour-of-week spread table** per instrument (median and p90 from OANDA data) and stress it.

## 3. Costs: spread, slippage, financing, commission

| Cost | Model (default) | Stress test |
|---|---|---|
| Spread | from bid/ask candles. Fallback: hour-of-week median table | × 1.5 and × 2 |
| Market-order slippage | 0.1 pip for majors in normal hours, 0.5 pip in the first 2 minutes after high-impact news (**UNVERIFIED** values: calibrate from live `halfSpreadCost` and fill-vs-quote data. `02` §6.7) | + 0.5 pip, + 1.0 pip per side |
| Stop-order slippage | fill at max(stop, open) adverse on gaps. Plus 0.1 × ATR(H1) when the bar range > 3 × ATR (fast market) | double |
| Financing (swap) | daily at 17:00 NY for positions open across it: units × price × QHC × rate/365 × `daysCharged` (`02` §6.3 `financing` field). For history, use (base − quote policy-rate differential) ± a broker markup parameter (default 1.5% p.a. each side, **UNVERIFIED**) | markup × 2 |
| Commission | 0 for OANDA standard pricing. Per-million or per-lot for core/raw accounts (config) | — |

Report every cost component separately in the backtest result. **A strategy whose edge is smaller than its cost uncertainty is not tradeable.** The London-breakout example in `03` §4 shows exactly this.

## 4. Overfitting and multiple testing

### 4.1 Why

- Every configuration you try is a lottery ticket. Report the best of N and its Sharpe is biased upward even when every configuration has zero true edge.
- Sullivan, Timmermann & White (1999, JF) showed how data snooping inflates technical-rule performance, using White's Reality Check (2000, Econometrica).
- Harvey, Liu & Zhu (2016, RFS) argue for t-statistics > 3.0 (instead of 2.0) for new factors given the amount of searching.

### 4.2 Probabilistic and Deflated Sharpe Ratio (Bailey & López de Prado 2014)

Notation: per-period (non-annualized) Sharpe estimate $\widehat{SR}$ over T returns, skewness $\hat\gamma_3$, kurtosis $\hat\gamma_4$ (non-excess, normal = 3).

$$PSR(SR^*) = \Phi\!\left(\frac{(\widehat{SR}-SR^*)\sqrt{T-1}}{\sqrt{1-\hat\gamma_3\widehat{SR}+\frac{\hat\gamma_4-1}{4}\widehat{SR}^2}}\right)$$

Expected maximum Sharpe of N independent zero-edge trials (γ ≈ 0.5772, Euler–Mascheroni; V = variance of the N trial Sharpe estimates):

$$SR_0^* = \sqrt{V}\left((1-\gamma)\,\Phi^{-1}\!\left(1-\tfrac{1}{N}\right)+\gamma\,\Phi^{-1}\!\left(1-\tfrac{1}{Ne}\right)\right)$$

$$DSR = PSR(SR_0^*)$$

**Worked example (ours).**

- Strategy: the best configuration in `03` §4, the London breakout 3-pair portfolio on MT5 data 2012–2022.
- T = 2,412 weekday returns. Daily SR = 0.0408 (0.65 annualized). Skew 0.35, kurtosis 2.7. PSR(0) = **0.978**: "significant" if it were the only thing tried.
- With N = 10 configurations tried (annualized Sharpes 0.01, 0.23, 0.33, 0.33, 0.11, −0.14, 0.55, −0.97, −0.19, −0.24), SR₀* = 0.042 daily (0.67 annualized) and **DSR = 0.47**. Not significant.
- This is why the backtester must record the number of trials.

### 4.3 Minimum backtest length (Bailey, Borwein, López de Prado & Zhu 2014)

MinBTL ≈ (E[max of N standard normals]/SR_target)². Recomputed: for an in-sample annualized Sharpe of 1 to be expected from noise alone, **7 trials need ≈ 1.9 years, 45 trials ≈ 5.0 years, 100 trials ≈ 6.4 years** of data. Practical rule: with fewer years than this, the in-sample "best" is indistinguishable from luck.

### 4.4 Probability of Backtest Overfitting, CSCV (Bailey, Borwein, López de Prado & Zhu 2017)

Algorithm (implement in `backtest/overfitting.py`):

1. Build matrix M (T × N): per-period returns of N candidate configurations over the same T periods.
2. Split rows into S contiguous blocks (S even, default **S = 16**).
3. For each of the C(S, S/2) = 12,870 combinations: the train set J = the chosen S/2 blocks, the test set J̄ = the rest.
4. Pick n* = argmax Sharpe on J. Compute the relative rank ω of n*'s Sharpe among all N on J̄ (ω ∈ (0,1)). Then λ = ln(ω/(1−ω)).
5. **PBO = fraction of combinations with λ ≤ 0** (the IS-best is below the OOS median).
6. Also report the regression of OOS on IS performance (degradation slope) and the probability of an OOS loss.

Gate: **PBO < 0.3** for any parameter selection we rely on.

### 4.5 Practical anti-overfitting rules

- Prefer **few, a-priori parameters** from the literature (`03` §5) over optimized ones. If parameters are optimized, look for **plateaus**: ±20% perturbations of each parameter must keep mean R > 0.
- Keep a **final holdout** (the most recent 12 months of data at project start) that nobody looks at until a promotion decision.
- Count everything: number of strategies × parameter sets × pairs × timeframes tried. Log it in the backtest registry.
- Test on **multiple instruments and data sources**. A rule that only works on one pair or one vendor's data is suspect (`03` §4: the London breakout works on MT5 2012–22 GBP/USD but not on OANDA 2007–18 EUR/USD).

## 5. Monte Carlo and robustness tests

| Test | What it tells you | How |
|---|---|---|
| Trade reshuffle (permutation of the R sequence) | Drawdown and losing-streak **distribution** for the same trades (expectancy unchanged) | 5,000 permutations. Report the p50/p95 of maxDD and the longest losing streak. Live drawdown beyond p95 → investigate |
| Stationary block bootstrap of daily returns (Politis & Romano 1994) | Confidence interval of Sharpe/CAGR with autocorrelation preserved | Mean block 20 days, 5,000 resamples |
| Random-entry benchmark | Whether the **entries** add value beyond exits/sizing | Same exit rules, same trade count, random entry times/sides. Strategy mean R must exceed the random 95th percentile |
| Cost stress | Robustness of the edge to costs | Spread × 1.5, × 2. Slippage + 0.5/+1.0 pip |
| Delay test | Sensitivity to latency/data delays | Execute 1 bar later. Edge sign must not flip for H4/D1 strategies |
| Parameter perturbation | Plateau vs spike | ±20% on each parameter, one at a time and jointly (Latin hypercube 50 points) |
| Sub-period / per-pair split | Stability | Per year and per pair. No single year/pair > 50% of the total P&L |
| Synthetic null data | Pipeline sanity | GBM/random walk with realistic vol and spread. Every strategy must show ≈ 0 gross and < 0 net expectancy. Trend-injected series: the trend strategy must profit |

## 6. Walk-forward and promotion gates

- **Walk-forward analysis:** for strategies with fixed a-priori parameters, walk-forward is simply sequential out-of-sample evaluation by year. For optimized parameters: rolling/anchored windows (e.g. train 3 years, test 6 months, step 6 months), re-optimize in each window, concatenate test segments. Report walk-forward efficiency = OOS annualized return / IS annualized return (Pardo 2008). Expect 0.3–0.7 at best. Values > 1 are suspicious.
- **Shadow → live promotion gates** (used by `03` §5 and `05` §6). All must pass on **out-of-sample** evidence (walk-forward backtest segments + shadow live labels):
  1. ≥ **200** OOS trades spanning ≥ **2 years** and ≥ **3** instruments.
  2. Net mean R > 0 with **PSR(0) ≥ 0.95** on the trade-level R series.
  3. **DSR ≥ 0.90**, with N = all configurations of that strategy family ever tried (from the registry).
  4. Mean R still > 0 at **1.5× costs**. With +1 bar delay the sign does not flip.
  5. PBO < 0.3 if any parameter selection was involved.
  6. No single year or instrument contributes > 50% of total R.
  7. The live-shadow drawdown in R is within the Monte-Carlo p95 of the backtest.
  8. Manual approval in the UI (journaled).

## 7. Metrics the backtester must report

Per run and per strategy/instrument:

- **Returns and risk:** CAGR, annualized vol, Sharpe (daily returns, √252; state the convention), Sortino, max drawdown and its duration, Calmar.
- **Trade statistics:** trades/yr, exposure %, win rate, average win/loss in R, expectancy (R), profit factor, MAE/MFE distributions.
- **Costs:** breakdown (spread, slippage, financing, commission) in R and in currency.
- **Statistical:** PSR(0), DSR (with N trials), bootstrap Sharpe CI, Monte-Carlo drawdown p50/p95.
- **Provenance:** data hash, config hash, code commit, random seeds, number of trials. Every result is reproducible, as required by brief principle 2.

## 8. Concrete checklist for `backtest/` (acceptance tests)

Engine:

- [ ] Event-driven loop over **closed** bars. Strategies cannot access bars with index > t (enforced by a view object, not convention).
- [ ] Orders created at bar t execute at the **open of t+1** (default) with bid/ask sides. A configurable extra latency in bars.
- [ ] Long stop/TP evaluated on **bid**, short stop/TP on **ask**. Gap fills at the open.
- [ ] **Same-bar ambiguity:** if a bar touches both stop and TP, assume the **stop first** (default). If an entry and the stop/TP could both occur in the entry bar, do not evaluate the stop/TP on the entry bar's range, except a close beyond the stop. Optional "bar magnifier": resolve the path with M1 data when available. Count ambiguous bars in the report.
- [ ] Rollover financing applied at 17:00 NY using per-instrument long/short rates and `daysCharged`.
- [ ] Spread model: real bid/ask when available, else hour-of-week table. Cost multipliers configurable.
- [ ] Session/rollover/weekend/news filters identical to the live risk engine (**same code path**: the backtester calls the risk engine).
- [ ] Position sizing via the live risk engine, including currency conversion with historical conversion rates (QHC from the relevant pair at that time).
- [ ] Netting semantics identical to the broker adapter (OANDA non-hedging: opposite orders reduce first).
- [ ] Deterministic: same inputs + seed → byte-identical results. Results stored with provenance.

Data:

- [ ] Candles stored in UTC with source, price side (B/A/M), `smooth` flag and timezone of origin.
- [ ] Gap and duplicate checks. Weekend/holiday gaps flagged, not forward-filled into fake bars.
- [ ] Resampling tested across DST transitions (March/November US, March/October EU).

Statistics:

- [ ] PSR/DSR, trial counter, CSCV/PBO, trade reshuffle, block bootstrap, random-entry benchmark, cost and delay stress, parameter perturbation, per-year/per-pair split.

Tests (pytest, no network):

- [ ] Future-scramble invariant test (§1).
- [ ] Synthetic null-data test (§5).
- [ ] Known-answer tests: hand-computed fills for a 5-bar fixture (long stop hit by bid low, short TP hit by ask low, gap through stop, same-bar stop+TP, financing over Wednesday).
- [ ] Regression test reproducing the squeeze bug from `03` §4: a stop-entry bar whose low is below the stop must not be counted as a stop-out unless it closes there.

## 9. Sources

- Bailey, D. H. & López de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. *Journal of Portfolio Management* 40(5).
- Bailey, D. H., Borwein, J., López de Prado, M. & Zhu, Q. J. (2014). Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance. *Notices of the AMS* 61(5).
- Bailey, D. H., Borwein, J., López de Prado, M. & Zhu, Q. J. (2017). The Probability of Backtest Overfitting. *Journal of Computational Finance* 20(4).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley (ch. 7, 11–14).
- Harvey, C. R., Liu, Y. & Zhu, H. (2016). …and the Cross-Section of Expected Returns. *Review of Financial Studies* 29(1).
- Sullivan, R., Timmermann, A. & White, H. (1999). Data-Snooping, Technical Trading Rule Performance, and the Bootstrap. *Journal of Finance* 54(5).
- White, H. (2000). A Reality Check for Data Snooping. *Econometrica* 68(5). Hansen, P. R. (2005). A Test for Superior Predictive Ability. *JBES* 23(4).
- Politis, D. N. & Romano, J. P. (1994). The Stationary Bootstrap. *JASA* 89(428).
- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*, 2nd ed. Wiley (walk-forward analysis).
- OANDA trigger semantics, smoothing parameter, alignment defaults: `02-oanda-v20-api-spec.md`.
- Measurements and worked examples: our computation on the datasets in `07-data-sources.md`.
