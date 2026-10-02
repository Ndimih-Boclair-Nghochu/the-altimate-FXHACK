# Altimate FX — Threat Model and Security Requirements

Owner: security. Applies to every stage. `docs/PROJECT_BRIEF.md` wins on conflict; where this
document sets a requirement that ARCHITECTURE/ROADMAP only sketch, this document is the
requirement. Reviews happen at the end of stages 1, 5, 6 and 7 using
[`docs/security/review-checklist.md`](security/review-checklist.md). The CI security job is
specified in [`docs/security/ci-security-job.md`](security/ci-security-job.md).

**MUST** means a review blocks the stage until it is met. **SHOULD** means do it unless the
review log records why not. Setting names follow `backend/src/fxbot/config.py` (`FXBOT_` prefix,
`ALLOW_LIVE_TRADING` unprefixed). Names marked *(proposed)* do not exist yet. Engineers may rename
them, but the behaviour is required.

Contents: [1 Scope](#1-scope-and-assumptions) · [2 System and trust boundaries](#2-system-and-trust-boundaries)
· [3 Assets](#3-assets) · [4 Threat actors](#4-threat-actors) · [5 Threats (STRIDE)](#5-threats-stride)
· [6 Security requirements](#6-security-requirements-sr) · [7 Stage map](#7-requirements-by-stage)
· [8 Deployment guidance](#8-deployment-guidance) · [9 Incident runbook](#9-incident-runbook)
· [10 Accepted risks](#10-accepted-risks) · [11 Review log](#11-review-log)

---

## 1. Scope and assumptions

- One operator. The software is self-hosted on the operator's laptop, a home server or a small VPS.
  There are no other users, no tenants and no public sign-up.
- The default deployment is reachable on `127.0.0.1` only. Remote access is opt-in (section 8).
- The broker is OANDA v20. A personal access token gives full API access to the operator's
  v20 accounts and is **not scoped to one sub-account**. At the time of writing the v20 REST API
  has trading and account-data endpoints but no withdrawal endpoints. The realistic impact of a
  stolen token is therefore unauthorized trading (which can still wipe the balance) plus disclosure
  of account data. Treat the token as equivalent to the money.
- Practice and live are separate OANDA environments with separate hosts and separate tokens. A
  practice token does not authenticate against the live host, so a mismatch fails closed.
- Out of scope: protecting against a fully compromised host (root on the box owns everything), a
  compromised broker, and market risk. Market risk is the risk engine's job, not a security
  control. Section 10 records these explicitly.

## 2. System and trust boundaries

```
 Browser ──(TB1: HTTP(S) + WS, cookie session)──► nginx (SPA + /api,/ws proxy) ──► FastAPI + engine
                                                     127.0.0.1:8080 only              (one process)
                                                                                         │   │
         Operator shell / CLI ──(TB2: host user)──► .env / secrets dir, fxbot CLI ───────┘   │
                                                                                             │
         SQLite journal, audit log, model artefacts, backups ◄──(TB3: filesystem)────────────┤
                                                                                             │
         OANDA v20 REST + streams ◄──(TB4: internet, TLS, bearer token)──────────────────────┘

         PyPI / npm / GitHub Actions ──(TB5: supply chain)──► dev machine, CI, container images
```

| Boundary | What crosses it | Main controls |
|---|---|---|
| TB1 browser ↔ app | Operator commands, account data | Auth, session cookie flags, CSRF and Origin checks, Host allowlist, CSP, validation (SR-24 – SR-41) |
| TB2 operator ↔ host | Secrets, mode, start/stop | Env/secret files, interlock, file permissions (SR-1, SR-9 – SR-12, SR-45) |
| TB3 app ↔ disk | Journal, audit, models | ORM only, append-only audit, hash-checked models, backups (SR-21, SR-22, SR-42 – SR-45, SR-54) |
| TB4 app ↔ broker | Orders, token | TLS, pinned hosts, account lock, fat-finger limits, rate limits, idempotency (SR-6, SR-7, SR-11, SR-13 – SR-19) |
| TB5 third-party code | Dependencies, actions | Lockfiles, audits, SHA-pinned actions, secret scanning (SR-46 – SR-50) |

## 3. Assets

| ID | Asset | Where it lives | Needs | Impact if lost |
|---|---|---|---|---|
| A1 | Broker token + account ID | Env or secret file on the host; process memory | Confidentiality | Unauthorized trading on every v20 account of the operator; account data disclosure |
| A2 | Account funds | At the broker | Integrity of every order | Direct financial loss (runaway loop, fat finger, attacker trades) |
| A3 | Trade journal + audit log | SQLite (`/data`), backups | Integrity, availability, some confidentiality | Wrong performance numbers (breaks the honesty principle), failed reconciliation, lost tax records, balance and positions disclosed |
| A4 | Dashboard access | Password hash, session cookies | Confidentiality, integrity | Attacker can loosen limits, release the kill switch, place manual closes, read everything |
| A5 | Model artefacts | `/data/models`, `model_versions` table | Integrity | Code execution on load (pickle); poisoned models skew allocation |
| A6 | Risk configuration + kill-switch state | `settings` table, code hard caps | Integrity, availability | Limits silently loosened; kill switch not honoured after restart |
| A7 | Source repo + CI | GitHub, developer machines | Integrity, confidentiality of history | Malicious code shipped; secrets published |

## 4. Threat actors

| ID | Actor | Capability | Most likely route |
|---|---|---|---|
| AC1 | Remote attacker | Reaches exposed ports. Or, more realistically, gets the operator's browser to load a hostile page | CSRF, DNS rebinding, cross-site WebSocket hijacking against the localhost API; brute force if the port is exposed |
| AC2 | Malicious dependency | Runs code at install, build or import time with the developer's or service user's privileges | Reads `.env` or env vars and exfiltrates the token; tampers with the build |
| AC3 | Leaked repo | Anyone who sees a public repo, fork, CI log or screenshot | Committed `.env`, recorded fixtures with real tokens or account IDs, logs pasted into issues |
| AC4 | Compromised host | Malware or an intruder with the service user's or root privileges | Reads secrets and the DB, trades directly; out of scope to prevent, in scope to limit and detect |
| AC5 | Operator error | Legitimate access, wrong input | Wrong mode or account, risk 10 instead of 1.0, units off by 100×, releasing the kill switch by accident |
| AC6 | Buggy strategy / runaway loop | The bot itself | Order storms, flip-flopping, NaN or inf sizes, stale prices, duplicate orders on retry, JPY pip-size bugs |

AC5 and AC6 are the most likely sources of real loss, so the order path gets the deepest
defences (SR-13 – SR-19).

## 5. Threats (STRIDE)

S = spoofing, T = tampering, R = repudiation, I = information disclosure, D = denial of service,
E = elevation of privilege.

| ID | STRIDE | Threat | Actor | Asset | Mitigations |
|---|---|---|---|---|---|
| T-01 | I | Token or account ID appears in logs, tracebacks (local variables), exception text, `repr` | AC3, AC6 | A1 | SR-3, SR-4, SR-23 |
| T-02 | I | Token returned by an API endpoint, WebSocket snapshot, error body or frontend bundle | AC1 | A1 | SR-5, SR-38 |
| T-03 | I | `.env`, recorded fixture or notebook with real credentials committed and pushed | AC3 | A1 | SR-2, SR-47 (gitleaks + fixture guard) |
| T-04 | I/E | Malicious dependency reads env/`.env` and exfiltrates the token | AC2 | A1, A2 | SR-46 – SR-50, SR-52, SR-8 (rotation) |
| T-05 | S/I | Broker traffic sent to the wrong host (free-form base URL), TLS verification disabled, redirect followed with the auth header | AC1, AC5 | A1 | SR-6, SR-11 |
| T-06 | E | Practice configuration ends up trading live, or a stale live confirmation authorizes a different account | AC5 | A2 | SR-9, SR-10, SR-11, SR-12 |
| T-07 | T | Adapter acts on a sub-account other than the configured one (the token is not account-scoped) | AC6, AC5 | A2 | SR-7 |
| T-08 | T/D | Runaway loop: order storm, flip-flopping, repeated entries on one bar | AC6 | A2 | SR-16, SR-19 |
| T-09 | T | Fat finger or sizing bug: wrong units, ×100 JPY pip error, NaN/inf passing `>` checks | AC5, AC6 | A2 | SR-14, SR-15, SR-34 |
| T-10 | T | Duplicate orders after a timeout is blindly retried | AC6 | A2 | SR-17 |
| T-11 | T | Orders placed on stale or broken prices; fills far from the quote in a spike | AC6 | A2 | SR-18, SR-15 (price bound) |
| T-12 | D | Kill switch unavailable when needed (API down, auth broken, engine wedged) or forgotten after restart | AC6, AC5 | A2, A6 | SR-19 |
| T-13 | E | Learning component raises risk (bad or poisoned model, allocator drift) | AC6 | A2 | SR-20 |
| T-14 | T | Order path bypassed (direct `submit_order`, "force" flags, a second engine on the same account) | AC6 | A2 | SR-13, ARCHITECTURE §6 instance lock |
| T-15 | R | Cannot tell who or what placed an order, changed a limit or released the kill switch | AC5, AC1 | A3, A6 | SR-21, SR-22 |
| T-16 | S | A new route ships without auth | AC1 | A4 | SR-25 (route enumeration test) |
| T-17 | S | Password brute force or guessing; default password | AC1 | A4 | SR-26, SR-28 |
| T-18 | S/T | CSRF from a hostile page the operator visits | AC1 | A4, A6 | SR-27, SR-29 |
| T-19 | S | DNS rebinding: a hostile page reaches `127.0.0.1` through an attacker domain | AC1 | A4 | SR-31, SR-25 |
| T-20 | S/I | Cross-site WebSocket hijacking; token in WS URL lands in proxy/access logs | AC1 | A4, A1 | SR-33 |
| T-21 | I/T | XSS in the dashboard steals data or drives actions | AC1, AC2 | A4 | SR-32, SR-38, SR-39 |
| T-22 | S | Session theft or replay (token in localStorage, long-lived, not revocable) | AC1, AC2 | A4 | SR-27, SR-38 |
| T-23 | T | Malformed or hostile input sets absurd risk parameters or injects SQL | AC1, AC5 | A6, A3 | SR-34, SR-35, SR-42 |
| T-24 | D | Resource exhaustion: unbounded backtests, WS floods, huge bodies, pagination | AC1, AC5 | A2 (engine starved) | SR-33, SR-34, SR-37 |
| T-25 | I | Verbose errors, public OpenAPI docs, server banners | AC1 | A4 | SR-36, SR-32 |
| T-26 | E | Code execution by loading a tampered model file (pickle) | AC2, AC4 | A5 | SR-43 |
| T-27 | T/D | Journal or audit tampered, corrupted or lost (disk, bad migration, ransomware) | AC4, AC6 | A3 | SR-22, SR-45, SR-54 |
| T-28 | T/E | Compromised dependency or GitHub Action injects code into builds | AC2 | A7 | SR-46 – SR-50 |
| T-29 | I/E | Port exposed to LAN/internet (Docker publish on `0.0.0.0` bypasses host firewalls) | AC1 | A4 | SR-24, SR-51, SR-53 |
| T-30 | E | Container break-out or persistence via writable root FS / root user | AC2, AC4 | all | SR-51 |
| T-31 | all | Host compromise | AC4 | all | Out of scope to prevent; limit with SR-8, SR-55, SR-56 and section 9 |

## 6. Security requirements (SR)

Each requirement lists the stage(s) where it must be met and how a reviewer verifies it.
Placeholders marked *(placeholder)* are tuned by the owning stage. The outer bounds (hard caps)
may only be raised by editing this document.

### A. Secrets and credentials

**SR-1 — Secrets come only from env vars or secret files.** *Stage 0–1.* The process reads
secrets only from environment variables or from files in a secrets directory (pydantic-settings
`secrets_dir`, e.g. `/run/secrets`). Never from command-line arguments (visible in `ps`),
committed config files, query strings or the API. Secrets are `FXBOT_OANDA_API_TOKEN`,
`FXBOT_OANDA_ACCOUNT_ID` (treated as secret), the dashboard password hash, any session signing key,
and `FXBOT_DATABASE_URL` whenever it contains a password. A credential-bearing database URL must be
a `SecretStr`, or the password must be supplied separately. *Verify:* review `config.py`;
`grep -rn "argv\|sys.argv" backend/src` shows no secret flags.

**SR-2 — `.env` is never committed.** *Stage 0.* `.gitignore` covers `.env` and `.env.*` except
`*.example`. `.env.example` holds empty values or the canonical fakes listed in `.gitleaks.toml`.
The gitleaks job (SR-47) runs on every push and PR. If a real secret is ever committed, **rotate it
first**; scrubbing history is optional and never a substitute, because clones and forks keep it.
*Verify:* `git ls-files | grep -E '(^|/)\.env' | grep -v '\.example$'` prints nothing.

**SR-3 — Secrets are typed `SecretStr` and unwrapped only at the point of use.** *Stage 1.*
`get_secret_value()` is called only where the secret is consumed: building the broker
`Authorization` header (once, when the httpx client is created), verifying the password, and
signing sessions. Secrets are never stored unwrapped on long-lived objects other than the httpx
client's default headers. *Verify:* `grep -rn get_secret_value backend/src` hits only
`brokers/oanda/` and `api/auth*`.

**SR-4 — Secrets are never logged.** *Stage 0–1, re-checked at 5.*
- The structlog redaction processor runs on every event, from structlog and stdlib loggers
  (uvicorn, httpx, SQLAlchemy), before rendering. It masks sensitive keys and value patterns: the
  OANDA token (`[0-9a-f]{32}-[0-9a-f]{32}`), the account ID, `Bearer`/`Basic` credentials, URL
  userinfo, `key=value` secrets, and JWTs (`eyJ…`) once sessions exist.
- **Tracebacks never include local variables.** structlog defaults to `show_locals=True` in
  `ExceptionDictTransformer` (used by `structlog.processors.dict_tracebacks`) and in
  `RichTracebackFormatter`. We reproduced a token leak this way: a header dict held in a local
  variable was written in clear text to the JSON log, even though `SecretStr` was used. Use
  `format_exc_info` and `plain_traceback` (the current scaffold does), or pass `show_locals=False`
  explicitly.
- `httpx` and `httpcore` loggers are set to `WARNING`. Request and response headers are never
  logged.
- A test uses the canonical fake token as a sentinel and pushes it through every log path:
  structlog event, stdlib record, exception raised with the token in a local variable, httpx
  error. It asserts the token is absent from captured output (ROADMAP `tests/test_secrets.py`).

*Verify:* the sentinel test; `grep -rnE "dict_tracebacks|ExceptionDictTransformer|RichTracebackFormatter|show_locals" backend/src`.

**SR-5 — Secrets never leave the backend.** *Stage 1, 5, 6.*
- No API response, WebSocket message, error body or frontend bundle contains the token, the full
  account ID, the password hash or a signing key.
- Responses use dedicated public schemas built from an allowlist of fields; `Settings` is never
  serialized.
- Secrets are reported only as `configured: true/false`.
- The account ID is shown masked, keeping the last segment only (`***-***-*******-001`).
- Broker error bodies are logged (redacted) and mapped to domain errors. They are not forwarded
  verbatim to clients.
- Settings validation errors never echo input (`hide_input_in_errors=True`, already set).

*Verify:* ROADMAP `tests/api/test_no_secret_leak.py`.

**SR-6 — Broker transport is locked down.** *Stage 1.*
- HTTPS with certificate verification: no `verify=False`, no custom CA.
- `follow_redirects=False` (the httpx default; keep it).
- Explicit timeouts on every client. REST: connect ≤ 5 s, read ≤ 15 s *(placeholder)*. Streams: a
  read timeout above the heartbeat interval, plus the `stale_after` watchdog.
- The token goes only in the `Authorization` header, never in URLs.
- `repr()`/`str()` of the client, adapter and settings never show the token. Test this.
- Reconnects use capped exponential backoff with jitter.

**SR-7 — The adapter only touches the configured account.** *Stage 1.* All requests use
`FXBOT_OANDA_ACCOUNT_ID`; the adapter never iterates or acts on other accounts returned by
`GET /v3/accounts`. On start it verifies the configured account is listed for the token, then logs
the masked ID, currency and NAV (also recorded in the startup audit event, SR-21). If the account
is not listed, it refuses to start.

**SR-8 — Tokens are rotated and revocable.** *Stage 7 (runbook).* The runbook (section 9) says how
to revoke and regenerate the token in the OANDA account portal. The token is rotated after any
suspected leak, lost device or host rebuild, and a **fresh token is issued for live**: practice
tokens are never reused. The operator SHOULD enable two-factor authentication on the OANDA login
where available, since that portal mints tokens.

### B. Live-trading interlock and order safety

**SR-9 — Mode, host, account and credentials are fixed at process start.** *Stage 1, 5.* No API
endpoint, WebSocket message or dashboard control can change the trading mode, broker host,
account ID or credentials. Changing any of them requires editing env/secret files on the host and
restarting. *Verify:* ROADMAP `tests/engine/test_interlock.py`; `grep -rnE "trading_mode|oanda_" backend/src/fxbot/api`
shows reads only.

**SR-10 — Live needs an explicit, account-bound, three-part opt-in.** *Stage 1 (config, factory),
Stage 5 (engine).* `live` starts only when all of these hold:
- `FXBOT_TRADING_MODE=live`
- `ALLOW_LIVE_TRADING=true`, unprefixed and from the environment
- `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` *(proposed)* equals `FXBOT_OANDA_ACCOUNT_ID`

A bare boolean confirmation (the current `FXBOT_LIVE_TRADING_CONFIRMED=true`) is not enough: it
silently carries over when the account ID changes. Security requires the account-bound form; this
settles the ADR 0004 proposal. It is due by the end of Stage 5 and SHOULD land in Stage 1 with the
broker factory. The check runs in `Settings` validation, in `brokers/factory.py` and in
`TradingEngine.start()`. Every refusal exits non-zero, names the missing items and prints no
secret.

**SR-11 — Broker hosts are pinned by mode.** *Stage 1.* `practice` maps to
`api-fxpractice.oanda.com` and `stream-fxpractice.oanda.com`; `live` maps to
`api-fxtrade.oanda.com` and `stream-fxtrade.oanda.com`. The mapping lives in one module. No setting
accepts a free-form broker URL. Tests swap the transport (respx / `httpx.MockTransport`) instead of
the URL. *Verify:* `grep -rnE "fxtrade|fxpractice" backend/src` hits one file; a test asserts that
`paper` and `practice` can never resolve to an `fxtrade` host.

**SR-12 — Live start-up gates.** *Stage 5.* In `live` the engine refuses to start unless:
- dashboard auth is configured (SR-26);
- all risk settings are within hard caps;
- the audit log is writable;
- the kill-switch state was loaded. If it was engaged, the engine stays halted.

The engine then starts with entries paused (`live_startup`): it reconciles and observes, and opens
nothing until the operator resumes from the dashboard. Start-up logs a `WARNING` banner with the
mode, masked account and NAV, and the UI shows the `live` badge.

**SR-13 — One order path, no bypass.** *Stage 2–3, hardened 5.* Every entry goes
`DecisionPipeline → RiskManager.evaluate → ApprovedOrder → OrderManager.submit → Broker.submit_order`.
- `ApprovedOrder` can be constructed only inside `risk/`.
- `Broker.submit_order` is called only by `OrderManager`.
- There is no `force`, `skip_risk` or debug flag that bypasses checks.
- Manual closes and kill-switch flattening go through `OrderManager.close` and `flatten_all`.

*Verify:* `grep -rn "submit_order(" backend/src` hits only `engine/order_manager.py` and broker
implementations; ROADMAP `tests/risk/test_approved_order.py`.

**SR-14 — Orders are validated as data.** *Stage 1 (domain), 3 (risk).*
- `OrderRequest` and every numeric settings model reject NaN and ±inf: Pydantic
  `allow_inf_nan=False`, or `Decimal` with `is_finite()` checks. Every hand-written guard in
  `risk/` and `engine/` either checks finiteness first or is written as "allow only if
  `x <= limit`". `nan > limit` is always false, so a NaN slips past an `if x > limit: reject`
  check.
- The instrument matches `^[A-Z]{3}_[A-Z]{3}$` and is in the enabled-instruments list.
- `units > 0`, with the side as an enum; the adapter applies the sign. Units are rounded down to
  the instrument's precision.
- `stop_loss` is mandatory and on the correct side of the entry. The optional `take_profit` is too.
- Every order attaches `stopLossOnFill`, so the broker protects the position even if the bot or
  host dies.

**SR-15 — Fat-finger limits: a second, independent check before any order is sent.** *Stage 3
(values), Stage 5 (enforced in `OrderManager`).* These checks deliberately do not reuse the sizing
code, so they catch sizing bugs (for example the ×100 JPY pip-value error).

| Check | Default *(placeholder)* | Hard cap in code | On breach |
|---|---|---|---|
| Units per order | `FXBOT_MAX_ORDER_UNITS` *(proposed)*: 100 000 in paper/practice; **must be set explicitly for live** | 1 000 000 | Reject + `CRITICAL` risk event |
| Notional per order (account ccy) | ≤ 5 × NAV | ≤ 10 × NAV | Reject + `CRITICAL` |
| Risk at stop, recomputed from units × stop distance × pip value | ≤ 1.5 × configured risk per trade | ≤ 2 % NAV | Reject + `CRITICAL` (sizing bug) |
| Stop distance | ≥ 2 × current spread, inside the ATR clamp (ROADMAP stage 3) | — | Reject |
| Market-order `priceBound` (max slippage from the decision quote) | 3 pips | 20 pips | Not filled (FOK) |
| Quote age when submitting | ≤ 10 s (OANDA streams send a heartbeat about every 5 s) | ≤ 30 s | Reject; pause entries if persistent (SR-18) |
| Margin required after the order | ≤ 50 % of NAV | ≤ 80 % | Reject |

Risk settings editable through the API have hard caps too (422 above them, SR-35): risk per trade
≤ 2 %, daily loss limit ≤ 5 %, weekly ≤ 10 %, drawdown breaker ≤ 25 %, max open trades ≤ 10,
aggregate open risk ≤ 6 %. The ROADMAP stage 3 defaults sit well inside these.

**SR-16 — Order-rate limits and runaway protection.** *Stage 5 (in `OrderManager`, across all
strategies).*

| Limit | Default *(placeholder)* | Hard cap | On breach |
|---|---|---|---|
| Entry orders | 5 per minute, 30 per trading day | 20 per minute, 200 per day | Pause entries (`order_rate_limit`) + `CRITICAL` event; operator resume required |
| Same instrument + side within 60 s (any `client_id`) | Reject | — | Reject + `WARN` |
| One entry per instrument per closed bar | Enforced | — | Reject |
| Closes, excluding kill-switch flatten | 20 per minute | — | Pause entries + `CRITICAL` (close loop) |
| Consecutive broker errors | 5 | — | Pause entries (ARCHITECTURE §10) |

Separately, the broker client's HTTP token bucket (Stage 1) protects OANDA's request limits. It
does not replace these order-level limits.

**SR-17 — Idempotent submits and no blind retries.** *Stage 1 (adapter), 5 (manager).*
- Every order carries a deterministic `client_id`, sent as `clientExtensions.id`.
- An order POST is **never** retried automatically. After a timeout, connection error or 5xx the
  order is `UNKNOWN` and is resolved by looking up the `client_id` (and by reconciling) before any
  resubmit.
- Only idempotent GETs are retried, with backoff and jitter.

*Verify:* ROADMAP `test_order_manager.py`; `grep -rnE "retry|backoff|tenacity" backend/src/fxbot/brokers`
then confirm no POST is wrapped.

**SR-18 — No entries on bad market data.** *Stage 1 (feed), 5 (engine).* Entries are paused when
any of these holds:
- the feed is stale (`FeedStaleError`);
- the spread is above the filter;
- the price is non-finite or non-positive;
- the instrument is not `tradeable`;
- reconciliation has an unresolved `CRITICAL` discrepancy.

Exits are always allowed.

**SR-19 — Kill switch.** *Stage 3 (core), 5 (API and CLI), 6 (UI), 7 (drill).*
- **Engage:** idempotent, effective immediately. `OrderManager` checks the switch before every
  submit. Engaging persists the state, writes the audit record, cancels pending orders and calls
  `flatten_all` until reconciliation confirms the account is flat. A broker-side failure keeps
  retrying with backoff and raises a `CRITICAL` alert. Kill-switch flattening is exempt from the
  SR-16 close limits.
- **Persistence:** the engine reads the state at start and stays halted if it is engaged.
- **Triggers:**
  - operator: dashboard, `POST /api/risk/kill-switch`, or CLI;
  - automatic: drawdown breaker, unflattenable position, repeated `CRITICAL` order-rate breaches,
    or an audit-log write failure (no order without an audit record).
- **Engaging needs no typing in the UI** (button + confirm, at most two clicks). Speed matters in
  an emergency.
- **Release:** manual only, by an authenticated operator, with a typed confirmation and a reason.
  It is audited and does not clear other pause reasons.
- **Out-of-band path (MUST be documented):** `docker compose stop backend`. Positions keep their
  broker-side stops. Flatten from the OANDA web or mobile platform if needed.
- **Without the dashboard (SHOULD):** an `fxbot kill-switch engage --reason …` *(proposed)* CLI
  writes the persisted state directly to the DB, and the engine honours it within ≤ 2 s.

**SR-20 — Learning only reduces or reallocates risk.** *Stage 4.*
- The meta-model can veto a signal or scale it within `[0, 1]`.
- Allocator weights have a floor and cap and sum to 1. The combined multiplier is clamped to
  `[0, max_multiplier]`, and the risk engine's hard caps always apply after it.
- Promotion and rollback are guardrailed (ADR 0005), operator-initiated or rule-based, and audited.
- Nothing in `learning/` imports `brokers/` or calls the order manager.

*Verify:* `grep -rnE "from fxbot\.(brokers|engine\.order_manager)" backend/src/fxbot/learning` prints nothing.

### C. Audit and logging

**SR-21 — Audit trail.** *Stage 3 (risk events), 5 (everything else).* The audit log is the
`risk_events` table (ARCHITECTURE §7) plus the `orders` and `signals` rows. Together they record:
- every decision (accepted, filtered, rejected, with reasons);
- every order state change and broker transaction ID;
- kill-switch engage and release, and entry pause and resume;
- every settings change, with the old and new values;
- strategy enable and disable;
- model promotion and rollback;
- reconciliation results;
- start-up: version, git SHA, mode, masked account, config hash;
- authentication: login success and failure, logout, session revocation.

Each record carries a UTC timestamp, an actor (`operator`, `engine`, `system`), a reason and, for
API actions, a request ID and client IP. The repository API for these tables is insert + read only:
no update or delete paths. *Verify:* `grep -rnE "\.(delete|update)\(" backend/src/fxbot/persistence`
shows none on audit tables.

**SR-22 — Tamper evidence and journal integrity.** *Stage 5.* Journal rows carry `mode`, so paper,
practice and live histories never mix. Closed trades are immutable; corrections are new rows.
**SHOULD:** each `risk_events` row stores `sha256(prev_hash || canonical_json(row))`, and an
`fxbot audit verify` *(proposed)* command checks the chain. This is cheap, and a silent edit
becomes detectable.

**SR-23 — Log hygiene.** *Stage 1 onward.*
- No `print()` in `src/`.
- Logs go to stdout only; there are no log files inside the repo.
- `DEBUG` is never the default in practice or live.
- Exceptions raised by our code don't interpolate secrets or full request headers into messages.
- Broker URLs contain the account ID, which the redactor masks. Don't depend on that: prefer
  logging the instrument and the endpoint name.

### D. API, authentication and browser

**SR-24 — Network exposure.** *Stage 5, 7.*
- The backend binds `127.0.0.1` by default (already the case).
- In Compose, the backend port is **not published**. nginx serves the SPA and proxies `/api` and
  `/ws`, so the browser sees one origin.
- nginx publishes on `127.0.0.1:<port>` only. Docker-published ports bypass host firewalls such as
  ufw, so `0.0.0.0` publishes are forbidden.
- Exposing the app beyond the host follows section 8.

**SR-25 — Authentication on everything except health and login.** *Stage 5.*
- Auth is a router-level dependency on every `/api` router, plus a check in the WebSocket
  handshake. It is not added route by route.
- Allowlist: `GET /api/health` (returns status, version and mode only) and `POST /api/auth/login`.
- A test enumerates `app.routes` and asserts 401 for each non-allowlisted route without
  credentials, and WebSocket close code 1008 (ROADMAP `tests/api/test_auth_required.py`).

**SR-26 — Operator credential.** *Stage 5.*
- Single operator, password only. It is stored as an **argon2id** hash (`argon2-cffi`
  `PasswordHasher`, library defaults or stronger) in `FXBOT_DASHBOARD_PASSWORD_HASH` *(proposed)*.
- An `fxbot hash-password` *(proposed)* command reads the password from a TTY prompt (never argv),
  enforces ≥ 12 characters, and prints the env line.
- **Write the hash in single quotes in `.env`** (`FXBOT_DASHBOARD_PASSWORD_HASH='$argon2id$v=19$…'`).
  Docker Compose interpolates `$` in `env_file` values that are unquoted or double-quoted. We
  verified it turns the hash into garbage, so every login fails. Alternatively, use a secret
  file (SR-52).
- There is no default password. The API refuses to start without a hash in every mode, so dev
  setups need one too. Tests use a fixture hash.
- Verify the password with `PasswordHasher.verify`. Re-hash on `check_needs_rehash`.

**SR-27 — Sessions.** *Stage 5.* Successful login sets one cookie. The flags are mandatory:

- `HttpOnly; SameSite=Strict; Path=/`, with no `Domain` attribute.
- `Secure` whenever the app is served over HTTPS. It may be off only when the app is reached on
  `http://127.0.0.1` or `http://localhost`. With HTTPS, SHOULD use the `__Host-` cookie name prefix.
- Idle timeout ≤ 30 min (sliding), absolute lifetime ≤ 12 h. Logout invalidates the session on the
  server. Changing the password or rotating the signing key invalidates all sessions.
- The session value never appears in a response body, URL, log line, `localStorage` or
  `sessionStorage`.

Recommended mechanism, given one process and one worker (ARCHITECTURE §6): an **opaque random
session ID** (`secrets.token_urlsafe(32)`). Store only its SHA-256 server-side, in memory or in a
`sessions` table if sessions should survive restarts. Revocation is trivial and there is no
signing key to manage. **If a JWT is used instead:** PyJWT, HS256 with a ≥ 32-byte random key
(`FXBOT_SESSION_SECRET` *(proposed)*, `SecretStr`). Decode with `algorithms=["HS256"]` and
`options={"require": ["exp", "iat", "sub"]}`, keep `exp` ≤ 30 min with refresh, and embed a
server-side `session_epoch` so logout and password changes revoke outstanding tokens. No other
bearer or API tokens in v1. Adding one is a security-review item.

**SR-28 — Login throttling.** *Stage 5.*
- Failed logins are limited to 5 per 15 min per client IP and 20 per 15 min globally. Beyond that
  the API returns 429 with `Retry-After`.
- The error message is generic and every attempt is audited (SR-21).
- The client IP comes from the socket. Forwarded headers are trusted only from the configured
  proxy (uvicorn `forwarded_allow_ips` = the proxy address, never `*`); otherwise a spoofed
  `X-Forwarded-For` defeats the per-IP limit.
- When nginx is the edge, it **overwrites** the header (`proxy_set_header X-Forwarded-For
  $remote_addr`) instead of appending to whatever the client sent (`$proxy_add_x_forwarded_for`).

**SR-29 — CSRF.** *Stage 5.* The `SameSite=Strict` cookie is the primary control. In addition, for
every `POST`/`PUT`/`PATCH`/`DELETE`:
- require `Content-Type: application/json`;
- require the `Origin` header (or `Referer` if `Origin` is absent) to match the allowed origins;
- otherwise return 403.

`GET` never changes state.

The allowed origins are an **explicit list**: `FXBOT_ALLOWED_ORIGINS` *(proposed; may reuse
`FXBOT_CORS_ORIGINS`)*. The default covers `http://127.0.0.1:8080`, `http://localhost:8080` and
the dev origin `http://localhost:5173`. Do not derive the expected origin from the `Host` header:
nginx forwards `$host` without the port, and the Vite proxy's `changeOrigin` rewrites `Host` but
not `Origin`. The WebSocket Origin check (SR-33) uses the same list.

**SR-30 — CORS.** *Stage 5.* Production is same-origin, so CORS is off: no middleware, or an empty
allowlist. In development, prefer the Vite dev-server proxy (also same-origin); otherwise allow an
explicit list (`http://localhost:5173`). Never `"*"`, never `allow_origin_regex`, and
`allow_credentials=True` only with explicit origins.

**SR-31 — Host header allowlist (DNS-rebinding defence).** *Stage 5.* Add Starlette
`TrustedHostMiddleware` with `FXBOT_ALLOWED_HOSTS` *(proposed)*, default
`localhost,127.0.0.1`, plus the proxy hostname when one is used. Requests with any other `Host` get
400. Without this, a hostile web page can resolve its own domain to `127.0.0.1` and talk to the API.

**SR-32 — Security headers.** *Stage 5 (API), 6 (compatibility), 7 (nginx).*
- **SPA (nginx):**
  `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`
  (as in `frontend/nginx.conf` and `vite.config.ts` `preview.headers`; keep the two in sync).
  Relax `style-src` to `'self' 'unsafe-inline'` only if a dependency injects `<style>` elements.
  Never relax `script-src`.
- **API responses:**
  `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` and `Cache-Control: no-store`.
- **Both:** `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin`,
  `Permissions-Policy: camera=(), microphone=(), geolocation=()`.
- `Strict-Transport-Security: max-age=31536000` is sent only when serving HTTPS.
- No `Server` version: uvicorn `server_header=False` (already set) and nginx `server_tokens off`.
- nginx gotcha: an `add_header` inside a `location` block drops every server-level `add_header`.
  Use `always` and repeat the headers, or use an include file.

**SR-33 — WebSocket.** *Stage 5.*
- Authenticate during the handshake, **before `accept()`**: valid session cookie, and an `Origin`
  header in the allowlist. This blocks cross-site WebSocket hijacking. On failure, close with 1008.
- Never put credentials in the WS URL or query string; they end up in access and proxy logs.
- Re-check the session expiry periodically (≤ 60 s) and close expired connections.
- Client → server messages are limited to `subscribe`, `unsubscribe` and `ping`. They are
  validated by a Pydantic model and capped at 4 KiB. No state-changing operations go over WS.
  They go through REST, with CSRF checks, validation and audit.
- Bounded per-client queues (ARCHITECTURE §5) and at most 5 concurrent connections
  *(placeholder)*.

**SR-34 — Input validation everywhere.** *Stage 5.*
- Every body and query model is Pydantic with `extra="forbid"`.
- Explicit bounds: `Field(ge=…, le=…)`, string `max_length`, `Literal` or enums for modes, sides,
  actions and strategy IDs.
- `allow_inf_nan=False`. Starlette's `request.json()` accepts the `NaN` and `Infinity` tokens.
- **Custom `RequestValidationError` handler** that returns only `loc`, `msg` and `type` for each
  error, never `input` or `ctx`. We verified that FastAPI's default 422 body echoes the submitted
  value, so a rejected login echoes the password. When that value is `NaN`, serializing it fails
  and the client gets a 500 instead of a 422.
- The instrument regex and allowlist from SR-14 apply.
- Pagination `limit` ≤ 500 *(placeholder)*.
- Sort and filter fields are mapped through an allowlist, never interpolated.
- Request bodies ≤ 1 MiB, enforced in nginx (`client_max_body_size 1m`, already configured) and,
  for direct access, in middleware.

**SR-35 — Settings and control changes.** *Stage 3 (caps), 5 (API).*
- `PATCH /api/settings` accepts only the documented, non-secret keys. Values above the hard caps
  (SR-15) return 422.
- A change that **loosens** a risk limit requires an explicit `confirm: true` field in the request
  (the UI shows old → new values first).
- Each change is applied atomically, persisted, and audited with before and after values.
- Kill switch, entry pause, promotion, rollback and manual close are `POST` actions with a
  `reason` and are audited.

**SR-36 — Error and docs exposure.** *Stage 5.*
- Unhandled errors return `{"error": "internal_error", "request_id": …}`, with no stack traces and
  never `debug=True`.
- `/api/docs` and `/api/openapi.json` are disabled outside `paper`, or served only behind auth.
  Today they are unconditional; see the review log.

**SR-37 — Expensive jobs are bounded.** *Stage 5.*
- Backtests and retraining run in the process pool, never on the event loop.
- One job at a time per kind *(placeholder)*.
- Requests are bounded (date range, instruments, bars) and jobs time out.
- Queued jobs beyond the limit are rejected with 429.

### E. Frontend

**SR-38 — No credentials in browser-readable places.** *Stage 6.*
- Auth relies only on the HttpOnly cookie, and requests use `fetch(…, {credentials: "same-origin"})`.
- No `Authorization` header is built in JS, and there is no `document.cookie` access.
- `localStorage` and Zustand `persist` hold UI preferences only (use `partialize`).
- No secrets in `VITE_*` variables: everything prefixed `VITE_` ships to the browser.

**SR-39 — XSS hygiene and CSP compatibility.** *Stage 6.*
- None of these: `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `document.write`, `eval`, `new Function`, or string `setTimeout`.
- Broker, strategy and journal strings are rendered as text.
- Any URL built from data goes through an `http(s):` scheme allowlist before it reaches an `href`.
- External links use `rel="noopener noreferrer"`.
- No third-party runtime origins (fonts are self-hosted via `@fontsource`; no CDNs or analytics).
- The production build contains no inline `<script>`.

**SR-40 — Safe controls.** *Stage 6.*
- The mode badge is visible on every page; `live` is high-contrast.
- Kill-switch **engage** takes at most two clicks, with no typing. **Release** requires typed
  confirmation (this deliberately differs from the current ROADMAP stage 6 wording; see the review
  log).
- Loosening a risk limit, manual close, promote and rollback open a confirm dialog that shows the
  old and new values.
- Numeric inputs mirror server bounds; the server stays authoritative.
- On 401 the app clears the session state and redirects to login once, without looping.

**SR-41 — Dev server stays local.** *Stage 6.* The Vite dev server binds to localhost only: no
`--host` or `server.host: true` on untrusted networks. It is never used in deployment. Keep `vite`
patched: dev-server file-read bypasses (`server.fs.deny`) have shipped as CVEs.

### F. Persistence, models and data

**SR-42 — SQL through SQLAlchemy only.** *Stage 1 onward.* Use the ORM or Core with bound
parameters. Never build `text()` with f-strings, `%` or `.format`. Dynamic columns or sort keys go
through allowlist mappings. Ruff `S608` stays enabled.

**SR-43 — Model artefacts are never loaded from outside the system.** *Stage 4.*
- ADR 0005's pickled scikit-learn artefacts are acceptable only because:
  1. only the trainer writes them, into `DATA_DIR/models/`;
  2. their SHA-256 is recorded in `model_versions` at save time and checked **before** loading.
     A mismatch means refuse, audit, and keep the champion.
  3. there is no upload, import or URL-load path, in the API or anywhere else;
  4. model IDs are resolved to paths inside the models directory: `Path.resolve()` plus an
     `is_relative_to(models_dir)` check.
- Any model that comes from outside (import, sharing between machines) must use **skops**
  (`skops.io.load` with an explicit `trusted` list, never blanket trust) or **ONNX**. It goes
  through a security review first.
- Banned on external or untrusted data:
  - `pickle.load`, `joblib.load`, `pd.read_pickle`;
  - `np.load(allow_pickle=True)`;
  - `yaml.load` (use `safe_load`);
  - `eval` and `exec`;
  - `DataFrame.eval` and `DataFrame.query` with external strings.

**SR-44 — External market data is untrusted input.** *Stage 1.*
- Downloaded, CSV and replay data must pass these checks:
  - schema and types;
  - tz-aware UTC timestamps, strictly increasing;
  - finite, positive OHLC with `high ≥ max(open, close)` and `low ≤ min(open, close)`.
- Rows are size-limited.
- File paths are built from validated instrument and granularity enums only (no path traversal).

**SR-45 — Data at rest.** *Stage 5, 7.*
- `DATA_DIR` (journal, models, lock file, backups) is mode `0700` and its files `0600`, owned by
  the service user. `.env` and secret files are `0600`.
- The DB never stores secrets: the `settings` table holds non-secret keys only.

### G. Supply chain and CI

**SR-46 — Locked dependencies.** *Stage 0 onward.* `backend/uv.lock` and
`frontend/package-lock.json` are committed. CI uses `uv sync --locked` and `npm ci`; Docker builds
use `uv sync --frozen` and `npm ci`. Dependency upgrades are explicit, reviewed changes: read the
changelog and watch for maintainer changes. Never install unpinned tools in CI.

**SR-47 — CI security job.** *Stage 0.* As specified in `docs/security/ci-security-job.md`:
- gitleaks over the pushed or PR commits, plus full history on the schedule;
- the fixture guard;
- `pip-audit` on the exported `uv.lock`, all groups;
- `npm audit --audit-level=high` on `package-lock.json`.

It runs on push, PR and a weekly schedule. A high or critical finding blocks the merge unless it is
recorded in section 10 with an expiry date.

**SR-48 — GitHub Actions hardening.** *Stage 0.*
- Workflow `permissions: contents: read` by default; add more per job only when needed.
- Third-party actions are pinned to a full commit SHA with a version comment.
- No `pull_request_target`. No secrets are needed in CI: broker credentials never go to CI, and
  tests never touch the network.
- `persist-credentials: false` on checkouts that don't push.
- Actions that declare the Node 20 runtime must be bumped (review log, F0-2).

**SR-49 — Static checks stay on.** *Stage 0 onward.* Ruff `S` (flake8-bandit) remains in `select`
for `src/`. Every `# noqa: S…` carries a one-line justification. The test suite blocks real sockets
(ARCHITECTURE §12: a conftest guard or `pytest-socket` `--disable-socket`).

**SR-50 — New dependencies need a reason.** *Any stage.* Every new runtime dependency is justified
in the PR. Check the exact package name (typosquats), the maintainer, recent releases and install
scripts. Prefer the stdlib or what is already locked. The planned additions for Stage 5 are
`argon2-cffi`, plus `pyjwt` only if JWT is chosen.

### H. Deployment and operations

**SR-51 — Hardened containers.** *Stage 7.* Backend and frontend images:
- run as a fixed non-root UID (for example 10001), or `nginx-unprivileged` for the frontend;
- use `read_only: true` with `tmpfs: [/tmp]`; the only writable volume is `/data`;
- `cap_drop: [ALL]` and `security_opt: [no-new-privileges:true]`;
- set memory and pids limits, and a healthcheck;
- use a multi-stage build with base images pinned by digest and no build tools or caches in the
  final image;
- ship a `.dockerignore` that excludes `.env*`, `.git`, `data/`, `.venv/`, `node_modules/`,
  `**/tests/fixtures/`.

**SR-52 — Secrets in containers.** *Stage 7.* Secrets are never baked into images or build args.
`env_file` is acceptable for paper and practice. For live, use **SHOULD** Compose `secrets:` (files
under `/run/secrets`, read via pydantic-settings `secrets_dir`). This keeps the token out of
`docker inspect`, `/proc/*/environ` and child processes.

**SR-53 — Remote access.** *Stage 7.* See section 8. Never serve the dashboard on plain HTTP
beyond loopback. The app's own auth stays on behind any proxy.

**SR-54 — Journal backups.** *Stage 7.*
- Take a daily online backup with the SQLite backup API (WAL-safe). Never `cp` a live DB file.
- Keep 14 daily and 8 weekly backups. Off-host copies are encrypted (for example with `age`).
- Backups never include `.env` or secret files.
- Test a restore monthly and during the Stage 7 drill (`PRAGMA integrity_check` → `ok`, then
  reconcile against the broker).
- With Postgres, use the `pg_dump` equivalent. Commands are in section 8.

**SR-55 — Host hygiene.** *Stage 7 (runbook).*
- Automatic OS security updates.
- Full-disk encryption on laptops.
- A dedicated OS user for the bot.
- SSH key-only auth on a VPS.
- NTP time sync (trading days, session expiry and audit order depend on the clock).

**SR-56 — Runbook, drills and go-live.** *Stage 7.*
- `docs/RUNBOOK.md` includes section 9 of this document.
- The Stage 7 E2E run exercises these drills: kill switch (UI and out-of-band), restart, restore,
  and token rotation (practice).
- Go-live checklist:
  - a dedicated OANDA sub-account funded only with risk capital;
  - a fresh token;
  - practice soak complete;
  - `FXBOT_MAX_ORDER_UNITS` set;
  - backups verified;
  - this document's review log has no open High findings.

## 7. Requirements by stage

| Stage | Must be met at the end of the stage | Security review |
|---|---|---|
| 0 Foundation | SR-1, SR-2, SR-4 (scaffold), SR-46 – SR-49 | — (this baseline) |
| 1 Broker & data | SR-3 – SR-7, SR-9, SR-10 (config + factory), SR-11, SR-14 (domain), SR-17 (adapter), SR-18 (feed), SR-23, SR-42, SR-44 | **Yes** |
| 2 Strategies & backtester | SR-13 (single path, `ApprovedOrder`), SR-42 | — |
| 3 Risk | SR-14, SR-15 (values + caps), SR-19 (core), SR-21 (risk events), SR-35 (caps) | — |
| 4 Learning | SR-20, SR-43 | — |
| 5 Engine + API + auth | SR-5, SR-9, SR-10 (engine, account-bound), SR-12, SR-13, SR-15 – SR-19, SR-21, SR-22, SR-24 – SR-37, SR-45 | **Yes** |
| 6 Dashboard | SR-32 (CSP compatibility), SR-38 – SR-41 | **Yes** |
| 7 Hardening & deploy | SR-8, SR-24, SR-32 (nginx), SR-45, SR-51 – SR-56; re-verify all | **Yes (final)** |

## 8. Deployment guidance

**Default (recommended): local only.** `docker compose up -d`; open `http://127.0.0.1:<port>`.
Nothing listens on other interfaces.

**Remote access, in order of preference:**

1. **SSH tunnel:** `ssh -N -L 8080:127.0.0.1:8080 user@host`, then open
   `http://127.0.0.1:8080` locally. Nothing new is exposed.
2. **Private VPN** (WireGuard or Tailscale): reach the host's VPN address. Bind the proxy to the
   VPN interface only.
3. **Internet-facing TLS reverse proxy:** only if 1 and 2 are impossible. Caddy gives automatic
   HTTPS:

   ```
   fx.example.com {
       reverse_proxy 127.0.0.1:8080
       header Strict-Transport-Security "max-age=31536000"
       request_body { max_size 1MB }
   }
   ```

   Add `fx.example.com` to `FXBOT_ALLOWED_HOSTS` and to the allowed origins (`https://fx.example.com`).
   Set the cookie `Secure` flag (and SHOULD use the `__Host-` prefix), and trust forwarded headers
   from the proxy only (SR-28). For an internet-facing deployment, SHOULD add a second layer in
   front of the app: an IP allowlist, client certificates, or proxy-level basic auth.

**Backups (SR-54), run on the host or in the container:**

```sh
# Online, WAL-safe backup with the SQLite backup API (no sqlite3 CLI needed)
python3 -c "import sqlite3,sys; s=sqlite3.connect('file:/data/fxbot.db?mode=ro', uri=True); \
d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close(); s.close()" \
  /data/backups/fxbot-$(date -u +%Y%m%dT%H%M%SZ).db
chmod 600 /data/backups/*.db
# Encrypt before copying off-host
age -r "$AGE_RECIPIENT" -o fxbot-YYYYMMDD.db.age /data/backups/fxbot-YYYYMMDD.db
# Restore test
python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('pragma integrity_check').fetchone()[0])" restored.db
```

## 9. Incident runbook

Keep the OANDA web or mobile login, with 2FA, available on a **second device**. Every playbook
below may need it.

| Situation | Do, in this order |
|---|---|
| **Runaway bot / unexpected orders** | 1. Engage the kill switch (dashboard, or CLI). 2. If that fails: `docker compose stop backend`. Positions keep their broker-side stops. 3. Flatten from the OANDA platform if exposure is unacceptable. 4. Copy the DB and logs before restarting. 5. Find the root cause before releasing the kill switch. |
| **Token possibly leaked** (seen in a repo, log or CI; lost laptop; unknown trades) | 1. Revoke the token in the OANDA portal (Manage API Access) from a clean device. 2. Engage the kill switch or stop the backend. 3. Review OANDA transaction history for activity the journal doesn't explain; close unauthorized positions. 4. Issue a new token and update the secret on the host. 5. If the token was committed, scrub history only after rotating. 6. Record the incident in section 11. |
| **Dashboard compromise suspected** | 1. Stop the backend. 2. Set a new password hash (and signing key, if JWT): all sessions are invalidated. 3. Review `risk_events` for settings changes, releases and manual closes. 4. Check proxy logs for source IPs. 5. Restore any loosened limits before restarting. |
| **Host compromise suspected** | 1. From another device: revoke the token, change the OANDA password, check 2FA. 2. Flatten via the OANDA platform. 3. Rebuild the host from scratch; do not clean it in place. 4. Restore the journal from a backup taken before the compromise; reconcile against the broker (the broker wins). 5. New token, new dashboard password. |
| **Journal corruption or loss** | 1. Stop the backend. 2. Restore the latest backup that passes `integrity_check`. 3. Start; reconciliation adopts broker state and records discrepancies. 4. Document the gap. Performance reports must flag the affected period. |

## 10. Accepted risks

| Risk | Why accepted | Compensating controls |
|---|---|---|
| Root or host compromise means full compromise | Out of scope for a self-hosted single-operator app | Fast revocation (section 9), dedicated sub-account, broker-side stops, backups |
| The OANDA token is not scoped to one sub-account | Broker limitation | SR-7 account lock; fund the bot's sub-account with risk capital only |
| Pickle-format model artefacts (ADR 0005) | Self-produced files only; simplest scikit-learn path | SR-43 hash check, no import path, data dir permissions |
| Single-factor dashboard login | Loopback/VPN by default; one operator | SR-24, SR-28, SR-53 second layer for internet exposure |
| gitleaks allowlists `backend/tests/fixtures/` | Tests need credential-shaped fakes | CI fixture guard (SR-47) fails on non-canonical token or account shapes |
| `env_file` secrets in paper/practice | Convenience; anyone who can read them can read secret files too | SR-52 for live, SR-45 permissions |
| Gaps through stop-loss prices | Market risk, not a security control | Risk engine caps, small position sizes |

Audit exceptions (a known vulnerability with no fix yet). Each needs an expiry date:

| Package | Advisory | Reason | Expires |
|---|---|---|---|
| — | — | — | — |

## 11. Review log

| Stage | Date | Commit | Result | Notes |
|---|---|---|---|---|
| 0 | 2026-10-02 | (uncommitted scaffold) | Baseline | Threat model, `.gitleaks.toml`, CI job spec. gitleaks: 0 findings on the working tree. `pip-audit` (59 locked packages) and `npm audit`: 0 known vulnerabilities. |

**Stage 0 observations** (not blocking Stage 0; each must be closed by the stage shown):

| ID | Sev | Finding | Fix by |
|---|---|---|---|
| F0-1 | Medium | `config.py` uses a bare boolean `FXBOT_LIVE_TRADING_CONFIRMED`; SR-10 requires `FXBOT_LIVE_CONFIRM_ACCOUNT_ID == FXBOT_OANDA_ACCOUNT_ID` | Stage 5 at the latest; preferably Stage 1 |
| F0-2 | Medium | (Fixed in Stage 0: actions bumped and SHA-pinned.) `.github/workflows/ci.yml` used `actions/checkout@v4` and `astral-sh/setup-uv@v6` (and `actions/setup-node@v4` in the frontend job draft). These declare the Node 20 runtime that GitHub has removed from hosted runners. Bump them and pin SHAs (versions in `ci-security-job.md`) | Stage 0 (CI merge) |
| F0-3 | Low | `create_app` always serves `/api/docs` and `/api/openapi.json`; no `TrustedHostMiddleware` or security headers yet | Stage 5 (SR-31, SR-32, SR-36) |
| F0-4 | Low | `docker-compose.yml` publishes the backend on `127.0.0.1:8000` and has no hardening options; no Dockerfiles yet | Stage 7 (SR-24, SR-51) |
| F0-5 | Info | `database_url` is a plain `str`; fine for SQLite, but a Postgres URL with a password must be a `SecretStr` (SR-1). The logging redactor already masks URL userinfo | When Postgres is used |
| F0-6 | Low | ROADMAP stage 6 asks for typed confirmation to **engage** the kill switch; SR-40 requires engage ≤ 2 clicks, with typing only to release | Fixed in Stage 0 (ROADMAP aligned) |
| F0-7 | Low | `frontend/nginx.conf` sets `X-Forwarded-For $proxy_add_x_forwarded_for`, which appends a client-supplied header. Use `$remote_addr` while nginx is the edge (SR-28) | Stage 5 (when the login limiter lands) |
| F0-8 | Low | Base images are tag-pinned, not digest-pinned: `python:3.11-slim-bookworm`, `ghcr.io/astral-sh/uv:0.8`, `node:22-alpine`, `nginxinc/nginx-unprivileged:1.30-alpine`. Compose lacks `read_only`, `cap_drop` and `no-new-privileges` | Stage 7 (SR-51) |

Already compliant in the scaffold:
- `logging.py` redacts stdlib and structlog records and renders tracebacks without locals (SR-4).
- `Settings` is frozen, uses `SecretStr` and `hide_input_in_errors=True`, and defaults to `paper`
  on `127.0.0.1`.
- `server_header=False`.
- Ruff `S` rules are on.
- `.gitignore` covers `.env*`.
- Both Dockerfiles are multi-stage and non-root (backend uid 10001, `uv sync --locked --no-dev`;
  frontend `nginx-unprivileged`). Both `.dockerignore` files exclude `.env*`; the backend's also
  excludes `tests/`.
- `nginx.conf` sends the SR-32 header set at server level (no `add_header` in locations),
  `server_tokens off` and `client_max_body_size 1m`. The CSP is mirrored in Vite `preview.headers`.
- The frontend keeps only UI preferences in `localStorage`, calls same-origin `/api`, has no inline
  scripts in `index.html`, and its only external link uses `rel="noopener noreferrer"`.
