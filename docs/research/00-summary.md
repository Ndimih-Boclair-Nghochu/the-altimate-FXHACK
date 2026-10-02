# 00 — Research summary: decisions, defaults and honest expectations

This is the entry point to `docs/research/`. Each section links to the detailed report.
Evidence (published research or our own reproducible computation) is kept separate from
opinion (engineering judgement). Numbers we could not verify are marked **UNVERIFIED** in the
detailed reports.

| # | Report | One-line takeaway |
|---|---|---|
| 01 | [Broker platforms](01-broker-platforms.md) | OANDA v20 is the primary adapter, **but its live REST API is reportedly unavailable to OANDA Global Markets/TMS clients**. cTrader Open API is the secondary adapter. |
| 02 | [OANDA v20 API spec](02-oanda-v20-api-spec.md) | Implementation reference built from OANDA's official OpenAPI spec and recorded payloads. |
| 03 | [Strategies](03-strategies.md) | Only slow trend following has decent evidence. Mean reversion and session breakout start in **shadow mode**. |
| 04 | [Risk management](04-risk-management.md) | 0.5% risk/trade (0.25% first live phase), ATR stops on fill, layered limits, drawdown ladder. |
| 05 | [Adaptive learning](05-adaptive-learning.md) | Label every signal from market data. Meta-model can only shrink. Clamped discounted Thompson sampling. Drift detection is slow. |
| 06 | [Backtesting pitfalls](06-backtesting-pitfalls.md) | Bid/ask fills, same-bar ambiguity, cost stress, DSR/PBO, promotion gates, acceptance checklist. |
| 07 | [Data sources](07-data-sources.md) | OANDA `price=BA` for research. Pinned GitHub datasets for offline validation. Synthetic data in CI. |
| 08 | [MetaTrader 5](08-metatrader5.md) | The user's live path (Cameroon, Stage 1b). Python API reference, Windows-VPS + localhost bridge deployment, broker shortlist with caveats, design implications. |

---

## 1. Decisions

1. **Brokers.**
   - **Update:** the user is in Cameroon and trades on **MetaTrader 5**, so the **MT5 adapter (Stage 1b) is the production path** (`08`). OANDA v20 stays the reference adapter for development and offline tests.
   - Build OANDA v20 as the primary adapter, with our own thin `httpx` client (no unmaintained SDK) and pydantic models that ignore unknown fields.
   - Design the `Broker` protocol so a **cTrader Open API** adapter (JSON over WebSocket, port 5036) can be added next, followed by an optional MT5 bridge.
   - Do not use FXCM: `fxcmpy` was removed from PyPI and ForexConnect has no Python ≥ 3.8 Linux wheels.
2. **Strategies.**
   - Ship `trend_breakout_h4` (55-bar Donchian breakout on H4, D1 126-day TSMOM direction filter, 2.5×ATR stop, 3×ATR chandelier trail) as the only strategy enabled by default.
   - Implement `mean_reversion_h1` and `session_breakout_h1` but run them in **shadow mode** (signals + labels, no orders) until they pass the promotion gates in `06` §6.
   - No M15 trading, no stand-alone carry, no grid/martingale.
3. **Regime detection.** ADX(14) + Kaufman efficiency ratio ER(20) → TREND/RANGE/NEUTRAL. ATR percentile over 120 days → LOW/NORMAL/HIGH/EXTREME vol. Two-bar hysteresis. No new entries in EXTREME vol.
4. **Risk.** All orders carry a stop **on fill**. Risk is sized from the all-in stop distance. The risk engine is the last word, and learning components can only reduce risk (bandit max ×1.5 within hard caps).
5. **Learning.**
   - Label **all** signals (executed, filtered, shadow, historical) by simulating each strategy's exit rules on bid/ask data. This is the main defence against feedback loops.
   - Meta-model: pass-through or logistic regression as champion, HistGradientBoosting as challenger. Purged/embargoed CV and walk-forward. Promotion gates with bootstrap CIs and DSR/PBO.
   - Allocator: discounted Normal-Inverse-Gamma Thompson sampling with a cash arm, clamped to [0.5, 1.5].
   - Drift detection via `river` (ADWIN/PageHinkley) plus input/cost monitors.
6. **Backtester.**
   - Event-driven, closed bars only, next-open fills on the correct side of the spread, conservative same-bar handling.
   - Rollover financing from instrument data. Calls **the same risk engine** as live.
   - Records the number of trials and reports PSR/DSR, PBO, Monte-Carlo drawdowns and cost/delay stress.
7. **Data.** OANDA `price=BA`, `smooth=false`, complete candles only, stored in UTC with provenance metadata. Pinned GitHub validation sets (QuantConnect LEAN OANDA bid/ask H1 2007–2018, ejtraderLabs MT5 H1/M15 2012–2022) downloaded on demand into git-ignored `data/`. CI uses synthetic data.

## 2. Default parameters (implement directly)

### 2.1 Strategies and regime

| Key | Default |
|---|---|
| `universe` | EUR_USD, GBP_USD, USD_JPY, AUD_USD (add USD_CAD, NZD_USD later. Exclude CHF pairs initially) |
| `regime.adx_period` / `trend_min` / `range_max` | 14 / 25 / 20 |
| `regime.er_period` / `er_trend_min` / `er_range_max` | 20 / 0.30 / 0.20 |
| `regime.atr_pct_window_days` | 120 |
| `regime.vol_buckets` | LOW < 0.25 ≤ NORMAL < 0.75 ≤ HIGH < 0.95 ≤ EXTREME |
| `regime.hysteresis_bars` | 2 |
| `s1.trend_breakout_h4` | enabled. Donchian entry 55, exit 20. D1 TSMOM lookback 126 days (D1 bars aligned to 17:00 NY). ATR 20. Initial stop 2.5 ATR. Chandelier 3.0 ATR. Time stop 120 bars. `priceBound` 0.1 ATR. No new entries in EXTREME vol |
| `s2.mean_reversion_h1` | **shadow**. Gate: H1 RANGE, H4 ADX < 25, vol LOW/NORMAL. Entry: close beyond SMA20 ± 2.0σ and RSI14 < 30 / > 70. Stop 1.5 ATR14. TP = SMA20 (≥ 1R else skip). Time stop 24 bars. Spread ≤ 10% of stop |
| `s3.session_breakout_h1` | **shadow**. Asian range 00:00–06:59 UTC (width 0.3–1.5 × ATR14·√7). Entry window 07:00–11:59 UTC on an H1 close beyond range ± 0.1 ATR. Stop at the opposite side. TP 1.5R. Flat 16:00 UTC. One trade/pair/day. Pairs GBP_USD, EUR_USD, USD_JPY |

### 2.2 Risk

| Key | Default |
|---|---|
| `risk.per_trade_pct` | 0.50 paper/practice. **0.25 live phase 1**. Max 1.00 after multipliers |
| `risk.max_open_risk_pct` / `max_currency_risk_pct` / `max_cluster_risk_pct` | 2.0 / 1.0 / 1.0 (cluster: 60-day ρ_eff > 0.7) |
| `risk.max_positions` | 4 (3 in live phase 1). 1 per strategy×instrument. 2 per instrument |
| `risk.max_gross_leverage` | 5:1 (internal). Regulatory caps 30:1 majors / 20:1 minors used as upper bound |
| `risk.portfolio_vol_target_pct` | 10% annualized (tail overlay) |
| `risk.daily_loss_limit_pct` / `weekly_loss_limit_pct` | 2 / 4 (days start 17:00 NY) |
| `risk.dd_ladder` | −5% → ×0.75. −8% → ×0.5. −12% → halt (manual re-arm). −20% → kill switch |
| `risk.margin_closeout_guard` | halt + flatten at `marginCloseoutPercent ≥ 0.5` |
| `filters.spread_caps_pips` | EUR_USD 2.5, GBP_USD 3.0, USD_JPY 2.5, AUD_USD 3.0 (others 3.0–3.5). Also ≤ 2.5× hour-of-week median and ≤ 10% of stop |
| `filters.rollover_blackout_ny` | 16:45–17:30 |
| `filters.friday_cutoff_ny` | no entries after 15:00. S2/S3 flat by 15:30 |
| `filters.weekend_gap_budget_pct` | 1.0 (gap p99 ≈ 2× measured p95, e.g. ~70 pips EUR/USD) |
| `filters.news_blackout_min` | 30 before / 30 after high-impact events (affected currencies) |
| `filters.stale_price_sec` | 10 |

### 2.3 Learning

| Key | Default |
|---|---|
| `learning.min_events_to_train` | 300 per strategy (500 preferred). Bootstrap from historical backtest signals |
| `learning.cv` | PurgedKFold k=5, embargo = max(holding period, 1% of n). Walk-forward monthly |
| `learning.models` | champion = pass-through / LR(C=0.5). Challenger = HistGradientBoosting(depth 3, 8 leaves, min_leaf ≥ 50, lr 0.05, ≤ 300 iters). Calibrated |
| `meta.size_rule` | m_meta = clip((p̂ − p*) / 0.15, 0, 1). Skip if < 0.2. Never > 1 |
| `bandit` | discounted NIG Thompson, γ = 0.99, prior μ₀ = 0, κ₀ = 10, σ₀ = 1.5R. Cash arm. Clamp [0.5, 1.5]. Min 20 obs. Demote to shadow if P(μ > 0) < 0.10 after ≥ 50 trades |
| `drift` | P&L: PageHinkley(delta=0.15, threshold=60, alpha=0.999, mode="down") → warning. Model: ADWIN(0.002) on Brier error → retrain. Features: PSI > 0.25 on ≥ 3. Costs: PageHinkley up on realized − modeled cost |
| `promotion` | ≥ 3 months and ≥ 150 events in the evaluation window. Log-loss −1% with bootstrap CI > 0. Must beat pass-through. PBO < 0.3. 14-day shadow, 14-day cooldown, auto-rollback |
| `strategy promotion (shadow → live)` | ≥ 200 OOS trades / ≥ 2 years / ≥ 3 pairs. PSR(0) ≥ 0.95. DSR ≥ 0.90. Positive at 1.5× costs. No year/pair > 50% of R. Manual approval |

## 3. Things that should change the plan in `PROJECT_BRIEF.md`

1. **Broker availability (most important).** The brief assumes OANDA v20 for practice and live. Evidence:
   - a developer.oanda.com excerpt says the REST API is "available to all divisions except OANDA Global Markets and OANDA TMS BROKERS S.A.";
   - third-party lists say OANDA does not onboard residents of some African countries (e.g. Nigeria, South Africa).
   - **Proposal:** keep OANDA as primary for development and practice, add an explicit "broker availability check" to the user docs, and put a **cTrader Open API adapter** on the roadmap (after Stage 5, or as Stage 1b if the user confirms OANDA live API is unavailable to them). The `Broker` protocol needs capability flags (`01` §4).
2. **Ensemble defaults.** The brief lists trend, mean reversion and breakout as peers. The evidence (literature + our bid/ask checks: H1 mean reversion and squeeze breakout negative after costs on 4–5 of 5 datasets) does not support enabling all three. **Proposal:** add a first-class strategy **mode** `{disabled, shadow, live}`. Only the trend strategy defaults to `live`. Shadow strategies feed the learning system.
3. **Learning from closed trades alone is too slow.** Proving a +0.1R edge needs ~400–1,000 trades. **Proposal:** the learning stage labels *all* signals (historical, shadow, filtered) from market data. The bandit learns only from executed trades, with clamps.
4. **Backtester must reuse the live risk engine and record trial counts.** This is needed for DSR/PBO and for live/backtest parity (`06` §8).
5. **Data for local validation:** add a `fetch-validation` command for pinned GitHub datasets (`07` §3). The LEAN OANDA files are smoothed, so no gap analysis on them.
6. **Live phase-1 risk 0.25%** instead of reusing paper defaults. Exclude CHF pairs initially (SNB 2015 gap risk).
7. **Dependencies:** add `river` (drift detection, Python ≥ 3.11 is satisfied). `lightgbm` is optional (needs OpenMP runtime in Docker). DSR/PSR need only `statistics.NormalDist` from the standard library (`cdf`, `inv_cdf`), so no SciPy dependency is required.
8. **Decision bars should come from the candles endpoint, not from stream ticks** (affects `ARCHITECTURE.md` §3.1 "Bar builder").
   - OANDA's pricing stream sends at most 4 prices per second per instrument: only the last price in each 250 ms window, with windows not aligned across connections (`02` §5).
   - Bars aggregated from the stream therefore have different highs/lows than OANDA's candles, which are what backtests use. That breaks live/backtest parity.
   - **Proposal:** at each bar boundary + 2–5 s, fetch the just-closed candle(s) with `price=BA` and use only `complete=true` candles for decisions. The stream feeds monitoring, stale-price checks, spread filters and paper-broker fills.
9. **Candle model needs bid/ask sides** (affects the `Candle` dataclass).
   - Long stops trigger on the bid and short stops on the ask (`02` §6.10, `06` §2). Mid OHLC plus close spread under-states stop-outs and entry costs by half a spread.
   - **Proposal:** store bid and ask OHLC (as OANDA returns them with `price=BA`) and derive mid. If only mid is kept, store the spread at open *and* close and apply ±spread/2 to high/low checks.
10. **Regime enum vs 2-D regime.** `ARCHITECTURE.md` has one enum (`TRENDING`, `RANGING`, `HIGH_VOLATILITY`, `UNDEFINED`). The research uses trend label × volatility bucket (`03` §5.1). Suggested mapping:
    - `HIGH_VOLATILITY` = EXTREME vol (no new entries);
    - `TRENDING` = TREND;
    - `RANGING` = RANGE;
    - add a `NEUTRAL` value for the in-between state instead of overloading `UNDEFINED` (which means warm-up).
    The allocator can key its cells by (regime, vol bucket) internally.

## 3b. MetaTrader 5 update (after the user's answer: Cameroon + MT5)

Details and sources in [`08-metatrader5.md`](08-metatrader5.md).

1. **Deployment:** one **Windows VPS** near the broker's servers runs the MT5 terminal, a minimal **mt5-bridge** (Windows Python, owns the `MetaTrader5` module, single worker thread, allow-listed HTTP API on **127.0.0.1 only**, bearer token, idempotency store), and our backend **natively on Windows** (no Docker).
   - The user's PC in Cameroon is only a browser. This keeps the grid's documented outages out of the trading path.
   - Do not use the Wine/RPyC images for live: `mt5linux` uses RPyC classic mode (remote code execution) and common images publish it unauthenticated on `0.0.0.0`.
   - MQL5's own VPS cannot run Python.
   - MetaApi requires handing over the master password.
2. **Brokers (opinion, verify first):**
   - **Exness** (Mobile Money reported for Cameroon, Seychelles entity);
   - **IC Markets or Pepperstone** (raw-spread MT5, offshore entity, no confirmed Mobile Money);
   - **HFM** as an alternative.
   - All serve Cameroon via **offshore** entities. COSUMAF does not license them, and BEAC transfer rules apply to funding.
   - The user follows the verification checklist in `08` §C.5 (regulator register, demo specs, small deposit → withdrawal test).
3. **Design rules the backend must honour:**
   - Treat all MT5 timestamps as **broker server clock** (detect the rule, usually New York + 7 h).
   - Build H4/D1 ourselves from H1 in UTC.
   - Ask = bid + `max(bar min-spread, spread profile)`. Plain bid + bar spread under-states the ask high by a median of 0.3–0.5 pip, p99 2.5–3.4 pips in our check.
   - **Require a hedging account** (`margin_mode = 2`), and always send the `position` ticket when closing or modifying.
   - Idempotency via `magic` + a ≤ 25-char hashed `comment`, with reconcile-before-retry on ambiguous retcodes (10012/10031/10011/`None`).
   - Server-side SL/TP plus our own SL moves via `TRADE_ACTION_SLTP` (MT5's trailing stop is client-side).
   - Symbol mapping by `currency_base/profit` + `trade_calc_mode`.
   - A faithful fake `MetaTrader5` module for Linux CI.
4. **New risk default: minimum equity.** MT5's 0.01-lot step (1,000 units) means the H4 trend trade on EUR/USD (≈ 60-pip stop) risks at least USD 6. That needs **≥ USD 1,200 at 0.5% risk and ≥ USD 2,400 at 0.25%**. The risk engine must compute this from live symbol specs, skip trades it cannot size, and show it on the dashboard.

## 4. Honest expectations

### 4.1 What happens to retail FX/CFD traders (evidence)

- **ESMA (2018):** national regulators' analyses found **74–89% of retail CFD accounts lose money**, with average losses per client of €1,600–€29,000. This led to the EU leverage caps (30:1 majors), the 50% margin close-out, negative balance protection and the mandatory risk warning. https://www.esma.europa.eu/sites/default/files/library/esma71-98-128_press_release_product_intervention.pdf , https://www.fca.org.uk/publication/consultation/cp18-38.pdf
- **Mandatory broker disclosures** (snapshot figures quoted by comparison sites in 2026. They change quarterly, so check the broker's current page): OANDA ~76.6%, Pepperstone ~79.6%, IG ~69% of retail CFD accounts lose money. https://www.forexbrokers.com/compare/oanda-vs-pepperstone , https://www.theinvestorscentre.co.uk/reviews/ig-vs-oanda/
- **Day trading for a living:** Chague, De-Losso & Giovannetti (2019): of Brazilian individuals who day-traded equity futures for more than 300 days, **97% lost money**, and only 1.1% earned more than the minimum wage. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101
- **Counterpoint:** Abbey & Doukas (2015, JIMF) found that a sample of 428 individual currency-trader accounts (2004–2009) earned positive abnormal returns on average after costs. Skilled minorities exist, but the base rate is losing. https://ideas.repec.org/a/eee/jimfin/v56y2015icp158-177.html

### 4.2 Why no system can guarantee continuous profit

- **Prices are close to unpredictable at short horizons.** Published FX rule profits faded after they became known (Neely, Weller & Ulrich 2009). Intraday rules did not survive realistic costs in the tested sample (Neely & Weller 2003). Edges that remain are small, time-varying and crowded.
- **Costs are certain, edges are not.** Our measured EUR/USD spread (~1.3 pips) is 11% of a typical H1 bar range and 22% of an M15 range (`03` §2). One extra pip of cost erased the best result in our checks.
- **Statistics:** even a genuinely good strategy has many losing periods. Normal approximation, annual Sharpe S → P(losing month) = Φ(−S/√12), P(losing year) = Φ(−S):
  - S = 0.5: 44% losing months, 31% losing years;
  - S = 1.0: 39% losing months, 16% losing years.
  - "Profit every month" is not a realistic property of any honest system.
- **Losing streaks and drawdowns are normal.** With a 35% win rate, the median longest losing streak in 250 trades is 11. A trend-like system with a small positive edge at 0.5% risk per trade has a median maximum drawdown of ~14% over 250 trades (`04` §3.1).
- **Regimes change and tails are real:** the SNB removed the EUR/CHF floor in 2015, there was a 178-pip weekend gap in EUR/USD in 2017, and carry crashes happen. Stops do not protect against gaps.
- **Overfitting is the default outcome of strategy research.** Our best-looking configuration had PSR 0.98 but a deflated Sharpe of 0.47 after accounting for only 10 tried configurations (`06` §4.2).

### 4.3 Realistic targets (opinion, informed by the above)

- **Success** = positive net expectancy that survives walk-forward, cost stress and deflation. Live results stay inside the backtest's Monte-Carlo bands.
- Realistic net Sharpe for a small FX-majors trend system: **0 to 0.5**. Above ~0.7 sustained live would be exceptional. A single-pair backtest Sharpe above 1.5 is a red flag.
- At 0.5% risk per trade, our H4 trend checks produced roughly **−1% to +1% per year per pair**, with 6–14% maximum drawdowns per pair (16–17% for the 3-pair portfolio). Our vol-targeted daily TSMOM (10% vol per pair, 63/126/252-day lookbacks) produced roughly −3% to +6% per year with 17–53% drawdowns. Plan for **multi-year flat or losing stretches**.
- The dashboard must show these expectations next to live results (expected vs realized R distribution, drawdown percentile).

### 4.4 Why paper → practice → small live is the right rollout

| Phase | Purpose | Exit criteria (default) |
|---|---|---|
| **Paper** (local simulator) | Find bugs where they cost nothing: lookahead, sizing, netting, reconnects, breakers | ≥ 4 weeks running. Replaying the same bars through the backtester reproduces every paper trade exactly. All breakers and the kill switch exercised by fault-injection tests |
| **Practice** (MT5 demo at the chosen broker, or OANDA practice) | Real API, real quotes, real rejects (MT5 retcodes such as 10018/10030/10016, OANDA `MARKET_HALTED`), real reconciliation, server-time detection | ≥ 3 months and ≥ 30 trades. Zero unprotected positions. Zero unresolved reconciliation diffs. Median fill vs modeled price within 0.3 pip. Cost model within tolerance. **Profit is not an exit criterion**: 3 months is statistically meaningless |
| **Small live** | Real fills, real financing, real psychology | 0.25% risk/trade, ≤ 3 positions, capital the user can afford to lose entirely. On MT5 the 0.01-lot step means roughly ≥ USD 2,400 is needed for the H4 trend strategy at 0.25% (`08` §D.8); with less, the system will (correctly) skip most trades. Scale up only after ≥ 100 live trades with results inside the backtest's Monte-Carlo bands and no operational incidents. Live mode requires `ALLOW_LIVE_TRADING=true` and an explicit config confirmation (brief principle 1) |

Reasons:

- Early losses in automated trading come mostly from **software and operational errors**, not from the strategy, and those are found cheaply in paper/practice.
- Demo fills can differ from live, and only small live trading measures real slippage and financing (**UNVERIFIED** in degree for OANDA practice vs live).
- Gradual scaling keeps a broken assumption from becoming a large loss.

## 5. Method notes

- Primary sources for the OANDA spec came from GitHub (official OpenAPI spec and SDKs, recorded test fixtures), because developer.oanda.com is blocked from the build container.
- Our own computations used two public datasets on GitHub (QuantConnect LEAN OANDA bid/ask H1 2007–2018, ejtraderLabs MT5 H1 2012–2022). The simulator conventions are described in `03` §4. They are sanity checks, not validated results. Any decision-driving number must be reproduced in the project's own backtester (brief principle 2).
