# Goldbet scraper

Production scraper for Goldbet's hidden JSON API at
`https://www.goldbet.it/api/sport/...`. Fetches live prematch odds for
the top-5 European leagues across every market family the API exposes
and ingests validated `OddsSnapshot` rows into the Parquet lake via
`superbrain.data.connection.Lake.ingest_odds`.

Entry point: `superbrain.scrapers.bookmakers.goldbet.scrape`.

```python
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.goldbet import scrape

lake = Lake(root=...)
lake.ensure_schema()
report = await scrape(lake, leagues=None)  # None → all top-5 leagues
```

---

## Bootstrap — `curl_cffi`

Goldbet is fronted by Akamai Bot Manager with JA3 / TLS fingerprinting.
A vanilla `httpx.AsyncClient` gets `HTTP 403 Access Denied` at the edge
because the default Python TLS ClientHello does not match Chrome's.

The production scraper uses **`curl_cffi` with `impersonate="chrome124"`**.
A one-shot GET against the football landing page
(`https://www.goldbet.it/scommesse/sport/calcio/`) seeds the Akamai
cookies (`_abck`, `bm_sz`, `ak_bmsc`) into the session jar; every
subsequent JSON call works with plain headers. A `403` anywhere
downstream triggers a single in-flight cookie refresh before retries
give up.

Playwright was evaluated in a 20-minute time-box and rejected:
`curl_cffi` alone clears the edge today, which removes the need for a
real Chromium binary, a `playwright install chromium` step, and the
~300 MB download.

If Akamai tightens the gate later and `curl_cffi` stops working, swap
the bootstrap inside `client._warmup_cookies` for a Playwright session
that extracts cookies once and hands them to the `AsyncSession`. The
rest of the scraper stays unchanged.

### Required headers

Every JSON request must carry:

```
X-Brand:         1
X-IdCanale:      1
X-AcceptConsent: false
X-Verticale:     1
Accept:          application/json, text/plain, */*
Content-Type:    application/json
```

Omitting any of the four `X-*` headers produces `HTTP 403` even with
valid Akamai cookies. The client sets them on every request.

### Refresh cadence

`_abck` in the spike carried a `~-1~-1~-1` TTL suggesting per-session
validity. The production scraper does **not** pre-schedule a refresh;
it relies on reactive refresh on the first `403`. In long-running
processes (APScheduler inside the Fly.io backend) each scrape opens a
new `AsyncSession` + warmup, so cookie staleness is bounded by the
scrape frequency.

---

## Endpoint catalog (inherited from the spike)

All paths are under `https://www.goldbet.it`.

| Purpose | Method + path | Notes |
|---|---|---|
| Tournament listing | `GET /api/sport/pregame/getOverviewEventsAams/0/1/0/{idTournament}/0/0/0` | Returns up to ~10 events per matchweek for one league. The event dict carries `ei`, `pi` (AAMS id), `ti`, `tai`, `en` (`"Home - Away"`), `ed` (`"dd-mm-YYYY HH:MM"`), plus a main-tab `mmkW` with Principali odds. |
| Event detail | `GET /api/sport/pregame/getDetailsEventAams/{tai}/{ti}/{pi}/{ei}/{macroTab}/0` | `macroTab=0` → Principali tab with odds + full `lmtW` tree. Other `macroTab` values: see below. |
| Event detail (non-AAMS) | `GET /api/sport/pregame/getDetailsEvent/{ti}/{ei}/{macroTab}` | Byte-identical payload. |
| Supporting | `GET /api/sport/pregame/getTopTournaments/`, `GET /api/sport/pregame/getProgram/` | Discovery only; not used at runtime. |

### Discovery beyond the spike (2026-04-21)

The spike concluded `macroTab` only returned odds for `0`. **That was
too conservative.** Empirical probing during this phase's
time-box found that passing each tab's `tbI` (4-digit tab-block id,
e.g. `3500` for *Angoli* or `3491` for *Multigol*) as `macroTab`
**also** returns odds-bearing markets for that tab. Arbitrary integers
that aren't a real `tbI` return a tree-only payload with
`success: false`.

The production scraper exploits this: for every event it fetches
`macroTab=0` once (which yields Principali markets plus the tree under
`lmtW`), then iterates every `tbI` in the tree and fetches its odds.
This lifts the per-event market count from ~19 (Principali only) to
roughly 200+ (Principali + Handicap + U/O variants + Ris.Esatto +
Multigol + Casa / Ospite team totals + Angoli + Sanzioni + Speciali
tabs).

### Tournament ID map

| League | `id_tournament` | `id_aams_tournament` |
|---|---|---|
| Serie A        | 93    | 21 |
| Premier League | 26604 | 86 |
| La Liga        | 95    | 79 |
| Bundesliga     | 84    | 4  |
| Ligue 1        | 86    | 14 |

Hard-coded in `client.TOP5_TOURNAMENTS`. If Goldbet ever renumbers,
`GET /api/sport/pregame/getProgram/` enumerates the full tree.

---

## Market coverage

The parser dispatches on the `mn` (market name) string inside each
`mmkW` block. Mapped market families:

| Goldbet `mn` | `Market` enum | Params | Selections |
|---|---|---|---|
| `1X2` | `MATCH_1X2` | — | `1` / `X` / `2` |
| `DC` | `MATCH_DOUBLE_CHANCE` | — | `1X` / `12` / `X2` |
| `U/O` | `GOALS_OVER_UNDER` | `threshold` | `OVER` / `UNDER` |
| `U/O 1T` / `U/O 2T` | `HALVES_OVER_UNDER` | `half`, `threshold` | `OVER` / `UNDER` |
| `GG/NG` | `GOALS_BOTH_TEAMS` | — | `YES` / `NO` |
| `U/O Casa`, `U/O Ospite` | `GOALS_TEAM` | `team`, `threshold` | `OVER` / `UNDER` |
| `1X2 + U/O` | `COMBO_1X2_OVER_UNDER` | `result_1x2`, `threshold` | `OVER` / `UNDER` |
| `GG/NG + U/O` | `COMBO_BTTS_OVER_UNDER` | `bet_btts`, `threshold` | `OVER` / `UNDER` |
| `Ris.Esatto …` | `SCORE_EXACT` | `home`, `away` | `H:A` literal |
| `Esito 1T/Finale` | `SCORE_HT_FT` | `ht`, `ft` | `HT/FT` literal |
| `U/O Angoli`, `U/O Angoli 1T` | `CORNER_TOTAL` | `threshold` | `OVER` / `UNDER` |
| `Multigol` (full-match) | `MULTIGOL` | `lower`, `upper` | `lower-upper` literal |
| `MultiGol Casa`, `MultiGol Ospite` | `MULTIGOL_TEAM` | `team`, `lower`, `upper` | `lower-upper` |

Markets that Goldbet exposes but don't map cleanly onto the shared
`Market` enum (half-time 1X2, parity P/D, handicap 1X2 H, bucketed
totals, VAR / penalty / card-coach specials, 1X2-plus-BTTS combos) are
listed in `markets._EXPLICIT_SKIP` — they are silently ignored so
run logs stay quiet. Any genuinely unknown `mn` gets one
`goldbet.unmapped_market` log entry per scrape run.

The contract is explicit: **missing markets never abort an event**,
missing events never abort a league, and any exception inside a tab
parse is caught and logged. The only thing that fails a scrape is an
inability to bootstrap the Akamai session, in which case the
`scrape_runs` row still lands with `status="failed"` and the raw
error message.

### Known product gaps

Confirmed in the spike (Napoli – Cremonese, Serie A matchweek):

- **Shots / Tiri in porta** — no tab surfaces shot markets for Serie A
  regular-season games. Open question whether Champions League and
  Premier League matches expose them. The parser is ready (`SHOTS_*`
  slots exist); data is simply absent.
- **Anytime / First goalscorers** — surfaced as a separate
  outright/antepost event under a different `idTournament` category.
  Not on the production scraper's path yet.
- **Team-specific cards O/U** — the *Sanzioni* tab only lists coach
  bookings, penalty markets, and VAR specials. No `U/O Cartellini`
  for Serie A.

---

## Rate limit & concurrency

- One HTTP request per second (token-bucket in `_RateLimiter`).
- `asyncio.Semaphore(3)` on per-event fetches in the orchestrator.
- Tenacity: 3 attempts, exponential backoff with jitter, retries on
  `429/502/503/504`; a `403` triggers a single cookie refresh and
  retries once.

Per-event cost: 1 Principali fetch + up to 25 tab fetches = ~26
requests. For ~50 events across the top 5 leagues → ~1,300 requests
per scrape, or roughly 20–25 minutes per full run.

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `GoldbetError: akamai warmup failed: HTTP 403` | `curl_cffi` fingerprint aged out or Akamai tightened. | Try a newer `impersonate` target (e.g. `chrome131`); failing that, port the Playwright fallback into `_warmup_cookies`. |
| Repeated `HTTP 429` | Rate limit too aggressive. | Increase `min_interval_seconds` in `get_session(...)`. |
| `goldbet.unmapped_market` flooding logs | Goldbet renamed an `mn`. | Add the exact string to `markets._EXPLICIT_SKIP` or a new handler. |
| `rows_written=0, rows_received>0` | Every row is a dedupe. | Expected on a re-run at the same `captured_at`; check `rows_skipped_duplicate`. |

---

## Tests

- `tests/scrapers/bookmakers/goldbet/test_client.py` — retries, 403
  refresh path, rate limiter, mandatory headers. Substitutes a small
  fake session for `curl_cffi.AsyncSession`.
- `tests/scrapers/bookmakers/goldbet/test_markets.py` — fixture-driven
  per-market-family assertions.
- `tests/scrapers/bookmakers/goldbet/test_scraper.py` — end-to-end via
  the fake session: ingest correctness, idempotency under a frozen
  clock, graceful failure on 500s.
- `tests/scrapers/bookmakers/goldbet/test_live.py` — gated on
  `SUPERBRAIN_LIVE_TESTS=1`; proves one real scrape lands rows.

Fixtures in `tests/fixtures/bookmakers/goldbet/` are trimmed excerpts
of spike payloads (all < 50 KB).
