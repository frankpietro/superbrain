"""Goldbet JSON payload → :class:`OddsSnapshot` stream.

Goldbet ships each event's odds as a dict of *market blocks* keyed by
``"<tbI>;<slI>;<sslI>;0;0"`` under ``leo[0].mmkW``. Each block has:

- ``mn`` — market name (Italian string, e.g. ``"1X2"``, ``"U/O"``)
- ``smk`` — "split market" flag; True when the market has thresholds
- ``spd`` — ``dict[threshold_key, block]``; each block contains
  ``asl`` (all-selections list) where each selection has ``sn``
  (selection name) and ``ov`` (odds value)

The parser dispatches on ``mn`` via a small set of handlers, each of
which yields zero or more :class:`OddsSnapshot` rows. Unknown market
names are logged **once per scrape run** and skipped — missing odds
must never abort an event.

The handlers below cover at least: 1X2, double chance, goals O/U
(full match and halves), BTTS, team goals O/U, multigol (total and
per-team), corners O/U, combo 1X2 + O/U, combo BTTS + O/U, exact
score, HT-FT. Markets that Goldbet exposes but that don't map onto
the shared ``Market`` enum are listed in the module docstring's
"explicit skip" set (rather than logged as unknown) to keep run logs
quiet.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import structlog

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League, OddsSnapshot, compute_match_id
from superbrain.core.teams import canonicalize_team

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EventMeta:
    """Per-event metadata forwarded into every snapshot."""

    bookmaker_event_id: str
    match_label: str
    match_date: date
    season: str
    league: League | None
    home_team: str
    away_team: str
    captured_at: datetime
    source: str
    run_id: str

    @property
    def match_id(self) -> str | None:
        """Canonical ``match_id`` (sha256 of home/away/date/league)."""
        if self.league is None:
            return None
        return compute_match_id(self.home_team, self.away_team, self.match_date, self.league)


# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------

_OV_TOKENS = {"o", "ov", "over"}
_UN_TOKENS = {"u", "un", "under"}


def _as_over_under(sn: str) -> str | None:
    token = sn.strip().lower()
    if token in _OV_TOKENS:
        return "OVER"
    if token in _UN_TOKENS:
        return "UNDER"
    return None


def _as_yes_no(sn: str) -> str | None:
    token = sn.strip().lower()
    if token in {"gg", "si", "sì", "yes"}:
        return "YES"
    if token in {"ng", "no"}:
        return "NO"
    return None


def _as_float(value: Any) -> float | None:
    try:
        if isinstance(value, str):
            return float(value.replace(",", "."))
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_snapshot(**kwargs: Any) -> OddsSnapshot | None:
    """Build an ``OddsSnapshot``; return ``None`` on validation failure.

    Keeps the caller free of try/except noise when forging rows on the fly.
    Payout ≤ 0 is a common "suspended selection" signal in Goldbet's feed and
    is rejected at the pydantic layer anyway, so we filter early.

    :param kwargs: keyword args forwarded to ``OddsSnapshot``
    :return: validated snapshot or ``None``
    """
    payout = kwargs.get("payout")
    if payout is None or float(payout) <= 0.0:
        return None
    try:
        return OddsSnapshot(**kwargs)
    except Exception as e:  # pydantic ValidationError + TypeError catchall
        logger.debug("goldbet.snapshot_rejected", error=str(e), market=kwargs.get("market"))
        return None


def _common_snapshot_kwargs(meta: EventMeta, raw_market: dict[str, Any]) -> dict[str, Any]:
    return {
        "bookmaker": Bookmaker.GOLDBET,
        "bookmaker_event_id": meta.bookmaker_event_id,
        "match_id": meta.match_id,
        "match_label": meta.match_label,
        "match_date": meta.match_date,
        "season": meta.season,
        "league": meta.league,
        "home_team": meta.home_team,
        "away_team": meta.away_team,
        "captured_at": meta.captured_at,
        "source": meta.source,
        "run_id": meta.run_id,
        "raw_json": None,  # populated on a per-block basis; see below
    }


# ---------------------------------------------------------------------------
# Handlers
#
# Every handler has the same shape:
#
#     def handle_<name>(market: dict, meta: EventMeta) -> Iterator[OddsSnapshot]
#
# The dispatcher picks one handler per market block, based on ``mn``.
# ---------------------------------------------------------------------------


def _iter_spd(market: dict[str, Any]) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Yield ``(threshold_key, selection_list)`` pairs from a market block."""
    spd = market.get("spd") or {}
    for key, block in spd.items():
        if not isinstance(block, dict):
            continue
        asl = block.get("asl") or []
        if isinstance(asl, list):
            yield str(key), asl


def _handle_1x2(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for _, asl in _iter_spd(market):
        for sel in asl:
            sn, ov = sel.get("sn"), _as_float(sel.get("ov"))
            if sn not in {"1", "X", "2"} or ov is None:
                continue
            snap = _safe_snapshot(
                **common,
                market=Market.MATCH_1X2,
                market_params={},
                selection=sn,
                payout=ov,
            )
            if snap is not None:
                yield snap


def _handle_double_chance(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for _, asl in _iter_spd(market):
        for sel in asl:
            sn, ov = sel.get("sn"), _as_float(sel.get("ov"))
            if sn not in {"1X", "12", "X2"} or ov is None:
                continue
            snap = _safe_snapshot(
                **common,
                market=Market.MATCH_DOUBLE_CHANCE,
                market_params={},
                selection=sn,
                payout=ov,
            )
            if snap is not None:
                yield snap


def _handle_goals_ou(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for threshold_key, asl in _iter_spd(market):
        threshold = _as_float(threshold_key)
        if threshold is None:
            continue
        for sel in asl:
            choice = _as_over_under(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if choice is None or ov is None:
                continue
            snap = _safe_snapshot(
                **common,
                market=Market.GOALS_OVER_UNDER,
                market_params={"threshold": threshold},
                selection=choice,
                payout=ov,
            )
            if snap is not None:
                yield snap


def _handle_btts(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for _, asl in _iter_spd(market):
        for sel in asl:
            choice = _as_yes_no(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if choice is None or ov is None:
                continue
            snap = _safe_snapshot(
                **common,
                market=Market.GOALS_BOTH_TEAMS,
                market_params={},
                selection=choice,
                payout=ov,
            )
            if snap is not None:
                yield snap


def _handle_halves_ou(
    market: dict[str, Any], meta: EventMeta, *, half: int
) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for threshold_key, asl in _iter_spd(market):
        threshold = _as_float(threshold_key)
        if threshold is None:
            continue
        for sel in asl:
            choice = _as_over_under(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if choice is None or ov is None:
                continue
            snap = _safe_snapshot(
                **common,
                market=Market.HALVES_OVER_UNDER,
                market_params={"half": half, "threshold": threshold},
                selection=choice,
                payout=ov,
            )
            if snap is not None:
                yield snap


def _handle_team_ou(
    market: dict[str, Any], meta: EventMeta, *, team: str
) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for threshold_key, asl in _iter_spd(market):
        threshold = _as_float(threshold_key)
        if threshold is None:
            continue
        for sel in asl:
            choice = _as_over_under(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if choice is None or ov is None:
                continue
            snap = _safe_snapshot(
                **common,
                market=Market.GOALS_TEAM,
                market_params={"team": team, "threshold": threshold},
                selection=choice,
                payout=ov,
            )
            if snap is not None:
                yield snap


def _handle_corner_total(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for threshold_key, asl in _iter_spd(market):
        threshold = _as_float(threshold_key)
        if threshold is None:
            continue
        for sel in asl:
            choice = _as_over_under(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if choice is None or ov is None:
                continue
            snap = _safe_snapshot(
                **common,
                market=Market.CORNER_TOTAL,
                market_params={"threshold": threshold},
                selection=choice,
                payout=ov,
            )
            if snap is not None:
                yield snap


_COMBO_1X2_OU_RE = re.compile(r"^\s*([1X2])\s*-\s*(Ov|Un)\s*$", flags=re.IGNORECASE)


def _handle_combo_1x2_ou(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for threshold_key, asl in _iter_spd(market):
        threshold = _as_float(threshold_key)
        if threshold is None:
            continue
        for sel in asl:
            m = _COMBO_1X2_OU_RE.match(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if m is None or ov is None:
                continue
            result = m.group(1).upper()
            choice = "OVER" if m.group(2).lower().startswith("o") else "UNDER"
            snap = _safe_snapshot(
                **common,
                market=Market.COMBO_1X2_OVER_UNDER,
                market_params={"result_1x2": result, "threshold": threshold},
                selection=choice,
                payout=ov,
            )
            if snap is not None:
                yield snap


_COMBO_BTTS_OU_RE = re.compile(r"^\s*(GG|NG)\s*-\s*(Ov|Un)\s*$", flags=re.IGNORECASE)


def _handle_combo_btts_ou(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for threshold_key, asl in _iter_spd(market):
        threshold = _as_float(threshold_key)
        if threshold is None:
            continue
        for sel in asl:
            m = _COMBO_BTTS_OU_RE.match(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if m is None or ov is None:
                continue
            bet = "YES" if m.group(1).upper() == "GG" else "NO"
            choice = "OVER" if m.group(2).lower().startswith("o") else "UNDER"
            snap = _safe_snapshot(
                **common,
                market=Market.COMBO_BTTS_OVER_UNDER,
                market_params={"bet_btts": bet, "threshold": threshold},
                selection=choice,
                payout=ov,
            )
            if snap is not None:
                yield snap


_SCORE_EXACT_RE = re.compile(r"^\s*(\d+)\s*[:\-]\s*(\d+)\s*$")


def _handle_score_exact(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for _, asl in _iter_spd(market):
        for sel in asl:
            m = _SCORE_EXACT_RE.match(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if m is None or ov is None:
                continue
            home_goals, away_goals = int(m.group(1)), int(m.group(2))
            snap = _safe_snapshot(
                **common,
                market=Market.SCORE_EXACT,
                market_params={"home": home_goals, "away": away_goals},
                selection=f"{home_goals}:{away_goals}",
                payout=ov,
            )
            if snap is not None:
                yield snap


_HT_FT_RE = re.compile(r"^\s*([1X2])\s*[\-/]\s*([1X2])\s*$", flags=re.IGNORECASE)


def _handle_ht_ft(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for _, asl in _iter_spd(market):
        for sel in asl:
            m = _HT_FT_RE.match(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if m is None or ov is None:
                continue
            ht, ft = m.group(1).upper(), m.group(2).upper()
            snap = _safe_snapshot(
                **common,
                market=Market.SCORE_HT_FT,
                market_params={"ht": ht, "ft": ft},
                selection=f"{ht}/{ft}",
                payout=ov,
            )
            if snap is not None:
                yield snap


_MULTIGOL_RANGE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*(?:gol)?\s*$", flags=re.IGNORECASE)


def _handle_multigol(market: dict[str, Any], meta: EventMeta) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for _, asl in _iter_spd(market):
        for sel in asl:
            m = _MULTIGOL_RANGE_RE.match(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if m is None or ov is None:
                continue
            lower, upper = int(m.group(1)), int(m.group(2))
            snap = _safe_snapshot(
                **common,
                market=Market.MULTIGOL,
                market_params={"lower": lower, "upper": upper},
                selection=f"{lower}-{upper}",
                payout=ov,
            )
            if snap is not None:
                yield snap


def _handle_multigol_team(
    market: dict[str, Any], meta: EventMeta, *, team: str
) -> Iterator[OddsSnapshot]:
    common = _common_snapshot_kwargs(meta, market)
    for _, asl in _iter_spd(market):
        for sel in asl:
            m = _MULTIGOL_RANGE_RE.match(str(sel.get("sn") or ""))
            ov = _as_float(sel.get("ov"))
            if m is None or ov is None:
                continue
            lower, upper = int(m.group(1)), int(m.group(2))
            snap = _safe_snapshot(
                **common,
                market=Market.MULTIGOL_TEAM,
                market_params={"team": team, "lower": lower, "upper": upper},
                selection=f"{lower}-{upper}",
                payout=ov,
            )
            if snap is not None:
                yield snap


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

# Markets we intentionally skip without logging, because they exist in Goldbet
# but don't map onto the shared ``Market`` enum. Kept explicit (instead of
# silently falling through) so new Goldbet market-name variants still reach
# the "unmapped" logger.
_EXPLICIT_SKIP: set[str] = {
    # Half-time 1X2 / DC / BTTS are real markets but we have no half-result
    # code in the engine yet.
    "1X2 1T",
    "1X2 2T",
    "GG/NG 1T",
    "GG/NG 2T",
    "DC 1T",
    "DC 2T",
    # Parity / Draw No Bet / Handicap don't have Market enum slots.
    "P/D",
    "P/D 1T",
    "P/D 2T",
    "P/D Casa",
    "P/D Ospite",
    "Draw No Bet",
    "Draw No Bet 1T",
    "Draw No Bet 2T",
    "Away No Bet",
    "Home No Bet",
    "1X2 H",
    "1T 1X2 H",
    "2T 1X2 H",
    # Bucketed totals (non-OU enumerations).
    "Totale Angoli",
    "Somma Gol",
    "Somma Gol 1T",
    "Somma Gol 2T",
    "Somma Gol Totale",
    "Somma Gol Casa",
    "Somma Gol Ospite",
    # VAR / special-match / penalty / card-coach markets don't fit the engine.
    "Arbitro Consulta VAR",
    "1X2 + Arbitro Consulta VAR",
    # Team-win combos and goal-team yes/no don't have a clean enum home.
    "Vince o Avanti di 2 Casa",
    "Vince o Avanti di 2 Ospite",
    "Segna Gol Team Casa",
    "Segna Gol Team Ospite",
    "GG o Over 2.5",
    # Combo Multigol variants (handled via base Multigol handler; combos with
    # 1X2 / DC are tracked under their own enum slots if a future mapping is
    # added).
    "1X2 + GG/NG",
}


@dataclass(frozen=True)
class _UnmappedLog:
    """One-time dedupe record for "unknown market" warnings."""

    seen: set[str]

    def note(self, mn: str) -> bool:
        if mn in self.seen:
            return False
        self.seen.add(mn)
        return True


def _classify(mn: str) -> str | None:
    """Return a stable dispatch key for a Goldbet ``mn``, or ``None`` to skip.

    Skip semantics:
    - ``"SKIP"`` → known-but-unmapped; reach :data:`_EXPLICIT_SKIP`
    - ``None``   → truly unknown; logged once per run

    :param mn: raw Goldbet market name
    :return: dispatch key, ``"SKIP"``, or ``None``
    """
    name = mn.strip()
    if not name:
        return None

    if name in _EXPLICIT_SKIP:
        return "SKIP"

    # Exact dispatches first.
    exact = {
        "1X2": "match_1x2",
        "DC": "double_chance",
        "U/O": "goals_ou",
        "U/O 1T": "halves_ou_1",
        "U/O 2T": "halves_ou_2",
        "GG/NG": "btts",
        "1X2 + U/O": "combo_1x2_ou",
        "GG/NG + U/O": "combo_btts_ou",
        "Esito 1T/Finale": "ht_ft",
        "U/O Angoli": "corner_total",
        "U/O Casa": "team_ou_home",
        "U/O Ospite": "team_ou_away",
        " Multigol": "multigol",
        "Multigol": "multigol",
        "MultiGol Casa": "multigol_home",
        "MultiGol Ospite": "multigol_away",
        " MultiGol Ospite": "multigol_away",
        "MultiGol Casa 1T": "multigol_home",
        "MultiGol Ospite 1T": "multigol_away",
    }
    if name in exact:
        return exact[name]

    # Prefix / regex dispatches.
    if name.startswith("Ris.Esatto"):
        return "score_exact"
    if re.match(r"^U/O Angoli(?:\s*[12]T)?$", name):
        return "corner_total"

    return None


def parse_markets(
    event_payload: dict[str, Any],
    meta: EventMeta,
    *,
    unmapped: _UnmappedLog | None = None,
) -> Iterable[OddsSnapshot]:
    """Parse the ``mmkW`` dict of a Goldbet event-detail payload.

    :param event_payload: the full JSON returned by ``getDetailsEventAams``;
        the parser looks for ``leo[0].mmkW``
    :param meta: per-event metadata that every snapshot inherits
    :param unmapped: shared "seen unknown market" set, so a long scrape
        doesn't log the same "???" mn hundreds of times
    :yield: validated :class:`OddsSnapshot` rows (never raises on a bad block)
    """
    if unmapped is None:
        unmapped = _UnmappedLog(seen=set())

    leo = event_payload.get("leo") or []
    if not leo:
        return
    event = leo[0]
    if not isinstance(event, dict):
        return
    mmkw = event.get("mmkW") or {}
    if not isinstance(mmkw, dict):
        return

    for key, market in mmkw.items():
        if not isinstance(market, dict):
            continue
        mn = str(market.get("mn") or "").strip()
        if not mn:
            continue

        dispatch = _classify(mn)
        if dispatch is None:
            if unmapped.note(mn):
                logger.info(
                    "goldbet.unmapped_market",
                    mn=mn,
                    key=key,
                    event_id=meta.bookmaker_event_id,
                )
            continue
        if dispatch == "SKIP":
            continue

        try:
            yield from _dispatch(dispatch, market, meta)
        except Exception as e:  # defensive: one bad block must not kill an event
            logger.warning(
                "goldbet.market_parse_error",
                mn=mn,
                key=key,
                event_id=meta.bookmaker_event_id,
                error=str(e),
            )


def _dispatch(  # noqa: PLR0912  -- dispatcher over the Goldbet market taxonomy
    key: str, market: dict[str, Any], meta: EventMeta
) -> Iterator[OddsSnapshot]:
    if key == "match_1x2":
        yield from _handle_1x2(market, meta)
    elif key == "double_chance":
        yield from _handle_double_chance(market, meta)
    elif key == "goals_ou":
        yield from _handle_goals_ou(market, meta)
    elif key == "halves_ou_1":
        yield from _handle_halves_ou(market, meta, half=1)
    elif key == "halves_ou_2":
        yield from _handle_halves_ou(market, meta, half=2)
    elif key == "btts":
        yield from _handle_btts(market, meta)
    elif key == "combo_1x2_ou":
        yield from _handle_combo_1x2_ou(market, meta)
    elif key == "combo_btts_ou":
        yield from _handle_combo_btts_ou(market, meta)
    elif key == "ht_ft":
        yield from _handle_ht_ft(market, meta)
    elif key == "score_exact":
        yield from _handle_score_exact(market, meta)
    elif key == "corner_total":
        yield from _handle_corner_total(market, meta)
    elif key == "team_ou_home":
        yield from _handle_team_ou(market, meta, team=meta.home_team)
    elif key == "team_ou_away":
        yield from _handle_team_ou(market, meta, team=meta.away_team)
    elif key == "multigol":
        yield from _handle_multigol(market, meta)
    elif key == "multigol_home":
        yield from _handle_multigol_team(market, meta, team=meta.home_team)
    elif key == "multigol_away":
        yield from _handle_multigol_team(market, meta, team=meta.away_team)


# ---------------------------------------------------------------------------
# Public module-level helpers used by the orchestrator
# ---------------------------------------------------------------------------

_EVENT_NAME_RE = re.compile(r"^\s*(.+?)\s*-\s*(.+?)\s*$")
_EVENT_DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2})$")

LEAGUE_BY_ID: dict[int, League] = {
    93: League.SERIE_A,
    26604: League.PREMIER_LEAGUE,
    95: League.LA_LIGA,
    84: League.BUNDESLIGA,
    86: League.LIGUE_1,
}


def parse_event_datetime(ed: str) -> datetime | None:
    """Parse Goldbet's ``ed`` string (``"dd-mm-YYYY HH:MM"``) into a datetime.

    Goldbet returns kickoff times in Europe/Rome without a timezone marker.
    Historically the whole pipeline is UTC-on-the-wire, so for the purposes of
    season bucketing and dedupe we normalize to midnight naive and let
    downstream consumers attach the tz tag where it matters.

    :param ed: raw event datetime string
    :return: naive :class:`datetime` or ``None`` if unparsable
    """
    m = _EVENT_DATE_RE.match(ed.strip())
    if m is None:
        return None
    dd, mm, yyyy, hh, mi = (int(x) for x in m.groups())
    try:
        return datetime(yyyy, mm, dd, hh, mi)
    except ValueError:
        return None


def split_event_name(en: str) -> tuple[str, str]:
    """Split ``"Home - Away"`` into ``(home, away)``.

    Both names are run through :func:`canonicalize_team` so downstream dedupe
    keys are stable across sources.

    :param en: raw ``en`` string from Goldbet
    :return: ``(home_canonical, away_canonical)`` — falls back to ``(en, "")``
        when the separator is missing
    """
    m = _EVENT_NAME_RE.match(en)
    if m is None:
        return en.strip(), ""
    return canonicalize_team(m.group(1)), canonicalize_team(m.group(2))


def infer_season(match_date: date) -> str:
    """European football season bucket (Aug→Jul) in the ``YYYY-YY`` form.

    :param match_date: kickoff date
    :return: e.g. ``"2025-26"``
    """
    start_year = match_date.year if match_date.month >= 8 else match_date.year - 1
    end_suffix = str((start_year + 1) % 100).zfill(2)
    return f"{start_year}-{end_suffix}"


def build_event_meta(
    event: dict[str, Any],
    *,
    captured_at: datetime,
    source: str,
    run_id: str,
    league_hint: League | None = None,
) -> EventMeta | None:
    """Build an :class:`EventMeta` from one entry of Goldbet's ``leo`` array.

    :param event: the event dict (from ``leo[i]`` or the per-event detail)
    :param captured_at: timestamp to stamp on every snapshot this event
        produces
    :param source: provenance tag (e.g. ``"goldbet-scraper"``)
    :param run_id: scrape-run identifier
    :param league_hint: optional :class:`League` override when the tournament
        id isn't one of the top-5 we hardcode
    :return: an :class:`EventMeta` ready to hand to :func:`parse_markets`, or
        ``None`` when the event is too malformed to use
    """
    ei = event.get("ei")
    en = event.get("en")
    ed = event.get("ed")
    ti = event.get("ti")
    if ei is None or not isinstance(en, str) or not isinstance(ed, str):
        return None

    dt = parse_event_datetime(ed)
    if dt is None:
        return None
    match_date = dt.date()
    home, away = split_event_name(en)
    if not home or not away:
        return None

    league = league_hint
    if league is None and isinstance(ti, int):
        league = LEAGUE_BY_ID.get(ti)

    season = infer_season(match_date)

    return EventMeta(
        bookmaker_event_id=str(ei),
        match_label=f"{home} - {away}",
        match_date=match_date,
        season=season,
        league=league,
        home_team=home,
        away_team=away,
        captured_at=captured_at,
        source=source,
        run_id=run_id,
    )


def make_unmapped_log() -> _UnmappedLog:
    """Return a fresh "unknown market" dedupe sink for one scrape run."""
    return _UnmappedLog(seen=set())
