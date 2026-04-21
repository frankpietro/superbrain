# Operator preferences

> Gaia's Tier-2 knowledge. These are the operator's **defaults** for
> a new project or a tool choice inside an existing one. They are
> not laws — if a project diverges intentionally, record the reason
> in its `docs/knowledge.md` under Architecture.

Seeded into every target at `.gaia/reference/preferences.md`. Agents
grep this file before proposing a tool the project hasn't yet
chosen. For an existing project being *adopted* into Gaia, this is
the reference the adoption protocol
([`docs/HOW_TO_ADOPT.md`](../docs/HOW_TO_ADOPT.md)) uses to classify
each detected tool as aligned / divergent / unknown.

Version pins (e.g. "Python 3.12+") mean *current major at seed
time*; older pins in a project are not automatically divergent.

---

## Guiding principles

- **The user doesn't run commands.** The agent drives everything —
  installs, builds, tests, migrations, deploys, CI checks. Every
  tool choice here is evaluated against this baseline. A tool that
  *requires* the human to run a shell command, click a dashboard
  button, or respond to a prompt is almost always the wrong choice
  for a new project; see *Agent-operable* in the rubric below.
- **Application-driven, not stack-driven.** The application shape
  picks the stack (see `archetypes/`), not the other way around.
- **Boring technology.** Prefer tools that have been stable for
  years and have excellent docs. Novelty pays its own way.
- **One source of truth per concern.** One lockfile. One state
  store. One styling system. Never two.
- **Least pollution for new projects.** Don't scaffold features the
  project doesn't yet need. Optional libraries (i18n, maps, forms,
  E2E) are added *when* the concern appears, not day one.
- **Prefer tools the agent already speaks.** When Cursor / Claude
  Code / the operator's MCP fleet already integrates a capability
  first-class (browser automation, GitHub, Google Workspace, Hex,
  a specific DB), **don't introduce an external tool that
  duplicates it**. External tooling is justified only when: (a) a
  CI or production context needs it headlessly, (b) the native
  integration is meaningfully weaker than a dedicated tool, or
  (c) reproducibility / auditability requires it. When in doubt,
  try the native integration first; record any limitation that
  forced an external tool in `docs/knowledge.md`.
- **Prefer the cheaper override to the costlier refactor.** When a
  project diverges from these defaults and the divergence is
  intentional, record it in `docs/knowledge.md` rather than forcing
  a migration.

---

## When Gaia has no opinion — the rubric

For a concern Gaia has no default for (Elixir backends, iOS apps,
niche DBs), apply these in order. Higher numbers break ties.

1. **Agent-operable.** The agent — not the user — runs this tool
   every time. Required: plain-text config, introspectable CLI,
   grep-able docs, non-interactive auth, and — when available — a
   first-class MCP / editor integration the agent already speaks.
   Anything that forces a dashboard click, a keychain prompt, a
   CAPTCHA, a per-command confirmation, or "reach out to support"
   loses immediately — those translate directly into the user
   being handed a task, which Gaia rejects. If a native
   integration covers the concern, prefer it to installing a
   second tool that does the same thing.
2. **Boring.** Version 1.x with multi-year adoption beats 0.3 with
   hype. A tool that survived one major ecosystem shift is almost
   always safer than one that hasn't.
3. **Single-file state.** One lockfile. One config format. Two
   tools competing for the same concern is a smell.
4. **Local-first.** The default dev loop works offline after
   install. Cloud is additive, not required.
5. **Reversible.** `git revert` fully undoes this month's adoption.
   Tools that write to a cloud DB, a shared registry, or an external
   queue need explicit rollback notes.
6. **Only then — cool / fast / modern.** Novelty is a tiebreaker.

For each unknown-to-Gaia choice, paste this into
`docs/knowledge.md`:

```
## <tool>
- Chosen for: <concern>
- Why: <top 1–2 rubric answers>
- Alternatives considered: <at least one>
```

If the same unknown-to-Gaia tool shows up in a **second** seeded
project, that's the signal to open an outbox entry (tier
`reference`) and codify a default here.

---

## Language and runtime

| Concern | Default | Alternatives (Stay unless otherwise noted) |
|---|---|---|
| Python | current stable (3.12+), managed by `uv` | poetry (Stay); pip+pip-tools (Tune: add a lockfile); conda (only for native-dep scenarios) |
| Python lint/format | `ruff` (covers black, isort, flake8, pyupgrade) | black+isort+flake8 (Tune: migrate, XS) |
| Python types | `mypy --strict` on new modules, gradual on legacy | `pyright` (faster, better inference — Stay if in place) |
| Python tests | `pytest` | `unittest` (stdlib, verbose — Stay if small); `hypothesis` (complement) |
| Node | current LTS, pinned via `.nvmrc` | — |
| Node package manager | `npm` (committed `package-lock.json`) | `pnpm` (Stay, especially in monorepos); `yarn` classic (Tune, S); `bun` (Stay if already bun-native) |
| TypeScript | always on, `strict: true` | prototype-only: record in knowledge.md with the trigger that flips the switch |
| Shell | `bash` with `set -euo pipefail` | `zsh`/`fish` as interactive shells, never script targets |

**Migration notes.** Package-manager swaps (poetry→uv, yarn→npm)
are Gaia's cheapest wins: XS–S, reversible, one PR. Type-checker
swaps (mypy↔pyright) are usually not worth doing as pure aesthetics;
stay with what's in place.

---

## Frontend

| Concern | Default | Alternatives |
|---|---|---|
| Framework | React + Vite (TypeScript, strict) | Next.js/Remix (only when SSR is a hard requirement); Solid/Svelte/Vue (Stay if in place) |
| Styling | Tailwind + `shadcn/ui` (copy-in primitives) | MUI/Chakra/Mantine (Stay, don't force-migrate); CSS Modules (fine for tiny apps) |
| State | `zustand` with `persist` when localStorage-backed | Redux Toolkit (Stay); Jotai/Recoil (fine); React Context alone (fine until fan-out) |
| Tests | Vitest (unit). Playwright (E2E) **only** once a user flow in CI is worth protecting | Dev-time interactive verification uses the agent's built-in browser integration — don't add Playwright just to click around. Jest→Vitest migration is XS-reversible; Cypress is workable but flakier |
| Lint | ESLint flat config | — |

**Optional — add when the concern actually appears, not day one:**

- **Forms** → `react-hook-form` + `zod`, schema shared with server.
- **i18n** → `react-i18next`, only once a second locale is on the
  roadmap. English-only projects should not carry i18n scaffolding.
- **Maps** → Leaflet + OpenStreetMap (no API key;
  `import 'leaflet/dist/leaflet.css'` explicitly).
- **Plotting** → `plotly.graph_objects`. **Never matplotlib in new
  code** (operator hard rule).

**Migration notes.** Framework swaps are almost never worth doing on
an existing app; CRA→Vite is the exception when CI is painful (M,
reversible). UI-library migrations (MUI→shadcn, etc.) are L and
high-risk; let them die naturally at the next redesign.

---

## Backend

| Concern | Default | Alternatives |
|---|---|---|
| Web framework (Python) | FastAPI (ASGI, Pydantic v2, OpenAPI) | Django (Stay — batteries-included is valid); Flask (Tune when surface grows); Starlette/Litestar (niche) |
| ORM | SQLAlchemy 2.0 | SQLModel (fine if committed project-wide); raw asyncpg/psycopg (fine for read-heavy services); Tortoise/Piccolo (niche) |
| Migrations | Alembic, one per PR, never edit a released migration | hand-managed SQL (Tune: introduce Alembic with an `initial` revision) |
| DB | PostgreSQL | MySQL/MariaDB (Stay); managed Neon/Supabase (pick at archetype level); SQLite prod only for single-writer, small data |
| Password hashing | Argon2id (`argon2-cffi`), cost tuned to ~100ms on the deploy host | bcrypt (Stay on live auth; migrate only alongside a planned auth change) |
| Session | HttpOnly + Secure + SameSite=Strict cookies; CSRF double-submit on state-changing endpoints | JWT (Stay on existing deployments; migrate when revocation bites) |

**Migration notes.** SQLAlchemy 1.x → 2.x is worth doing (S for
small apps, M for large); the 2.x API is the forward direction and
type support is meaningfully better. Framework swaps (FastAPI ↔
Django ↔ Flask) are almost always Stay on first adoption.

---

## Data & analytics

| Concern | Default | Alternatives |
|---|---|---|
| Dataframes | `polars` (preferred) or `duckdb` | pandas (Stay; migrate per-module only when a specific transform bottlenecks) |
| Notebooks | `.py` + `# %%` cell markers (Jupytext), or Hex for hosted dashboards | `.ipynb` (Tune: `jupytext --to py:percent` is XS per notebook; add `.ipynb` to `.gitignore`) |
| Plotting | `plotly.graph_objects` | matplotlib is the operator's hard no in new code (see above) |
| Scheduling | cron or GitHub Actions cron | Airflow/Prefect/Dagster earn their weight only at >10 recurring jobs or real cross-job dependencies |

**Hard operator rule.** When a project uses a Hex-exported YAML,
**never modify the YAML directly** — write code in separate `.py`
files and reference them. Hex round-trips the YAML; hand edits
regress silently on the next sync.

---

## DevOps & deploy

| Concern | Default | Alternatives |
|---|---|---|
| SPA hosting | Vercel (auto-deploy on merge; `vercel.json` only for SPA fallback) | Netlify, Cloudflare Pages (Stay — equivalent) |
| API hosting (managed) | Fly.io (EU region for personal-data apps) | Render, Railway (equivalent UX); ECS/Cloud Run/ACA (only with real compliance/scale/latency triggers) |
| API hosting (VPS) | Hetzner CX22 + Docker Compose + Caddy (auto-TLS) | Traefik (Stay); Nginx+certbot (Stay); Kubernetes only with team >3 and multi-service ambition |
| DB hosting | Neon (managed) or Docker Postgres on VPS | Supabase (only if using more than the DB); RDS (overkill for personal/small-team) |
| Container registry | GHCR (same account as the repo) | Docker Hub (rate-limited, separate account); cloud-specific ECR/GCR/ACR (Stay if already there) |
| Secrets | Fly secrets / env files on VPS; plaintext on personal dev box (see `AGENTS.md` → Operating principle) | — |

---

## Operator style

Small, cross-cutting preferences enforced in agent-written code:

- **Python docstrings** use reStructuredText with **only** `:param:`
  and `:return:` directives. No `:rtype:`, no Napoleon.
- **Comments** explain *non-obvious intent, trade-offs, constraints*.
  Don't narrate what the code already says.
- **Markdown** is concise. Short imperatives over long prose in
  instructions.
- **Matplotlib is banned in new code.** (Stated here and in Data.)
- **Hex project YAMLs are never edited by hand.** (Stated here and
  in Data.)

---

## Adopt-time decision hints (cross-cutting)

When adoption hits a divergence, consult these rules of thumb
*before* writing a proposal. More specific hints live in each
archetype's "Adopt-time decision hints" table.

- **Lockfile / package manager divergence** → propose Tune
  (XS–S, reversible). Gaia's cheapest win.
- **Missing lockfile** → propose adding one as a Tune (XS).
- **Password hashing / session scheme divergence** → Stay + record,
  unless the user is actively discussing auth or there's a CVE.
- **Framework divergence (backend or frontend)** → **always Stay**
  on first adoption. A Tune (strict TS, linter upgrade, test runner
  swap) is the ceiling in Phase 3.
- **Missing tests or CI** → propose scaffolding as a *follow-up*
  PR, never bundled with the adoption.
- **Unknown-to-Gaia tool in an aligned role** → `docs/knowledge.md`
  note; if this is the second project doing the same, queue an
  outbox entry.
