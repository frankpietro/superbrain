"""Meeting → event discovery for the Eurobet scraper.

Eurobet publishes the schedule across two feeds with complementary
coverage:

* ``top-disciplines`` (public, plain ``httpx``) ships the homepage
  carousel. Cheap, but editorial: on any given day it may skip one or
  two top-5 leagues (La Liga and Ligue 1 were absent in the discovery
  sample). Use as a ``push'' hint.
* ``detail-service/meeting/{discipline}/{meeting_slug}`` (Cloudflare
  gated, ``curl_cffi``) is the authoritative list for a given meeting:
  one ``dataGroupList`` entry per date with per-event ``eventInfo``
  tiles.

We call both and union on ``(program_code, event_code)`` so missing
coverage in either feed does not silently drop fixtures.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import structlog

from superbrain.core.models import League
from superbrain.scrapers.bookmakers.eurobet.client import EurobetClient, EurobetError

log = structlog.get_logger(__name__)

DISCIPLINE_CALCIO = "calcio"


EUROBET_LEAGUE_MEETINGS: dict[League, str] = {
    League.SERIE_A: "it-serie-a",
    League.PREMIER_LEAGUE: "ing-premier-league",
    League.BUNDESLIGA: "de-bundesliga",
    League.LA_LIGA: "es-liga",
    League.LIGUE_1: "fr-ligue-1",
}

EUROBET_MEETING_CODES: dict[int, League] = {
    21: League.SERIE_A,
    86: League.PREMIER_LEAGUE,
    4: League.BUNDESLIGA,
    79: League.LA_LIGA,
    14: League.LIGUE_1,
}


@dataclass(frozen=True)
class EurobetEventRef:
    """Minimal descriptor needed to hit the per-event markets endpoint."""

    program_code: int
    event_code: int
    meeting_slug: str
    event_slug: str
    meeting_code: int
    meeting_description: str
    kickoff: datetime
    home_team_raw: str
    away_team_raw: str
    betradar_match_id: str | None
    league: League | None
    source: str

    @property
    def event_id(self) -> str:
        """Stable bookmaker event id used for dedupe downstream."""
        return f"{self.program_code}-{self.event_code}"


async def discover_events(
    client: EurobetClient,
    *,
    leagues: Iterable[League],
    discipline_alias: str = DISCIPLINE_CALCIO,
    top_disciplines_errors: list[str] | None = None,
    per_meeting_errors: list[str] | None = None,
) -> dict[League, list[EurobetEventRef]]:
    """Enumerate Eurobet events for the requested leagues.

    Calls the homepage carousel first (best-effort) and then the
    per-meeting endpoint for each requested league. Merges the two
    sources and groups by :class:`League`. Failures per source and per
    meeting are logged and appended to the caller's optional error
    lists; the function never raises ``EurobetError`` out.

    :param client: open :class:`EurobetClient`
    :param leagues: requested :class:`League` set (order preserved)
    :param discipline_alias: discipline slug (default: ``calcio``)
    :param top_disciplines_errors: optional list the caller wants
        populated with any homepage-feed failures
    :param per_meeting_errors: optional list the caller wants populated
        with any per-meeting-feed failures, keyed by league
    :return: mapping league → list of :class:`EurobetEventRef`,
        deduped on ``(program_code, event_code)``
    """
    requested = list(leagues)
    per_league: dict[League, dict[tuple[int, int], EurobetEventRef]] = {
        league: {} for league in requested
    }

    try:
        payload = await client.fetch_top_disciplines(discipline_alias)
    except EurobetError as e:
        log.warning("eurobet.navigation.top_disciplines_failed", error=str(e))
        if top_disciplines_errors is not None:
            top_disciplines_errors.append(str(e))
    else:
        for ref in _parse_top_disciplines(payload):
            if ref.league is None or ref.league not in per_league:
                continue
            per_league[ref.league][(ref.program_code, ref.event_code)] = ref

    for league in requested:
        meeting_slug = EUROBET_LEAGUE_MEETINGS.get(league)
        if meeting_slug is None:
            continue
        try:
            payload = await client.fetch_meeting(
                discipline_alias=discipline_alias,
                meeting_slug=meeting_slug,
            )
        except EurobetError as e:
            log.warning(
                "eurobet.navigation.meeting_failed",
                league=league.value,
                meeting_slug=meeting_slug,
                error=str(e),
            )
            if per_meeting_errors is not None:
                per_meeting_errors.append(f"{league.value}:{e}")
            continue
        for ref in _parse_meeting(
            payload, league=league, meeting_slug=meeting_slug
        ):
            per_league[league][(ref.program_code, ref.event_code)] = ref

    return {league: list(by_key.values()) for league, by_key in per_league.items()}


def _parse_top_disciplines(payload: dict[str, Any]) -> list[EurobetEventRef]:
    result = payload.get("result")
    if not isinstance(result, list):
        return []
    out: list[EurobetEventRef] = []
    for meeting in result:
        if not isinstance(meeting, dict):
            continue
        items = meeting.get("itemList") or []
        meeting_code = _safe_int(meeting.get("meetingCode"))
        meeting_desc = str(meeting.get("meeting") or "")
        league = EUROBET_MEETING_CODES.get(meeting_code) if meeting_code is not None else None
        for item in items:
            if not isinstance(item, dict):
                continue
            ref = _event_ref_from_tile(
                item,
                fallback_meeting_code=meeting_code,
                fallback_meeting_desc=meeting_desc,
                league=league,
                source="top-disciplines",
            )
            if ref is not None:
                out.append(ref)
    return out


def _parse_meeting(
    payload: dict[str, Any],
    *,
    league: League,
    meeting_slug: str,
) -> list[EurobetEventRef]:
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    data_groups = result.get("dataGroupList") or []
    out: list[EurobetEventRef] = []
    for group in data_groups:
        if not isinstance(group, dict):
            continue
        items = group.get("itemList") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            ref = _event_ref_from_tile(
                item,
                fallback_meeting_code=None,
                fallback_meeting_desc=None,
                league=league,
                source=f"meeting:{meeting_slug}",
            )
            if ref is not None:
                out.append(ref)
    return out


def _event_ref_from_tile(
    item: dict[str, Any],
    *,
    fallback_meeting_code: int | None,
    fallback_meeting_desc: str | None,
    league: League | None,
    source: str,
) -> EurobetEventRef | None:
    ei = item.get("eventInfo") or {}
    program_code = _safe_int(ei.get("programCode"))
    event_code = _safe_int(ei.get("eventCode"))
    event_slug = str(ei.get("aliasUrl") or "").strip()
    if program_code is None or event_code is None or not event_slug:
        return None
    meeting_code = (
        _safe_int(ei.get("meetingCode"))
        if ei.get("meetingCode") is not None
        else fallback_meeting_code
    )
    meeting_desc = str(
        ei.get("meetingDescription") or fallback_meeting_desc or ""
    )
    meeting_slug = _meeting_slug_from_breadcrumb(item) or (
        EUROBET_LEAGUE_MEETINGS.get(league) if league else None
    )
    if meeting_slug is None:
        return None

    kickoff_ms = ei.get("eventData")
    if kickoff_ms is None:
        return None
    try:
        kickoff = datetime.fromtimestamp(int(kickoff_ms) / 1000.0, tz=UTC)
    except (TypeError, ValueError):
        return None

    home = str((ei.get("teamHome") or {}).get("description") or "").strip()
    away = str((ei.get("teamAway") or {}).get("description") or "").strip()
    if not home or not away:
        return None

    betradar = ei.get("matchId") or ei.get("programBetradarInfo") or None
    betradar_id: str | None
    if isinstance(betradar, dict):
        betradar_id = str(betradar.get("matchId") or betradar.get("id") or "") or None
    elif betradar is None:
        betradar_id = None
    else:
        betradar_id = str(betradar)

    resolved_league = (
        league
        or (
            EUROBET_MEETING_CODES.get(meeting_code)
            if meeting_code is not None
            else None
        )
    )

    return EurobetEventRef(
        program_code=program_code,
        event_code=event_code,
        meeting_slug=meeting_slug,
        event_slug=event_slug,
        meeting_code=meeting_code if meeting_code is not None else -1,
        meeting_description=meeting_desc,
        kickoff=kickoff,
        home_team_raw=home,
        away_team_raw=away,
        betradar_match_id=betradar_id,
        league=resolved_league,
        source=source,
    )


def _meeting_slug_from_breadcrumb(item: dict[str, Any]) -> str | None:
    bc = item.get("breadCrumbInfo") or {}
    nav = bc.get("navigationPathData") if isinstance(bc, dict) else None
    if not isinstance(nav, list):
        return None
    for node in nav:
        if isinstance(node, dict) and node.get("itemType") == "MEETING":
            slug = node.get("aliasUrl")
            if slug:
                return str(slug)
    return None


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def season_for(match_date: date) -> str:
    """European football season key for a match date (``YYYY-YY``).

    :param match_date: match date (UTC)
    :return: season code in ``YYYY-YY`` form
    """
    y = match_date.year
    start = y if match_date.month >= 7 else y - 1
    return f"{start}-{str((start + 1) % 100).zfill(2)}"


__all__ = [
    "DISCIPLINE_CALCIO",
    "EUROBET_LEAGUE_MEETINGS",
    "EUROBET_MEETING_CODES",
    "EurobetEventRef",
    "discover_events",
    "season_for",
]
