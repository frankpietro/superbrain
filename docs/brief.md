# superbrain
### Product Vision
*Draft — 2026-04-21*

> This file is the **original brief** for superbrain. It is the
> starting idea, preserved as-is. When the project calibrates away from
> anything written here, record the new direction in
> `docs/knowledge.md`, not here. The brief is immutable; the knowledge
> log is where the project evolves.
>
> Seeded from Gaia (https://github.com/frankpietro/gaia).

---

## Concept in one line

An AI-owned football-betting research platform that continuously scrapes historical match data and live bookmaker odds, detects value bets through cluster-and-similarity analysis, and surfaces them through a web UI shared by three operators.

## Target audience

- **Primary**: three co-owners (the user and two friends) who want a single, shared, always-on tool to support their personal betting decisions.
- **Motivation**: the old `fbref24` repo proved the cluster/similarity value-bet algorithm works (corner bets were profitable in a live 2024-25 trial), but the codebase is unmaintainable and the scrapers are broken. A clean, reliable platform is worth more than new features.

## Core loop / key flows

1. Scrapers (historical stats + live bookmaker odds) continuously populate a DuckDB+Parquet lake.
2. The bet-agnostic engine clusters teams, builds a Frobenius-style similarity matrix, and for every live match + market computes a model probability.
3. Where model payout < bookmaker payout by a configurable threshold, a **value bet** is surfaced.
4. The three operators see live value bets in the SPA, drill into backtests and analytics, optionally record placed bets in the bet log.
5. Telegram alerts fire for new high-edge bets so operators can act without watching the dashboard.

## Success criteria

- The value-bet algorithm from the old repo is reproduced *exactly* (locked under a golden regression corpus) before any improvements land.
- The three bookmakers (Sisal, Goldbet, Eurobet) are scraped every few minutes with no manual intervention, across **all** markets they expose.
- A new collaborator can `git clone && uv sync && cp .env.example .env` and run any scraper locally, uploading results to the shared lake — no Docker, no cloud credentials, no push access.
- The platform is hosted continuously on free-tier infrastructure (Fly.io Hobby + Vercel + GitHub Actions).
- Historical match data for top-5 European leagues from 2020-21 to present is in the lake, from free sources only.

## Out of scope

- A public product or a paid tier.
- A mobile app.
- Any paid data API.
- Automated bet placement on bookmakers.
- Per-user accounts beyond the three bearer tokens.

## Non-goals

- **No CLI for end users.** All interaction happens through the SPA. A minimal developer CLI exists only for running scrapers manually during development.
- **No silent data loss.** Every scraper validates against a schema and quarantines rather than drops.
- **No irreversible migrations of old code.** The old `fbref24` repo is archival-only after the odds backfill and the team-name dictionary are extracted.
- **No matplotlib, ever.** Plotly graph_objects only.

## Open questions

- Which free historical data source ultimately wins (football-data.co.uk + Understat combined, vs. FBref via `soccerdata` if still alive, vs. scraping Sofascore/Fotmob). Decided by the phase-2 spike.
- Whether the Fly.io free allowance is enough to run APScheduler + FastAPI + DuckDB for three users or whether we need to move to Cloudflare R2 for the parquet lake.
- Which improvements beyond the frozen algorithm baseline actually produce measurable ROI lift — open until each phase-4b PR has data.
