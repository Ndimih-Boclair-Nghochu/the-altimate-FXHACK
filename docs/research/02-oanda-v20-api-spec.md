# 02 — OANDA v20 REST/Streaming API: implementation reference

Status: research reference for the `brokers/oanda/` adapter (Stage 1).
Written without access to `developer.oanda.com` (blocked from the build container). Every
shape below comes from one of the primary sources listed in §0, and each example payload
says where it was copied from. Anything that could not be confirmed from a primary
source is marked **UNVERIFIED**.

---

## 0. Sources and how much to trust them

| Tag | Source | What it gives us | Trust |
|---|---|---|---|
| [SPEC] | OANDA's official OpenAPI 2.0 spec, `oanda/v20-openapi`, `json/v20.json`, version **3.0.25** (last commit 2018-09-28, `70324cf`). https://github.com/oanda/v20-openapi | Every path, parameter, response schema, enum | High for shapes. It is from 2018, so fields added later are missing (see §11). |
| [PY] | Official Python SDK `oanda/v20-python` (v3.0.25.0). https://github.com/oanda/v20-python | Headers, stream parsing, SDK defaults, docstrings | High |
| [HOOT] | `hootnot/oanda-api-v20` (oandapyV20 0.7.2) response fixtures `oandapyV20/endpoints/responses/*.py`. https://github.com/hootnot/oanda-api-v20 | Real JSON responses (from OANDA's own doc examples and the author's practice account) | High for shape. Fixtures date from 2016. |
| [AV20] | `jamespeterschinner/async_v20` test data `tests/data/json_data.py` and parameter docstrings `async_v20/endpoints/annotations.py`. https://github.com/jamespeterschinner/async_v20 | Recorded practice-account payloads (2017–2018, UNIX time format) and parameter defaults copied from the developer docs | High |
| [NB1] | Recorded practice-account output in `anthonyng2/oanda_2018`, notebook `oandapyV20/04.00 Order Management.ipynb`. https://github.com/anthonyng2/oanda_2018 | A complete MARKET-order fill response (2018-06-27) | High (real output) |
| [NB2] | `anthonyng2/FX-Trading-with-Python-and-Oanda`, notebook `Oanda v20 REST-oandapyV20/05.00 Trade Management.ipynb`. https://github.com/anthonyng2/FX-Trading-with-Python-and-Oanda | A real `MARKET_HALTED` cancel response (2017-01-28) | High (real output) |
| [ISS149] | hootnot issue #149. https://github.com/hootnot/oanda-api-v20/issues/149 | A real `400` reject body (`TAKE_PROFIT_ON_FILL_PRICE_PRECISION_EXCEEDED`) | Medium (shown abridged in the issue) |
| [BLANK] | `blankly-finance/blankly`, `blankly/exchanges/interfaces/oanda/oanda_interface.py` docstring. https://github.com/blankly-finance/blankly | A newer instrument object with `financing`, `tags`, `guaranteedStopLossOrderMode` | Medium |
| [DEVG] | developer.oanda.com "Development Guide", "Best Practices", "Introduction" pages, seen through web-search excerpts only (pages not fetchable here). https://developer.oanda.com/rest-live-v20/development-guide/ , https://developer.oanda.com/rest-live-v20/best-practices/ , https://developer.oanda.com/rest-live-v20/introduction/ | Rate limits, division availability | Medium (excerpts, not full text) |

---

## 1. Environments, hosts and ports

| Environment | REST base URL | Streaming base URL |
|---|---|---|
| practice (demo, "fxTrade Practice") | `https://api-fxpractice.oanda.com` | `https://stream-fxpractice.oanda.com` |
| live ("fxTrade") | `https://api-fxtrade.oanda.com` | `https://stream-fxtrade.oanda.com` |

Source: `TRADING_ENVIRONMENTS` in [HOOT] `oandapyV20/oandapyV20.py`. All paths below are
under `/v3` (the [SPEC] `basePath` is `/v3`, scheme `https`, port 443).

- Only these two path groups go to the **stream** host: `GET /v3/accounts/{accountID}/pricing/stream` and
  `GET /v3/accounts/{accountID}/transactions/stream`. Everything else goes to the REST host.
- Tokens are environment-specific. A practice token does not work against the live host. (Commonly
  documented; **UNVERIFIED** from a primary source here.)
- **Division availability (important for non-US/EU users).** A developer.oanda.com excerpt
  [DEVG introduction] says the v20 REST API is "available to all divisions except OANDA Global
  Markets and OANDA TMS BROKERS S.A.". OANDA Global Markets (BVI) is the entity that usually serves
  clients outside the US/UK/EU/Canada/Australia/Singapore/Japan. So a live account opened
  from Africa or other emerging markets may **not** have REST API access. See
  `01-broker-platforms.md` §3.

Configuration (pydantic-settings) the adapter should expose:

```python
class OandaSettings(BaseSettings):
    oanda_env: Literal["practice", "live"] = "practice"
    oanda_api_token: SecretStr            # never logged
    oanda_account_id: str | None = None   # auto-discover via GET /v3/accounts if None
    oanda_rest_url: AnyHttpUrl | None = None    # override for tests
    oanda_stream_url: AnyHttpUrl | None = None
    oanda_datetime_format: Literal["RFC3339", "UNIX"] = "RFC3339"
```

## 2. Request headers

| Header | Value | Source |
|---|---|---|
| `Authorization` | `Bearer <token>` | [PY] `Context.set_token`; [HOOT] |
| `Content-Type` | `application/json` (all requests that have a body) | [PY] `Context._headers` |
| `Accept-Datetime-Format` | `RFC3339` or `UNIX` | [PY] `set_datetime_format` accepts exactly these two; [SPEC] `acceptDatetimeFormatHeaderParam` |
| `Accept-Encoding` | `gzip, deflate` (recommended, large candle pages) | [HOOT] `DEFAULT_HEADERS` |
| `OANDA-Agent` | optional free text, the SDK sends `v20-python/3.0.25 (<app>)` | [PY] |

Response headers worth reading:

- `RequestID` on every response ([SPEC]). Log it with every error, so OANDA support can trace it.
- `Location` on `201` order creation and position close ([SPEC]).
- `Link` on paginated list endpoints (`/trades`, `/orders`) for the next page ([SPEC]).

Datetime formats ([SPEC] `DateTime` format description):

- `RFC3339`: `"2018-06-27T09:36:12.964984863Z"`. Nanosecond precision. Python `datetime` only
  holds microseconds, so truncate to 6 digits when parsing and keep the raw string if exact
  ordering matters.
- `UNIX`: `"1512446222.248676455"` (string, seconds since epoch, up to 9 decimals). See [AV20]
  payloads.

**Recommendation:** use `RFC3339` everywhere and parse with a helper that truncates
nanoseconds (`2018-06-27T09:36:12.964984863Z` → `2018-06-27T09:36:12.964984+00:00`).

## 3. Wire conventions the domain layer must handle

1. **Decimals are JSON strings.** Prices (`PriceValue`), amounts (`AccountUnits`), `units`,
   rates (`DecimalNumber`) are strings ([SPEC] definitions). Parse to `decimal.Decimal`, never
   `float`. (The official SDK converts to float by default, `decimal_number_as_float=True`
   [PY]; we should not.)
2. **Trailing zeros are not guaranteed.** Recorded payloads contain `"1.2018"` for a 5-dp
   instrument and `"0.766"` for AUD/USD ([AV20] `stream_price`, `GETInstrumentsCandles_response`).
   Do not infer precision from the response string. Get it from the instrument spec.
3. **IDs are strings** of integers (`"6390"`), but some recorded payloads contain integers
   (`"tradeID": 4956` in [AV20] account-changes data; `userID` is always an integer).
   Accept `str | int` and normalize to `str`.
4. **`liquidity` type varies:** integer in `/pricing` and the stream ([HOOT] pricing fixtures), but a
   string (`"10000000"`) inside `orderFillTransaction.fullPrice` ([NB1]). Accept both.
5. **Units sign = direction:** `"units": "100"` is a long/buy, `"-100"` is a short/sell ([SPEC]
   `MarketOrderRequest.units`). For FX `tradeUnitsPrecision` is `0`, so units are integers.
6. **Instrument names** use an underscore: `EUR_USD`, `USD_JPY` ([SPEC] `InstrumentName`). One recorded
   candle response returned `"instrument": "DE30/EUR"` with a slash ([HOOT] candles fixture).
   Treat the request's instrument as the source of truth.
7. **Deprecated but present fields:** `ClientPrice.status` (`tradeable|non-tradeable|invalid`)
   still appears beside the boolean `tradeable` ([AV20] `stream_price` has both). Use
   `tradeable`. Fall back to `status == "tradeable"` if the boolean is missing (older
   fixtures in [HOOT] have only `status`). `OrderFillTransaction.price` is documented as
   deprecated ([SPEC]). Use `tradeOpened.price` / `tradesClosed[].price` / `tradeReduced.price`.

## 4. Error format and HTTP status codes

Every non-2xx response body ([SPEC] responses) is:

```json
{ "errorCode": "OPTIONAL_MACHINE_CODE", "errorMessage": "Human readable text" }
```

`errorCode` "may not be returned for some errors" ([SPEC]). Order endpoints add transaction
fields (see §6.7). Real examples:

```text
400 {"errorMessage":"Invalid value specified for 'order.instrument'"}
```
Source: [HOOT] `docs/oanda-api-v20.rst` log line (practice account, 2016).

```json
{"errorMessage": "Invalid value specified for 'instruments'"}
```
Source: [AV20] `tests/test_interface/test_parser.py`.

| HTTP | Meaning (per [SPEC]) | Adapter action |
|---|---|---|
| 200 / 201 | OK / created | Parse. **201 on order create does not mean filled** (§6.7). |
| 400 | Bad request / order rejected (`orderRejectTransaction` present on order endpoints) | Do not retry unchanged. Map `errorCode` to a domain `OrderRejected`. |
| 401 | Token invalid or missing | Stop. Raise `BrokerAuthError`. Alert. Never retry in a loop. |
| 403 | Token not authorized for this action/account | Same as 401. |
| 404 | Account/trade/order/instrument not found | Domain `NotFound`. On order endpoints may carry `orderRejectTransaction`. |
| 405 | Wrong method | Programming error. |
| 416 | Range not satisfiable (transactions/changes with bad ID range) | Re-sync from `lastTransactionID` (§9). |
| 429 | Rate limited ([DEVG]: "excess requests will receive HTTP 429") | Back off with jitter. Body shape **UNVERIFIED**. |
| 5xx / connection reset / timeout | Server or network | Retry **GET only** (exponential backoff 0.5s → 8s, max 5). For **POST/PUT order calls never blind-retry**. Reconcile instead (§9). |

## 5. Rate and connection limits

From developer.oanda.com, via search excerpts [DEVG]:

- REST: **120 requests per second** per IP. Excess gets **HTTP 429**.
- Streaming: **20 active streams** per IP. Requests above that are rejected.
- **2 new connections per second** max. Excess connections are rejected.
- Best Practices page: on a persistent connection, keep to ~100 requests/s, and reuse
  connections (HTTP keep-alive).

Pricing stream behaviour ([PY] `pricing.stream` docstring, i.e. OANDA's own text): "at most 4
prices per second (every 250 milliseconds) for each instrument". If several prices occur in the
window only the last is sent, and windows are not aligned across connections.
Heartbeats: about every **5 s** (excerpts from the Pricing page and third-party clients;
**UNVERIFIED** from a primary source).

**Adapter defaults:** one shared `httpx.AsyncClient` per host with keep-alive. A token-bucket
limiter at **20 req/s** (far below the limit, and we never need more). Exactly **one** pricing
stream (all instruments in one request) and **one** transaction stream. Reconnect delay: start at
1 s, double up to 30 s, add jitter. Never reconnect faster than 2/s.

## 6. Endpoints

All examples: `{acct}` = account ID like `101-004-1435156-001` (format
`{siteID}-{divisionID}-{userID}-{accountNumber}` [SPEC]).

### 6.1 List accounts — `GET /v3/accounts`

Response 200 ([SPEC] `accounts: [AccountProperties]`, `AccountProperties = {id, mt4AccountID?, tags}`):

```json
{
  "accounts": [
    { "id": "101-004-1435156-002", "tags": [] },
    { "id": "101-004-1435156-001", "tags": [] }
  ]
}
```
Source: [HOOT] `endpoints/responses/accounts.py` `_v3_accounts`.

If `mt4AccountID` is present the account is an MT4 account. Do **not** set `clientExtensions`
on MT4 accounts ([SPEC] `ClientExtensions` description). Refuse such accounts in the adapter.

### 6.2 Account summary — `GET /v3/accounts/{acct}/summary`

Response 200: `{ "account": AccountSummary, "lastTransactionID": "..." }` ([SPEC]).

```json
{
  "account": {
    "marginCloseoutNAV": "35454.4740",
    "marginUsed": "10581.5000",
    "currency": "EUR",
    "resettablePL": "-13840.3525",
    "NAV": "35454.4740",
    "marginCloseoutMarginUsed": "10581.5000",
    "marginCloseoutPositionValue": "211630.0000",
    "openTradeCount": 2,
    "id": "101-004-1435156-001",
    "openPositionCount": 1,
    "marginCloseoutPercent": "0.14923",
    "marginCallMarginUsed": "10581.5000",
    "hedgingEnabled": false,
    "positionValue": "211630.0000",
    "pl": "-13840.3525",
    "lastTransactionID": "2123",
    "marginAvailable": "24872.9740",
    "marginRate": "0.05",
    "marginCallPercent": "0.29845",
    "pendingOrderCount": 0,
    "withdrawalLimit": "24872.9740",
    "unrealizedPL": "0.0000",
    "alias": "hootnotv20",
    "createdByUserID": 1435156,
    "marginCloseoutUnrealizedPL": "0.0000",
    "createdTime": "2016-06-24T21:03:50.914647476Z",
    "balance": "35454.4740"
  },
  "lastTransactionID": "2123"
}
```
Source: [HOOT] `accounts.py` `_v3_account_by_accountID_summary` (Python `False` rendered as JSON `false`).

Map to the domain `AccountSummary`: `currency` (home currency), `balance`, `NAV` (equity),
`unrealizedPL`, `marginUsed`, `marginAvailable`, `marginCloseoutPercent` (≥ 1.0 means
closeout [SPEC]), `marginCallPercent` (≥ 1.0 means margin call [SPEC]), `openTradeCount`,
`hedgingEnabled`, `lastTransactionID`. Other fields in [SPEC] `AccountSummary`:
`guaranteedStopLossOrderMode` (`DISABLED|ALLOWED|REQUIRED`), `financing`, `commission`,
`marginCallEnterTime`, `lastOrderFillTimestamp`.

**Risk use:** the risk engine should treat `marginCloseoutPercent > 0.5` as a hard stop for new
orders (our own guardrail, far before the broker's 1.0 closeout).

### 6.3 Account instruments — `GET /v3/accounts/{acct}/instruments[?instruments=EUR_USD,USD_JPY]`

Query `instruments` is a comma-separated list ([SPEC] `type: array`, collectionFormat csv).
Response 200: `{ "instruments": [Instrument], "lastTransactionID": "..." }`.

[SPEC] `Instrument` fields: `name`, `type` (`CURRENCY|CFD|METAL`), `displayName`,
`pipLocation` (int, pip = 10^pipLocation), `displayPrecision` (int, price decimals),
`tradeUnitsPrecision` (int, units decimals), `minimumTradeSize`, `maximumTrailingStopDistance`,
`minimumTrailingStopDistance`, `maximumPositionSize` (`"0"` = no instrument-level limit, per
recorded data), `maximumOrderUnits`, `marginRate`, `commission`.

```json
{
  "minimumTradeSize": "1",
  "displayName": "EUR/USD",
  "name": "EUR_USD",
  "displayPrecision": 5,
  "type": "CURRENCY",
  "minimumTrailingStopDistance": "0.00050",
  "marginRate": "0.05",
  "maximumOrderUnits": "100000000",
  "tradeUnitsPrecision": 0,
  "pipLocation": -4,
  "maximumPositionSize": "0",
  "maximumTrailingStopDistance": "1.00000"
}
```
Source: [HOOT] `accounts.py` `_v3_account_by_accountID_instruments` (EUR_USD element).

USD_JPY, recorded by [AV20] `example_instruments` (that library re-serialized decimals as
floats, so the strings look like `"1.0"`): `pipLocation: -2`, `displayPrecision: 3`,
`tradeUnitsPrecision: 0`, `marginRate: "0.05"`, `maximumTrailingStopDistance: "100.0"`.

Newer accounts return extra fields that are not in the 3.0.25 spec ([BLANK], GBP_NZD):

```json
{
  "name": "GBP_NZD", "type": "CURRENCY", "displayName": "GBP/NZD",
  "pipLocation": -4, "displayPrecision": 5, "tradeUnitsPrecision": 0,
  "minimumTradeSize": "1", "maximumTrailingStopDistance": "1.00000",
  "minimumTrailingStopDistance": "0.00050", "maximumPositionSize": "0",
  "maximumOrderUnits": "100000000", "marginRate": "0.03",
  "guaranteedStopLossOrderMode": "DISABLED",
  "tags": [{ "type": "ASSET_CLASS", "name": "CURRENCY" }],
  "financing": {
    "longRate": "-0.0153",
    "shortRate": "-0.0093",
    "financingDaysOfWeek": [
      { "dayOfWeek": "MONDAY", "daysCharged": 1 },
      { "dayOfWeek": "TUESDAY", "daysCharged": 1 },
      { "dayOfWeek": "WEDNESDAY", "daysCharged": 1 },
      { "dayOfWeek": "THURSDAY", "daysCharged": 1 },
      { "dayOfWeek": "FRIDAY", "daysCharged": 1 },
      { "dayOfWeek": "SATURDAY", "daysCharged": 0 },
      { "dayOfWeek": "SUNDAY", "daysCharged": 0 }
    ]
  }
}
```
Source: [BLANK] docstring of `get_products()`. The pydantic model must use `extra="ignore"` and
treat `financing`/`tags`/`guaranteedStopLossOrderMode` as optional.

Use of these fields:

- `pip = Decimal(10) ** pipLocation`; `tick = Decimal(10) ** -displayPrecision`.
- `marginRate` → max leverage `1/marginRate` (0.05 → 20:1, 0.0333 → 30:1). The risk engine uses
  `min(broker leverage, configured regulatory cap)`.
- `financing.longRate/shortRate` are annualized rates. The backtester's swap model should read
  these and `financingDaysOfWeek` (see `06-backtesting-pitfalls.md`). Do **not** hard-code
  "triple Wednesday": the recorded example above charges Wednesday ×1. OANDA's help pages
  describe Wednesday-triple for T+2 instruments in some divisions, so the data may differ by
  division.

### 6.4 Candles — `GET /v3/instruments/{instrument}/candles`

(Account-scoped variant: `GET /v3/accounts/{acct}/instruments/{instrument}/candles`, which also
takes `units`, for volume-weighted bid/ask candles [SPEC].)

Query parameters ([SPEC]; defaults from [AV20] `annotations.py` / `interface/instrument.py`,
which copied them from the developer docs):

| Param | Type | Default | Notes |
|---|---|---|---|
| `price` | string | `M` | Any combination of `M` (mid), `B` (bid), `A` (ask), e.g. `BA` or `MBA` |
| `granularity` | enum | `S5` | `S5 S10 S15 S30 M1 M2 M4 M5 M10 M15 M30 H1 H2 H3 H4 H6 H8 H12 D W M` [SPEC] |
| `count` | int | 500 | **max 5000** ([AV20] `Count`, and [HOOT] `contrib/factories/history.py` `MAX_BATCH = 5000`: "OANDA will respond with a V20Error if count > MAX_BATCH"). Do not send with both `from` and `to`. |
| `from` | DateTime | — | Start of range |
| `to` | DateTime | — | End of range |
| `smooth` | bool | false | If true, open = previous close |
| `includeFirst` | bool | true | Whether the candle at `from` is included. Set **false** when polling from the last stored candle time. |
| `dailyAlignment` | int 0–23 | 17 | Hour for D/H-aligned granularities |
| `alignmentTimezone` | string | `America/New_York` | Times are still returned in UTC |
| `weeklyAlignment` | enum | `Friday` | `Monday`…`Sunday` |

So by default **D candles close at 17:00 New York**, which is the FX trading-day convention we want.

Response 200 ([SPEC]): `{ "instrument": str, "granularity": str, "candles": [Candlestick] }` with
`Candlestick = { time, bid?, ask?, mid?, volume:int, complete:bool }` and
`CandlestickData = { o, h, l, c }` (all strings). `time` is the candle **start** time ([SPEC]).
`complete` is "false" while the candle's end time is still in the future.

```json
{
  "candles": [
    { "volume": 132, "time": "2016-10-17T19:35:00.000000000Z", "complete": true,
      "mid": { "h": "10508.0", "c": "10506.0", "l": "10503.8", "o": "10503.8" } },
    { "volume": 162, "time": "2016-10-17T19:40:00.000000000Z", "complete": true,
      "mid": { "h": "10507.0", "c": "10504.9", "l": "10502.0", "o": "10506.0" } }
  ],
  "instrument": "DE30/EUR",
  "granularity": "M5"
}
```
Source: [HOOT] `instruments.py` `_v3_instruments_instrument_candles` (first 2 of 5 candles;
request `count=5&granularity=M5`).

With `price=BA` each candle carries `"bid": {o,h,l,c}` and `"ask": {o,h,l,c}` instead of
`"mid"` (shape per [SPEC] `Candlestick`. No recorded BA payload was found. The keys are
**UNVERIFIED** by example but certain from the schema).

**Implementation rules (no lookahead):**

1. Request `price=BA` for backtest/research storage (mid can be derived, spread is real). Request
   `price=M` only for display.
2. **Drop every candle with `complete == false`** before it reaches the candle store or any
   signal. A strategy may only see closed bars.
3. Backfill algorithm: `from=<last stored candle time>`, `includeFirst=false`, `count=5000`,
   loop until fewer than `count` candles come back or `time >= now - granularity`. The
   hootnot factory does the same (`includeFirst` forced to avoid a 1-record gap). Sleep ≥ 50 ms
   between pages.
4. Candle `time` is the open time. For signal timestamps use `time + granularity` (the close).
5. The stream (§6.6) does not give candles. Live bar building either polls candles every
   granularity boundary + 2–5 s (simplest and recommended), or aggregates stream ticks
   (only for display).

### 6.5 Pricing snapshot — `GET /v3/accounts/{acct}/pricing?instruments=EUR_USD,USD_JPY`

Params ([SPEC]): `instruments` (required, csv), `since` (DateTime), `includeUnitsAvailable`
(bool), `includeHomeConversions` (bool). Response 200: `{ "prices": [ClientPrice],
"homeConversions"?: [HomeConversions], "time": DateTime }`.

`ClientPrice` ([SPEC]): `type` ("PRICE"), `instrument`, `time`, `status` (deprecated),
`tradeable` (bool), `bids: [PriceBucket]`, `asks: [PriceBucket]`, `closeoutBid`, `closeoutAsk`,
`quoteHomeConversionFactors {positiveUnits, negativeUnits}`, `unitsAvailable`.
`PriceBucket = {price: str, liquidity: int}`. `bids`/`asks` may be empty ([SPEC]: "It is
possible for this list to be empty").

```json
{
  "prices": [
    {
      "status": "tradeable",
      "quoteHomeConversionFactors": { "negativeUnits": "0.89160730", "positiveUnits": "0.89150397" },
      "asks": [ { "price": "1.12170", "liquidity": 10000000 }, { "price": "1.12172", "liquidity": 10000000 } ],
      "unitsAvailable": {
        "default": { "short": "506246", "long": "506128" },
        "reduceOnly": { "short": "0", "long": "0" },
        "openOnly": { "short": "506246", "long": "506128" },
        "reduceFirst": { "short": "506246", "long": "506128" }
      },
      "closeoutBid": "1.12153",
      "bids": [ { "price": "1.12157", "liquidity": 10000000 }, { "price": "1.12155", "liquidity": 10000000 } ],
      "instrument": "EUR_USD",
      "time": "2016-10-05T05:28:16.729643492Z",
      "closeoutAsk": "1.12174"
    }
  ]
}
```
Source: [HOOT] `pricing.py` `_v3_accounts_accountID_pricing` (EUR_USD element only).

Domain mapping: `bid = bids[0].price`, `ask = asks[0].price` (top of book), `spread = ask - bid`.
`closeoutBid/closeoutAsk` are only used for closeout valuation ([SPEC]: "never used to open a
new position"). Do not trade on them. Use `quoteHomeConversionFactors` to convert P/L in quote
currency into account currency for position sizing (positiveUnits for gains, negativeUnits for
losses).

### 6.6 Pricing stream — `GET {stream}/v3/accounts/{acct}/pricing/stream?instruments=EUR_USD,USD_JPY&snapshot=true`

- Transport: one long-lived HTTP/1.1 response with chunked transfer. **Each JSON object is one
  line** (newline-delimited JSON). Read with `httpx` `client.stream("GET", ...)` and
  `response.aiter_lines()`.
- `snapshot` default `true` ([AV20] `Snapshot`): the current price for each instrument is sent
  on connect.
- Line types, dispatched on `type` ([PY] `Parser.__call__`): `"PRICE"` → `ClientPrice`.
  `"HEARTBEAT"` → `PricingHeartbeat {type, time}`. Missing `type` → treat as a price (the SDK does this).
- Any other `type`: log and ignore (forward compatibility).

Recorded stream lines ([HOOT] `pricing.py` `_v3_accounts_accountID_pricing_stream`, reduced to
one depth level for brevity):

```json
{"status":"tradeable","asks":[{"price":"114.312","liquidity":1000000}],"closeoutBid":"114.291","bids":[{"price":"114.295","liquidity":1000000}],"instrument":"EUR_JPY","time":"2016-10-27T08:38:43.094548890Z","closeoutAsk":"114.316","type":"PRICE"}
{"type":"HEARTBEAT","time":"2016-10-27T08:38:44.327443673Z"}
{"status":"tradeable","asks":[{"price":"1.09188","liquidity":10000000}],"closeoutBid":"1.09173","bids":[{"price":"1.09177","liquidity":10000000}],"instrument":"EUR_USD","time":"2016-10-27T08:38:45.664613867Z","closeoutAsk":"1.09192","type":"PRICE"}
```

A recorded line with the `tradeable` boolean, UNIX time format ([AV20] `stream_price`):

```json
{"type": "PRICE", "instrument": "EUR_USD", "time": "1514852541.189833163", "status": "tradeable",
 "tradeable": true, "bids": [{"price": "1.20165", "liquidity": 10000000}],
 "asks": [{"price": "1.2018", "liquidity": 10000000}], "closeoutBid": "1.2015", "closeoutAsk": "1.20195"}
```

Stream client rules:

1. A watchdog: if no line (price or heartbeat) arrives for **10 s**, close and reconnect.
2. On reconnect, take a REST pricing snapshot (§6.5) so the "last price" is never stale.
3. Mark a price **stale** after 30 s without update during market hours. The risk engine
   blocks new orders on stale or `tradeable == false` prices.
4. Stream prices are for monitoring, spread filters and live mark-to-market only. Signals use
   closed candles (§6.4).

### 6.7 Create order — `POST /v3/accounts/{acct}/orders`

Body: `{ "order": OrderRequest }`. We only use `MarketOrderRequest` (type `MARKET`).
[SPEC] / [PY] fields and SDK defaults:

| Field | Type | Default (SDK) | Our value |
|---|---|---|---|
| `type` | `"MARKET"` | `MARKET` | `MARKET` |
| `instrument` | str | — | e.g. `EUR_USD` |
| `units` | decimal string, signed | — | integer string, `+` long / `-` short |
| `timeInForce` | `FOK` or `IOC` for market orders | `FOK` | **`FOK`** (all or nothing) |
| `priceBound` | price string | — | worst acceptable fill: ask + maxSlip (long), bid − maxSlip (short). Cancel reason `BOUNDS_VIOLATION` if breached. |
| `positionFill` | `OPEN_ONLY \| REDUCE_FIRST \| REDUCE_ONLY \| DEFAULT` | `DEFAULT` | `DEFAULT` (= `REDUCE_FIRST` on non-hedging accounts, `OPEN_ONLY` on hedging accounts, per enum docs copied in [AV20] `primitives.py`) |
| `clientExtensions` | `{id, tag, comment}` | — | order-level, `id` = our order intent ID |
| `tradeClientExtensions` | `{id, tag, comment}` | — | applied to the opened trade. `id` = same intent ID (idempotency, see below) |
| `stopLossOnFill` | `StopLossDetails {price \| distance, timeInForce=GTC, gtdTime, clientExtensions, guaranteed}` | tif `GTC` | **always set** (price) |
| `takeProfitOnFill` | `TakeProfitDetails {price, timeInForce, gtdTime, clientExtensions}` | — | when the strategy has a target |
| `trailingStopLossOnFill` | `TrailingStopLossDetails {distance, timeInForce, gtdTime, clientExtensions}` | — | optional. We trail ourselves via §6.10. |

`StopLossDetails`: "Only one of the price and distance fields may be specified" ([SPEC]).
`distance` is in **price units** from the fill price. Prefer `price` (deterministic for
backtest parity). Use `distance` only when you want the SL to be anchored to the actual fill.

Recommended request (constructed from [SPEC]; not a recorded payload):

```json
{
  "order": {
    "type": "MARKET",
    "instrument": "EUR_USD",
    "units": "12000",
    "timeInForce": "FOK",
    "positionFill": "DEFAULT",
    "priceBound": "1.16400",
    "stopLossOnFill": { "price": "1.16010", "timeInForce": "GTC" },
    "takeProfitOnFill": { "price": "1.17150", "timeInForce": "GTC" },
    "clientExtensions": { "id": "afx-7f3c2a", "tag": "trend_breakout_h4", "comment": "sig=2024-03-04T12:00Z" },
    "tradeClientExtensions": { "id": "afx-7f3c2a", "tag": "trend_breakout_h4" }
  }
}
```

The length limits of `clientExtensions` strings are **UNVERIFIED**. Keep `id` ≤ 32 chars and
`comment` ≤ 120 chars, ASCII only. Reject reasons `CLIENT_ORDER_ID_INVALID`,
`CLIENT_ORDER_TAG_INVALID`, `CLIENT_ORDER_COMMENT_INVALID` exist in [SPEC].

#### Possible responses (the adapter must handle all of them)

The 201 response schema ([SPEC]) is: `orderCreateTransaction`, `orderFillTransaction?`,
`orderCancelTransaction?`, `orderReissueTransaction?`, `orderReissueRejectTransaction?`,
`relatedTransactionIDs`, `lastTransactionID`. The 400/404 schema is: `orderRejectTransaction?`,
`relatedTransactionIDs?`, `lastTransactionID?`, `errorCode?`, `errorMessage`.

**(A) 201, filled.** `orderCreateTransaction` + `orderFillTransaction`. Real practice-account
response ([NB1], 2018-06-27):

```json
{
  "orderCreateTransaction": {
    "type": "MARKET_ORDER", "instrument": "EUR_USD", "units": "100",
    "timeInForce": "FOK", "positionFill": "DEFAULT", "reason": "CLIENT_ORDER",
    "id": "22", "userID": 5120019, "accountID": "101-003-5120019-001",
    "batchID": "22", "requestID": "78475265757515465",
    "time": "2018-06-27T09:36:12.964984863Z"
  },
  "orderFillTransaction": {
    "type": "ORDER_FILL", "orderID": "22", "instrument": "EUR_USD", "units": "100",
    "price": "1.16377", "pl": "0.0000", "financing": "0.0000", "commission": "0.0000",
    "accountBalance": "99999.9604",
    "gainQuoteHomeConversionFactor": "1.36376", "lossQuoteHomeConversionFactor": "1.36394",
    "guaranteedExecutionFee": "0.0000", "halfSpreadCost": "0.0089", "reason": "MARKET_ORDER",
    "tradeOpened": {
      "price": "1.16377", "tradeID": "23", "units": "100",
      "guaranteedExecutionFee": "0.0000", "halfSpreadCost": "0.0089",
      "initialMarginRequired": "3.1742"
    },
    "fullPrice": {
      "closeoutBid": "1.16349", "closeoutAsk": "1.16392",
      "timestamp": "2018-06-27T09:36:07.712138542Z",
      "bids": [{ "price": "1.16364", "liquidity": "10000000" }],
      "asks": [{ "price": "1.16377", "liquidity": "10000000" }]
    },
    "id": "23", "userID": 5120019, "accountID": "101-003-5120019-001",
    "batchID": "22", "requestID": "78475265757515465",
    "time": "2018-06-27T09:36:12.964984863Z"
  },
  "relatedTransactionIDs": ["22", "23"],
  "lastTransactionID": "23"
}
```

A recorded fill with a trailing stop on fill, showing the dependent order created in the same
batch ([AV20] `example_transaction_array`, UNIX time format, AUD_USD short):

```json
[
  {"type": "MARKET_ORDER", "instrument": "AUD_USD", "units": "-19554", "timeInForce": "FOK",
   "positionFill": "DEFAULT", "trailingStopLossOnFill": {"distance": "0.00050", "timeInForce": "GTC"},
   "reason": "CLIENT_ORDER", "id": "7095", "batchID": "7095", "time": "1512446222.248676455"},
  {"type": "ORDER_FILL", "orderID": "7095", "instrument": "AUD_USD", "units": "-19554", "price": "0.76412",
   "pl": "0.0000", "financing": "0.0000", "commission": "0.0000", "accountBalance": "97770.1692",
   "gainQuoteHomeConversionFactor": "1.308472358521", "lossQuoteHomeConversionFactor": "1.308694969377",
   "guaranteedExecutionFee": "0.0000", "halfSpreadCost": "1.5353", "reason": "MARKET_ORDER",
   "tradeOpened": {"price": "0.76412", "tradeID": "7096", "units": "-19554",
                   "guaranteedExecutionFee": "0.0000", "halfSpreadCost": "1.5353"},
   "fullPrice": {"closeoutBid": "0.76397", "closeoutAsk": "0.76440", "timestamp": "1512446219.959988002",
                 "bids": [{"price": "0.76412", "liquidity": "10000000"}],
                 "asks": [{"price": "0.76425", "liquidity": "10000000"}]},
   "id": "7096", "batchID": "7095", "time": "1512446222.248676455"},
  {"type": "TRAILING_STOP_LOSS_ORDER", "tradeID": "7096", "timeInForce": "GTC", "triggerCondition": "DEFAULT",
   "distance": "0.00050", "reason": "ON_FILL", "id": "7097", "batchID": "7095", "time": "1512446222.248676455"}
]
```
(`userID`, `accountID`, `requestID` omitted for brevity. They are present in the source.)

Notes on (A):

- `OrderFillTransaction` fields ([SPEC]): `orderID`, `clientOrderID?`, `instrument`, `units`,
  `price` (deprecated), `fullVWAP`, `fullPrice`, `reason` (`MARKET_ORDER`, `STOP_LOSS_ORDER`,
  `TAKE_PROFIT_ORDER`, `TRAILING_STOP_LOSS_ORDER`, `MARKET_ORDER_TRADE_CLOSE`,
  `MARKET_ORDER_POSITION_CLOSEOUT`, `MARKET_ORDER_MARGIN_CLOSEOUT`,
  `MARKET_ORDER_DELAYED_TRADE_CLOSE`, `LIMIT_ORDER`, `STOP_ORDER`, `MARKET_IF_TOUCHED_ORDER`),
  `pl`, `financing`, `commission`, `guaranteedExecutionFee`, `accountBalance`,
  `tradeOpened?: TradeOpen`, `tradesClosed?: [TradeReduce]`, `tradeReduced?: TradeReduce`,
  `halfSpreadCost`, `gainQuoteHomeConversionFactor`, `lossQuoteHomeConversionFactor`.
- `TradeOpen` = `{tradeID, units, price, guaranteedExecutionFee, clientExtensions?, halfSpreadCost,
  initialMarginRequired}`. `TradeReduce` = `{tradeID, units, price, realizedPL, financing,
  guaranteedExecutionFee, halfSpreadCost}` ([SPEC]).
- On a non-hedging account an opposite-direction order with `positionFill=DEFAULT` first
  **closes/reduces** existing trades (`tradesClosed`/`tradeReduced`) and may also open a new
  one. Our engine must not send opposite orders by accident. Close trades explicitly via §6.9.
- `halfSpreadCost` is in account currency. Record it per fill: it is the real spread cost we
  compare against the backtester's model.
- **SL/TP/TSL orders created "on fill" are NOT top-level fields of the response.** They are
  separate transactions in the same `batchID` (type `STOP_LOSS_ORDER` / `TAKE_PROFIT_ORDER` /
  `TRAILING_STOP_LOSS_ORDER`, `reason: "ON_FILL"`). Their IDs only show up in
  `relatedTransactionIDs`. To learn the SL order ID either call `GET /trades/{tradeID}`
  (`stopLossOrder.id`) or read the transaction stream. Verify that the SL exists after every
  fill. If it does not, close the trade (fail-safe).

**(B) 201, cancelled (not filled).** `orderCreateTransaction` + `orderCancelTransaction`. Real
response, weekend, on a trade-close market order ([NB2], 2017-01-28):

```json
{
  "lastTransactionID": "65",
  "orderCancelTransaction": {
    "accountID": "101-003-5120068-001", "batchID": "64", "id": "65", "orderID": "64",
    "reason": "MARKET_HALTED", "time": "2017-01-28T13:31:38.732264064Z",
    "type": "ORDER_CANCEL", "userID": 5120068
  },
  "orderCreateTransaction": {
    "accountID": "101-003-5120068-001", "batchID": "64", "id": "64",
    "instrument": "NZD_USD", "positionFill": "REDUCE_ONLY", "reason": "TRADE_CLOSE",
    "time": "2017-01-28T13:31:38.732264064Z", "timeInForce": "FOK",
    "tradeClose": { "tradeID": "35", "units": "ALL" },
    "type": "MARKET_ORDER", "units": "-100", "userID": 5120068
  },
  "relatedTransactionIDs": ["64", "65"]
}
```

`OrderCancelReason` values ([SPEC], descriptions from the developer docs as copied in [AV20]
`primitives.py`). The ones a market order can realistically hit:

| reason | meaning | engine action |
|---|---|---|
| `MARKET_HALTED` | instrument halted (weekend, holiday, outage) | do not retry until `tradeable` is true again |
| `INSUFFICIENT_MARGIN` | not enough margin | risk-engine bug or account drawdown → halt & alert |
| `INSUFFICIENT_LIQUIDITY` | not enough liquidity | skip the signal, log |
| `BOUNDS_VIOLATION` | fill would violate `priceBound` | slippage guard worked. Skip the signal. |
| `STOP_LOSS_ON_FILL_LOSS` | SL would trigger immediately at a loss | SL too close / market moved. Skip. |
| `TAKE_PROFIT_ON_FILL_LOSS`, `LOSING_TAKE_PROFIT` | TP on the wrong side | bug → alert |
| `STOP_LOSS_ON_FILL_PRICE_DISTANCE_MAXIMUM_EXCEEDED`, `TAKE_PROFIT_ON_FILL_PRICE_DISTANCE_MAXIMUM_EXCEEDED` | SL/TP too far | config error → alert |
| `FIFO_VIOLATION` | US FIFO rule (NFA 2-43(b)) | close oldest trades first |
| `CLIENT_TRADE_ID_ALREADY_EXISTS` | `tradeClientExtensions.id` already used by an open trade | **duplicate submit detected** → treat as "already done", reconcile |
| `POSITION_SIZE_EXCEEDED`, `OPEN_TRADES_ALLOWED_EXCEEDED`, `ACCOUNT_POSITION_VALUE_LIMIT_EXCEEDED` | account limits | alert |
| `ACCOUNT_LOCKED`, `ACCOUNT_NEW_POSITIONS_LOCKED`, `ACCOUNT_ORDER_CREATION_LOCKED`, `ACCOUNT_ORDER_FILL_LOCKED` | account locked | halt trading, alert |
| `INSTRUMENT_BID_HALTED`, `INSTRUMENT_ASK_HALTED`, `INSTRUMENT_BID_REDUCE_ONLY`, `INSTRUMENT_ASK_REDUCE_ONLY` | instrument restrictions | skip, retry later |
| `INTERNAL_SERVER_ERROR`, `MIGRATION` | broker side | skip, alert if repeated |

Full enum list in [SPEC] `OrderCancelReason` (47 values).

**(C) 400, rejected.** `orderRejectTransaction` (type `MARKET_ORDER_REJECT`, field `rejectReason`)
plus `errorCode`/`errorMessage`. Real body, abridged as shown in [ISS149]:

```json
{
  "orderRejectTransaction": {
    "type": "MARKET_ORDER_REJECT",
    "rejectReason": "TAKE_PROFIT_ON_FILL_PRICE_PRECISION_EXCEEDED",
    "instrument": "EUR_USD", "units": "80000", "timeInForce": "FOK", "positionFill": "DEFAULT",
    "takeProfitOnFill": { "price": "1.12247999999999", "timeInForce": "GTC" }
  },
  "errorCode": "TAKE_PROFIT_ON_FILL_PRICE_PRECISION_EXCEEDED",
  "errorMessage": "The Take Profit on fill specified contains a price with more precision than is allowed by the Order's instrument"
}
```

Root cause in that issue: a Python float was serialized as `1.12247999999999`. **Always build
price strings with `Decimal.quantize`** (§8). Other common `TransactionRejectReason` values
([SPEC], 143 in total): `INSTRUMENT_NOT_TRADEABLE`, `INSTRUMENT_UNKNOWN`, `UNITS_INVALID`,
`UNITS_PRECISION_EXCEEDED`, `UNITS_MIMIMUM_NOT_MET` (sic), `UNITS_LIMIT_EXCEEDED`,
`PRICE_PRECISION_EXCEEDED`, `PRICE_BOUND_INVALID`, `PRICE_BOUND_PRECISION_EXCEEDED`,
`STOP_LOSS_ON_FILL_PRICE_PRECISION_EXCEEDED`, `STOP_LOSS_ON_FILL_PRICE_AND_DISTANCE_BOTH_SPECIFIED`,
`STOP_LOSS_ON_FILL_DISTANCE_PRECISION_EXCEEDED`, `STOP_LOSS_ON_FILL_REQUIRED_FOR_PENDING_ORDER`,
`CLIENT_ORDER_ID_ALREADY_EXISTS`, `ACCOUNT_NOT_ACTIVE`, `ACCOUNT_LOCKED`, `INSUFFICIENT_MARGIN`.

Another recorded reject (position close), [AV20] `example_market_order_reject_transaction`:

```json
{"type": "MARKET_ORDER_REJECT", "rejectReason": "CLOSEOUT_POSITION_DOESNT_EXIST",
 "instrument": "AUD_USD", "timeInForce": "FOK", "positionFill": "REDUCE_ONLY",
 "reason": "POSITION_CLOSEOUT", "shortPositionCloseout": {"instrument": "AUD_USD", "units": "ALL"},
 "id": "7158", "userID": 6557245, "accountID": "123-123-1234567-123", "batchID": "7157",
 "requestID": "24359106208214028", "time": "1512696194.488775774"}
```

**(D) 404**: account (or referenced order) does not exist. May include `orderRejectTransaction`.
`lastTransactionID`/`relatedTransactionIDs` are "only present if the Account exists" ([SPEC]).

**(E) 401/403**: plain `{errorMessage}`. Example text **UNVERIFIED**.

**(F) Network failure / timeout after sending.** The order may or may not exist. Never resend
blindly. Reconcile (§9), using the `clientExtensions.id` we generated.

#### Domain mapping (suggested)

```python
class OrderResult(BaseModel):
    status: Literal["FILLED", "CANCELLED", "REJECTED", "UNKNOWN"]
    client_order_id: str
    broker_order_id: str | None          # orderCreateTransaction.id
    trade_id: str | None                 # orderFillTransaction.tradeOpened.tradeID
    fill_price: Decimal | None           # tradeOpened.price
    filled_units: Decimal | None
    half_spread_cost: Decimal | None     # account currency
    reason: str | None                   # cancel reason / rejectReason / errorCode
    last_transaction_id: str | None
    raw: dict                            # store raw JSON in the journal
```

Decision tree: `orderFillTransaction` present → FILLED (also check `tradesClosed`/`tradeReduced`).
`orderCancelTransaction` present → CANCELLED(reason). HTTP 400/404 → REJECTED(errorCode or
rejectReason). Exception before a response → UNKNOWN → reconcile.

### 6.8 Trades — `GET /v3/accounts/{acct}/openTrades` and `GET /v3/accounts/{acct}/trades`

`openTrades` returns `{ "trades": [Trade], "lastTransactionID" }`. `/trades` takes `ids` (csv),
`state` (`OPEN|CLOSED|CLOSE_WHEN_TRADEABLE|ALL`), `instrument`, `count`, `beforeID` and paginates
via the `Link` header ([SPEC]). The `count` default/max (commonly 50/500) is **UNVERIFIED**.

[SPEC] `Trade`: `id`, `instrument`, `price`, `openTime`, `state` (`OPEN|CLOSED|CLOSE_WHEN_TRADEABLE`),
`initialUnits`, `initialMarginRequired`, `currentUnits`, `realizedPL`, `unrealizedPL`,
`marginUsed`, `averageClosePrice`, `closingTransactionIDs`, `financing`, `closeTime`,
`clientExtensions`, `takeProfitOrder`, `stopLossOrder`, `trailingStopLossOrder`.

```json
{
  "trades": [
    {
      "financing": "0.0000", "openTime": "2016-10-28T14:27:19.011002322Z",
      "price": "1.09448", "unrealizedPL": "-0.0933", "realizedPL": "0.0000",
      "instrument": "EUR_USD", "state": "OPEN",
      "initialUnits": "100", "currentUnits": "100", "id": "2313"
    }
  ],
  "lastTransactionID": "2315"
}
```
Source: [HOOT] `trades.py` `_v3_accounts_accountID_trades` (EUR_USD element).

`tradeSpecifier` in paths accepts the OANDA trade ID **or** `@<clientExtensions.id>` ([SPEC]
`TradeSpecifier` format), e.g. `PUT /v3/accounts/{acct}/trades/@afx-7f3c2a/close`.

### 6.9 Close trade — `PUT /v3/accounts/{acct}/trades/{tradeSpecifier}/close`

Body: `{ "units": "ALL" }` or `{ "units": "<positive decimal ≤ open units>" }` ([SPEC]).
Responses: 200 `{orderCreateTransaction: MarketOrderTransaction, orderFillTransaction?,
orderCancelTransaction?, relatedTransactionIDs, lastTransactionID}`. 400/404
`{orderRejectTransaction: MarketOrderRejectTransaction, errorCode?, errorMessage, ...}`.

```json
{
  "orderFillTransaction": {
    "orderID": "2316", "financing": "0.0000", "instrument": "EUR_USD", "price": "1.09289",
    "userID": 1435156, "batchID": "2316", "accountBalance": "33848.1208",
    "reason": "MARKET_ORDER_TRADE_CLOSE",
    "tradesClosed": [ { "units": "-100", "financing": "0.0000", "realizedPL": "-0.1455", "tradeID": "2313" } ],
    "time": "2016-10-28T15:11:58.023004583Z", "units": "-100", "type": "ORDER_FILL",
    "id": "2317", "pl": "-0.1455", "accountID": "101-004-1435156-001"
  },
  "orderCreateTransaction": {
    "timeInForce": "FOK", "positionFill": "REDUCE_ONLY", "userID": 1435156, "batchID": "2316",
    "instrument": "EUR_USD", "reason": "TRADE_CLOSE",
    "tradeClose": { "units": "100", "tradeID": "2313" },
    "time": "2016-10-28T15:11:58.023004583Z", "units": "-100", "type": "MARKET_ORDER",
    "id": "2316", "accountID": "101-004-1435156-001"
  },
  "relatedTransactionIDs": ["2316", "2317"],
  "lastTransactionID": "2317"
}
```
Source: [HOOT] `trades.py` `_v3_account_accountID_trades_close` (request body `{"units": 100}`).

A close can be **cancelled with `MARKET_HALTED`** (example (B) in §6.7 is exactly that). The
kill switch must handle it: mark the trade "close pending" and retry when `tradeable` returns.
Do not report "flat" until a fill is confirmed.

### 6.10 Modify dependent orders — `PUT /v3/accounts/{acct}/trades/{tradeSpecifier}/orders`

Body (all optional) `{ "takeProfit": TakeProfitDetails|null, "stopLoss": StopLossDetails|null,
"trailingStopLoss": TrailingStopLossDetails|null }`. Semantics (docstring of [PY]
`trade.set_dependent_orders`): **field set to `null` → that order is cancelled**. Field omitted
→ unchanged. Field present → created or replaced.

Example: move the stop to break-even and leave TP unchanged:

```json
{ "stopLoss": { "price": "1.16377", "timeInForce": "GTC" } }
```

Response 200 ([SPEC]) may contain any of: `takeProfitOrderCancelTransaction`,
`takeProfitOrderTransaction`, `takeProfitOrderFillTransaction`,
`takeProfitOrderCreatedCancelTransaction`, `stopLossOrderCancelTransaction`,
`stopLossOrderTransaction`, `stopLossOrderFillTransaction`,
`stopLossOrderCreatedCancelTransaction`, `trailingStopLossOrderCancelTransaction`,
`trailingStopLossOrderTransaction`, `relatedTransactionIDs`, `lastTransactionID`.
Note `stopLossOrderFillTransaction`: if the new SL is already through the market it can
**fill immediately and close the trade**. 400 adds `*RejectTransaction` /
`*CancelRejectTransaction` variants plus `errorCode/errorMessage`.

Recorded response for setting TP + replacing SL ([HOOT] `trades.py` `_v3_account_accountID_trades_crcdo`.
The fixture's `url` says `/close`, which is a typo in the fixture. The body/response belong to
`/orders`):

```json
{
  "stopLossOrderTransaction": {
    "timeInForce": "GTC", "triggerCondition": "TRIGGER_DEFAULT", "replacesOrderID": "2324",
    "tradeID": "2323", "price": "1.10000", "userID": 1435156, "batchID": "2325",
    "reason": "REPLACEMENT", "time": "2016-10-28T21:00:19.978476830Z",
    "cancellingTransactionID": "2326", "type": "STOP_LOSS_ORDER", "id": "2327",
    "accountID": "101-004-1435156-001"
  },
  "takeProfitOrderTransaction": {
    "timeInForce": "GTC", "triggerCondition": "TRIGGER_DEFAULT", "tradeID": "2323",
    "price": "1.05000", "userID": 1435156, "batchID": "2325", "reason": "CLIENT_ORDER",
    "time": "2016-10-28T21:00:19.978476830Z", "type": "TAKE_PROFIT_ORDER", "id": "2325",
    "accountID": "101-004-1435156-001"
  },
  "relatedTransactionIDs": ["2325", "2326", "2327"],
  "lastTransactionID": "2327",
  "stopLossOrderCancelTransaction": {
    "orderID": "2324", "replacedByOrderID": "2327", "userID": 1435156, "batchID": "2325",
    "reason": "CLIENT_REQUEST_REPLACED", "time": "2016-10-28T21:00:19.978476830Z",
    "type": "ORDER_CANCEL", "id": "2326", "accountID": "101-004-1435156-001"
  }
}
```

The 2016 fixture shows `triggerCondition: "TRIGGER_DEFAULT"`. The 3.0.25 enum is
`DEFAULT|INVERSE|BID|ASK|MID`, and a 2017 recorded transaction shows `"DEFAULT"` ([AV20]).
Accept both. `DEFAULT` = "compare to ask for long orders and bid for short orders". The SL of a
long trade is a sell order, so it triggers on the **bid** ([AV20] enum docs). Our backtester
must check long stops against bid lows and short stops against ask highs.

**Trailing/break-even policy:** our engine computes new stop levels on bar close and sends
`PUT .../orders` with `stopLoss` only when the stop moves by ≥ 1 tick in the favorable
direction (never loosen). This keeps backtest/live parity better than OANDA's tick-based
`trailingStopLossOnFill`, whose distance trails every price update.

### 6.11 Positions — `GET /v3/accounts/{acct}/openPositions`, `PUT .../positions/{instrument}/close`

`openPositions` → `{ "positions": [Position], "lastTransactionID" }`. [SPEC] `Position`:
`instrument, pl, unrealizedPL, marginUsed, resettablePL, financing, commission,
guaranteedExecutionFees, long: PositionSide, short: PositionSide`, and
`PositionSide = {units, averagePrice, tradeIDs, pl, unrealizedPL, resettablePL, financing,
guaranteedExecutionFees}`.

```json
{
  "short": {
    "unrealizedPL": "870.0000", "units": "-20", "resettablePL": "-13959.3000",
    "tradeIDs": ["2121", "2123"], "averagePrice": "10581.5", "pl": "-13959.3000"
  },
  "unrealizedPL": "870.0000",
  "long": { "units": "0", "resettablePL": "404.5000", "unrealizedPL": "0.0000", "pl": "404.5000" },
  "instrument": "DE30_EUR", "resettablePL": "-13554.8000", "pl": "-13554.8000"
}
```
Source: [HOOT] `positions.py` `_v3_accounts_accountID_positions` (one element).

Close position body: `{ "longUnits": "ALL" }` and/or `{ "shortUnits": "ALL" }` (`"NONE"` or a
number also allowed [SPEC]). Response 200 has `longOrderCreateTransaction`,
`longOrderFillTransaction`, `longOrderCancelTransaction`, and the `short*` equivalents, plus
`relatedTransactionIDs`, `lastTransactionID`. Full recorded example: [HOOT] `positions.py`
`_v3_accounts_accountID_position_close` (fill `reason: MARKET_ORDER_POSITION_CLOSEOUT`, two
`tradesClosed`). Rejection example: `CLOSEOUT_POSITION_DOESNT_EXIST` in §6.7(C).

**Kill switch = for every instrument in `openPositions`, `PUT .../positions/{instrument}/close`
with `longUnits: "ALL"` if long units ≠ 0 and `shortUnits: "ALL"` if short units ≠ 0**, then poll
`openPositions` until empty, and retry halted instruments when tradeable.

### 6.12 Transactions — since-ID polling and the transaction stream

- `GET /v3/accounts/{acct}/transactions/sinceid?id=<lastSeenID>` → `{ "transactions": [Transaction],
  "lastTransactionID" }`. Returns all transactions **newer than** `id` ([SPEC]). 416 if the range
  is invalid.
- `GET {stream}/v3/accounts/{acct}/transactions/stream` → NDJSON of `Transaction` objects and
  `TransactionHeartbeat {type:"HEARTBEAT", lastTransactionID, time}` ([SPEC]).

Recorded stream lines ([AV20], UNIX time):

```json
{"type": "HEARTBEAT", "lastTransactionID": "16388", "time": "1514852380.912339327"}
{"id": "16389", "time": "1514852381.353432710", "userID": 6557245, "accountID": "101-011-6557245-001", "batchID": "16389", "requestID": "24368149911764854", "type": "MARKET_ORDER", "reason": "CLIENT_ORDER", "timeInForce": "FOK", "instrument": "AUD_USD", "units": "1.0", "positionFill": "DEFAULT"}
```

`TransactionType` enum ([SPEC]) includes `MARKET_ORDER`, `MARKET_ORDER_REJECT`,
`ORDER_FILL`, `ORDER_CANCEL`, `STOP_LOSS_ORDER`, `TAKE_PROFIT_ORDER`,
`TRAILING_STOP_LOSS_ORDER`, `DAILY_FINANCING`, `MARGIN_CALL_ENTER/EXTEND/EXIT`,
`TRADE_CLIENT_EXTENSIONS_MODIFY`, `CLIENT_CONFIGURE`, `TRANSFER_FUNDS`, `RESET_RESETTABLE_PL`, etc.

What the engine needs from transactions:

- `ORDER_FILL` with `reason` in {`STOP_LOSS_ORDER`, `TAKE_PROFIT_ORDER`,
  `TRAILING_STOP_LOSS_ORDER`, `MARKET_ORDER_MARGIN_CLOSEOUT`} → a trade closed **by the broker**.
  Record exit, compute R, feed the learning system.
- `DAILY_FINANCING` → financing accrual (journal).
- `MARGIN_CALL_ENTER` → immediate halt + alert.

Alternative for state sync: `GET /v3/accounts/{acct}/changes?sinceTransactionID=N` returns
`{changes: {ordersCreated, ordersCancelled, ordersFilled, ordersTriggered, tradesOpened,
tradesReduced, tradesClosed, positions, transactions}, state: {NAV, unrealizedPL, marginUsed,
..., orders, trades, positions}, lastTransactionID}` ([SPEC] `AccountChanges`,
`AccountChangesState`). The developer docs recommend "Account Details once, then Poll Account
Updates" ([DEVG] best practices). **Recommendation:** transaction stream for low latency,
plus `/changes` polling every 5 s as the authoritative backstop (it also survives stream
drops). Store `lastTransactionID` durably.

## 7. Order types we deliberately do not use (yet)

`LIMIT`, `STOP`, `MARKET_IF_TOUCHED`, `GTD`/`GFD` (GFD = cancelled at 5 pm New York [AV20]
enum docs), guaranteed stops (`guaranteed: true`, account mode `guaranteedStopLossOrderMode`).
Breakout strategies are simulated with market orders on bar close plus `priceBound`, so the
backtester and live behave the same. Pending stop-entry orders can be added later.

## 8. Precision rules (most common source of rejects)

From [SPEC] and the reject reasons:

1. **Price strings:** at most `displayPrecision` decimals (`PRICE_PRECISION_EXCEEDED`,
   `*_ON_FILL_PRICE_PRECISION_EXCEEDED`). EUR_USD 5, USD_JPY 3 (recorded instrument specs).
2. **Distances** (`distance` in SL/TSL): also price units, same precision
   (`*_DISTANCE_PRECISION_EXCEEDED`). TSL distance must be within
   [`minimumTrailingStopDistance`, `maximumTrailingStopDistance`].
3. **Units:** at most `tradeUnitsPrecision` decimals (`UNITS_PRECISION_EXCEEDED`). For FX this is 0
   → integer units. Must be ≥ `minimumTradeSize` (`UNITS_MIMIMUM_NOT_MET`) and ≤ `maximumOrderUnits`.
4. **Never pass floats to `json.dumps`.**

```python
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_DOWN

def fmt_price(p: Decimal, display_precision: int) -> str:
    q = Decimal(1).scaleb(-display_precision)          # 1e-5 for EUR_USD
    return str(p.quantize(q, rounding=ROUND_HALF_EVEN))  # "1.16010"

def fmt_units(u: Decimal, trade_units_precision: int) -> str:
    q = Decimal(1).scaleb(-trade_units_precision)      # 1 for FX
    return str(u.quantize(q, rounding=ROUND_DOWN))       # round toward zero = never oversize
```

Round **stop prices away from the entry** only if that does not breach the risk budget. Simpler
rule: compute units *after* the stop is rounded, so the risk is exact.

## 9. Reconciliation (startup, reconnect, unknown order outcome)

1. `GET /accounts/{acct}/summary` → equity, `lastTransactionID`.
2. `GET /openTrades`, `GET /openPositions`, `GET /pendingOrders`. Compare with the local DB.
   - A broker trade the DB does not know (e.g. opened during a crash): adopt it if
     `clientExtensions.id` starts with our prefix (`afx-`). Otherwise flag it as "external", never touch it, and alert.
   - A DB trade the broker does not have: it was closed (SL/TP) while we were down. Fetch
     `transactions/sinceid?id=<db_last_tx>` to get the closing `ORDER_FILL`.
3. For an order whose submit raised a timeout: search `transactions/sinceid` for a
   `MARKET_ORDER` with our `clientExtensions.id`. Found + fill → FILLED. Found + cancel →
   CANCELLED. Not found after 10 s → treat as not sent. It is then reasonably safe to
   re-submit **with the same id**: if the first submit did open a trade and that trade is still
   open, the `tradeClientExtensions.id` collision makes OANDA cancel the duplicate with
   `CLIENT_TRADE_ID_ALREADY_EXISTS` (cancel-reason description in [SPEC]/[AV20]). This does not
   protect against a first trade that has already closed, so re-submit only if the signal is still
   valid and the bar has not changed.
4. Every trade must have a stop-loss order. Any open trade without `stopLossOrder` → set one
   via §6.10 immediately, or close it.

## 10. Testing without network (respx)

- Store the payloads in this document as JSON fixtures under `backend/tests/fixtures/oanda/`
  (filled, cancelled-MARKET_HALTED, rejected-precision, close-trade, set-dependent-orders,
  positions, candles BA, pricing, stream lines with heartbeat).
- Unit-test the stream parser with a fake async line iterator that includes: a PRICE, a HEARTBEAT,
  an unknown `type`, a blank keep-alive line, a malformed JSON line (log + skip), and a stall
  (watchdog fires).
- Property test: `fmt_price` never produces more than `displayPrecision` decimals for random
  floats converted through `Decimal(str(x))`.

## 11. Known gaps / UNVERIFIED

| Item | Status |
|---|---|
| Rate limits 120 req/s, 20 streams, 2 new conns/s, HTTP 429 | From developer.oanda.com excerpts via search, not fetched in full |
| 429 response body shape | **UNVERIFIED** |
| Heartbeat interval 5 s (pricing and transaction streams) | **UNVERIFIED** (secondary sources agree) |
| `price=BA` candle JSON keys `bid`/`ask` | Schema-certain, no recorded example found |
| `clientExtensions` max lengths | **UNVERIFIED** |
| `/trades` `count` default/max | **UNVERIFIED** |
| Fields added after spec 3.0.25 (instrument `financing`, `tags`, `guaranteedStopLossOrderMode`, and possibly others in transactions) | Seen in [BLANK]. Models must ignore unknown fields. |
| REST API availability per OANDA division (Global Markets / TMS excluded) | From a developer.oanda.com excerpt. Confirm with OANDA support for the user's country. |
| Earliest candle history (often quoted as 2005 for majors) | **UNVERIFIED**. QuantConnect's OANDA-sourced H1 EURUSD file starts 2007-01-01 (see `07-data-sources.md`). |
