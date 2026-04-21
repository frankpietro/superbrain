"""Trim spike Sisal payloads into test fixtures.

Reads the raw spike payloads under
``../superbrain-phase-3-spike-sisal/data/spike/sisal/`` and writes trimmed
copies into ``tests/fixtures/bookmakers/sisal/``. Each trimmed fixture keeps
real structure but discards payload bloat (e.g. full-league event lists are
reduced to 2 events, ``scommessaMap`` is filtered to the families we
assert against).

Run once (or any time the raw spike payloads are refreshed)::

    uv run python scripts/build_sisal_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SPIKE_DIR = Path("/Users/frankp/PersonalProjects/superbrain-phase-3-spike-sisal/data/spike/sisal")
OUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "bookmakers" / "sisal"

COVERED_MARKET_DESCRIPTIONS: set[str] = {
    "1X2 ESITO FINALE",
    "1 TEMPO: ESITO 1X2",
    "2 TEMPO: ESITO 1X2",
    "DOPPIA CHANCE",
    "DOPPIA CHANCE TEMPO X",
    "UNDER/OVER",
    "UNDER/OVER TEMPO X",
    "U/O SQUADRA X",
    "GOAL/NOGOAL",
    "GOAL/NOGOAL TEMPO X",
    "MULTIGOAL",
    "MULTIGOAL TEMPO X",
    "MULTIGOAL SQUADRA X",
    "RISULTATO ESATTO 26 ESITI",
    "ESITO 1 TEMPO/FINALE",
    "1 TEMPO: 1X2 CORNER",
    "1 TEMPO: 1X2 HANDICAP CORNER",
    "COMBO: 1X2 + U/O",
    "COMBO: GOAL/NOGOAL + U/O",
}

TOP5_KEYS = {"1-209", "1-331", "1-228", "1-570", "1-781"}


def _find(path_prefix: str) -> Path:
    matches = sorted(SPIKE_DIR.glob(f"*{path_prefix}*.json"))
    if not matches:
        raise FileNotFoundError(path_prefix)
    return matches[-1]


def trim_tree() -> dict[str, Any]:
    raw = json.loads(_find("alberaturaPrematch").read_text())
    trimmed: dict[str, Any] = {}
    disciplina = raw.get("disciplinaMap", {})
    trimmed["disciplinaMap"] = {"1": disciplina.get("1")} if disciplina.get("1") else {}
    full_map = raw.get("manifestazioneMap", {})
    trimmed["manifestazioneMap"] = {k: full_map[k] for k in TOP5_KEYS if k in full_map}
    trimmed["manifestazioneListByDisciplinaTutti"] = {"1": sorted(TOP5_KEYS)}
    trimmed["eventsNumberByManifestazioneTutti"] = {
        k: raw.get("eventsNumberByManifestazioneTutti", {}).get(k, 10) for k in TOP5_KEYS
    }
    return trimmed


def trim_events(league_slug: str, keep_events: int = 2) -> dict[str, Any]:
    raw = json.loads(_find(f"events-{league_slug}").read_text())
    events = (raw.get("avvenimentoFeList") or [])[:keep_events]
    # Drop the heavy default-cluster bundles: the production scraper only
    # uses the event list from this endpoint and re-fetches per-event
    # market bundles via ``schedaAvvenimento``.
    slim_events = [_slim_event(ev) for ev in events]
    return {
        "avvenimentoFeList": slim_events,
        "scommessaMap": {},
        "infoAggiuntivaMap": {},
    }


def _slim_ia(iv: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "posizione",
        "descrizione",
        "key",
        "codicePalinsesto",
        "codiceAvvenimento",
        "codiceScommessa",
        "idInfoAggiuntiva",
        "soglia",
        "esitoList",
        "stato",
        "shortDescription",
        "teamIds",
        "competitorList",
    )
    slim = {k: iv[k] for k in keep if k in iv}
    slim_esiti = []
    for e in iv.get("esitoList", []):
        slim_esiti.append(
            {k: e[k] for k in ("codiceEsito", "descrizione", "quota", "stato") if k in e}
        )
    slim["esitoList"] = slim_esiti
    return slim


def _slim_sc(v: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "posizione",
        "descrizione",
        "key",
        "codicePalinsesto",
        "codiceAvvenimento",
        "codiceScommessa",
        "codiceDisciplina",
        "codiceManifestazione",
        "stato",
        "infoAggiuntivaKeyDataList",
    )
    return {k: v[k] for k in keep if k in v}


def _slim_event(ev: dict[str, Any]) -> dict[str, Any]:
    drop = {
        "externalProviderInfoList",
        "scommessaKeyDataList",
        "livescore",
        "preAlertPromozionaliRedax",
        "postAlertPromozionaliRedax",
        "legaturaAAMS",
        "firstScommessa",
    }
    return {k: v for k, v in ev.items() if k not in drop}


def trim_event_markets() -> dict[str, Any]:
    raw = json.loads(_find("markets-36171-19").read_text())
    avvenimento = _slim_event(raw.get("avvenimentoFe") or {})
    sc = raw.get("scommessaMap", {}) or {}
    ia = raw.get("infoAggiuntivaMap", {}) or {}

    kept_sc: dict[str, Any] = {}
    kept_ia: dict[str, Any] = {}
    for k, v in sc.items():
        desc = str(v.get("descrizione") or "").strip()
        if desc not in COVERED_MARKET_DESCRIPTIONS:
            continue
        kept_sc[k] = _slim_sc(v)
        prefix = f"{k}-"
        for ik, iv in ia.items():
            if ik.startswith(prefix):
                kept_ia[ik] = _slim_ia(iv)
    return {
        "avvenimentoFe": avvenimento,
        "scommessaMap": kept_sc,
        "infoAggiuntivaMap": kept_ia,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "tree.json").write_text(
        json.dumps(trim_tree(), ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    for slug in ("serie_a", "premier_league", "bundesliga", "la_liga", "ligue_1"):
        try:
            payload = trim_events(slug)
        except FileNotFoundError:
            continue
        (OUT_DIR / f"events-{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
    (OUT_DIR / "markets-36171-19.json").write_text(
        json.dumps(trim_event_markets(), ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    for f in sorted(OUT_DIR.glob("*.json")):
        print(f"{f.name}: {f.stat().st_size} bytes")


if __name__ == "__main__":
    main()
