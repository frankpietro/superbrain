"""Polars / Arrow schemas matching the pydantic models.

Having the schema in one place means:

* ``Lake.ingest_*`` can cast an incoming frame before writing.
* ``Lake.read_table`` can assert the result.
* Contributors who upload their own parquets can validate locally before
  shipping them to the ``/ingest`` endpoint.
"""

from __future__ import annotations

from typing import Any

import polars as pl


def _schema(columns: list[tuple[str, Any]]) -> pl.Schema:
    return pl.Schema(columns)


ODDS_SCHEMA: pl.Schema = _schema(
    [
        ("bookmaker", pl.String),
        ("bookmaker_event_id", pl.String),
        ("match_id", pl.String),
        ("match_label", pl.String),
        ("match_date", pl.Date),
        ("season", pl.String),
        ("league", pl.String),
        ("home_team", pl.String),
        ("away_team", pl.String),
        ("market", pl.String),
        ("market_params_json", pl.String),
        ("market_params_hash", pl.String),
        ("selection", pl.String),
        ("payout", pl.Float64),
        ("captured_at", pl.Datetime(time_unit="us", time_zone="UTC")),
        ("source", pl.String),
        ("run_id", pl.String),
        ("raw_json", pl.String),
    ]
)


MATCH_SCHEMA: pl.Schema = _schema(
    [
        ("match_id", pl.String),
        ("league", pl.String),
        ("season", pl.String),
        ("match_date", pl.Date),
        ("home_team", pl.String),
        ("away_team", pl.String),
        ("home_goals", pl.Int64),
        ("away_goals", pl.Int64),
        ("source", pl.String),
        ("ingested_at", pl.Datetime(time_unit="us", time_zone="UTC")),
    ]
)


TEAM_MATCH_STATS_SCHEMA: pl.Schema = _schema(
    [
        ("match_id", pl.String),
        ("team", pl.String),
        ("is_home", pl.Boolean),
        ("league", pl.String),
        ("season", pl.String),
        ("match_date", pl.Date),
        ("goals", pl.Int64),
        ("goals_conceded", pl.Int64),
        ("ht_goals", pl.Int64),
        ("ht_goals_conceded", pl.Int64),
        ("shots", pl.Int64),
        ("shots_on_target", pl.Int64),
        ("shots_off_target", pl.Int64),
        ("shots_in_box", pl.Int64),
        ("corners", pl.Int64),
        ("fouls", pl.Int64),
        ("yellow_cards", pl.Int64),
        ("red_cards", pl.Int64),
        ("offsides", pl.Int64),
        ("possession_pct", pl.Float64),
        ("passes", pl.Int64),
        ("pass_accuracy_pct", pl.Float64),
        ("tackles", pl.Int64),
        ("interceptions", pl.Int64),
        ("aerials_won", pl.Int64),
        ("saves", pl.Int64),
        ("big_chances", pl.Int64),
        ("big_chances_missed", pl.Int64),
        ("xg", pl.Float64),
        ("xga", pl.Float64),
        ("ppda", pl.Float64),
        ("source", pl.String),
        ("ingested_at", pl.Datetime(time_unit="us", time_zone="UTC")),
    ]
)


TEAM_ELO_SCHEMA: pl.Schema = _schema(
    [
        ("team", pl.String),
        ("country", pl.String),
        ("snapshot_date", pl.Date),
        ("elo", pl.Float64),
        ("rank", pl.Int64),
        ("source", pl.String),
        ("ingested_at", pl.Datetime(time_unit="us", time_zone="UTC")),
    ]
)


SCRAPE_RUNS_SCHEMA: pl.Schema = _schema(
    [
        ("run_id", pl.String),
        ("bookmaker", pl.String),
        ("scraper", pl.String),
        ("started_at", pl.Datetime(time_unit="us", time_zone="UTC")),
        ("finished_at", pl.Datetime(time_unit="us", time_zone="UTC")),
        ("status", pl.String),
        ("rows_written", pl.Int64),
        ("rows_rejected", pl.Int64),
        ("error_message", pl.String),
        ("host", pl.String),
    ]
)


def align_to_schema(frame: pl.DataFrame, schema: pl.Schema) -> pl.DataFrame:
    """Reorder and cast ``frame`` to match ``schema``.

    Missing columns are added as nulls with the target dtype. Extra columns
    are dropped. This is the last step before a parquet write, so it is
    deliberately forgiving.

    :param frame: incoming polars dataframe
    :param schema: target polars schema
    :return: dataframe whose columns match ``schema`` exactly
    """
    out: list[pl.Series] = []
    for col, dtype in schema.items():
        if col in frame.columns:
            out.append(frame.get_column(col).cast(dtype, strict=False))
        else:
            out.append(pl.Series(name=col, values=[None] * frame.height, dtype=dtype))
    return pl.DataFrame(out)
