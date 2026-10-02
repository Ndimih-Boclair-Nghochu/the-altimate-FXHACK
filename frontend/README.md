# Altimate FX — dashboard

The web dashboard for Altimate FX: React + TypeScript (strict) on Vite, styled with Tailwind
CSS v4 design tokens, with TanStack Query for server state, Zustand for UI state, React Router
(data router) and lightweight-charts.

> Stage 0: scaffold, design system and app shell. Pages are placeholders; real data arrives in
> Stage 6. Nothing in the UI is real trading data yet.

## Requirements

- Node.js **22.22+** and npm **10+**
- The backend on `http://localhost:8000` for live health/mode (optional: the UI shows
  "Offline" without it)

## Run

```bash
npm ci
npm run dev        # http://localhost:5173
```

The dev server proxies `/api` and `/ws` (WebSocket) to `http://localhost:8000`. To point
somewhere else, set `BACKEND_URL` in the shell (it's read by `vite.config.ts` only and is never
bundled):

```bash
BACKEND_URL=http://localhost:9000 npm run dev
```

There are no `VITE_*` variables. Anything prefixed `VITE_` ends up in the public bundle, so
secrets must never go there. Broker credentials stay on the server.

## Scripts

| Script                 | What it does                                                        |
| ---------------------- | ------------------------------------------------------------------- |
| `npm run dev`          | Vite dev server with HMR and the API/WebSocket proxy                |
| `npm run build`        | Type-check (`tsc -b`), then build to `dist/`                        |
| `npm run preview`      | Serve `dist/` with the **production security headers** (CSP etc.)   |
| `npm run lint`         | ESLint (typescript-eslint strict, react-hooks, react-refresh, a11y) |
| `npm run typecheck`    | `tsc -b` over app, tests and Vite config                            |
| `npm test`             | Vitest + Testing Library (watch mode; add `-- --run` for CI)        |
| `npm run format`       | Prettier (with Tailwind class sorting)                              |
| `npm run format:check` | Prettier check without writing                                      |

Quality gates (must pass before committing a stage):

```bash
npm ci && npm run lint && npm run typecheck && npm test -- --run && npm run build
```

Tests never touch the network: `src/test/setup.ts` makes any un-mocked `fetch` fail, and
`mockHealth()` in `src/test/utils.tsx` stubs the backend.

## Layout

```
src/
  app/            route table (shared by browser + test routers), providers
  components/
    ui/           design-system primitives: Button, Card, Badge, Stat, Table, Switch, Tabs,
                  SegmentedControl, Tooltip, Dialog, Drawer, EmptyState, Skeleton
    layout/       app shell: TopBar, Sidebar, mode badge, connection status, theme toggle,
                  kill switch, page header, placeholder page
    charts/       TimeSeriesChart (lightweight-charts, follows the theme) + token bridge
  hooks/          useModal (focus trap, Escape, scroll lock, focus restore)
  lib/            api.ts (fetch wrapper, ApiError, health query), format.ts, storage.ts, cn.ts
  pages/          one file per route, plus 404 and route-error pages
  stores/         Zustand: theme (persisted), ui (sidebar, mobile drawer)
  index.css       design tokens + Tailwind theme
public/
  theme-init.js   applies the saved/system theme before first paint
```

## Design system

- **Tokens** live in `src/index.css` as CSS variables for light (`:root`) and dark (`.dark`),
  mapped to Tailwind utilities: `bg-background`, `bg-surface`, `bg-surface-raised`,
  `bg-surface-muted`, `border-border`, `text-fg`, `text-fg-muted`, `text-fg-subtle`,
  `text-accent` / `bg-accent-solid`, `text-profit` (= `success`), `text-loss` (= `danger`),
  `text-warning`. Tailwind's default palette is removed, so only tokens can be used.
- **Profit / loss** colours were checked for colour-vision-deficiency separation, and text
  tokens meet WCAG AA contrast on their surfaces. P&L is never colour-only: `Stat` pairs it
  with a `+`/`−` sign (true minus, U+2212), an arrow icon and screen-reader text.
- **Figures** use tabular numerals everywhere; the `numeric` utility adds the monospaced face
  (JetBrains Mono) for prices and table columns. Fonts are self-hosted via `@fontsource`.
- **Theme** defaults to the OS preference; the toggle pins light/dark and Settings can return
  to "system". Stored in `localStorage` (failures are ignored, never thrown).
- **Motion** is short and subtle, and disabled under `prefers-reduced-motion`.

## API client

`src/lib/api.ts` wraps `fetch` for same-origin calls under `/api` with
`credentials: 'include'`. Non-2xx replies and network failures reject with a typed `ApiError`
(`status`, `code`, `message`, `details`; FastAPI `detail` messages are extracted). Aborts are
re-thrown unchanged so React Query cancellation works. `useHealthQuery()` polls
`GET /api/health` every 15 s and validates the payload at runtime; an unknown trading mode is
an error, never displayed.

## Docker

```bash
docker build -t altimate-fx-frontend .
docker run --rm -p 8080:8080 --network <compose-network> altimate-fx-frontend
```

Multi-stage build: Node builds `dist/`, then `nginxinc/nginx-unprivileged` (non-root, port
**8080**) serves it with `nginx.conf`:

- SPA fallback to `index.html` (never cached); hashed `/assets/` cached for a year
- `/api/` and `/ws` reverse-proxied to `backend:8000` (WebSocket upgrade supported). The
  backend name is resolved per request through Docker DNS, so the UI starts even if the backend
  isn't up yet.
- Security headers: strict Content-Security-Policy (`'self'` only, no inline script or style),
  `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy`, COOP/CORP. HSTS is ready to enable once served over HTTPS.
- `GET /nginx-health` for the container health check

Keep the CSP in `nginx.conf` and `preview.headers` in `vite.config.ts` in sync, and check new
dependencies against it. For example, lightweight-charts' built-in attribution logo injects an
inline `<style>`, so it's disabled and `TimeSeriesChart` renders the TradingView attribution
link instead (required by its license).

## Tooling notes

- ESLint 10 (flat config). For accessibility linting it uses `eslint-plugin-jsx-a11y-x`, a
  maintained fork of `eslint-plugin-jsx-a11y` with the same rules that supports ESLint 10. The
  original plugin only declares support up to ESLint 9, which is end-of-life. The `strict`
  preset is enabled.
- TypeScript 6 (`strict`, `noUncheckedIndexedAccess`), held at 6.0.x because typescript-eslint
  doesn't support TypeScript 7 yet.
