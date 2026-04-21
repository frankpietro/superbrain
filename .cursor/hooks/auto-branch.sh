#!/usr/bin/env bash
# Cursor sessionStart hook. Two jobs:
#   (1) Concurrency isolation across parallel Cursor sessions.
#   (2) Gaia freshness nudge.
#
# Concurrency model:
#   - In a Gaia-managed session WORKTREE (sibling dir created by
#     `gaia session new`), the hook does nothing disruptive: it welcomes
#     the agent and records the session → slug link.
#   - In the MAIN worktree on a clean default branch:
#       * If no other agent session worktrees exist, create
#         `agent/session-<id>-<ts>` like before (single-session happy path).
#       * If sibling session worktrees DO exist, refuse to auto-branch and
#         tell the agent to stop and surface a collision to the user —
#         the main tree being edited under another agent's session is the
#         real source of "agents stashing each other's work".
#   - On a non-default branch or a dirty tree, the hook leaves the tree
#     alone (today's behaviour) and surfaces the situation.
#
# Seeded from Gaia (https://github.com/frankpietro/gaia). Do not edit in place; change upstream in
# Gaia and re-seed with `gaia update`. Fails open on any error.
set -eu

DEFAULT_BRANCH="main"

emit_empty_and_exit() {
  echo '{}'
  exit 0
}
trap emit_empty_and_exit EXIT

input="$(cat)"

if ! command -v jq >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
  exit 0
fi

session_id="$(printf '%s' "$input"  | jq -r '.session_id // ""')"
composer_mode="$(printf '%s' "$input" | jq -r '.composer_mode // "agent"')"

case "$composer_mode" in
  ask) exit 0 ;;
esac

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$repo_root" ]] || exit 0
cd "$repo_root"

current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
[[ -n "$current_branch" ]] || exit 0

# --- worktree detection --------------------------------------------------
# In a secondary worktree, --git-dir is `.git/worktrees/<name>` while
# --git-common-dir points at the main `.git`. In the main checkout they are
# the same.
git_dir="$(git rev-parse --absolute-git-dir 2>/dev/null || echo "")"
git_common_dir="$(cd "$repo_root" && cd "$(git rev-parse --git-common-dir 2>/dev/null || echo .)" && pwd 2>/dev/null || echo "")"
is_session_worktree=0
if [[ -n "$git_dir" && -n "$git_common_dir" && "$git_dir" != "$git_common_dir" ]]; then
  is_session_worktree=1
fi

# Count sibling session worktrees (main excluded).
session_count=0
while IFS= read -r line; do
  [[ "$line" == *"refs/heads/agent/"* ]] && session_count=$((session_count + 1))
done < <(git worktree list --porcelain 2>/dev/null | awk '/^branch /')

tree_dirty=0
if ! git diff --quiet || ! git diff --cached --quiet \
   || [[ -n "$(git ls-files --others --exclude-standard 2>/dev/null)" ]]; then
  tree_dirty=1
fi

# --- Gaia freshness (best-effort, never blocks) --------------------------
freshness_note=""
if command -v gaia >/dev/null 2>&1; then
  fresh_json="$(gaia check --json "$repo_root" 2>/dev/null || echo "")"
  if [[ -n "$fresh_json" ]]; then
    fresh_status="$(printf '%s' "$fresh_json" | jq -r '.status // "unknown"')"
    fresh_behind="$(printf '%s' "$fresh_json" | jq -r '.behind_by // 0')"
    fresh_fetch_age="$(printf '%s' "$fresh_json" | jq -r '.fetch_age_hours // -1')"
    case "$fresh_status" in
      behind)
        freshness_note=$'\n\nGaia freshness: this project is '"$fresh_behind"$' commit(s) behind upstream Gaia. Before editing, run `gaia whatsnew` to see what changed in core/ and reference/, reconcile with docs/knowledge.md if anything conflicts, then `gaia update` to apply. Commit the re-seeded files in a dedicated PR (type: chore, scope: gaia).'
        ;;
      ahead)
        freshness_note=$'\n\nGaia freshness: this project was seeded from a Gaia commit newer than your local $GAIA_HOME clone. Run `gaia sync` to pull upstream into the clone before doing anything Gaia-related.'
        ;;
      diverged)
        freshness_note=$'\n\nGaia freshness: this project and $GAIA_HOME have diverged histories. Do not run `gaia update` — inspect $GAIA_HOME and resolve upstream first.'
        ;;
      up-to-date)
        if [[ "$fresh_fetch_age" -ge 24 ]]; then
          freshness_note=$'\n\nGaia freshness: project is up to date with the local Gaia clone, but the clone itself has not been fetched in >24h. Run `gaia sync` to make sure "up to date" means "up to date with upstream".'
        fi
        ;;
    esac
  fi
fi

emit() {
  local ctx="$1"
  local env_json="${2:-null}"
  trap - EXIT
  jq -n --arg ctx "${ctx}${freshness_note}" --argjson env "$env_json" '
    if $env == null then {additional_context: $ctx}
    else {additional_context: $ctx, env: $env}
    end
  '
  exit 0
}

# --- (1) session worktree: already isolated; just welcome ----------------
if [[ "$is_session_worktree" -eq 1 ]]; then
  # Try to recover the slug from .git/gaia-sessions.json (source of truth).
  slug=""
  sessions_json="$git_common_dir/gaia-sessions.json"
  if [[ -f "$sessions_json" ]]; then
    slug="$(jq -r --arg p "$repo_root" '.[] | select(.path == $p) | .slug' "$sessions_json" 2>/dev/null | head -n1)"
  fi
  [[ -n "$slug" ]] || slug="${current_branch#agent/}"
  env_json="$(jq -n --arg branch "$current_branch" --arg session "$session_id" --arg slug "$slug" \
    '{SESSION_BRANCH: $branch, SESSION_ID: $session, GAIA_SESSION_SLUG: $slug}')"
  emit "Concurrency isolation: this session is running inside a Gaia session worktree (slug \`$slug\`, branch \`$current_branch\`). You have a dedicated working tree — edits here cannot collide with other concurrent Cursor sessions. Commit, push, open a PR when done. Teardown: \`gaia session done --slug $slug\`. See AGENTS.md > \"You are not alone in this repo\"." "$env_json"
fi

# --- (2) main worktree, non-default branch -------------------------------
if [[ "$current_branch" != "$DEFAULT_BRANCH" ]]; then
  emit "Git state at session start: on branch \`$current_branch\` (not the default). Auto-branching skipped — respect this branch if it is yours, but STOP and ask the user if it has commits or unstaged work you did not make. See AGENTS.md > \"You are not alone in this repo\" for the full contract."
fi

# --- (3) main worktree, dirty tree ---------------------------------------
if [[ "$tree_dirty" -eq 1 ]]; then
  emit "Git state at session start: on \`$DEFAULT_BRANCH\` with uncommitted or untracked changes. Auto-branching was SKIPPED so your changes are not swept away. Run \`git status\` and read the output carefully. If the changes are not yours, follow the Recovery playbook in AGENTS.md (\`git stash push -u -m \"...\"\`) before starting new work. If they are yours, create your own branch before editing more: \`git checkout -b <type>/<slug>-\$(date +%Y%m%d%H%M%S)\`."
fi

# --- (4) main worktree, clean, but sibling sessions are live -------------
# This is the collision case the old hook silently allowed: two Cursor
# windows open on the same repo, both editing the shared main tree. Refuse
# to auto-branch; tell the agent to surface it.
if [[ "$session_count" -gt 0 ]]; then
  emit "Concurrency collision avoided: this session opened on \`$DEFAULT_BRANCH\` in the MAIN worktree, but ${session_count} sibling Gaia session worktree(s) are already active on \`agent/*\` branches. The main working tree is shared — any edit here risks clobbering another agent. STOP and surface this to the user. Options: (a) run \`gaia session new --slug <name>\` to get your own isolated worktree and re-open Cursor there, or (b) pause this task until the sibling sessions finish (\`gaia session list\` to inspect). Do NOT start editing until the user decides."
fi

# --- (5) main worktree, clean, alone: the original happy path ------------
short_id="$(printf '%s' "${session_id:-unknown}" \
  | tr -c 'a-zA-Z0-9' '-' \
  | cut -c1-8 \
  | sed -E 's/^-+//; s/-+$//')"
[[ -n "$short_id" ]] || short_id="anon"
branch="agent/session-${short_id}-$(date +%Y%m%d%H%M%S)"

if ! git checkout -b "$branch" >/dev/null 2>&1; then
  emit "Auto-branch hook tried to create \`$branch\` but git refused. Create your own branch before editing: \`git checkout -b <type>/<slug>-\$(date +%Y%m%d%H%M%S)\`."
fi

env_json="$(jq -n --arg branch "$branch" --arg session "$session_id" '{SESSION_BRANCH: $branch, SESSION_ID: $session}')"
emit "Concurrency isolation: this session started on a clean \`$DEFAULT_BRANCH\`, so it has been automatically moved to a fresh branch \`$branch\`. Edit freely — your commits will land here, isolated from \`$DEFAULT_BRANCH\`. For parallel work with another agent, prefer \`gaia session new\` which creates a dedicated worktree (stronger isolation than branch-only). When ready to ship, rename the branch (\`git branch -m <type>/<short-slug>\`), push, and open a PR. See AGENTS.md > \"You are not alone in this repo\" for the full contract." "$env_json"
