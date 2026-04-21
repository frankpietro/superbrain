"""Team-name canonicalization.

Three-layer pipeline:

1. ``normalize_team_name`` — cosmetic cleanup (trim, collapse whitespace).
2. ``canonicalize_team`` — maps any known variant to its canonical spelling
   via the ``CANONICAL_ALIASES`` dictionary.
3. ``match_team_name`` — picks the best canonical name from an explicit
   whitelist (useful for joining a scraped row against an already-normalized
   list of teams for a given league).

The canonical spelling is the one used throughout the data lake, the engine,
the analytics layer, and the API. Sources disagree constantly (Italian
bookmakers italianize, football-data.co.uk abbreviates, Understat accents
differently), so everything must funnel through here before it is stored.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from superbrain.core.team_aliases import CANONICAL_ALIASES


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


_LOOKUP: dict[str, str] = {}
for _alt, _canonical in CANONICAL_ALIASES.items():
    _LOOKUP[_alt.lower()] = _canonical
    _stripped = _strip_accents(_alt.lower())
    if _stripped != _alt.lower():
        _LOOKUP[_stripped] = _canonical


def normalize_team_name(name: str) -> str:
    """Cosmetic cleanup: trim and collapse whitespace.

    :param name: raw team name
    :return: trimmed, whitespace-collapsed name (case and accents preserved)
    """
    if not isinstance(name, str):
        return str(name)
    result = name.strip()
    return re.sub(r"\s+", " ", result)


@lru_cache(maxsize=2048)
def canonicalize_team(name: str) -> str:
    """Map any team-name variant to its canonical spelling.

    Lookups are attempted in this order: exact, accent-stripped,
    hyphen-stripped. Unknown names are returned as-is after cosmetic
    normalization — logs should flag these and the alias dict updated.

    :param name: raw team name from any source
    :return: canonical spelling (or the normalized input if unknown)
    """
    cleaned = normalize_team_name(name)
    key = cleaned.lower()

    if key in _LOOKUP:
        return _LOOKUP[key]

    stripped = _strip_accents(key)
    if stripped in _LOOKUP:
        return _LOOKUP[stripped]

    no_hyphens = key.replace("-", " ")
    if no_hyphens in _LOOKUP:
        return _LOOKUP[no_hyphens]

    return cleaned


def match_team_name(name: str, available_names: list[str]) -> str:
    """Pick the best name from a whitelist, using canonicalization as the pivot.

    :param name: team name from any source
    :param available_names: canonical-style whitelist to match against
    :return: the matched entry from ``available_names`` (or the input if no
        match is found)
    """
    canonical = canonicalize_team(name)
    canon_lower = canonical.lower()

    for avail in available_names:
        if avail.lower() == canon_lower:
            return avail
    for avail in available_names:
        if canonicalize_team(avail).lower() == canon_lower:
            return avail
    name_lower = name.lower().strip()
    for avail in available_names:
        if avail.lower().strip() == name_lower:
            return avail
    for avail in available_names:
        avail_low = avail.lower()
        if canon_lower in avail_low or avail_low in canon_lower:
            return avail
    stripped_canon = _strip_accents(canon_lower)
    for avail in available_names:
        stripped_avail = _strip_accents(avail.lower())
        if stripped_canon in stripped_avail or stripped_avail in stripped_canon:
            return avail
    return name


def normalize_for_url(component: str) -> str:
    """Produce a URL-safe slug (lowercase ASCII, hyphen-separated).

    :param component: arbitrary text component
    :return: ascii lowercase slug
    """
    if not component:
        return ""
    c = component.lower()
    c = _strip_accents(c)
    c = c.replace(" ", "-")
    c = re.sub(r"[^a-z0-9-]", "", c)
    return re.sub(r"-+", "-", c)


def split_match_string(match_str: str) -> tuple[str, str]:
    """Split ``Home-Away`` into canonical home and away team names.

    :param match_str: string of the form ``Home-Away``
    :return: ``(home, away)`` after canonicalization, or two sentinels when
        the input is malformed
    """
    if not isinstance(match_str, str) or "-" not in match_str:
        return "Unknown_Team1", "Unknown_Team2"
    left, right = match_str.split("-", maxsplit=1)
    return canonicalize_team(left.strip()), canonicalize_team(right.strip())


def canonicalize_match_string(match_str: str) -> str:
    """Return the ``Home-Away`` string with both names canonicalized.

    :param match_str: string of the form ``Home-Away``
    :return: canonicalized ``Home-Away``
    """
    home, away = split_match_string(match_str)
    return f"{home}-{away}"


def get_all_aliases(canonical_name: str) -> list[str]:
    """List every known alias that resolves to ``canonical_name``.

    :param canonical_name: canonical team spelling
    :return: every alias (lowercased) that maps to ``canonical_name``
    """
    return [a for a, c in CANONICAL_ALIASES.items() if c == canonical_name]


def validate_coverage(source_teams: list[str], source_name: str = "source") -> dict[str, str]:
    """Report the canonical form of every team from a source.

    :param source_teams: raw team names from ``source_name``
    :param source_name: label for logging; unused but kept for signature
        stability and to make call sites self-documenting
    :return: mapping from input name to canonical name (same-string means no
        alias hit was registered)
    """
    del source_name
    return {team: canonicalize_team(team) for team in source_teams}
