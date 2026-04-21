# Superbrain Frontend (phase 7)

React SPA for the three owners. Reads from the Phase-6 FastAPI backend.

## Stack

- Vite 5 + React 18 + TypeScript (strict, `noUncheckedIndexedAccess`)
- Tailwind CSS 3 + shadcn/ui-style primitives (components hand-copied, no CLI)
- TanStack Router (code-based routes) + TanStack Query
- Zustand with `persist` for preferences
- `zod` at every API boundary
- Charts via `react-plotly.js` on the `plotly.js-cartesian-dist-min` bundle
- Vitest + React Testing Library + `@testing-library/jest-dom`

## Commands

```bash
npm install
npm run dev        # Vite dev server on :5273 (strict, fails loudly if busy)
npm run build      # typecheck + production bundle in dist/
npm run preview    # preview built bundle
npm run test       # Vitest (watch mode)
npm run test -- --run
npm run lint       # ESLint, zero warnings
npm run typecheck  # tsc --noEmit
npm run format     # Prettier write
```

## Environment

Copy `.env.example` to `.env.local`:

```
VITE_API_BASE_URL=http://localhost:8100
```

Preferences (theme, timezone, selected leagues) live in
`superbrain.prefs`. The SPA is unauthenticated — it talks to the API
without a token.

## Route map

| Path | Purpose |
|------|---------|
| `/` | Dashboard: fixture / value-bet / scraper-health cards + today's matches. |
| `/matches` | Filterable fixture table (league, date range, search). |
| `/matches/$id` | Fixture detail + odds pivot (markets × bookmakers). |
| `/scrapers` | Per-bookmaker tiles, rows-written history (plotly), unmapped markets. |
| `/bets/value` | Value-bets table (empty state until phase 4b wires the engine). |
| `/backtest` | Backtest form; calls the 501 stub and shows a friendly toast. |
| `/settings` | Theme, timezone, API base URL. |

## Layout

```
src/
  components/       # shared UI (including ui/ shadcn primitives)
  lib/              # api client, zod types, format helpers, utils
  routes/           # one file per screen, wired in router.tsx
  stores/           # zustand stores (preferences)
  test/             # Vitest setup + tests
  index.css         # tailwind base + design tokens (CSS variables)
  main.tsx          # QueryClient + Router bootstrap
  router.tsx        # code-based route tree
```

## Design tokens

HSL CSS variables live in `src/index.css` (`:root` and `.dark`). Tailwind is
configured to read them via `tailwind.config.js`; shadcn-style components
reference semantic tokens (`bg-card`, `text-muted-foreground`, …) rather than
hard-coded colors. The accent is forest green (HSL `155 66% 26%`).

## Types

`src/lib/types.ts` hand-writes zod schemas for the Phase-1/Phase-3 pydantic
models (`Match`, `OddsSnapshot`, `ScrapeRun`, …). Once the Phase-6 backend
exposes a stable `/openapi.json`, regenerate with:

```bash
npx openapi-typescript http://localhost:8100/openapi.json -o src/lib/api-types.ts
```

and migrate `types.ts` to reference the generated types.

## Testing notes

- `src/test/setup.ts` wires `@testing-library/jest-dom` matchers and resets
  `localStorage` between tests.
- `api.test.ts` stubs the global `fetch` via `vi.stubGlobal` and asserts
  that requests go out without an Authorization header.
- There are **no e2e** tests yet; that's phase 8.
