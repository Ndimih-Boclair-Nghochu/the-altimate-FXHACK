# 03 — FX strategy evidence review and recommended ensemble

Status: research input for Stage 2 (indicators, regime, strategies, backtester).

**Summary.**

- The best-documented FX edge available to a retail system is **slow trend following / time-series momentum** (daily to multi-week horizons, volatility-scaled).
- Edges at intraday horizons (M15/H1) in major pairs are thin and **cost-dominated**. Most published intraday rules lose their excess return once realistic costs are applied.
- Our own quick, unoptimized checks on real bid/ask data reproduce this. Simple H1 mean-reversion and squeeze-breakout rules lost money after spread, H4/D1 trend rules were roughly break-even per pair, and a vol-targeted daily TSMOM was the only family with a consistently (slightly) positive Sharpe (§4).
- Recommendation: ship one **core trend strategy enabled by default**, plus mean-reversion and session-breakout strategies that run in **shadow mode** (signals logged and labelled, no orders) until they pass the walk-forward gates in `06-backtesting-pitfalls.md`.

Evidence and opinion are separated: **Evidence** = published research or our reproducible
computation. **Opinion** = engineering judgement.

---

## 1. Literature evidence

### 1.1 Time-series momentum (trend following)

- **Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", JFE 104(2):228–250.** Study of 58 liquid futures (equity indices, **currencies**, commodities, bonds), 1985–2009. Strategy: go long (short) if the instrument's own past 12-month excess return is positive (negative), scale positions to a constant ex-ante volatility, hold 1 month. Findings: returns persist for 1–12 months and partially reverse over longer horizons. A diversified TSMOM portfolio "yields a Sharpe ratio greater than one on an annual basis, or roughly 2.5 times the Sharpe ratio for the equity market portfolio" (paper text), and it performs best in extreme markets. Note this is **diversified across ~58 instruments and 4 asset classes**. A single FX pair cannot be expected to reach that. https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf
- **Hurst, Ooi & Pedersen (2017), "A Century of Evidence on Trend-Following Investing", JPM.** Trend following was positive in every decade they examined, across asset classes. (Cited for persistence of the phenomenon. No FX-specific numbers are used here.)
- **Menkhoff, Sarno, Schmeling & Schrimpf (2012), "Currency Momentum Strategies", JFE 106(3):660–684.** *Cross-sectional* currency momentum: up to ~10% p.a. spread between past winners and losers. But "very effective limits to arbitrage": high time variation, concentration in currencies with high idiosyncratic volatility and in risky countries, and partial explanation by transaction costs. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1988679
- **Neely, Weller & Ulrich (2009), "The Adaptive Markets Hypothesis: Evidence from the Foreign Exchange Market", JFQA.** True out-of-sample tests of previously published rules. FX technical profits of the 1970s–80s were genuine, but **had disappeared by the early 1990s for filter and moving-average rules**. Less-studied rules also declined. https://www.researchgate.net/publication/46543368
- **Neely & Weller (2003), "Intraday technical trading in the foreign exchange market", JIMF 22(2):223–237.** Genetic-programming and linear forecasting rules on intraday data: **no excess returns once realistic transaction costs and trading hours are included**. https://ideas.repec.org/a/eee/jimfin/v22y2003i2p223-237.html
- **Hsu, Taylor & Wang (2016), "Technical trading: Is it still beating the foreign exchange market?", JIE 102:188–208.** More than 21,000 rules, 30 currencies, 45 years, with a stepwise test against data snooping. Finds significant predictability in developed and emerging currencies, varying strongly across sub-periods and groups. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2765673

**Takeaway (evidence):** trend persistence is real at multi-week horizons and best harvested across many instruments with volatility scaling. Simple, well-known FX rules on major pairs have weakened since the 1990s, and intraday versions do not survive costs in the cited study.

### 1.2 Carry

- **Brunnermeier, Nagel & Pedersen (2008), "Carry Trades and Currency Crashes", NBER Macro Annual.** Carry portfolios have high Sharpe ratios but **negative skewness and fat tails**: crashes happen when funding liquidity and risk appetite fall. https://www.nber.org/system/files/working_papers/w14473/w14473.pdf
- **Daniel, Hodrick & Lu (2017), "The Carry Trade: Risks and Drawdowns", Critical Finance Review 6.** Large drawdowns. https://www.nber.org/system/files/working_papers/w20433/w20433.pdf
- **Hsu, Taylor, Wang & Li (2024), "The out-of-sample performance of carry trades", JIMF 143.** Carry strategies chosen as profitable in one period are generally not profitable in the next. Success is "mainly due to luck", even with learning and stop-losses. Consistent profitability is confined to **1998–2005**. https://ideas.repec.org/a/eee/jimfin/v143y2024ics0261560624000299.html
- **Koijen, Moskowitz, Pedersen & Vrugt (2018), "Carry", JFE.** Carry predicts returns across asset classes (general reference). https://jacobslevycenter.wharton.upenn.edu/wp-content/uploads/2014/06/Carry.pdf

**Takeaway:** do **not** build a stand-alone carry strategy. A retail CFD account also pays the broker's financing markup, so the carry captured is smaller than the interest differential. Use financing as a **cost input** in sizing and backtests, and as an optional tie-breaker (avoid holding multi-week trend trades whose financing cost is large relative to the expected move).

### 1.3 Mean reversion in ranging regimes

- No strong peer-reviewed evidence was found that simple indicator-based fades (Bollinger/RSI) are profitable net of costs in major FX pairs at H1. The intraday study above (Neely & Weller 2003) finds no excess returns after costs for the intraday rules it tested.
- Intraday momentum/reversal effects exist in some FX markets (e.g. Elaut, Frömmel & Lampaert on RUB/USD exchange data: first-half-hour predicts last-half-hour return). That is a market-microstructure effect on exchange data, not a retail OTC edge. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2694985
- **Our check (§4):** a textbook H1 Bollinger(20, 2σ) fade filtered by ADX < 20 **lost** on all five datasets after spread (Sharpe −0.4 to −1.9), and was roughly zero *before* costs on EUR/USD.

**Takeaway:** implement mean reversion because the brief asks for it and because it is a plausible regime-specific component, but **keep it in shadow mode by default**.

### 1.4 Breakouts (Donchian, range/session breakouts)

- Donchian channel breakouts are the classic trend-follower entry (the "Turtle" rules: 20/55-day breakouts, N = 20-day ATR). This is practitioner literature, not peer-reviewed. Conceptually it is a time-series-momentum entry rule, so §1.1 applies.
- Opening-range / session breakouts (Asian range → London open) are widely used by practitioners. No peer-reviewed FX evidence was found. **Our check (§4):** mixed. Positive on GBP/USD and USD/JPY 2012–2022 at base costs, negative on EUR/USD and on OANDA 2007–2018 data. It **disappears with +1 pip extra cost**, and the yearly R was negative in 2018, 2019 and 2021. That is an edge too fragile to trade live without much more validation.
- Volatility-contraction ("squeeze") breakouts: volatility clustering is one of the most robust facts in finance (ARCH/GARCH, Engle 1982, Bollerslev 1986), so low volatility predicts *higher future volatility*, but **not its direction**. Our H1 squeeze test was negative after costs on 4/5 datasets.

### 1.5 Regime filters

- **ADX** (Wilder 1978, *New Concepts in Technical Trading Systems*): directional-movement strength. Conventional thresholds are ADX < 20 = weak trend / range and ADX > 25 = trend. These are conventions, not estimated parameters.
- **Kaufman Efficiency Ratio** ER(n) = |C_t − C_{t−n}| / Σ_{i=t−n+1..t}|C_i − C_{i−1}| ∈ [0, 1]. 1 = straight line, ≈ 0 = noise (Kaufman, *Trading Systems and Methods*). Cheap, bounded, interpretable.
- **ATR percentile** (current ATR vs its trailing distribution): a volatility-regime proxy that exploits volatility clustering.
- **Hurst exponent / variance ratio** (Lo & MacKinlay 1988): statistically noisy on the short windows needed for trading decisions. Use as a **feature for the meta-model**, not as a hard gate.
- Evidence that these filters improve FX strategy returns is largely practitioner/anecdotal. They are recommended mainly as **risk controls** (avoid fading strong trends, avoid trading in extreme volatility), and their usefulness is tested by the meta-labeling layer (`05-adaptive-learning.md`).

## 2. Timeframes and pairs

**Evidence (our computation, `07-data-sources.md` datasets):** cost relative to typical bar range, EUR/USD, median true range from 2012–2022 hourly data (resampled), with an assumed all-in spread of 1.3 pips (the median OANDA EUR/USD spread we measured in 2007–2018 bid/ask data was 1.2–1.4 pips):

| Timeframe | Median true range (pips) | Spread as % of median bar range |
|---|---|---|
| M15 | 5.8 | **22%** |
| H1 | 12.0 | 11% |
| H4 | 25.4 | 5.1% |
| D1 | 75.0 | 1.7% |

A strategy whose stop is ~1.5 bars of range pays roughly 0.15 R per round trip in spread at M15, but ~0.01 R at D1. **Opinion:** do not trade M15 initially. Use **H4 for the core strategy, D1 for direction filters, and H1 only for shadow candidates.** M15 may be used for execution timing later.

Spread by hour (evidence, OANDA EUR/USD H1 bid/ask 2007–2018, median spread at bar open by New York hour): 1.2–1.3 pips for most of the day, **2.5 pips at 17:00 NY and 2.1 at 18:00 NY** (daily rollover), 1.6 at 19:00 NY. NZD/USD: 2.2–2.5 pips most hours, **5.0 pips at 17:00–18:00 NY**. Hence the rollover blackout in `04-risk-management.md`.

**Pairs (opinion, cost-driven):** start with the four most liquid majors: **EUR_USD, GBP_USD, USD_JPY, AUD_USD**. Add USD_CAD, USD_CHF, NZD_USD once the system is stable. The diversification benefit of more pairs is limited because USD-based majors are correlated, hence the correlation/currency exposure limits in `04`.

## 3. Realistic performance ranges

| Context | Realistic annualized Sharpe (net) | Basis |
|---|---|---|
| Diversified multi-asset trend portfolio, institutional costs | historically > 1 in 1985–2009 (MOP 2012), lower out of sample | MOP 2012 |
| FX-only trend, a handful of majors, retail costs | **≈ 0 to 0.5** | Our checks (§4), decline documented by Neely et al. 2009 |
| Single-pair intraday rule, retail costs | **≈ −1 to +0.3** | Neely & Weller 2003, our checks |
| Anything with backtest Sharpe > 1.5 on 1–3 FX pairs | treat as **overfit until proven** (DSR/PBO) | `06-backtesting-pitfalls.md` |

These ranges are opinion informed by the cited evidence. The system must not promise more.

## 4. Our sanity-check backtests (evidence, reproducible, unoptimized)

Purpose: calibrate expectations and catch "too good to be true" results later. **Not** a validation of profitability.

- **Data:** QuantConnect LEAN repo OANDA H1 bid+ask, EUR/USD and NZD/USD, 2007-01-01 → 2018-12-31 (real spreads). ejtraderLabs MT5 H1 (bid only + fixed spread 1.3/1.6/1.4 pips), EUR/USD, GBP/USD, USD/JPY, 2012-11 → 2022-03. Details in `07-data-sources.md`.
- **Simulation:** signals on closed bars only. Market fills at the next bar open on the correct side (ask for buys, bid for sells). Stops checked intrabar against bid lows (long) / ask highs (short). Gaps fill at the open. On the entry bar, stops are not checked intrabar (path unknown); exit only if the bar closes beyond the stop. Financing not included. Risk 0.5% of equity per trade, compounding.
- **Parameters:** chosen *a priori* from common practice, not tuned. In total **7 rule families × up to 3 variants were run** (≈ 12 configurations), so any best result here is subject to selection bias (see deflated Sharpe in `06`).

| Strategy (timeframe) | Per-dataset Sharpe range (5 datasets) | 3-pair portfolio Sharpe, MT5 2012–22 | Avg R / trade range |
|---|---|---|---|
| Donchian 55/20 + EMA50/200 filter, 2.5 ATR stop, 3 ATR trail (H4) | −0.23 … +0.22 | +0.01 | −0.09 … +0.09 |
| Same with **D1 TSMOM(126) direction filter** (H4) | −0.29 … +0.34 | **+0.23** | −0.08 … +0.13 |
| Same rules on D1 | −0.52 … +0.19 | n/a (3–4 trades/yr) | −0.32 … +0.26 |
| **TSMOM daily, sign of 126-day return, 10% vol target, weekly rebalance** | −0.18 … +0.55 | **+0.33** | n/a |
| TSMOM 63-day / 252-day lookback | −0.28 … +0.46 / −0.09 … +0.12 | +0.33 / +0.11 | n/a |
| H1 Bollinger(20,2) fade when ADX(14) < 20, exit at SMA20 / 24 bars / 1.5 ATR stop | **−1.95 … −0.42** | n/a | −0.22 … −0.06 |
| H4 RSI(2) pullback in D1 TSMOM direction | −1.10 … +0.13 | −0.14 | −0.08 … +0.01 |
| H1 volatility squeeze breakout (BB width ≤ 20th pct, 24-bar range stop-entry, 1 ATR stop, 2R TP) | −1.53 … +0.13 | n/a | −0.22 … +0.02 |
| H1 Asian-range → London breakout (stop-entry 07:00–12:00 UTC, stop = range, TP 1.5R, flat 16:00 UTC) | −0.52 … +0.79 | +0.55 → **+0.32 with +0.5 pip, −0.03 with +1 pip** | −0.04 … +0.07 |

Observations:

1. Costs matter enormously at H1. The mean-reversion rule is ≈ 0 R before costs and clearly negative after.
2. Slow trend (D1 TSMOM, H4 breakout with a D1 trend filter) is the only family that is not negative on the 3-pair portfolio. Its edge is small (Sharpe ~0.2–0.3) and comes with long flat/drawdown periods.
3. The London breakout's portfolio result is the "best" number in the table. It is also the most cost-sensitive and its yearly results decay (yearly sum of R: 2013 +64, 2014 +40, 2018 −18, 2019 −17, 2021 −17). It is the kind of result that most often fails out of sample.
4. **A simulator bug changed the squeeze result from about −0.03 R to −0.9 R per trade** (checking the stop against the full range of the bar in which a stop-entry fired). Same-bar ambiguity handling is a top-priority backtester test (`06`).

The scripts are kept outside the repo (research scratch). The rules above are specified precisely enough to re-implement in the project backtester, which is where any number that drives a decision must come from (brief principle 2).

## 5. Recommended ensemble (defaults)

Common definitions (all computed on **mid** prices of **closed** bars. Fills use bid/ask):

- `ATR(n)`: Wilder ATR (EMA with α = 1/n) of true range.
- `ADX(14)`: Wilder.
- `ER(n)`: Kaufman efficiency ratio.
- `ATRpct`: percentile rank of ATR(14)/close over the trailing **120 trading days** of the same timeframe (H1: 2,880 bars. H4: 720 bars).
- `TSMOM126`: sign of ln(C_d / C_{d−126}) on **D1 bars aligned to 17:00 New York**. Value for day d is usable from the D1 close of day d onward.

### 5.1 Regime classifier (per instrument, per timeframe)

| Label | Rule (defaults) |
|---|---|
| `TREND` | ADX(14) ≥ 25 **and** ER(20) ≥ 0.30 |
| `RANGE` | ADX(14) < 20 **and** ER(20) < 0.20 |
| `NEUTRAL` | otherwise |
| Volatility: `LOW` / `NORMAL` / `HIGH` / `EXTREME` | ATRpct < 0.25 / 0.25–0.75 / 0.75–0.95 / ≥ 0.95 |

Composite regime key = `(trend_label, vol_label)` (12 cells). It is used by the gating table below and by the bandit allocator (`05`). Add hysteresis to avoid flapping: a label must hold for 2 consecutive closed bars before it switches. **Opinion:** thresholds are conventional. Treat them as config, not as tuned constants.

Mapping to the single `Regime` enum in `ARCHITECTURE.md`:

| Enum value | Research label |
|---|---|
| `HIGH_VOLATILITY` | vol `EXTREME` (takes precedence) |
| `TRENDING` | `TREND` |
| `RANGING` | `RANGE` |
| (proposed new value) `NEUTRAL` | `NEUTRAL` |
| `UNDEFINED` | warm-up only |

Keep the vol bucket in `RegimeState.inputs` so the allocator can still key cells by (regime, vol bucket).

### 5.2 S1 `trend_breakout_h4` (core, **enabled by default**)

| Item | Rule / default |
|---|---|
| Timeframe | H4 (bars aligned to 17:00 NY day boundary: 17, 21, 01, 05, 09, 13 NY) |
| Long entry | H4 close > highest high of previous **55** H4 bars **and** `TSMOM126 = +1` |
| Short entry | H4 close < lowest low of previous **55** H4 bars **and** `TSMOM126 = −1` |
| Order | market at next bar open (live: immediately after bar close + data check), `priceBound` = 0.1 × ATR |
| Initial stop | **2.5 × ATR(20)** from entry |
| Trailing stop | chandelier: best close since entry ∓ **3.0 × ATR(20)**, updated on each H4 close, never loosened |
| Exit signal | close crosses the opposite **20-bar** Donchian channel → exit at next open |
| Take profit | none (let winners run). Optional `takeProfitOnFill` at 6R as a disaster-cap only |
| Time stop | 120 H4 bars (~20 trading days) without new high-water mark → exit |
| Regime gating | allowed in `TREND`/`NEUTRAL` × `LOW`/`NORMAL`/`HIGH`. **No new entries in `EXTREME` vol.** Not gated by `RANGE` (a breakout ends a range by definition), but the meta-model sees the regime |
| Re-entry | after an exit, wait for a fresh 55-bar breakout |
| Expected frequency | ~17–20 trades/yr per pair (§4) |

### 5.3 S2 `mean_reversion_h1` (**shadow mode by default**)

| Item | Rule / default |
|---|---|
| Timeframe | H1 |
| Regime gate | `RANGE` on H1 **and** H4 ADX(14) < 25 **and** vol ∈ {`LOW`, `NORMAL`} |
| Long entry | close < SMA(20) − **2.0** σ(20) **and** RSI(14) < 30 |
| Short entry | close > SMA(20) + 2.0 σ(20) **and** RSI(14) > 70 |
| Stop | **1.5 × ATR(14)** beyond entry |
| Take profit | SMA(20) at signal time (mid-band), or at least 1.0R. Skip the trade if the distance to the mid-band < 1.0 × stop distance (poor payoff) |
| Time stop | 24 H1 bars |
| Session filter | no entries 16:00–19:00 NY (rollover) and in the 30 min around high-impact news |
| Cost filter | skip if spread > 10% of stop distance |
| Promotion to live | only after passing the gates in `06` §6 on walk-forward data |

### 5.4 S3 `session_breakout_h1` (**shadow mode by default**)

| Item | Rule / default |
|---|---|
| Timeframe | H1 (UTC clock) |
| Range | Asian session high/low from 00:00 to 06:59 **UTC** |
| Validity | range width between 0.3× and 1.5× of ATR(14,H1) × √7 (skip abnormal days) |
| Entry | at 07:00–11:59 UTC, first H1 close above range high + 0.1 ATR → long. Below range low − 0.1 ATR → short. One trade per pair per day |
| Stop | opposite side of the range (risk = range width + buffers). Cap the risk at 1.5 × ATR(14,H1) × √7, else skip |
| Take profit | **1.5 R** |
| Exit | flat by **16:00 UTC** regardless |
| Regime gate | vol ∈ {`LOW`, `NORMAL`, `HIGH`}. No entries on days with a high-impact event for either currency between 07:00 and 12:00 UTC |
| Pairs | GBP_USD, EUR_USD, USD_JPY (London-active pairs) |
| Promotion to live | only after passing `06` §6 gates. Cost sensitivity test at +1 pip **must** stay positive |

Note: §4 used stop-entry orders inside the bar. The live version above uses closed-bar confirmation (no intrabar orders), which is easier to keep in parity between live and backtest. Re-run the backtest with these exact rules before any promotion.

### 5.5 Enablement matrix (defaults)

| Strategy | Mode default | TREND | NEUTRAL | RANGE | EXTREME vol |
|---|---|---|---|---|---|
| S1 trend_breakout_h4 | **live-eligible** (paper → practice) | ✅ | ✅ | ✅ (breakouts only) | ❌ new entries |
| S2 mean_reversion_h1 | shadow | ❌ | ❌ | ✅ | ❌ |
| S3 session_breakout_h1 | shadow | ✅ | ✅ | ✅ | ❌ |

"Shadow" means the strategy computes signals, the journal stores them with all features, and the labeler computes triple-barrier outcomes from market data (`05`). No orders. This gives the learning system data without risking capital, and an honest out-of-sample track record for promotion.

### 5.6 Things deliberately left out

- Stand-alone carry (§1.2), grid/martingale/averaging-down (unbounded risk), news trading (spread/slippage), M15 scalping (costs, §2), ML price-direction prediction as a primary signal (low signal-to-noise. ML is used for **meta-labeling** only, `05`).

## 6. Sources

- Moskowitz, Ooi, Pedersen (2012) JFE: https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf ; SSRN https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463
- Hurst, Ooi, Pedersen (2017) "A Century of Evidence on Trend-Following Investing", Journal of Portfolio Management (AQR).
- Menkhoff, Sarno, Schmeling, Schrimpf (2012) JFE: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1988679 , VoxEU summary https://cepr.org/voxeu/columns/limits-currency-momentum-trading
- Neely, Weller, Ulrich (2009) JFQA: https://www.researchgate.net/publication/46543368_The_Adaptive_Markets_Hypothesis_Evidence_from_the_Foreign_Exchange_Market ; St. Louis Fed overview https://files.stlouisfed.org/files/htdocs/wp/2011/2011-001.pdf
- Neely, Weller (2003) JIMF: https://ideas.repec.org/a/eee/jimfin/v22y2003i2p223-237.html
- Hsu, Taylor, Wang (2016) JIE: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2765673
- Brunnermeier, Nagel, Pedersen (2008): https://www.nber.org/system/files/working_papers/w14473/w14473.pdf
- Daniel, Hodrick, Lu (2017): https://www.nber.org/system/files/working_papers/w20433/w20433.pdf
- Hsu, Taylor, Wang, Li (2024) JIMF: https://ideas.repec.org/a/eee/jimfin/v143y2024ics0261560624000299.html
- Koijen, Moskowitz, Pedersen, Vrugt "Carry": https://jacobslevycenter.wharton.upenn.edu/wp-content/uploads/2014/06/Carry.pdf
- Bekaert & Panayotov "Good Carry, Bad Carry": https://www.nber.org/system/files/working_papers/w25420/w25420.pdf
- Elaut, Frömmel, Lampaert "Intraday Momentum in FX Markets": https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2694985
- Wilder (1978) *New Concepts in Technical Trading Systems* (ADX, ATR). Kaufman *Trading Systems and Methods* (efficiency ratio). Engle (1982) Econometrica (ARCH). Bollerslev (1986) J. Econometrics (GARCH). Lo & MacKinlay (1988) RFS (variance ratio).
- Datasets for §2/§4: see `07-data-sources.md`.
