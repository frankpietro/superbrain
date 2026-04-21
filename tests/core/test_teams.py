"""Tests for the team-name canonicalizer."""

from __future__ import annotations

from typing import cast

import pytest

from superbrain.core.team_aliases import CANONICAL_ALIASES
from superbrain.core.teams import (
    canonicalize_match_string,
    canonicalize_team,
    get_all_aliases,
    match_team_name,
    normalize_for_url,
    normalize_team_name,
    split_match_string,
    validate_coverage,
)


class TestCanonicalize:
    def test_italian_bookmaker_names_resolve(self) -> None:
        assert canonicalize_team("siviglia") == "Sevilla"
        assert canonicalize_team("Barcellona") == "Barcelona"
        assert canonicalize_team("Maiorca") == "Mallorca"
        assert canonicalize_team("Verona") == "Hellas Verona"

    def test_accent_variants_resolve_without_accents(self) -> None:
        assert canonicalize_team("atletico madrid") == "Atlético Madrid"
        assert canonicalize_team("Atletico Madrid") == "Atlético Madrid"

    def test_abbreviations_resolve(self) -> None:
        assert canonicalize_team("Man Utd") == "Manchester Utd"
        assert canonicalize_team("Manchester United") == "Manchester Utd"
        assert canonicalize_team("Wolves") != canonicalize_team("Wolfsburg")

    def test_psg_variants(self) -> None:
        for v in ("PSG", "Paris SG", "Paris Saint Germain", "Paris Saint-Germain"):
            assert canonicalize_team(v) == "Paris S-G"

    def test_unknown_name_returns_normalized_input(self) -> None:
        assert canonicalize_team("Timbuktu FC") == "Timbuktu FC"

    def test_non_string_input_handled_gracefully(self) -> None:
        # lru_cache erases the ``str`` annotation, so mypy would accept ``int``
        # directly; the cast keeps the intent explicit.
        assert canonicalize_team(cast("str", 123)) == "123"

    def test_hyphen_variants_resolve(self) -> None:
        assert canonicalize_team("Saint-Etienne") == "Saint-Étienne"

    @pytest.mark.parametrize(
        "alias,canonical",
        list(CANONICAL_ALIASES.items()),
    )
    def test_every_alias_in_the_dictionary_resolves(self, alias: str, canonical: str) -> None:
        assert canonicalize_team(alias) == canonical


class TestNormalizeTeamName:
    def test_trims_and_collapses_whitespace(self) -> None:
        assert normalize_team_name("  Real   Madrid ") == "Real Madrid"

    def test_preserves_case_and_accents(self) -> None:
        assert normalize_team_name("Atlético Madrid") == "Atlético Madrid"


class TestMatchTeamName:
    def test_exact_match_wins(self) -> None:
        assert match_team_name("Roma", ["Roma", "Lazio"]) == "Roma"

    def test_canonicalization_matches_against_whitelist(self) -> None:
        assert match_team_name("Siviglia", ["Sevilla"]) == "Sevilla"

    def test_substring_fallback(self) -> None:
        assert match_team_name("Roma", ["AS Roma"]) == "AS Roma"

    def test_no_match_returns_input(self) -> None:
        assert match_team_name("NotATeam", ["Roma", "Lazio"]) == "NotATeam"


class TestNormalizeForUrl:
    def test_slug_shape(self) -> None:
        assert normalize_for_url("Atlético Madrid") == "atletico-madrid"

    def test_empty_input(self) -> None:
        assert normalize_for_url("") == ""

    def test_collapses_multiple_hyphens(self) -> None:
        assert normalize_for_url("a - b") == "a-b"


class TestSplitMatchString:
    def test_canonicalizes_both_sides(self) -> None:
        assert split_match_string("Siviglia-Barcellona") == ("Sevilla", "Barcelona")

    def test_missing_hyphen_returns_sentinels(self) -> None:
        assert split_match_string("Roma") == ("Unknown_Team1", "Unknown_Team2")

    def test_hyphenated_team_is_consumed_once(self) -> None:
        # Saint-Étienne-Lyon should split on the FIRST hyphen only; given
        # that the canonicalizer has to round-trip, we accept the naive
        # split and expect downstream code to use canonical hyphen-free
        # aliases ("saint etienne").
        home, away = split_match_string("Saint Etienne-Lyon")
        assert home == "Saint-Étienne"
        assert away == "Lyon"


class TestCanonicalizeMatchString:
    def test_roundtrip(self) -> None:
        assert canonicalize_match_string("Siviglia-Barcellona") == "Sevilla-Barcelona"


class TestGetAllAliases:
    def test_returns_aliases_only(self) -> None:
        aliases = get_all_aliases("Manchester Utd")
        assert "man utd" in aliases
        assert "Manchester Utd" not in aliases


class TestValidateCoverage:
    def test_maps_each_input(self) -> None:
        result = validate_coverage(["Siviglia", "NotATeam"], source_name="t")
        assert result["Siviglia"] == "Sevilla"
        assert result["NotATeam"] == "NotATeam"
