# Eurobet prematch scraper

Production scraper for Eurobet's hidden prematch-odds JSON APIs.
Lands one `OddsSnapshot` row per (market, selection, threshold,
half, …) for every event in the top-5 European leagues.

Spike-era discovery doc: see
`docs/spike/eurobet/README.md` (phase 3 spike) for the full endpoint
catalog, payload dumps, and the Cloudflare archaeology that led here.
This file is the *operational* reference.

## Architecture

```
scrape()  ──►  EurobetClient  ──►  discover_events  ──►  parse_event_markets  ──►  Lake.ingest_odds
(scraper.py)   (client.py)        (navigation.py)       (markets.py)              (data/connection.py)
```

- **`client.py`** — dual-transport async client. Plain `httpx` for the
  public navigation endpoints; `curl_cffi` with
  `impersonate="chrome124"` for the Cloudflare-gated
  `/detail-service/...` per-event market calls. Centralizes default
  headers, a shared ≤ 1 req/s rate limiter, and `tenacity` retry-with-
  jitter. Raises `EurobetError` on unrecoverable failures.
- **`navigation.py`** — event discovery. Fuses the homepage
  `top-disciplines` carousel (cheap, always available) with the
  authoritative per-meeting `detail-service/meeting` blob (Cloudflare-
  gated but complete), deduping on `(programCode, eventCode)`. Handles
  the spike's observed quirk that `top-disciplines` occasionally skips
  a top-5 league on a given day.
- **`markets.py`** — pure function `parse_event_markets(payload,
  league, captured_at, run_id) -> (list[OddsSnapshot], Counter)`. Never
  raises; unmapped Eurobet markets are logged once and counted.
- **`scraper.py`** — orchestrator. Discovers events per league, fetches
  per-event markets under a bounded `asyncio.Semaphore(3)`, and writes
  to the lake + `scrape_runs`. Always returns a valid
  `EurobetScrapeResult`.
- **`__init__.py`** — re-exports the public entry points.

## Cloudflare / `curl_cffi` dependency

Eurobet routes `www.eurobet.it` through Cloudflare with Bot Fight Mode
on. The public navigation endpoints
(`prematch-homepage-service`, `prematch-menu-service`,
`_next/data/...`) pass Cloudflare cleanly with plain `httpx`. The
per-event `detail-service/.../event/...` calls, however, are rejected
with HTTP 403 `cf-mitigated: challenge` unless the TLS / JA3
fingerprint matches a modern browser.

The scraper uses **`curl_cffi` with `impersonate="chrome124"`** for
every `detail-service` call. This is a pure TLS / JA3 impersonation —
no Playwright, no cookie relay. The `curl_cffi` dep is pinned in
`pyproject.toml`; it pulls a vendored libcurl-impersonate and is
`asyncio`-friendly via `curl_cffi.requests.AsyncSession`.

On top of the TLS fingerprint, two tenant headers are mandatory on
every `detail-service` request:

- `X-EB-MarketId: IT`
- `X-EB-PlatformId: WEB`

Without them the Spring backend returns a 404 (without `X-EB-MarketId`)
or a validation error (without `X-EB-PlatformId`). Both are set as
defaults on the `curl_cffi` session.

## Endpoints used

All `GET`, all unauthenticated, all JSON. Base URL:
`https://www.eurobet.it`.

| Method on `EurobetClient`                       | Transport       | Endpoint |
|-------------------------------------------------|-----------------|----------|
| `fetch_top_disciplines(discipline_alias)`       | `httpx`         | `/prematch-homepage-service/api/v2/sport-schedule/services/top-disciplines/1/{discipline_alias}` |
| `fetch_sport_list(discipline_alias)`            | `httpx`         | `/prematch-menu-service/api/v2/sport-schedule/services/sport-list/{discipline_alias}` |
| `fetch_meeting(discipline_alias, meeting_slug)` | `curl_cffi`     | `/detail-service/sport-schedule/services/meeting/{discipline_alias}/{meeting_slug}?prematch=1&live=0` |
| `fetch_event_markets(..., group_alias=None)`    | `curl_cffi`     | `/detail-service/sport-schedule/services/event/{discipline_alias}/{meeting_slug}/{event_slug}[/{group_alias}]?prematch=1&live=0` |

Top-5 league meeting codes (all `disciplineAlias = calcio`,
`meetingCode` = the integer Eurobet uses internally):

| League         | `meetingCode` | `meeting_slug`       |
|----------------|---------------|----------------------|
| Serie A        | `21`          | `it-serie-a`         |
| Premier League | `86`          | `ing-premier-league` |
| Bundesliga     | `4`           | `de-bundesliga`      |
| La Liga        | `79`          | `es-liga`            |
| Ligue 1        | `14`          | `fr-ligue-1`         |

Live discovery: the spike initially used `gb-premier-league`; Eurobet
actually serves the English league under `ing-premier-league`
(verified against the live `sport-list` tree 2026-04-21).

## Market coverage

The parser maps Eurobet's numeric `betId` onto the canonical
`superbrain.core.markets.Market` enum via a dispatch table
(`_FAMILY_BY_BET_ID` → `_EMITTER_BY_FAMILY` in `markets.py`). The
following families are covered for every event that prices them:

| Market family           | Eurobet `betId`s (non-exhaustive)                          |
|-------------------------|------------------------------------------------------------|
| 1X2 (full match)        | `24`                                                       |
| 1X2 per half            | `363` (1st half), `377` (2nd half)                         |
| 1X2 handicap            | `53`                                                       |
| Double chance           | `1555`                                                     |
| Goals over/under        | `4243`                                                     |
| Both teams to score     | `1550`                                                     |
| Multigoal               | `97` (full), `407` (home), `430` (away)                    |
| Goals per team (Y/N)    | `392` (home), `415` (away)                                 |
| Exact score             | `51`, `5458`, `5474` (XL variants)                         |
| Half-time / Full-time   | `74`                                                       |
| Corner 1X2              | `455`                                                      |
| Corners over/under      | `1971`                                                     |
| Cards over/under        | `2043`                                                     |

"SCOMMESSE TOP" compound groups (`betId` 1549 / 6754) are walked via a
sub-dispatcher that fans out to the families above.

Everything else lands in `EurobetScrapeResult.unmapped_markets` and is
logged once at `INFO` (first occurrence of each distinct
`betDescription` per run). The spike catalog lists markets Eurobet
publishes only on match-day (corners / cards / shots compound groups
and scorer markets); the scraper consumes them when present but does
not yet emit every one of them — see
`docs/knowledge.md` → *Eurobet scraper (phase 3, 2026-04-21)*.

## Operational knobs

All knobs live on `EurobetClient` and `scrape()`:

| Knob                                   | Default            | Rationale                                                     |
|----------------------------------------|--------------------|---------------------------------------------------------------|
| `EurobetClient.timeout`                | 30 s               | `/tutte` per-event payloads can exceed 2 MB.                  |
| `EurobetClient.max_attempts`           | 3                  | Exponential-jitter backoff on 429/5xx/network.                |
| `EurobetClient.min_interval_s`         | 1.0 s (global)     | Matches the spike's "≤ 1 req/s" empirical budget.             |
| `scrape(event_concurrency=...)`        | 3                  | In-flight `detail-service/event` calls.                       |
| `scrape(group_alias=...)`              | `None`             | Pass `"tutte"` for the exhaustive per-event dump.             |

Retries fire on `httpx.TimeoutException`, `httpx.TransportError`,
`curl_cffi` connection / timeout errors, and HTTP `429 / 502 / 503 /
504`. 4xx responses other than 429 fail fast — those are our bug, not
a transient one.

## Contracts (what `scrape()` promises)

- **Never raises.** All failures (meeting fetch, event discovery,
  per-event markets, parser, ingest) are caught and recorded on
  `EurobetScrapeResult.errors`. Status is `success`, `partial`
  (something failed but we still landed rows) or `failed` (nothing
  landed).
- **Idempotent.** `Lake.ingest_odds` dedupes on
  `OddsSnapshot.natural_key` — re-running the same `run_id` against
  the same `captured_at` yields `rows_written = 0`.
- **Observable.** Every run writes a row to `scrape_runs` with the
  run id, status, row counts, and a truncated error message.
- **Forensic.** Each `OddsSnapshot` carries `raw_json` (the trimmed
  bytes of the Eurobet `oddList` payload) for after-the-fact
  debugging.

## Live smoke test

```
SUPERBRAIN_LIVE_TESTS=1 uv run pytest \
  tests/scrapers/bookmakers/eurobet/test_live.py -q
```

This hits the real Eurobet stack (Serie A only, ~10 events, 100 KB –
2 MB per event). Gated so CI and day-to-day `pytest -q` don't ping
Cloudflare.

## Reproduce a single-event scrape

```python
import asyncio
from pathlib import Path
from superbrain.core.models import League
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.eurobet import scrape

async def main() -> None:
    lake = Lake(root=Path("data/lake"))
    lake.ensure_schema()
    result = await scrape(lake, leagues=[League.SERIE_A])
    print(result.run_id, result.rows_written, result.status)
    for market, count in result.per_market_rows.most_common():
        print(f"  {market:<30} {count}")
    if result.unmapped_markets:
        print("unmapped:", result.unmapped_markets.most_common(10))

asyncio.run(main())
```
