"""Canonical team-name alias dictionary.

This is the single source of truth for reconciling team names across data
sources. Keys are lowercased variants (and accent-stripped variants); values
are the canonical spelling used everywhere downstream.

Until the Phase 2 historical-data spike locks in a new canonical style, we
retain the FBRef spellings used by the legacy project, because our legacy
odds backfill already keys on them.

Extend this dict whenever a new source is added. Never rename an existing
canonical value without a data migration — everything downstream (Parquet
partitions, Simulations, analytics dashboards) reads these strings back.
"""

from __future__ import annotations

CANONICAL_ALIASES: dict[str, str] = {
    # ---- Italian translations (Sisal/Goldbet/Eurobet → canonical) ----
    "siviglia": "Sevilla",
    "barcellona": "Barcelona",
    "maiorca": "Mallorca",
    "verona": "Hellas Verona",
    # ---- Accent / hyphen differences ----
    "paris sg": "Paris S-G",
    "paris saint germain": "Paris S-G",
    "paris saint-germain": "Paris S-G",
    "psg": "Paris S-G",
    "saint etienne": "Saint-Étienne",
    "saint-etienne": "Saint-Étienne",
    "st etienne": "Saint-Étienne",
    "st. etienne": "Saint-Étienne",
    "atletico madrid": "Atlético Madrid",
    "atletico bilbao": "Athletic Club",
    "athletic bilbao": "Athletic Club",
    "cadiz": "Cádiz",
    "alaves": "Alavés",
    "leganes": "Leganés",
    "nimes": "Nîmes",
    "greuther furth": "Greuther Fürth",
    "koln": "Köln",
    "fc koln": "Köln",
    # ---- Abbreviation / full-name differences ----
    "manchester united": "Manchester Utd",
    "man united": "Manchester Utd",
    "man utd": "Manchester Utd",
    "manchester city": "Manchester City",
    "man city": "Manchester City",
    "newcastle": "Newcastle Utd",
    "newcastle united": "Newcastle Utd",
    "leeds": "Leeds United",
    "nottingham": "Nott'ham Forest",
    "nottingham forest": "Nott'ham Forest",
    "nott'ham forest": "Nott'ham Forest",
    "nottm forest": "Nott'ham Forest",
    "wolverhampton": "Wolves",
    "wolverhampton wanderers": "Wolves",
    "sheffield united": "Sheffield Utd",
    "sheffield utd": "Sheffield Utd",
    "west bromwich": "West Brom",
    "west bromwich albion": "West Brom",
    "eintracht frankfurt": "Eint Frankfurt",
    "eint. frankfurt": "Eint Frankfurt",
    "borussia dortmund": "Dortmund",
    "bayern munchen": "Bayern Munich",
    "bayern münchen": "Bayern Munich",
    "rb leipzig": "RB Leipzig",
    "rasen ballsport leipzig": "RB Leipzig",
    "bayer leverkusen": "Leverkusen",
    "borussia monchengladbach": "Gladbach",
    "monchengladbach": "Gladbach",
    "b. monchengladbach": "Gladbach",
    # ---- Prefix differences ----
    "real valladolid": "Valladolid",
    "real oviedo": "Oviedo",
    "real betis": "Betis",
    "real sociedad": "Real Sociedad",  # intentionally keep "Real" here
    # ---- Italian league specifics ----
    "internazionale": "Inter",
    "fc inter": "Inter",
    "inter milan": "Inter",
    "inter milano": "Inter",
    "ac milan": "Milan",
    "ac milano": "Milan",
    "as roma": "Roma",
    "ss lazio": "Lazio",
    "ssc napoli": "Napoli",
    "us lecce": "Lecce",
    # ---- French league specifics ----
    "paris fc": "Paris FC",
    "rc lens": "Lens",
    "rc strasbourg": "Strasbourg",
    "ogc nice": "Nice",
    "stade rennais": "Rennes",
    "stade de reims": "Reims",
    "as monaco": "Monaco",
    "olympique marseille": "Marseille",
    "olympique lyonnais": "Lyon",
    "olympique lyon": "Lyon",
    # ---- Spanish league specifics ----
    "rcd espanyol": "Espanyol",
    "rcd mallorca": "Mallorca",
    "ca osasuna": "Osasuna",
    "ud las palmas": "Las Palmas",
    "ud almeria": "Almería",
    "cd leganes": "Leganés",
    "sd eibar": "Eibar",
    "sd huesca": "Huesca",
    "rc celta": "Celta Vigo",
    "celta de vigo": "Celta Vigo",
    "rayo": "Rayo Vallecano",
    # ---- German league specifics ----
    "sc freiburg": "Freiburg",
    "1. fc koln": "Köln",
    "1. fc union berlin": "Union Berlin",
    "fc augsburg": "Augsburg",
    "tsg hoffenheim": "Hoffenheim",
    "vfb stuttgart": "Stuttgart",
    "vfl wolfsburg": "Wolfsburg",
    "vfl bochum": "Bochum",
    "sv werder bremen": "Werder Bremen",
    "werder": "Werder Bremen",
    "fc st. pauli": "St. Pauli",
    "hamburger sv": "Hamburger SV",
    "hertha berlin": "Hertha BSC",
    "hertha bsc": "Hertha BSC",
    "arminia bielefeld": "Arminia",
    "darmstadt": "Darmstadt 98",
    "sv darmstadt 98": "Darmstadt 98",
    "holstein kiel": "Holstein Kiel",
    "heidenheim": "Heidenheim",
    "1. fc heidenheim": "Heidenheim",
    "mainz": "Mainz 05",
    "1. fsv mainz 05": "Mainz 05",
    "schalke": "Schalke 04",
    "fc schalke 04": "Schalke 04",
}
