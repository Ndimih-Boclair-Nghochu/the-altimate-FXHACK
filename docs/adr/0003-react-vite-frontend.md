# ADR 0003 — React + Vite single-page dashboard

- Status: Accepted
- Date: 2026-10-02
- Stage: 0 (implemented in stage 6)

## Context

One operator needs a clean dashboard with live updates (equity, positions, signals, risk),
financial charts, data-heavy tables, and safe controls (kill switch, pause/resume, settings).
Secrets must never reach the browser. The backend already exposes REST + WebSocket.

## Decision

- React + TypeScript (strict) + Vite, Tailwind CSS, React Router, lucide-react icons.
- **TanStack Query** owns server state (REST fetch, cache, invalidation). **Zustand** owns client
  state: session, WebSocket connection, live deltas, UI preferences.
- **lightweight-charts** for equity, drawdown and candle charts.
- A static build served by nginx; the SPA calls same-origin `/api` and `/ws`, so production
  needs no CORS and no API URL with credentials in the bundle. Only `VITE_*` variables are
  read at build time and none are secrets.
- Quality: ESLint, Prettier, Vitest + Testing Library.

## Consequences

- No server-side rendering; fine for an authenticated, single-user tool.
- TypeScript types must mirror backend Pydantic schemas. Hand-written types can drift; generating
  them from the OpenAPI schema is an open decision (see `docs/STATUS.md`).
- WebSocket deltas must be merged into the Query cache carefully to avoid double sources of truth;
  the rule is REST snapshot first, then apply deltas by `seq`, refetch on `resync`.
- The frontend owns no trading logic; every control is a request the backend validates.

## Alternatives considered

- **Next.js** — SSR and server components add complexity and a Node runtime for no benefit here.
- **Streamlit / Dash** — fast to prototype, but limited control over UX, auth and real-time
  behaviour, and couples UI to the Python process.
- **Grafana** — excellent for metrics, poor for operator controls and trade drill-down; could
  complement later for ops metrics.
- **Vue or Svelte** — viable; React chosen for the depth of its charting, table and testing
  ecosystem.
