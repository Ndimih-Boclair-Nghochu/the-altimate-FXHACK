# Altimate FX — Roadmap

Scope and acceptance criteria for stages 0–7. `docs/PROJECT_BRIEF.md` wins on any conflict.
Design details live in `docs/ARCHITECTURE.md`; progress lives in `docs/STATUS.md`.

## How to read this

- A stage is **done** when every acceptance box below is checked, the Definition of Done
  holds, and `docs/STATUS.md` records the commit/PR.
- Backend test paths are relative to `backend/tests/` (mirrors `src/fxbot/`). Frontend tests are
  co-located under `frontend/src/`. Test file names are binding; rename them here first.
- Stages are sequential (brief). Prototyping the next stage against mocks is fine, but nothing
  from stage N+1 is committed before stage N is done.
- Numeric defaults marked *(placeholder)* are starting values until the research reports in
  `docs/research/` or `docs/SECURITY.md` set them. Change them in this file, not silently in code.

## Definition of Done (every stage)

- [ ] Backend gates green from `backend/`: `uv sync`, `uv run ruff check .`,
      `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest`.
- [ ] Frontend gates green from `frontend/` whenever frontend code changed:
      `npm ci`, `npm run lint`, `npm run typecheck`, `npm test -- --run`, `npm run build`.
- [ ] CI (`.github/workflows/ci.yml`) green on the pushed commit.
- [ ] No test opens a real network socket (guard in `tests/conftest.py`); broker I/O is tested
      with `respx` against fixtures in `tests/fixtures/oanda/`.
- [ ] No secret in logs, exceptions, API responses, fixtures or the frontend bundle. Fixtures use
      obviously fake tokens and account IDs.
- [ ] Decision code (`indicators/`, `regime/`, `strategies/`, `risk/`, `learning/`,
      `engine/pipeline.py`) reads time only from an injected `Clock` and uses closed bars only.
- [ ] `ARCHITECTURE.md` updated if an interface changed; `STATUS.md` row and decisions log updated.
- [ ] Security review done and findings fixed or tracked (stages 1, 5, 6, 7).
- [ ] Committed and pushed; commit/PR linked in `STATUS.md`.

## Overview

| # | Stage | Owner(s) | Depends on | Security review |
|---|---|---|---|---|
| 0 | Foundation | all (lead integrates) | — | — |
| 1 | Broker connectivity & market data | backend | 0 | yes |
| 2 | Indicators, regime, strategies, backtester | backend | 1 | — |
| 3 | Risk management engine | backend | 2 | — |
| 4 | Adaptive learning | backend | 2, 3 | — |
| 5 | Live engine + REST/WS API + auth | backend | 1–4 | yes |
| 6 | Dashboard UI | frontend | 5 | yes |
| 7 | Hardening, deployment, docs, E2E paper run | security + all | 1–6 | yes (final) |

Persistence tables are introduced with the stage that first needs them:
1 → `instruments`, `candles`; 2 → `backtest_runs`; 3 → `risk_events`, `settings`;
4 → `signals`, `model_versions`; 5 → `orders`, `trades`, `equity_snapshots`.

---

## Stage 0 — Foundation

**Objective.** Shared understanding and empty-but-green skeletons so stage 1 starts on solid ground.

**In scope.** Research reports; roadmap, architecture, status, ADRs; threat model; backend and
frontend scaffolds with all quality gates wired; CI.
**Out of scope.** Any trading, broker or data logic; auth; deployment hardening (stage 7);
real UI pages.

**Deliverables.**

| Item | Owner |
|---|---|
| `docs/research/*` (strategy evidence, regime detection, risk sizing, meta-labeling/bandits, OANDA v20 notes) | research |
| `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md`, `docs/adr/0001`–`0005` | PM |
| `docs/SECURITY.md` (threat model, secret handling, auth, live interlock requirements) | security |
| `backend/pyproject.toml`, `backend/uv.lock`, `src/fxbot/` with every package from the brief layout (importable, empty where not yet built), `config.py`, `logging.py`, `cli.py` (`fxbot` entry point), `api/app.py` with `GET /api/health`, `backend/.env.example`, `backend/Dockerfile` | backend |
| `frontend/` Vite + React + TS strict + Tailwind + ESLint + Prettier + Vitest; deps from the brief installed; app shell with router and placeholder routes for the 7 pages | frontend |
| `.github/workflows/ci.yml` running both gate sets on push and PR | lead (backend/frontend supply their jobs) |
| Root `.gitignore`, project `README.md` replacing the original placeholder, `docker-compose.yml` skeleton | lead |
| `.gitleaks.toml` secret-scanning config | security |

**Acceptance criteria.**

- [ ] All PM, research and security docs above exist and are cross-linked from `README.md`.
- [ ] `tests/test_config.py`: default `Settings()` has mode `paper`; secrets are `SecretStr` and
      never rendered; `practice` needs credentials; `live` refused unless `ALLOW_LIVE_TRADING`,
      `FXBOT_LIVE_TRADING_CONFIRMED` and credentials are all set; `.env.example` documents every
      setting with safe defaults.
- [ ] `tests/test_logging.py`: secret-named keys, `SecretStr` values, credential patterns in text
      and tracebacks are masked in console and JSON output.
- [ ] `tests/test_api_health.py`: `GET /api/health` → 200 with `status: ok`, version and mode;
      no auth needed; no secret in the response.
- [ ] `tests/test_cli.py`: invalid configuration exits non-zero without echoing secrets.
- [ ] `tests/conftest.py` network guard: a test that opens a socket fails (self-test included).
- [ ] mypy runs in strict mode on `src/`; ruff config committed.
- [ ] `frontend/src/App.test.tsx`: shell renders; nav links for Overview, Trades, Strategies,
      Learning, Risk, Backtests, Settings present.
- [ ] CI runs on a PR and is green for both jobs.
- [ ] ADRs 0001–0005 accepted (or amended) by the lead.

**Risks.** Agents diverge on names → ARCHITECTURE.md interface sketches are the reference;
scaffold over-reaches into stage 1 → keep stubs empty; lockfiles missing → CI not reproducible.

---

## Stage 1 — Broker connectivity & market data

**Objective.** Talk to OANDA v20 and the paper broker through one `Broker` protocol, and build a
reliable local candle store, all testable offline.

**In scope.** Domain models; `Broker` and `MarketDataFeed` protocols; OANDA REST client, adapter,
pricing and transaction streams; paper broker; synthetic and replay feeds; candle store and
historical downloader; mode interlock in config and broker factory.
**Out of scope.** Indicators, strategies, risk rules, order lifecycle management, API beyond
health, UI. Non-market order types (limit/stop entries) — later if needed.

**Deliverables** (`backend/src/fxbot/`).

- `domain/models.py` — `Instrument`, `Candle`, `Price`, `OrderRequest`, `OrderResult`, `Fill`,
  `Trade`, `Position`, `AccountSummary`, `Transaction`. Money and prices are `Decimal`; times are
  tz-aware UTC.
- `domain/enums.py` — `Side`, `Granularity`, `Mode`, `OrderStatus`, `ExitReason`.
- `domain/clock.py` — `Clock` protocol, `SystemClock`, `SimClock`.
- `domain/errors.py` — `BrokerUnavailableError` (retryable), `BrokerRejectedError`,
  `RateLimitedError`, `FeedStaleError`, `DataIntegrityError`, `LiveTradingNotAllowedError`.
- `brokers/base.py` — `Broker`, `MarketDataFeed` protocols (see ARCHITECTURE §4).
- `brokers/factory.py` — `build_broker(settings)`, `build_feed(settings)`; enforces the interlock.
- `config.py` — add `FXBOT_DATA_FEED` (`synthetic` default / `replay` / `oanda`) for paper mode.
- `brokers/oanda/client.py` — httpx `AsyncClient`: auth header, timeouts, client-side rate limit,
  retry with backoff + jitter for idempotent GETs only, HTTP → domain error mapping.
- `brokers/oanda/adapter.py` — `OandaBroker`: v20 JSON ↔ domain mapping, signed units, price
  rounding to instrument precision, `clientExtensions.id` as idempotency key,
  `stopLossOnFill`/`takeProfitOnFill`.
- `brokers/oanda/streaming.py` — pricing and transaction streams: line parsing, heartbeat
  watchdog, reconnect with capped exponential backoff.
- `brokers/oanda/feed.py` — `OandaFeed` (candles via REST, prices via stream).
- `brokers/paper.py` — `PaperBroker`: tick- or bar-driven price source, fills at bid/ask +
  slippage, broker-side SL/TP, margin, P&L in account currency, transaction log with IDs.
- `data/candle_store.py`, `data/downloader.py` (paginated, resumable, complete candles only,
  CLI `python -m fxbot.data.downloader`), `data/synthetic.py` (seeded generator + `SyntheticFeed`),
  `data/replay.py` (`ReplayFeed` from the store).
- `persistence/db.py` (async engine from `FXBOT_DATABASE_URL`, SQLite WAL + busy timeout),
  `persistence/models.py` (`instruments`, `candles`), `persistence/repositories.py`.
- `tests/fixtures/oanda/*.json` — recorded or hand-built v20 payloads with fake IDs.

**Acceptance criteria.**

- [ ] `tests/domain/test_models.py`: Decimal round-trips; pip size from `pip_location`; units > 0
      enforced; naive datetimes rejected.
- [ ] `tests/brokers/oanda/test_client.py` (respx): account summary, instruments, candles
      (pagination, `complete=false` dropped), market order with SL on fill, close trade,
      open trades/positions, order lookup by client ID; 4xx → `BrokerRejectedError` without retry;
      5xx/timeout → retried then `BrokerUnavailableError`; 429 → backoff honoured.
- [ ] `tests/brokers/oanda/test_streaming.py`: parses PRICE and HEARTBEAT lines; no heartbeat
      within `stale_after` → `FeedStaleError`; reconnects after disconnect with backoff.
- [ ] `tests/brokers/test_broker_contract.py`: one parametrized contract suite passes for both
      `PaperBroker` and `OandaBroker` (mocked): submit → fill → open trade visible → close →
      transaction recorded; resubmitting the same `client_id` does not create a second order.
- [ ] `tests/brokers/test_paper.py`: buy fills at ask, sell at bid, plus slippage; SL/TP trigger
      on tick and on bar high/low; P&L converted to account currency for `USD_JPY` and `EUR_GBP`
      in a USD account; deterministic with a seed.
- [ ] `tests/brokers/test_factory.py`: `paper` builds `PaperBroker` with no credentials;
      `practice` without credentials → config error; `live` without `ALLOW_LIVE_TRADING=true`
      or without `FXBOT_LIVE_TRADING_CONFIRMED=true` → `LiveTradingNotAllowedError` even if a
      `Settings` object is constructed bypassing validation; practice/live hosts are fixed by
      mode, not user-supplied.
- [ ] `tests/data/test_candle_store.py`: upsert idempotent; range query ordered; gap detection
      skips weekends.
- [ ] `tests/data/test_synthetic.py`: same seed → identical series; OHLC invariants hold;
      weekend gaps present; regime segments distinguishable (trend vs mean-revert vs vol burst).
- [ ] `tests/data/test_downloader.py` (respx): resumes from last stored candle; stores only
      complete candles.
- [ ] `tests/test_secrets.py`: with `FXBOT_OANDA_API_TOKEN` set to a sentinel, the sentinel never
      appears in captured logs, exception messages or `repr` of client/settings objects.
- [ ] Manual (user machine, not CI): downloader fetches real practice candles for one instrument.

**Risks.** Fixtures drift from the real API (record fixtures from docs + one manual practice
session, keep them versioned); FIFO/no-hedging rules on some account types (handled in stage 3:
one open trade per instrument); Decimal vs float leaking into domain; stream reconnect storms.

---

## Stage 2 — Indicators, regime detection, strategies, backtester

**Objective.** Generate signals from closed bars and evaluate them in an event-driven backtester
that runs the same decision code the live engine will run.

**In scope.** Vectorized indicators; rule-based regime classifier; trend, mean-reversion and
breakout strategies; `DecisionPipeline`; basic order manager; minimal risk stub; backtester with
realistic costs, metrics, walk-forward splits, reproducible reports.
**Out of scope.** Full risk rules (stage 3); learning (stage 4); live engine, API, UI.
Parameter optimisation beyond walk-forward evaluation.

**Deliverables.**

- `indicators/` — SMA, EMA, ATR, ADX, RSI, Bollinger, Donchian, realized volatility, efficiency
  ratio (plus anything research recommends). Pure numpy/pandas, causal.
- `regime/base.py` (`RegimeClassifier`, `Regime`, `RegimeState`), `regime/classifier.py`
  (`RuleBasedRegimeClassifier`: trend strength + volatility percentile →
  `TRENDING | RANGING | HIGH_VOLATILITY | UNDEFINED`).
- `strategies/base.py` (`Strategy`, `Signal`, `BarContext`), `strategies/trend.py`,
  `strategies/mean_reversion.py`, `strategies/breakout.py`, `strategies/registry.py`.
- `engine/pipeline.py` — `DecisionPipeline` with meta-model and allocator slots wired to
  pass-through implementations.
- `engine/order_manager.py` — basic `OrderManager` over `Broker` (client IDs, fill tracking).
- `risk/manager.py` — `BasicRiskManager`: mandatory stop, fixed-fractional sizing; replaced in
  stage 3. `ApprovedOrder` type introduced here.
- `persistence/journal.py` — `TradeJournal` protocol + `InMemoryTradeJournal`.
- `backtest/engine.py` (`Backtester`), `backtest/costs.py`, `backtest/metrics.py`,
  `backtest/walk_forward.py`, `backtest/report.py`, `backtest/cli.py`
  (`python -m fxbot.backtest`); `backtest_runs` table + repository.

**Acceptance criteria.**

- [ ] `tests/indicators/test_indicators.py`: each indicator matches hand-computed reference
      values; warm-up rows are NaN and nothing after warm-up is NaN.
- [ ] `tests/indicators/test_causality.py`: for each indicator and sampled `t`,
      `f(x[:t+1])[t] == f(x)[t]`.
- [ ] `tests/regime/test_classifier.py`: synthetic trend → `TRENDING` on ≥ 80% of post-warm-up
      bars; OU mean-reverting → `RANGING` ≥ 80%; injected vol burst → `HIGH_VOLATILITY`; causal.
- [ ] `tests/strategies/test_trend.py`, `test_mean_reversion.py`, `test_breakout.py`: handcrafted
      bars produce the expected signal (bar, side, stop distance); no signal during warm-up or in
      disallowed regimes; every signal carries a stop distance and a rationale.
- [ ] `tests/strategies/test_no_lookahead.py`: for every registered strategy, bar-by-bar signals
      equal signals computed with future bars present; a deliberately leaking fixture strategy is
      detected by the harness.
- [ ] `tests/backtest/test_fills.py`: signal at close of bar `t` fills at open of `t+1` ± half
      spread + slippage; SL/TP evaluated on high/low; both touched in one bar → stop first; gap
      through stop fills at the (worse) open.
- [ ] `tests/backtest/test_costs.py`: random-entry strategy on zero-drift synthetic data over
      ≥ 20 seeds has mean net R ≈ −(costs in R) within tolerance — the system manufactures no edge.
- [ ] `tests/backtest/test_determinism.py`: same config + seed → identical trades and report hash.
- [ ] `tests/backtest/test_metrics.py`: CAGR, Sharpe, Sortino, max drawdown, profit factor,
      win rate, expectancy, exposure match hand-computed series.
- [ ] `tests/backtest/test_walk_forward.py`: train and test never overlap; test windows are
      contiguous; purge/embargo gap respected.
- [ ] `tests/engine/test_pipeline.py`: pipeline returns a `Decision` for every signal, including
      rejected ones with reasons; identical inputs → identical outputs.
- [ ] `tests/test_no_wallclock.py`: static scan finds no `datetime.now(`, `datetime.utcnow(`,
      `time.time(` in decision-code packages.
- [ ] Demonstrate: `uv run python -m fxbot.backtest --strategies all --instrument EUR_USD
      --synthetic --seed 42 --out report.json` finishes in < 60 s in CI; report includes
      provenance (params, seed, data source, cost model, code version, config hash).

**Risks.** Lookahead via pandas alignment/`shift` mistakes (causality tests); optimistic fills
(conservative conventions above); strategies tuned to synthetic data (synthetic results are for
correctness only, never quoted as performance); backtest/live divergence (shared pipeline, parity
test in stage 5).

---

## Stage 3 — Risk management engine

**Objective.** No order reaches a broker without passing a deterministic, auditable risk check,
and losses are bounded by limits, breakers and a kill switch.

**In scope.** Sizing, stops, loss limits, drawdown breaker, exposure limits, spread/session
filters, kill switch, `RiskManager` composition, persistence of risk state and events,
backtester integration.
**Out of scope.** Learning-driven sizing (stage 4 supplies a bounded multiplier only); UI controls
(stage 6); API endpoints (stage 5).

**Deliverables** (`risk/`).

- `sizing.py` — units = equity × risk_fraction × multiplier / (stop distance × pip value in
  account currency); rounded down to instrument precision; min/max units.
- `stops.py` — ATR initial stop, clamped to `[min_atr_mult, max_atr_mult]`; optional trailing.
- `limits.py` — daily and weekly loss limits (trading day rolls at 17:00 America/New_York),
  max open trades, one open trade per instrument (FIFO-safe), drawdown breaker from equity
  high-water mark.
- `exposure.py` — per-currency net exposure and aggregate open risk.
- `filters.py` — spread filter (vs rolling median and absolute cap), session/weekend/rollover filter.
- `kill_switch.py` — persisted state; engage → halt entries + flatten request; manual release only.
- `manager.py` — `DefaultRiskManager` composing all checks → `RiskDecision`; hard caps in code
  that runtime settings cannot exceed.
- `risk_events` and `settings` tables + repositories; backtester uses `DefaultRiskManager`.

Initial defaults *(placeholder)*: risk 0.5% equity/trade (hard cap 2%); stop 2×ATR(14) within
[1, 4]×ATR; daily loss 2%; weekly loss 5%; drawdown breaker 10% from HWM; max 4 open trades;
aggregate open risk ≤ 2%; ≤ 2 same-direction trades sharing a currency; no entries Fri 16:00 →
Sun 18:00 NY or 16:55–17:10 NY daily.

**Acceptance criteria.**

- [ ] `tests/risk/test_sizing.py`: worked examples for `EUR_USD`, `USD_JPY`, `EUR_GBP` in a USD
      account; result never exceeds max units or hard cap; zero/negative stop → rejection.
- [ ] `tests/risk/test_stops.py`: stop on correct side of entry; clamped to ATR bounds; an intent
      without a stop is rejected.
- [ ] `tests/risk/test_limits.py`: daily limit breach blocks entries until the 17:00 NY rollover;
      weekly likewise; drawdown breaker trips at threshold and engages the kill switch; one open
      trade per instrument enforced.
- [ ] `tests/risk/test_exposure.py`: aggregation across pairs; order that would breach a currency
      limit rejected; order that reduces exposure allowed.
- [ ] `tests/risk/test_filters.py`: wide spread rejected; weekend, rollover window and
      out-of-session entries rejected.
- [ ] `tests/risk/test_kill_switch.py`: engage is idempotent, persisted and survives a restart;
      while engaged every intent is rejected; release requires an actor and is audited.
- [ ] `tests/risk/test_manager.py`: every rejection carries a reason code; same snapshot + intent
      → same decision; settings above hard caps are refused.
- [ ] `tests/risk/test_approved_order.py`: `OrderManager.submit` only accepts `ApprovedOrder`;
      constructing one outside `risk/` raises.
- [ ] `tests/backtest/test_risk_integration.py`: synthetic crash scenario trips the breaker; no
      new entries afterwards; max drawdown stays within breaker + one-trade risk (absent gaps).

**Risks.** Currency conversion errors in sizing (worked-example tests); limits defined on the
wrong equity base (start-of-day snapshot, documented); gaps exceed stops (accepted, reported);
operators loosening limits at runtime (hard caps + audit).

---

## Stage 4 — Adaptive learning system

**Objective.** Improve signal selection and capital allocation from the system's own outcomes,
with guardrails that make learning from noise unlikely and always reversible.

**In scope.** Features, triple-barrier labeling, meta-model training/scoring, bandit allocator,
drift detection, model registry, champion/challenger promotion, learning loop; pipeline wiring;
learning-on vs learning-off backtest comparison.
**Out of scope.** Learning that changes strategy logic or parameters; deep learning or RL;
any path that raises risk above `RiskManager` caps; UI (stage 6).

**Deliverables** (`learning/`).

- `features.py` — causal feature builder (regime, ATR percentile, trend strength, spread,
  session, distance to bands, recent strategy hit rate …); versioned feature schema.
- `labeling.py` — triple-barrier labels (SL, TP, time barrier, net of costs) for **every**
  signal, taken or not, once its horizon has passed.
- `dataset.py` — training sets from labeled signals; purged + embargoed walk-forward splits.
- `meta_model.py`, `trainer.py` — calibrated scikit-learn classifier; pass-through until the
  minimum sample count is reached.
- `bandit.py` — discounted Thompson sampling per (regime, strategy) on net R; weights with floor
  and cap; seeded RNG.
- `drift.py` — PSI on features, rolling Brier/calibration, Page-Hinkley on per-strategy R.
- `registry.py` — versions, artifacts on the data volume with SHA-256, load-time hash check.
- `promotion.py` — champion/challenger shadow scoring, promotion guardrails, rollback.
- `loop.py` — `LearningLoop`: on labeled signal/closed trade → update allocator, drift monitors;
  `maybe_retrain(now)` driven by the injected clock.
- `signals` and `model_versions` tables; pipeline uses real `MetaModel` and `StrategyAllocator`.

**Acceptance criteria.**

- [ ] `tests/learning/test_labeling.py`: handcrafted paths give TP/SL/timeout labels; costs
      included; unlabeled until the horizon has elapsed.
- [ ] `tests/learning/test_features.py`: causal (truncating future bars changes nothing); schema
      version mismatch at scoring time raises.
- [ ] `tests/learning/test_dataset.py`: no training sample's label horizon overlaps its test fold;
      embargo applied.
- [ ] `tests/learning/test_meta_model.py`: pass-through below min samples; scores in [0, 1];
      planted-signal synthetic data → OOS AUC > 0.6; deterministic with seed.
- [ ] `tests/learning/test_promotion.py`: on pure-noise labels the challenger is **rejected**
      (permutation baseline guardrail); promotion requires ≥ N shadow OOS signals and a margin
      over champion; rollback restores the previous champion; every decision writes
      `model_versions` and `risk_events` rows.
- [ ] `tests/learning/test_bandit.py`: converges to the best arm on stationary rewards; adapts
      after a reward switch (discounting); weights sum to 1 and respect floor/cap; regimes
      independent; seeded runs identical.
- [ ] `tests/learning/test_drift.py`: PSI flags a shifted distribution and not an identical one;
      performance detector fires on a step change.
- [ ] `tests/learning/test_registry.py`: tampered artifact (hash mismatch) is refused.
- [ ] `tests/engine/test_pipeline_learning.py`: for any meta score and allocator weight, final
      per-trade risk ≤ base risk × max multiplier ≤ hard cap.
- [ ] Demonstrate: walk-forward backtest on synthetic data reports learning-on and learning-off
      side by side in one report, whatever the result.

**Risks.** Overfitting on small samples (min samples, purged CV, permutation test, shadow period);
selection bias from training only on taken trades (label all signals); feedback loops between
filter and allocator (both bounded, both reversible); pickle-loading risk (hash-verified
artifacts written only by the trainer).

---

## Stage 5 — Live trading engine + REST/WebSocket API + auth

**Objective.** Run the shared pipeline continuously against a feed and broker, survive restarts
and disconnects, and expose state and controls through an authenticated API.

**In scope.** Engine orchestrator, bar builder, hardened order manager, reconciliation, event bus,
scheduler, instance lock, SQL trade journal, FastAPI routers, WebSocket channels, auth per
`docs/SECURITY.md`.
**Out of scope.** UI (stage 6); Docker/deployment (stage 7); multi-user or multi-account.

**Deliverables.**

- `engine/engine.py` (`TradingEngine`), `engine/bar_builder.py`, `engine/order_manager.py`
  (state machine, idempotent client IDs, UNKNOWN resolution, flatten-all),
  `engine/reconciliation.py`, `engine/events.py` (`EventBus`, event types),
  `engine/scheduler.py` (rollover, reconciliation, equity snapshots, retrain checks),
  `engine/lock.py` (single-instance lock).
- `persistence/journal.py` `SqlTradeJournal`; `orders`, `trades`, `equity_snapshots` tables.
- `api/app.py` (lifespan starts/stops engine), `api/auth.py`, `api/deps.py`, `api/schemas.py`,
  `api/ws.py`, `api/routers/` for every endpoint in ARCHITECTURE §8.

**Acceptance criteria.**

- [ ] `tests/engine/test_bar_builder.py`: ticks → correct OHLC; bar emitted only after the
      boundary (or timer + grace); no partial bars reach strategies; empty periods emit no bar.
- [ ] `tests/engine/test_engine_paper.py`: synthetic feed + `PaperBroker` + `SimClock` run N bars:
      signal → risk → order → fill → journal → closed trade → learning update, all persisted.
- [ ] `tests/engine/test_parity.py`: the same bars through `TradingEngine` (paper, sim clock) and
      `Backtester` give identical trades.
- [ ] `tests/engine/test_order_manager.py`: duplicate submit with same client ID → one order;
      timeout → UNKNOWN → resolved by client-ID lookup before any resubmit; rejection recorded.
- [ ] `tests/engine/test_reconciliation.py`: unknown broker trade adopted + risk event; local trade
      missing at broker closed from broker transactions; field mismatches take broker values;
      runs at start before entries are enabled; unresolved critical discrepancy pauses entries.
- [ ] `tests/engine/test_interlock.py`: engine refuses `live` without env flag + confirmation;
      in `live` it starts with entries paused until an operator resumes; mode cannot be changed
      through the API.
- [ ] `tests/engine/test_kill_switch_e2e.py`: `POST /api/risk/kill-switch` flattens all paper
      positions, rejects later signals, broadcasts on `risk`, survives restart.
- [ ] `tests/engine/test_restart.py`: stop mid-session and start again → state reloaded,
      reconciliation clean, no duplicate orders.
- [ ] `tests/engine/test_feed_stale.py`: stale feed pauses entries; on recovery candles are
      backfilled before bar building resumes.
- [ ] `tests/engine/test_instance_lock.py`: a second engine on the same data directory refuses
      to start.
- [ ] `tests/api/test_auth_required.py`: enumerates `app.routes`; every route except
      `/api/health` and `/api/auth/login` returns 401 without credentials.
- [ ] `tests/api/test_no_secret_leak.py`: sentinel token never appears in any GET response,
      WS snapshot or captured log.
- [ ] `tests/api/test_settings.py`: values beyond hard caps → 422; secrets not readable or
      writable; changes audited in `risk_events`.
- [ ] `tests/api/test_ws.py`: subscribe/unsubscribe; per-connection `seq` increasing;
      unauthenticated connection closed with 1008.
- [ ] `tests/api/test_routers.py`: each endpoint returns its schema; Decimals serialized as strings.
- [ ] Manual (user machine): practice mode runs ≥ 1 trading session against OANDA demo with
      zero unresolved reconciliation discrepancies.

**Risks.** Concurrency bugs between reconciliation and order flow (single trading lock);
duplicate orders on timeout (client-ID lookup); two engines on one account (instance lock,
single uvicorn worker); event-loop blocking (CPU work in process pool); auth design gaps
(security review).

---

## Stage 6 — Dashboard UI

**Objective.** A clean, fast operator dashboard showing live state with honest provenance and
safe controls.

**In scope.** App shell, login, seven pages, typed API client, WebSocket client, charts.
**Out of scope.** Mobile-first layouts (desktop ≥ 1280 px primary, usable on tablet);
multi-user admin; editing secrets; switching to `live` from the UI.

**Deliverables** (`frontend/src/`). `api/` (typed client, resource modules, 401 handling),
`lib/ws.ts` (reconnecting, resubscribing WS client), `stores/` (Zustand: session, live data, UI
prefs), `components/` (AppShell, ModeBadge, ConnectionStatus, KillSwitchControl, ConfirmDialog,
DataTable, StatCard, EquityChart, Meter), `pages/` below, `routes.tsx`.

**Pages.**

| Page | Must show / do |
|---|---|
| Overview | Equity curve with range selector; realized + unrealized P&L (today, week, all); account (balance, NAV, margin used/available); open positions live via WS (instrument, side, units, entry, price, P&L, SL/TP, strategy, age); engine and feed status |
| Trades | Server-paginated history; filters (instrument, strategy, side, outcome, exit reason, regime, date range) synced to URL; per-trade detail: signal → risk decision → order → fill → exit timeline, SL/TP, R-multiple, MAE/MFE, regime, meta score + model version, allocator weight, candle chart with entry/exit markers |
| Strategies | Per-strategy performance (trades, win rate, expectancy R, profit factor, max DD) overall and by regime; current regime per instrument; bandit weights (regime × strategy) and history; enable/disable |
| Learning | Model versions with status (champion/challenger/retired/rejected), metrics, training window, sample count; champion vs challenger comparison; drift alerts; manual promote/rollback/retrain (confirmed, still guardrailed server-side) |
| Risk | Each limit vs current usage (daily/weekly loss, drawdown, open trades, currency exposure, margin); entry-pause reasons; risk event log; kill switch engage/release; pause/resume entries |
| Backtests | Start a run (strategies, instruments, range, data source, seed, cost model); progress via WS; results: metrics, equity + drawdown chart, trades, provenance |
| Settings | Mode read-only with how-to-change note; instruments; risk params within server hard caps; paper data feed; secrets shown only as configured / not configured |

**Acceptance criteria.**

- [ ] `pages/*/*.test.tsx` for every page: loading, empty, error and populated states with a
      mocked API client.
- [ ] `pages/Overview/Overview.test.tsx`: a WS `positions` event updates the table without refetch.
- [ ] `pages/Trades/Trades.test.tsx`: filters round-trip through the URL; detail view renders
      the full decision timeline.
- [ ] `pages/Risk/Risk.test.tsx`: kill switch engages in at most two clicks (button + confirm,
      no typing, per SR-40); release requires typed confirmation; buttons disabled while the
      request is in flight.
- [ ] `pages/Settings/Settings.test.tsx`: no input exists for any secret; mode is not editable;
      out-of-range risk value shows the server's 422 message.
- [ ] `pages/Backtests/Backtests.test.tsx`: results show data source, seed and cost model.
- [ ] `lib/ws.test.ts`: reconnects with backoff, resubscribes, drops out-of-order `seq`.
- [ ] `api/client.test.ts`: 401 → session cleared and redirect to login.
- [ ] Mode badge visible on every page; `live` rendered in a distinct high-contrast style.
- [ ] Every performance number shows its provenance (journal mode or backtest run ID).
- [ ] P&L sign conveyed by text (+/−), not colour alone; all controls keyboard reachable.
- [ ] Build check: `dist/` contains no `OANDA_` strings or token-like values; only `VITE_`
      variables are read in source.

**Risks.** Type drift between backend schemas and TS types (see open decision in STATUS.md);
WS flood re-rendering charts (throttle server-side, batch client-side); accidental destructive
clicks (confirm dialogs).

---

## Stage 7 — Security hardening, deployment, docs, end-to-end paper run

**Objective.** A clean clone becomes a running, hardened paper-trading system with one command,
proven by an observed end-to-end run.

**In scope.** Fixes from security reviews; container images; docker compose; CI extensions;
runbook and README; E2E paper run with drills.
**Out of scope.** Enabling `live` trading (the user's decision, on their machine); cloud hosting.

**Deliverables.** Final `backend/Dockerfile` (slim, non-root, single worker, healthcheck),
`frontend/Dockerfile` (multi-stage build → nginx), `frontend/nginx.conf` (SPA, `/api` and `/ws`
proxy, security headers), final `docker-compose.yml` (backend, frontend, `fxbot-data` volume,
ports bound to 127.0.0.1), final `backend/.env.example`, CI image-build + compose-smoke job, `docs/RUNBOOK.md` (start/stop,
backups, kill switch, practice checklist, go-live checklist), updated `README.md` and
`docs/SECURITY.md` (security), final `docs/STATUS.md`.

**Acceptance criteria.**

- [ ] All security-review findings from stages 1, 5, 6 closed or explicitly accepted in
      `docs/SECURITY.md`.
- [ ] From a clean clone: `cp backend/.env.example backend/.env && docker compose up -d --build`
      → dashboard on `http://127.0.0.1:8080`, login works, mode `paper`, synthetic feed running.
- [ ] CI compose-smoke job: images build, stack starts, `GET /api/health` via nginx returns 200.
- [ ] Containers run as non-root; all published ports bind to 127.0.0.1; the browser reaches
      the API only through nginx (same origin); nginx sends the headers required by
      `docs/SECURITY.md`.
- [ ] E2E paper run ≥ 24 h (synthetic feed, short granularity) with a written report in
      `docs/STATUS.md`: zero unhandled exceptions; zero unresolved reconciliation discrepancies;
      every trade had a stop; journal P&L equals paper balance change exactly.
- [ ] Restart drill: `docker compose restart backend` mid-run → state recovered, no duplicate
      orders, positions reconciled.
- [ ] Kill-switch drill: engage from the UI → flat within 5 s, no new orders until release.
- [ ] Feed drill: interrupt the feed → entries paused, alert shown, recovery with backfill.
- [ ] Backup/restore of the SQLite volume documented and tested once.
- [ ] `README.md` quick start verified by someone who did not write it.

**Risks.** Long-run issues (memory growth, log volume, DB growth) only show in the soak; nginx WS
proxy misconfiguration; OANDA practice soak can only run on the user's machine.
