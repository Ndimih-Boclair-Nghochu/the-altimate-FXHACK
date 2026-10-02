# Security review checklist

Used by the security reviewer at the end of stages 1, 1b, 5, 6 and 7 (`docs/SECURITY.md` §7). Every
item maps to a requirement (SR-n) in [`docs/SECURITY.md`](../SECURITY.md). Commands run from the
repository root with bash.

- **Expect** gives the passing result.
- **Inspect** means read the hits; hits are allowed but each one must be justified.
- File names in `backend/tests/...` refer to the acceptance tests in `docs/ROADMAP.md`.

```sh
export REPO=$(git rev-parse --show-toplevel)
export FAKE_TOKEN=0123456789abcdef0123456789abcdef-fedcba9876543210fedcba9876543210
export FAKE_ACCT=101-004-1234567-001
```

## How a review runs

1. Scope: `git log --oneline <last-reviewed-sha>..HEAD` and `git diff --stat <last-reviewed-sha>..HEAD`.
   Read every changed file under `brokers/`, `engine/`, `risk/`, `api/`, `persistence/`,
   `config.py` and `logging.py` in full. Skim the rest.
2. Run section 0, then the stage section.
3. Record findings in `docs/SECURITY.md` §11 as `F<stage>-<n>` with severity, SR, `file:line` and
   the stage that must fix it.
4. **Exit criteria:** no open Critical or High findings. Medium findings are fixed, or scheduled
   with a named stage. Low findings are tracked.

| Severity | Meaning |
|---|---|
| Critical | Money can move without the risk checks or the interlock; credential disclosure; auth bypass |
| High | Kill switch defeatable; secret in logs or responses; XSS/CSRF; unauthenticated route; blind order retry; missing fat-finger or rate limit |
| Medium | A control missing but currently covered by another; an SR without its test |
| Low | Hygiene, docs, defence in depth |

---

## 0. Every review

- [ ] **0-1 Quality gates green** (brief). Expect: all pass.
  ```sh
  (cd backend && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest)
  (cd frontend && npm ci && npm run lint && npm run typecheck && npm test -- --run && npm run build)
  ```
- [ ] **0-2 Secret scan, full history** (SR-2). Expect: `no leaks found`.
  ```sh
  gitleaks git --redact -v .
  ```
- [ ] **0-3 No env files tracked** (SR-2). Expect: no output.
  ```sh
  git ls-files | grep -E '(^|/)\.env' | grep -vE '\.example$'
  ```
- [ ] **0-4 Fixture guard** (SR-47). Expect: `fixture guard: ok`. Run the script from
  `docs/security/ci-security-job.md`:
  ```sh
  sed -n '/name: Fixture guard/,/fixture guard: ok/p' docs/security/ci-security-job.md \
    | sed '1,/run: |/d; s/^          //' | bash
  ```
- [ ] **0-5 Dependency audits** (SR-47). Expect: `No known vulnerabilities found` and
  `found 0 vulnerabilities`. Otherwise the advisory is fixed, or recorded in §10 with an expiry.
  ```sh
  (cd backend && uv export --frozen --all-groups --all-extras --no-emit-project --format requirements-txt -o /tmp/req-audit.txt \
    && uvx pip-audit==2.10.1 -r /tmp/req-audit.txt --require-hashes --disable-pip --strict)
  (cd frontend && npm audit --audit-level=high)
  ```
- [ ] **0-6 New dependencies justified** (SR-46, SR-50). Inspect: each new package has a reason in
  the PR, an exact name (no typosquat) and an active maintainer.
  ```sh
  git diff <last-reviewed-sha>..HEAD -- backend/pyproject.toml frontend/package.json
  ```
- [ ] **0-7 Bandit rules on; every suppression justified** (SR-49). Expect: `"S"` is in the
  `select` list; each `noqa: S` hit has a reason on the same line.
  ```sh
  grep -n 'select' backend/pyproject.toml
  grep -rnI 'noqa: *S' backend/src
  ```
- [ ] **0-8 Dangerous primitives** (SR-42, SR-43). Expect: no output, or only justified hits.
  ```sh
  grep -rnIE 'pickle\.|joblib\.load|read_pickle|allow_pickle=True|yaml\.load\(|\beval\(|\bexec\(|shell=True|os\.system|\.query\(|\.eval\(' backend/src
  ```
- [ ] **0-9 No prints, no locals in tracebacks** (SR-4, SR-23). Expect: no output, or
  `show_locals=False` only.
  ```sh
  grep -rnIE '\bprint\(' backend/src
  grep -rnIE 'dict_tracebacks|ExceptionDictTransformer|RichTracebackFormatter|show_locals' backend/src
  ```

---

## Stage 1 — Broker adapter, secrets, data

**Secrets (SR-1 – SR-5)**

- [ ] **1-1 Secret fields are `SecretStr`.** Expect: no hits for plain `str` secrets.
  ```sh
  grep -rnIE '^\s*\w*(token|secret|password|passwd|api_key|account_id)\w*\s*:\s*(str|str \| None|Optional\[str\])\b' backend/src
  ```
- [ ] **1-2 Secrets are unwrapped only at the point of use.** Expect: hits only in
  `brokers/oanda/client.py` (auth header, account path, compare), `config.py:secret_equals`
  (constant-time compare), from Stage 1b the bridge's HMAC and `initialize` code, and from
  Stage 5 `api/auth*`.
  ```sh
  grep -rnI 'get_secret_value' backend/src
  ```
- [ ] **1-3 Sentinel tests exist and pass** (`tests/test_secrets.py`, `tests/test_logging.py`).
  Inspect: they cover structlog events, stdlib records, an exception with the token in a local
  variable, an httpx error, and `repr()` of settings, client and adapter.
  ```sh
  (cd backend && uv run pytest -q tests/test_secrets.py tests/test_logging.py)
  grep -rlnI "$FAKE_TOKEN" backend/tests
  ```
- [ ] **1-4 Live run of the logging path leaks nothing.** Expect: `0`. Start in paper mode from an
  empty directory with the fake token set, then stop with Ctrl-C after a few seconds:
  ```sh
  W=$(mktemp -d) && cd "$W" && env -i PATH="$PATH" HOME="$HOME" FXBOT_LOG_LEVEL=DEBUG \
    FXBOT_OANDA_API_TOKEN=$FAKE_TOKEN FXBOT_OANDA_ACCOUNT_ID=$FAKE_ACCT \
    "$REPO/backend/.venv/bin/fxbot" > log.txt 2>&1; grep -cE "${FAKE_TOKEN:0:16}|$FAKE_ACCT" log.txt; cd "$REPO"
  ```
- [ ] **1-5 httpx/httpcore loggers quiet** (SR-4). Expect: both set to `WARNING` or higher.
  ```sh
  grep -rnIE 'getLogger\(["'"'"'](httpx|httpcore)' backend/src
  ```

**Transport, hosts, account (SR-6, SR-7, SR-11)**

- [ ] **1-6 Hosts pinned in one module.** Expect: one file.
  ```sh
  grep -rlIE 'fxtrade|fxpractice' backend/src
  grep -rnIE '\b(base_url|api_url|oanda_(api_)?url|broker_url|BASE_URL)\b' backend/src/fxbot/config.py   # expect: none
  ```
- [ ] **1-7 TLS on, no redirects, explicit timeouts.** Expect: no hits for the first command;
  every client in the second has `timeout=`.
  ```sh
  grep -rnIE 'verify\s*=\s*False|follow_redirects\s*=\s*True' backend/src
  grep -rnIE -A4 'httpx\.(Async)?Client\(' backend/src
  ```
- [ ] **1-8 Token only in a header.** Expect: no hits.
  ```sh
  grep -rnIE 'params=.*(token|auth)|\?(token|access_token)=' backend/src
  ```
- [ ] **1-9 Account lock.** Inspect: every v20 path uses the configured account ID; the bare
  `/v3/accounts` path is used only for the start-up check.
  ```sh
  grep -rnI '/v3/accounts' backend/src
  ```
- [ ] **1-10 Safe `repr`.** Inspect: the client and adapter define `__repr__` without credentials,
  or are dataclasses with `repr=False` on credential fields; covered by 1-3.

**Interlock (SR-9, SR-10)**

- [ ] **1-11 Factory and config refuse unsafe modes** (`tests/brokers/test_factory.py`,
  `tests/test_config.py`). Expect: pass; the tests cover `live` without the flag, without the
  confirmation, with a confirmation for a **different** account (F0-1), and `practice`/`paper`
  never resolving to `fxtrade`.
  ```sh
  (cd backend && uv run pytest -q tests/brokers/test_factory.py tests/test_config.py)
  ```
- [ ] **1-12 Manual refusal check.** Expect: non-zero exit, a message naming the missing items, and
  `0` occurrences of the token.
  ```sh
  W=$(mktemp -d) && cd "$W"
  env -i PATH="$PATH" HOME="$HOME" FXBOT_TRADING_MODE=live "$REPO/backend/.venv/bin/fxbot"; echo "exit=$?"
  env -i PATH="$PATH" HOME="$HOME" FXBOT_TRADING_MODE=live ALLOW_LIVE_TRADING=true \
    FXBOT_OANDA_API_TOKEN=$FAKE_TOKEN FXBOT_OANDA_ACCOUNT_ID=$FAKE_ACCT \
    FXBOT_LIVE_CONFIRM_ACCOUNT_ID=101-001-0000000-001 "$REPO/backend/.venv/bin/fxbot" 2>&1 | tee out.txt; \
    grep -c "${FAKE_TOKEN:0:16}" out.txt; cd "$REPO"
  ```

**Order primitives (SR-14, SR-17, SR-18)**

- [ ] **1-13 Idempotency key, broker-side stop, price bound present.** Expect: all three appear in
  the order-building code.
  ```sh
  grep -rnIE 'clientExtensions|stopLossOnFill|priceBound' backend/src/fxbot/brokers
  ```
- [ ] **1-14 No retry around order POSTs.** Inspect: retry/backoff wraps only GETs; the `submit`
  path maps timeout/5xx to `BrokerUnavailableError`/`UNKNOWN` and returns. Tests: 4xx is not
  retried; 5xx on submit is not retried.
  ```sh
  grep -rnIE 'retry|backoff|tenacity|attempt' backend/src/fxbot/brokers
  ```
- [ ] **1-15 Finite numbers only.** Expect: domain models with numeric fields set
  `allow_inf_nan=False` (or validate `Decimal.is_finite()`); a test feeds NaN and inf.
  ```sh
  grep -rnIE 'allow_inf_nan|is_finite' backend/src/fxbot/domain
  ```
- [ ] **1-16 Stream watchdog and backoff** (`tests/brokers/oanda/test_streaming.py`). Expect:
  pass, including the stale → `FeedStaleError` case and capped backoff.

**Tests offline, fixtures clean, data validated (SR-44, SR-49)**

- [ ] **1-17 No real network in tests.** Expect: a socket guard is active (conftest guard or
  `pytest-socket`), and real OANDA hosts appear only inside respx mocks.
  ```sh
  grep -rnIE 'disable.socket|socket\.socket|SocketBlocked' backend/tests backend/pyproject.toml
  grep -rnI 'oanda.com' backend/tests | grep -v respx
  ```
- [ ] **1-18 Fixtures use canonical fakes only.** Expect: 0-4 passes; in addition, recorded
  payloads contain no `Authorization` headers.
  ```sh
  grep -rniIE 'authorization' backend/tests/fixtures
  ```
- [ ] **1-19 Candle validation** (SR-44). Inspect: the downloader and store reject non-UTC,
  non-increasing, non-finite and OHLC-inconsistent rows; paths are built from enums.
  ```sh
  grep -rnIE 'open\(|Path\(' backend/src/fxbot/data
  ```
- [ ] **1-20 SQL via ORM only** (SR-42). Expect: no hits.
  ```sh
  grep -rnIE '\btext\(\s*f["'"'"']|\bexecute\(\s*f["'"'"']|\.format\(.*\b(SELECT|INSERT|UPDATE|DELETE)\b' backend/src
  ```

**Stage 1 follow-up** (re-review of F1-1 to F1-5; tests are in `docs/security/stage1-findings.md`)

- [ ] **1-21 Every fill is protected and reported** (SR-57, F1-1, F1-2). Expect:
  - the suggested tests pass;
  - every `FILLED` return path in `submit_order` goes through the protection check;
  - the fail-safe catches `Exception`;
  - no exception escapes `submit_order` after the POST except auth or account mismatch.
  ```sh
  grep -nE 'return (existing|result|await self\._resolve_unknown)|_ensure_stop|_protect|except ' backend/src/fxbot/brokers/oanda/adapter.py
  (cd backend && uv run pytest -q -k 'protect or attach or unverif or resolved_after_timeout')
  ```
- [ ] **1-22 `ALLOW_LIVE_TRADING` comes from the environment only** (SR-10, F1-3). Expect: the
  tests pass; the key is gone from `.env.example`; a `.env` containing it is ignored with a
  warning (the last command prints `False`).
  ```sh
  grep -n 'ALLOW_LIVE_TRADING' backend/.env.example backend/src/fxbot/config.py
  W=$(mktemp -d) && cd "$W" && printf 'ALLOW_LIVE_TRADING=true\n' > .env && \
    "$REPO/backend/.venv/bin/python" -c "from fxbot.config import Settings; print(Settings().allow_live_trading)"; cd "$REPO"
  ```
- [ ] **1-23 Private data files on POSIX** (SR-45, F1-4). Expect: `-rw-------` for `fxbot.db`,
  `-wal` and `-shm`.
  ```sh
  W=$(mktemp -d) && cd "$W" && "$REPO/backend/.venv/bin/python" -c "import asyncio; from fxbot.persistence.db import Database; d=Database('sqlite+aiosqlite:///$W/data/fxbot.db'); asyncio.run(d.create_all())" && ls -l data/; cd "$REPO"
  ```
- [ ] **1-24 No trading before the account check** (SR-7, F1-5). Expect: a test shows
  `submit_order`, `close_trade` and `close_all` raise before `connect()`.

---

## Stage 1b — MT5 adapter, bridge and Windows VPS

Code and tests run on Linux (CI, or locally with the fake `MetaTrader5` module). Host checks run in
PowerShell on the VPS, against the **demo** account. Paths assume `backend/src/fxbot/brokers/mt5/`
(ROADMAP stage 1b); adjust them to the real layout.

```sh
export MT5="backend/src/fxbot/brokers/mt5"
```

**Code and tests**

- [ ] **1b-1 Loopback bind, Host and Origin checks** (SR-58). Expect:
  - the default bind is `127.0.0.1`, and any other address is refused unless the explicit tunnel
    mode is configured;
  - `Host` is checked against `127.0.0.1:<port>` and `localhost:<port>`;
  - any `Origin` header gets 403;
  - no CORS middleware.
  ```sh
  grep -rnIE '0\.0\.0\.0|127\.0\.0\.1|bind|host' $MT5/bridge
  grep -rnIE 'Origin|Host|CORSMiddleware|TrustedHost' $MT5/bridge
  ```
- [ ] **1b-2 Signed requests with a replay window** (SR-59). Expect:
  - `hmac.compare_digest`, a ±30 s timestamp window, a nonce cache, and the body hash in the
    signed string;
  - the secret is a `SecretStr`;
  - tests for unauthenticated, wrong-signature, expired, replayed and tampered-body requests.
  ```sh
  grep -rnIE 'compare_digest|hmac\.new|nonce|timestamp|SecretStr' $MT5/bridge
  (cd backend && uv run pytest -q tests/brokers/mt5/test_bridge_security.py)
  ```
- [ ] **1b-3 No generic dispatch** (SR-61, SR-71). Expect: no hits, apart from the single
  configured-module import of `MetaTrader5`.
  ```sh
  grep -rnIE 'getattr\(\s*(mt5|self\._mt5)|rpyc|mt5linux|metaapi|\beval\(|\bexec\(|pickle|import_module\(' $MT5 backend/pyproject.toml
  ```
- [ ] **1b-4 Endpoint allowlist** (SR-61). Expect: the route table matches research 08 §B.4
  exactly, and an unknown path returns 404. Print the routes from the bridge app factory and
  compare.
  ```sh
  grep -rnIE '@(app|router)\.(get|post|put|patch|delete)\(|add_route|Route\(' $MT5/bridge
  ```
- [ ] **1b-5 `order/send` validation** (SR-61). Expect a test, each returning 422 before any MT5
  call, for:
  - a PENDING, MODIFY, REMOVE or CLOSE_BY action;
  - an opening DEAL without `sl`, or with `sl` on the wrong side;
  - SLTP with `sl=0`, or an SLTP that widens the stop;
  - `magic` outside our range;
  - a `comment` not matching `^afx:[A-Z2-7]{12}$`;
  - `volume` above `FXBOT_MT5_MAX_LOTS` or off the step;
  - an unmapped symbol;
  - a `position` ticket without our magic;
  - an unknown field;
  - a NaN.
  ```sh
  (cd backend && uv run pytest -q tests/brokers/mt5 -k 'reject or invalid or refuse or validation')
  ```
- [ ] **1b-6 Account binding** (SR-60, SR-10). Expect tests for:
  - `practice` on REAL, `live` on DEMO, and CONTEST in any mode;
  - a login or server mismatch;
  - a reconnect to a different login;
  - netting in `live`;
  - `trade_expert` false, and `tradeapi_disabled` true;
  - live without an environment-only `ALLOW_LIVE_TRADING`;
  - `FXBOT_LIVE_CONFIRM_ACCOUNT_ID` not equal to the MT5 login.

  The check runs before every `order_send`.
  ```sh
  grep -rnIE 'trade_mode|margin_mode|fifo_close|trade_expert|tradeapi_disabled|login|server' $MT5
  (cd backend && uv run pytest -q tests/brokers/test_factory.py tests/brokers/mt5 -k 'account or mode or login or interlock')
  ```
- [ ] **1b-7 Idempotency and ambiguous outcomes** (SR-62). Expect tests for:
  - a repeated key returns the stored result;
  - a key in flight gets 409;
  - the fake's "10012 after creating the position" case is found by `magic` + comment, with no
    second deal;
  - a comment rewritten by the broker is found by the `magic` + symbol + side + volume + time
    fallback;
  - retries only for 10004, 10020 and 10030.
- [ ] **1b-8 Protection after fill** (SR-57). Expect tests for:
  - the fake strips `sl` on DEAL, and SLTP attaches it;
  - SLTP fails twice, and the position is closed;
  - a close failure is reported as `UNPROTECTED`;
  - reconciliation finds our position with `sl == 0` and sets the SL or closes it.
- [ ] **1b-9 One worker thread, timeouts, rate** (SR-63). Expect: a single-thread executor;
  per-call timeouts; ≤ 1 trading request per second; `tests/brokers/mt5/test_threading.py` passes.
  ```sh
  grep -rnIE 'ThreadPoolExecutor|max_workers|run_in_executor|timeout' $MT5
  ```
- [ ] **1b-10 Secrets and logs** (SR-64, SR-65). Expect:
  - the MT5 password and the bridge secret are `SecretStr`, and are not settings of the backend
    process (bridge only);
  - the login is masked to its last 3 digits;
  - the sentinel tests are extended and pass;
  - no `initialize(...password=...)` unless the SR-65 fallback is configured.
  ```sh
  grep -rnIE 'password|bridge_secret|login' $MT5 backend/src/fxbot/config.py
  grep -rnIE 'initialize\(' $MT5
  (cd backend && uv run pytest -q tests/test_secrets.py)
  ```
- [ ] **1b-11 Package and fixtures** (SR-71, SR-47). Expect:
  - `MetaTrader5` is an optional extra with a `sys_platform == 'win32'` marker, locked with hashes,
    and present in the `pip-audit` export;
  - the fixture guard passes;
  - MT5 fixtures use login `12345678` (the last command prints nothing).
  ```sh
  grep -n -i 'metatrader' backend/pyproject.toml && grep -c -i 'name = "metatrader5"' backend/uv.lock
  grep -i metatrader /tmp/req-audit.txt       # after 0-5
  grep -rnE '"login"' backend/tests/fixtures/mt5 | grep -v 12345678
  ```
- [ ] **1b-12 Setup guide covers the operator rules** (SR-65 – SR-70). Expect `docs/MT5_SETUP.md`
  to cover:
  - investor vs master password;
  - the non-admin user, and RDP not public;
  - firewall block rules;
  - the `icacls` command;
  - no secrets in service definitions;
  - a tunnel with no `funnel`;
  - verifying the broker through the regulator, and the withdrawal test;
  - the red flags.
  ```sh
  grep -niE 'investor|non-admin|standard user|RDP|New-NetFirewallRule|icacls|AppEnvironmentExtra|funnel|regulator|withdraw|red flag' docs/MT5_SETUP.md
  ```

**Black-box against the bridge** (on the VPS against the demo account, or locally with the
bridge on the fake module). Use `curl.exe` for unsigned calls; it ships with Windows Server
2019 and later.

- [ ] **1b-13 Rejections.** Expect `401`, `401`, `400`/`421`, `403`, `404` and `413`, in that
  order.

```powershell
$B = "http://127.0.0.1:<bridge-port>"
curl.exe -s -o NUL -w "%{http_code}`n" "$B/account"                                   # no auth
curl.exe -s -o NUL -w "%{http_code}`n" -H "X-AFX-Signature: 00" "$B/account"           # bad signature
curl.exe -s -o NUL -w "%{http_code}`n" -H "Host: evil.example" "$B/health"             # wrong Host
curl.exe -s -o NUL -w "%{http_code}`n" -H "Origin: http://evil.example" "$B/health"    # browser origin
curl.exe -s -o NUL -w "%{http_code}`n" "$B/eval"                                       # unknown path
curl.exe -s -o NUL -w "%{http_code}`n" -X POST --data-binary "@C:\Windows\explorer.exe" "$B/order/send"   # oversized
```

- [ ] **1b-14 Replay.** Capture one signed `GET /account` made with the bridge's own client (debug
  hook or test harness). Expect: resending the identical headers and body after the first
  response returns 401, and so does resending after 31 s.
- [ ] **1b-15 Interlock drills on the demo.** Each refusal returns 409 and logs `CRITICAL`, and the
  backend pauses entries. Expect:
  - a different `FXBOT_MT5_LOGIN` → trading refused;
  - `FXBOT_TRADING_MODE=live` on the demo → refused at start;
  - Algo Trading switched off in the terminal → health degraded, entries paused;
  - the terminal closed and restarted → reconnect, SR-60 checks, reconciliation, then entries
    resume.

**Windows VPS host checks** (PowerShell; SR-67 – SR-69)

- [ ] **1b-16 Listeners are loopback only.** Expect `127.0.0.1` for both ports.
  ```powershell
  Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 8000,<bridge-port> | Select-Object LocalAddress,LocalPort,OwningProcess
  ```
- [ ] **1b-17 Firewall.** Expect:
  - every profile is `Enabled=True` with `DefaultInboundAction=Block`;
  - the block rules for 8000 and the bridge port exist;
  - there are no allow rules for `python.exe`;
  - Remote Desktop allow rules are restricted to the VPN or allowlisted addresses, or disabled.
  ```powershell
  Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction
  Get-NetFirewallRule -DisplayName 'fxbot*' | Select-Object DisplayName,Direction,Action,Enabled
  Get-NetFirewallApplicationFilter | Where-Object Program -like '*python*' | Get-NetFirewallRule | Where-Object Action -eq Allow
  Get-NetFirewallRule -DisplayGroup 'Remote Desktop' | Where-Object Enabled -eq True | Get-NetFirewallAddressFilter
  ```
- [ ] **1b-18 RDP is not public.** From a machine **outside** the VPN, expect a failure (or success
  only from the allowlisted IP). The `nc` command can be replaced with
  `Test-NetConnection <vps-public-ip> -Port 3389`.
  ```sh
  nc -zv -w3 <vps-public-ip> 3389
  ```
- [ ] **1b-19 Non-admin service user, and no secrets in service definitions.** Expect:
  - `StartName` is the dedicated user, who is not in Administrators;
  - `PathName`, the NSSM environment, scheduled-task arguments and machine variables contain no
    token, password or secret. `ALLOW_LIVE_TRADING` is allowed.
  ```powershell
  Get-CimInstance Win32_Service | Where-Object Name -like 'fxbot*' | Select-Object Name,StartName,PathName
  Get-LocalGroupMember Administrators
  reg query "HKLM\SYSTEM\CurrentControlSet\Services\fxbot-backend\Parameters" /v AppEnvironmentExtra
  Get-ScheduledTask | Where-Object TaskName -like 'fxbot*' | ForEach-Object { $_.Actions }
  [Environment]::GetEnvironmentVariables('Machine').Keys | Select-String 'FXBOT|MT5|OANDA'
  ```
- [ ] **1b-20 Folder ACLs** (SR-68, F1-4). Expect: only the service user, SYSTEM and
  Administrators; no `Everyone`, `BUILTIN\Users` or `Authenticated Users` anywhere below (the
  second command prints nothing).
  ```powershell
  icacls C:\fxbot
  icacls C:\fxbot /t /c | Select-String 'Everyone|BUILTIN\\Users|Authenticated Users'
  ```
- [ ] **1b-21 Updates, antivirus, time, no remote tools.** Expect: recent patches; Defender
  real-time protection on; time synced; no remote-desktop tools.
  ```powershell
  Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 3
  Get-MpComputerStatus | Select-Object AMServiceEnabled,RealTimeProtectionEnabled
  w32tm /query /status
  Get-Package | Where-Object Name -match 'AnyDesk|TeamViewer|RustDesk|UltraViewer'
  ```
- [ ] **1b-22 Terminal hygiene** (SR-66). Expect: no third-party `.ex5` or `.dll` outside the
  terminal's shipped examples (the command prints nothing); "Allow DLL imports" and "Allow
  WebRequest" off (checked by hand in Tools → Options → Expert Advisors).
  ```powershell
  Get-ChildItem C:\fxbot\mt5\MQL5\Experts,C:\fxbot\mt5\MQL5\Indicators,C:\fxbot\mt5\MQL5\Scripts,C:\fxbot\mt5\MQL5\Libraries -Recurse -File -Include *.ex5,*.dll | Where-Object FullName -notmatch '\\Examples\\|\\Free Robots\\'
  ```
- [ ] **1b-23 Dashboard tunnel** (SR-69). Expect: Tailscale serves only `127.0.0.1:8000` and
  funnel is off; or OpenSSH has `PasswordAuthentication no`. The bridge port is never forwarded.
  ```powershell
  tailscale serve status; tailscale funnel status
  Select-String -Path C:\ProgramData\ssh\sshd_config -Pattern 'PasswordAuthentication|PubkeyAuthentication'
  ```

---

## Stage 5 — Engine, API, auth

**Code checks**

- [ ] **5-1 One order path** (SR-13). Expect: `submit_order(` only in `engine/order_manager.py`
  and broker implementations; no bypass flags.
  ```sh
  grep -rnI 'submit_order(' backend/src
  grep -rnIE 'force|skip_risk|bypass|unsafe' backend/src/fxbot/engine backend/src/fxbot/risk
  ```
- [ ] **5-2 Fat-finger and rate limits implemented with hard caps** (SR-15, SR-16). Expect: tests
  exist and pass for units cap, notional cap, independent risk recompute, the JPY pip-size case,
  price bound, quote age, per-minute/day caps, duplicate suppression, and the pause on breach.
  ```sh
  (cd backend && uv run pytest -q -k 'fat_finger or notional or max_units or rate_limit or runaway or duplicate or quote_age')
  ```
- [ ] **5-3 Interlock in the engine, live starts paused** (SR-10, SR-12; `tests/engine/test_interlock.py`).
  Expect: pass; the confirmation compares the **account ID** (F0-1 closed).
  ```sh
  grep -rnI 'LIVE_CONFIRM_ACCOUNT_ID\|live_confirm_account_id' backend/src
  ```
- [ ] **5-4 Kill switch** (SR-19; `tests/engine/test_kill_switch_e2e.py`,
  `tests/risk/test_kill_switch.py`). Expect: pass; the check runs before every submit; state
  persists across restart; release requires actor + reason; flatten is exempt from the close rate
  limit; a CLI or out-of-band path is documented.
- [ ] **5-5 Mode and credentials are not writable** (SR-9). Inspect: only reads, and responses use
  the `configured: bool` form for secrets.
  ```sh
  grep -rnIE 'trading_mode|oanda_api_token|oanda_account_id|password_hash|session_secret' backend/src/fxbot/api
  ```
- [ ] **5-6 Auth on every route** (SR-25; `tests/api/test_auth_required.py`). Expect: pass; the
  dependency is applied at router level; the allowlist is only `/api/health` and `/api/auth/login`.
  ```sh
  grep -rnIE 'APIRouter\(|include_router\(' backend/src/fxbot/api
  ```
- [ ] **5-7 Password hashing and login throttling** (SR-26, SR-28). Expect: argon2 `PasswordHasher`
  with `verify`; no plaintext password setting; a limiter on the login route; a trusted-proxy
  setting that is not `*`.
  ```sh
  grep -rnIE 'argon2|PasswordHasher|bcrypt' backend/src
  grep -rnIE 'forwarded_allow_ips|proxy_headers|X-Forwarded-For' backend/src
  ```
- [ ] **5-8 Session and cookie** (SR-27). Expect: `httponly=True`, `samesite="strict"`, `secure`
  tied to HTTPS, no `domain=`. If JWT: `algorithms=["HS256"]` and `require` options are set.
  ```sh
  grep -rnI -A6 'set_cookie(' backend/src
  grep -rnI -A3 'jwt.decode' backend/src
  grep -rnIE 'access_token|"token"' backend/src/fxbot/api   # the session value is never in a body
  ```
- [ ] **5-9 CSRF, CORS and Host middleware** (SR-29 – SR-31). Expect: an Origin + JSON
  content-type check on unsafe methods; no wildcard or regex CORS; `TrustedHostMiddleware` present.
  ```sh
  grep -rnIE 'allow_origins\s*=\s*\[\s*["'"'"']\*|allow_origin_regex' backend/src   # expect: none
  grep -rnI 'TrustedHostMiddleware' backend/src                                       # expect: present
  grep -rnIE 'Origin|origin' backend/src/fxbot/api
  ```
- [ ] **5-10 Validation and the 422 handler** (SR-34). Expect: a shared request base model with
  `extra="forbid"` and `allow_inf_nan=False`; a custom `RequestValidationError` handler that omits
  `input` and `ctx`.
  ```sh
  grep -rnIE 'extra\s*=\s*["'"'"']forbid|allow_inf_nan' backend/src/fxbot/api
  grep -rnI 'RequestValidationError' backend/src/fxbot/api
  ```
- [ ] **5-11 Errors, docs, debug** (SR-36). Expect: docs and OpenAPI disabled outside paper (F0-3);
  no `debug=True`; a generic 500 handler with a request ID.
  ```sh
  grep -rnIE 'docs_url|openapi_url|redoc_url|debug\s*=' backend/src/fxbot/api
  ```
- [ ] **5-12 WebSocket** (SR-33; `tests/api/test_ws.py`). Expect: auth and Origin checked
  **before** `accept()`; no credentials read from `query_params`; inbound size limit; ops limited
  to subscribe, unsubscribe and ping; periodic expiry check.
  ```sh
  grep -rnIE 'accept\(|close\(|query_params|max_size|Origin' backend/src/fxbot/api/ws.py
  ```
- [ ] **5-13 Audit trail append-only** (SR-21, SR-22). Expect: no update or delete on
  `risk_events`; login, logout, settings, kill switch, pause/resume and promotion are all
  recorded.
  ```sh
  grep -rnIE '\.(update|delete)\(|DELETE FROM|UPDATE ' backend/src/fxbot/persistence
  grep -rnI 'risk_event\|RiskEvent' backend/src/fxbot/api | head -50
  ```
- [ ] **5-14 Learning cannot reach the broker** (SR-20). Expect: no output.
  ```sh
  grep -rnIE 'from fxbot\.(brokers|engine\.order_manager)' backend/src/fxbot/learning
  ```
- [ ] **5-15 Heavy work off the loop** (SR-37). Expect: backtests and training use the process
  pool; one job at a time; bounded request schema; `--workers 1`.
  ```sh
  grep -rnIE 'ProcessPoolExecutor|run_in_executor|workers' backend/src
  ```
- [ ] **5-16 API tests pass.**
  ```sh
  (cd backend && uv run pytest -q tests/api tests/engine)
  ```

**Black-box checks** (paper mode, fake credentials, from a scratch directory)

```sh
W=$(mktemp -d) && cd "$W"
HASH=$(uv run -q --no-project --with argon2-cffi python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('review-only-passphrase'))")
env -i PATH="$PATH" HOME="$HOME" FXBOT_DASHBOARD_PASSWORD_HASH="$HASH" \
  FXBOT_OANDA_API_TOKEN=$FAKE_TOKEN FXBOT_OANDA_ACCOUNT_ID=$FAKE_ACCT \
  "$REPO/backend/.venv/bin/fxbot" > server.log 2>&1 &
B=http://127.0.0.1:8000; sleep 3
J='Content-Type: application/json'
```

- [ ] **5-17 Unauthenticated sweep.** Expect: `401` on every route except `/api/health` (200) and
  `/api/auth/login` (4xx). This only covers routes in the schema; 5-6 covers the rest.
  ```sh
  curl -s $B/api/openapi.json | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(m.upper(), p) for p,ops in d["paths"].items() for m in ops]' > routes.txt
  while read -r m p; do u="$B$(sed -E 's/\{[^}]+\}/1/g' <<<"$p")"; printf '%s %s %s\n' "$(curl -s -o /dev/null -w '%{http_code}' -X "$m" "$u")" "$m" "$p"; done < routes.txt
  ```
- [ ] **5-18 Login sets a safe cookie, and no token appears in the body.** Expect: `Set-Cookie`
  has `HttpOnly`, `SameSite=strict` and `Path=/`; the body contains no session value.
  ```sh
  curl -si -c jar.txt -H "$J" -H "Origin: $B" -d '{"password":"review-only-passphrase"}' $B/api/auth/login
  ```
- [ ] **5-19 CSRF and Origin.** Expect: `403` for the evil origin, `415` or `403` for the wrong
  content type.
  ```sh
  curl -s -o /dev/null -w '%{http_code}\n' -b jar.txt -X POST -H "$J" -H 'Origin: https://evil.example' -d '{"action":"pause","reason":"csrf probe"}' $B/api/engine/entries
  curl -s -o /dev/null -w '%{http_code}\n' -b jar.txt -X POST -H 'Content-Type: text/plain' -H "Origin: $B" -d '{"action":"pause","reason":"csrf probe"}' $B/api/engine/entries
  ```
- [ ] **5-20 Host and CORS.** Expect: `400`; no `access-control-allow-origin` header.
  ```sh
  curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' $B/api/health
  curl -si -X OPTIONS -H 'Origin: https://evil.example' -H 'Access-Control-Request-Method: POST' $B/api/risk/kill-switch | grep -i '^access-control'
  ```
- [ ] **5-21 API security headers** (SR-32). Expect: CSP `default-src 'none'`, `nosniff`,
  `no-referrer`, `DENY`, `no-store`; no `server` header.
  ```sh
  curl -sI $B/api/health | grep -iE '^(content-security-policy|x-content-type-options|referrer-policy|x-frame-options|cache-control|server):'
  ```
- [ ] **5-22 Bounds, NaN and no input echo** (SR-34, SR-35). Expect: `422` for each request (never
  500 or 200), and `0` occurrences of `"input"`. Adjust the key name to the real settings schema.
  ```sh
  for body in '{"risk_per_trade_pct": NaN}' '{"risk_per_trade_pct": 1e999}' '{"risk_per_trade_pct": 50}' '{"unknown_key": 1}'; do
    curl -s -o /dev/null -w '%{http_code} ' -b jar.txt -X PATCH -H "$J" -H "Origin: $B" -d "$body" $B/api/settings; done; echo
  curl -s -H "$J" -H "Origin: $B" -d '{"password": 123}' $B/api/auth/login | grep -c '"input"'
  ```
- [ ] **5-23 No secrets in any GET response or in the log** (SR-5). Expect: `0` and `0`.
  ```sh
  grep '^GET' routes.txt | while read -r m p; do curl -s -b jar.txt "$B$(sed -E 's/\{[^}]+\}/1/g' <<<"$p")"; done \
    | grep -cE "${FAKE_TOKEN:0:16}|$FAKE_ACCT|argon2|\\\$2[aby]\\\$"
  grep -cE "${FAKE_TOKEN:0:16}|$FAKE_ACCT" server.log
  ```
- [ ] **5-24 WebSocket handshake.** Expect: `refused` for no cookie and for the evil origin;
  `OPEN` for cookie + same origin.

```sh
COOKIE=$(sed 's/^#HttpOnly_//' jar.txt | awk '!/^#/ && NF>=7 {printf "%s=%s; ", $6, $7}')
COOKIE="$COOKIE" "$REPO/backend/.venv/bin/python" - <<'EOF'
import asyncio, os
from websockets.asyncio.client import connect
URL = "ws://127.0.0.1:8000/ws"
async def probe(label, origin, cookie):
    headers = {"Cookie": cookie} if cookie else {}
    try:
        async with connect(URL, origin=origin, additional_headers=headers, open_timeout=5) as ws:
            await ws.send('{"op": "ping"}')
            print(label, "OPEN", (await asyncio.wait_for(ws.recv(), 5))[:60])
    except Exception as exc:
        print(label, "refused", type(exc).__name__)
async def main():
    c = os.environ["COOKIE"]
    await probe("no-cookie/same-origin ", "http://127.0.0.1:8000", None)
    await probe("cookie/evil-origin    ", "https://evil.example", c)
    await probe("cookie/same-origin    ", "http://127.0.0.1:8000", c)
asyncio.run(main())
EOF
```
- [ ] **5-25 Kill-switch drill (paper).** Expect: engaged; still engaged after restart; new
  entries rejected; audit rows for engage, login and restart.
  ```sh
  curl -s -b jar.txt -X POST -H "$J" -H "Origin: $B" -d '{"action":"engage","reason":"review drill"}' $B/api/risk/kill-switch
  curl -s -b jar.txt $B/api/status | python3 -m json.tool | grep -iE 'kill|pause'
  # restart the server (kill %1; start again as above), log in again, then repeat the status call
  python3 -c "import sqlite3; [print(r) for r in sqlite3.connect('data/fxbot.db').execute('select time,type,actor from risk_events order by id desc limit 10')]"
  ```
- [ ] **5-26 Login throttling (run last; it locks you out for 15 min).** Expect: `401` ×5, then `429`.
  ```sh
  for i in 1 2 3 4 5 6 7; do curl -s -o /dev/null -w '%{http_code} ' -H "$J" -H "Origin: $B" -d '{"password":"wrong-password-x"}' $B/api/auth/login; done; echo
  ```

---

## Stage 6 — Dashboard (XSS, token storage, CSP)

- [ ] **6-1 No dangerous DOM sinks** (SR-39). Expect: no output.
  ```sh
  grep -rnIE 'dangerouslySetInnerHTML|\.innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function\(|setTimeout\(\s*["'"'"'`]' frontend/src
  ```
- [ ] **6-2 No credentials in JS-readable storage** (SR-38). Expect: storage holds only UI prefs;
  `persist(` uses `partialize`; no `document.cookie`; no `Authorization` header built in JS.
  ```sh
  grep -rnIE 'localStorage|sessionStorage|indexedDB|document\.cookie' frontend/src
  grep -rnI -A5 'persist(' frontend/src
  grep -rnIE 'Authorization|Bearer' frontend/src
  ```
- [ ] **6-3 Same-origin requests and WS without tokens in URLs.** Expect: `credentials` is
  `same-origin` (or `include` toward the same origin only); the WS URL is built from
  `location`; no token query parameters.
  ```sh
  grep -rnIE 'credentials\s*:' frontend/src
  grep -rnIE 'new WebSocket\(|wss?://' frontend/src
  grep -rnIE '\?(token|auth|session)=' frontend/src
  ```
- [ ] **6-4 No secrets in `VITE_*`.** Expect: no secret-like `VITE_` names; source reads only
  `VITE_` variables.
  ```sh
  grep -rnIE 'VITE_[A-Z_]*(TOKEN|SECRET|PASSWORD|KEY|ACCOUNT)' frontend --include='*.ts' --include='*.tsx' --include='*.env*' --exclude-dir=node_modules
  grep -rnI 'import.meta.env' frontend/src
  ```
- [ ] **6-5 Links and URLs from data** (SR-39). Inspect: each `target="_blank"` has
  `rel="noopener noreferrer"`; each `href={…}` built from data goes through an `http(s)` allowlist.
  ```sh
  grep -rnI 'target="_blank"' frontend/src
  grep -rnIE 'href=\{' frontend/src
  ```
- [ ] **6-6 No third-party runtime origins.** Expect: only localhost hits, or none.
  ```sh
  grep -rnoIE 'https?://[A-Za-z0-9.-]+' frontend/src frontend/index.html | grep -vE 'localhost|127\.0\.0\.1|www\.w3\.org'
  ```
- [ ] **6-7 Build output is clean** (ROADMAP stage 6 build check). Expect: no output from each
  command.
  ```sh
  (cd frontend && npm run build)
  grep -rlIE 'OANDA_|FXBOT_|[0-9a-f]{32}-[0-9a-f]{32}' frontend/dist
  grep -nE '<script(\s[^>]*)?>' frontend/dist/index.html | grep -v 'src='     # no inline scripts
  ls frontend/dist/assets/*.map 2>/dev/null                                    # no source maps unless intended
  ```
- [ ] **6-8 CSP compatibility** (SR-32). Expect: no CSP violations in the browser console while
  clicking through every page. Serve the build with the production CSP, for example with
  `preview.headers` in `vite.config.ts` set to the SR-32 SPA policy, then:
  ```sh
  (cd frontend && npx vite preview --host 127.0.0.1 --port 4173)
  curl -sI http://127.0.0.1:4173/ | grep -i content-security-policy
  ```
- [ ] **6-9 Dev server stays local and proxies the API** (SR-41, SR-30). Expect: no `host: true`
  or `0.0.0.0`; `/api` and `/ws` proxied.
  ```sh
  grep -nE 'host\s*:|proxy' frontend/vite.config.*
  ```
- [ ] **6-10 Safe controls** (SR-40; `pages/Risk/Risk.test.tsx`, `pages/Settings/Settings.test.tsx`,
  `api/client.test.ts`). Expect: pass. Check by hand: the mode badge shows on every page;
  kill-switch **engage** takes at most two clicks with no typing; **release** needs typed
  confirmation; loosening dialogs show old → new; no secret inputs; a 401 redirects once.
  ```sh
  (cd frontend && npm test -- --run src/pages/Risk src/pages/Settings src/api)
  ```
- [ ] **6-11 Frontend audit.** Expect: `found 0 vulnerabilities` at high/critical.
  ```sh
  (cd frontend && npm audit --audit-level=high)
  ```

---

## Stage 7 — Deployment and final review

- [ ] **7-1 Compose hardening** (SR-24, SR-51, SR-52). Expect: frontend ports `127.0.0.1:` only;
  no backend ports; both services have `user`, `read_only=True`, `cap_drop=['ALL']`,
  `no-new-privileges`, and a `tmpfs` entry; live secrets come from `secrets`.

```sh
docker compose config --format json > /tmp/compose.json && python3 - /tmp/compose.json <<'EOF'
import json, sys
for name, s in json.load(open(sys.argv[1]))["services"].items():
    ports = [f'{p.get("host_ip", "0.0.0.0")}:{p.get("published")}->{p.get("target")}' for p in s.get("ports", [])]
    print(f'{name}: ports={ports} user={s.get("user")} read_only={s.get("read_only")} cap_drop={s.get("cap_drop")} '
          f'security_opt={s.get("security_opt")} tmpfs={s.get("tmpfs")} secrets={[x.get("source") for x in s.get("secrets", [])]}')
EOF
```
- [ ] **7-2 Images.** Expect: `FROM … @sha256:` everywhere; `.dockerignore` excludes `.env*`,
  `.git`, `data`, `.venv`, `node_modules` and test fixtures; no secrets in layers; non-root UID.
  ```sh
  grep -nE '^FROM' backend/Dockerfile frontend/Dockerfile
  cat backend/.dockerignore frontend/.dockerignore
  docker compose build && for svc in backend frontend; do docker compose run --rm --no-deps --entrypoint id "$svc"; done
  docker history --no-trunc "$(docker compose images -q backend | head -1)" | grep -iE 'token|secret|password|\.env'   # expect: none
  ```
- [ ] **7-3 Runtime.** Expect: a read-only FS error; nothing listening on `0.0.0.0` or `::`;
  backend port 8000 not on the host.
  ```sh
  docker compose up -d
  docker compose exec backend sh -c 'touch /app/probe' 2>&1 | grep -i 'read-only'
  ss -tlnp | grep -E ':(8000|8080)\b'
  ```
- [ ] **7-4 Secrets not visible in the container config (live setup)**. Expect: `0`.
  ```sh
  docker inspect "$(docker compose ps -q backend)" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -ciE 'TOKEN|PASSWORD|SECRET'
  ```
- [ ] **7-5 nginx headers on every location** (SR-32). Expect: the full SR-32 header set on `/`,
  an asset path and `/api/health`; no nginx version in `Server`. Inspect for the `add_header`
  inheritance gotcha.
  ```sh
  A=$(curl -s http://127.0.0.1:8080/ | grep -oE '/assets/[^"]+\.js' | head -1)
  for u in / "$A" /api/health /nope; do echo "== $u"; curl -sI "http://127.0.0.1:8080$u" | grep -iE '^(content-security-policy|x-content-type-options|referrer-policy|x-frame-options|permissions-policy|cross-origin-opener-policy|strict-transport-security|server):'; done
  ```
- [ ] **7-6 Through the proxy:** Host check, body limit, WS upgrade. Expect: `400`, `413`, and
  WS `OPEN` (rerun 5-24 against `ws://127.0.0.1:8080/ws` with origin `http://127.0.0.1:8080`).
  ```sh
  curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' http://127.0.0.1:8080/api/health
  head -c 2000000 /dev/zero | tr '\0' 'a' | curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:8080/api/auth/login
  ```
- [ ] **7-7 Data permissions** (SR-45). Expect: `700` on the directory, `600` on files, owned by
  the service user; `.env` is `600` on the host.
  ```sh
  docker compose exec backend sh -c 'stat -c "%a %U %n" /data /data/* /data/backups/* 2>/dev/null'
  stat -c '%a %n' .env backend/.env 2>/dev/null
  ```
- [ ] **7-8 Backup and restore** (SR-54). Expect: the backup file exists with `600`;
  `integrity_check` prints `ok`; after restore, reconciliation is clean.
  ```sh
  docker compose exec backend python -c "import sqlite3; s=sqlite3.connect('file:/data/fxbot.db?mode=ro', uri=True); d=sqlite3.connect('/data/backups/review.db'); s.backup(d); d.close()"
  docker compose exec backend python -c "import sqlite3; print(sqlite3.connect('/data/backups/review.db').execute('pragma integrity_check').fetchone()[0])"
  ```
- [ ] **7-9 TLS, if remote access is configured** (SR-53). Expect: an HTTP → HTTPS redirect; HSTS;
  the `Secure` cookie flag; the app still asks for login.
  ```sh
  curl -sI http://<host>/ | head -3; curl -sI https://<host>/ | grep -iE 'strict-transport|content-security'
  ```
- [ ] **7-10 Drills** (SR-19, SR-56; ROADMAP stage 7). Expect, each with audit rows in
  `risk_events`:
  - kill switch from the UI → flat within 5 s, no new orders until release;
  - out-of-band stop (`docker compose stop backend`) leaves positions with broker-side stops;
  - restart drill → no duplicate orders;
  - restore drill (7-8);
  - practice token rotation, following the runbook.
- [ ] **7-11 CI hardened** (SR-47, SR-48). Expect: the security job is present; every `uses:` is
  pinned to a 40-character SHA; no `pull_request_target`; least-privilege `permissions`.
  ```sh
  grep -nE 'uses: ' .github/workflows/*.yml | grep -vE '@[0-9a-f]{40}'          # expect: none
  grep -nE 'pull_request_target|permissions:|security:' .github/workflows/*.yml
  ```
- [ ] **7-12 Templates and docs.** Expect, in `.env.example`: `FXBOT_TRADING_MODE=paper`,
  `ALLOW_LIVE_TRADING=false`, and every secret empty or a canonical fake.
  `docs/RUNBOOK.md` contains the section 9 playbooks and the go-live checklist (SR-56).
  `docs/SECURITY.md` §10 and §11 are updated, with all findings closed or accepted.
  ```sh
  grep -nE 'TOKEN|ACCOUNT|PASSWORD|SECRET|MODE|ALLOW_LIVE' .env.example backend/.env.example 2>/dev/null
  grep -niE 'revoke|kill switch|backup|restore|go-live' docs/RUNBOOK.md
  ```
- [ ] **7-13 Full re-run.** Section 0 plus 5-17 – 5-26 against the deployed stack (through nginx).
