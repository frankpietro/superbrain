# Multi-tenant SaaS

## When to use

You are building a **real product with authenticated users and
per-tenant data**: a business tool, a dashboard, a workflow app —
anything where losing data is bad and other people log in. You
need password auth, server-side persistence, migrations, backups,
and probably GDPR-compliant export/deletion.

If it's a solo-operator personal app with no other users, pick
[`personal-web-spa.md`](./personal-web-spa.md) instead.

## Reference stack

### Backend

- Python 3.12+, `uv`, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL,
  `ruff`, `pytest` — defaults from
  [`preferences.md`](../preferences.md).
- **Tests**: `pytest` against an **ephemeral Postgres** (prefer
  `docker compose up -d db` or `testcontainers-python`). SQLite is
  acceptable only for pure-unit tests that do not touch the DB.
  Production-parity is worth the few seconds of container startup
  per CI job.
- **Password hashing**: Argon2id (`argon2-cffi`); cost tuned to
  ~100ms on the deploy host; parameters recorded in
  `docs/knowledge.md`.
- **Sessions**: HttpOnly + Secure + SameSite=Strict cookies; CSRF
  double-submit on state-changing endpoints.
- **Rate limiting**: per-IP on `/login` at minimum (`slowapi`).
- **Audit log**: a `login_events` table — IP, user agent, outcome of
  every auth attempt.

### Frontend

Same as [`personal-web-spa`](./personal-web-spa.md) for the UI
layer: Vite + React + TS + Tailwind + `shadcn/ui` + zustand. The
API client is plain `fetch` with a thin wrapper that handles CSRF +
JSON.

Unlike the personal-SPA archetype, a multi-tenant SaaS **ships
Playwright E2E in CI from day one** — the auth + signup + one
paid-flow smoke are worth protecting. Dev-time interactive
verification still goes through the agent's built-in browser; the
Playwright suite is the CI gate.

### Infra

- Container images built by GitHub Actions on push to default
  branch, published to GHCR.
- **Two deploy paths** (pick one at project start, document in
  `docs/knowledge.md`):
  - **Managed**: Fly.io (API, EU region) + Neon (Postgres) + Vercel
    (frontend), with a rewrite from `/api/*` to Fly.
  - **Single VPS**: Hetzner CX22 + Docker Compose + Caddy (auto-TLS)
    + cron-scheduled `pg_dump` backup to `/var/backups/<app>`.

## Archetype-specific reasoning

Most tool choices inherit from
[`preferences.md`](../preferences.md). Archetype-specific ones:

- **Ephemeral Postgres for tests, not SQLite.** Prod-parity:
  JSONB, case sensitivity, transactional isolation, `ON CONFLICT`,
  advisory locks, triggers — none of these match between SQLite and
  Postgres. The few seconds of container startup in CI buys real
  coverage.
- **Argon2id, never bcrypt, for new projects.** Existing projects
  on bcrypt: Stay + document, migrate alongside the next planned
  auth change.
- **Alembic migrations are never edited after release.** The
  trailing guarantee is what makes schema changes safe. Pair with
  [`patterns/zero-downtime-migrations.md`](../patterns/zero-downtime-migrations.md)
  once there are live users.
- **GHCR, not Docker Hub.** Same account as the repo; no token
  dance; no rate limits.
- **Caddy on the VPS path.** Auto-TLS with zero config; Compose is
  the simplest orchestration that could work.

Reference project:
[`frankpietro/forno-mastrella`](https://github.com/frankpietro/forno-mastrella).

## Security baseline

- HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy
  headers set explicitly.
- `COOKIE_SECURE=true` in production; HTTPS enforced.
- Per-user data export (`GET /api/account/export`) and deletion
  (`DELETE /api/account`) endpoints for GDPR.
- EU region for personal-data apps with European users.

## Known gotchas

- **`alembic revision --autogenerate` misses server-side default
  changes.** Review every diff by hand before committing.
- **Argon2 default cost is too low on modern hardware.** Tune; see
  above.
- **Vercel rewrites vs. serving frontend from Fly** — pick one per
  project and document it. Mixing is a debugging nightmare.
- **`uv sync --frozen` in CI** is non-negotiable, or lockfile drifts.

## Folder layout

```
backend/
  app/
    api/               routers per concern
    models/            SQLAlchemy models
    schemas/           Pydantic models
    services/          business logic, pure-ish
    db/                session, migrations config
  alembic/
  tests/
  pyproject.toml
  uv.lock
frontend/
  src/
    components/ui/     shadcn primitives
    pages/
    lib/api/           fetch wrapper, CSRF
    lib/store/
  package.json
  package-lock.json
infra/
  Dockerfile.api
  Dockerfile.web
  docker-compose.yml   # includes a 'db' service used in tests
  Caddyfile
  backup.sh
  fly.api.toml
.github/workflows/
```

## Alternatives considered

- **Django** — batteries-included: ORM, admin, templates, auth.
  Strong fit when you *want* an admin UI for free. Don't rewrite
  Django→FastAPI unless you're already doing a major overhaul.
- **Flask** — simpler, sync, no types. Fine for very small APIs.
  Migrate (M, reversible) past ~20 endpoints or when Pydantic
  validation becomes valuable — otherwise Stay.
- **Node backend (NestJS / Express / Hono with Prisma or Drizzle)**
  — legitimate override if the team's whole stack is JS. Record in
  `docs/knowledge.md` and queue an outbox entry proposing a
  `node-saas` archetype.
- **JWT sessions** instead of cookie sessions — tempting for
  microservices; painful for revocation and rotation. Stay on
  existing deployments; migrate (M) when revocation bites.
- **SQLite in production** for single-writer, small data,
  read-heavy workloads — acceptable; record migration trigger (user
  count, DB size) in `docs/knowledge.md`.
- **Render / Railway / AWS / GCP** instead of Fly — all work.
  Migrate only with a concrete cost / latency / compliance trigger.
- **Hetzner VPS → managed Fly.io** — migrate only when VPS ops
  burden exceeds cost savings, usually once a project gets a second
  maintainer.

## Adopt-time decision hints

| Detected | Classification | Recommendation |
|---|---|---|
| FastAPI + SQLAlchemy 2 + Alembic + argon2id | aligned | Stay. No action beyond the seed. |
| FastAPI + SQLAlchemy 1.x | divergent | Tune (M, reversible): schedule 1.x→2.0 migration as a separate PR. Don't bundle. |
| Django | divergent | Stay. Record the override. Migrate only as part of a planned rewrite. |
| Flask + SQLAlchemy | divergent | Stay at adoption. Consider FastAPI migration (M–L) as a follow-up *only* if the API surface is small and growing. |
| bcrypt for passwords | divergent | Stay + document. Migrate only alongside a planned auth change. |
| JWT sessions | divergent | Stay + document. Plan revocation+rotation before a security incident; don't migrate preemptively. |
| No Alembic, hand-managed SQL migrations | divergent | Tune (S, reversible): introduce Alembic with an `initial` revision mirroring current state. |
| Tests against SQLite only (prod is Postgres) | divergent | Tune (S): add a test Postgres via docker compose or `testcontainers`; migrate integration tests first, keep unit tests as-is. |
| Separate Node + Python repos for backend+frontend | divergent (shape) | Stay. Don't force a monorepo on adoption; revisit only if it actively hurts. |

## Seeding

```bash
gaia init --archetype multi-tenant-saas --name <project-name>
# or on an existing repo being adopted:
gaia adopt --seed --archetype multi-tenant-saas
```

After seed, scaffold `backend/` and `frontend/` separately. Record
concrete decisions (Alembic cost params, Fly region, Caddy vs. Fly
split) in `docs/knowledge.md` → Architecture as they are made.
