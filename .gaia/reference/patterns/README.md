# Gaia patterns

Named, reusable technical recipes that apply across multiple
archetypes. Patterns are **not defaults** — not every project needs
every pattern — but when a project's concern matches a pattern, the
agent should consult it before reinventing.

Seeded into every target at `.gaia/reference/patterns/`.

## How to use patterns

### As an agent working in a seeded project

When you're about to tackle a concern (add CI, add migrations,
rotate a secret, wire feature flags, structure logging, …), grep
this directory first:

```bash
ls .gaia/reference/patterns/
```

Pattern filenames are the concern they address
(`zero-downtime-migrations.md`, `ci-matrix-strategy.md`, …). If the
concern matches, read the pattern. If not, apply Gaia's default
(from `preferences.md`) or the archetype's recommendation, and
consider proposing a new pattern via the outbox (`gaia outbox add
--tier reference …`) if you find yourself reinventing the same
recipe twice.

### As the Gaia maintainer

Patterns are added:

- **Top-down** — by harvesting strong reference repos (see
  [`docs/HOW_TO_HARVEST.md`](../../docs/HOW_TO_HARVEST.md)).
  Findings classified as `pattern` land here.
- **Bottom-up** — by seeded projects queueing outbox entries
  tagged `reference`. The drain agent (see
  [`docs/HOW_TO_PROMOTE.md`](../../docs/HOW_TO_PROMOTE.md)) decides
  whether the entry fits as a `preferences.md` default, an
  archetype learning, or a named pattern.

Either way, one pattern per file; one file per PR.

## What belongs here (and what doesn't)

### Yes, a pattern:

- A named recipe that solves a recurring concern across archetypes.
- Has **at least two plausible application archetypes**. If it only
  makes sense for one, it goes in that archetype instead.
- Has a clear "when to use / when not to use".
- Names its trade-offs explicitly.

### No, not a pattern:

- A default tool (that's `preferences.md`).
- A full stack recommendation (that's `archetypes/`).
- A project-specific fix (that's `docs/knowledge.md` in the project).
- An anti-pattern (that's `anti-patterns.md`, same directory).
- A tutorial / howto / getting-started (not Gaia's job).

## Pattern file shape

Every pattern follows this template:

```markdown
# <Concern this pattern addresses>

## When to use

<2–4 bullets describing the situations in which this pattern
applies. Be specific about archetypes, project size, constraints.>

## When NOT to use

<2–3 bullets describing when a simpler approach wins, or when
this pattern would be overkill / counterproductive.>

## The recipe

<Numbered steps, concrete code or config snippets where useful.
Paraphrase from the source, never copy-paste verbatim from a
reference repo.>

## Trade-offs

- **Cost**: <complexity, runtime overhead, cognitive load>
- **Benefit**: <what problem it solves>
- **Alternatives**: <simpler or more complex choices and when they
  win>

## Failure modes

<Bulleted list of "what goes wrong if you apply this sloppily".>

## Evidence

<Where this pattern has been proven. Link to reference repos,
specs, talks, post-mortems. Always cite something — patterns
without evidence are just opinions.>

## See also

<Related patterns, archetype entries, preferences entries.>
```

## Current patterns

Run `ls reference/patterns/` in Gaia (or
`ls .gaia/reference/patterns/` in a seeded project) to see the
full list. Indicative entries at the time of writing:

- `zero-downtime-migrations.md` — expand/contract schema changes
  without blocking writes.
- `ci-matrix-strategy.md` — matrix builds for min+max supported
  runtime versions.
- `secrets-via-env-only.md` — the twelve-factor "config from env"
  pattern, with the small-project escape hatch.
- `anti-patterns.md` — named things NOT to do, with the reasoning.

## Adding a pattern

1. Have two exemplars or a strong published source; one repo's
   idea is not a pattern yet.
2. Follow the template above.
3. Keep it under ~200 lines; longer means you're writing a tutorial.
4. Run `./tests/test-seed.sh` to confirm seeding still works.
5. Update `reference/exemplars.md` if the pattern came from a
   harvest.

See [`HOW_TO_HARVEST.md`](../../docs/HOW_TO_HARVEST.md) → Phase 4
for the PR template.
