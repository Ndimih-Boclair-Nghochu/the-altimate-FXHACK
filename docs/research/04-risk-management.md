# 04 — Risk management: methods and concrete defaults

Status: research input for Stage 3 (risk engine). Every order passes through this engine. The
risk engine can only **reduce or veto** what strategies and the learning system ask for.

**Summary of defaults.**

| Control | Default |
|---|---|
| Risk per trade | 0.5% of equity (paper/practice), **0.25% for the first live phase** |
| Stops | ATR-based, set **on fill** |
| Max open risk | 2% |
| Max same-currency risk | 1% |
| Daily loss halt | −2% |
| Weekly loss halt | −4% |
| Drawdown ladder | −5% → ×0.75, −8% → ×0.5, −12% → halt (manual review), −20% → flatten (kill switch) |
| Internal leverage cap | 5:1 gross, always below the regulatory 30:1/50:1 |
| Time-based blackouts | rollover 16:45–17:30 NY, Friday after 15:00 NY, news ±30 min |

---

## 1. Layered design

1. **Pre-trade checks** (per order): sizing, stop validity, spread/liquidity/session/news filters, stale-price guard, margin check.
2. **Portfolio checks**: open risk, per-currency and correlated-cluster risk, gross leverage, max positions, weekend gap budget.
3. **Account circuit breakers**: daily/weekly loss limits, drawdown ladder, margin-closeout guard.
4. **Kill switch** (manual or automatic): cancel pending orders, close all positions, halt new orders, persist state, require manual re-arm.

Every veto is journaled with a reason code, so the dashboard can show "why didn't it trade".

## 2. Position sizing

### 2.1 Fixed-fractional risk (primary)

Risk a fixed fraction *r* of current equity *E* between entry and stop:

```
risk_home        = E × r × m_strategy × m_meta × m_drawdown        # multipliers ≤ 1.5, see below
loss_per_unit    = |entry − stop| × QHC                             # in home currency
units            = floor_to_step( risk_home / loss_per_unit )
```

- `QHC` (quote → home conversion). With OANDA use `quoteHomeConversionFactors.negativeUnits` from the pricing endpoint (the factor for losses, `02` §6.5). Otherwise:
  - EUR_USD on a USD account: QHC = 1.
  - USD_JPY on a USD account: QHC = 1 / USDJPY.
  - EUR_GBP on a USD account: QHC = GBPUSD.
- Use the **ask** for long entries and the **bid** for short entries when computing `|entry − stop|`, and add the expected exit half-spread. That way 1R is the *all-in* loss.
- Round units **down** to `tradeUnitsPrecision`. If `units < minimumTradeSize`, skip the trade. Never round up the risk.
- Multipliers (all clamped):
  - `m_strategy` ∈ [0.5, 1.5] from the bandit allocator (`05` §6). A strategy the allocator demotes goes to shadow mode, so it gets no order at all.
  - `m_meta` ∈ [0, 1] from the meta-model. The meta-model can only shrink a trade.
  - `m_drawdown` ∈ {1, 0.75, 0.5, 0} from the drawdown ladder (§4).
  - The product is then capped so that `r × product ≤ r_max = 1.0%`.

With an ATR stop, fixed-fractional sizing is automatically **volatility-normalized**: units ∝ 1/ATR. Each trade risks the same fraction regardless of the pair's volatility.

### 2.2 Volatility targeting (portfolio overlay)

Evidence: Harvey et al. (2018), "The Impact of Volatility Targeting", JPM 45(1). Vol targeting raises Sharpe ratios for equities and credit, but for **currencies, bonds and commodities the Sharpe impact is negligible**. It does **reduce the likelihood of extreme (left-tail) returns across all asset classes**. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3175538

Recommendation: use vol targeting as a **tail-risk overlay**, not as a return enhancer.

- Estimate the ex-ante portfolio volatility of the *open* positions from a 60-trading-day EWMA covariance (λ ≈ 0.97) of daily mid returns × position notionals.
- If the estimated annualized portfolio vol exceeds **10%** of equity, scale down new entries (and optionally existing positions) by `10% / vol_est`.

### 2.3 Kelly and fractional Kelly (cap only)

- For a repeated bet with win probability *p* and payoff ratio *b* (average win R / average loss R), the Kelly fraction is f* = p − (1 − p)/b. For continuous returns f* ≈ μ/σ².
- Fractional Kelly c·f* gives long-run growth g(c) = c(2 − c)·g*. **Half Kelly keeps 75% of the growth with half the volatility.** This is a mathematical identity for the log-optimal growth approximation, see Thorp (2006) and MacLean, Thorp & Ziemba (2010).
- In practice *p* and *b* are estimated with large error. With realistic FX edges (§3 of `03`: average R per trade ≈ 0.0–0.15), the estimation error is of the same order as the estimate.

Recommendation (opinion): **never size by Kelly.** Compute, per strategy and after ≥ 100 closed trades (live + shadow), the Kelly fraction using the **lower 80% confidence bound** of expectancy. Then enforce `r_effective ≤ 0.25 × f*_lower`. If `f*_lower ≤ 0`, the strategy is demoted to shadow mode (the allocator's job, `05`).

### 2.4 Sizing example (EUR_USD, USD account)

E = 10,000 USD, r = 0.5% → 50 USD. Long at ask 1.08520. ATR(20,H4) = 0.00240 → stop = 1.08520 − 2.5×0.00240 = 1.07920 (60 pips). Exit half-spread allowance 0.6 pip → loss/unit = 0.00606 USD → units = floor(50 / 0.00606) = 8,250 units (OANDA allows 1-unit steps. A 1,000-unit-step broker would round down to 8,000).

## 3. Stops, R-multiples and exits

- **R-multiple**: R = (exit − entry) × side / |entry − initial_stop|, net of costs. Every trade in the journal stores initial R-risk, realized R, MAE/MFE in R, costs in R. All learning and evaluation uses R (`05`).
- **ATR stops**: initial stop k × ATR(n) from entry (S1: 2.5 × ATR(20) H4. S2: 1.5 × ATR(14) H1). The stop is attached to the order **on fill** (`stopLossOnFill`) so there is never an unprotected position.
- **Stop validity checks** before sending an order:
  - stop distance ≥ max(5 × current spread, broker minimum distance);
  - stop distance ≤ the distance that would make `units < minimumTradeSize`;
  - for OANDA, the stop must not be inside the current spread, else cancel reason `STOP_LOSS_ON_FILL_LOSS`.
- **Trailing**: chandelier (best close since entry ∓ 3 × ATR) on bar close, never loosened, sent with `PUT /trades/{id}/orders` (`02` §6.10).
- **Break-even rule (opinion)**: moving the stop to break-even early cuts the right tail that trend strategies depend on. Defaults:
  - S1: no break-even rule, the chandelier trail only.
  - S2/S3: move the stop to entry + costs once price has reached +1.0R. These are short-horizon trades whose edge, if any, is in the hit rate.
  - Make it configurable and evaluate it in the backtester. Do not assume it helps.
- **Time stops** per strategy (`03` §5).

### 3.1 What normal bad luck looks like (evidence: simulation, ours)

Maximum losing streak for independent trades, 5,000 simulations:

| Win rate | Trades | Median longest losing streak | 95th percentile |
|---|---|---|---|
| 35% (trend-like) | 100 | 9 | 14 |
| 35% | 250 | 11 | 17 |
| 45% | 100 | 6 | 11 |
| 60% (mean-reversion-like) | 100 | 4 | 7 |

Maximum drawdown over 250 trades for a trend-like payoff (36% winners, average winner 2.5R):

| Mean R/trade | Risk/trade | Median maxDD | 5% worst |
|---|---|---|---|
| 0.00 | 0.5% | −15.6% | −28.6% |
| +0.05 | 0.5% | −13.6% | −25.3% |
| +0.15 | 0.5% | −10.5% | −19.1% |
| +0.05 | 1.0% | −26.1% | −44.6% |

Implications:

- Rules like "stop the strategy after 5 losses in a row" fire constantly on a valid trend system.
- At 1% risk per trade a realistic FX system will very likely see a 25%+ drawdown.
- That is why the default is 0.5% (0.25% live) and why the drawdown ladder below de-risks progressively instead of killing everything at −10%.
- Our H4 trend backtests (`03` §4) had max drawdowns of −6% to −16% at 0.5% risk, consistent with this table.

## 4. Loss limits and circuit breakers (defaults)

Equity = NAV (balance + unrealized P/L). The "trading day" starts at **17:00 New York**.

| Breaker | Trigger | Action | Reset |
|---|---|---|---|
| Daily loss | NAV ≤ NAV_at_day_start × (1 − **2%**) | No new entries. Existing stops stay. | Automatically at next 17:00 NY |
| Weekly loss | NAV ≤ NAV_at_week_start (Sun 17:00 NY) × (1 − **4%**) | No new entries for the rest of the week | Next Sunday 17:00 NY |
| Drawdown step 1 | NAV ≤ peak × (1 − **5%**) | `m_drawdown = 0.75` | When NAV recovers above peak × (1 − 2.5%) |
| Drawdown step 2 | NAV ≤ peak × (1 − **8%**) | `m_drawdown = 0.5` | When NAV recovers above peak × (1 − 5%) |
| Drawdown halt | NAV ≤ peak × (1 − **12%**) | Halt new entries. Alert. Requires **manual review & re-arm** | Manual only |
| Catastrophic | NAV ≤ peak × (1 − **20%**) **or** `marginCloseoutPercent ≥ 0.5` **or** `MARGIN_CALL_ENTER` transaction | **Kill switch**: flatten everything, halt | Manual only |
| Broker/data health | stale prices > 30 s in market hours, stream down > 60 s, reconciliation mismatch, 3 consecutive order errors | Halt new entries | Automatic when healthy for 5 min (except reconciliation mismatch: manual) |

Daily −2% ≈ 4 full losses at 0.5% risk. Weekly −4% ≈ 8 losses. The numbers are opinion, sized against the losing-streak table above so that breakers catch abnormal behaviour (bugs, regime breaks, gaps) rather than routine variance.

## 5. Exposure aggregation

### 5.1 Per-currency exposure

Decompose each position into currency legs. Long 10,000 EUR_USD at 1.0850 = +10,000 EUR and −10,850 USD. Convert both to home currency, then sum per currency across all positions.

- **Risk-based limit (primary):** the sum of open risk (R-amount at the current stop) across positions that are long the same currency, or short the same currency, must be ≤ **1.0% of equity**. Example: long EUR_USD and short USD_CHF are both "short USD". At 0.5% each that is 1.0%, which is the limit.
- **Notional limit (secondary):** |net exposure per currency| ≤ **3 × equity**. Gross notional across all positions ≤ **5 × equity**. This is far below regulatory caps.

### 5.2 Correlation clusters

- Rolling 60-trading-day correlation ρ_ij of daily mid returns. Effective correlation for two positions = ρ_ij × sign_i × sign_j.
- Positions with effective correlation > **0.7** are in the same cluster (single-linkage). Cluster open risk ≤ **1.0%**. Example: long EUR_USD + long GBP_USD.
- Recompute daily at 17:00 NY. Cache the result.

### 5.3 Portfolio caps

- Max total open risk: **2.0%** of equity (e.g. 4 trades at 0.5%).
- Max concurrent positions: **4** (paper/practice), **3** (first live phase).
- Max 1 open trade per (strategy, instrument). Max 2 per instrument across strategies.
- With a non-hedging (netting) account, opposite signals on the same instrument from different strategies **net out**. The engine must aggregate the target position per instrument before sending orders, or block the second signal. Default: block, and log the conflict.
- US (NFA) accounts: FIFO, no hedging (§7). The order manager must close the oldest trade first.

## 6. Spread, liquidity, session and event filters

### 6.1 Spread filter

Reject a new entry if any of the following holds:

- spread > instrument cap: EUR_USD 2.5 pips, GBP_USD 3.0, USD_JPY 2.5, AUD_USD 3.0, USD_CAD 3.0, USD_CHF 3.0, NZD_USD 3.5. Opinion: about 2× the 90th percentile we measured (`03` §2).
- spread > 2.5 × the rolling 4-week median spread for that hour of week;
- spread > 10% of the stop distance (cost > 0.1R).

### 6.2 Daily rollover (17:00 New York)

- **Evidence (ours, OANDA bid/ask H1 2007–2018):** the median EUR/USD spread is 1.2–1.3 pips most of the day, **2.5 pips in the 17:00 NY bar and 2.1 in the 18:00 NY bar**. NZD/USD goes from ~2.3 to **5.0**. OANDA charges/credits financing on positions held at 17:00 ET (OANDA help pages).
- Default: **no new entries 16:45–17:30 NY**, and no discretionary stop modifications in that window. S2/S3 shadow signals inside it are flagged as non-executable.
- Use the instrument's `financing` (long/short rates, `financingDaysOfWeek`) for expected-holding-cost estimates. Do not hard-code "triple Wednesday": the recorded OANDA instrument data in `02` §6.3 shows Wednesday charged ×1 for that account.

### 6.3 Friday close and weekend gaps

- **Evidence (ours, ejtraderLabs MT5 H1 2012-11 → 2022-03, unsmoothed):** EUR/USD weekend gaps (Friday close → Monday open) have |gap| median **5.8 pips**, 95th percentile **35.6 pips**, max **178 pips** (2017-04-24, after the first round of the French election). USD/JPY: median 7.6, p95 44.3, max 151 pips.
- Note: the QuantConnect/LEAN OANDA hourly files are **smoothed** (every open equals the previous close), so they show zero gaps. Never use them to estimate gap risk (`07`).
- Defaults:
  - no new entries after **Friday 15:00 NY**;
  - S2/S3 positions flattened by Friday 15:30 NY;
  - S1 may hold over the weekend if the weekend gap budget holds: Σ_positions units × QHC × gap_p99 ≤ **1.0% of equity**, with gap_p99 = 2 × the measured p95 per instrument (conservative, ≈ 70 pips EUR/USD). Otherwise reduce S1 positions on Friday 15:00 NY.
- Tail reminder: on 2015-01-15 the Swiss National Bank removed the EUR/CHF floor and CHF pairs moved by tens of percent within minutes, far through stops. Stops do not cap gap risk. Negative balance protection exists for EU/UK retail (ESMA/FCA) but depends on jurisdiction and entity. **Exclude CHF pairs by default** until the system is mature.

### 6.4 Holidays and thin markets

Opinion: no new entries from Dec 24 17:00 NY to Jan 2 17:00 NY. Half risk on US/UK bank holidays. A configurable holiday calendar is enough. No external data is needed.

### 6.5 News-event risk

- High-impact releases (US NFP, CPI, FOMC decision/press conference, ECB/BoE/BoJ/RBA/BoC decisions) produce spread spikes and slippage through stops.
- Default: for affected currencies, **no new entries from 30 min before to 30 min after** a high-impact event. S2/S3 must be flat 15 min before the event. S1 keeps its positions (its stops are wide relative to typical event moves), but the weekend-gap-style budget applies on FOMC/NFP days (opinion).
- Calendar source:
  - (a) a built-in config of recurring scheduled events (NFP: usually the first Friday 08:30 ET; FOMC: 8 scheduled meetings/year published by the Fed; central-bank calendars published annually);
  - (b) optionally the unofficial ForexFactory weekly JSON export (`https://nfs.faireconomy.media/ff_calendar_thisweek.json`), which is rate-limited (reportedly max 2 downloads per 5 minutes, updated hourly). Its licensing is unclear, so it must stay optional and be cached. Fail safe: if the calendar is unavailable, treat the top-of-hour windows around 08:30 ET and 14:00 ET as event windows.

### 6.6 Price health

No orders when: the price is older than 10 s (live), `tradeable == false`, bid ≥ ask, a price jump > 10 × ATR(14,M1-equivalent) without confirmation, or the account/stream reconciliation is not clean.

## 7. Regulatory leverage caps (configuration)

| Regime | Retail leverage caps (FX) | Other rules | Source |
|---|---|---|---|
| ESMA (EU, 2018 product intervention, now permanent national measures) | **30:1 major currency pairs**. **20:1 non-major pairs, gold, major indices**. 10:1 commodities other than gold and non-major indices. 5:1 individual equities. 2:1 crypto | Margin close-out at **50%** of required margin per account. **Negative balance protection**. Standardized risk warning with % of losing accounts | ESMA press release & FAQ: https://www.esma.europa.eu/sites/default/files/library/esma71-98-128_press_release_product_intervention.pdf , https://www.esma.europa.eu/sites/default/files/library/esma71-98-125_faq_esmas_product_intervention_measures.pdf |
| UK FCA (PS19/18) | Same structure as ESMA | Same | https://www.fca.org.uk/publication/policy/ps19-18.pdf |
| US NFA/CFTC | Minimum security deposit **2%** (= 50:1) for GBP, CHF, CAD, JPY, EUR, AUD, NZD, SEK, NOK, DKK. **5%** (= 20:1) for other currencies. NFA may raise these in extraordinary conditions (e.g. CHF to 5% in Jan 2015) | **FIFO, no hedging** (NFA Compliance Rule 2-43(b)) | NFA Financial Requirements Section 12: https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=7&RuleID=SECTION+12 ; NFA notice: https://www.nfa.futures.org/news/newsNotice.asp?ArticleID=4531 |
| Others (ASIC, FSCA, CMA, offshore BVI/Seychelles…) | Vary. Offshore entities often allow much higher leverage | Often no negative balance protection | Check per broker (**UNVERIFIED** here) |

Defaults:

- `max_leverage_major = 30`, `max_leverage_minor = 20` (the strictest common caps). The engine uses `min(config cap, 1/instrument.marginRate)`.
- The internal 5:1 gross cap (§5.1) is the binding constraint in practice.

## 8. Kill switch

- Triggers: manual (UI/API, authenticated), catastrophic breaker (§4), reconciliation failure that cannot be resolved, repeated broker auth errors.
- Actions, in order:
  1. Set `halted=true` (persisted) so no new orders can be created.
  2. Cancel pending orders.
  3. Close all positions per instrument (OANDA `PUT /positions/{instrument}/close`, `02` §6.11).
  4. Poll until positions are empty. Retry `MARKET_HALTED` instruments when `tradeable` returns.
  5. Alert and journal everything.
- Re-arm requires an explicit authenticated action, and in `live` mode a typed confirmation.

## 9. Default parameter table (copy into `config.py`)

| Key | Default | Notes |
|---|---|---|
| `risk.per_trade_pct` | 0.50 (paper/practice), 0.25 (live phase 1) | of NAV |
| `risk.per_trade_pct_max` | 1.00 | after all multipliers |
| `risk.max_open_risk_pct` | 2.0 | |
| `risk.max_currency_risk_pct` | 1.0 | same-direction currency exposure |
| `risk.max_cluster_risk_pct` | 1.0 | ρ_eff > 0.7 |
| `risk.corr_window_days` | 60 | |
| `risk.max_gross_leverage` | 5.0 | internal |
| `risk.max_positions` | 4 (paper/practice), 3 (live phase 1) | |
| `risk.portfolio_vol_target_pct` | 10.0 | annualized, overlay |
| `risk.daily_loss_limit_pct` | 2.0 | resets 17:00 NY |
| `risk.weekly_loss_limit_pct` | 4.0 | resets Sun 17:00 NY |
| `risk.dd_ladder` | [(5, 0.75), (8, 0.5), (12, halt), (20, kill)] | % from peak |
| `risk.margin_closeout_guard` | 0.5 | `marginCloseoutPercent` |
| `risk.kelly_cap_fraction` | 0.25 | of the lower-bound Kelly, after ≥ 100 trades |
| `filters.spread_caps_pips` | EUR_USD 2.5, GBP_USD 3.0, USD_JPY 2.5, AUD_USD 3.0, USD_CAD 3.0, USD_CHF 3.0, NZD_USD 3.5 | |
| `filters.spread_vs_median_max` | 2.5 | hour-of-week median, 4 weeks |
| `filters.spread_max_fraction_of_stop` | 0.10 | |
| `filters.rollover_blackout_ny` | 16:45–17:30 | |
| `filters.friday_no_entry_after_ny` | 15:00 | |
| `filters.weekend_gap_budget_pct` | 1.0 | |
| `filters.news_blackout_min` | 30 before / 30 after | |
| `filters.stale_price_sec` | 10 | |
| `filters.excluded_instruments` | CHF crosses (EUR_CHF etc.) | until mature |
| `orders.max_slippage_atr_frac` | 0.10 | → OANDA `priceBound` |
| `regulatory.max_leverage_major` / `_minor` | 30 / 20 | |

## 10. Sources

- Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, Van Hemert (2018) "The Impact of Volatility Targeting", JPM 45(1):14–33: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3175538
- Thorp, E. O. (2006) "The Kelly Criterion in Blackjack, Sports Betting and the Stock Market", in *Handbook of Asset and Liability Management*. MacLean, Thorp, Ziemba (2010) "Good and bad properties of the Kelly criterion".
- ESMA product intervention (2018): press release https://www.esma.europa.eu/sites/default/files/library/esma71-98-128_press_release_product_intervention.pdf ; FAQ https://www.esma.europa.eu/sites/default/files/library/esma71-98-125_faq_esmas_product_intervention_measures.pdf ; additional information https://www.esma.europa.eu/sites/default/files/library/esma35-43-1000_additional_information_on_the_agreed_product_intervention_measures_relating_to_contracts_for_differences_and_binary_options.pdf
- FCA PS19/18: https://www.fca.org.uk/publication/policy/ps19-18.pdf
- NFA Financial Requirements Section 12: https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=7&RuleID=SECTION+12 ; NFA Forex Regulatory Guide: https://www.nfa.futures.org/members/member-resources/files/forex-regulatory-guide.html ; FIFO rule summary: https://fxcodebase.com/documents/IndicoreSDK/nfa.html
- OANDA financing (17:00 ET, T+2 Wednesday convention by division): https://help.oanda.com/bvi/en/faqs/financing-costs.htm , https://www.oanda.com/au-en/trading/financing-costs/
- ForexFactory calendar export, rate limiting (forum reports): https://www.forexfactory.com/thread/1311021-mql45-programmers-this-weekly-news-download-code-solves
- Spread-by-hour and weekend-gap measurements: our computation on the datasets in `07-data-sources.md`.
