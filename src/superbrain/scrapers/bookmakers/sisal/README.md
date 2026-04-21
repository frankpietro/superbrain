# Sisal prematch scraper

Production scraper for the Sisal hidden prematch-odds JSON API. Lands
one `OddsSnapshot` row per (market, selection, threshold, half, …) for
every event in the top-5 European leagues.

Spike-era discovery doc: see `docs/spike/sisal/README.md` in the
repo root for the full endpoint catalog, payload dumps and the API
archaeology that led here. This file is the *operational* reference.

## Architecture

```
scrape()  ──►  SisalClient   ──►  parse_event_markets  ──►  Lake.ingest_odds
 (scraper.py)  (client.py)       (markets.py)             (data/connection.py)
```

- **`client.py`** — thin async `httpx` wrapper. Centralizes default
  headers, per-endpoint rate limiting, and retry-with-jitter. Raises
  `SisalError` on unrecoverable failures.
- **`markets.py`** — pure function `parse_event_markets(payload,
  league, captured_at, run_id) -> (list[OddsSnapshot], Counter)`.
  Never raises; unknown or malformed markets are logged and counted.
- **`scraper.py`** — orchestrator. Fetches the tree (cached 1 h),
  the events per league, then event markets under a bounded
  `asyncio.Semaphore`, and writes to the lake + `scrape_runs`.
- **`__init__.py`** — re-exports the public entry points.

## Endpoints used

All `GET`, all unauthenticated, all JSON. Base URL:
`https://betting.sisal.it/api/lettura-palinsesto-sport/palinsesto/prematch`.

| Method on `SisalClient`           | Endpoint                                                                       |
|-----------------------------------|--------------------------------------------------------------------------------|
| `fetch_tree()`                    | `alberaturaPrematch`                                                           |
| `fetch_events(competition_key)`   | `v1/schedaManifestazione/{timeFilter}/{competitionKey}?offerId=0&metaTplEnabled=true&deep=true` |
| `fetch_event_markets(event_key)`  | `schedaAvvenimento/{eventKey}?offerId=0`                                       |

Top-5 league keys (all `sportId = 1`, Calcio):

| League         | Key     |
|----------------|---------|
| Serie A        | `1-209` |
| Premier League | `1-331` |
| Bundesliga     | `1-228` |
| La Liga        | `1-570` |
| Ligue 1        | `1-781` |

## Market coverage

The parser maps Sisal's `descrizione` labels onto the canonical
`superbrain.core.markets.Market` enum via a dispatch table
(`_FAMILY_BY_DESCRIZIONE` → `_EMITTER_BY_FAMILY` in `markets.py`).
The following families are covered for every event:

| Market family           | Covered Sisal labels (non-exhaustive)                                                  |
|-------------------------|-----------------------------------------------------------------------------------------|
| 1X2 (full match)        | `1X2 FINALE`                                                                            |
| 1X2 per half            | `1X2 PRIMO TEMPO`, `1X2 SECONDO TEMPO`                                                  |
| Double chance           | `DOPPIA CHANCE`, `DOPPIA CHANCE 1T/2T`                                                  |
| Goals over/under        | `UNDER/OVER GOALS`, `U/O FINALE`, `U/O ASIATICO`, per-half variants                     |
| Both teams to score     | `GOAL/NOGOAL`, `GOL/NO GOL`, per-half variants                                          |
| Multigoal               | `MULTIGOAL`, `MULTIGOAL 1T/2T`, `MULTIGOAL CASA/OSPITE` (ranges incl. "5 O PIU'")       |
| Goals per team (U/O)    | `U/O SQUADRA 1`, `U/O SQUADRA 2`                                                        |
| Exact score             | `RISULTATO ESATTO` (full match)                                                         |
| Half-time / Full-time   | `PARZIALE / FINALE`                                                                     |
| Corner 1X2              | `1X2 CORNER`, `1 TEMPO: 1X2 CORNER`                                                     |
| Corner handicap         | `1X2 HANDICAP CORNER`, `1 TEMPO: 1X2 HANDICAP CORNER`                                   |
| Halves over/under       | `U/O 1T`, `U/O 2T`                                                                      |
| Combo 1X2 + over/under  | `1X2 + U/O`, `COMBO 1X2 U/O`                                                            |
| Combo BTTS + over/under | `G/NG + U/O`, `COMBO GOAL U/O`                                                          |

Everything else is counted in `SisalScrapeResult.unmapped_markets` and
logged once at `INFO` (first occurrence of each distinct label per
run). See the spike README → *Known missing markets* for the list of
markets Sisal simply does not publish (prematch cards, shots, corner
totals, corner per team).

## Operational knobs

All knobs live on `SisalClient` and `scrape()`:

| Knob                                      | Default            | Rationale                                             |
|-------------------------------------------|--------------------|-------------------------------------------------------|
| `SisalClient.timeout`                     | 30 s               | Event-markets payloads are ~2 MB.                     |
| `SisalClient.max_attempts`                | 3                  | Exponential-jitter backoff on 429/5xx/network.        |
| `SisalClient.min_interval_s`              | 1 s per endpoint   | Match the spike's "≤ 1 req/s" empirical budget.       |
| `SisalClient.endpoint_concurrency`        | 1 per endpoint     | Per-endpoint semaphore; tree/events/markets separate. |
| `scrape(event_concurrency=...)`           | 4                  | In-flight `schedaAvvenimento` calls.                  |
| `scrape(tree_ttl_s=...)`                  | 3600 s             | `alberaturaPrematch` barely changes day-to-day.       |

Retries fire on `httpx.TimeoutException`, `httpx.TransportError`, and
HTTP `429 / 502 / 503 / 504`. 4xx responses other than 429 fail fast —
those are our bug, not a transient one.

## Contracts (what `scrape()` promises)

- **Never raises.** All failures (tree, per-league events, per-event
  markets, parser, ingest) are caught and recorded on
  `SisalScrapeResult.errors`. Status is `success`, `partial`
  (something failed but we still landed rows) or `failed`
  (nothing landed).
- **Idempotent.** `Lake.ingest_odds` dedupes on
  `OddsSnapshot.natural_key` — re-running the same run id against
  the same `captured_at` yields `rows_written = 0`.
- **Observable.** Every run writes a row to `scrape_runs` with the
  run id, status, row counts, and a truncated error message.
- **Forensic.** Each `OddsSnapshot` carries `raw_json` (the trimmed
  bytes of the esito payload) for after-the-fact debugging.

## Live smoke test

```
SUPERBRAIN_LIVE_TESTS=1 uv run pytest tests/scrapers/bookmakers/sisal/test_live.py -q
```

This hits the real API (Serie A only, ~10 events, ~2 MB per event).
Gated so CI and day-to-day `pytest -q` don't ping Sisal.

## Reproduce a single-event scrape

```python
import asyncio
from pathlib import Path
from superbrain.core.models import League
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.sisal import scrape

async def main() -> None:
    lake = Lake(root=Path("data/lake"))
    lake.ensure_schema()
    result = await scrape(lake, leagues=[League.SERIE_A])
    print(result.run_id, result.rows_written, result.status)
    for market, count in result.per_market_rows.most_common():
        print(f"  {market:<30} {count}")

asyncio.run(main())
```
