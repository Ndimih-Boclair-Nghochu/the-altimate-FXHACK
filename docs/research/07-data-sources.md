# 07 — Historical FX data sources and local validation datasets

Status: research input for Stage 1 (historical downloader, candle store) and Stage 2 (backtests).
All reachability tests were run from the build container on **2026-10-02**. Nothing was
downloaded into the repository. Test files were fetched into a scratch directory outside the
repo.

**Summary.**

- **Production/research data** should come from the **OANDA candles API with `price=BA`** (bid and ask), downloaded on the user's machine with their own practice token. This matches the broker we trade with, includes real spreads, and has a documented format (`02` §6.4).
- **From this container** only GitHub (raw + git), PyPI and npm are reachable. OANDA, Dukascopy, HistData, TrueFX, FXCM's S3 host, Kaggle, Yahoo, Google Drive and HuggingFace are all blocked.
- For **local validation backtests** (and CI-sized fixtures) we found real hourly data on GitHub:
  - **QuantConnect LEAN**: OANDA EUR/USD and NZD/USD H1 *bid+ask*, 2007-01 → 2018-12 (≈ 74k bars each). Smoothed, so no gaps.
  - **ejtraderLabs**: EUR/USD, GBP/USD, USD/JPY and 9 more symbols, M15/M30/H1/H4/D1, bid OHLC + tick volume, 2012-11 → 2022-03, broker server time.
- CI keeps using **synthetic data** (brief constraint). Real files are downloaded on demand to a git-ignored `data/` folder, verified by SHA-256.

---

## 1. Source overview

| Source | Granularity | Price sides | History | Cost / access | Licence / terms | Reachable from container |
|---|---|---|---|---|---|---|
| **OANDA v20 candles** `GET /v3/instruments/{i}/candles` | S5 … M (21 granularities) | `M`, `B`, `A` (any combination) | Majors reportedly from ~2005 (**UNVERIFIED**). The LEAN OANDA files below start 2007-01 | Free with any OANDA account (practice is enough). Max 5,000 candles/request, 120 req/s | OANDA API terms. Redistribution likely not permitted (**UNVERIFIED**). Use for own research | ❌ (`api-fxpractice.oanda.com` 403 at proxy) |
| **Dukascopy** datafeed (`datafeed.dukascopy.com/datafeed/{PAIR}/{YYYY}/{MM-1}/{DD}/{HH}h_ticks.bi5`) | Tick (bid/ask + volumes), LZMA "bi5" hourly files | bid & ask | Majors from ~2003 (third-party date-range tables, e.g. Tickstory) | Free, no key. Tools: `dukascopy-node` (npm, 900+ stars), `duka`, `dukascopy-python` 4.0.1 (PyPI) | Dukascopy terms. Redistribution restricted | ❌ |
| **HistData.com** | M1 OHLC (bid), ticks | bid (M1) | EUR/USD from 2000 | Free download, web form/captcha. `histdata` 1.1 on PyPI | Free for personal use (site terms. Check) | ❌ |
| **TrueFX** (Integral) | Tick, ms timestamps | bid & ask | Majors from **May 2009**, monthly CSVs | Free registration | TrueFX terms | ❌ |
| **FXCM public samples** `https://candledata.fxcorporate.com/{m1\|H1\|D1}/{PAIR}/{YEAR}/{WEEK}.csv.gz` | m1, H1, D1 | bid & ask columns (**UNVERIFIED**) | 2017–2020, 21 pairs | Free | "For personal use and abides by our EULA". Timestamps UTC. "Data points are indicative" (FXCM `MarketData` README) | ❌ (host blocked) |
| **Kaggle** datasets | various | various | various | Free account | Per-dataset licence. Provenance often unclear | ❌ |
| **QuantConnect LEAN repo** sample data | tick/second/minute (sample days), **hour**, daily | **bid & ask OHLC** | OANDA: 2007-01 → 2018-12 (hour/daily) | Free, GitHub | Repo Apache-2.0. Coverage of the underlying OANDA/FXCM price data by that licence is unclear → local use only, do not redistribute | ✅ |
| **ejtraderLabs/historical-data** | M15, M30, H1, H4, D1 | bid (MT5 bars) + tick volume | 2012-11 → 2022-03 (H1/M15) | Free, GitHub | Repo Apache-2.0. Underlying broker unknown → local use only | ✅ |
| **nautilus_trader test data** | M1 (one month), ticks | bid & ask (FXCM M1), bid/ask ticks (TrueFX) | FXCM USD/JPY Feb 2013, GBP/USD Feb 2012. TrueFX AUD/USD 100k ticks 2020-01 | Free, GitHub | Repo LGPL-3.0. Data provenance FXCM/TrueFX | ✅ |
| **backtesting.py test data** | H1 | single OHLC + volume | EUR/USD 2017-04-19 → 2018-02-07 (5,000 bars) | Free, GitHub | Repo AGPL-3.0. Provenance not stated | ✅ |
| **FX-Data / FX31337** GitHub mirrors (e.g. `FX-Data/FX-Data-EURUSD-DS`, one branch per year 2007–2022) | Dukascopy-derived ticks, one CSV per hour | bid & ask (by value: first price < second) | 2007–2022 | Free, GitHub | Dukascopy terms apply | ✅ (but huge: ~6,000 files/year) |
| **philipperemy/FX-1-Minute-Data** | HistData M1 | bid | 2000–2024 | Data moved to Google Drive (repo holds only scripts now) | HistData terms | Scripts ✅, data ❌ |

## 2. Reachability test (curl from the container, 2026-10-02)

| URL tested | Result |
|---|---|
| `https://api-fxpractice.oanda.com/v3/accounts`, `https://stream-fxpractice.oanda.com/`, `https://api-fxtrade.oanda.com/v3/accounts`, `developer.oanda.com` | blocked (proxy CONNECT 403 / curl 000) |
| `https://datafeed.dukascopy.com/...bi5`, `https://www.dukascopy.com` | blocked |
| `https://www.histdata.com/...` | blocked |
| `https://www.truefx.com/...` | blocked |
| `https://candledata.fxcorporate.com/H1/EURUSD/2020/1.csv.gz` | blocked |
| `https://query1.finance.yahoo.com/...`, `https://www.kaggle.com`, `https://drive.google.com`, `https://huggingface.co`, `https://stooq.com`, `https://www.alphavantage.co`, `https://fred.stlouisfed.org`, ECB data portal | blocked |
| `https://raw.githubusercontent.com/...` | ✅ 200 (also with pinned commit SHAs) |
| `git clone https://github.com/...` (public repos) | ✅ |
| `https://pypi.org`, `https://registry.npmjs.org` | ✅ |
| GitHub REST API `api.github.com` | 403 (not usable unauthenticated here) |

## 3. Recommended local-validation datasets (exact URLs)

Use **pinned commit URLs** so files cannot change underneath us.

### 3.1 QuantConnect LEAN: OANDA hourly bid/ask (best realism available offline)

| File | URL (pinned) | Size | SHA-256 |
|---|---|---|---|
| EUR/USD H1 | `https://raw.githubusercontent.com/QuantConnect/Lean/0ebc2fc44fd4754ff66bdc7ef6cb42c5003f8fc1/Data/forex/oanda/hour/eurusd.zip` | 1,603,996 B | `09f9a548cdb8088e06d40b8af9fca611952d4c88a7ea9e92a7749466951bf92d` |
| NZD/USD H1 | `.../Data/forex/oanda/hour/nzdusd.zip` (same commit) | 1,567,370 B | `1e122113f4ed088cc4683ef6a948da3c258a4961f91c88d7c655f26cb08cce7f` |
| EUR/USD H1 (FXCM) | `.../Data/forex/fxcm/hour/eurusd.zip` | 1,474,845 B | `65eebb6fd18e1a3f20ef5b6e0d16664395aa9e3d8af3de1ba3c005ff6ad95eb2` |
| Daily OANDA: EUR/USD, GBP/USD, EUR/GBP, NZD/USD | `.../Data/forex/oanda/daily/{eurusd,gbpusd,eurgbp,nzdusd}.zip` | ~90 KB each | — |

Commit `0ebc2fc4…` (2026-10-02). Repo: https://github.com/QuantConnect/Lean. Format doc: `Data/forex/readme.md` in the same repo.

- **Format:** zip with one headerless CSV: `Time,BidOpen,BidHigh,BidLow,BidClose,LastBidSize,AskOpen,AskHigh,AskLow,AskClose,LastAskSize`. Time = `YYYYMMDD HH:mm`. Sizes are 0 in these files.
- **Time zone:** UTC. LEAN's market-hours database lists `Forex-oanda-[*]` with `dataTimeZone: "UTC"` and `exchangeTimeZone: "America/New_York"`. `Forex-fxcm-[*]` uses `dataTimeZone: "UTC-05"`. The bar timestamp is believed to be the bar start (LEAN convention, **UNVERIFIED**).
- **Coverage (our check):** EUR/USD 74,439 bars, 2007-01-01 21:00 → 2018-12-31 21:00. NZD/USD 74,451 bars, same range. FXCM EUR/USD 69,928 bars, 2007-03-30 → 2018-07-04.
- **Measured properties:**
  - median EUR/USD spread at bar open 1.2–1.4 pips (by year: 2008 0.9, 2012 1.2, 2016 1.4, 2018 1.4; p90 1.8–3.0);
  - 2.5 pips in the 17:00 NY bar;
  - NZD/USD 1.7–4.7 pips depending on year;
  - **smoothed:** 100% of bars have open == previous close, so weekend gaps are invisible. Do not use these files for gap-risk estimation.
- **Only EUR/USD and NZD/USD exist at hourly resolution** in LEAN (GBP/USD and EUR/GBP only daily). There is no USD/JPY.

### 3.2 ejtraderLabs: MT5 bars for 12 symbols (unsmoothed, more pairs, shorter)

| File | URL (pinned) | Rows | SHA-256 |
|---|---|---|---|
| EUR/USD H1 | `https://raw.githubusercontent.com/ejtraderLabs/historical-data/fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd/EURUSD/EURUSDh1.csv` | 57,600 | `1b29ca23bdc7b2645ae48a0ccb06108263b69e586bdc7d0ba40e66d1e5966eb9` |
| GBP/USD H1 | `.../GBPUSD/GBPUSDh1.csv` | 57,600 | `affda7b6e6f4ea505e46f714de37a51bf5d466efb78c3247c5900a0f0a85d3d7` |
| USD/JPY H1 | `.../USDJPY/USDJPYh1.csv` | 57,600 | `4bdca353ee0403727fc0eae621ff8206f5c06d7323b0126923d2a456abc21dbe` |
| EUR/USD M15 | `.../EURUSD/EURUSDm15.csv` | 230,400 | `8f9a8d0f7fe483cdede1f19dade91b79928f63678c7a199f990ee555be10faf1` |
| Others | `{SYMBOL}/{SYMBOL}{m15,m30,h1,h4,d1}.csv` for AUDJPY, AUDUSD, EURCHF, EURGBP, EURJPY, EURUSD, GBPJPY, GBPUSD, USDCAD, USDCHF, USDJPY, XAUUSD | | |

Commit `fbd29b3c…` (2022-08-26). Repo: https://github.com/ejtraderLabs/historical-data (Apache-2.0).

- **Format:** header `Date,open,high,low,close,tick_volume`. Date `YYYY-MM-DD HH:MM:SS`.
- **Prices are scaled integers stored as floats with noise:** EUR/USD × 100,000 (`127801.00000000001` = 1.27801), USD/JPY × 1,000 (`81121.0` = 81.121). Divide and round to the instrument precision on load.
- **Price side:** single OHLC, presumably **bid** (MT5 bars are built from bid). There is no ask, so a spread model is required (we used 1.3/1.6/1.4 pips for EUR/USD, GBP/USD, USD/JPY).
- **Time zone: broker server time = New York time + 7 h** (UTC+2 in winter, UTC+3 in summer, following **US** DST). Verified [OURS, `08` §A.10]: the first bar of the week is Monday 00:00 in 482 of 485 weeks, including the March weeks when US and EU DST dates differ. So 00:00 server = 17:00 New York. The exact broker is unknown. The sanity checks in `03` §4 converted with `Europe/Athens` (EU DST), which is off by one hour for 1–3 weeks per year. Use the rule below instead.
- **Coverage:** H1 EUR/USD 2012-11-16 → 2022-03-04. GBP/USD and USD/JPY start the same day (05:00 / 12:00) and end 2022-03-04 23:00. M15 EUR/USD 2012-11-14 → 2022-03-04.
- **Unsmoothed:** weekend gaps are present. EUR/USD |gap| median 5.8 pips, p95 35.6, max 178 (2017-04-24). USD/JPY median 7.6, p95 44.3, max 151.

### 3.3 Small fixtures (unit-test sized)

| File | URL (pinned) | Content |
|---|---|---|
| backtesting.py EUR/USD H1 | `https://raw.githubusercontent.com/kernc/backtesting.py/ca2e2611621e472542ba90f7243a1fa06a7d7108/backtesting/test/EURUSD.csv` | 5,000 bars, header `,Open,High,Low,Close,Volume`, 2017-04-19 09:00 → 2018-02-07 15:00. Sunday bars start 21:00 (UTC-like). Provenance not stated. AGPL-3.0 repo (keep out of our repo) |
| nautilus FXCM M1 bid/ask | `https://raw.githubusercontent.com/nautechsystems/nautilus_trader/224f599df710ecca2b9f4757ce07a06a86b3db70/test_data/fxcm/{usdjpy-m1-bid-2013,usdjpy-m1-ask-2013,gbpusd-m1-bid-2012,gbpusd-m1-ask-2012}.csv` | ~28–30k M1 rows each (Feb 2013 USD/JPY, Feb 2012 GBP/USD), header `timestamp,open,high,low,close`, UTC with `+00:00`. Separate bid and ask files. Good for testing spread/fill logic and an M1 "bar magnifier" |
| nautilus TrueFX ticks | `.../test_data/truefx/audusd-ticks.csv` | 100k ticks, `timestamp,bid,ask`, 2020-01 |

### 3.4 Datasets we looked at and do not recommend

- Dozens of hobby repos with `EURUSD_H1.csv` (GitHub code search returned 34 hits): unknown provenance, timezone and side. Not worth the risk.
- `FX-Data/FX-Data-*-DS` Dukascopy tick mirrors: reachable and genuine bid/ask ticks, but ~6,000 hourly files per year per pair. Fine for spot checks of a specific day, too heavy for routine use.

## 4. Loader sketch (for `data/` module)

```python
LEAN_COLS = ["time", "bid_o", "bid_h", "bid_l", "bid_c", "bid_sz",
             "ask_o", "ask_h", "ask_l", "ask_c", "ask_sz"]

def load_lean_hour(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, names=LEAN_COLS, compression="zip")
    df["time"] = pd.to_datetime(df["time"], format="%Y%m%d %H:%M", utc=True)
    return df.drop(columns=["bid_sz", "ask_sz"]).set_index("time")      # source="lean-oanda", smoothed=True

def load_ejtrader(path: Path, scale: int, precision: int) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"])
    for c in ("open", "high", "low", "close"):
        df[c] = (df[c] / scale).round(precision)
    # server clock = America/New_York wall clock + 7 h (see 08 §A.10)
    ny = (df["Date"] - pd.Timedelta(hours=7)).dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    df = df[ny.notna()].assign(time=ny[ny.notna()].dt.tz_convert("UTC")).set_index("time")
    return df.rename(columns=str.lower)                                  # source="ejtrader-mt5", side="bid", smoothed=False
```

Store each dataset in the candle store with metadata: `source`, `instrument`, `granularity`, `price_side` (`BA`/`B`/`M`), `smoothed`, `tz_origin`, `sha256`, `license_note`.

## 5. Recommendations

1. **Downloader (Stage 1):**
   - `fxbot data fetch --source oanda --instrument EUR_USD --granularity H1 --from 2010-01-01 --price BA`;
   - paging as in `02` §6.4 (`count=5000`, `includeFirst=false`, `smooth=false`), resumable, idempotent upserts keyed by (instrument, granularity, time);
   - stores only `complete=true` candles.
2. **Validation fetcher (Stage 2):**
   - `fxbot data fetch-validation` downloads the pinned files in §3.1–3.2 into git-ignored `data/validation/` and verifies SHA-256.
   - Add `data/` to `.gitignore`. **Never commit market data**: licences are unclear and size bloats the repo.
3. **CI:** synthetic generators only (GBM with stochastic volatility, injected trend segments, regime switches, realistic spread by hour and weekend gaps), as the brief requires. Tests marked `@pytest.mark.real_data` skip automatically when `data/validation/` is absent.
4. **Research hygiene:** always state the dataset (source, side, smoothing, timezone) in backtest reports. Run every strategy on **both** the LEAN-OANDA bid/ask set and the ejtrader set before believing a result.

## 6. Sources

- QuantConnect LEAN: https://github.com/QuantConnect/Lean (data format: `Data/forex/readme.md`. Time zones: `Data/market-hours/market-hours-database.json`)
- ejtraderLabs historical data: https://github.com/ejtraderLabs/historical-data
- backtesting.py: https://github.com/kernc/backtesting.py (`backtesting/test/__init__.py` docstring: "hourly EUR/USD forex data from April 2017 to February 2018")
- nautilus_trader test data and loaders: https://github.com/nautechsystems/nautilus_trader (`python/nautilus_trader/testkit/providers.py`)
- FXCM MarketData README: https://github.com/fxcm/MarketData
- philipperemy FX-1-Minute-Data (HistData format, EST without DST): https://github.com/philipperemy/FX-1-Minute-Data
- FX-Data Dukascopy mirrors: https://github.com/FX-Data/FX-Data-EURUSD-DS
- Dukascopy tools: https://github.com/Leo4815162342/dukascopy-node , https://github.com/giuse88/duka , https://pypi.org/project/dukascopy-python/ ; date ranges: https://tickstory.com/dukascopy-historical-data-available-date-ranges/
- TrueFX history from May 2009 (secondary): https://www.truefx.com/truefx-historical-downloads-2/ , https://newyorkcityservers.com/blog/top-12-sources-to-download-forex-historical-data-free-paid
- OANDA candles API: `02-oanda-v20-api-spec.md`.
