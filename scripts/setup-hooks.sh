#!/usr/bin/env bash
# Wire up the repo's git hooks and commit-message template.
# Run once per fresh clone: `./scripts/setup-hooks.sh`.
#
# Seeded from Gaia (https://github.com/frankpietro/gaia).
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git config core.hooksPath .githooks
git config commit.template .gitmessage

# Auto-prune stale remote-tracking refs on every fetch. Without this,
# branches deleted on the remote (e.g. via `gh pr merge --delete-branch`)
# linger in `git branch -a` as `origin/feat/old-thing` forever. See
# AGENTS.md → *Clean up after yourself*.
git config fetch.prune true

chmod +x .githooks/* 2>/dev/null || true
chmod +x .cursor/hooks/*.sh 2>/dev/null || true

echo "Hooks wired:"
echo "  core.hooksPath      = $(git config --get core.hooksPath)"
echo "  commit.template     = $(git config --get commit.template)"
echo "  fetch.prune         = $(git config --get fetch.prune)"
