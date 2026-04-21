# Gaia reference — preferences, archetypes, patterns, exemplars (Tier 2)

This directory holds the operator's **preferences**, the
**application archetypes** Gaia knows about, the cross-cutting
**named patterns** Gaia has codified, and the curated list of
**exemplar repos** Gaia has learned from. It is seeded into every
target project at `.gaia/reference/` so agents can consult it when
they need to pick tech, apply a recipe, or trace a decision.

## Files

- [`preferences.md`](./preferences.md) — the operator's default tools
  per concern (package managers, test runners, lint, deploy
  targets). Project-agnostic; consult it before proposing a library
  or platform.
- [`archetypes/`](./archetypes/) — one reference stack per
  application shape. Each archetype is a short markdown file with
  *when to use*, *reference stack*, *why*, *known gotchas*, and the
  *seed command*.
- [`patterns/`](./patterns/) — named, reusable technical recipes
  (zero-downtime migrations, CI matrix strategy, anti-patterns, …).
  Not defaults — consulted on demand when a concern matches. See
  [`patterns/README.md`](./patterns/README.md) for what belongs
  there and what doesn't.
- [`exemplars.md`](./exemplars.md) — curated repos Gaia considers
  worth learning from, with per-repo notes on what was harvested and
  what's still pending. Append-only from the harvest flow; see
  [`docs/HOW_TO_HARVEST.md`](../docs/HOW_TO_HARVEST.md).

## How to pick an archetype

```
Is the app client-only? (no users, no server, localStorage is fine)
  └─ yes → personal-web-spa
  └─ no  ↓

Does it have authenticated users with server-side per-tenant data?
  └─ yes → multi-tenant-saas
  └─ no  ↓

Is it a terminal-first utility?
  └─ yes → cli-tool
  └─ no  ↓

Is the primary output data / reports / charts?
  └─ yes → data-pipeline
  └─ no  ↓

None fits? Start from the closest archetype, document the delta in
docs/knowledge.md, and — once you've shipped something — open a PR
against Gaia to add a new archetype here.
```

## Current archetypes

| Archetype | One-liner | Reference project |
|-----------|-----------|-------------------|
| [`personal-web-spa`](./archetypes/personal-web-spa.md) | Client-only game/tool/portfolio; Vite+React+Tailwind+shadcn+zustand+Vercel. | [`side-quest`](https://github.com/frankpietro/side-quest) |
| [`multi-tenant-saas`](./archetypes/multi-tenant-saas.md) | Product with auth and per-user server data; FastAPI+Postgres+uv+Argon2id+Vite/React+Fly or VPS. | [`forno-mastrella`](https://github.com/frankpietro/forno-mastrella) |
| [`cli-tool`](./archetypes/cli-tool.md) | Terminal utility; Python+uv+typer or plain bash with one entry point. | Gaia itself |
| [`data-pipeline`](./archetypes/data-pipeline.md) | Batch analytics / ETL / reports; Python+uv+polars/duckdb+plotly.graph_objects. | (none yet) |

## Adding a new archetype

See [`docs/HOW_TO_AUTHOR_ARCHETYPE.md`](../docs/HOW_TO_AUTHOR_ARCHETYPE.md)
in the Gaia repo. In short:

1. Copy an existing archetype file as a template.
2. Fill the five sections (when to use, reference stack, why, known
   gotchas, seed command).
3. Add a row to the table above and to the decision tree.
4. Open a PR against Gaia.

Criteria for "is this a new archetype?": the *shape* of the
application differs enough that the reference stack differs. If the
difference is only in one or two libraries, stay in the existing
archetype and note the variant in the project's own
`docs/knowledge.md`.
