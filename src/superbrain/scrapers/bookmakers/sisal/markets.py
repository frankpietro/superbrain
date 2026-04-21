"""Sisal → ``OddsSnapshot`` market parser.

The input is the full ``schedaAvvenimento`` payload for a single event
(``scommessaMap`` + ``infoAggiuntivaMap`` + ``avvenimentoFe``). The output is
a list of validated :class:`OddsSnapshot` objects plus a counter of Sisal
market descriptions we did not know how to map.

The parser is deliberately conservative:

* Unknown Sisal markets are skipped (and counted, not raised). The user's
  contract is *"scrape what you can; missing markets never abort a run"*.
* Malformed selections / missing odds skip the offending market, never the
  whole event.
* Every emitted snapshot carries the selection-level JSON in ``raw_json``
  for forensic replay against a parser regression.
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
# Descrizione catalog  (Sisal "descrizioneScommessa" → internal market family)
# ---------------------------------------------------------------------------
#
# All markets Sisal publishes on a top-5 prematch fixture. "supported" rows
# emit ``OddsSnapshot`` rows; "ignored" rows are intentionally skipped (e.g.
# player-prop markets that don't fit the value-bet engine's stat contract).
# "unknown" means "not yet categorized" and is what the runtime logs + counts
# under ``unmapped_markets`` so new mappings can be prioritized.

_SUPPORTED_FAMILIES = {
    # 1X2 family
    "1X2_FULL",
    "1X2_HALF1",
    "1X2_HALF2",
    # Double chance
    "DC_FULL",
    "DC_HALF",
    # Goals totals
    "GOALS_OU",
    "GOALS_OU_HALF",
    "GOALS_OU_TEAM",
    # BTTS
    "BTTS",
    "BTTS_HALF",
    # Multigoal
    "MULTIGOL_FULL",
    "MULTIGOL_TEAM_HALF",  # stored under MULTIGOL with half param
    "MULTIGOL_TEAM",
    # Score
    "SCORE_EXACT",
    "SCORE_HT_FT",
    # Corner
    "CORNER_1X2",
    "CORNER_HANDICAP",
    # Combos
    "COMBO_1X2_OU",
    "COMBO_BTTS_OU",
}

# Descrizione strings Sisal returns (trimmed with ``.strip()``) → family.
# Keys must be canonical (``_canonical_market_key``: strip, collapse spaces,
# uppercase, remove accents). The lookup is case/accent/whitespace-insensitive
# via ``_canonical_market_key``.
_FAMILY_BY_DESCRIZIONE: dict[str, str] = {
    "1X2 ESITO FINALE": "1X2_FULL",
    "1 TEMPO: ESITO 1X2": "1X2_HALF1",
    "2 TEMPO: ESITO 1X2": "1X2_HALF2",
    "DOPPIA CHANCE": "DC_FULL",
    "DOPPIA CHANCE TEMPO X": "DC_HALF",
    "UNDER/OVER": "GOALS_OU",
    "UNDER/OVER TEMPO X": "GOALS_OU_HALF",
    "U/O SQUADRA X": "GOALS_OU_TEAM",
    "GOAL/NOGOAL": "BTTS",
    "GOAL/NOGOAL TEMPO X": "BTTS_HALF",
    "MULTIGOAL": "MULTIGOL_FULL",
    "MULTIGOAL TEMPO X": "MULTIGOL_TEAM_HALF",
    "MULTIGOAL SQUADRA X": "MULTIGOL_TEAM",
    "RISULTATO ESATTO 26 ESITI": "SCORE_EXACT",
    "RISULTATO ESATTO 75 ESITI": "SCORE_EXACT",
    "1 TEMPO: RISULTATO ESATTO": "SCORE_EXACT",
    "2 TEMPO: RISULTATO ESATTO": "SCORE_EXACT",
    "ESITO 1 TEMPO/FINALE": "SCORE_HT_FT",
    "RISULTATO ESATTO PARZIALE/FINALE (46 ESITI)": "SCORE_HT_FT",
    "1 TEMPO: 1X2 CORNER": "CORNER_1X2",
    "1 TEMPO: 1X2 HANDICAP CORNER": "CORNER_HANDICAP",
    "COMBO: 1X2 + U/O": "COMBO_1X2_OU",
    "COMBO: GOAL/NOGOAL + U/O": "COMBO_BTTS_OU",
}

_CANONICAL_FAMILY_LOOKUP: dict[str, str] = {}


def _canonical_market_key(descrizione: str) -> str:
    s = descrizione.strip()
    s = re.sub(r"\s+", " ", s)
    return s.upper()


for _k, _v in _FAMILY_BY_DESCRIZIONE.items():
    _CANONICAL_FAMILY_LOOKUP[_canonical_market_key(_k)] = _v

_SKIP_DESCR_PREFIXES: tuple[str, ...] = (
    # Player-prop markets — out of scope for the value-bet engine.
    "PRIMO MARCATORE",
    "ULTIMO MARCATORE",
    "PRIMO O ULTIMO MARCATORE",
    "MARCATORE SI/NO",
    "MARCATORE PIÙ",
    "GIOCATORE",
    "MIGLIOR GIOCATORE",
    "MINUTO PRIMO",
    "MINUTO ULTIMO",
    "1X2 + MARCATORE",
    "1X2 + PRIMO MARCATORE",
    "RISULTATO ESATTO + MARCATORE",
    "RISULTATO ESATTO + PRIMO",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class ParsedEvent:
    """Structured view of one Sisal event descriptor."""

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


def parse_event_meta(avvenimento: dict[str, Any], league: League | None) -> ParsedEvent | None:
    """Extract the event metadata needed to assemble ``OddsSnapshot`` rows.

    :param avvenimento: an entry from ``avvenimentoFeList`` *or* the
        singular ``avvenimentoFe`` object.
    :param league: event league (used only for the season fallback).
    :return: parsed event metadata, or ``None`` if the event is unusable.
    """
    try:
        event_key = str(avvenimento["key"])
        regulator = avvenimento.get("regulatorEventId") or avvenimento.get("eventId")
        event_id = str(regulator) if regulator is not None else event_key
        desc = str(avvenimento.get("descrizione") or "")
        first = avvenimento.get("firstCompetitor") or {}
        second = avvenimento.get("secondCompetitor") or {}
        home_raw = str(first.get("description") or "").strip()
        away_raw = str(second.get("description") or "").strip()
        kickoff_iso = avvenimento.get("data")
        if not (event_key and home_raw and away_raw and kickoff_iso):
            return None
        kickoff = _parse_iso(str(kickoff_iso))
    except (KeyError, TypeError, ValueError) as e:
        log.warning("sisal.parser.event_meta_invalid", error=str(e))
        return None

    home = canonicalize_team(home_raw)
    away = canonicalize_team(away_raw)
    match_date = kickoff.astimezone(UTC).date()
    return ParsedEvent(
        event_key=event_key,
        event_id=event_id,
        descrizione=desc or f"{home_raw} - {away_raw}",
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
    source: str = "sisal.schedaAvvenimento",
) -> tuple[list[OddsSnapshot], Counter[str]]:
    """Parse a ``schedaAvvenimento`` payload into ``OddsSnapshot`` rows.

    :param payload: the raw ``schedaAvvenimento`` JSON (or any structurally
        compatible dict with ``avvenimentoFe``/``scommessaMap``/
        ``infoAggiuntivaMap`` keys).
    :param league: ``League`` enum the event belongs to.
    :param captured_at: timestamp tagged on every emitted snapshot.
    :param run_id: scrape-run id tagged on every emitted snapshot.
    :param source: the ``source`` string for the snapshots (used in
        provenance and debugging).
    :return: ``(snapshots, unmapped_counter)``; ``unmapped_counter`` keys are
        canonical market descriptions and values are occurrences in this
        event.
    """
    avvenimento = payload.get("avvenimentoFe") or {}
    if not avvenimento and isinstance(payload.get("avvenimentoFeList"), list):
        events = payload["avvenimentoFeList"]
        avvenimento = events[0] if events else {}
    event = parse_event_meta(avvenimento, league)
    unmapped: Counter[str] = Counter()
    if event is None:
        return [], unmapped

    match_id = compute_match_id(event.home_team, event.away_team, event.match_date, league)
    scommesse: dict[str, Any] = payload.get("scommessaMap") or {}
    info_agg: dict[str, Any] = payload.get("infoAggiuntivaMap") or {}

    snapshots: list[OddsSnapshot] = []
    for market_key, market_entry in scommesse.items():
        try:
            market_descr = str(market_entry.get("descrizione") or "").strip()
            if not market_descr:
                continue
            if any(market_descr.upper().startswith(p) for p in _SKIP_DESCR_PREFIXES):
                continue
            family = _CANONICAL_FAMILY_LOOKUP.get(_canonical_market_key(market_descr))
            if family is None:
                unmapped[market_descr] += 1
                continue
            prefix = f"{market_key}-"
            ia_entries = [ia for ik, ia in info_agg.items() if ik.startswith(prefix)]
            if not ia_entries:
                continue
            for ia in ia_entries:
                try:
                    family_snapshots = _snapshots_for_family(
                        family=family,
                        market_descr=market_descr,
                        ia=ia,
                        event=event,
                        league=league,
                        match_id=match_id,
                        captured_at=captured_at,
                        run_id=run_id,
                        source=source,
                    )
                except _MarketSkipError as e:
                    log.debug(
                        "sisal.parser.ia_skipped",
                        market=market_descr,
                        reason=e.reason,
                        event_key=event.event_key,
                    )
                    continue
                except Exception as e:  # pragma: no cover - defensive
                    log.warning(
                        "sisal.parser.ia_error",
                        market=market_descr,
                        error=str(e),
                        event_key=event.event_key,
                    )
                    continue
                snapshots.extend(family_snapshots)
        except Exception as e:  # pragma: no cover - defensive outer guard
            log.warning(
                "sisal.parser.market_error",
                market=str(market_entry.get("descrizione")),
                error=str(e),
                event_key=event.event_key,
            )
            continue

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
    "DC_FULL": "_emit_dc_full",
    "DC_HALF": "_emit_dc_half",
    "GOALS_OU": "_emit_goals_ou",
    "GOALS_OU_HALF": "_emit_halves_ou",
    "GOALS_OU_TEAM": "_emit_goals_team_ou",
    "BTTS": "_emit_btts_full",
    "BTTS_HALF": "_emit_btts_half",
    "MULTIGOL_FULL": "_emit_multigol_full",
    "MULTIGOL_TEAM_HALF": "_emit_multigol_half",
    "MULTIGOL_TEAM": "_emit_multigol_team",
    "SCORE_EXACT": "_emit_score_exact",
    "SCORE_HT_FT": "_emit_score_ht_ft",
    "CORNER_1X2": "_emit_corner_1x2",
    "CORNER_HANDICAP": "_emit_corner_handicap",
    "COMBO_1X2_OU": "_emit_combo_1x2_ou",
    "COMBO_BTTS_OU": "_emit_combo_btts_ou",
}


def _snapshots_for_family(
    *,
    family: str,
    market_descr: str,
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    kwargs: dict[str, Any] = {
        "ia": ia,
        "event": event,
        "league": league,
        "match_id": match_id,
        "captured_at": captured_at,
        "run_id": run_id,
        "source": source,
    }
    emitter_name = _EMITTER_BY_FAMILY.get(family)
    if emitter_name is None:
        raise _MarketSkipError(f"unknown family {family!r}")
    emitter = globals()[emitter_name]
    if family == "SCORE_EXACT":
        return list(emitter(market_descr=market_descr, **kwargs))
    return list(emitter(**kwargs))


def _emit_match_1x2_full(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_match_1x2(half=None, **kwargs)


def _emit_match_1x2_half1(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_match_1x2(half=1, **kwargs)


def _emit_match_1x2_half2(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_match_1x2(half=2, **kwargs)


def _emit_dc_full(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_double_chance(half=None, **kwargs)


def _emit_dc_half(ia: dict[str, Any], **kwargs: Any) -> list[OddsSnapshot]:
    return _emit_double_chance(ia=ia, half=_half_from_ia(ia), **kwargs)


def _emit_btts_full(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_btts(half=None, **kwargs)


def _emit_btts_half(ia: dict[str, Any], **kwargs: Any) -> list[OddsSnapshot]:
    return _emit_btts(ia=ia, half=_half_from_ia(ia), **kwargs)


def _emit_multigol_full(**kwargs: Any) -> list[OddsSnapshot]:
    return _emit_multigol(half=None, **kwargs)


def _emit_multigol_half(ia: dict[str, Any], **kwargs: Any) -> list[OddsSnapshot]:
    return _emit_multigol(ia=ia, half=_half_from_soglia_or_ia(ia), **kwargs)


def _emit_match_1x2(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    *,
    half: int | None,
) -> list[OddsSnapshot]:
    mapping = {"1": "1", "X": "X", "2": "2"}
    market = Market.MATCH_1X2
    params: dict[str, Any] = {}
    if half is not None:
        params["half"] = half
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip().upper()
        selection = mapping.get(desc)
        if selection is None:
            raise _MarketSkipError(f"unexpected 1X2 esito {desc!r}")
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=market,
                market_params=params,
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_double_chance(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    *,
    half: int | None,
) -> list[OddsSnapshot]:
    mapping = {"1X": "1X", "12": "12", "X2": "X2"}
    params: dict[str, Any] = {}
    if half is not None:
        params["half"] = half
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip().upper().replace(" ", "")
        selection = mapping.get(desc)
        if selection is None:
            raise _MarketSkipError(f"unexpected DC esito {desc!r}")
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.MATCH_DOUBLE_CHANCE,
                market_params=params,
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_goals_ou(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    threshold = _soglia_as_threshold(ia)
    if threshold is None:
        raise _MarketSkipError("missing U/O threshold")
    return _ou_snapshots(
        ia=ia,
        event=event,
        league=league,
        match_id=match_id,
        market=Market.GOALS_OVER_UNDER,
        params={"threshold": threshold},
        captured_at=captured_at,
        run_id=run_id,
        source=source,
    )


def _emit_halves_ou(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    threshold = _soglia_as_threshold(ia)
    half = _half_from_ia(ia)
    if threshold is None or half is None:
        raise _MarketSkipError("missing halves threshold/half")
    return _ou_snapshots(
        ia=ia,
        event=event,
        league=league,
        match_id=match_id,
        market=Market.HALVES_OVER_UNDER,
        params={"half": half, "threshold": threshold},
        captured_at=captured_at,
        run_id=run_id,
        source=source,
    )


def _emit_goals_team_ou(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    threshold = _soglia_as_threshold(ia)
    team_side = _team_side_from_ia(ia)
    if threshold is None or team_side is None:
        raise _MarketSkipError("missing team U/O threshold/team")
    team_name = event.home_team if team_side == "home" else event.away_team
    return _ou_snapshots(
        ia=ia,
        event=event,
        league=league,
        match_id=match_id,
        market=Market.GOALS_TEAM,
        params={"team": team_name, "side": team_side, "threshold": threshold},
        captured_at=captured_at,
        run_id=run_id,
        source=source,
    )


def _ou_snapshots(
    *,
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    market: Market,
    params: dict[str, Any],
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    mapping = {"OVER": "OVER", "UNDER": "UNDER", "O": "OVER", "U": "UNDER"}
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip().upper()
        selection = mapping.get(desc)
        if selection is None:
            raise _MarketSkipError(f"unexpected O/U esito {desc!r}")
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=market,
                market_params=params,
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_btts(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    *,
    half: int | None,
) -> list[OddsSnapshot]:
    mapping = {
        "GOAL": "YES",
        "GOL": "YES",
        "NO GOAL": "NO",
        "NOGOAL": "NO",
        "NO GOL": "NO",
        "NOGOL": "NO",
    }
    params: dict[str, Any] = {}
    if half is not None:
        params["half"] = half
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip().upper()
        selection = mapping.get(desc)
        if selection is None:
            raise _MarketSkipError(f"unexpected BTTS esito {desc!r}")
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.GOALS_BOTH_TEAMS,
                market_params=params,
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_multigol(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    *,
    half: int | None = None,
) -> list[OddsSnapshot]:
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip()
        lower, upper = _parse_multigol_range(desc)
        if lower is None:
            raise _MarketSkipError(f"unexpected multigol esito {desc!r}")
        params: dict[str, Any] = {"lower": lower, "upper": upper}
        if half is not None:
            params["half"] = half
        selection = f"{lower}-{upper}" if lower != upper else f"{lower}"
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.MULTIGOL,
                market_params=params,
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_multigol_team(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    team_side = _team_side_from_ia(ia)
    if team_side is None:
        raise _MarketSkipError("missing team for multigol team")
    team_name = event.home_team if team_side == "home" else event.away_team
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip()
        lower, upper = _parse_multigol_range(desc)
        if lower is None:
            raise _MarketSkipError(f"unexpected multigol team esito {desc!r}")
        params: dict[str, Any] = {
            "team": team_name,
            "side": team_side,
            "lower": lower,
            "upper": upper,
        }
        selection = f"{lower}-{upper}" if lower != upper else f"{lower}"
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.MULTIGOL_TEAM,
                market_params=params,
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_score_exact(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
    market_descr: str,
) -> list[OddsSnapshot]:
    half = _half_from_descrizione(market_descr)
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip()
        if desc.upper() in {"1", "X", "2", "ALTRO"}:
            # Grouping buckets; not an exact score per se.
            continue
        parsed = _parse_score_exact(desc)
        if parsed is None:
            continue
        home, away = parsed
        params: dict[str, Any] = {"home": home, "away": away}
        if half is not None:
            params["half"] = half
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.SCORE_EXACT,
                market_params=params,
                selection=f"{home}-{away}",
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_score_ht_ft(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip()
        parts = _parse_ht_ft(desc)
        if parts is None:
            continue
        ht, ft = parts
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.SCORE_HT_FT,
                market_params={"ht": ht, "ft": ft},
                selection=f"{ht}/{ft}",
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_corner_1x2(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    mapping = {"1": "1", "X": "X", "2": "2"}
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip().upper()
        selection = mapping.get(desc)
        if selection is None:
            raise _MarketSkipError(f"unexpected corner 1X2 esito {desc!r}")
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.CORNER_1X2,
                market_params={"half": 1},
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_corner_handicap(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    try:
        handicap = float(ia.get("soglia") or "0")
    except (TypeError, ValueError) as e:
        raise _MarketSkipError(f"bad handicap soglia: {e}") from e
    # Sisal posts 1/X/2 selections against a home-side handicap; we emit
    # HOME and AWAY rows (draw is not a target on the HANDICAP market) and
    # encode the handicap as a positive or negative float.
    selection_map = {"1": "HOME", "2": "AWAY"}
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip().upper()
        selection = selection_map.get(desc)
        if selection is None:
            # "X" isn't part of the Market.CORNER_HANDICAP selections.
            continue
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.CORNER_HANDICAP,
                market_params={"half": 1, "handicap": handicap},
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_combo_1x2_ou(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    threshold = _soglia_as_threshold(ia)
    if threshold is None:
        raise _MarketSkipError("missing combo 1X2+OU threshold")
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc = str(esito.get("descrizione") or "").strip().upper().replace(" ", "")
        parts = desc.split("+")
        if len(parts) != 2:
            raise _MarketSkipError(f"unexpected combo 1X2+OU esito {desc!r}")
        result_1x2, over_under = parts
        if result_1x2 not in {"1", "X", "2"}:
            raise _MarketSkipError(f"unexpected 1X2 side in combo: {desc!r}")
        selection_map = {"O": "OVER", "U": "UNDER", "OVER": "OVER", "UNDER": "UNDER"}
        selection = selection_map.get(over_under)
        if selection is None:
            raise _MarketSkipError(f"unexpected O/U side in combo: {desc!r}")
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.COMBO_1X2_OVER_UNDER,
                market_params={"result_1x2": result_1x2, "threshold": threshold},
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
            )
        )
    return out


def _emit_combo_btts_ou(
    ia: dict[str, Any],
    event: ParsedEvent,
    league: League,
    match_id: str,
    captured_at: datetime,
    run_id: str,
    source: str,
) -> list[OddsSnapshot]:
    threshold = _soglia_as_threshold(ia)
    if threshold is None:
        raise _MarketSkipError("missing combo BTTS+OU threshold")
    out: list[OddsSnapshot] = []
    for esito in _esiti(ia):
        desc_upper = str(esito.get("descrizione") or "").strip().upper()
        desc = " ".join(desc_upper.split())
        m = re.match(r"^(NO\s*GOAL|NOGOAL|GOAL)\s*\+\s*(OVER|UNDER|O|U)$", desc)
        if not m:
            raise _MarketSkipError(f"unexpected combo BTTS+OU esito {desc!r}")
        btts_side, ou_side = m.group(1), m.group(2)
        btts_label = "NO" if btts_side.replace(" ", "") in {"NOGOAL"} else "YES"
        selection = "OVER" if ou_side.startswith("O") else "UNDER"
        out.append(
            _make_snapshot(
                event=event,
                league=league,
                match_id=match_id,
                market=Market.COMBO_BTTS_OVER_UNDER,
                market_params={"bet_btts": btts_label, "threshold": threshold},
                selection=selection,
                payout=_payout(esito),
                captured_at=captured_at,
                run_id=run_id,
                source=source,
                raw=esito,
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
        bookmaker=Bookmaker.SISAL,
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


def _esiti(ia: dict[str, Any]) -> list[dict[str, Any]]:
    esiti = ia.get("esitoList")
    if not isinstance(esiti, list):
        raise _MarketSkipError("esitoList missing/invalid")
    out: list[dict[str, Any]] = []
    for e in esiti:
        if not isinstance(e, dict):
            continue
        if int(e.get("stato", 0)) == 0:
            # 0 = suspended; ignore these rows (no live quote).
            continue
        out.append(e)
    return out


def _payout(esito: dict[str, Any]) -> float:
    quota = esito.get("quota")
    payout = esito.get("payout")
    if payout is not None:
        try:
            p = float(payout)
            if p > 0:
                return p
        except (TypeError, ValueError):
            pass
    if quota is None:
        raise _MarketSkipError("missing quota")
    try:
        q = float(quota)
    except (TypeError, ValueError) as e:
        raise _MarketSkipError(f"bad quota {quota!r}") from e
    # Sisal serializes decimal odds as integer * 100 (e.g. 195 → 1.95).
    decimal = q / 100.0
    if decimal <= 1.0:
        raise _MarketSkipError(f"non-positive payout {decimal}")
    return decimal


def _soglia_as_threshold(ia: dict[str, Any]) -> float | None:
    soglia = ia.get("soglia")
    if soglia is None or soglia == "":
        return None
    try:
        return float(str(soglia))
    except (TypeError, ValueError):
        return None


def _half_from_ia(ia: dict[str, Any]) -> int | None:
    short = str(ia.get("shortDescription") or "").upper()
    if "1 T" in short or "TEMPO 1" in short or short.startswith("T 1"):
        return 1
    if "2 T" in short or "TEMPO 2" in short or short.startswith("T 2"):
        return 2
    return None


def _half_from_soglia_or_ia(ia: dict[str, Any]) -> int | None:
    soglia_str = str(ia.get("soglia") or "")
    if soglia_str in {"1", "2"}:
        return int(soglia_str)
    return _half_from_ia(ia)


def _team_side_from_ia(ia: dict[str, Any]) -> str | None:
    team_ids = ia.get("teamIds") or []
    short = str(ia.get("shortDescription") or "").upper()
    if team_ids:
        mapping = {"1": "home", "2": "away"}
        return mapping.get(str(team_ids[0]))
    if "SQUADRA 1" in short or short.endswith(" S 1") or "CASA" in short:
        return "home"
    if "SQUADRA 2" in short or short.endswith(" S 2") or "OSPITE" in short:
        return "away"
    return None


def _parse_multigol_range(desc: str) -> tuple[int, int] | tuple[None, None]:
    s = desc.strip().upper().replace("'", "").replace("\u2019", "")
    if s.isdigit():
        n = int(s)
        return n, n
    m = re.match(r"^(\d+)\s*-\s*(\d+)$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d+)\s*\+$", s)
    if m:
        return int(m.group(1)), 99
    m = re.match(r"^(\d+)\s*O\s*PIU$", s)
    if m:
        return int(m.group(1)), 99
    m = re.match(r"^(\d+)\s*O\s*PIU\s*GOAL$", s)
    if m:
        return int(m.group(1)), 99
    return None, None


def _parse_score_exact(desc: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d+)\s*-\s*(\d+)$", desc.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_ht_ft(desc: str) -> tuple[str, str] | None:
    # HT-FT 1X2 pairs (e.g. "1/1", "X/2"); full 46-esiti exact-score ("1-0/2-1")
    # is skipped for now (distinct market family).
    m = re.match(r"^([12X])\s*[-/]\s*([12X])$", desc.strip().upper())
    if m:
        return m.group(1), m.group(2)
    return None


def _half_from_descrizione(descrizione: str) -> int | None:
    upper = descrizione.upper()
    if "1 TEMPO" in upper or "1T" in upper or "PRIMO TEMPO" in upper:
        return 1
    if "2 TEMPO" in upper or "2T" in upper or "SECONDO TEMPO" in upper:
        return 2
    return None


def _parse_iso(iso: str) -> datetime:
    """Parse an ISO-8601 timestamp (with optional trailing ``Z``)."""
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _season_for(match_date: date) -> str:
    """European football season key for a match date (``YYYY-YY``)."""
    y = match_date.year
    start = y if match_date.month >= 7 else y - 1
    return f"{start}-{str((start + 1) % 100).zfill(2)}"


__all__ = [
    "ParsedEvent",
    "parse_event_markets",
    "parse_event_meta",
]
