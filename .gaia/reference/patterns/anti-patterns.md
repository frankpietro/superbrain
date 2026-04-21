# Anti-patterns

Named practices Gaia has seen in the wild and actively discourages.
Each entry exists because the mistake is common enough, and the cost
of making it high enough, that calling it out by name saves time.

Labelling something an anti-pattern is a **strong claim**. Entries
live here only if:

1. The practice is genuinely common (not a strawman).
2. There is a specific, named alternative.
3. The cost of the anti-pattern is concrete, not theoretical.

One entry per anti-pattern. Keep each entry short; link to Gaia's
preferred alternative for the full story.

---

## Lockfile drift: committing manifest without lockfile, or two lockfiles

**Seen as**: `package.json` committed without `package-lock.json` /
`uv.lock`; or both `package-lock.json` AND `bun.lockb` in the same
commit; or `poetry.lock` alongside `uv.lock`.

**Cost**: reproducibility is a fiction. CI builds something
different from local, prod is different from CI, the "bug only
happens on Julie's machine" emerges.

**Alternative**: exactly one lockfile per concern, committed.
`gaia adopt` flags this as `missing` (no lockfile) or `divergent`
(wrong package manager). See
`preferences.md` → Language and runtime.

---

## Non-idempotent migrations

**Seen as**: Alembic migrations that assume specific starting state
(`INSERT INTO x …` without `ON CONFLICT`), or Django migrations that
delete + recreate tables in the same revision.

**Cost**: running the migration twice (e.g. after a mid-deploy
crash) corrupts data or fails loudly. Recovery requires manual DB
intervention on live production.

**Alternative**: every migration is idempotent. Every backfill uses
`ON CONFLICT DO NOTHING` or explicit "already-migrated?" checks.
See `patterns/zero-downtime-migrations.md`.

---

## `any` as the escape hatch

**Seen as**: `any`/`unknown` sprinkled across a TypeScript codebase;
`# type: ignore` comments scattered across Python; `mypy` config
with broad `ignore_errors = True` per module.

**Cost**: the type system's value approaches zero asymptotically.
Each new `any` lowers the bar; eventually everyone assumes the
types are lies and reads the code instead.

**Alternative**: use `unknown` + narrowing in TS, `typing.Protocol`
+ `cast` in Python, and put a comment explaining the narrow
constraint being sidestepped. Prefer fixing the type over silencing
the checker. If a whole module must be excluded, record it in
`docs/knowledge.md` with a trigger to revisit.

---

## "Works on main" as a substitute for CI

**Seen as**: no CI, or CI that only runs on `main` after merge, or
CI that only runs on-demand. PRs get merged because "it passed
locally".

**Cost**: regressions land in main. Bisects to find who broke it
become routine. New contributors burn their first week fighting the
build.

**Alternative**: required-check CI on PRs, before merge. See
`patterns/ci-matrix-strategy.md` for the shape.

---

## Storing secrets in the repo

**Seen as**: `.env` committed to git (even "dev-only"); API keys in
code comments; `config.py` with real credentials under "remember to
change before prod".

**Cost**: every past contributor has a copy of the secret forever.
Rotation requires purging git history AND notifying everyone.
GitHub secret-scanning catches some but not all.

**Alternative**: `.env` in `.gitignore`, `.env.example` committed
with placeholder values; real secrets in the deploy provider's
secret store (Fly secrets, Vercel env, VPS env file with tight
permissions). For personal dev boxes, plaintext is acceptable per
the operating principle in `AGENTS.md`. See `preferences.md` →
DevOps & deploy.

---

## Matplotlib in new projects

**Seen as**: `import matplotlib.pyplot as plt` in any Python data /
web project started after 2022.

**Cost**: this is a Gaia operator-specific veto. Plots don't
compose into dashboards without re-writing; static images don't
survive a theme change; the rendering surface is not interactive.

**Alternative**: `plotly.graph_objects`. See `preferences.md` →
Data & analytics.

---

## Editing Hex YAML by hand

**Seen as**: direct edits to the YAML Hex exports when the project
is represented as code.

**Cost**: Hex round-trips the YAML; hand edits regress on the next
sync, silently. Lost work.

**Alternative**: write all code in separate `.py` files and
reference them from Hex cells. Treat the YAML as Hex-owned. See
`preferences.md` → Data & analytics.

---

## Adding an orchestrator before it earns its weight

**Seen as**: an Airflow / Prefect / Dagster deployment for a pipeline
with 3 recurring jobs and no cross-job dependencies.

**Cost**: you now operate an orchestrator, not a pipeline. The
orchestrator's webserver, scheduler, and backend DB need care. The
time saved on DAGs is smaller than the time spent on orchestrator
ops.

**Alternative**: `cron` or `.github/workflows/cron.yml` until you
have >10 recurring jobs or real cross-job dependencies. Then adopt
a real orchestrator. See `archetypes/data-pipeline.md` →
Alternatives considered.

---

## Branch-only isolation for concurrent AI agents

**Seen as**: multiple Cursor (or Claude Code, Codex, …) agent
sessions opened on the same local repo, each auto-branching into its
own `agent/*` branch but sharing one working tree. The
`sessionStart` hook happily branches both; `git checkout` between
their branches silently clobbers the other agent's uncommitted work.

**Cost**: agents stash each other's edits; recovery requires
digging through `git stash list` to identify whose stash is whose;
files "mysteriously revert" mid-session. The symptom set is known
colloquially as "agents mixing files".

**Alternative**: one git worktree per concurrent agent session,
provisioned via `gaia session new`. Git's worktree primitive gives
HEAD + index + working-tree isolation; the shared `.git/objects`
keeps the disk cost low. See
`patterns/agent-worktree-sessions.md`. The `core/.cursor/hooks/auto-branch.sh`
hook refuses to auto-branch the main tree when sibling session
worktrees are already live.

---

## Pushing directly to `main` to "fix CI"

**Seen as**: bypassing branch protection, committing a "hotfix" to
unstick a build, then catching up the PR later.

**Cost**: whatever was broken stays broken in history; the PR that
was supposed to carry the change loses context; the next contributor
has to reason about two parallel fixes.

**Alternative**: open a small PR with the hotfix, merge it, rebase
the original PR on top. Two minutes slower, no history-surgery later.

---

> Gaia's own promotion and admission rules (when to add a pattern,
> when to name a new anti-pattern, second-occurrence requirement)
> live in [`docs/HOW_TO_HARVEST.md`](../../docs/HOW_TO_HARVEST.md)
> and [`docs/HOW_TO_PROMOTE.md`](../../docs/HOW_TO_PROMOTE.md), not
> here. This file is for project-level anti-patterns only.
