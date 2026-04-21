# Personal web SPA

## When to use

You are building a **client-only web app**: a game, a portfolio, a
personal tool, a prototype. All state fits in the browser's
`localStorage` (or the user can wipe it without losing anything
precious). No auth, no other users' data, no server-side secrets.
Zero to a few dozen daily users you personally know.

Not the right archetype if:

- Multiple users must see shared server-side state.
- You need authentication with password reset or email verification.
- You need offline sync to a server on reconnect.
- You have GDPR/privacy obligations that require server-side
  retention controls.

→ For those, see [`multi-tenant-saas.md`](./multi-tenant-saas.md).

## Reference stack (core — always)

- **Build**: Vite + React + TypeScript (`strict: true`)
- **Styling**: Tailwind + `shadcn/ui` (copy-in primitives, not a
  dependency)
- **State**: `zustand` with `persist` middleware (localStorage), one
  slice per concern
- **Tests**: Vitest (unit). No E2E scaffold day one — the agent's
  built-in browser integration handles dev-time interactive checks.
- **Lint**: ESLint flat config
- **Package manager**: `npm`
- **Deploy**: Vercel, auto-deploy on merge to default branch
- **Backend / auth**: none

## Reference stack (optional — add when the concern appears)

Do not scaffold these day one. Add each only when the feature
actually lands in the product.

| Concern | Choice | Notes |
|---|---|---|
| Forms | `react-hook-form` + `zod` | One shared schema for validation |
| i18n | `react-i18next` | Only once a second locale is on the roadmap |
| Maps | Leaflet + OpenStreetMap | Import `leaflet/dist/leaflet.css` explicitly |
| Plotting | `plotly.graph_objects` | Never matplotlib |
| E2E tests | Playwright | Only once a user flow in CI is worth protecting; for dev-time verification use the agent's built-in browser |

## Why these choices

- **Vite, not Next/Remix.** Client-only; SSR is pure overhead.
- **Zustand + `persist`.** Rehydration is asynchronous — gate routes
  on `_hasHydrated` with a splash, or you'll render against stale
  state.
- **shadcn/ui.** Components are pasted into `src/components/ui/`;
  you own them. No framework-bump breaking-change risk.
- **Vercel.** Free tier fits this shape. Preview deploys per PR.
- **`localStorage` as DB.** Versioned persist keys with
  `migrate: (state, v) => ...`. Never silently drop data on schema
  change.

Reference project:
[`frankpietro/side-quest`](https://github.com/frankpietro/side-quest).

## Known gotchas

Core stack:

- **Zustand `persist` rehydration is asynchronous.** Use
  `_hasHydrated` gating; don't render persisted routes before it's
  true.
- **Theme flash.** With dark mode, put a tiny inline script in
  `index.html` that sets the theme class before React mounts, or
  reloads show the wrong theme for ~50ms.

Only if you pulled in an optional concern:

- **Leaflet CSS is not imported by default.** Add
  `import 'leaflet/dist/leaflet.css'` in `main.tsx` or the route
  that uses it.
- **`navigator.geolocation.watchPosition` needs explicit cleanup**
  on unmount, or it keeps firing after the user leaves the page.

## Folder layout

```
src/
  components/
    ui/                shadcn primitives (copied)
    <feature>/         feature-scoped components
  pages/               route components, one per tab
  lib/
    store/             zustand slices
    hooks/             React hooks
  assets/              SVGs, static images
```

Add `src/i18n/`, `src/lib/game/` (pure business logic),
`src/lib/api/` etc. only when you have code to put in them.

## Alternatives considered

- **Next.js instead of Vite SPA** — only if SEO or crawlable public
  pages are a hard requirement. The "better default" stories online
  mostly assume you have a backend; for a client-only app, Next's
  opinions are overhead. Migration: Vite→Next M; Next→Vite S (for a
  genuinely client-only app).
- **SolidJS / Svelte / Qwik** — nice, smaller ecosystems. Stay if
  an existing project uses one; don't rewrite.
- **Redux Toolkit / Jotai / Recoil** instead of zustand — all
  workable; zustand wins on ceremony for the small-state scope.
  Stay if in place.
- **MUI / Chakra / Mantine** — impose a design system that's harder
  to undo. Stay on adoption; let them die naturally at next
  redesign.
- **IndexedDB (Dexie) / RxDB / PouchDB** instead of localStorage —
  upgrade when state grows beyond a few MB, includes binary, or
  requires queryable indexes. Don't upgrade preemptively; document
  the migration trigger in `docs/knowledge.md`.
- **Netlify / Cloudflare Pages** instead of Vercel — equivalent.
  Stay if in place.

## Adopt-time decision hints

| Detected | Classification | Recommendation |
|---|---|---|
| React + Vite + Tailwind + shadcn | aligned | Stay. No action beyond the seed. |
| React + Create-React-App | divergent | Tune (M, reversible) if CI is painful; otherwise defer. CRA is unmaintained. |
| Next.js for a client-only app (no SSR) | divergent | Stay in Phase 4. Propose a follow-up Refactor (S–M) only if the team is willing. |
| Yarn / pnpm / bun | divergent | Tune (XS–S) — swap to npm, or Stay with a `knowledge.md` override. |
| MUI / Chakra / Mantine | divergent | Stay. UI-system migration is L + high-risk. |
| Redux / other state lib | divergent | Stay. Don't rewrite state. |
| No tests at all | missing | Scaffold Vitest (XS) as a **separate** follow-up PR. Add Playwright (S) only once a user flow in CI is worth protecting; until then rely on the agent's built-in browser for interactive checks. |
| Two lockfiles committed (e.g. Lovable/Bolt output) | divergent | Tune (XS): delete the unused one. See `patterns/anti-patterns.md` → lockfile drift. |

## Seeding

```bash
gaia init --archetype personal-web-spa --name <project-name>
# or on an existing repo being adopted:
gaia adopt --seed --archetype personal-web-spa
```

After seed, bootstrap the Vite+React+TS+Tailwind+shadcn app in
place (or import a Lovable/Bolt/v0 scaffold) and record the
concrete stack in `docs/knowledge.md` → Architecture.
