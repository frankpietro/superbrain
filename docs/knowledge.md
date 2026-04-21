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
- [Alerts](#alerts-phase-8-2026-04-21)
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

### SPA (phase 7, 2026-04-21)

Single-page app lives in `frontend/` at the repo root, separate from the
Python monorepo.

| Piece | Choice |
|-------|--------|
| Build | Vite 5 + React 18 + TypeScript 5 (strict, `noUncheckedIndexedAccess`) |
| Styling | Tailwind 3 + shadcn/ui-style primitives hand-copied under `frontend/src/components/ui/` (no CLI; kept only the ones we use) |
| Routing | TanStack Router 1 (code-based tree in `frontend/src/router.tsx`) |
| Data fetching | TanStack Query 5; stale-time 30 s, no refetch-on-focus, retries disabled for 401/404 |
| Global state | `zustand` with `persist`; `superbrain.auth` (bearer token) + `superbrain.prefs` (theme, timezone, selected leagues) — both in `localStorage` |
| Boundary validation | `zod` schemas in `frontend/src/lib/types.ts`; every API response is `safeParse`d and malformed payloads raise `ApiParseError` for a banner (never a blank screen) |
| API client | `frontend/src/lib/api.ts` — typed `apiFetch<T>(path, schema, opts)`, bearer-token header, base URL from `VITE_API_BASE_URL`; 401 auto-clears the token |
| Charts | `react-plotly.js` over `plotly.js-cartesian-dist-min` (saves ~3 MB vs `plotly.js-dist`); component wrapper at `src/components/plot.tsx` |
| Tests | Vitest + React Testing Library + `@testing-library/jest-dom`; `src/test/setup.ts` installs an in-memory `Storage` because Node 25 ships an experimental `localStorage` that conflicts with jsdom |
| Lint / format | ESLint flat-ish (`.eslintrc.cjs`) with `@typescript-eslint` + Prettier; `--max-warnings 0` |

Routes:

| Path | Purpose |
|------|---------|
| `/login` | Bearer-token entry. Validates against `GET /health` + an authenticated probe. |
| `/` | Dashboard: fixture / value-bet / scraper-health cards + today's matches table. |
| `/matches` | Filterable table (league multi-select, date range, team search). |
| `/matches/$id` | Fixture detail + odds pivot (markets × bookmakers, last-update tooltip). |
| `/scrapers` | Per-bookmaker tiles: status, rows written, unmapped markets, rows-written history chart, trigger button. |
| `/bets/value` | Empty state until the engine ships in phase 4b; sortable table when items arrive. |
| `/backtest` | Form → `POST /backtest/run`; 501 is caught and rendered as a friendly toast. |
| `/settings` | Active token (masked), theme, timezone, API base URL. |

Env: copy `frontend/.env.example` → `frontend/.env.local` and set
`VITE_API_BASE_URL`. Build/test:

```bash
cd frontend
npm install
npm run lint
npm run typecheck   # tsc --noEmit (strict, noUncheckedIndexedAccess)
npm run test -- --run
npm run build       # dist/, ~2.0 MB unminified / ~650 KB gzipped (plotly-heavy)
```

CI runs the same four commands as the `frontend` job in
`.github/workflows/ci.yml` on Node 20 (npm cache keyed on
`frontend/package-lock.json`).

Types are hand-written from `superbrain.core.models` + `markets`; replace
with `openapi-typescript` output once the Phase-6 backend exposes a stable
`/openapi.json`. See `docs/knowledge.md` → *Deferred* for the switch-over.

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

### Historical data pipeline (phase 2, 2026-04-21)

Lives under `src/superbrain/scrapers/historical/`. Backfills matches,
team-match stats, and team Elo for the top-5 European leagues from
2020-21 onward. Idempotent by construction — everything flows through
`Lake.ingest_*`, natural keys dedupe.

**Source stack, by role:**

| Source | Role | Transport | Fields |
|--------|------|-----------|--------|
| football-data.co.uk | **Primary backbone** (shots, cards, fouls, HT/FT goals, referee, closing odds) | `httpx` against the static `mmz4281/<YYYY>/<LEAGUE>.csv` URL | schedule, FT/HT goals, 6x 1X2 + AH + OU closings, shots, SoT, corners, fouls, yellows, reds, referee |
| Understat | **xG/xGA/xPts** (must-have for the engine) | Direct AJAX (`/getLeagueData/<slug>/<year>` with `X-Requested-With: XMLHttpRequest`) | per-match xG, xGA, xPts, shots, shots on target |
| `soccerdata.FBref` | **Enrichment** (possession, pressures, PPDA proxy, passing%) | `soccerdata` + `undetected-chromedriver` | whatever FBref exposes per stat-type; pivoted per team |
| `soccerdata.ClubElo` | **Team ratings** (new `team_elo` table) | `soccerdata` | daily Elo + rank per club |

**Merge order** (`merge.py`):

1. Fetch football-data CSV and Understat payload per `(league, season)` — always.
2. Pivot FBref per stat type if `fbref` is in `--sources`.
3. Canonicalize team names via `superbrain.core.teams.canonicalize_team` **before** joining.
4. Outer-join football-data + Understat on `(league, match_date, home_canon, away_canon)`; preserve both sides when one is missing (null fills).
5. Compute `match_id = sha256(league|date|home|away)[:16]` once per merged row.
6. Emit two records per row into the stats frame (home & away), attach FBref columns by `(match_id, team)` left-join if present.
7. ClubElo runs independently — one pass per country, writes into the `team_elo` table, not blocking matches.

**Lake surface:**

- `matches`: hive `league=X/season=Y`; natural key `match_id`.
- `team_match_stats`: hive `league=X/season=Y`; natural key `(match_id, team)`.
- `team_elo` (new, migration `m003_team_elo`): hive `country=X`; natural key `(team, snapshot_date, source)`.
- `scrape_runs`: every backfill call logs one row per `(league, season, source-set)`.

**Orchestrator:** `scripts/backfill_historical.py` — CLI:
`--lake`, `--leagues`, `--seasons`, `--sources football_data,understat[,fbref,clubelo]`.
Prints a JSON report with `matches_written / matches_skipped / stats_written / elo_written / rejected`.

**Dependency note:** `soccerdata` is an **optional** extra
(`uv sync --extra historical`). Core `football_data` + `understat`
paths are pure-`httpx` and need no Chromedriver.

**Measured baseline (2026-04-21, live, Serie A 2023-24, football-data + understat):**

- 382 matches written, 764 team-match-stats rows, 0 rejections.
- Wall clock: 1.77s first run; re-run is idempotent (writes 0 rows, skips 382).

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
| Historical sources | football-data.co.uk (primary) + Understat AJAX (xG) + `soccerdata.FBref` (enrichment) + `soccerdata.ClubElo` (team ratings) |
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

### Value-bet engine (phase 4a, 2026-04-21)

The engine is a behaviour-preserving port of `fbref24/refactored_src/{engine,bets}` onto the new lake (Polars + DuckDB) and the new `Market` / `OddsSnapshot` pydantic contracts. Lives under `src/superbrain/engine/` and `src/superbrain/engine/bets/`. Imports are side-effect-driven: importing `superbrain.engine.bets` registers every concrete strategy into `BET_REGISTRY` by virtue of the `@register(Market.X)` decorator.

Pipeline shape:

1. `build_engine_context(lake, fixture=..., config=...)` reads `matches` + `team_match_stats` rows with `match_date < fixture.match_date` (strict no-leakage), attaches an `opponent` column (derived from the matches table), clusters, merges opponent clusters, and computes the `(team, season)` similarity matrix.
2. `price_fixture(...)` iterates every registered `BetStrategy`, pulls the neighbor sample once per target column per fixture, and feeds it to `strategy.compute_probability(outcome, values_home=..., values_away=...)`. Outcomes with fewer than `config.probability.min_matches` (default 6) on either side are skipped.
3. `find_value_bets(...)` joins `price_fixture`'s output against the latest snapshot per `(bookmaker, market, selection, params)` tuple, computes `edge = model_probability - 1/decimal_odds`, and emits `ValueBet` rows sorted by descending edge.

Parameters (matching the old repo's production defaults):

- Clustering — `sklearn.cluster.AgglomerativeClustering(metric="cosine", linkage="average")` with `n_clusters=8`, `StandardScaler` on the feature columns `(goals, goals_conceded, shots, shots_on_target, corners, yellow_cards, fouls)`.
- Similarity — per `(team, season)`, an `n_clusters × n_clusters` `(cluster, opponent_cluster)` co-occurrence matrix, normalised row-wise to a probability distribution; similarity = `1 / (1 + euclid_distance(flat_A, flat_B))` — equivalent to the old Frobenius formulation because flattening preserves the norm. Implemented with `scipy.spatial.distance.pdist` + `squareform`, fully vectorised.
- Probability — quantile threshold `q = 0.7`, minimum sample `min_matches = 6`. For a fixture we pool target-stat values from matches where `(team, opponent, season)` triples are in the similarity neighborhood of the home/away teams.
- Value bet — `edge_threshold = 0.05` default, tunable from config.

Registered markets (13): `cards_total`, `corner_1x2`, `corner_combo`, `corner_handicap`, `corner_team`, `corner_total`, `goals_both_teams`, `goals_over_under`, `goals_team`, `match_1x2`, `match_double_chance`, `shots_on_target_total`, `shots_total`. Every strategy is stateless and declares `target_stat_columns()` as the `TeamMatchStats` columns it needs.

Intentional deviations from the old repo (none change observable behaviour on the canonical slice):

- Opponent-cluster join uses `(match_id, opponent)` instead of `(date, season, team, opponent)` — equivalent by construction and ~10x faster on large lakes.
- Caching: in-process LRU on `(target_column, home, away, season)` inside `price_fixture` instead of the old disk-based `engine/cache.py` (lake is the durable layer; re-pricing is cheap enough that a pickle cache is net-negative on CI).

Golden regression corpus and full end-to-end backtest are **deferred to phase 4b** (see *Deferred / open*). Unit tests cover clustering determinism + partition invariance under row permutation, similarity symmetry / range / hand-computed reference value, and neighbor pooling on a hand-computed 5-team toy. `tests/engine/test_*.py` (22 tests) is the current correctness floor.

### Alerts (phase 8, 2026-04-21)

Notification layer over high-edge value bets produced by the pricing pipeline. Lives under `src/superbrain/alerts/`; tests under `tests/alerts/`. The engine owns *what* is a value bet; this package owns *whether, where and how* to tell a human.

Shape:

1. `AlertPolicy.should_alert(value_bet)` filters a batch into `AlertRecord`s. Rejects fire first-match-wins and are counted on `AlertRunReport.rejected_by_reason`.
2. `AlertDispatcher.dispatch(value_bets)` loads the last `alert_dedup_window_hours` of `alert_id`s from the sink, runs the policy, fans out to every enabled channel **concurrently per alert, sequentially across alerts**, and persists every `(alert_id, channel)` pair.
3. `run_alert_sweep(lake)` is the scheduler hook: reads upcoming fixtures in the next `alert_lookahead_hours`, prices them via `find_value_bets`, and calls the dispatcher. Phase 5's APScheduler owns the *when*; this function is the *what*. Also exposed as `python -m superbrain.alerts --run-once` for the GH Actions fallback and the Fly worker.

Threshold reasoning:

- `SUPERBRAIN_ALERT_EDGE_THRESHOLD=0.05` matches the engine's default `edge_threshold`. Lowering it here doesn't help (the engine drops sub-threshold bets before we see them) — the knob exists so owners can raise it for noisy periods.
- `SUPERBRAIN_ALERT_MIN_PROBABILITY=0.35` guards against +EV longshots that clear edge by virtue of sample variance on rare outcomes (think `corner_total` > 14 at 6.0 odds). 35% is empirical: the fbref24 backtest over 2020-23 showed the realised-vs-model gap widening below that floor.
- `SUPERBRAIN_ALERT_MAX_PER_RUN=20` + `SUPERBRAIN_ALERT_MAX_PER_MATCH=3` are anti-spam guardrails; a pathological fixture can price 8–10 bets when cornering markets are liquid, and a single Telegram sweep dropping 40 messages is a fast way to train owners to mute the bot.

Dedup contract:

- Natural key: `(bet_code, match_id, bookmaker, selection, date(kickoff))`. `alert_id` is a deterministic hex hash of that tuple.
- Sink (`data/alerts/sent_alerts.parquet`) records one row per `(alert_id, channel, kickoff_date)` — we track channel-level deliveries so a retry after a partial failure doesn't double-send on the channel that succeeded.
- `AlertSink.load_alerted_ids(since=...)` returns the set of `alert_id`s whose status is `sent` or `partial` on **any** channel within the dedup window. Those IDs are blocked for the whole sweep. Alerts that failed everywhere stay eligible for re-delivery on the next run.
- Intra-batch dedup is enforced inside `AlertPolicy` too, so a pricing quirk that emits the same `(market, selection)` twice in one run only alerts once.

Channel optionality:

- Both channels are opt-in via env. `TelegramChannel.from_settings(...)` returns `None` unless both `SUPERBRAIN_TELEGRAM_BOT_TOKEN` and `SUPERBRAIN_TELEGRAM_CHAT_IDS` are set. `EmailChannel.from_settings(...)` returns `None` unless both `SUPERBRAIN_SMTP_HOST` and `SUPERBRAIN_ALERT_EMAIL_RECIPIENTS` are set.
- If no channel is enabled, `AlertDispatcher` still runs — policy decisions are recorded as `AlertRunReport(sent=0, channels=[])`. That's deliberate: it means a fresh clone can smoke the pipeline end-to-end without provisioning credentials.

Delivery guarantees — what each channel does with a batch:

- **Telegram**: one `sendMessage` call per `(alert, chat_id)` pair, HTML `parse_mode` (smaller escape surface than MarkdownV2, enough for team names + bookmaker slugs). 429 responses honour `parameters.retry_after`; otherwise fall back to `backoff_base * 2^(attempt-1)` up to `max_attempts=3`. Status is `sent` when every chat id succeeds, `partial` on mixed, `failed` on all-zero.
- **Email**: one batched `multipart/alternative` (plain text + HTML table) per sweep, TLS via `smtplib.SMTP_SSL`. Subject is `Superbrain: {N} value bet(s)` so owner inbox rules can filter cleanly. One `ChannelResult` per alert, all sharing the same `sent_at`; `status` is `sent` for all on success, `failed` for all on SMTP error (SMTP is a batch protocol — no per-recipient partials).

Operator runbook:

1. **Telegram bot.** Open `@BotFather` → `/newbot` → copy the token into `SUPERBRAIN_TELEGRAM_BOT_TOKEN`. Start a chat with the bot, send any message, then `curl https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `result[-1].message.chat.id` into `SUPERBRAIN_TELEGRAM_CHAT_IDS`. For channels prefix `-100`. Multiple ids are comma-separated.
2. **SMTP.** Use an app-password-capable provider (Fastmail, Zoho, Gmail with an app password, SES with SMTP creds). Set `SUPERBRAIN_SMTP_HOST`/`PORT` (`465` for SMTPS), `SUPERBRAIN_SMTP_USER`/`PASSWORD`, `SUPERBRAIN_SMTP_FROM` (must match the auth identity for most providers), and `SUPERBRAIN_ALERT_EMAIL_RECIPIENTS` (comma-separated).
3. **Dry-run.** `uv run python -m superbrain.alerts --run-once` reads the lake, prices the next 48 hours, runs the policy, dispatches to whichever channels are configured, persists to the sink, and prints a JSON summary. Safe to rerun — the sink idempotency blocks re-sends inside the dedup window.
4. **Tuning.** If the bot is noisy, raise `SUPERBRAIN_ALERT_EDGE_THRESHOLD` or `SUPERBRAIN_ALERT_MIN_PROBABILITY` before lowering `SUPERBRAIN_ALERT_MAX_PER_RUN` — the latter silently drops information, the former two shift the bar.

### Ablation and engine tests (phase 4b, 2026-04-21)

Phase 4b closes two of the three phase-4a follow-ups and introduces the feature-ablation harness that the SPA will consume in phase 4c. Lives under `src/superbrain/ablation/` and new test files under `tests/engine/` and `tests/ablation/`.

**Engine test coverage (shipped).** Three new test modules:

- `tests/engine/test_bets.py` — parametrized over every registered `BetStrategy`. Asserts that `iter_outcomes` materialises every `(selection, params_hash)` seeded into the snapshot list, that `compute_probability` stays in `[0, 1]` and is strictly positive on at least one outcome per market against a deterministic `(home=[3]*6, away=[2]*6)` neighbour sample, that repeated input dedupes, and that empty neighbour samples return `0.0` without raising. Tiebreaker: `validate_result` returning `None` when both realised values are missing — per-team markets (`corner_team`, `goals_team`) decide on one side alone, so the "one missing" case is not universally `None` and is covered instead in `test_backtest`.
- `tests/engine/test_pipeline.py` — integration against a purpose-built 20-match lake (six teams, round-robin prefix). Asserts `build_engine_context` returns a populated similarity matrix, `price_fixture` yields finite probabilities in `[0, 1]` with correct `model_payout = 1 / p`, and `find_value_bets` returns bets sorted by descending edge with non-negative expected value per row. Deterministic: same fixture ⇒ same priced outcomes bit-for-bit.
- `tests/engine/test_backtest.py` — 10-match synthetic lake, forced short-priced OVER 0.5 bets via a module-level `OddsProvider`. Asserts `n_wins + n_losses + n_unresolved == n_bets`, `roi == total_profit / total_stake`, `hit_rate == n_wins / (n_wins + n_losses)`, and — constructively — that wrapping the lake in `_NoLeakageLake(cutoff=fixture.match_date)` makes `read_matches` / `read_odds` return zero rows for the held-out match-of-interest.

**OddsProvider is now a `typing.Protocol`** (`src/superbrain/engine/backtest.py`). Was a concrete class with a raising `__call__`; that made every callable-based test fail mypy. The new `@runtime_checkable` Protocol keeps the contract identical at runtime and lets tests pass plain functions.

**FeatureAblationStudy (shipped).** `src/superbrain/ablation/`:

- `FeatureAblationStudy` is a dataclass wrapping `run_backtest` in a greedy forward-selection loop over clustering features. Seeds with the best size-2 subset pairing the anchor feature (first in tie-breaker order) against every other feature, then greedily extends while ROI strictly improves. Tie-breaking across candidates is stable (alphabetical on the added feature); tie-breaking across trajectory maxima prefers fewer features, then lexicographic subset.
- **Deterministic by construction.** Given identical lake + fixtures + universe + tie-breaker + base pricing config, two runs produce bitwise-identical trajectories and best subset. The `seed` attribute is currently unused (greedy search is deterministic without it) but is threaded through for future stochastic variants.
- **Fail-soft on degenerate clustering.** A subset whose feature vectors collapse to zero makes sklearn's cosine `AgglomerativeClustering` raise `"Cosine affinity cannot be used when X contains zero vectors"`. The study catches this at the trial boundary, logs `ablation: backtest failed for subset=...`, and scores the trial ROI=0 so the search continues and the trajectory remains complete.
- **Persistence contract.** Trajectories are written to `data/ablation_runs/<bet_code>/<run_id>.parquet` with schema `(run_id, bet_code, feature_subset: list[str], n_matches, roi, hit_rate, avg_edge, started_at, finished_at)`. Reads via DuckDB in `read_ablation_runs(root=..., bet_code=...)` so the FastAPI read-side can stream them to the SPA without changing the lake layout.
- **No CLI, no HTTP endpoint.** The ablation entry points are Python class + parquet only. SPA wiring lives in phase 4c; this is the foundation.

Tests (5 in `tests/ablation/test_feature_ablation.py`) cover:

1. `test_greedy_forward_selection_is_deterministic` — two fresh lakes built with the same seed produce identical trajectories and best subsets.
2. `test_best_subset_is_the_trajectory_maximum` — the chosen best is the ROI-argmax in the trajectory (no outcome beats it).
3. `test_parquet_persistence_roundtrips` — every row of the dumped parquet matches the in-memory outcome, the schema equals `ABLATION_FRAME_SCHEMA`, and `finished_at >= started_at`.
4. `test_read_ablation_runs_filters_by_bet` — DuckDB glob read filters by bet_code and returns an empty frame for missing bets.
5. `test_empty_feature_universe_raises` — a <2-column universe raises `ValueError`.

### Golden regression corpus TODO (phase 4b, 2026-04-21)

Deferred to a dedicated `feat(engine): golden regression corpus` PR. The blocker is shape translation, not algorithmic equivalence:

- `fbref24/refactored_src/engine/pipeline.py` takes pandas DataFrames keyed by `(league, season, date, team, opponent)` and returns dicts of (dict of pandas). Our new lake materialises polars frames keyed by `(league, season, match_id, is_home)`.
- The adapter needed is a reader that (a) pulls our lake's Serie A 2023-24 first-20-matchday slice, (b) projects the row schema into the old pandas shape (flatten `team`/`opponent`/`is_home` into the old `(HomeTeam, AwayTeam, HomeGoals, AwayGoals, HomeStat, AwayStat, …)` wide format), and (c) feeds that into the old pipeline.
- Output capture needs mirror code: legacy returns pandas DataFrames, we store polars + a SHA256 of the flattened bytes; either we convert on the fly at snapshot time, or we freeze both representations.
- Scope: 1 file of translation code (~150 lines), 1 script (`scripts/generate_engine_golden.py`), 1 test (`tests/engine/test_regression.py`) asserting `abs(new - old) <= 1e-6` on probabilities and exact equality on cluster partitions. Estimate: a single focused PR once the translator is written.

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

### Goldbet scraper (phase 3, 2026-04-21)

Production scraper at `src/superbrain/scrapers/bookmakers/goldbet/`.
Full usage and endpoint catalog live in that module's `README.md`; this
entry records the decisions future agents need to know without reading
the code.

- **Akamai bootstrap.** Goldbet is fronted by Akamai Bot Manager with
  JA3 fingerprinting. A plain `httpx` client is blocked at the edge
  with `HTTP 403`. The scraper uses **`curl_cffi` with
  `impersonate="chrome124"`**, evaluated in a 20-minute time-box
  against Playwright: `curl_cffi` alone clears the edge today, removes
  the need for a Chromium binary and `playwright install`, and keeps
  the runtime footprint small. Playwright is the documented fallback
  in the module README if fingerprint aging ever breaks it.
- **Cookie refresh cadence.** Reactive, not scheduled. One GET against
  `https://www.goldbet.it/scommesse/sport/calcio/` seeds `_abck`,
  `bm_sz`, `ak_bmsc` into the session jar at startup; any downstream
  `403` triggers a single in-flight refresh before retries give up.
  Long-running processes (APScheduler inside Fly) open a fresh session
  per scrape, so cookie staleness is bounded by scrape frequency.
- **Mandatory headers.** `X-Brand: 1`, `X-IdCanale: 1`,
  `X-AcceptConsent: false`, `X-Verticale: 1` on every JSON request.
  Missing any of the four → `HTTP 403` even with valid Akamai cookies.
- **Market families mapped.** `MATCH_1X2`, `MATCH_DOUBLE_CHANCE`,
  `GOALS_OVER_UNDER`, `HALVES_OVER_UNDER` (HT + 2H), `GOALS_BOTH_TEAMS`,
  `GOALS_TEAM` (per-side O/U), `COMBO_1X2_OVER_UNDER`,
  `COMBO_BTTS_OVER_UNDER`, `SCORE_EXACT`, `SCORE_HT_FT`, `CORNER_TOTAL`
  (match + 1H), `MULTIGOL` (full-match), `MULTIGOL_TEAM` (per-side).
  Per-event cost: ~26 requests (Principali + ~25 tab blocks).
- **Market discovery beyond the spike.** The spike's README said
  only `macroTab=0` returned odds; that was too conservative.
  `getDetailsEventAams` **does** return odds when called with each
  tab's `tbI` (e.g. `3500` for Angoli, `3491` for Multigol). The
  orchestrator fetches `tab=0` once (for Principali + the tab tree)
  and iterates every `tbI` under `lmtW`, lifting per-event coverage
  from ~19 markets to 200+. See `src/superbrain/scrapers/bookmakers/
  goldbet/scraper.py::_fetch_event_snapshots`.
- **Unmapped-market policy.** A curated `_EXPLICIT_SKIP` set in
  `markets.py` silences families that don't cleanly map onto the
  shared `Market` enum (half-time 1X2, parity, handicap 1X2, bucketed
  totals, VAR / penalty / card-coach specials). Genuinely unknown `mn`
  strings get one `goldbet.unmapped_market` log entry per run. Missing
  markets never fail an event; missing events never fail a league.
- **Rate limit & concurrency.** ≤ 1 HTTP req/s (token bucket);
  `asyncio.Semaphore(3)` on per-event market fetches; tenacity with 3
  attempts + expo backoff + jitter; `403` triggers one cookie refresh.
- **Known product gaps.** No shots / tiri markets on Serie A regular
  season. No team-specific cards O/U (Sanzioni tab is coach bookings,
  penalty markets, VAR specials only). Anytime / first-goalscorer
  markets live under a separate antepost `idTournament` and aren't on
  the production path yet.
- **Tournament IDs.** Hard-coded in `client.TOP5_TOURNAMENTS`. If
  Goldbet renumbers, `getProgram/` enumerates the full tree.
- **GENERAL: `OddsSnapshot` dedupe keys include `captured_at`.** Tests
  that assert idempotency of a scrape must monkeypatch
  `datetime.now()` to a frozen instant inside the scraper/parser
  modules, otherwise a second run legitimately writes fresh rows. See
  `tests/scrapers/bookmakers/goldbet/test_scraper.py::test_scrape_is_idempotent`.

### Eurobet scraper (phase 3, 2026-04-21)

Production scraper lives in `src/superbrain/scrapers/bookmakers/eurobet/`. Dual transport: plain `httpx` for public navigation (`prematch-homepage-service`, `prematch-menu-service`), **`curl_cffi` with `impersonate="chrome124"`** for the Cloudflare-gated `detail-service` (per-event + per-meeting). `curl_cffi` is now a hard runtime dep (see `pyproject.toml`); it carries a vendored libcurl-impersonate.

- **Cloudflare bot-fight gate.** `www.eurobet.it` fronts `detail-service` with Bot Fight Mode. Plain `httpx` returns `403 cf-mitigated: challenge`. TLS / JA3 impersonation is the only thing Cloudflare checks — cookies and Playwright are not required. UA string is cosmetic once the fingerprint matches.
- **Mandatory tenant headers** on every `detail-service` call: `X-EB-MarketId: IT` and `X-EB-PlatformId: WEB`. Missing `X-EB-MarketId` → backend 404. Missing `X-EB-PlatformId` → `{"code":-99,"description":"validation error"}`. Cloudflare occasionally strips or cache-poisons `X-EB-PlatformId` on the meeting endpoint; the scraper tolerates this by fusing `top-disciplines` (public, always available) with `detail-service/meeting` (authoritative) and deduping events.
- **Discipline/meeting slugs.** `calcio` for football. Top-5 meeting slugs verified live: `it-serie-a` (21), `ing-premier-league` (86 — **not** `gb-premier-league` as the spike initially recorded), `de-bundesliga` (4), `es-liga` (79), `fr-ligue-1` (14).
- **Rate limit.** Single shared `_RateLimiter` on the client, ≤ 1 req/s across both transports. Per-event market fetches run under `asyncio.Semaphore(3)` on top of that.
- **Mapped market families.** 1X2 full + per-half, 1X2 handicap, double chance, goals over/under, BTTS, multigoal (full + per-team), goals-per-team Y/N, exact score (incl. XL variants), HT/FT, corners 1X2, corners over/under, cards over/under. "SCOMMESSE TOP" compound groups (`betId` 1549 / 6754) are fan-out-walked into the individual families. `_FAMILY_BY_BET_ID` in `markets.py` is the canonical mapping; the exact-score XL market has two `betId` variants (`5458` and `5474`) depending on fixture.
- **Known gaps (unmapped, logged once per run).** On the 2026-04-21 live measurement (49 events, top-5 leagues): `QUASI VINCE`, `1X2 + U/O`, `1X + U/O`, `X2 + U/O`, `GG/NG + U/O`, `RIS. ESATTO A GRUPPI` — all appear on ~every event (49/49). These are combo / grouped markets; follow-up phase can map them once we decide whether they fold into existing market families or get their own codes. Match-day-only groups (scorers, corners-team, cards combos, shots, asian handicap) are passed through unmapped for now — the spike catalog documents them but phase 3a intentionally keeps scope to families Sisal and Goldbet already cover.
- **Measured output (2026-04-21 live run).** 49 events discovered (10/10/9/10/10 across Serie A / Premier / Bundesliga / La Liga / Ligue 1), 5 981 snapshots received, 5 785 written (196 deduped against same-minute re-pricing). Distribution: 3 626 exact-score, 879 1X2, 694 goals-O/U, 441 HT-FT, 196 BTTS, 145 double-chance. No errors.
- **Live smoke test.** `SUPERBRAIN_LIVE_TESTS=1 uv run pytest tests/scrapers/bookmakers/eurobet/test_live.py`.

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
- ~~2026-04-21 — **FBref is dead.** `soccerdata`'s FBref backend broke when the site closed. Any scraper that imports `soccerdata.FBref` must be gated behind a live-check.~~ **Superseded 2026-04-21:** `soccerdata.FBref` works (via `undetected-chromedriver`); kept as an enrichment source behind `--sources fbref`, not the primary. See *Historical data pipeline (phase 2)* below.
- 2026-04-21 — **Understat doesn't embed `datesData` anymore.** The old `JSON.parse` block on the league HTML page is gone (site redesign). Don't parse the league HTML. Use the internal AJAX endpoint `GET https://understat.com/getLeagueData/<league_slug>/<start_year>` with header `X-Requested-With: XMLHttpRequest`; it returns the full JSON payload (`dates`, `teams`, `players`). Our `understat.py` implements it directly in `httpx`; no `understatapi` dep.
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

- ~~Which historical data source wins after the phase-2 spike.~~ Decided 2026-04-21: football-data.co.uk (primary) + Understat (xG) + optional `soccerdata.FBref` + `soccerdata.ClubElo`. See *Historical data pipeline (phase 2)*.
- Whether to keep the Fly volume as the authoritative lake or move to Cloudflare R2.
- Exact market taxonomy (which bookmaker markets collapse into a shared `market_code` vs. get their own row).
- Whether to adopt a supervised layer on top of similarity in a future phase 4c.
- **CI `gaia doctor` job** — disabled in CI (2026-04-21) because Gaia is a private repo and the job can't clone it without a PAT. Re-enable by adding a `GAIA_READ_PAT` repository secret and restoring the `gaia` job in `.github/workflows/ci.yml`. Local coverage via the pre-push hook and the Cursor session-start hook is adequate in the interim.
- **SPA ↔ backend type sync** — 2026-04-21: `frontend/src/lib/types.ts` is hand-written to mirror `superbrain.core.models`. Swap to `openapi-typescript http://localhost:8000/openapi.json -o src/lib/api-types.ts` as soon as the Phase-6 FastAPI `/openapi.json` stabilises.
- **SPA bundle splitting** — 2026-04-21: Plotly drags `dist/assets/index-*.js` to ~2 MB unminified (~645 KB gzipped). Acceptable for a 3-user internal tool. If we ever route public traffic at it, lazy-load `src/components/plot.tsx` via `React.lazy` and drop Plotly from the initial chunk.
- **SPA value-bet and backtest screens** — 2026-04-21: ship phase 7 with empty-state UX against the Phase-6 stubs (`GET /bets/value` → `{items: []}`, `POST /backtest/run` → 501). Real wiring lands alongside the engine in phase 4b; the forms + sortable table are already in place.
- ~~**Phase 4a follow-ups** (2026-04-21, tracked for phase 4b):~~
  1. ~~**Golden regression corpus.**~~ **Deferred 2026-04-21 to a dedicated PR.** See *Golden regression corpus TODO (phase 4b, 2026-04-21)* for the adapter; blocked on the pandas↔Polars shape mismatch documented there.
  2. ~~**End-to-end backtest + integration + no-leakage tests.**~~ **Shipped 2026-04-21** as `tests/engine/test_pipeline.py` + `tests/engine/test_backtest.py` (see *Ablation and engine tests (phase 4b, 2026-04-21)*).
  3. ~~**Per-strategy bet unit tests.**~~ **Shipped 2026-04-21** as `tests/engine/test_bets.py` covering all 13 registered strategies.
- **Phase 4c follow-ups** (2026-04-21, newly opened by phase 4b):
  1. Golden regression corpus (see the TODO section cited above).
  2. API + SPA surface for ablation runs. Backend: `GET /ablation/runs?bet=...` streams `data/ablation_runs/<bet>/*.parquet` via DuckDB; `POST /ablation/studies` kicks off a backgrounded `FeatureAblationStudy.run(...)`. Frontend: drop the result table next to the backtest screen; no write path today because the Python class is the only entry point.
  3. Beam / genetic search extensions to `FeatureAblationStudy`. Hooks are documented in the class docstring; swap `_search` and use the `seed` attribute for your RNG.

---

<!-- The git history of this file is the changelog — no separate
section needed. Seeded from Gaia (https://github.com/frankpietro/gaia). -->
