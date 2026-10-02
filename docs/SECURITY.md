# Altimate FX — Threat Model and Security Requirements

Owner: security. Applies to every stage. `docs/PROJECT_BRIEF.md` wins on conflict; where this
document sets a requirement that ARCHITECTURE/ROADMAP only sketch, this document is the
requirement. Reviews happen at the end of stages 1, 1b, 5, 6 and 7 using
[`docs/security/review-checklist.md`](security/review-checklist.md). The CI security job is
specified in [`docs/security/ci-security-job.md`](security/ci-security-job.md). Stage review details
live next to it, for example [`docs/security/stage1-findings.md`](security/stage1-findings.md).

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

- One operator. There are no other users, no tenants and no public sign-up. The operator lives in
  Cameroon and trades through MetaTrader 5 (ADR 0007).
- **Production (live) deployment:** one **Windows VPS** that runs:
  - the MT5 terminal;
  - a localhost-only, authenticated `mt5-bridge` process;
  - the backend, natively, without Docker (research 08 §B.3).

  The operator's own PC is only a browser, reaching the dashboard through a tunnel (SR-69).
  Linux/Docker remains the development, CI and paper setup.
- Every service binds to `127.0.0.1` by default. Remote access is opt-in (section 8).
- **Brokers.** OANDA v20 (development data, practice) and MT5 at a broker's offshore entity (live).
- **MT5.** Our code drives a logged-in terminal over local IPC. Whoever controls that terminal
  session, or can call the bridge, can trade the account.
  - The **master password** trades. The **investor password** only reads.
  - There is no API host to pin, so the interlock binds to the account itself: login, server and
    trade mode (SR-60).
- **OANDA.** A personal access token gives full API access to the operator's
  v20 accounts and is **not scoped to one sub-account**. At the time of writing the v20 REST API
  has trading and account-data endpoints but no withdrawal endpoints. The realistic impact of a
  stolen token is therefore unauthorized trading (which can still wipe the balance) plus disclosure
  of account data. Treat the token as equivalent to the money.
- Practice and live are separate OANDA environments with separate hosts and separate tokens. A
  practice token does not authenticate against the live host, so a mismatch fails closed.
- Out of scope:
  - protecting against a fully compromised host (root or Administrator on the box owns
    everything);
  - a compromised broker or MT5 trade server;
  - the broker's solvency, and recovering funds from an offshore entity;
  - market risk, which is the risk engine's job, not a security control.

  Operator-side broker and scam risks get procedural rules (SR-70). Section 10 records the
  accepted risks explicitly.

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

Production on the Windows VPS (MT5, Stage 1b). Everything below runs as one non-admin Windows user:

```
 Operator's browser ──(TB1 over Tailscale or an SSH tunnel)──► backend 127.0.0.1:8000 (SPA + API)
                                                                  │
                                    (TB6: loopback HTTP, HMAC-signed requests)
                                                                  ▼
                                                     mt5-bridge 127.0.0.1:<port>, one worker thread
                                                                  │
                                    (TB7: named-pipe IPC, same Windows user)
                                                                  ▼
                                                     MT5 terminal (portable install)
                                                                  │
                                    (TB8: broker protocol, managed by the terminal)
                                                                  ▼
                                                     broker's MT5 trade server
 Operator ──(TB9: broker portal, deposits/withdrawals, chats)──► broker and third parties
 Administrator ──(TB10: RDP or provider console)──► Windows VPS
```

| Boundary | What crosses it | Main controls |
|---|---|---|
| TB1 browser ↔ app | Operator commands, account data | Auth, session cookie flags, CSRF and Origin checks, Host allowlist, CSP, validation (SR-24 – SR-41) |
| TB2 operator ↔ host | Secrets, mode, start/stop | Env/secret files, interlock, file permissions (SR-1, SR-9 – SR-12, SR-45) |
| TB3 app ↔ disk | Journal, audit, models | ORM only, append-only audit, hash-checked models, backups (SR-21, SR-22, SR-42 – SR-45, SR-54) |
| TB4 app ↔ broker | Orders, token | TLS, pinned hosts, account lock, fat-finger limits, rate limits, idempotency (SR-6, SR-7, SR-11, SR-13 – SR-19) |
| TB5 third-party code | Dependencies, actions | Lockfiles, audits, SHA-pinned actions, secret scanning (SR-46 – SR-50, SR-71) |
| TB6 backend ↔ bridge | Order requests, account data | Loopback bind, HMAC with replay window, Host/Origin checks, allowlisted endpoints, bridge-side caps, idempotency store (SR-58, SR-59, SR-61, SR-62) |
| TB7 bridge ↔ terminal | Every MT5 call | Same non-admin user, one worker thread, account binding at every (re)connect and before every order (SR-60, SR-63) |
| TB8 terminal ↔ broker | Orders; the saved master password | Terminal hygiene; the master password is never in our config (SR-65, SR-66) |
| TB9 operator ↔ broker and third parties | Money, passwords | Operator rules (SR-70) |
| TB10 administrator ↔ VPS | Full control | No public RDP, admin separate from the service user, firewall, updates (SR-67, SR-68) |

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
| A8 | MT5 master password | Saved by the terminal for its Windows user; never in our config (SR-65) | Confidentiality | Full trading on the account from any MT5 client, anywhere |
| A9 | MT5 investor password | Wherever the operator shares it | Confidentiality (low) | Read-only: positions, history, balance |
| A10 | Bridge secret (HMAC key) | ACL'd secret files of the bridge and backend on the VPS | Confidentiality | Anyone holding it on the VPS can place orders through the bridge |
| A11 | Windows VPS (admin and RDP credentials, the service user's session) | VPS provider | Integrity, availability | Everything above, including the logged-in terminal |
| A12 | Broker client-portal login and funding channel (e.g. Mobile Money) | Operator | Confidentiality | Withdrawals redirected; deposits sent to a fake broker |

## 4. Threat actors

| ID | Actor | Capability | Most likely route |
|---|---|---|---|
| AC1 | Remote attacker | Reaches exposed ports. Or, more realistically, gets the operator's browser to load a hostile page | CSRF, DNS rebinding, cross-site WebSocket hijacking against the localhost API; brute force if the port is exposed |
| AC2 | Malicious dependency | Runs code at install, build or import time with the developer's or service user's privileges | Reads `.env` or env vars and exfiltrates the token; tampers with the build |
| AC3 | Leaked repo | Anyone who sees a public repo, fork, CI log or screenshot | Committed `.env`, recorded fixtures with real tokens or account IDs, logs pasted into issues |
| AC4 | Compromised host | Malware or an intruder with the service user's or root privileges | Reads secrets and the DB, trades directly; out of scope to prevent, in scope to limit and detect |
| AC5 | Operator error | Legitimate access, wrong input | Wrong mode or account, risk 10 instead of 1.0, units off by 100×, releasing the kill switch by accident |
| AC6 | Buggy strategy / runaway loop | The bot itself | Order storms, flip-flopping, NaN or inf sizes, stale prices, duplicate orders on retry, JPY pip-size bugs |

| AC7 | Scammer / social engineer | Contacts the operator on Telegram, WhatsApp or Facebook: fake "account managers", clone brokers, signal sellers, "recovery" services | Asks for the master password, remote-desktop access, an EA or "bot" install, or deposits to a personal number |
| AC8 | Local process or user on the VPS | Malware in the service user's session, another RDP user, a browser opened on the VPS | Calls the loopback bridge or backend; reads `.env`, secret files and the DB |
| AC9 | VPS host (provider, or the broker for a broker-supplied VPS) | Hypervisor or administrator access | Reads secrets and the terminal session; unavoidable, so choose the host deliberately |

AC5 and AC6 are the most likely sources of real loss, so the order path gets the deepest
defences (SR-13 – SR-19, SR-57). On MT5, AC7 (the operator being talked into giving away
access) is the most likely route to a total loss.

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
| T-32 | S/E | Bridge reachable beyond loopback: `0.0.0.0` bind, the Windows Firewall "Allow access" prompt, a port forward, a tunnel forwarding it. Anyone on the network places orders | AC1 | A2, A10 | SR-58, SR-59, SR-67 |
| T-33 | S | A local process, or a browser page via DNS rebinding, calls the loopback bridge | AC8, AC1 | A2 | SR-58 (Host and Origin checks), SR-59 |
| T-34 | T | A captured bridge request is replayed or altered (logs, local proxy, debugging tools) | AC8 | A2 | SR-59, SR-62 |
| T-35 | E | Generic RPC in the bridge (RPyC `eval`, pass-through of module calls) turns it into remote code execution | AC1, AC8 | all | SR-61, SR-71 |
| T-36 | T/E | The terminal is logged into the wrong account (real instead of demo, another login, a contest account), switched in the terminal UI or after a reinstall | AC5 | A2 | SR-60, SR-10 |
| T-37 | I | The MT5 master password is stored, logged or shared (`.env`, service config, screenshots, an "account manager") | AC3, AC7 | A8 | SR-65, SR-68, SR-70 |
| T-38 | T | Duplicate MT5 orders after an ambiguous retcode or a bridge timeout; the broker rewrites the comment, so the lookup misses | AC6 | A2 | SR-62 |
| T-39 | T | MT5 deal filled without an SL (stripped under Market Execution); an SL removed or widened through SLTP | AC6, AC8 | A2 | SR-57, SR-61 |
| T-40 | D | Terminal closed, logged out, disconnected, Algo Trading off, or restarted by auto-update; module calls hang | AC6, AC5 | A2 | SR-63, SR-18 |
| T-41 | E | VPS compromised through public RDP (brute force, credential stuffing), missing patches, or browsing and email on the trading box | AC1, AC4 | all | SR-67 |
| T-42 | I | Secrets readable by other local accounts: NSSM/registry environment, Task Scheduler arguments, inherited ACLs on `C:\fxbot`, `setx` machine variables | AC8 | A1, A8, A10 | SR-68 (F1-4) |
| T-43 | S | Social engineering of the operator: fake account managers, clone brokers, signal sellers, "recovery" and "withdrawal fee" scams, remote-desktop requests | AC7 | A8, A11, A12 | SR-70, SR-65 |
| T-44 | E | A third-party EA, indicator, script or DLL inside the bot's terminal trades the same account or reads its data | AC2, AC7 | A2, A8 | SR-66 |
| T-45 | I/T | Broker-supplied free VPS: the broker's staff or contractor administers the machine that holds every secret | AC9 | all | SR-67; accept in section 10 if used |
| T-46 | I/E | Dashboard exposed on the VPS public IP (no tunnel), possibly over plain HTTP | AC1 | A4 | SR-69, SR-24, SR-53 |
| T-47 | T | Clock skew on the VPS breaks server-time detection, bar alignment and session expiry | AC6 | A2, A3 | SR-67 (time sync), SR-63 (offset re-check) |

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
is not listed, it refuses to start. Trading calls are refused until that check has passed (F1-5).
For MT5, SR-60 is the equivalent check.

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

**SR-10 — Live needs an explicit, account-bound opt-in.** *Stage 1 (config and factory: done),
Stage 1b (MT5), Stage 5 (engine).* `live` starts only when all of these hold:
- `FXBOT_TRADING_MODE=live`;
- `ALLOW_LIVE_TRADING=true`, unprefixed, read from the **process environment only**. A value in
  `.env` is ignored (F1-3), so going live always takes a deliberate step outside the config file;
- `FXBOT_LIVE_TRADING_CONFIRMED=true`, kept as an extra gate (lead decision);
- `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` equals the account being traded: `FXBOT_OANDA_ACCOUNT_ID` for
  OANDA, the MT5 login for MT5 (SR-60).

The confirmation is account-bound, so it cannot silently carry over to another account. The check
runs in `Settings` validation, in `brokers/factory.py` and in `TradingEngine.start()`; for MT5 it
also runs in the bridge (SR-60). Every refusal exits non-zero, names the missing items and prints no
secret.

**SR-11 — Broker hosts are pinned by mode.** *Stage 1.* `practice` maps to
`api-fxpractice.oanda.com` and `stream-fxpractice.oanda.com`; `live` maps to
`api-fxtrade.oanda.com` and `stream-fxtrade.oanda.com`. The mapping lives in one module. No setting
accepts a free-form broker URL. Tests swap the transport (respx / `httpx.MockTransport`) instead of
the URL. *Verify:* `grep -rnE "fxtrade|fxpractice" backend/src` hits one file; a test asserts that
`paper` and `practice` can never resolve to an `fxtrade` host. MT5 has no host to pin: SR-60 binds
to the account instead.

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
- Every order attaches `stopLossOnFill` (MT5: `sl` on the DEAL), so the broker protects the
  position even if the bot or host dies. Every fill is then verified (SR-57).

**SR-15 — Fat-finger limits: a second, independent check before any order is sent.** *Stage 3
(values), Stage 5 (enforced in `OrderManager`).* These checks deliberately do not reuse the sizing
code, so they catch sizing bugs (for example the ×100 JPY pip-value error).

| Check | Default *(placeholder)* | Hard cap in code | On breach |
|---|---|---|---|
| Units per order | `FXBOT_MAX_ORDER_UNITS` *(proposed)*: 100 000 in paper/practice; **must be set explicitly for live** | 1 000 000 | Reject + `CRITICAL` risk event |
| Notional per order (account ccy) | ≤ 5 × NAV | ≤ 10 × NAV | Reject + `CRITICAL` |
| Risk at stop, recomputed from units × stop distance × pip value | ≤ 1.25 × the trade's intended risk (base risk × allocator multiplier × meta factor, SR-20) | ≤ 2 % NAV | Reject + `CRITICAL` (sizing bug) |
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
| Consecutive order errors (rejects, unknown outcomes, broker failures) | 3 (lead decision) | 3 | Pause entries + `CRITICAL` (ARCHITECTURE §10) |

Separately, the broker client's HTTP token bucket (Stage 1) protects OANDA's request limits. It
does not replace these order-level limits.

**SR-17 — Idempotent submits and no blind retries.** *Stage 1 (adapter), 5 (manager).*
- Every order carries a deterministic `client_id`, sent as `clientExtensions.id`.
- An order POST is **never** retried automatically. After a timeout, connection error or 5xx the
  order is `UNKNOWN` and is resolved by looking up the `client_id` (and by reconciling) before any
  resubmit.
- Only idempotent GETs are retried, with backoff and jitter.
- Once the order request may have reached the broker, `submit_order` returns a result (`FILLED`,
  `CANCELLED`, `REJECTED` or `UNKNOWN`) instead of raising (SR-57, F1-1).
- MT5 specifics (magic + comment, idempotency store, retcode classes) are in SR-62.

*Verify:* ROADMAP `test_order_manager.py`; `grep -rnE "retry|backoff|tenacity" backend/src/fxbot/brokers`
then confirm no POST is wrapped.

**SR-57 — Every fill is protected, and the caller knows it.** *Stage 1 (OANDA, F1-1/F1-2),
1b (MT5), 5 (engine).*
- **Every `FILLED` result is checked for a broker-side stop**, whichever path produced it: a fresh
  submit, an order already known to the broker, or one resolved by client-ID lookup after a
  timeout.
  - If the stop is missing, attach it. If that fails, close the trade.
  - If the close fails too, the outcome is `UNPROTECTED`.
  - The fail-safe catches every exception type, not only broker errors, and never raises.
- **The result carries the outcome:** `VERIFIED`, `ATTACHED`, `CLOSED` (with the closing fill),
  `UNPROTECTED` or `UNVERIFIED`. A `CLOSED` trade is never journaled as open.
- **`UNPROTECTED` and `UNVERIFIED` are `CRITICAL`.** The engine pauses entries and keeps
  re-verifying, attaching or flattening until the trade is protected or closed.
- **Fatal exceptions:** the only exceptions `submit_order` may raise once the request may have
  reached the broker are authentication failures and an account mismatch. The engine treats
  both as fatal and engages the kill switch. The order manager treats any other exception as
  `UNKNOWN` and reconciles.

*Verify:* the suggested tests in `docs/security/stage1-findings.md`; for Stage 1b, the contract
suite with a fake broker that strips SL on market execution.

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

**SR-20 — Learning stays inside the hard caps.** *Stage 4.*
- The meta-model can veto a signal or scale it within `[0, 1]`.
- The allocator outputs one multiplier per strategy, clamped to `[0.5, 1.5]` (lead decision).
  The per-trade risk is base risk × allocator multiplier × meta factor.
- That product is always clamped afterwards by the risk engine's hard caps (risk per trade ≤ 2 %
  NAV, the live phase-1 cap) and checked by the fat-finger limits (SR-15). Learning can raise a
  strategy's risk by up to 1.5×, but never above those caps.
- Multipliers are finite and range-checked when loaded; a NaN or out-of-range value falls back
  to 1.0 and raises an alert.
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
- **Windows VPS (no Docker, no nginx):**
  - the backend serves the SPA and the API on `127.0.0.1` itself and sends the SR-32 SPA headers;
  - forwarded headers are never trusted, because there is no proxy;
  - a non-loopback `FXBOT_API_HOST` is refused unless remote access is configured per SR-69;
  - an inbound firewall block rule exists for the port (SR-67).
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
- **SPA served by the backend** (Windows VPS): the backend sends the same SPA header set on the
  SPA and its static files.
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
  the service user. `.env` and secret files are `0600`. The SQLite file is created `0600` before
  SQLite opens it (SQLite gives `-wal`/`-shm` the same mode), or the process sets `umask 077`
  (F1-4).
- On Windows, POSIX modes do nothing: the install folder's ACL does this job (SR-68).
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

**SR-51 — Hardened containers.** *Stage 7.* This applies to Docker deployments (development, CI
and paper on Linux). The Windows production host follows SR-67 and SR-68 instead. Backend and
frontend images:
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
- Windows VPS:
  - run the same Python one-liner from Task Scheduler as the service user, into a folder inside
    the ACL'd install directory (SR-68);
  - encrypt before the copy leaves the VPS;
  - include the bridge's idempotency and audit stores.

**SR-55 — Host hygiene.** *Stage 7 (runbook).*
- Automatic OS security updates.
- Full-disk encryption on laptops.
- A dedicated OS user for the bot.
- SSH key-only auth on a VPS.
- NTP time sync (trading days, session expiry and audit order depend on the clock).
- Windows VPS: SR-67 replaces this list.

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
- MT5 go-live additions:
  - the broker has been verified and a small withdrawal has succeeded (SR-70);
  - a hedging (`margin_mode = 2`) real account, with the lowest available leverage;
  - SR-60 checks pass against the real login;
  - the demo soak is complete, through the same bridge build;
  - the VPS hardening checklist (SR-67, SR-68) has been verified;
  - the bridge secret has been rotated since the last install.

### I. MetaTrader 5, the bridge and the Windows VPS (Stage 1b)

The bridge is a new trust boundary that can place orders (ADR 0007). Research 08 §B.4 lists its
baseline. The requirements below make it testable.

**SR-58 — Bridge network exposure.** *Stage 1b.*
- **Bind.** The bridge binds `127.0.0.1` and refuses to start on any other address. Binding to a
  private tunnel interface (a remote-backend topology) is a separate, explicitly configured mode.
  It needs SR-59 plus an encrypted tunnel (WireGuard/Tailscale, or TLS) and its own review
  before use.
- **Host header.** The `Host` header must be `127.0.0.1:<port>` or `localhost:<port>`; anything
  else is refused (DNS-rebinding defence).
- **Origin header.** Any request carrying an `Origin` header gets 403. The bridge has no browser
  clients, so this blocks every web page. It never sends CORS headers.
- **Firewall.** An inbound Windows Firewall block rule for the bridge port is created at install.
  Never accept the firewall's "Allow access" prompt for `python.exe` (SR-67).

*Verify:* `tests/brokers/mt5/test_bridge_security.py`; on the VPS,
`Get-NetTCPConnection -State Listen -LocalPort <port>` shows `127.0.0.1` only.

**SR-59 — Bridge authentication and replay protection.** *Stage 1b.*
- **Secret.** A shared secret of ≥ 32 random bytes (`secrets.token_urlsafe(32)`), in
  `FXBOT_MT5_BRIDGE_SECRET` *(proposed)*, held as `SecretStr` in both processes and loaded per
  SR-68. It is generated at install and rotated on reinstall or on suspicion.
- **Signed requests.** Every request carries a timestamp, a nonce (≥ 16 random bytes) and an
  HMAC-SHA256 signature over method, path with query, timestamp, nonce and SHA-256(body).
  Header names are *(proposed)*: `X-AFX-Timestamp`, `X-AFX-Nonce`, `X-AFX-Signature`. A bare
  bearer token alone is not enough, because it can be replayed.
- **Rejections.** The bridge returns 401 with no detail when:
  - the signature is missing or wrong (compared with `hmac.compare_digest`);
  - the timestamp is outside ±30 s;
  - the nonce was already seen within the window.
- **Brute force.** Failed authentication is rate-limited (≤ 10 per minute) and logged without the
  secret or the signature.

**SR-60 — MT5 account binding and mode interlock.** *Stage 1b.* MT5 has no host to pin, so the
bridge checks the account itself.
- **When.** At start, after every `initialize()` or reconnect, after a terminal build change, and
  immediately before every `order_send`.
- **What.** It reads `account_info()` and `terminal_info()`. If any of the following fails, it
  refuses every trading call with 409 and a `CRITICAL` log, and the backend pauses entries:
  - `login` equals `FXBOT_MT5_LOGIN` *(proposed)* and `server` equals `FXBOT_MT5_SERVER`
    *(proposed)*;
  - `trade_mode` is `0` (DEMO) in `practice` and `2` (REAL) in `live`; `1` (CONTEST) is always
    refused;
  - `margin_mode` is `2` (hedging) in `live`. Netting is refused in live and limited in practice
    (research 08 §D.6). `fifo_close` is false;
  - `account_info().trade_allowed` and `trade_expert` are true;
  - `terminal_info().trade_allowed` is true and `tradeapi_disabled` is false.
- **Mode agreement.** The bridge is configured with the mode, and every order request repeats it.
  Any disagreement between the request, the configuration and `trade_mode` means refuse.
- **Live.** It also needs everything in SR-10, including `FXBOT_LIVE_CONFIRM_ACCOUNT_ID == MT5
  login` and an environment-only `ALLOW_LIVE_TRADING`. These are checked in config, factory and
  engine; entries start paused (SR-12).
- **Backend side.** The adapter re-reads the bridge's account identity (masked login, server,
  trade mode) at connect and after every bridge reconnect. No trading calls before that (F1-5).
  Logs mask the login to its last 3 digits.

**SR-61 — Bridge surface and validation.** *Stage 1b.*
- **Allowlist.** Only the endpoints in research 08 §B.4: health, account, symbols, tick, rates,
  ticks, positions, orders, history deals and orders, order check, order send, reconnect. There is
  no generic call, `eval`, RPyC, pickle, `getattr(mt5, name)` dispatch or file access. An unknown
  path returns 404.
- **Request models.** Pydantic with `extra="forbid"`, finite numbers and bounded values; bodies are
  ≤ 64 KiB.
- **`order/send` fields:**
  - `action` is DEAL or SLTP only; PENDING, MODIFY, REMOVE and CLOSE_BY get 422;
  - `symbol` is in the configured map;
  - `volume` is a multiple of `volume_step` and ≤ `FXBOT_MT5_MAX_LOTS` *(proposed)*, a bridge-side
    cap independent of the backend's caps;
  - `magic` is in our range;
  - `comment` matches `^afx:[A-Z2-7]{12}$`;
  - `deviation` is bounded;
  - `type_filling` is set explicitly.
- **Opening DEAL.** `sl` is mandatory, on the losing side and outside `trade_stops_level`.
- **Closing DEAL.** It needs a `position` ticket carrying our `magic` and a volume no larger than
  the position.
- **SLTP.** It needs a `position` ticket carrying our `magic`. It refuses `sl = 0` (removing a stop)
  and any new SL that increases the position's risk. Stops only tighten; reconciliation may set a
  missing SL.
- **Positions without our `magic`** are never modified or closed by the bot. The kill switch
  flattens our positions and raises an alert listing external ones.

**SR-62 — MT5 idempotency and retries.** *Stage 1b.*
- **Idempotency key.** `POST /order/send` requires an `Idempotency-Key`: our client ID,
  format-checked.
  - Before calling `order_send`, the bridge commits the key as `IN_FLIGHT` in its SQLite store.
  - A repeat while the key is in flight gets 409; a repeat after completion gets the stored
    result.
  - Keys are kept for ≥ 7 days. After a bridge restart, `IN_FLIGHT` keys are resolved by
    reconciliation before any new order.
- **Persist first.** The backend persists the intent (client ID, short ID, request) before calling
  the bridge.
- **Ambiguous outcomes:**
  - these are `None` with an IPC error, 10012 TIMEOUT, 10031 CONNECTION, 10011 ERROR, or a bridge
    or HTTP timeout;
  - there is no resend until reconciliation has run: search by `magic` + comment token, then by
    `magic` + symbol + side + volume + time window, because brokers rewrite comments;
  - automatic retries are allowed only for 10004/10020 (≤ 2, within the max slippage) and 10030
    (once, with the next filling mode).

**SR-63 — Bridge runtime.** *Stage 1b.*
- **One worker thread** owns the `MetaTrader5` module, and every call is queued to it. Per-call
  timeouts are 30 s for trading calls and 10 s for reads. When the bounded queue is full, the
  bridge returns 503.
- **Rate.** At most 1 trading request per second per account.
- **Watchdog.** Every 10 s the bridge calls `terminal_info()` and `account_info()`.
  - If the terminal is disconnected, logged out or has algo trading off, health reports it,
    trading calls return 503, and the backend pauses entries (SR-18).
  - Recovery runs the SR-60 checks, then reconciliation, before entries resume.
- **Server time.** The server-time offset is re-detected at start and daily (research 08 §A.10). A
  change outside the DST dates pauses entries.

**SR-64 — Bridge logging, audit and leak tests.** *Stage 1b.*
- **Logs** carry the request ID, endpoint, retcode, timings and the masked login. They never carry
  the secret, signatures, passwords, or full request and response bodies at INFO.
- **Redaction.** The bridge uses `fxbot.logging`, so the same redaction applies, extended with the
  bridge secret and MT5 password patterns.
- **Audit.** An append-only audit (JSONL or SQLite) records every order send, SLTP and close: key,
  request without secrets, retcode, deal, order and position tickets, and timestamps.
- **Leak tests.** `tests/test_secrets.py` is extended: bridge-secret and MT5-password sentinels
  never appear in logs, errors, responses or `repr`.

**SR-65 — MT5 credentials.** *Stage 1b.*
- **The master password is not stored by our software.** Log in once, interactively, in the
  terminal with "save password". The bridge calls `initialize(path, portable=True)` without
  `login` or `password`.
- **If a password must be passed** (for example after a reinstall), only the bridge reads it, as
  `SecretStr`, from Windows Credential Manager or an ACL'd secret file (SR-68). It never goes in
  the backend's settings, `.env`, command lines, service definitions or the repo. OTP and
  certificate accounts cannot log in from Python; that is fine.
- **The investor (read-only) password** is the only credential given to anyone or anything that
  just watches: monitoring apps, accountants, people "checking" results.
- **Rotation.** After any suspected exposure, change the master password through the broker
  (section 9).
- **Repo scanning.** gitleaks' `mt5-password-assignment` rule and the CI fixture guard cover the
  repo.

**SR-66 — Terminal hygiene.** *Stage 1b.*
- **A dedicated portable terminal** (e.g. `C:\fxbot\mt5\`) is used only by the bot. It is
  installed from the broker's official domain, reached through the regulator register (SR-70).
- **No third-party code** in that terminal: no Expert Advisors, indicators, scripts or market
  products.
- **Settings:** "Allow DLL imports" off, "Allow WebRequest" off, Algo Trading on, and "Disable
  automatic trading via external Python API" unchecked in this terminal only.
- **One user.** The terminal, bridge and backend run as the same dedicated non-admin Windows user
  (SR-67).
- **Builds.** A terminal build change is logged and triggers the SR-60 checks.

**SR-67 — Windows VPS hardening.** *Stage 1b (setup guide), Stage 7 (verified).*
- **Users.** A dedicated standard (non-admin) user runs the terminal, bridge and backend. A
  separate administrator account is used only for maintenance. No shared accounts.
- **RDP is not reachable from the internet.** Use the provider's web console, or RDP only over
  Tailscale/WireGuard. If public RDP cannot be avoided:
  - allowlist IPs in both the provider firewall and Windows Firewall;
  - turn on Network Level Authentication;
  - set an account lockout policy;
  - use a long, unique passphrase and a non-default admin name.
- **Firewall.** Windows Defender Firewall is on for every profile, with inbound default deny.
  There are no inbound allow rules for the backend or bridge ports, and explicit block rules are
  created at install so an "Allow access" prompt cannot open them.
- **Updates and antivirus.**
  - Automatic Windows updates restart in a weekend window.
  - Microsoft Defender is on.
  - The terminal's unattended restart after a reboot is tested (research 08 §E).
- **Single purpose.** No web browsing, email or other software on the trading VPS. No
  remote-desktop tools (AnyDesk, TeamViewer and the like).
- **Time.** `w32tm` sync is enabled and checked (`w32tm /query /status`).
- **Who controls the VPS.** For live, prefer a VPS the operator controls over a broker-supplied
  free VPS (T-45). If a broker VPS is used, record it in section 10.

**SR-68 — Windows secrets, files and services.** *Stage 1b, Stage 7.*
- **Install folder ACL.** Install under a folder whose ACL grants only the service user, SYSTEM
  and Administrators, for example:
  `icacls C:\fxbot /inheritance:r /grant:r "fxbot:(OI)(CI)M" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"`.
  `.env`, secret files, `FXBOT_DATA_DIR`, the bridge's idempotency and audit stores, and backups
  all live there. Verify with `icacls`. The code's POSIX modes do nothing on Windows (F1-4).
- **No secrets in service definitions.** That means not in NSSM `AppEnvironmentExtra` (stored in
  the registry), Task Scheduler arguments, an `sc.exe` `binPath`, or `setx /M` machine variables.
  Services read secrets from the ACL'd files, or from Credential Manager/DPAPI.
- **`ALLOW_LIVE_TRADING` is the deliberate exception.** It is a non-secret switch that must come
  from the process environment (SR-10). Set it in the backend service's environment for a live
  run, and remove it to go back.
- **Paths.** Services use an absolute working directory and an absolute `FXBOT_DATA_DIR`. A
  service's default working directory is `C:\Windows\System32`.
- **Service accounts.** The bridge and backend log on as the non-admin user, restart on failure,
  and start after the terminal.

**SR-69 — Reaching the dashboard on the VPS.** *Stage 1b (guide), Stage 7.*
- The backend binds `127.0.0.1`. The operator reaches it in one of two ways:
  - Tailscale `serve` (tailnet-only HTTPS in front of `127.0.0.1:8000`; **never `funnel`**, which
    publishes to the internet);
  - an SSH tunnel to Windows OpenSSH Server, with key-only auth and port 22 reachable only from the
    tailnet or an allowlist.
- Tunnels forward the dashboard port only, **never the bridge port**.
- The tailnet hostname is added to `FXBOT_ALLOWED_HOSTS` and the allowed origins. App auth stays
  on.
- Internet-facing exposure is discouraged and, if used, follows SR-53.

**SR-70 — Operator and broker safety (procedural).** *Stage 1b (`docs/MT5_SETUP.md`), Stage 7
(runbook).* These rules are written into the setup guide and the runbook, and the dashboard shows
the account's `company` and `server` so a clone or unexpected server is visible:
1. Never share the MT5 master password, the broker-portal login or 2FA codes with anyone. No
   legitimate broker, "account manager" or support agent needs them. Share only the investor
   password.
2. Never install remote-desktop tools, EAs, "signal bots" or files sent by contacts. Never let
   anyone remote into the VPS.
3. Reach the broker only through the regulator's register entry; the domain must match. Download
   MT5 only from that domain, and check the server name against the broker's documentation.
4. Test the money path with small amounts: deposit, then withdraw part of it back to the same
   method before depositing more. No bonuses. Use the lowest leverage offered.
5. Stop immediately at these red flags: guaranteed returns, unsolicited contact, deposits to a
   personal (Mobile Money) number, fees demanded before a withdrawal, "recovery" services,
   pressure to deposit.
6. Protect the operator's email and broker portal with unique passwords and 2FA. The email is the
   reset path for both.
7. Keep statements and transfer receipts (tax and BEAC rules, research 08 §C.2).

**SR-71 — MT5 supply chain and test data.** *Stage 1b.*
- **The package.** `MetaTrader5` comes from PyPI only, as a Windows-only optional extra
  (`fxbot[mt5]`), locked with hashes in `uv.lock` and covered by `pip-audit`. The bridge imports it
  through the configured module name, so tests inject the fake.
- **No third-party bridges in the `live` path:** no `mt5linux`, RPyC, Wine bridge images or MetaApi
  (ADR 0007, research 08 §B.2). Wine experiments use demo accounts and loopback binds only.
- **Golden fixtures** under `backend/tests/fixtures/mt5/` use login `12345678`, masked names and
  `"<redacted>"` passwords. The CI fixture guard enforces logins and passwords.

## 7. Requirements by stage

| Stage | Must be met at the end of the stage | Security review |
|---|---|---|
| 0 Foundation | SR-1, SR-2, SR-4 (scaffold), SR-46 – SR-49 | — (this baseline) |
| 1 Broker & data | SR-3 – SR-7, SR-9, SR-10 (config + factory), SR-11, SR-14 (domain), SR-17 (adapter), SR-18 (feed), SR-23, SR-42, SR-44, SR-57 (OANDA adapter: F1-1, F1-2) | **Yes** (done; see section 11) |
| 1b MT5 adapter + bridge | SR-10 and SR-17 (MT5-aware), SR-18, SR-57, SR-58 – SR-66, SR-71; SR-67 – SR-70 as setup-guide content | **Yes** |
| 2 Strategies & backtester | SR-13 (single path, `ApprovedOrder`), SR-42 | — |
| 3 Risk | SR-14, SR-15 (values + caps), SR-19 (core), SR-21 (risk events), SR-35 (caps) | — |
| 4 Learning | SR-20, SR-43 | — |
| 5 Engine + API + auth | SR-5, SR-9, SR-10 (engine, account-bound), SR-12, SR-13, SR-15 – SR-19, SR-21, SR-22, SR-24 – SR-37, SR-45, SR-57 (engine side) | **Yes** |
| 6 Dashboard | SR-32 (CSP compatibility), SR-38 – SR-41 | **Yes** |
| 7 Hardening & deploy | SR-8, SR-24, SR-32 (nginx or backend-served SPA), SR-45, SR-51 – SR-56, SR-67 – SR-70 verified on the VPS; re-verify all | **Yes (final)** |

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

**Windows VPS with MT5 (production, Stage 1b).** No Docker and no nginx. The backend serves the
SPA and API on `127.0.0.1:8000` and the bridge listens on `127.0.0.1:<bridge-port>`, both as the
non-admin service user (SR-67, SR-68).

```powershell
# Pre-create block rules: block beats allow in Windows Firewall, so an "Allow access" prompt cannot expose these ports
New-NetFirewallRule -DisplayName "fxbot: block backend inbound" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Block
New-NetFirewallRule -DisplayName "fxbot: block bridge inbound"  -Direction Inbound -Protocol TCP -LocalPort <bridge-port> -Action Block
# Lock the install folder to the service user, SYSTEM and Administrators
icacls C:\fxbot /inheritance:r /grant:r "fxbot:(OI)(CI)M" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"
```

Reach the dashboard from the operator's PC (SR-69):
- **Tailscale:** `tailscale serve --bg 8000` on the VPS publishes `http://127.0.0.1:8000` as HTTPS
  inside the tailnet only. Check the syntax with `tailscale serve --help`, and never use
  `tailscale funnel`.
- **SSH:** `ssh -N -L 8000:127.0.0.1:8000 fxbot@<vps-tailnet-name>`, to Windows OpenSSH Server with
  key-only auth, then open `http://127.0.0.1:8000`.

Never forward the bridge port.

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

Keep the broker's own access on a **second device**: OANDA web or mobile with 2FA, or the MT5
mobile app. Every playbook below may need it.

| Situation | Do, in this order |
|---|---|
| **Runaway bot / unexpected orders** | 1. Engage the kill switch (dashboard, or CLI). 2. If that fails, stop the backend: `docker compose stop backend`, or stop the Windows service. On MT5, also switch **Algo Trading off** in the terminal; every Python trading call then fails with retcode 10027. Positions keep their broker-side stops. 3. Flatten from the broker's platform if exposure is unacceptable (OANDA web/mobile, MT5 terminal or mobile app). 4. Copy the DB, logs and bridge audit before restarting. 5. Find the root cause before releasing the kill switch. |
| **Token possibly leaked** (seen in a repo, log or CI; lost laptop; unknown trades) | 1. Revoke the token in the OANDA portal (Manage API Access) from a clean device. 2. Engage the kill switch or stop the backend. 3. Review OANDA transaction history for activity the journal doesn't explain; close unauthorized positions. 4. Issue a new token and update the secret on the host. 5. If the token was committed, scrub history only after rotating. 6. Record the incident in section 11. |
| **Dashboard compromise suspected** | 1. Stop the backend. 2. Set a new password hash (and signing key, if JWT): all sessions are invalidated. 3. Review `risk_events` for settings changes, releases and manual closes. 4. Check proxy logs for source IPs. 5. Restore any loosened limits before restarting. |
| **Host compromise suspected** | 1. From another device: revoke the token, change the OANDA password, check 2FA. 2. Flatten via the OANDA platform. 3. Rebuild the host from scratch; do not clean it in place. 4. Restore the journal from a backup taken before the compromise; reconcile against the broker (the broker wins). 5. New token, new dashboard password. |
| **Journal corruption or loss** | 1. Stop the backend. 2. Restore the latest backup that passes `integrity_check`. 3. Start; reconciliation adopts broker state and records discrepancies. 4. Document the gap. Performance reports must flag the affected period. |
| **MT5 master password possibly exposed** (shared with an "account manager", in a file or screenshot) | 1. From a trusted device, change the master password through the broker (client portal, or the terminal's change-password dialog); this ends other sessions. 2. Check the account history for deals the journal doesn't explain; close unauthorized positions. 3. Log the bot's terminal in again interactively with the new password (SR-65). 4. If the broker-portal or email password was shared too, change them and turn on 2FA. 5. Record the incident in section 11. |
| **Bridge secret possibly exposed, or unexplained orders with our magic** | 1. Switch Algo Trading off in the terminal and stop the bridge service. 2. Compare the bridge audit log, the backend journal and the broker history. 3. Treat the VPS as suspect (T-41): check users, services and scheduled tasks; rebuild if in doubt. 4. Rotate the bridge secret in both secret files before restarting. |
| **VPS unreachable or terminal down with open positions** | Positions keep their server-side SL/TP; client-side trailing stops pause. Monitor or close from the MT5 mobile app, restore the VPS, then let reconciliation run before resuming entries. |

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
| The MT5 terminal stores the master password for its Windows user | Needed for unattended operation; Python cannot handle OTP logins | SR-65 (never in our config), SR-67/SR-68 (non-admin user, ACLs), password-change runbook |
| `MetaTrader5` module behaviour (thread safety, edge cases) is undocumented; the fake module can drift | Vendor limitation | One worker thread (SR-63), demo acceptance, golden fixtures |
| The broker is an offshore entity; no local regulator can help recover funds | The practical option for a Cameroon resident (research 08 §C) | SR-70: verified broker, a withdrawal test, small deposits |
| The VPS provider has hypervisor access to the machine holding every secret | Inherent to renting a VPS | Reputable provider, SR-67, nothing else of value on the VPS |

Audit exceptions (a known vulnerability with no fix yet). Each needs an expiry date:

| Package | Advisory | Reason | Expires |
|---|---|---|---|
| — | — | — | — |

## 11. Review log

| Stage | Date | Commit | Result | Notes |
|---|---|---|---|---|
| 0 | 2026-10-02 | (uncommitted scaffold) | Baseline | Threat model, `.gitleaks.toml`, CI job spec. gitleaks: 0 findings on the working tree. `pip-audit` (59 locked packages) and `npm audit`: 0 known vulnerabilities. |
| 1 | 2026-10-02 | `37f3aeb` (reviewed on `0a6361a`) | **Changes required** (2 High) | Checklist sections 0 and 1 clean: gitleaks (history and tree), fixture guard, `pip-audit`, `npm audit`, all greps. 353 tests pass. Ten probe tests reproduce F1-1 to F1-5. Details, fixes and suggested tests: `docs/security/stage1-findings.md`. Added the gitleaks `mt5-password-assignment` rule and an MT5 fixture guard. |

**Stage 0 observations** (not blocking Stage 0; each must be closed by the stage shown):

| ID | Sev | Finding | Fix by |
|---|---|---|---|
| F0-1 | Medium | `config.py` uses a bare boolean `FXBOT_LIVE_TRADING_CONFIRMED`; SR-10 requires `FXBOT_LIVE_CONFIRM_ACCOUNT_ID == FXBOT_OANDA_ACCOUNT_ID` | **Closed** in Stage 1 (config + factory; the boolean stays as an extra gate) |
| F0-2 | Medium | (Fixed in Stage 0: actions bumped and SHA-pinned.) `.github/workflows/ci.yml` used `actions/checkout@v4` and `astral-sh/setup-uv@v6` (and `actions/setup-node@v4` in the frontend job draft). These declare the Node 20 runtime that GitHub has removed from hosted runners. Bump them and pin SHAs (versions in `ci-security-job.md`) | Stage 0 (CI merge) |
| F0-3 | Low | `create_app` always serves `/api/docs` and `/api/openapi.json`; no `TrustedHostMiddleware` or security headers yet | Stage 5 (SR-31, SR-32, SR-36) |
| F0-4 | Low | `docker-compose.yml` publishes the backend on `127.0.0.1:8000` and has no hardening options; no Dockerfiles yet | Stage 7 (SR-24, SR-51) |
| F0-5 | Info | `database_url` is a plain `str`; fine for SQLite, but a Postgres URL with a password must be a `SecretStr` (SR-1). The logging redactor already masks URL userinfo | **Closed** in Stage 1 (a password in the URL is refused) |
| F0-6 | Low | ROADMAP stage 6 asks for typed confirmation to **engage** the kill switch; SR-40 requires engage ≤ 2 clicks, with typing only to release | Fixed in Stage 0 (ROADMAP aligned) |
| F0-7 | Low | `frontend/nginx.conf` sets `X-Forwarded-For $proxy_add_x_forwarded_for`, which appends a client-supplied header. Use `$remote_addr` while nginx is the edge (SR-28) | Stage 5 (when the login limiter lands) |
| F0-8 | Low | Base images are tag-pinned, not digest-pinned: `python:3.11-slim-bookworm`, `ghcr.io/astral-sh/uv:0.8`, `node:22-alpine`, `nginxinc/nginx-unprivileged:1.30-alpine`. Compose lacks `read_only`, `cap_drop` and `no-new-privileges` | Stage 7 (SR-51) |

**Stage 1 findings** (severity-ordered; the High findings block Stage 1b from reusing the order
path):

| ID | Sev | Location | Finding | Fix | Fix by |
|---|---|---|---|---|---|
| F1-1 | High | `brokers/oanda/adapter.py:257-268`, `:293-297` | Exceptions after an accepted order POST escape `submit_order`, and the fill is lost. Reproduced three ways: (i) attaching the stop and the fallback close both fail (`BrokerUnavailableError`); (ii) a non-`BrokerError` during the attach, so the **close never runs**; (iii) an unreadable 201 body. The position may be naked, and the caller thinks the order failed | No raise after the POST except auth and account mismatch. Parse inside `try`, falling back to `_resolve_unknown`. `_ensure_stop` catches `Exception` and reports an outcome. Stage 5 `OrderManager` treats any exception as `UNKNOWN` (SR-57) | Stage 1 follow-up, before 1b |
| F1-2 | High | `adapter.py:232-235`, `:245-247`/`:270-279`, `:286-289` | Stop verification is skipped for fills found by client-ID lookup (the existing order, or one resolved after a timeout): a timeout after a stop-less fill leaves a naked position (reproduced). An unreadable trade only logs a WARNING. A trade closed by the fail-safe is still reported as `FILLED` | Verify protection for every `FILLED` result. Add a protection outcome (`VERIFIED`/`ATTACHED`/`CLOSED`/`UNPROTECTED`/`UNVERIFIED`); the last two are CRITICAL (SR-57) | Stage 1 follow-up, before 1b |
| F1-3 | Medium | `config.py:49,60`; `backend/.env.example:17` | `ALLOW_LIVE_TRADING` is read from `.env`, so one file satisfies every live gate (reproduced). The brief requires it in the environment | Drop the key from the dotenv source (or read `os.environ` in `live_trading_problems`); warn if it is present in `.env`; remove it from `.env.example` (SR-10) | Stage 1 follow-up |
| F1-4 | Medium (Windows) / Low (POSIX) | `persistence/db.py:41`; `data/validation.py:249,270` | On POSIX the SQLite DB, WAL and SHM are created `0644` (reproduced). On Windows, `chmod` and `mkdir(mode=)` do nothing, and `C:\fxbot`-style folders inherit ACLs readable by local users. That exposes the journal now, and from Stage 1b the bridge secret (which can place orders) | POSIX: pre-create the DB as `0600`, or set `umask 077` in `cli.main`. Windows: ACL guidance plus an `icacls` check (SR-45, SR-68); optional start-up warning | POSIX: Stage 1 follow-up. Windows: Stage 1b guide, verified Stage 7 |
| F1-5 | Low | `adapter.py:95-116` | The SR-7 start-up account check (`connect()`) is opt-in: trading methods work on an unconnected broker, and nothing in `src/` calls `connect()`. The MT5 equivalent is the interlock itself (SR-60) | Trading methods raise until `connect()` succeeds; the engine connects at start and after every reconnect | Stage 1b (pattern), Stage 5 |
| F1-6 | Info | `brokers/oanda/client.py:119` via `adapter.py:171` | The expected 404 on every client-ID lookup is logged at WARNING, so real warnings drown in noise | Log expected 4xx at DEBUG | Any time |

Stage 1, already compliant:
- `get_secret_value` appears at 4 justified sites: the auth header, the account path, and two
  constant-time compares.
- Hosts are pinned in `hosts.py`, with no URL setting.
- TLS verification is on, redirects are off, and every client has an explicit timeout.
- Every account-scoped response, and every transaction-stream message, is checked against the
  configured account.
- Order POSTs are sent once; GETs are retried with backoff.
- `clientExtensions.id`, `tradeClientExtensions`, FOK, `priceBound` and `stopLossOnFill` are on
  every order.
- Domain models are finite, `extra="forbid"`, and reject a stop on the wrong side.
- `httpx`/`httpcore` log at WARNING.
- The sentinel tests cover reprs, a token held in a local variable, hostile error bodies and CLI
  refusals.
- The validation download is allowlisted, SHA-256 and size pinned, size-capped and protected
  against path traversal.
- Tests block real sockets.
- Windows CI runs with SHA-pinned actions.

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
