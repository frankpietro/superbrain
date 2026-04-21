"""Eurobet → ``OddsSnapshot`` market parser.

Given the JSON envelope returned by the per-event detail endpoint
(``/detail-service/sport-schedule/services/event/...``), emit a list
of validated :class:`OddsSnapshot` rows covering the same market
families that the Sisal / Goldbet parsers already produce.

The Eurobet response shape boils down to:

    {
      "result": {
        "eventInfo": { programCode, eventCode, aliasUrl, eventData,
                        teamHome.description, teamAway.description, ... },
        "betGroupList": [
          {
            "betId": <int>,
            "betDescription": "1X2" | "U/O GOAL" | "GG/NG" | "DC" | ...,
            "oddGroupList": [
              {
                "oddGroupDescription": "1X2" | "2.5" | "1X" | ...,
                "oddList": [
                  {
                    "boxTitle": "1" | "OVER" | "UN 2.5" | ...,
                    "oddDescription": "1" | "OVER" | ...,
                    "oddValue": <int>,        # decimal odds * 100
                    "additionalInfo": [i, i, i, i, i, i]
                  },
                  ...
                ]
              }, ...
            ]
          }, ...
        ]
      }
    }

Decimal odds come packed as ``int * 100`` (``133 -> 1.33``, ``1050 -> 10.50``).
Thresholds for O/U-style markets live in ``additionalInfo[0]`` as
``int * 100`` (``250 -> 2.5``).

The parser is deliberately conservative:

* Unknown Eurobet ``betId`` → logged once via the caller, counted, skipped.
* Malformed selections / zero or negative quotes → skip the offending
  odd, never the whole event.
* Every emitted snapshot carries the selection-level JSON in
  ``raw_json`` for forensic replay.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import structlog

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League, OddsSnapshot, compute_match_id
from superbrain.core.teams import canonicalize_team

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Eurobet betId catalog  (betId → internal family)
# ---------------------------------------------------------------------------
#
# All betIds below emit :class:`OddsSnapshot` rows. Anything not in this
# dict is counted under ``unmapped_markets`` (keyed by the human-readable
# ``betDescription``) and surfaced by the orchestrator.

_FAMILY_BY_BET_ID: dict[int, str] = {
    24: "1X2_FULL",
    363: "1X2_HALF1",
    377: "1X2_HALF2",
    53: "1X2_HANDICAP",
    1555: "DC_FULL",
    4243: "GOALS_OU",
    1550: "BTTS",
    97: "MULTIGOL_FULL",
    407: "MULTIGOL_TEAM_HOME",
    430: "MULTIGOL_TEAM_AWAY",
    392: "GOALS_TEAM_YN_HOME",
    415: "GOALS_TEAM_YN_AWAY",
    51: "SCORE_EXACT",
    5458: "SCORE_EXACT",
    5474: "SCORE_EXACT",
    74: "SCORE_HT_FT",
    455: "CORNER_1X2",
    1971: "CORNER_OU",
    2043: "CARDS_OU",
    # SCOMMESSE TOP: a synthetic group containing the 1X2 / GG/NG /
    # U/O 2.5 oddGroups we already parse from the primary groups. Marking
    # it "known" suppresses the unmapped counter.
    1549: "TOP_GROUP_IGNORE",
    6754: "TOP_GROUP_IGNORE",  # SCOMMESSE TOP 1T
}

# SCOMMESSE TOP oddGroups expose their true market through the inner
# ``betId`` on each odd. We promote those mid-parse so they land under
# the right family without double-counting.
_TOP_INNER_FAMILY_BY_BET_ID: dict[int, str] = {
    24: "1X2_FULL",
    4243: "GOALS_OU",
    1550: "BTTS",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class ParsedEvent:
    """Structured view of one Eurobet event descriptor."""

    event_key: str
    event_id: str
    descrizione: str
    home_team_raw: str
    away_team_raw: str
    home_team: str
    away_team: str
    match_date: date
    kickoff: datetime
    season: str


def parse_event_meta(
    event_info: dict[str, Any], league: League | None
) -> ParsedEvent | None:
    """Extract the event metadata needed to assemble ``OddsSnapshot`` rows.

    :param event_info: the ``eventInfo`` sub-object from the Eurobet
        per-event payload.
    :param league: event league (used only for the season fallback).
    :return: parsed event metadata, or ``None`` if the event is unusable.
    """
    try:
        program_code = event_info.get("programCode")
        event_code = event_info.get("eventCode")
        if program_code is None or event_code is None:
            return None
        event_key = f"{program_code}-{event_code}"
        event_id = str(event_info.get("aliasUrl") or event_key)
        home_raw = str((event_info.get("teamHome") or {}).get("description") or "").strip()
        away_raw = str((event_info.get("teamAway") or {}).get("description") or "").strip()
        kickoff_ms = event_info.get("eventData")
        if not (home_raw and away_raw and kickoff_ms):
            return None
        kickoff = datetime.fromtimestamp(int(kickoff_ms) / 1000.0, tz=UTC)
    except (KeyError, TypeError, ValueError) as e:
        log.warning("eurobet.parser.event_meta_invalid", error=str(e))
        return None

    home = canonicalize_team(home_raw)
    away = canonicalize_team(away_raw)
    match_date = kickoff.astimezone(UTC).date()
    descr = f"{home_raw} - {away_raw}"
    return ParsedEvent(
        event_key=event_key,
        event_id=event_id,
        descrizione=descr,
        home_team_raw=home_raw,
        away_team_raw=away_raw,
        home_team=home,
        away_team=away,
        match_date=match_date,
        kickoff=kickoff,
        season=_season_for(match_date),
    )


def parse_event_markets(
    payload: dict[str, Any],
    *,
    league: League,
    captured_at: datetime,
    run_id: str,
    source: str = "eurobet.event",
) -> tuple[list[OddsSnapshot], Counter[str]]:
    """Parse a per-event detail payload into ``OddsSnapshot`` rows.

    :param payload: the raw ``result``-wrapped Eurobet event JSON (or the
        ``result`` sub-object directly).
    :param league: :class:`League` the event belongs to.
    :param captured_at: timestamp tagged on every emitted snapshot.
    :param run_id: scrape-run id tagged on every emitted snapshot.
    :param source: the ``source`` string for the snapshots (used in
        provenance and debugging).
    :return: ``(snapshots, unmapped_counter)``; ``unmapped_counter`` keys
        are the raw ``betDescription`` strings, values are occurrences.
    """
    unmapped: Counter[str] = Counter()
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if not isinstance(result, dict):
        return [], unmapped
    event_info = result.get("eventInfo") or {}
    event = parse_event_meta(event_info, league)
    if event is None:
        return [], unmapped

    match_id = compute_match_id(event.home_team, event.away_team, event.match_date, league)
    bet_groups = result.get("betGroupList") or []
    if not isinstance(bet_groups, list):
        return [], unmapped

    snapshots: list[OddsSnapshot] = []
    for bg in bet_groups:
        if not isinstance(bg, dict):
            continue
        try:
            bet_id = int(bg.get("betId") or 0)
        except (TypeError, ValueError):
            continue
        descr = str(bg.get("betDescription") or "").strip() or f"betId={bet_id}"
        family = _FAMILY_BY_BET_ID.get(bet_id)
        if family is None:
            unmapped[descr] += 1
            continue
        if family == "TOP_GROUP_IGNORE":
            snapshots.extend(
                _emit_top_group(
                    bg=bg,
                    event=event,
                    league=league,
                    match_id=match_id,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                    descr=descr,
                )
            )
            continue
        try:
            rows = _emit_family(
                family=family,
                bg=bg,
                event=event,
                league=league,
                match_id=match_id,
                captured_at=captured_at,
                run_id=run_id,
                source=source,
            )
        except _MarketSkipError as e:
            log.debug(
                "eurobet.parser.bet_group_skipped",
                market=descr,
                reason=e.reason,
                event_key=event.event_key,
            )
            continue
        except Exception as e:  # pragma: no cover - defensive outer guard
            log.warning(
                "eurobet.parser.bet_group_error",
                market=descr,
                error=str(e),
                event_key=event.event_key,
            )
            continue
        snapshots.extend(rows)

    return snapshots, unmapped


# ---------------------------------------------------------------------------
# Family-specific emitters
# ---------------------------------------------------------------------------


class _MarketSkipError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_EMITTER_BY_FAMILY: dict[str, str] = {
    "1X2_FULL": "_emit_match_1x2_full",
    "1X2_HALF1": "_emit_match_1x2_half1",
    "1X2_HALF2": "_emit_match_1x2_half2",
    "1X2_HANDICAP": "_emit_match_1x2_handicap",
    "DC_FULL": "_emit_dc",
    "GOALS_OU": "_emit_goals_ou",
    "BTTS": "_emit_btts",
    "MULTIGOL_FULL": "_emit_multigol_full",
    "MULTIGOL_TEAM_HOME": "_emit_multigol_team_home",
    "MULTIGOL_TEAM_AWAY": "_emit_multigol_team_away",
    "GOALS_TEAM_YN_HOME": "_emit_goals_team_yn_home",
    "GOALS_TEAM_YN_AWAY": "_emit_goals_team_yn_away",
    "SCORE_EXACT": "_emit_score_exact",
    "SCORE_HT_FT": "_emit_score_ht_ft",
    "CORNER_1X2": "_emit_corner_1x2",
    "CORNER_OU": "_emit_corner_ou",
    "CARDS_OU": "_emit_cards_ou",
}


def _emit_family(
    *,
    family: str,
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    emitter_name = _EMITTER_BY_FAMILY.get(family)
    if emitter_name is None:
        raise _MarketSkipError(f"unknown family {family!r}")
    kwargs: dict[str, Any] = {
        "bg": bg,
        "event": event,
        "league": league,
        "match_id": match_id,
        "captured_at": captured_at,
        "run_id": run_id,
        "source": source,
    }
    emitter = globals()[emitter_name]
    return list(emitter(**kwargs))


def _emit_top_group(
    *,
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    descr: str,
) -> list[OddsSnapshot]:
    """Unpack SCOMMESSE TOP into the appropriate sub-families."""
    out: list[OddsSnapshot] = []
    half = 1 if "1T" in descr.upper() else None
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        inner_bet_id = _inner_bet_id(og)
        if inner_bet_id is None:
            continue
        inner_family = _TOP_INNER_FAMILY_BY_BET_ID.get(inner_bet_id)
        if inner_family is None:
            continue
        fake_bg = {"betId": inner_bet_id, "oddGroupList": [og]}
        family_to_use = inner_family
        if family_to_use == "1X2_FULL" and half == 1:
            family_to_use = "1X2_HALF1"
        try:
            out.extend(
                _emit_family(
                    family=family_to_use,
                    bg=fake_bg,
                    event=event,
                    league=league,
                    match_id=match_id,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                )
            )
        except _MarketSkipError:
            continue
    return out


# --- 1X2 family -------------------------------------------------------------


def _emit_match_1x2_full(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_match_1x2(half=None, handicap=None, **kwargs)


def _emit_match_1x2_half1(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_match_1x2(half=1, handicap=None, **kwargs)


def _emit_match_1x2_half2(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_match_1x2(half=2, handicap=None, **kwargs)


def _emit_match_1x2_handicap(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    """Handicap 1X2 has one oddGroup per handicap line."""
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        handicap = _parse_handicap(og.get("oddGroupDescription"))
        rows = _rows_from_1x2_odd_group(
            og=og,
            event=event,
            league=league,
            match_id=match_id,
            captured_at=captured_at,
            run_id=run_id,
            source=source,
            half=None,
            handicap=handicap,
        )
        out.extend(rows)
    return out


def _emit_match_1x2(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    *,
    half: int | None,
    handicap: float | None,
) -> list[OddsSnapshot]:
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        out.extend(
            _rows_from_1x2_odd_group(
                og=og,
                event=event,
                league=league,
                match_id=match_id,
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                half=half,
                handicap=handicap,
            )
        )
    return out


def _rows_from_1x2_odd_group(
    *,
    og: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    half: int | None,
    handicap: float | None,
) -> list[OddsSnapshot]:
    mapping = {"1": "1", "X": "X", "2": "2"}
    params: dict[str, Any] = {}
    if half is not None:
        params["half"] = half
    if handicap is not None:
        params["handicap"] = handicap
    out: list[OddsSnapshot] = []
    for odd in og.get("oddList") or []:
        if not isinstance(odd, dict):
            continue
        desc = _odd_label(odd)
        selection = mapping.get(desc)
        if selection is None:
            continue
        payout = _payout(odd)
        if payout is None:
            continue
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.MATCH_1X2,
                market_params=params,
                selection=selection,
                payout=payout,
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=odd,
            )
        )
    return out


# --- Double chance ----------------------------------------------------------


def _emit_dc(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    mapping = {"1X": "1X", "12": "12", "X2": "X2"}
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        for odd in og.get("oddList") or []:
            if not isinstance(odd, dict):
                continue
            desc = _odd_label(odd).replace(" ", "")
            selection = mapping.get(desc)
            if selection is None:
                continue
            payout = _payout(odd)
            if payout is None:
                continue
            out.append(
                _make_snapshot(
                    event=event,
                    league=league,
                    match_id=match_id,
                    market=Market.MATCH_DOUBLE_CHANCE,
                    market_params={},
                    selection=selection,
                    payout=payout,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                    raw=odd,
                )
            )
    return out


# --- Goals O/U + BTTS -------------------------------------------------------


def _emit_goals_ou(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    return _emit_generic_ou(
        bg=bg,
        event=event,
        league=league,
        match_id=match_id,
        captured_at=captured_at,
        run_id=run_id,
        source=source,
        market=Market.GOALS_OVER_UNDER,
        extra_params={},
    )


def _emit_corner_ou(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    return _emit_generic_ou(
        bg=bg,
        event=event,
        league=league,
        match_id=match_id,
        captured_at=captured_at,
        run_id=run_id,
        source=source,
        market=Market.CORNER_TOTAL,
        extra_params={},
    )


def _emit_cards_ou(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    return _emit_generic_ou(
        bg=bg,
        event=event,
        league=league,
        match_id=match_id,
        captured_at=captured_at,
        run_id=run_id,
        source=source,
        market=Market.CARDS_TOTAL,
        extra_params={},
    )


def _emit_generic_ou(
    *,
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    market: Market,
    extra_params: dict[str, Any],
) -> list[OddsSnapshot]:
    mapping = {
        "OVER": "OVER",
        "UNDER": "UNDER",
        "OV": "OVER",
        "UN": "UNDER",
        "O": "OVER",
        "U": "UNDER",
    }
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        for odd in og.get("oddList") or []:
            if not isinstance(odd, dict):
                continue
            desc = _odd_label(odd)
            token = desc.split(" ")[0] if " " in desc else desc
            selection = mapping.get(token) or mapping.get(desc)
            if selection is None:
                continue
            threshold = _threshold_from_odd(odd, og)
            if threshold is None:
                continue
            payout = _payout(odd)
            if payout is None:
                continue
            params: dict[str, Any] = {"threshold": threshold, **extra_params}
            out.append(
                _make_snapshot(
                    event=event,
                    league=league,
                    match_id=match_id,
                    market=market,
                    market_params=params,
                    selection=selection,
                    payout=payout,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                    raw=odd,
                )
            )
    return out


def _emit_btts(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    mapping = {
        "GG": "YES",
        "GOAL": "YES",
        "NG": "NO",
        "NOGOAL": "NO",
        "NO GOAL": "NO",
    }
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        for odd in og.get("oddList") or []:
            if not isinstance(odd, dict):
                continue
            desc = _odd_label(odd).replace(" ", "")
            selection = mapping.get(desc)
            if selection is None:
                continue
            payout = _payout(odd)
            if payout is None:
                continue
            out.append(
                _make_snapshot(
                    event=event,
                    league=league,
                    match_id=match_id,
                    market=Market.GOALS_BOTH_TEAMS,
                    market_params={},
                    selection=selection,
                    payout=payout,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                    raw=odd,
                )
            )
    return out


# --- Multigol ---------------------------------------------------------------


def _emit_multigol_full(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    return _emit_multigol(
        bg=bg,
        event=event,
        league=league,
        match_id=match_id,
        captured_at=captured_at,
        run_id=run_id,
        source=source,
        team_side=None,
    )


def _emit_multigol_team_home(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_multigol(team_side="home", **kwargs)


def _emit_multigol_team_away(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_multigol(team_side="away", **kwargs)


def _emit_multigol(
    *,
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    team_side: str | None,
) -> list[OddsSnapshot]:
    market = Market.MULTIGOL if team_side is None else Market.MULTIGOL_TEAM
    team_name = (
        event.home_team if team_side == "home" else event.away_team
    ) if team_side else None
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        for odd in og.get("oddList") or []:
            if not isinstance(odd, dict):
                continue
            label = _odd_label(odd)
            lower, upper = _parse_multigol_range(label)
            if lower is None or upper is None:
                continue
            payout = _payout(odd)
            if payout is None:
                continue
            params: dict[str, Any] = {"lower": lower, "upper": upper}
            if team_side is not None:
                params["team"] = team_name
                params["side"] = team_side
            selection = f"{lower}-{upper}" if lower != upper else f"{lower}"
            out.append(
                _make_snapshot(
                    event=event,
                    league=league,
                    match_id=match_id,
                    market=market,
                    market_params=params,
                    selection=selection,
                    payout=payout,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                    raw=odd,
                )
            )
    return out


# --- Team yes/no "SEGNA GOAL SQUADRA" (store as GOALS_TEAM @ 0.5) -----------


def _emit_goals_team_yn_home(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_goals_team_yn(team_side="home", **kwargs)


def _emit_goals_team_yn_away(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_goals_team_yn(team_side="away", **kwargs)


def _emit_goals_team_yn(
    *,
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    team_side: str,
) -> list[OddsSnapshot]:
    """"SEGNA GOAL SQUADRA" is equivalent to team-U/O at threshold 0.5."""
    mapping = {"SI": "OVER", "YES": "OVER", "NO": "UNDER"}
    team_name = event.home_team if team_side == "home" else event.away_team
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        for odd in og.get("oddList") or []:
            if not isinstance(odd, dict):
                continue
            desc = _odd_label(odd)
            selection = mapping.get(desc)
            if selection is None:
                continue
            payout = _payout(odd)
            if payout is None:
                continue
            params: dict[str, Any] = {
                "team": team_name,
                "side": team_side,
                "threshold": 0.5,
            }
            out.append(
                _make_snapshot(
                    event=event,
                    league=league,
                    match_id=match_id,
                    market=Market.GOALS_TEAM,
                    market_params=params,
                    selection=selection,
                    payout=payout,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                    raw=odd,
                )
            )
    return out


# --- Score exact + HT/FT ----------------------------------------------------


def _emit_score_exact(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        for odd in og.get("oddList") or []:
            if not isinstance(odd, dict):
                continue
            desc = _odd_label(odd)
            parsed = _parse_score_exact(desc)
            if parsed is None:
                continue
            home_goals, away_goals = parsed
            payout = _payout(odd)
            if payout is None:
                continue
            out.append(
                _make_snapshot(
                    event=event,
                    league=league,
                    match_id=match_id,
                    market=Market.SCORE_EXACT,
                    market_params={"home": home_goals, "away": away_goals},
                    selection=f"{home_goals}-{away_goals}",
                    payout=payout,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                    raw=odd,
                )
            )
    return out


def _emit_score_ht_ft(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        for odd in og.get("oddList") or []:
            if not isinstance(odd, dict):
                continue
            desc = _odd_label(odd)
            parts = _parse_ht_ft(desc)
            if parts is None:
                continue
            ht, ft = parts
            payout = _payout(odd)
            if payout is None:
                continue
            out.append(
                _make_snapshot(
                    event=event,
                    league=league,
                    match_id=match_id,
                    market=Market.SCORE_HT_FT,
                    market_params={"ht": ht, "ft": ft},
                    selection=f"{ht}/{ft}",
                    payout=payout,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                    raw=odd,
                )
            )
    return out


# --- Corners 1X2 ------------------------------------------------------------


def _emit_corner_1x2(
    bg: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    mapping = {"1": "1", "X": "X", "2": "2"}
    out: list[OddsSnapshot] = []
    for og in bg.get("oddGroupList") or []:
        if not isinstance(og, dict):
            continue
        for odd in og.get("oddList") or []:
            if not isinstance(odd, dict):
                continue
            desc = _odd_label(odd)
            selection = mapping.get(desc)
            if selection is None:
                continue
            payout = _payout(odd)
            if payout is None:
                continue
            out.append(
                _make_snapshot(
                    event=event,
                    league=league,
                    match_id=match_id,
                    market=Market.CORNER_1X2,
                    market_params={},
                    selection=selection,
                    payout=payout,
                    captured_at=captured_at,
                    run_id=run_id,
                    source=source,
                    raw=odd,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    event: ParsedEvent,
    league: League,
    match_id: str,
    market: Market,
    market_params: dict[str, Any],
    selection: str,
    payout: float,
    captured_at: datetime,
    run_id: str,
    source: str,
    raw: dict[str, Any],
) -> OddsSnapshot:
    return OddsSnapshot(
        bookmaker=Bookmaker.EUROBET,
        bookmaker_event_id=event.event_id,
        match_id=match_id,
        match_label=f"{event.home_team} - {event.away_team}",
        match_date=event.match_date,
        season=event.season,
        league=league,
        home_team=event.home_team,
        away_team=event.away_team,
        market=market,
        market_params=market_params,
        selection=selection,
        payout=payout,
        captured_at=captured_at,
        source=source,
        run_id=run_id,
        raw_json=json.dumps(raw, ensure_ascii=False, sort_keys=True),
    )


def _odd_label(odd: dict[str, Any]) -> str:
    raw = odd.get("oddDescription") or odd.get("boxTitle") or ""
    return str(raw).strip().upper()


def _inner_bet_id(og: dict[str, Any]) -> int | None:
    direct = og.get("betId")
    if direct is not None:
        try:
            return int(direct)
        except (TypeError, ValueError):
            pass
    for odd in og.get("oddList") or []:
        if isinstance(odd, dict) and odd.get("betId") is not None:
            try:
                return int(odd["betId"])
            except (TypeError, ValueError):
                continue
    return None


def _payout(odd: dict[str, Any]) -> float | None:
    quota = odd.get("oddValue")
    if quota is None:
        return None
    try:
        q = float(quota)
    except (TypeError, ValueError):
        return None
    decimal = q / 100.0
    if decimal <= 1.0:
        return None
    return decimal


def _threshold_from_odd(
    odd: dict[str, Any], og: dict[str, Any]
) -> float | None:
    add_info = odd.get("additionalInfo")
    if isinstance(add_info, list) and add_info:
        try:
            raw = float(add_info[0])
        except (TypeError, ValueError):
            raw = 0.0
        if raw:
            return raw / 100.0
    og_desc = str(og.get("oddGroupDescription") or "").strip()
    m = re.match(r"^(\d+(?:[.,]\d+)?)$", og_desc)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _parse_handicap(og_desc: Any) -> float | None:
    if og_desc is None:
        return None
    s = str(og_desc).strip().replace(" ", "")
    m = re.match(r"^(-?\d+)\s*[:\-]\s*(-?\d+)$", s)
    if m:
        home = int(m.group(1))
        away = int(m.group(2))
        return float(home - away)
    m = re.match(r"^[+]?(-?\d+(?:\.\d+)?)$", s)
    if m:
        return float(m.group(1))
    return None


def _parse_multigol_range(desc: str) -> tuple[int | None, int | None]:
    s = desc.strip().upper().replace("'", "").replace("\u2019", "").replace(" ", "")
    if s.isdigit():
        n = int(s)
        return n, n
    m = re.match(r"^(\d+)-(\d+)$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^>(\d+)$", s)
    if m:
        return int(m.group(1)) + 1, 99
    m = re.match(r"^(\d+)\+$", s)
    if m:
        return int(m.group(1)), 99
    return None, None


def _parse_score_exact(desc: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d+)\s*-\s*(\d+)$", desc.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_ht_ft(desc: str) -> tuple[str, str] | None:
    m = re.match(r"^([12X])\s*[-/]\s*([12X])$", desc.strip().upper())
    if m:
        return m.group(1), m.group(2)
    return None


def _season_for(match_date: date) -> str:
    y = match_date.year
    start = y if match_date.month >= 7 else y - 1
    return f"{start}-{str((start + 1) % 100).zfill(2)}"


__all__ = [
    "ParsedEvent",
    "parse_event_markets",
    "parse_event_meta",
]
