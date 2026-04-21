#!/usr/bin/env bash
# Cursor sessionStart hook: isolate each new agent session on its own git
# branch AND surface upstream Gaia freshness. Runs once per session open.
#
# Seeded from Gaia (https://github.com/frankpietro/gaia). Do not edit in-place; change upstream in
# Gaia and re-seed with `gaia update`.
#
# Two jobs:
#   (1) Concurrency isolation — auto-branch from a clean default branch so
#       multiple agents / the human do not collide. Conservative: never
#       touches a dirty tree or a non-default branch.
#   (2) Gaia freshness — if `gaia` is on PATH, compare this project's
#       recorded gaia_commit against the local Gaia clone's HEAD and tell
#       the agent whether to run `gaia whatsnew` + `gaia update`. Purely
#       informational; never blocks the session.
#
# Fails open: any unexpected error emits empty JSON and the session
# continues without guidance (better than blocking session start).
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

tree_dirty=0
if ! git diff --quiet || ! git diff --cached --quiet \
   || [[ -n "$(git ls-files --others --exclude-standard 2>/dev/null)" ]]; then
  tree_dirty=1
fi

# --- Gaia freshness (best-effort, never blocks) --------------------------
# Produces $freshness_note (possibly empty) to be appended to every emitted
# additional_context. Uses `gaia check --json` when available; falls back
# to silence otherwise.
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

if [[ "$current_branch" != "$DEFAULT_BRANCH" ]]; then
  emit "Git state at session start: on branch \`$current_branch\` (not the default). Auto-branching skipped — respect this branch if it is yours, but STOP and ask the user if it has commits or unstaged work you did not make. See AGENTS.md > \"You are not alone in this repo\" for the full contract."
fi

if [[ "$tree_dirty" -eq 1 ]]; then
  emit "Git state at session start: on \`$DEFAULT_BRANCH\` with uncommitted or untracked changes. Auto-branching was SKIPPED so your changes are not swept away. Run \`git status\` and read the output carefully. If the changes are not yours, follow the Recovery playbook in AGENTS.md (\`git stash push -u -m \"...\"\`) before starting new work. If they are yours, create your own branch before editing more: \`git checkout -b <type>/<slug>-\$(date +%Y%m%d%H%M%S)\`."
fi

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
emit "Concurrency isolation: this session started on a clean \`$DEFAULT_BRANCH\`, so it has been automatically moved to a fresh branch \`$branch\`. Edit freely — your commits will land here, isolated from \`$DEFAULT_BRANCH\` and from any other concurrent agent session. When ready to ship, rename the branch to something descriptive (\`git branch -m <type>/<short-slug>\`), push with \`git push -u origin HEAD\`, and open a PR. See AGENTS.md > \"You are not alone in this repo\" for the full contract." "$env_json"
