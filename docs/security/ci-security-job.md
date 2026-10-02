# CI security job

Implements SR-47 and SR-48 from [`docs/SECURITY.md`](../SECURITY.md). The orchestrator merges the
snippet below into `.github/workflows/ci.yml`. Everything in it was run locally against this
repository on 2026-10-02:
- gitleaks 8.30.1 with `.gitleaks.toml`: 0 findings, and every planted fake secret was caught;
- `pip-audit` 2.10.1 on the `uv export` output: 0 known vulnerabilities in 59 packages;
- `npm audit --audit-level=high`: 0 vulnerabilities;
- the fixture guard: fails on non-canonical values and prints no secrets.

## What the job does

| Step | Tool | Fails the build when |
|---|---|---|
| Secret scan | gitleaks 8.30.1 via `gitleaks/gitleaks-action` v3, using `.gitleaks.toml` (default rules + OANDA token, OANDA account ID, password hash) | Any finding in the pushed or PR commits; full history on `schedule` and `workflow_dispatch` |
| Fixture guard | `grep` | `backend/tests/fixtures/` contains a token-shaped, account-ID-shaped or `Bearer` value that is not one of the canonical fakes. This compensates for the gitleaks path allowlist on fixtures. Prints file:line only, never the value |
| Python deps | `uv export` (lockfile, all groups and extras, with hashes) → `pip-audit` 2.10.1 | Any known vulnerability (PyPI advisory DB) |
| JS deps | `npm audit --audit-level=high` (reads `package-lock.json`; no install needed) | Any high or critical advisory |

The job needs no repository secrets: `GITHUB_TOKEN` is provided automatically.

## Snippet

Add `schedule` and `workflow_dispatch` to the existing `on:` block, keep `permissions: contents:
read` at the top level, and add the `security` job next to `backend` and `frontend`. The job is
independent, so it runs in parallel.

```yaml
on:
  # ...keep the existing push and pull_request triggers unchanged, and add:
  schedule:
    - cron: "17 4 * * 1" # weekly: new advisories appear without code changes
  workflow_dispatch:

permissions:
  contents: read

jobs:
  # backend: ... (existing)
  # frontend: ... (existing)

  security:
    name: Security (secrets, dependency audit)
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
      pull-requests: read # gitleaks-action lists the PR's commits
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0 # gitleaks scans commit history
          persist-credentials: false

      - name: Secret scan (gitleaks)
        uses: gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e # v3.0.0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          # .gitleaks.toml needs >= 8.25 ([[allowlists]]); the action's built-in default is 8.24.3.
          GITLEAKS_VERSION: "8.30.1"
          GITLEAKS_CONFIG: .gitleaks.toml
          GITLEAKS_ENABLE_COMMENTS: "false" # avoids needing pull-requests: write
          # Only needed if the repository moves to a GitHub organization:
          # GITLEAKS_LICENSE: ${{ secrets.GITLEAKS_LICENSE }}

      - name: Fixture guard (only canonical fake credentials in test fixtures)
        shell: bash
        run: |
          set -euo pipefail
          dir=backend/tests/fixtures
          if [ ! -d "$dir" ]; then echo "no $dir yet; skipping"; exit 0; fi
          fake='0123456789abcdef0123456789abcdef-fedcba9876543210fedcba9876543210|0{32}-0{32}|[0-9]{3}-[0-9]{3}-(0{5,9}|1234567|12345678|123456789)-[0-9]{3}'
          hits=$(grep -rEnoI '\b[0-9a-fA-F]{32}-[0-9a-fA-F]{32}\b|\b[0-9]{3}-[0-9]{3}-[0-9]{5,9}-[0-9]{3}\b|[Bb]earer +[A-Za-z0-9._~+/-]{8,}' "$dir" \
            | grep -vE ":([Bb]earer +)?(${fake})\$" || true)
          if [ -n "$hits" ]; then
            echo "::error::Non-canonical token/account-shaped values in $dir (values hidden). Replace them with the fakes listed in .gitleaks.toml."
            printf '%s\n' "$hits" | cut -d: -f1,2 | sort -u
            exit 1
          fi
          echo "fixture guard: ok"

      - uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0
        with:
          enable-cache: false

      - name: Python dependency audit (pip-audit on uv.lock)
        working-directory: backend
        run: |
          uv export --frozen --all-groups --all-extras --no-emit-project \
            --format requirements-txt -o "$RUNNER_TEMP/requirements-audit.txt"
          uvx pip-audit==2.10.1 -r "$RUNNER_TEMP/requirements-audit.txt" \
            --require-hashes --disable-pip --strict --progress-spinner off

      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
        with:
          node-version: 22
          package-manager-cache: false

      - name: npm dependency audit
        working-directory: frontend
        run: npm audit --audit-level=high
```

Notes:

- **Why `--disable-pip --require-hashes`:** the export pins every package with hashes, so
  pip-audit checks exactly the locked set without creating a venv or resolving anything.
  `--all-groups` includes dev tools: they run on the developer's machine, where `.env` lives.
- **Why `npm audit` covers dev dependencies too:** the Vite dev server and build tooling run
  locally with access to the repo. Vite dev-server CVEs are relevant (SR-41).
- **Exceptions:** if an advisory has no fix, record it in `docs/SECURITY.md` §10 with an expiry
  date, then ignore it narrowly: `pip-audit --ignore-vuln <ID>`, or an npm `overrides` entry. Never
  lower `--audit-level` or remove the step.
- **gitleaks license:** not needed while the repository belongs to a personal account (per the
  gitleaks-action README). If it moves to an organization, add `GITLEAKS_LICENSE` or use the
  binary variant below.
- **Pins:** SHAs were resolved from the upstream tags on 2026-10-02. Update them by re-resolving
  the tag (`git ls-remote --tags https://github.com/<owner>/<repo>`), never by switching to a
  mutable `@vN` tag.

### Variant without the third-party action

Use this if the gitleaks-action license or its behaviour becomes a problem. It scans the full
history on every run, which is fine for a repository this size. Fill in `GITLEAKS_SHA256` from
the release's `gitleaks_8.30.1_checksums.txt` after checking it once by hand.

```yaml
      - name: Secret scan (gitleaks binary)
        env:
          GITLEAKS_VERSION: "8.30.1"
          GITLEAKS_SHA256: "<sha256 of gitleaks_8.30.1_linux_x64.tar.gz>"
        run: |
          curl -sSfL -o "$RUNNER_TEMP/gitleaks.tgz" \
            "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
          echo "${GITLEAKS_SHA256}  $RUNNER_TEMP/gitleaks.tgz" | sha256sum -c -
          tar -xzf "$RUNNER_TEMP/gitleaks.tgz" -C "$RUNNER_TEMP" gitleaks
          "$RUNNER_TEMP/gitleaks" git --redact --no-banner -v .
```

## Also fix the existing jobs (review log F0-2)

The workflow currently uses `actions/checkout@v4` and `astral-sh/setup-uv@v6`. The frontend job
draft also used `actions/setup-node@v4`. All three declare `using: node20`, and the gitleaks-action
README dates GitHub removing Node 20 from hosted runners to 2026-09-16. Wherever they appear,
replace them with the same pinned versions (their inputs `enable-cache`, `cache-dependency-glob`,
`cache` and `cache-dependency-path` still exist):

```yaml
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0
      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
```

## Running the same checks locally

From the repository root:

```sh
# Secrets (install: https://github.com/gitleaks/gitleaks, or `go install github.com/zricethezav/gitleaks/v8@v8.30.1`)
gitleaks git --redact -v .            # committed history, as CI does
gitleaks dir --redact -v .            # working tree; flags your local .env, which is expected

# Python dependencies
(cd backend && uv export --frozen --all-groups --all-extras --no-emit-project \
   --format requirements-txt -o /tmp/req-audit.txt \
 && uvx pip-audit==2.10.1 -r /tmp/req-audit.txt --require-hashes --disable-pip --strict)

# JS dependencies
(cd frontend && npm audit --audit-level=high)
```

Optional pre-commit hook. It catches secrets before they ever reach a commit:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - id: gitleaks
```
