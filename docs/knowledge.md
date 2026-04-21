# Knowledge log

> **This file is the source of truth for what superbrain is,
> what's been decided, and why.** Every agent must read it before
> editing and must update it before merging any non-trivial PR. See
> `AGENTS.md` for the protocol.

> **Authority.** When this file disagrees with the original brief
> (`docs/brief.md`), with your training data, or with what the user
> said in a previous chat, **this file wins.** The brief is the
> starting idea; this file is the calibrated direction.

> **Seeded from Gaia** (https://github.com/frankpietro/gaia). The *structure* of this file
> comes from Gaia; the *content* is yours.

---

## How to use this file

- **Reading.** Scan the Index. Read the sections relevant to your task.
- **Writing.** Stamp every entry with `YYYY-MM-DD`. Link to PRs/files, don't paste.
- **Invalidation.** Strike through (`~~like this~~`) superseded entries; add the replacement with a cross-reference. Never silently delete.
- **Promotion marker.** Start an entry with `GENERAL:` if the learning is a candidate for promotion to Gaia.

## Index

- [Product](#product)
- [User journey & UX](#user-journey--ux)
- [Architecture](#architecture)
- [Conventions](#conventions)
- [Algorithm correctness contract](#algorithm-correctness-contract)
- [Scraper reliability contract](#scraper-reliability-contract)
- [Gotchas](#gotchas)
- [Glossary](#glossary)
- [Deferred / open](#deferred--open)

---

## Product

### One-liner

AI-owned football value-bet platform: continuous scrapers → DuckDB+Parquet lake → bet-agnostic value-bet engine → React SPA shared by three owners.

### Identity & scope

| Fact | Value |
|------|-------|
| Codebase umbrella | `superbrain` (Python monorepo + `frontend/` SPA) |
| Primary surface | Web SPA at a Vercel URL, authenticated with bearer tokens |
| MVP scope | Top-5 European leagues, 2020-21 → present; Sisal + Goldbet + Eurobet odds across all markets they expose |
| Monetisation | None; personal tool for three owners |
| Platform | Fly.io Hobby (backend always-on) + Vercel free (frontend) + GitHub Actions (fallback scrapers) |

### Product decisions ledger

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-21 | Clean rebuild, not migration, from the old `fbref24` repo. Port only the value-bet math, the team-name canonicalization dictionary, and a one-off odds backfill. | The old repo had 4+ parallel `src` variants and was unmaintainable. Porting selectively avoids importing the mess. |
| 2026-04-21 | AI-owned: every change lands via agent-opened PRs reviewed by the user. No direct pushes to main. | User directive; matches Gaia's default concurrency contract. |
| 2026-04-21 | Historical data: free sources only, must be validated end-to-end before being approved. Likely combo: football-data.co.uk + Understat, with `soccerdata`/FBref as a bonus if still alive. | User budget constraint + algorithm needs the fullest stat set possible. |
| 2026-04-21 | Odds: hidden-API sniffing first (direct `httpx` against discovered JSON endpoints), Playwright only as a per-bookmaker fallback, no OCR unless forced. | Hidden JSON endpoints are faster and more robust than HTML parsing. |
| 2026-04-21 | Scope: scrape every market each bookmaker exposes — the 23 markets from the old repo are a floor, not a ceiling. | User directive. |
| 2026-04-21 | Always-on scraping: APScheduler lives inside the Fly.io backend process; GitHub Actions is the scheduled redundant fallback. | Fly Hobby gives one always-on machine for free; we get continuous scraping without a second service. |
| 2026-04-21 | Contributor ingestion: every scrape (local, GH Actions, or in-process) POSTs to the backend's `/ingest/odds` endpoint with a bearer token. No one needs push access to a data branch or cloud bucket credentials. | User directive: easy onboarding for collaborators. |
| 2026-04-21 | Storage: DuckDB over a partitioned Parquet lake under `data/lake/`. One authoritative DuckDB file at `data/superbrain.duckdb` defines views. | Fastest free option; polars-native; versionable; archetype-aligned. |
| 2026-04-21 | Algorithm extension strategy: bet-agnostic engine — each bet type declares `target_stat_columns` and a probability function; engine re-runs per bet. | Cheapest way to add new markets; matches the old `refactored_src` direction. |
| 2026-04-21 | Feature selection: automated ablation (randomized search over stat subsets + clustering hyperparameters, scored by backtest ROI on held-out seasons). No static CLI. | Bet-agnostic and extensible by construction; interaction via SPA only. |
| 2026-04-21 | Frontend stack: Vite + React + TypeScript + Tailwind + shadcn/ui + zustand + TanStack Query + TanStack Router. Charts via react-plotly.js. | Matches Gaia's `personal-web-spa` archetype; composes with backend plotly.graph_objects. |
| 2026-04-21 | Access control: three static bearer tokens minted by the owner, persisted in `localStorage`, sent as `Authorization: Bearer …` to the backend. | Three users; OAuth is overkill; matches "trade security for convenience" on personal infra. |

### Preserved learnings from the old `fbref24` repo

The old `refactored_src/` was the most complete variant. Things worth preserving (2026-04-21):

- The team-name canonicalization dictionary (`config/team_names.py`) is the single most valuable artifact. 100+ mappings across FBref/Sisal/Goldbet/Eurobet.
- The engine structure (`engine/clustering.py` + `engine/similarity.py` + `engine/probability.py` + `engine/pipeline.py`) is the template for phase 4a. Copy the math, not the surrounding code.
- The `betting_odds.db` SQLite (153K rows) is the odds backfill source. Schema split into 23 market-specific tables that collapse cleanly to the unified `odds` table.
- The Dash GUI, the Selenium-based Sisal scraper, the Telegram bot, all ad-hoc notebooks and HTML files, and the four parallel `src` variants are discarded.

---

## User journey & UX

1. Owner opens the SPA at the Vercel URL; logs in with a bearer token.
2. Landing on **Dashboard**: today's fixtures + live value bets table, sortable by edge / league / bookmaker. Clicking a bet shows its full math trace.
3. **Matches** lets drill-down into per-match odds across bookmakers and markets.
4. **Backtest** runs a sliding-window backtest with a parameter form; results stream in via SSE.
5. **Ablation** kicks off an automated feature search per market/league; winners flow back into the engine.
6. **Analytics**: ROI, Kelly sizing, calibration, drawdown, cohorts — plotly charts.
7. **Bet Log**: record placed bets, mark outcomes later, see personal ROI.
8. **Settings**: mint/rotate bearer tokens, toggle Telegram alerts, configure scheduling.
9. Telegram alerts fire out-of-band when new high-edge bets appear.

---

## Architecture

### Data-lake contract (phase 1, 2026-04-21)

The Parquet lake under `data/lake/` is the only persistence layer. The
entry point is `superbrain.data.connection.Lake`, which exposes:

- `ensure_schema()` — idempotent; runs numbered migrations under
  `src/superbrain/data/migrations/` and writes `schema_manifest.json`.
- `ingest_odds` / `ingest_matches` / `ingest_team_match_stats` — validated
  writes that dedupe on natural keys and return an `IngestReport`.
- `log_scrape_run` — append-only audit trail.
- `read_odds` / `read_matches` — union-by-name reads across hive
  partitions.

Hive partition layout:

| Table | Partition keys |
|-------|----------------|
| `odds` | `bookmaker=X/market=Y/season=Z` |
| `matches` | `league=X/season=Y` (+ top-level `match_index.parquet`) |
| `team_match_stats` | `league=X/season=Y` |
| `scrape_runs` | `bookmaker=X/year_month=YYYY-MM` |
| `simulation_runs` | `created_date=YYYY-MM-DD` |

Natural keys (dedupe):

- odds: `(bookmaker, bookmaker_event_id, market, params_hash, selection, captured_at)`
- matches: `(match_id)` where `match_id = sha256(league|date|home|away)[:16]`
- stats: `(match_id, team)`

Legacy odds backfill (`scripts/import_legacy_odds.py`) landed **99,492
Sisal rows** from `fbref24/refactored_src/data/betting_odds.db`, zero
rejected, re-run dedupes 100 %. Season code normalized from `"2526"` to
`"2025-26"`; team names canonicalized on the way in (`Siviglia→Sevilla`
etc.).

### Stack

| Concern | Choice |
|---------|--------|
| Language (backend) | Python 3.12 |
| Package manager | `uv` |
| Dataframes | `polars`; `duckdb` for SQL over the lake |
| ORM | None. Thin DuckDB connection wrapper + pydantic models. |
| Backend framework | FastAPI + uvicorn |
| Scheduler | APScheduler in-process inside the backend; GitHub Actions cron as fallback |
| Scraping | `httpx` (async); Playwright lazy-loaded per bookmaker only if forced |
| Historical sources (TBD after spike) | football-data.co.uk + Understat + (soccerdata if alive) |
| Bookmakers | Sisal, Goldbet, Eurobet |
| Testing | `pytest`, `pytest-asyncio`, `respx`, `hypothesis` for property tests |
| Lint/format | `ruff` |
| Types | `mypy` (strict on new code) |
| Plotting | `plotly.graph_objects` only. No matplotlib. |
| Frontend | Vite + React + TypeScript + Tailwind + shadcn/ui + zustand + TanStack Query + TanStack Router |
| Frontend charts | react-plotly.js |
| Storage | DuckDB + partitioned Parquet lake under `data/lake/` |
| Backups | Nightly rsync from Fly volume → `data-snapshots` branch (parquet, daily compaction < 50 MB/file) |
| Backend hosting | Fly.io Hobby (free always-on VM) |
| Frontend hosting | Vercel free tier |
| Alerts | Telegram bot |
| CI | GitHub Actions |

### Folder layout

```
superbrain/
├── AGENTS.md                 Gaia tier 1
├── .gaia/                    Gaia tier 2 + manifest + outbox
├── .cursor/                  session isolation + rules
├── .githooks/                conventional-commits + pre-push
├── .github/workflows/        CI + scheduled scrapers + backtest
├── docs/
│   ├── brief.md              immutable starting idea
│   ├── knowledge.md          this file
│   └── HOW_DATA_FLOWS.md     per-project reference (added in later phases)
├── pyproject.toml            uv-managed
├── uv.lock
├── src/superbrain/
│   ├── core/                 shared domain types, pydantic models
│   ├── data/                 DuckDB manager, parquet IO, schemas, migrations
│   ├── scrapers/
│   │   ├── historical/       football-data / understat / soccerdata adapters
│   │   └── bookmakers/       sisal / goldbet / eurobet (one module each)
│   ├── engine/               clustering, similarity, probability, bets registry
│   ├── ablation/             automated feature/column search
│   ├── analytics/            ROI, Kelly, calibration, drawdown, cohorts
│   ├── backtest/             sliding window + parallel grid
│   └── api/                  FastAPI app, routers, auth, scheduler, alerts
├── frontend/                 Vite + React SPA
├── scripts/                  one-off maintenance, legacy imports
├── tests/                    pytest
└── data/                     gitignored; local lake for dev
```

### Dev environment

Trade-offs made on the owner's personal dev machine. See `AGENTS.md` → "Operating principle".

- 2026-04-21 — `gh auth` is GitHub-token plaintext (via keychain), active account `pfra-bs`. Revert: `gh auth logout`.
- 2026-04-21 — **SSH commit signing disabled locally for this repo.** The global gitconfig signs every commit via 1Password's `op-ssh-sign`, which requires the 1Password app to be unlocked — that breaks AI-owned headless commits (the point of this project). Disabled with `git config --local commit.gpgsign false && git config --local tag.gpgsign false`. Revert: `git config --local --unset commit.gpgsign && git config --local --unset tag.gpgsign`. Trade-off logged per Gaia's "trade security for convenience when it removes a human step" principle.

---

## Conventions

### File layout

Python source lives under `src/superbrain/*`. Tests mirror the layout under `tests/`. One-off scripts live under `scripts/` and are deleted after use.

### Naming

- `snake_case` for Python modules and functions, `PascalCase` for classes, `SCREAMING_SNAKE` for constants.
- Parquet partition keys are lowercase (`league=serie-a`, `bookmaker=sisal`).
- Bet market codes are `snake_case`, stable, and enumerated in `src/superbrain/core/markets.py`.

### State

- DuckDB connection is a FastAPI dependency; writes take a write lock.
- Pydantic models are the contract at every system boundary (scraper output, API request/response, ingestion payload).
- UTC everywhere; convert at the edge only for display.

### Commits & PRs

- Conventional Commits enforced by `.githooks/commit-msg`.
- One logical change per commit. One PR per user-visible change.
- Every commit has the `Co-authored-by: Cursor Agent <cursoragent@cursor.com>` trailer.
- Never use markdown task-list syntax in a PR body.

---

## Algorithm correctness contract

**Rule:** the old `refactored_src/engine/` behaviour is the baseline. Phase 4a ports it behaviour-preserving and freezes the output on a canonical slice into `tests/fixtures/engine/golden_corners_v1.parquet`. The regression test fails CI on any deviation beyond 1e-9 on floats and exact equality on bet identity.

Canonical regression slice:

- Input: corners market, dates 2024-11-22 → 2025-05-15, `n_clusters=4, quantile=0.7, min_matches=6, probability_delta_threshold=0.2`.
- Output frozen: per-team cluster assignments, similarity-matrix checksum, per-match value-bet list (market, selection, model payout, bookmaker payout, edge, stake).

Property-based tests (hypothesis):

- Clustering output is invariant under row permutation of the input.
- Similarity matrix is symmetric and has ones on the diagonal.
- Model probability ∈ [0, 1] for every bet.
- Pipeline is deterministic under a fixed seed.

Phase 4b improvements land only as PRs that:

1. Keep the golden test green.
2. Report ΔROI, Δvalue-bets-found, Δprecision-at-k against the frozen baseline on at least three market/league slices.
3. Document the qualitative rationale in the PR body.

---

## Scraper reliability contract

Every scraper module satisfies:

- **Schema gate.** Output validated against a pydantic model; invalid rows routed to `data/lake/quarantine/` with the raw payload and the validation error.
- **Retries + circuit breaker.** `tenacity` with exponential backoff + jitter (3 retries). N consecutive failures trip the breaker for a cooldown window.
- **Canary.** A 5-minute scheduled workflow calls `scrape --sample`. Two consecutive canary failures auto-open a `bug: <scraper> down` GitHub issue and fire a Telegram alert.
- **Deterministic dedupe.** Idempotent on `(bookmaker, event_id, market_code, selection, captured_at)`.
- **Forensic payload.** Every odds row keeps a `raw_json` column so a parser regression can be replayed against stored payloads.
- **Observability.** Each run writes a row to `data/lake/scrape_runs/` (start, end, rows, quarantined, latency, git SHA). The SPA "Scraper Health" page reads these directly.

---

## Sisal scraper (phase 3, 2026-04-21)

Production scraper lives in `src/superbrain/scrapers/bookmakers/sisal/`.
Detailed README sits next to the code; this is the summary for future
agents.

**Architecture.** `scrape()` → `SisalClient` (async `httpx` + `tenacity`
retries + per-endpoint `asyncio.Semaphore`) → `parse_event_markets()`
(pure; never raises; returns `(list[OddsSnapshot], Counter[unmapped])`)
→ `Lake.ingest_odds` + `Lake.log_scrape_run`. The orchestrator owns
the run-id, `captured_at`, tree cache (1 h TTL, in-process), and the
`SisalScrapeResult` bookkeeping.

**Endpoints used.** `alberaturaPrematch` (tree),
`v1/schedaManifestazione/0/{competitionKey}?offerId=0&metaTplEnabled=true&deep=true`
(events per league), `schedaAvvenimento/{eventKey}?offerId=0`
(~2 MB, ~130 markets per Serie A prematch fixture). All three are
unauthenticated JSON over IPv4 from Italy — no cookies, no tokens.

**Top-5 league keys.** `1-209` Serie A, `1-331` Premier,
`1-228` Bundesliga, `1-570` La Liga, `1-781` Ligue 1 (all under
`sportId=1`). The tree → key map is brittle on `urlAlias`; resolve by
`descrizione` instead. Codified in `SISAL_LEAGUE_KEYS`.

**Rate / concurrency.** One request per second per endpoint class
(semaphore + minimum-interval limiter in `SisalClient`), event fetches
bounded by `asyncio.Semaphore(4)` in the orchestrator. Retries on
`429 / 502 / 503 / 504` and network errors, 3 attempts,
exponential-jitter backoff. 4xx other than 429 fails fast.

**Mapped market families.** 1X2 full + per-half, double chance full +
per-half, goals over/under (full + per-half, Asian lines, per-team),
GG/NG (full + per-half), multigoal (full + per-half + per-team), exact
score, HT/FT, corner 1X2 (full + 1T), corner handicap (full + 1T),
combos 1X2+U/O and BTTS+U/O, halves over/under. Anything not covered
is counted in `SisalScrapeResult.unmapped_markets` and logged once per
run at INFO.

**Known product gaps at Sisal** (spike 2026-04-21, unchanged): prematch
corner totals, corner per team, corner combos, cards, shots, shots on
target. Closing these needs a second bookmaker; do not build parsers
for them in this scraper.

**Team canonicalization.** Names from `firstCompetitor.description` /
`secondCompetitor.description` flow through
`superbrain.core.teams.canonicalize_team(name, Bookmaker.SISAL)`.
`match_id` = `stable_match_id(home_canonical, away_canonical, kickoff)`
so Sisal matches join cleanly against Goldbet / Eurobet / historicals.

**Idempotency.** Re-running `scrape(lake, run_id=X, captured_at=Y)`
with the same `(X, Y)` produces zero new rows: `Lake.ingest_odds`
dedupes on `OddsSnapshot.natural_key`, which folds
`(bookmaker, bookmaker_event_id, market, selection, frozen params,
captured_at, run_id)` into a stable hash. Verified by
`test_idempotent_second_scrape_emits_zero_new_rows`.

**Failure semantics.** `scrape()` never raises. A failed league emits
`events:<league>:<error>` to `SisalScrapeResult.errors`, sets status
to `partial`, and lets the other leagues continue. A failed event
emits `event_markets:<event_key>:<error>` and drops only that event's
rows. Only "zero rows written" sets status to `failed`.

**Fixture budget.** Test fixtures in
`tests/fixtures/bookmakers/sisal/` are compact (`separators=(",",":")`,
no `clusterMenu`, trimmed `scommessaMap` / `infoAggiuntivaMap`) and
each stay under 50 KB. `scripts/build_sisal_fixtures.py` regenerates
them from spike payloads. See `test_scraper.test_fixtures_are_under_50kb`
for the guard.

**Live smoke.**
`SUPERBRAIN_LIVE_TESTS=1 uv run pytest tests/scrapers/bookmakers/sisal/test_live.py`
hits the real API (Serie A only). CI and default `pytest -q` skip it.

---

## Gotchas

*Add new gotchas here whenever you debug something that cost you more than 10 minutes.*

- 2026-04-21 — **Sisal needs a browser User-Agent.** The spike ran with
  `superbrain-spike/0.1` and got HTTP 200s; by the time we built the
  production client, Akamai Bot Manager on `betting.sisal.it` started
  **silently timing out** any request whose `User-Agent` does not look
  like a mainstream browser. No 403 / 429 — just a dangling TLS
  connection. The default headers in `SisalClient` therefore pose as
  Chrome/macOS. Revisit this if request volume ever triggers a visible
  challenge (`_abck` gets a negative sensor value) and we need to
  persist cookies or rotate UAs.
- 2026-04-21 — **Sisal `descrizione`, not `descrizioneScommessa`**, is
  the market name the API publishes at event-detail level. The
  `esitoList` on each market entry is keyed by `codiceEsito`, and the
  selection label (`1`, `X`, `OVER`, `GOL`, `1+O`, …) lives in the
  matching `infoAggiuntivaMap` entry. Parse from those two together,
  not from `scommessaMap` alone.
- 2026-04-21 — **Sisal encodes `quota` as decimal-odds × 100 integer**
  (e.g. `173` → `1.73`), while `payout` carries the same number as a
  float. Prefer `payout`, fall back to `quota / 100` when missing.
- 2026-04-21 — **`soglia` is overloaded** on Sisal markets: threshold
  for over/under, `"1"` / `"2"` for team side on SQUADRA markets,
  `"1"` / `"2"` for half on MULTIGOAL TEMPO markets. Interpret per
  market family, not globally.
- 2026-04-21 — **Sisal `shortDescription` encodes the half** (`"1 T"`,
  `"TEMPO 1"`, `"T 1"`, `"1T"`) for per-half markets. Use a regex fold
  rather than exact matches; the SPA is inconsistent.
- 2026-04-21 — **FBref is dead.** `soccerdata`'s FBref backend broke when the site closed. Any scraper that imports `soccerdata.FBref` must be gated behind a live-check.
- 2026-04-21 — **The old repo's DuckDB schema is not portable.** Three separate SQLite files (`historical.db`, `betting_odds.db`, `simulations.db`) with overlapping keys. The migration script normalizes teams and drops one-off schema tables. Do not copy the old schema into the new lake verbatim.
- 2026-04-21 — **GitHub Actions cron minimum is effectively 5 minutes** and jobs are delayed under high platform load. The "always-on" piece must live on Fly.

---

## Glossary

| Term | Meaning |
|------|---------|
| Value bet | A bet where our model's implied probability exceeds the bookmaker's implied probability by more than `probability_delta_threshold`. |
| Frobenius similarity | Team-pair similarity score derived from the matrix norm of their stat-vector difference after clustering. |
| Canonical team name | The output of `canonical(team, source)` — the single identifier used across all sources. Mapped from the 100+-entry dictionary ported from `refactored_src/config/team_names.py`. |
| Canary | A frequent, small-scoped scrape whose only job is to detect breakage, not to populate data. |
| Golden regression corpus | Frozen output of the algorithm on a canonical slice; the assertion of correctness. |
| Quarantine | `data/lake/quarantine/` — where rows that failed schema validation land, with the error alongside. Never silently dropped. |

---

## Deferred / open

Items that will be decided as phases land:

- Which historical data source wins after the phase-2 spike.
- Whether to keep the Fly volume as the authoritative lake or move to Cloudflare R2.
- Exact market taxonomy (which bookmaker markets collapse into a shared `market_code` vs. get their own row).
- Whether to adopt a supervised layer on top of similarity in a future phase 4c.
- **CI `gaia doctor` job** — disabled in CI (2026-04-21) because Gaia is a private repo and the job can't clone it without a PAT. Re-enable by adding a `GAIA_READ_PAT` repository secret and restoring the `gaia` job in `.github/workflows/ci.yml`. Local coverage via the pre-push hook and the Cursor session-start hook is adequate in the interim.

---

<!-- The git history of this file is the changelog — no separate
section needed. Seeded from Gaia (https://github.com/frankpietro/gaia). -->
