Deployment runbook
==================

Superbrain ships as three moving parts. The **scraper worker** (Phase 5, lives
at the repo root under `fly.toml`) and the **API** (Phase 9, this folder) run
on Fly.io's free tier; the **SPA** runs on Vercel. All three pieces are free
for a 3-user setup.

Read this once, then treat it as a copy-paste runbook.

Prerequisites
-------------

- A Fly.io account (`flyctl auth signup`) and `flyctl` on your PATH.
- A Vercel account (`vercel login`) and the Vercel CLI on your PATH.
- The shared API bearer token(s) agreed with the three humans who use the
  platform.

Topology
--------

```
┌──────────────────────┐    https://superbrain.vercel.app
│ Vercel static SPA    │──────────────────────────────────┐
└──────────────────────┘                                  │
                                                          ▼
                                         ┌────────────────────────────────┐
                                         │ Fly.io: superbrain-api         │
                                         │ uvicorn + FastAPI + DuckDB     │
                                         │ reads /data/lake (shared vol)  │
                                         └────────────────────────────────┘
                                                          ▲
                                                          │ writes
                                         ┌────────────────────────────────┐
                                         │ Fly.io: superbrain-scheduler    │
                                         │ APScheduler + scrapers          │
                                         │ writes /data/lake (shared vol)  │
                                         └────────────────────────────────┘
```

Both Fly apps mount the same volume (`superbrain_data`) at `/data`, so the
scheduler's writes are immediately visible to the API. The volume lives in a
single region — pick one close to you (we default to `fra`, change the
`primary_region` in both `fly.toml` files if you want).

Step 1 — provision the shared volume and secrets
------------------------------------------------

From the repo root:

```bash
# Create the API app without deploying yet.
fly launch --config deploy/api/fly.toml --no-deploy --copy-config --name superbrain-api

# Provision the volume that both apps will mount.
fly volumes create superbrain_data \
  --app superbrain-api \
  --region fra \
  --size 1

# Inject the bearer token(s). Comma-separated if multiple.
fly secrets set --app superbrain-api \
  SUPERBRAIN_API_TOKENS="replace-me-with-a-long-random-secret"
```

Step 2 — deploy the API
-----------------------

```bash
fly deploy --config deploy/api/fly.toml --dockerfile deploy/api/Dockerfile
```

The first deploy boots in ~40 s. Verify:

```bash
curl -fsS https://superbrain-api.fly.dev/health | jq .
```

You should see `{"service":"superbrain-api","lake":{"exists":true,…},…}`.

Step 3 — deploy the scheduler worker
-------------------------------------

Follows its own runbook (`docs/deployment/scheduler.md`, added by Phase 5).
It reuses the same `superbrain_data` volume so reads/writes stay consistent.

Step 4 — deploy the SPA on Vercel
---------------------------------

From the repo root:

```bash
cd frontend
vercel link       # first time only; creates .vercel/project.json
vercel env add VITE_API_BASE_URL production
# paste: https://superbrain-api.fly.dev
vercel env add VITE_API_TOKEN production
# paste: the same bearer token you set on Fly
vercel --prod
```

The Vercel project picks up `frontend/vercel.json` automatically:

- `framework: vite` + `buildCommand: npm run build` + `outputDirectory: dist`
- SPA rewrite so every route serves `index.html`
- Immutable cache headers on `/assets/*` (hashed filenames)
- Security headers (`X-Content-Type-Options`, `Referrer-Policy`, …)

Rolling updates
---------------

- API: `git push` + `fly deploy --config deploy/api/fly.toml` (blue/green;
  auto-stop scales machines to zero when idle, first request after idle takes
  ~2 s).
- Scheduler: separate fly app, separate deploy command (see its runbook).
- SPA: `vercel --prod`. Typically <30 s from push to live.

Rollback
--------

```bash
# API
fly releases --app superbrain-api
fly deploy --image registry.fly.io/superbrain-api:deployment-<previous-id> \
  --config deploy/api/fly.toml

# SPA
vercel rollback
```

Cost guardrails
---------------

- Fly free tier: 3 shared-cpu-1x machines @ 256 MB + 3 GB persistent volume.
  We use 2 machines (API + scheduler) + 1 GB volume → well inside free.
- Vercel Hobby: 100 GB bandwidth/month. 3 internal users will use <1 GB.

Monitoring
----------

- `GET /health` on the API returns scraper run freshness per bookmaker; if the
  `most_recent_run` for any bookmaker is older than `min_success_interval`,
  the field `stale: true` surfaces on the dashboard.
- The scheduler's Phase-8 alert hook pushes Telegram/email when value bets
  above the configured edge threshold appear — so the "is anything running?"
  check is implicit.

Troubleshooting
---------------

- **Fly build out-of-memory**: the default 256 MB builder is fine for our
  deps. If you add a wheel-heavy dep (e.g. `pandas` + `pyarrow` changes),
  bump `[build.args] MEMORY = "512"`.
- **curl_cffi fails on Alpine**: don't use Alpine. The Dockerfile is
  intentionally `python:3.12-slim` (glibc) because `curl_cffi` ships glibc
  wheels only.
- **CORS preflight failures**: update `SUPERBRAIN_CORS_ORIGINS` in
  `fly.toml` and `fly deploy`.
