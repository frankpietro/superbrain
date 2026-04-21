# Reference exemplars

Repos Gaia treats as **worth learning from**. Each entry is a pointer
for the harvest protocol (`docs/HOW_TO_HARVEST.md`): what this repo is
exemplary at, what's already been folded into Gaia from it, and
outstanding notes of "this is nice, not yet promoted".

This file is **write-only from the harvest flow** — every harvest
session that produces a promoted PR must append (or update) a note
under the source repo's entry. Do not edit a section to "improve" an
existing entry retroactively; promotions are immutable history.

## How to add a new entry

Follow the template; keep each entry to ≤15 lines.

```markdown
## <owner>/<repo>

- Repo: <url>
- Exemplary for: <1–3 concerns, comma-separated>
- Last harvested: <YYYY-MM-DD> @ <short-sha>
- Applied to Gaia via:
  - <PR link or commit SHA> — <one-line summary>
- Pending (noticed, not yet promoted):
  - <one-line observation>  <!-- move to 'Applied' when promoted -->
- Dropped (considered, explicitly rejected):
  - <one-line observation> — <reason> — <date>
```

Remove "Pending" bullets once they're promoted or dropped; this
file should never grow unbounded.

## Seed exemplars

> Starter list. The harvest agent extends this file as work is
> done; the list itself is subject to promote/drop cadence. If a
> repo becomes unmaintained, CVE-ridden, or moves to a direction
> that no longer aligns with Gaia, move it to `## Retired` at the
> bottom of the file with a reason.

### tiangolo/full-stack-fastapi-template

- Repo: https://github.com/tiangolo/full-stack-fastapi-template
- Exemplary for: FastAPI project layout, Alembic migrations,
  SQLModel usage, docker-compose dev loop, pytest + DB fixtures.
- Last harvested: — (never)
- Applied to Gaia via: — (none yet)
- Pending:
  - Multi-stage Dockerfile for FastAPI (`python:slim` builder → runtime).
  - `conftest.py` pattern: create + drop a throwaway test DB per session.
  - `alembic/env.py` with offline + online migration modes split cleanly.

### frankpietro/forno-mastrella

- Repo: https://github.com/frankpietro/forno-mastrella
- Exemplary for: single-VPS (Hetzner) + Docker Compose + Caddy
  deploy; Argon2id cost-tuning pattern; `login_events` audit-log
  table; GDPR export/delete endpoints.
- Last harvested: — (operator's own reference; informally mirrored
  into archetypes/multi-tenant-saas.md at Gaia bootstrapping time)
- Applied to Gaia via:
  - `archetypes/multi-tenant-saas.md` — whole archetype derives
    from this repo's stack.
- Pending:
  - Backup script shape (`pg_dump` → `/var/backups/<app>` via cron)
    deserves its own pattern (`patterns/self-hosted-backups.md`).

### frankpietro/side-quest

- Repo: https://github.com/frankpietro/side-quest
- Exemplary for: client-only React + Vite + Tailwind + shadcn SPA,
  `zustand` with `persist`, `_hasHydrated` gating pattern,
  route-level theme-flash prevention.
- Last harvested: — (operator's own reference; informally mirrored
  into `archetypes/personal-web-spa.md`)
- Applied to Gaia via:
  - `archetypes/personal-web-spa.md` — whole archetype, including
    the "Leaflet CSS / theme flash / hydration" gotchas.
- Pending:
  - Nothing outstanding.

### astral-sh/uv

- Repo: https://github.com/astral-sh/uv
- Exemplary for: Python package management UX, release engineering
  (release-please + signed releases), Rust CLI patterns, extensive
  CI matrix across Python versions + OSes.
- Last harvested: — (never)
- Applied to Gaia via:
  - `preferences.md` → Language and runtime (uv as the default
    Python package manager) — adopted on community evidence, not
    yet formally harvested.
- Pending:
  - Release workflow (`.github/workflows/release.yml`) as a
    `patterns/release-engineering.md` candidate.
  - CI matrix config as a reference for
    `patterns/ci-matrix-strategy.md` (already drafted in patterns/).

### vitejs/vite

- Repo: https://github.com/vitejs/vite
- Exemplary for: plugin architecture, zero-config defaults with
  escape hatches, dev/build binary split, docs as a first-class
  citizen.
- Last harvested: — (never)
- Applied to Gaia via:
  - `preferences.md` → Frontend (Vite as the SPA default).
- Pending:
  - "Zero-config defaults + targeted escape hatches" could become
    a CLI-tool design pattern; not yet clear if it generalises
    enough to promote.

## Retired

> Entries removed because the repo no longer meets the bar. Each
> retired entry keeps its final reason so we don't re-harvest by
> accident.

_(none yet)_

---

## Invariants agents MUST preserve

- **Never** delete an "Applied to Gaia via" bullet; promotions are
  history.
- **Never** edit another agent's Applied / Dropped bullets to
  "improve" them; add a new bullet, dated, with the clarification.
- **Always** update this file in the same PR as the harvest that
  produced the change. A promoted pattern / archetype-learning /
  preferences-entry without an `exemplars.md` bullet cannot be
  traced back — that's a regression.
- **Do not** include private repos or repos behind login walls.
  If the user cites one, capture the learning via `docs/knowledge.md`
  in the relevant project; do not add it here.
