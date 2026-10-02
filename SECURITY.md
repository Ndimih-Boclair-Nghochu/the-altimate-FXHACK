# Security Policy

Altimate FX holds broker API credentials and can place real-money orders, so security reports
are taken seriously. The threat model and the requirements the code must meet are in
[`docs/SECURITY.md`](docs/SECURITY.md).

## Reporting a vulnerability

- **Report privately** through GitHub's private vulnerability reporting: the repository's
  **Security** tab, then **Report a vulnerability**. (Maintainers enable it under Settings → Code
  security → Private vulnerability reporting.)
- **Do not** open a public issue, pull request or discussion for a security problem.
- Include the affected commit or file, steps to reproduce, the impact you expect, and a fix if you
  have one.
- **Never include real credentials or account data** (OANDA tokens, account IDs, passwords,
  journal exports). Use the fake values listed at the top of [`.gitleaks.toml`](.gitleaks.toml).

This is a single-maintainer project. Fixes are best effort, with these targets:

| Severity | Examples | Acknowledge | Fix or mitigation |
|---|---|---|---|
| Critical | Orders placed without the risk checks; live trading without the interlock; credential disclosure; auth bypass | 3 days | 14 days |
| High | Dashboard XSS/CSRF, kill switch defeatable, secrets in logs | 7 days | 30 days |
| Medium / Low | Hardening gaps, missing headers, information leaks without credentials | 14 days | Next release |

## Scope

In scope: everything in this repository (backend, frontend, Docker and CI configuration, docs
that tell operators what to do).

Out of scope:
- OANDA's own platform and API (report those to OANDA).
- Attacks that need root on the operator's host.
- Trading losses from strategy behaviour. These are not security bugs unless a safety control
  (risk limits, kill switch, interlock) fails.
- Dependency vulnerabilities already public upstream. Tell us if Altimate FX is actually
  affected.

Supported version: the latest commit on `main`.

## Found a leaked credential?

If you see what looks like a real OANDA token or account ID in this repository, its history,
issues or CI logs, report it privately straight away and **do not use or test it**.

## Running Altimate FX and think your token leaked?

Revoke the token in the OANDA account portal first, from a device you trust. Then follow the
incident runbook in [`docs/SECURITY.md` §9](docs/SECURITY.md#9-incident-runbook).

## Good-faith research

We will not pursue action against good-faith research that follows this policy. It must not
access other people's accounts or data, and it must not place orders on accounts you do not own.
