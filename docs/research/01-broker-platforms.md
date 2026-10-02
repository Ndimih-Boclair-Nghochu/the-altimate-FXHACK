# 01 — Broker platform comparison and adapter recommendation

Status: research input for Stage 1 (broker connectivity) and the broker-agnostic `Broker` protocol.

**Bottom line.**

1. **Primary adapter: OANDA v20.** It has the cleanest API for our stack (REST + newline-delimited JSON streaming, Bearer token), free practice accounts with full API access, 1-unit position sizing, stop-loss/take-profit attached on fill, and good recorded fixtures for offline tests.
2. **Big caveat:** a developer.oanda.com excerpt says the v20 REST API is **not available to OANDA Global Markets (BVI) or OANDA TMS Brokers (EU/Poland) accounts**. OANDA Global Markets is the entity that usually serves clients outside the US, UK, Canada, Australia, Singapore and Japan. Several third-party lists also say OANDA does not onboard residents of Nigeria, South Africa and other countries. A user in Africa may therefore be able to **develop against OANDA practice but not trade live through the OANDA API**.
3. **Secondary adapter, to add next: cTrader Open API.** It is broker-neutral (many brokers worldwide, including some that accept African residents), runs on Linux, offers JSON over WebSocket (port 5036) as well as Protobuf, has free demo accounts, and supports SL/TP attached to market orders.
4. **Possible third adapter:** MT5 through a Windows-hosted bridge, because in some regions MT5 is the only platform offered. Interactive Brokers suits larger accounts in countries it serves.

---

## 1. Comparison table

Legend: ✅ good / ⚠️ caveat / ❌ poor for our use. "Evidence" columns cite sources (§6). Spreads and costs change often and differ by entity. Treat them as orders of magnitude.

| Criterion | OANDA v20 | Interactive Brokers | MetaTrader 5 | cTrader Open API | Saxo OpenAPI | FXCM |
|---|---|---|---|---|---|---|
| API style | REST/JSON + HTTP chunked NDJSON streams (prices, transactions) [O1] ✅ | TWS API: proprietary socket to a locally running TWS / IB Gateway. Client Portal Web API: REST + WebSocket through a local Java gateway [I1][I3] ⚠️ | Python package talks IPC to a running MT5 terminal. **Windows only** (PyPI wheels: `win_amd64` only, v5.0.6231, 2026-09-27) [M1] ❌ on Linux | Protobuf (port 5035) or **JSON (port 5036)** over TCP or WebSocket. Hosts `demo.ctraderapi.com`, `live.ctraderapi.com` [C1][C2] ✅ | REST + WebSocket streaming, OAuth2 [S1] ✅ | REST + socket.io (`fxcmpy`), ForexConnect SDK, FIX, Java [F1] ⚠️ |
| Auth | Personal access token (Bearer). Practice/live tokens separate | TWS: login + 2FA in the GUI/Gateway. CP Web API: browser login, **re-authenticate daily**, session times out after 5 min without `/tickle` [I3] ❌ for unattended | Terminal login (account + password) | OAuth2 app (client id/secret) + account access token. Refresh tokens [C1] | OAuth2. 24-hour developer token for SIM [S1] | API token |
| Demo account | ✅ free practice account, full API access [O3] | ⚠️ paper account normally tied to a (funded) IBKR account. A free trial exists (**UNVERIFIED** details) | ✅ free at almost every MT5 broker | ✅ free cTrader demo (cTrader ID) at most cTrader brokers | ✅ SIM environment, simulated $100k [S1] | ✅ |
| Reliability / ops | Stable API since ~2016. Official SDKs unmaintained since 2018 (`v20` 3.0.25.0, 2018-09-28 on PyPI), but the API itself is stable | Gateway designed for **daily restart**. Auto-restart can avoid re-auth Sun→Sun [I2] | Terminal + Wine/VM = extra moving parts. Symbol names vary by broker (suffixes) | Hosted by Spotware for all brokers. One app can serve many brokers/accounts | Mature bank API | `fxcmpy` **deleted from PyPI** (name now a security placeholder package) [F2]. ForexConnect Linux wheels only for Python ≤ 3.7 [F3] ❌ |
| Regulation | Per entity: CFTC/NFA (US), FCA (UK), KNF (Poland, OANDA TMS), ASIC, CIRO, MAS, JFSA, BVI FSC (OANDA Global Markets) [O4] | SEC/FINRA/CFTC, FCA, CBI, ASIC, MAS, SFC… (multi-entity) | Depends on the broker | Depends on the broker | Danish FSA (Saxo Bank A/S) + local entities | FCA, ASIC, CySEC (non-US. FXCM left the US market in 2017) |
| Global availability (Africa) | ⚠️ Restricted-country list varies by entity. Third-party lists say **Nigeria and South Africa are not served** [O5]. **REST API not available for OANDA Global Markets / TMS accounts** [O2]. Check by entering the country on OANDA's sign-up page. | ✅ broad. IBKR's country list includes e.g. Kenya, South Africa, Ghana, Egypt, Morocco, Cameroon, Senegal, Tanzania, Uganda, Zambia. **Not Nigeria** (IBKR statement 2025) [I4] | ✅ widest: most retail brokers, including African-regulated ones (e.g. FSCA, CMA) | ✅ many brokers (IC Markets, Pepperstone, FxPro, etc. offer cTrader). Availability is per broker/entity | ⚠️ many countries, but not all. Higher minimums | ⚠️ varies |
| Typical EUR/USD cost | Standard account spread-only, ~0.9–1.7 pips by third-party 2026 reviews [O6]. Our own measurement of OANDA bid/ask H1 data 2007–2018: median 1.2–1.4 pips (see `07-data-sources.md`). "Core" pricing: tighter spread + commission | IDEALPRO: ~interbank spread + **0.20 bp of trade value, min USD 2.00 per order** (Pro, tier I) [I5]. Orders under USD 25k are "odd lots" with different handling [I6] | Broker-specific | Raw spread + commission (typically ~USD 3 per 100k per side at common brokers, **UNVERIFIED** per broker) | Tiered by account size | Spread-based |
| Rate limits | 120 req/s per IP. 20 streams. 2 new connections/s. HTTP 429 [O1] | 50 msgs/s (depends on market-data lines). Historical: 60 requests / 10 min [I2] | Local terminal | 50 req/s per connection (non-historical), 5 req/s (historical). Error `BLOCKED_PAYLOAD_TYPE` with `retryAfter` [C3][C4] | 120 req/min per session per service group. **1 order/s**. 10M req/day per app [S2] | — |
| Order types we need | MARKET (FOK/IOC) with `priceBound`, `stopLossOnFill`, `takeProfitOnFill`, `trailingStopLossOnFill`. Modify SL/TP per trade (`PUT /trades/{id}/orders`) ✅ | Bracket orders (parent + TP + SL), trailing, OCA ✅ | `order_send` DEAL with `sl`/`tp` fields ✅ | `ProtoOANewOrderReq` with `relativeStopLoss`/`relativeTakeProfit` (in 1/100000 of price), `trailingStopLoss` flag, `guaranteedStopLoss` [C4] ✅ | Related orders (SL/TP) attached ✅ | ✅ |
| Position granularity | **1 unit** (`minimumTradeSize "1"`, `tradeUnitsPrecision 0`) ✅ best for small accounts | Any size, but < 25k odd-lot handling and a USD 2 min commission ❌ for small accounts | Usually 0.01 lot = 1,000 units | Broker-specific (often 0.01 lot = 1,000 units) | Broker minimums | 1k units (micro) |
| Python SDK maturity | Official `v20` (2018, sync `requests`). `oandapyV20` 0.7.2 (2021). `async_v20` (2019 beta). **Plan: own thin `httpx` client** (spec in `02-oanda-v20-api-spec.md`) | `ibapi` (official, licence restrictions). `ib_async` 2.1.0 (2025-12, maintained community fork). `ib_insync` last release 2023-07 | `MetaTrader5` official (Windows). `mt5linux` 1.1.1 (2026-08, Wine + RPyC bridge) [M2] | `ctrader-open-api` 0.9.2 (2024-06, Twisted-based) [C5]. Or our own asyncio JSON-over-WebSocket client | Community `saxo-openapi` 0.6.0 (2019) | `fxcmpy` gone. `forexconnect` 1.6.43 (2022) |
| Fit for Altimate FX | **Primary** | Later, for larger accounts | Optional bridge adapter | **Secondary** | Later / optional | ❌ Not recommended |

## 2. Recommendation and reasons

### Primary: OANDA v20

- **Developer experience:** plain HTTPS + JSON fits `httpx` + Pydantic. Streaming is newline-delimited JSON, trivial to parse and to fake in tests.
- **Free practice environment with the same API** as live (`api-fxpractice.oanda.com`), which is exactly the `practice` mode of our safety ladder.
- **Precise sizing:** 1-unit granularity means risk-based position sizing works even on very small accounts (a 0.25%-risk trade on a $500 account is possible). MT4/MT5/cTrader brokers usually have 1,000-unit minimum steps, and IBKR has a USD 2 minimum commission.
- **Server-side SL/TP attached on fill** removes the "naked position" window between fill and stop placement.
- **Offline testing:** official OpenAPI spec + many recorded fixtures (see `02`).

### Secondary: cTrader Open API

- **Solves the availability problem:** the same API works with any broker that offers cTrader. A user who cannot get OANDA API access in their country can pick a regulated cTrader broker that accepts them.
- **Linux-native and asyncio-friendly:** the JSON protocol on port 5036 over WebSocket means we can use the `websockets` library without Twisted or protobuf code generation. (Protobuf on 5035 remains an option for performance.)
- **Feature parity:** market orders with relative SL/TP, trailing flag, amend SL/TP, spot subscriptions, trendbars (historical candles), execution events.
- **Costs:** raw-spread + commission accounts are common. They scale with size, unlike IBKR's per-order minimum.
- **Caveats:** OAuth2 app registration at `openapi.ctrader.com` is required. Prices and volumes are integers in protocol units: spot `bid`/`ask` and `relativeStopLoss`/`relativeTakeProfit` are "in 1/100000 of unit of a price", and `volume` is "represented in 0.01 of a unit (e.g. 1000 in protocol means 10.00 units)". Absolute `stopLoss`/`takeProfit` are "Not supported for MARKET orders", so use the relative fields. `clientOrderId` (max 50 chars) and `label` (max 100) are available for idempotency and tagging (all from comments in `OpenApiMessages.proto` [C4]). Historical requests are limited to 5 req/s.

### Why not the others as secondary

- **MT5:** the official package is Windows-only, so on our Linux/Docker stack we would need Wine (`mt5linux`) or a Windows VM with a REST/ZeroMQ bridge, or a paid cloud bridge (e.g. MetaApi). That is fragile and hard to test. Still, MT5 is the most widely available retail platform. Keep it as an optional third adapter behind the same `Broker` protocol, running as a separate "bridge" service on a Windows host.
- **Interactive Brokers:** excellent regulation and broad country coverage (not Nigeria). But (a) the unattended auth story is poor: daily Gateway restarts, a CP Web API that needs daily browser re-auth, and pacing limits; (b) the USD 2 minimum commission makes small trades expensive (for a 5,000-unit EUR/USD trade, USD 2 per side ≈ 4 bps ≈ 0.4 pip per side on top of the spread), and odd lots below USD 25k are handled differently. Good for accounts of roughly USD 25k and up, later.
- **Saxo:** solid, but 1 order/s and 120 req/min limits, OAuth2 complexity, no official Python SDK, and higher minimum deposits.
- **FXCM:** `fxcmpy` has been removed from PyPI (the name is now an empty security-holding package), and ForexConnect's Linux wheels stop at Python 3.7. Not viable for Python 3.11+.

## 3. Regional availability: what is known and what the user must check

Known (with sources):

- OANDA serves clients through regulated entities in the US, Canada, UK, EU (OANDA TMS Brokers, Poland), Australia, Singapore and Japan, and through **OANDA Global Markets Ltd (BVI)** for other countries [O4].
- Excerpt from developer.oanda.com: "The v20 REST API is available to all divisions except OANDA Global Markets and OANDA TMS BROKERS S.A." [O2]. Implication: users onboarded by OANDA Global Markets (typical for Africa, Latin America and parts of Asia) or OANDA TMS (EU) may not be able to use the REST API for **live** trading.
- Third-party lists (TradersUnion) say OANDA does not provide services in Nigeria and South Africa, among others [O5]. These lists can be out of date. OANDA's own help page says eligibility is decided by the country entered at registration [O5b].
- IBKR's official country page lists many African countries (Kenya, South Africa, Ghana, Egypt, Morocco, Cameroon, Senegal, Uganda, Tanzania, Zambia, …). IBKR stated on X in 2025 that it does **not** serve residents of Nigeria [I4].

Checklist for the user (put this in the README / setup docs):

1. Open an **OANDA practice** account and generate a practice token. This is enough for paper → practice development regardless of the live situation. Confirm that practice sign-up works for your country (**UNVERIFIED** whether practice sign-up is restricted by country).
2. For live trading, before funding anything, confirm in writing with the broker:
   - Which legal entity will hold your account, and its regulator. Prefer a regulator you can complain to: FCA, ASIC, CySEC/ESMA, CFTC/NFA, FSCA (South Africa), CMA (Kenya), etc.
   - That **API trading is enabled** for that entity (for OANDA: does the account support "Manage API Access"?).
   - Leverage caps, negative balance protection, and the financing (swap) schedule.
   - Deposit/withdrawal methods and currency-control rules in your country.
3. If OANDA live API is unavailable: pick a regulated **cTrader** broker that accepts your country (secondary adapter), or an MT5 broker and use the bridge adapter.
4. Check local law: some countries restrict leveraged FX/CFD trading with offshore brokers or capital outflows. This research cannot verify each country's rules.

## 4. Adapter design implications (for ARCHITECTURE.md)

- The `Broker` protocol must not leak OANDA concepts. Use domain types: `Instrument(symbol="EUR_USD", pip_size, price_precision, units_step, min_units, margin_rate)`, `OrderRequest(side, units, stop_loss_price, take_profit_price, max_slippage, client_id)`, `OrderResult(status=FILLED|CANCELLED|REJECTED|UNKNOWN, ...)`.
- **Capability flags** per adapter: `supports_sl_on_fill`, `supports_trailing_stop`, `supports_hedging`, `units_step`, `fifo_required` (US accounts), `max_orders_per_second`.
- **Idempotency key** (`client_id`) is a first-class field. OANDA maps it to `clientExtensions.id` and `tradeClientExtensions.id`. cTrader maps it to `clientOrderId` (max 50 chars) and `label` (max 100) in `ProtoOANewOrderReq`.
- Symbol mapping per adapter (`EUR_USD` ↔ `EURUSD` ↔ broker-suffixed MT5 names).
- All adapters expose `get_candles(symbol, granularity, start, end, price="BA")` returning **closed bars only**.

## 5. Things that could change this recommendation

- If OANDA confirms API access for the user's actual entity and country, OANDA can stay the only live adapter for a long time.
- If the user's only accessible regulated broker is MT5-only, prioritize the MT5 bridge over cTrader.
- If account size grows beyond roughly USD 25–50k, IBKR becomes cost-competitive and attractive for counterparty safety.

## 6. Sources

- [O1] OANDA Development Guide / Best Practices (rate limits: 120 req/s, HTTP 429, 20 streams, 2 new connections/s), seen via search excerpts: https://developer.oanda.com/rest-live-v20/development-guide , https://developer.oanda.com/rest-live-v20/best-practices/
- [O2] OANDA v20 Introduction, "available to all divisions except OANDA Global Markets and OANDA TMS BROKERS S.A." (search excerpt): https://developer.oanda.com/rest-live-v20/introduction/
- [O3] Practice environment and token generation: https://www.oanda.com/sg-en/platforms/rest-api/ ; QuantStart OANDA tutorial: https://www.quantstart.com/articles/Forex-Trading-Diary-1-Automated-Forex-Trading-with-the-OANDA-API/
- [O4] OANDA entities and regulators (review summaries): https://www.forexbrokers.com/reviews/oanda , https://www.tradingpedia.com/forex-brokers/oanda/ ; OANDA "where we are": https://www.oanda.com/group/about-us/where-we-are/
- [O5] Third-party restricted-country list: https://tradersunion.com/brokers/forex/view/oanda/available-countries/ ; [O5b] OANDA help "unable to offer accounts to residents of this country": https://help.oanda.com/none/en/unsupported.htm
- [O6] OANDA spread reviews (2026): https://www.compareforexbrokers.com/us/oanda-review/ , https://brokeranalysis.com/broker-review/oanda/fees/
- [I1] TWS API introduction: https://interactivebrokers.github.io/tws-api/introduction.html
- [I2] TWS API pacing and historical limits, daily restart: https://interactivebrokers.github.io/tws-api/historical_limitations.html , https://www.interactivebrokers.com/docs/tws-api/doc/pacing-limitations/introduction , https://interactivebrokers.github.io/tws-api/initial_setup.html
- [I3] Client Portal Gateway FAQ (daily re-authentication, `/tickle`, 5-minute timeout): https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/client-portal-gateway-faq , https://www.interactivebrokers.com/docs/web-api/authentication/faq
- [I4] IBKR available countries: https://www.interactivebrokers.com/en/accounts/open-account-country-list.php ; IBKR on Nigeria (2025): https://x.com/IBKR/status/1937631690534293796
- [I5] IBKR spot currency commissions (0.20 bp, min USD 2.00, Pro tier I): https://www.interactivebrokers.com/en/pricing/commissions-spot-currencies.php
- [I6] IDEALPRO order sizes / odd lots: https://www.ibkrguides.com/kb/article-1708.htm , https://www.interactivebrokers.com/en/trading/SpecialOrderTypes.php
- [M1] PyPI `MetaTrader5` (wheels win_amd64 only), checked 2026-10-02: https://pypi.org/project/MetaTrader5/
- [M2] `mt5linux` (Wine + RPyC): https://pypi.org/project/mt5linux , https://github.com/Olamidipupo-favour/mt5linux
- [C1] cTrader Open API endpoints (`EndPoints` in the official Python SDK: `demo.ctraderapi.com`, `live.ctraderapi.com`, port 5035, OAuth URIs `https://openapi.ctrader.com/apps/auth|token`): https://github.com/spotware/OpenApiPy/blob/main/ctrader_open_api/endpoints.py
- [C2] Protobuf vs JSON ports 5035/5036, TCP and WebSocket: https://help.ctrader.com/open-api/proxies-endpoints/ , https://help.ctrader.com/open-api/protocol-buffers-json/
- [C3] cTrader rate limits (50 req/s, 5 req/s historical): https://help.ctrader.com/open-api/ , community threads https://community.ctrader.com/forum/connect-api-support/41177/
- [C4] cTrader proto messages (`ProtoOANewOrderReq.relativeStopLoss/relativeTakeProfit/trailingStopLoss/guaranteedStopLoss`, `retryAfter` on `BLOCKED_PAYLOAD_TYPE`): https://github.com/spotware/openapi-proto-messages
- [C5] PyPI `ctrader-open-api` 0.9.2: https://pypi.org/project/ctrader-open-api/
- [S1] Saxo environments, SIM and 24-hour token: https://developer.saxobank.com/openapi/learn/environments
- [S2] Saxo rate limits: https://openapi.help.saxo/hc/en-us/articles/4417694856849-How-do-I-avoid-exceeding-my-rate-limit-
- [F1] FXCM API overview: https://github.com/fxcm , https://www.fxcm.com/markets/algorithmic-trading/api-trading/
- [F2] PyPI `fxcmpy` now a "Security Holding Package" placeholder (checked 2026-10-02): https://pypi.org/project/fxcmpy/
- [F3] PyPI `forexconnect` 1.6.43 wheel list (Linux cp35–cp37 only): https://pypi.org/project/forexconnect/
- ESMA/NFA leverage rules: see `04-risk-management.md`.
