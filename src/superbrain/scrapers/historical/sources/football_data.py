"""football-data.co.uk CSV fetcher.

One HTTPS GET per league-season yields a ~100 KB CSV containing every basic
stat the phase-1 algorithm needs (goals, shots, SoT, corners, fouls, cards,
HT scores) plus closing 1X2 odds for Bet365 and Pinnacle.

URL template: ``https://www.football-data.co.uk/mmz4281/<YYYY>/<league>.csv``
where ``<YYYY>`` is the two-digit packed season tag (``"2324"`` for 2023-24).
"""

from __future__ import annotations

import io
import logging
from typing import Final

import httpx
import polars as pl

from superbrain.core.models import League

logger = logging.getLogger(__name__)

BASE_URL: Final[str] = "https://www.football-data.co.uk/mmz4281/{season_tag}/{code}.csv"

LEAGUE_CODES: Final[dict[League, str]] = {
    League.SERIE_A: "I1",
    League.PREMIER_LEAGUE: "E0",
    League.LA_LIGA: "SP1",
    League.BUNDESLIGA: "D1",
    League.LIGUE_1: "F1",
}

COLUMN_MAP: Final[dict[str, str]] = {
    "Div": "division",
    "Date": "date_raw",
    "Time": "time",
    "HomeTeam": "home_team_raw",
    "AwayTeam": "away_team_raw",
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "FTR": "result",
    "HTHG": "ht_home_goals",
    "HTAG": "ht_away_goals",
    "HTR": "ht_result",
    "HS": "home_shots",
    "AS": "away_shots",
    "HST": "home_shots_on_target",
    "AST": "away_shots_on_target",
    "HF": "home_fouls",
    "AF": "away_fouls",
    "HC": "home_corners",
    "AC": "away_corners",
    "HY": "home_yellow_cards",
    "AY": "away_yellow_cards",
    "HR": "home_red_cards",
    "AR": "away_red_cards",
    "B365CH": "odds_b365_home_closing",
    "B365CD": "odds_b365_draw_closing",
    "B365CA": "odds_b365_away_closing",
    "PSCH": "odds_pinnacle_home_closing",
    "PSCD": "odds_pinnacle_draw_closing",
    "PSCA": "odds_pinnacle_away_closing",
}

INT_COLUMNS: Final[tuple[str, ...]] = (
    "home_goals",
    "away_goals",
    "ht_home_goals",
    "ht_away_goals",
    "home_shots",
    "away_shots",
    "home_shots_on_target",
    "away_shots_on_target",
    "home_fouls",
    "away_fouls",
    "home_corners",
    "away_corners",
    "home_yellow_cards",
    "away_yellow_cards",
    "home_red_cards",
    "away_red_cards",
)

FLOAT_COLUMNS: Final[tuple[str, ...]] = (
    "odds_b365_home_closing",
    "odds_b365_draw_closing",
    "odds_b365_away_closing",
    "odds_pinnacle_home_closing",
    "odds_pinnacle_draw_closing",
    "odds_pinnacle_away_closing",
)


def season_tag(season: str) -> str:
    """Convert ``"2023-24"`` to football-data's packed ``"2324"`` form.

    :param season: season in canonical ``YYYY-YY`` form
    :return: 4-digit packed season tag used in URLs
    """
    if len(season) != 7 or season[4] != "-":
        raise ValueError(f"expected YYYY-YY, got {season!r}")
    return f"{season[2:4]}{season[5:7]}"


def build_url(league: League, season: str) -> str:
    """Build the CSV URL for a league-season.

    :param league: league enum
    :param season: canonical season code
    :return: full HTTPS URL
    """
    return BASE_URL.format(season_tag=season_tag(season), code=LEAGUE_CODES[league])


async def fetch_league_season(
    league: League,
    season: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> pl.DataFrame:
    """Fetch one league-season CSV and return a normalized polars frame.

    Returns an empty frame (matching the canonical schema) when the CSV is
    missing (404) or empty. Every other HTTP error propagates.

    :param league: league enum
    :param season: canonical season code
    :param client: optional reusable async client
    :param timeout: per-request timeout
    :return: polars frame; columns renamed per :data:`COLUMN_MAP` plus
        ``source``, ``league``, ``season``
    """
    url = build_url(league, season)
    headers = {"User-Agent": "superbrain/0.2 (+historical-backfill)"}
    owned_client = client is None
    if client is None:
        client = httpx.AsyncClient(headers=headers, timeout=timeout)
    try:
        resp = await client.get(url)
    finally:
        if owned_client:
            await client.aclose()

    if resp.status_code == 404:
        logger.warning("football-data: %s %s not found (404)", league.value, season)
        return _empty_frame(league, season)
    resp.raise_for_status()

    content = resp.content
    if not content.strip():
        logger.warning("football-data: %s %s returned empty body", league.value, season)
        return _empty_frame(league, season)

    return parse_csv(content, league=league, season=season)


def parse_csv(content: bytes, *, league: League, season: str) -> pl.DataFrame:
    """Parse raw CSV bytes into the normalized frame shape.

    Kept separate from the fetcher so tests can feed fixture bytes without
    hitting the network.

    :param content: raw CSV bytes
    :param league: league this CSV belongs to
    :param season: canonical season code
    :return: normalized polars frame
    """
    try:
        df = pl.read_csv(
            io.BytesIO(content),
            try_parse_dates=False,
            ignore_errors=True,
            null_values=["", "NA"],
            truncate_ragged_lines=True,
        )
    except pl.exceptions.NoDataError:
        return _empty_frame(league, season)

    if df.height == 0:
        return _empty_frame(league, season)

    keep = [c for c in COLUMN_MAP if c in df.columns]
    df = df.select(keep).rename({k: COLUMN_MAP[k] for k in keep})

    if "home_team_raw" not in df.columns or "away_team_raw" not in df.columns:
        return _empty_frame(league, season)

    df = df.filter(pl.col("home_team_raw").is_not_null() & pl.col("away_team_raw").is_not_null())

    if "date_raw" in df.columns:
        df = df.with_columns(
            pl.col("date_raw")
            .str.strptime(pl.Date, format="%d/%m/%Y", strict=False)
            .alias("match_date")
        )
    else:
        df = df.with_columns(pl.lit(None).cast(pl.Date).alias("match_date"))

    casts: list[pl.Expr] = []
    for col in INT_COLUMNS:
        if col in df.columns:
            casts.append(pl.col(col).cast(pl.Int64, strict=False))
    for col in FLOAT_COLUMNS:
        if col in df.columns:
            casts.append(pl.col(col).cast(pl.Float64, strict=False))
    if casts:
        df = df.with_columns(casts)

    df = df.with_columns(
        pl.lit("football_data").alias("source"),
        pl.lit(league.value).alias("league"),
        pl.lit(season).alias("season"),
    )
    return df


def _empty_frame(league: League, season: str) -> pl.DataFrame:
    cols: list[pl.Series] = [
        pl.Series("home_team_raw", [], pl.String),
        pl.Series("away_team_raw", [], pl.String),
        pl.Series("match_date", [], pl.Date),
        pl.Series("source", [], pl.String),
        pl.Series("league", [], pl.String),
        pl.Series("season", [], pl.String),
    ]
    df = pl.DataFrame(cols)
    return df.with_columns(
        pl.lit(league.value).alias("league"),
        pl.lit(season).alias("season"),
    )
