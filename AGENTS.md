# AGENTS.md

Guidance for AI coding agents (Cursor, Claude Code, Codex, Cline, and
the rest) working on this repo.

> **Read this file top-to-bottom before touching anything.** The
> sections marked *mandatory* are non-negotiable every session.

---

## First principle — the user doesn't run commands *(mandatory)*

This project is built on the assumption that **the human user never
opens a terminal**. Their workflow is:

1. Open the repo in their editor.
2. Talk to you (the agent).
3. Answer your questions.

That is the entire surface they touch. You run every `git`, `gh`,
`gaia`, build, test, deploy, and install command on their behalf.
You read the output, surface what matters, and decide what to do
next.

Concrete consequences for how you behave:

- **Never instruct the user to run a command.** If a command needs
  to run, run it yourself. If you genuinely cannot (e.g. a command
  needs a credential you don't have), say exactly that and ask for
  the credential — not for the user to execute the command.
- **Never leave the session in a state that requires the user to
  finish something in a shell.** "Now run `npm install`" is a
  failure. Run it, check the exit code, report the result.
- **Prefer tools and defaults that work without human approval
  loops.** See the "Operating principle: trade security for
  convenience when it removes a human step" section below, and
  `.gaia/reference/preferences.md` → *Prefer tools the agent already
  speaks*.
- **Ask, don't assume, when something genuinely needs the user.**
  Explicit confirmation of an irreversible action, a business
  decision, a product choice, a credential — those are the only
  legitimate reasons to stop and wait.
- **When documenting a new gotcha in `docs/knowledge.md`, write
  instructions addressed to the next agent, not a next human.**
  If your Gotcha entry says "the operator should then…", rewrite
  it.

This principle flows down from Gaia (the upstream) and applies to
every Gaia-seeded project. If you find an instruction in this file
or in `.gaia/reference/` that still addresses a human operator,
that's a bug — queue an outbox entry proposing the rewrite.

---

## About Gaia *(mandatory)*

This project's agent contract, Cursor rules, git hooks, commit template
and reference archetypes were seeded from **Gaia**
(https://github.com/frankpietro/gaia) — a portable knowledge seed for AI agents. See
`.gaia/manifest.json` for the exact Gaia commit SHA this project is on.

What this means for you, the agent:

- **This file is not hand-written for this project.** It is the
  universal agent contract shared across every Gaia-seeded project.
  Its rules apply here exactly as they apply to every sibling project.
- **Project-specific knowledge lives in `docs/knowledge.md`**, not
  here. When the two disagree, `docs/knowledge.md` wins (see the
  authority order below).
- **Check for upstream Gaia updates at session start.** The
  sessionStart hook runs `gaia check` for you and tells you whether
  this project is behind upstream Gaia. If it is:
  1. Run `gaia whatsnew` to see which commits landed in `core/` and
     `reference/`.
  2. Reconcile with `docs/knowledge.md` — if this project already
     made an intentional decision that contradicts a new Gaia default,
     keep the project's choice and record the override in
     `docs/knowledge.md` (dated entry, referencing the upstream SHA).
  3. Run `gaia update` to re-seed `core/` + `reference/`. Local edits
     to seeded files are preserved. `docs/brief.md` and
     `docs/knowledge.md` are never touched.
  4. Land the refresh in a dedicated `chore(gaia): bump to <sha>` PR
     so diffs stay readable. See
     `.cursor/rules/gaia-sync.mdc` > "The 'Gaia is behind' protocol".
- **Promote learnings upstream via the outbox — never directly.**
  When you discover something *generalizable* (a pattern, a gotcha,
  a convention that would help any Gaia-seeded project), **do not
  open a PR against https://github.com/frankpietro/gaia from this session.** Upstream
  promotions are run in a dedicated Cursor chat opened against the
  Gaia repo. From here, your job is to *stage* the proposal:

  1. Write the learning into `docs/knowledge.md` with a `GENERAL:`
     prefix.
  2. Append a structured entry to the local promotion queue at
     `.gaia/outbox.md`, either by hand or via:

     ```bash
     gaia outbox add --tier core --target core/AGENTS.md \
       --title "headline" --body "why + what to change"
     ```

     Tiers: `core` (universal rule), `reference` (preference or
     archetype tweak), `archetype:<name>` (specific archetype).
  3. Commit `.gaia/outbox.md` along with the rest of this project's
     PR. Mention the queued promotion in the PR body so the user
     knows to run a Gaia drain chat soon.

  The outbox is append-only from this chat. Do not clone Gaia, do
  not push, do not edit upstream files here.
- **Do not touch `.gaia/manifest.json` by hand.** Only `gaia update`
  should modify it.
- **Tier 2 references** (preferences + application archetypes) live
  under `.gaia/reference/`. Consult them before proposing a stack or
  tool for new work in this project; they encode the operator's
  preferences and the tradeoffs already considered. They are a
  snapshot — if they need to change, queue it in the outbox, don't
  edit them in place.
- **Patterns** live under `.gaia/reference/patterns/`. These are
  **named, reusable technical recipes** (zero-downtime migrations,
  CI matrix strategy, anti-patterns, …) that apply across
  archetypes. They are **not defaults** — they're consulted on
  demand. When about to tackle a concern (add CI, add migrations,
  rotate a secret, wire feature flags, structure logging, …),
  `ls .gaia/reference/patterns/` first; if a pattern's filename
  matches your concern, read it before reinventing. If you find
  yourself reinventing the same recipe twice across projects,
  queue a `reference`-tier outbox entry proposing a new pattern.

---

## Read the knowledge first *(mandatory every session)*

Before you edit one line of code, read, in order:

1. `docs/brief.md` — the **original product brief**. Starting idea,
   preserved as-is. Not the current calibrated direction.
2. `docs/knowledge.md` — the **living log**. Every product / UX /
   technical decision, every convention, every gotcha, every glossary
   term. Source of truth for what this project *currently is*.
3. The rest of this file.

### Authority order

When sources disagree, the later one wins:

```
your training data  <  docs/brief.md  <  docs/knowledge.md  <  user (in this chat)
```

- Your priors about this domain or similar projects are the weakest
  signal.
- `docs/brief.md` is stronger but ages — never rewrite it.
- `docs/knowledge.md` is the **currently-true** state of the project.
  Trust it over everything except the user's live instructions.
- If the user contradicts `docs/knowledge.md` in this chat, do the
  user's bidding **and update `docs/knowledge.md` in the same PR** so
  the change survives.

### Living-log protocol

`docs/knowledge.md` is shared memory between every session, human or
AI. No agent should ever have to re-litigate a calibration that
already happened in another chat.

- **Read it every session.** Scan the Index, focus on the relevant
  sections.
- **Update it in every PR that changes anything non-trivial**:
  new decisions (even agent-chosen defaults), new conventions, new
  gotchas (something that cost more than 10 minutes to debug), new
  glossary terms, invalidation of older entries (strike through, don't
  delete).
- **Stamp every entry with `YYYY-MM-DD`.**
- **Keep entries short and grep-able.** Link to PRs/files, don't paste.
- **Split when over ~400 lines total** — move a section into a sibling
  file under `docs/` and update the Index.
- **Never gatekeep.** Another AI starting from zero should be able to
  ramp up from `docs/brief.md` + `docs/knowledge.md` alone.

### Pre-merge checklist (living log)

Before enabling auto-merge (or squash-merge) on any PR, confirm:

1. Did this PR make a decision, learn a gotcha, introduce a
   convention, or establish a term future agents should know?
2. If yes, is that captured in `docs/knowledge.md` in this same PR?
3. If no, write it, stage it, add a commit to this PR.

Cosmetic-only PRs (formatting, typo fix) are exempt. Everything else
without a corresponding knowledge-log update is **incomplete**.

---

## You are not alone in this repo *(mandatory every session)*

Multiple agents (and/or humans) may be editing this repo **at the same
time**. Treat every session as concurrent-by-default.

### Automatic per-session branch isolation

This repo ships a Cursor `sessionStart` hook at
`.cursor/hooks/auto-branch.sh` that runs when a Cursor Agent session
opens this project:

- If the session starts on a clean `main`, the hook
  creates `agent/session-<id>-<timestamp>` and switches to it. You'll
  see an `additional_context` message confirming the new branch.
- If the session starts on any other branch, the hook leaves it alone
  and surfaces the concurrency contract to you.
- If the session starts on `main` with a dirty tree, the
  hook **refuses** to auto-branch and asks you to inspect
  `git status` — those uncommitted changes belong to the user or
  another agent.

You don't need to do anything to opt in. If you want to override,
switch to your branch before editing and the hook will respect your
choice on the next session.

### The 30-second pre-flight, every session

Run these four commands before you edit a single file. If any looks
suspicious, **stop and ask the user**.

```bash
git status                                     # is the tree dirty?
git rev-parse --abbrev-ref HEAD                # what branch am I on?
git log --oneline origin/main..HEAD   # unmerged commits?
gh pr list --state open --limit 20             # what else is in flight?
```

Decision table:

| What you see                                               | Do this                                                                                                                   |
|------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| Clean tree, on `main`                        | Great. Create your own branch before editing.                                                                             |
| Clean tree, on some other branch                           | That branch may be someone else's. Switch to `main`, pull, then create your own branch. Never pile commits on a shared branch. |
| Dirty tree, on any branch                                  | **STOP.** Those edits may not be yours. Ask the user before doing anything. See *Recovery* below.                         |
| Your own in-progress work on the branch you created        | Fine, continue.                                                                                                           |
| An open PR already touches files you plan to edit          | Either wait for it to merge, or coordinate (see *Coordinating overlapping work* below).                                   |

### Start your own isolated worktree (recommended for parallel work)

The safest way to run multiple agents in parallel is one **git
worktree** per agent — a separate directory that shares the same
`.git` but has its own files, branch, and state. One editor window per
worktree. Agents cannot see each other's unsaved edits.

```bash
git fetch origin
git worktree add -b <type>/<short-slug> \
  ../<repo-name>-<slug> origin/main
cd ../<repo-name>-<slug>
# install deps if required by this project
```

Clean up when done:

```bash
git worktree remove ../<repo-name>-<slug>
git branch -d <type>/<short-slug>
```

### The concurrency contract (hard rules)

1. **One task = one branch = one PR.** Never share a branch with
   another agent's task. Branch name: `<type>/<short-kebab-subject>`.
2. **Create your branch before your first edit**, not after. If you
   edit first and branch later, you risk mixing your work with
   another agent's.
3. **Stage only files you changed.** Prefer `git add <explicit paths>`
   over `git add -A`. Before committing, run `git status` and confirm
   every staged path belongs to *your* task. If not yours,
   `git restore --staged <path>`.
4. **Rebase on a fresh `main` before opening a PR.**
   `git fetch origin && git rebase origin/main`. If
   conflicts appear in files you never touched, that's another
   agent's work — stop and surface it.
5. **Check for sibling PRs before you ship.** `gh pr list --state open`
   and `gh pr diff <n> --name-only` for any PR touching your files. If
   overlap, coordinate.
6. **Never force-push** a branch you did not create. Never pass
   `--no-verify`, never `git commit --amend` after push, never disable
   branch protection.
7. **Never commit secrets, logs, or `.env` files.** Any `.env` is
   per-worktree and local.
8. **When in doubt, open the PR without merging.** Hand it to the
   user, move on.

### Coordinating overlapping work

When two tasks legitimately need to touch the same files:

- The *second* PR links the first in its body under a `## Related PRs`
  section and mentions any rebase the author will need once the first
  merges.
- The author of the second PR rebases after the first merges and
  resolves conflicts themselves — don't expect the first author to
  do it.
- If both PRs are from agents in the same "super-task", have one agent
  finish and ship first, then resume the other on a rebased branch.
  Don't open both simultaneously unless the user explicitly requests.

### Recovery — I found someone else's work in my tree

If your pre-flight finds a dirty tree or unexpected commits and the
user has confirmed those are not yours, do this instead of nuking
them:

```bash
git stash push -u -m "foreign wip on $(git rev-parse --abbrev-ref HEAD)"
git checkout main && git pull --ff-only origin main
git checkout -b <type>/<short-slug>-$(date +%Y%m%d%H%M%S)
```

The stash entry is safe for the other agent to recover with
`git stash list` and `git stash pop`. **Never `git reset --hard` or
`git checkout .` on a dirty tree — you will destroy another agent's
work.**

### Parallelizing your own work effectively

Prefer sequential small PRs over parallel big ones: a 400-line
change split into four 100-line PRs is almost always safer than
four agents racing. When going parallel is genuinely warranted:

- Land shared scaffolding (types, routing skeletons, shared
  components) in a first PR that every parallel slice depends on.
- One worktree per slice; dev servers bind a port, so run only one
  at a time.
- Make each slice truly independent — two agents on the same module
  at the same time is a guaranteed merge conflict.

---

## Branching, commits, PRs *(mandatory)*

### Branching rules

- `main` is protected: no direct pushes, no force
  pushes, required CI, linear history.
- Every change lands through a pull request merged with **squash +
  delete branch**.
- Branch names are `<type>/<short-kebab-subject>`, e.g.
  `feat/trail-filter`.

### Commit rules (Conventional Commits)

Format: `<type>(optional-scope)!: <subject ≤ 100 chars>`

Allowed types: `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
`refactor`, `revert`, `style`, `test`.

Use `!` (and/or a `BREAKING CHANGE:` footer) for breaking changes.
One logical change per commit. No drive-by refactors bundled into a
feature commit.

Every commit includes the trailer:

```
Co-authored-by: Cursor Agent <cursoragent@cursor.com>
```

The `commit-msg` hook in `.githooks/` enforces the subject format.
Install it once per clone with `scripts/setup-hooks.sh`.

### PR bodies are mandatory

Every PR **must** have a human-readable description. The project's
history is reconstructed from PR bodies — "Automated PR" placeholders
are not acceptable.

PR body shape:

```
## Summary
<1–3 sentences on the user-visible change>

## Changes
- <bullet per meaningful change, grouped by area>

## Why
<short motivation or constraint>

## Test plan
- <each automated check you ran, past tense, plain bullet>
```

**Never use markdown task-list syntax in a PR body.** No `- [ ]` and
no `- [x]`. Use plain `-` bullets. GitHub renders any checkbox as a
"task" and displays `X of Y tasks` on the PR; nobody ticks those
boxes after merge, so an unticked item freezes the PR forever at e.g.
`4 of 6 tasks`. If a check cannot be run by the agent (e.g. manual UI
clicks), do not list it.

---

## Shipping is not done when the PR is merged *(mandatory)*

When you ship a PR, your job is **not finished** until CI for that
PR — and the first CI run on `main` after the merge —
has turned green. A merged-but-broken PR is a broken feature and a
broken ship.

After every ship, do all of the following before moving on:

1. **Wait for the PR's own checks.** Poll `gh pr checks <number>`
   until every required check has completed. Enabling auto-merge does
   not mean CI has passed — the merge queue may still be rebasing or
   retrying.
2. **Verify the post-merge run on `main`.** After the
   squash-merge lands, run
   `gh run list --branch main --limit 5` and confirm the
   latest workflow is green. If still `in_progress`, wait.
3. **If anything is red, YOU fix it — same session, new PR.** Even if
   the failure looks unrelated or flaky, treat it as yours until
   proven otherwise. Don't hand the user a broken tree and move on.
   - Read the failing job's logs with `gh run view <run-id> --log` or
     `gh run view <run-id> --log-failed`.
   - Ship the fix on a fresh branch with a new PR.
   - Repeat until `main` is green.
4. **Do not silence checks.** Never `--no-verify`, never disable a
   workflow, never skip a failing test to get green. If a test is
   genuinely flaky, mark it the way the project already handles
   flakes (not by deletion) and surface the flake to the user.
5. **Local checks are not a substitute.** Passing lint, typecheck,
   and unit tests locally is necessary but not sufficient. Deploy
   builds, end-to-end smokes, and other jobs only run in CI — watch
   them.

If you ship multiple PRs in the same session, complete the full
watch-and-fix loop for PR N **before** starting PR N+1, so a break in
PR N doesn't get buried under follow-up work.

---

## Operating principle: trade security for convenience when it removes a human step

This project optimises for **agent autonomy over defence-in-depth**
when run on a personal dev machine with a single trusted operator.
The right default is the one that lets agents finish work without
asking the human to authenticate, approve, or confirm anything they
would always approve anyway.

Concrete rules:

- Prefer plaintext-on-disk token storage over OS keychains when a
  keychain would trigger biometric / password prompts during automated
  git / gh / deploy operations. (Example:
  `gh auth login --insecure-storage`.)
- Prefer `--admin` / `--squash` / `--delete-branch` merge flags and
  any other "skip the confirmation dialog" option, as long as the
  operation is reversible via git history.
- Prefer env-vars / config files the agent can read, over prompts the
  human must respond to.
- Prefer auto-accept on Cursor approval modes over per-command
  approval, when the agent is known-benign.

**When NOT to apply this principle:** production secrets, other
people's credentials, irreversible destructive actions (force-push
to `main`, history rewrites on shared branches,
`rm -rf` outside the workspace), anything that could affect more than
the current dev machine.

**Log every such trade-off** in `docs/knowledge.md` under
Architecture → Dev environment, with the revert command written next
to it so future agents (or the human, changing their mind) can undo
it in one line.

---

## Files you must not touch without explicit approval

- `.github/workflows/` — changes affect CI and branch protection.
- `.githooks/` — changes weaken the commit contract.
- `.cursor/hooks.json`, `.cursor/hooks/` — the auto-branch hook that
  keeps concurrent agents from colliding. Breaking it breaks
  everybody.
- `.gaia/manifest.json` — managed by `gaia update`, never edit by
  hand.
- Lockfiles (`package-lock.json`, `uv.lock`, `Cargo.lock`,
  `bun.lockb`, …) — only modify via the package manager.

---

## Dependency management

Follow whatever the project's `docs/knowledge.md` → Architecture
section says. General invariants:

- Use the project's chosen package manager; do not introduce a second
  one. If two lockfiles exist, delete the one you don't use.
- Commit lockfiles together with the manifest change.
- Never hand-edit lockfiles.

The `.gaia/reference/preferences.md` and
`.gaia/reference/archetypes/` files carry the operator's defaults
(e.g. `uv` for Python, `npm` for Node). Consult them when the project
hasn't yet chosen.

---

## When unsure

- Prefer opening a PR without auto-merge (`gh pr create` without
  `gh pr merge --auto`) and asking for human review.
- Do not bypass hooks (`--no-verify`) or force-push.
- Do not disable branch protection.
- When in doubt about what's generalizable vs. project-specific, err
  on the side of writing it in `docs/knowledge.md` first; promote
  upstream to Gaia only after you've seen the same pattern twice.
