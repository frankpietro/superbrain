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
├── frontend/                 (added in phase 9)
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

## Status

Early seed (phase 0). See the plan in the user's Cursor session for the phase sequence.
