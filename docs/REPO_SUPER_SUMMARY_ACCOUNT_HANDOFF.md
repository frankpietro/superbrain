# Superbrain — repository super-summary (account handoff)

**Generated:** 2026-04-29  
**Purpose:** One place to read what this repo is, what recent work and Cursor sessions focused on, and what matters next. The default Git branch is **`main`** (there is no `master`).

---

## 1. What this project is

**Superbrain** is an **AI-operated football value-betting platform** for three private owners. It replaces an older prototype (`fbref24`) with a single clean stack:

| Layer | What it does |
|--------|----------------|
| **Scrapers** | Continuous odds from Italian bookmakers (**Sisal, Goldbet, Eurobet**), every market they expose. Historical match and team stats for **top-5 European leagues** (2020–21 → present) from **football-data.co.uk**, **Understat** (xG), optional **soccerdata** (FBref, ClubElo). |
| **Lake** | **DuckDB** over **hive-partitioned Parquet** under `data/lake/` (local; Fly.io volume in prod). One authoritative place for matches, odds, team match stats, scrape runs, etc. |
| **Engine** | **Bet-agnostic value engine**: clustering + similarity + probability + **13 registered bet strategies** (1X2, O/U, corners, cards, shots, etc.). Ported in a behaviour-preserving way from the old repo; locked with **golden regression** tests. |
| **Backtest & ablation** | Sliding-window backtest; **FeatureAblationStudy** (greedy feature search) with parquet outputs under `data/ablation_runs/`. |
| **API** | **FastAPI** on **Fly.io** (Hobby): REST + in-process **APScheduler** (scrapers + historical backfill) + **Telegram/email alerts** for high-edge bets. |
| **Frontend** | **Vite + React + TypeScript + Tailwind + shadcn-style UI + TanStack Router/Query + zustand + react-plotly.js** on **Vercel**. **No authentication** since 2026-04-21 — URL obscurity only; revisit if exposure grows. |
| **CI** | **GitHub Actions**: tests, lint, frontend build, scheduled scrapes as fallback when Fly is down. |

**How the human fits in:** Owners open the SPA and review **PRs**; the **agent** is expected to run git, tests, and deploy steps (see `AGENTS.md`, seeded from **Gaia**). Project-specific truth lives in **`docs/knowledge.md`**.

**Money / scope:** Personal tool, no monetisation, three users.

---

## 2. Repository layout (high level)

- `src/superbrain/core/` — domain types, markets, team canonicalisation.  
- `src/superbrain/data/` — `Lake`, migrations, Parquet I/O.  
- `src/superbrain/scrapers/` — `historical/` + `bookmakers/{sisal,goldbet,eurobet}/`.  
- `src/superbrain/engine/` — pipeline, bets registry, backtest.  
- `src/superbrain/ablation/` — feature ablation studies.  
- `src/superbrain/alerts/` — Telegram + email dispatch, dedup.  
- `src/superbrain/api/` — FastAPI app, routers (bets, matches, odds, backtest, trends, data, scrapers, …).  
- `src/superbrain/scheduler/` — APScheduler jobs and `--run-once` for Actions.  
- `frontend/` — SPA (routes under `frontend/src/routes/`).  
- `docs/brief.md` — immutable product seed; **`docs/knowledge.md`** — living decisions.  
- `deploy/` — Fly/Vercel configs.  
- `.gaia/` — Gaia seed, hooks reference, outbox.

---

## 3. What the “latest chats” (Cursor sessions) have been about

This section is inferred from **local agent transcript files** under the Cursor project (filenames are opaque UUIDs; content is the source of truth). Themes cluster around **late April 2026** work on this repo.

### 3.1 Repository hygiene and GitHub

- **Merging open PRs** and **cleaning worktrees**: e.g. squash-merging **PR #30** (remove bearer auth end-to-end) and **PR #31** (wire `GET /bets/value` to the real engine), including **resolving rebase conflicts** after #30 landed (imports and `require_auth` removal in `bets` router and tests).  
- **Pruning** extra worktree directories, stale local/remote branches, and getting to a **single clean `main`** with CI green.

### 3.2 Authentication removal and confusion on localhost

- User saw **“missing or malformed bearer token”** on the dashboard while the codebase had already dropped auth.  
- Diagnosis in-session: a **stale `uvicorn` process** was still running **pre-merge** code; the frontend sent no `Authorization` header, so the old API returned 401. Fix: **restart the API** from current `main`, kill orphan Vite processes tied to deleted worktrees.  
- **Product direction:** no bearer tokens; if auth returns, it will be a new design.

### 3.3 Data visibility, past fixtures, and performance

- **Request:** “Past fixtures” missing / need to **scrape and visualise** what is in the DB — a **tab with stats** (rows per year/league, columns, samples).  
- **Shipped in repo:** **Phase 11 — Data tab** (`/data`, `GET /data/overview`) with per-table row counts, partition breakdowns, schema and sample rows; **historical backfill** via `scripts/backfill_historical.py` (scheduler alone does not populate historical matches/stats).  
- **Deep performance analysis** (same period): **`GET /bets/value`** was profiled as extremely expensive when the lake had real stats because **`build_engine_context` / clustering ran per fixture** in a loop, dominating wall time; dashboard and value-bet pages call this endpoint. Documented **fixes for later**: compute/cache context **once per request** (e.g. per cutoff date), in-process TTL cache, or **remove eager fetch from dashboard** / lazy “compute value bets”. Optional: persist clustered context to disk. Secondary: **frontend code-splitting** (Plotly and routes), **`_read_team_match_stats` memoisation**.

### 3.4 Misc engineering themes from the same window

- **Radix** multi-select: **dropdown** should stay open between checkbox toggles (`preventDefault` on `onSelect`); see knowledge gotcha and PR #34.  
- **Sisal / Goldbet** scraping quirks: User-Agent, Akamai, timeouts, Goldbet long runs → **30 min job timeout** on scheduler.

---

## 4. Most relevant features and directions for the future

These are **prioritised** by impact on the product narrative (data → model → UX → ops). Details and nuance: **`docs/knowledge.md`**, especially **Deferred / open** and per-phase sections.

### 4.1 Performance and correctness of value bets (high impact)

- **`/bets/value` request path:** Avoid **O(fixtures) × full re-cluster** behaviour; batch by cutoff date, cache, or decouple the **dashboard** from a heavy first paint.  
- **`_read_team_match_stats`:** Scan/memoise once per request where possible.  
- **Fixture upsert:** **Newer-data-wins** for `matches` when odds-promoted placeholders should be **overwritten** by historical backfill (tracked in Deferred — placeholders can block final scores from appearing).

### 4.2 Ablation and analytics in the product

- **Ablation API + SPA:** Backend pieces exist (parquet under `data/ablation_runs/`); **full HTTP + UI** for listing runs and kicking off studies is still a natural next step (phase-4c follow-ups in knowledge).  
- **Backtest:** Sync JSON is done; **SSE** for long runs, **persisted backtest history**, **Plotly ROI/drawdown** on results are listed as non-blocking improvements.

### 4.3 Data, lake, and infrastructure choices

- **Authoritative lake:** Whether **Fly volume** stays primary vs **object storage (e.g. R2)** — open decision.  
- **Market taxonomy:** How bookmaker-specific lines map to shared `market_code` over time.  
- **Optional ML:** **Supervised layer** on top of similarity — explicitly deferred.  
- **CI Gaia `doctor`:** Re-enable with **`GAIA_READ_PAT`** if private Gaia access is needed in CI; currently local hooks only.

### 4.4 Developer experience and types

- **OpenAPI → TypeScript:** Replace hand-written `frontend/src/lib/types.ts` with **`openapi-typescript`** once `/openapi.json` is stable.  
- **SPA bundle:** Lazy-load Plotly / routes if the app ever faces **public** traffic; internal 3-user scope tolerates a large main chunk today.

### 4.5 Alerts and operations

- **Telegram/email** are opt-in via env. Tuning threshold, dedup window, and anti-spam caps is documented in knowledge.  
- **Telephony of scrapers:** Staggered 15 min jobs, **Goldbet** ~20+ min wall time — ops must keep **timeout and overlap** (max instances) consistent.

### 4.6 Testing and quality

- **Engine:** Golden JSON regression is in place; keep regenerating when behaviour changes intentionally.  
- **pytest-asyncio** warning filter in `pyproject.toml` — revert when upstream fixes the leak (documented in knowledge).

---

## 5. How to get oriented in the codebase (practical)

1. Read **`README.md`** then **`docs/knowledge.md`** (Index → sections you need).  
2. **Run API:** `uv run uvicorn superbrain.api.main:app --host 127.0.0.1 --port 8100` (or project default in docs).  
3. **Run SPA:** `cd frontend && npm run dev` — **`frontend/.env.local`** with `VITE_API_BASE_URL`.  
4. **Backfill historical data** (if the lake is empty of matches/stats): `scripts/backfill_historical.py` with documented `--sources`.  
5. **Inspect the lake** without a REPL: open **`/data`** in the SPA with the API running.

---

## 6. Recent `main` history (snapshot)

As of the handoff update, `git log` shows work such as: **Data tab + `/data/overview` (#32)**, **Gaia bumps (#33)**, **dropdown fix (#34)**, **scraper API call fix** (`fix: api call for scraper`), and earlier **auth removal (#30)**, **value bets wiring (#31)**, **backtest API (#24)**, **trends (#26)**, **recent-bets + scrapers preview (#27)**, **matches redesign (#25)**, **fixture promotion from odds (#22)**, **scheduler/phase-5/8/9** features, **engine 4b/4c**, **SPA phase 7**.  
Use `git log --oneline` on `main` for the live list.

---

## 7. One-line reminder

**Superbrain = scrape odds + backfill history → Parquet lake → value-bet engine + backtest/ablation → FastAPI + scheduled jobs + alerts → React SPA for three owners, AI-maintained, documented in `docs/knowledge.md`.**

---

*This file is a handoff aid only; authoritative architecture and decisions remain in `docs/knowledge.md` and `AGENTS.md`.*
