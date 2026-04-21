# Agent worktree sessions

## When to use

- Two or more Cursor agent sessions need to work on the **same local
  repo** at the same time — a feature split across slices, one agent
  reviewing while another implements, bugfix parallel to feature work.
- Any archetype where agents occasionally collide on the main working
  tree ("they stash each other's work", "my uncommitted edits
  disappeared"). Symptom set, not archetype-bound.
- A long-running task the agent wants to park (a rebase, a big
  migration) without blocking other agents from the same repo.

## When NOT to use

- **One agent, one task, one session.** The `sessionStart` auto-branch
  hook already isolates you on a branch; you don't need a separate
  worktree for solo work. The worktree model pays off only when
  parallelism is real.
- **Repos with gigabyte-sized working trees** (e.g. vendored LLM
  weights) where N copies of the tree would fill the disk. Either use
  shallow clones + sparse checkout, or serialize agents.
- **Projects with singleton runtime state** that cannot be duplicated
  (a single dev database listening on a well-known port, a single
  docker-compose stack binding :3000). The worktree gives you tree
  isolation, not port isolation — see "Failure modes" below.

## The recipe

### 1. Create the worktree with `gaia session new`

Each agent gets its own worktree under `<parent>/<repo>-agents/<slug>/`,
on a fresh branch `agent/<slug>` off the default branch.

```bash
gaia session new --slug feat-x
# -> creates ../<repo>-agents/feat-x/
# -> branch agent/feat-x off origin/<default-branch>
# -> symlinks top-level .env* (gitignored secrets only)
# -> runs .gaia/hooks/post-worktree.sh if present + executable
# -> opens a Cursor window on the worktree if `cursor` CLI is on PATH
```

The user ends up with a new Cursor window pointed at the worktree.
From the agent's perspective in that window, `git status`, `git diff`,
`git stash` all operate on its own isolated tree — no other session can
clobber it.

### 2. Work normally, commit, open a PR

Inside the worktree, the `sessionStart` hook recognizes it and emits a
welcome noting the session slug, skipping auto-branching (you're
already on `agent/<slug>`). Normal workflow: edit, commit on the
session branch, `git push -u origin HEAD`, open the PR.

### 3. Tear down with `gaia session done`

When the PR is merged (or the task is abandoned):

```bash
gaia session done --slug feat-x
# -> refuses if uncommitted work OR unmerged commits exist
# -> git worktree remove + git branch -d
# -> removes the entry from .git/gaia-sessions.json
```

Pass `--force` to bypass the safety checks when the user explicitly
accepts the loss.

### 4. Inspect the fleet with `gaia session list` / `gaia doctor`

```bash
gaia session list          # slug, branch, path, dirty flag
gaia doctor                # warns about orphans, stale sessions, prunable worktrees
```

`gaia doctor` runs the three session-health checks on every
invocation; weave it into the agent's session-start ritual in repos
where concurrent sessions are common.

## Per-project bootstrap: `.gaia/hooks/post-worktree.sh`

A new worktree is just a `git checkout` — it has no `node_modules/`,
no `.venv/`, none of the artifacts built by the project's install
step. If the project needs any of those before an agent can start
work, add an executable `.gaia/hooks/post-worktree.sh` to the repo.
`gaia session new` runs it inside the new worktree with three env
vars set:

- `GAIA_SESSION_SLUG`
- `GAIA_SESSION_BRANCH`
- `GAIA_SESSION_MAIN_REPO` (absolute path to the main checkout)

Typical contents:

```bash
#!/usr/bin/env bash
set -euo pipefail
# Reuse the main checkout's package cache where possible — each
# worktree copying a 500MB node_modules is wasteful.
ln -sfn "$GAIA_SESSION_MAIN_REPO/node_modules" ./node_modules
# ...or just install:
# npm ci
# uv sync
```

Keep it quiet and fast — the user is waiting for their new Cursor
window to become useful.

## Trade-offs

- **Cost.** N worktrees means N copies of the source tree. Fine for
  most projects; painful for repos north of a few GB. Cost of
  `node_modules` / `.venv` can be mitigated by the post-worktree
  symlink trick above.
- **Benefit.** Git itself guarantees tree + index + HEAD isolation
  between worktrees. No more "my stash vanished" or "my file reverted
  to someone else's branch". This is the only approach that actually
  closes the class of bug rather than papering over it.
- **Alternatives.**
  - *Branch-only isolation (the old default).* Cheap (no extra dir),
    but still shares the working tree — exactly the bug we're fixing.
  - *One Cursor window at a time, serialize all work.* Zero
    concurrency cost; no parallelism.
  - *Per-agent clones.* Full isolation, but the clones diverge from
    each other on every fetch and the user juggles N git remotes.
    Worktrees are strictly better because they share `.git/objects`.

## Failure modes

- **Dev-server / port conflicts.** Two worktrees each running
  `npm run dev` on `:3000` is a lost battle. Either only one agent
  runs the dev server, or parametrize the port (e.g. `PORT=$((3000 +
  $(echo $GAIA_SESSION_SLUG | cksum | cut -c1-2)))`), or document
  "only the main checkout runs services" in `docs/knowledge.md`.
- **Database / shared service state.** The same singleton dev DB is
  reachable from every worktree — one agent's migration clobbers the
  other agent's data. Use one dev DB per session (`gaia session new`'s
  post-worktree hook can provision it) or pin "migrations only run in
  the main checkout".
- **`.env` drift.** The symlink model means all worktrees share the
  main repo's secrets file. Great for read-only secrets; dangerous if
  the session is supposed to test with different credentials. Override
  by copying instead of symlinking in `post-worktree.sh`.
- **Branch name collisions.** Two sessions asking for the same
  `--slug` fail loudly at `git worktree add`. Keep slugs descriptive
  (`feat-trail-filter` beats `session-2`).
- **Orphaned worktrees.** If the user `rm -rf`'s the worktree dir by
  hand, `git worktree list` shows it as `prunable`. `gaia doctor`
  nudges you to `git worktree prune`. The registry file
  (`.git/gaia-sessions.json`) will flag the orphan on the next
  `doctor` run.
- **Long-lived sessions.** Worktrees accumulate. After ~3 days with
  uncommitted work, `gaia doctor` nags. Either commit/push or
  `gaia session done --force` to retire.

## Evidence

- Pattern is backed by git's own worktree machinery — a first-class
  primitive since Git 2.5 (2015), stable, no third-party dependency.
- The narrower "branch per session, shared tree" model that preceded
  this pattern — implemented by [`core/.cursor/hooks/auto-branch.sh`](../../core/.cursor/hooks/auto-branch.sh)
  alone — was shown in practice to allow cross-session stash
  collisions whenever two Cursor windows were open on the same repo.
  The worktree split is what actually fixes the class of bug.
- Atlassian's ["Git worktrees for parallel features"](https://www.atlassian.com/git/tutorials/git-worktree)
  and numerous large-monorepo workflows (Chromium, LLVM) use
  worktrees for the same isolation goal, albeit for humans rather
  than agents.

## See also

- [`core/.cursor/hooks/auto-branch.sh`](../../core/.cursor/hooks/auto-branch.sh)
  — hook that recognizes session worktrees and refuses to auto-branch
  the main tree when siblings are live.
- [`core/AGENTS.md`](../../core/AGENTS.md) → *You are not alone in
  this repo* — the concurrency contract that points at this pattern.
- [`reference/patterns/anti-patterns.md`](anti-patterns.md) — includes
  the branch-only isolation anti-pattern this recipe supersedes.
