# superbrain

AI-owned football value-bet platform: continuous scrapers, DuckDB+Parquet lake, bet-agnostic value-bet engine, React SPA shared by three owners.

> **This project is managed by an AI agent.** The human owners review PRs and answer questions; the agent does the rest. See `AGENTS.md` for the universal contract (seeded from [Gaia](https://github.com/frankpietro/gaia)) and `docs/knowledge.md` for project-specific decisions.

## What this is

Superbrain replaces the old `fbref24` prototype with a clean, reliable, always-on stack:

- **Continuous scrapers** for historical match stats (top-5 European leagues, 2020-21 → present, free sources only) and live bookmaker odds (Sisal, Goldbet, Eurobet, every market they expose).
- **Bet-agnostic value-bet engine** ported behaviour-preserving from `fbref24/refactored_src/engine/` and locked under a golden regression corpus.
- **DuckDB + partitioned Parquet lake** — one authoritative store for every query.
- **FastAPI backend** running on Fly.io (Hobby free tier, always-on). Hosts the API, the APScheduler scraper loop, the Telegram alerts dispatcher, and the ingestion endpoint any collaborator uploads scrape output to.
- **Vite + React + TypeScript + Tailwind + shadcn/ui** SPA on Vercel free tier, authenticated with bearer tokens (three owners).
- **GitHub Actions** runs redundant scheduled scrapes, CI, and the weekly backtest refresh.

## Architecture at a glance

See `docs/knowledge.md` → *Architecture*. Short version:

```
external sources            scrapers                lake                       UI
------------------          --------                ----------------------     ---
football-data.co.uk  ──┐    historical  ──┐
Understat            ──┼──> scrapers    ──┤
soccerdata (if alive)──┘                  │
                                          ▼
Sisal   ─┐    ┌────────┐            DuckDB + Parquet  ──>  FastAPI  ──>  Vite SPA
Goldbet ─┼──> │GH      │──> /ingest─▶  data/lake/     ──>  engine   ──>  Telegram
Eurobet ─┘    │Actions │                                             ▲
              │  +     │                                             │
              │Fly     │                                             │
              │APSched │─────────────────────────────────────────────┘
              └────────┘
```

## Repository layout

```
superbrain/
├── AGENTS.md                 Gaia tier 1 (universal agent contract)
├── .gaia/                    Gaia tier 2 + manifest + outbox
├── .cursor/                  session isolation + rules
├── .githooks/                conventional-commits + pre-push
├── .github/workflows/        CI + scheduled scrapers + backtest
├── docs/
│   ├── brief.md              immutable starting idea
│   ├── knowledge.md          living source of truth
│   └── HOW_DATA_FLOWS.md     (added in later phases)
├── pyproject.toml
├── uv.lock
├── src/superbrain/
│   ├── core/                 domain types, pydantic models
│   ├── data/                 DuckDB manager, parquet IO, schemas, migrations
│   ├── scrapers/             historical + bookmakers
│   ├── engine/               clustering + similarity + probability + bet registry
│   ├── ablation/             automated feature-column search
│   ├── analytics/            ROI, Kelly, calibration, drawdown, cohorts
│   ├── backtest/             sliding window + parallel grid
│   └── api/                  FastAPI app + routers + scheduler + alerts
├── frontend/                 Vite+React+TS SPA (phase 7)
├── scripts/                  one-off maintenance, legacy imports
├── tests/
└── data/                     gitignored local lake
```

## For new contributors

You are one of the three owners. You never need to open a terminal to use the platform — you log into the SPA with your bearer token. You only need the local toolchain if you want to run a scraper or help debug.

```bash
git clone https://github.com/frankpietro/superbrain.git
cd superbrain
uv sync --all-extras --dev
cp .env.example .env
# fill in SUPERBRAIN_INGEST_TOKEN with a token the owner minted for you
uv run pytest        # smoke test everything still compiles
```

To run a scraper locally and upload its output to the shared lake:

```bash
uv run python -m superbrain.scrapers.run --bookmaker=sisal   # added in phase 3
```

See `docs/knowledge.md` → *Scraper reliability contract* for the guarantees every scraper satisfies.

## Frontend

The SPA lives in `frontend/` and is built with Vite + React 18 + TypeScript
(strict) + Tailwind + shadcn/ui-style primitives, TanStack Router/Query,
zustand, and `react-plotly.js`. Quick start:

```bash
cd frontend
cp .env.example .env.local        # set VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev                       # http://localhost:5173
```

CI runs `lint`, `typecheck`, unit tests, and a production `build` on every
PR. Full details (route map, design tokens, architectural decisions) in
`frontend/README.md` and `docs/knowledge.md` → *SPA*.

## Deploy

Superbrain deploys to **Fly.io free tier** (API + scheduler, sharing one
persistent volume with the Parquet lake) and **Vercel Hobby** (the SPA).

Full runbook: [`docs/deployment/api-and-spa.md`](docs/deployment/api-and-spa.md).
Scheduler-only runbook: [`docs/deployment/scheduler.md`](docs/deployment/scheduler.md).

Quick shape:

```bash
# API (Fly)
fly launch --config deploy/api/fly.toml --no-deploy --copy-config --name superbrain-api
fly volumes create superbrain_data --app superbrain-api --region fra --size 1
fly secrets set --app superbrain-api SUPERBRAIN_API_TOKENS="<long-random>"
fly deploy --config deploy/api/fly.toml --dockerfile deploy/api/Dockerfile

# SPA (Vercel)
cd frontend
vercel link
vercel env add VITE_API_BASE_URL production   # → https://superbrain-api.fly.dev
vercel env add VITE_API_TOKEN    production   # → same token
vercel --prod
```

## Status

Phases 0 – 7 shipped. Phase 4b (engine tests + ablation), Phase 5 (scheduler),
and Phase 8 (alerts) are in flight. Phase 9 (this commit) wires the deploy
configs for the pieces already on `main`.
