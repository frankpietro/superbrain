"""Understat fetcher (pure ``httpx``; internal AJAX JSON endpoint).

Understat renders its public pages as a thin HTML shell (~18 KB) plus an
AJAX call to ``https://understat.com/getLeagueData/<slug>/<year>``, which
returns the full league payload (teams, players, dates) as JSON. Hitting
that endpoint directly bypasses the HTML shell, avoids the brittle
"embedded JavaScript regex" approach used in earlier Understat scrapers,
and makes the whole source mockable with plain ``respx``.

The endpoint requires an ``X-Requested-With: XMLHttpRequest`` header,
matching the same convention the ``understatapi`` PyPI wrapper uses.

We keep the pure-httpx approach (rather than adding ``understatapi`` as a
dependency) because (per the phase-2 spike) that library pins ancient
``urllib3`` / ``idna`` versions that downgrade the rest of the
dependency tree.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final, cast

import httpx
import polars as pl

from superbrain.core.models import League

logger = logging.getLogger(__name__)

AJAX_URL: Final[str] = "https://understat.com/getLeagueData/{slug}/{season_start}"
AJAX_HEADERS: Final[dict[str, str]] = {"X-Requested-With": "XMLHttpRequest"}

LEAGUE_SLUGS: Final[dict[League, str]] = {
    League.SERIE_A: "Serie_A",
    League.PREMIER_LEAGUE: "EPL",
    League.LA_LIGA: "La_liga",
    League.BUNDESLIGA: "Bundesliga",
    League.LIGUE_1: "Ligue_1",
}


def season_start_year(season: str) -> str:
    """Convert ``"2023-24"`` to Understat's ``"2023"``.

    :param season: canonical season code
    :return: four-digit starting year as string
    """
    if len(season) != 7 or season[4] != "-":
        raise ValueError(f"expected YYYY-YY, got {season!r}")
    return season[:4]


def build_url(league: League, season: str) -> str:
    """Build the Understat AJAX URL for a league-season.

    :param league: league enum
    :param season: canonical season code
    :return: full HTTPS URL
    """
    return AJAX_URL.format(slug=LEAGUE_SLUGS[league], season_start=season_start_year(season))


async def fetch_league_season(
    league: League,
    season: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> pl.DataFrame:
    """Fetch the Understat match list for a league-season.

    Returns an empty, schema-compatible frame when the endpoint 404s;
    raises on other HTTP errors.

    :param league: league enum
    :param season: canonical season code
    :param client: optional reusable async client
    :param timeout: per-request timeout
    :return: polars frame, one row per match
    """
    url = build_url(league, season)
    ua = {"User-Agent": "superbrain/0.2 (+historical-backfill)"}
    owned_client = client is None
    if client is None:
        client = httpx.AsyncClient(headers=ua, timeout=timeout)
    try:
        resp = await client.get(url, headers={**ua, **AJAX_HEADERS})
    finally:
        if owned_client:
            await client.aclose()

    if resp.status_code == 404:
        logger.warning("understat: %s %s not found (404)", league.value, season)
        return _empty_frame(league, season)
    resp.raise_for_status()

    return parse_payload(resp.text, league=league, season=season)


def parse_payload(raw: str, *, league: League, season: str) -> pl.DataFrame:
    """Parse an Understat AJAX JSON payload into a normalized frame.

    Accepts either the full league payload (``{"teams": ..., "players": ...,
    "dates": [...]}``) or a bare list of matches.

    :param raw: JSON text as returned by the AJAX endpoint
    :param league: league enum
    :param season: canonical season code
    :return: polars frame, one row per match (empty when the payload has no
        matches)
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("understat: JSON parse failed for %s %s: %s", league.value, season, exc)
        return _empty_frame(league, season)

    if isinstance(parsed, dict):
        matches = cast(list[dict[str, Any]], parsed.get("dates") or [])
    elif isinstance(parsed, list):
        matches = cast(list[dict[str, Any]], parsed)
    else:
        matches = []

    rows = [_match_row(m) for m in matches if isinstance(m, dict)]
    if not rows:
        return _empty_frame(league, season)

    df = pl.DataFrame(rows)
    df = df.with_columns(
        pl.col("datetime").str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S", strict=False)
    ).with_columns(pl.col("datetime").dt.date().alias("match_date"))
    df = df.with_columns(
        pl.lit("understat").alias("source"),
        pl.lit(league.value).alias("league"),
        pl.lit(season).alias("season"),
    )
    return df


def _match_row(m: dict[str, Any]) -> dict[str, Any]:
    home = m.get("h") or {}
    away = m.get("a") or {}
    goals = m.get("goals") or {}
    xg = m.get("xG") or {}
    forecast = m.get("forecast") or {}
    return {
        "understat_match_id": str(m.get("id") or ""),
        "is_result": bool(m.get("isResult")),
        "datetime": m.get("datetime"),
        "home_team_raw": home.get("title"),
        "away_team_raw": away.get("title"),
        "home_goals": _int_or_none(goals.get("h")),
        "away_goals": _int_or_none(goals.get("a")),
        "home_xg": _float_or_none(xg.get("h")),
        "away_xg": _float_or_none(xg.get("a")),
        "forecast_home": _float_or_none(forecast.get("w")),
        "forecast_draw": _float_or_none(forecast.get("d")),
        "forecast_away": _float_or_none(forecast.get("l")),
    }


def _int_or_none(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _empty_frame(league: League, season: str) -> pl.DataFrame:
    df = pl.DataFrame(
        {
            "understat_match_id": pl.Series([], dtype=pl.String),
            "is_result": pl.Series([], dtype=pl.Boolean),
            "match_date": pl.Series([], dtype=pl.Date),
            "home_team_raw": pl.Series([], dtype=pl.String),
            "away_team_raw": pl.Series([], dtype=pl.String),
            "home_goals": pl.Series([], dtype=pl.Int64),
            "away_goals": pl.Series([], dtype=pl.Int64),
            "home_xg": pl.Series([], dtype=pl.Float64),
            "away_xg": pl.Series([], dtype=pl.Float64),
            "forecast_home": pl.Series([], dtype=pl.Float64),
            "forecast_draw": pl.Series([], dtype=pl.Float64),
            "forecast_away": pl.Series([], dtype=pl.Float64),
        }
    )
    return df.with_columns(
        pl.lit("understat").alias("source"),
        pl.lit(league.value).alias("league"),
        pl.lit(season).alias("season"),
    )
