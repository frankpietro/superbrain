# CLI tool

## When to use

You are building a **terminal-first utility** meant to be run by a
human or a script: automation, a thin API wrapper, a dev-ops
helper, a code generator. Distribution is "clone the repo and
symlink into `$PATH`", or published later once the tool matures.

This is the archetype for **Gaia itself**.

## Reference stack

- **Language**: Python 3.12+, or plain Bash for thin orchestration.
- **Python**: `uv` for deps; `typer` (preferred) or `click` for the
  CLI interface; `pytest` for tests; `ruff` for lint/format.
- **Bash**: `set -euo pipefail`; coloured output via `tput`; early
  errors; idempotent subcommands; one subcommand per verb.
- **Packaging** (when time): `uv tool install <name>` from a public
  PyPI release. `pipx install` remains valid for users not on `uv`.
  For shipped binaries, `shiv` / `pyinstaller` / PEX.

## Why these choices

- **`typer` over raw `argparse`** — type-annotated subcommands,
  automatic `--help`, minimal boilerplate.
- **`uv`** — same reason as every other Python stack: fast,
  reproducible, single binary.
- **Bash for thin wrappers** — when the tool *is* a chain of
  `git`/`gh`/`docker` commands, Python startup is overhead. Bash
  carries orchestration cleanly up to ~500 lines; past that,
  associative arrays become painful and Python wins.
- **Idempotent subcommands** — re-running `gaia init` should
  refuse politely, not explode. Every verb prints what it's doing.

## Design principles

- **One entry point.** No hunting through `scripts/`. A single
  executable at the repo root that dispatches to subcommands.
- **Every command prints what it's doing.** `log`, `ok`, `warn`,
  `die` helpers with colour. Never silent.
- **Short-circuit early.** Validate arguments and required tools
  (`require git`, `require gh`, …) at the top of each subcommand.
- **Idempotent.** Re-running the same command is safe and updates
  state rather than erroring.
- **No hidden state.** If a command changes a git config or drops
  a file, it says so.

## Known gotchas

- **`set -e` + `read` on an empty pipe** hangs. Use `|| true` when
  reading from a pipe that might be empty.
- **`set -u` + unset optional vars** explode. Use `${VAR:-default}`.
- **`typer` pulls in `rich` by default.** For a tiny CLI, pass
  `rich_markup_mode=None` to `typer.Typer()` to cut import cost.
- **CI-vs-local colour detection.** Use
  `[[ -t 1 ]] && command -v tput` to degrade gracefully.

## Folder layout

Use what `uv init --package <name>` scaffolds; don't reshape it for
taste. The defaults below are what you'll see.

### Python (`typer`)

```
<project-name>/
  pyproject.toml
  uv.lock
  src/<project_name>/
    __init__.py
    __main__.py          # `python -m <project_name>`
    cli.py               # typer app + subcommands
  tests/
```

### Bash

```
<project-name>/
  <project-name>              # bash CLI entry point
  lib/<name>.sh               # optional helpers sourced by the CLI
  tests/test-*.sh
```

## Alternatives considered

- **Click / argparse** — Click is Typer's grandparent and totally
  fine. `argparse` is stdlib and the right call for a single-file
  script where startup time matters. Stay with what's in place;
  migrate only if the current framework is actively painful.
- **Rust / Go** — valid for CLIs that ship binaries or need
  startup < 50 ms. Unknown-to-Gaia by default; apply the rubric
  from [`preferences.md`](../preferences.md). If two projects go
  this way, queue an outbox entry for a dedicated archetype.
- **Bash → Python** — migrate when the script exceeds ~500 lines,
  associative arrays become unavoidable, or JSON handling
  dominates.
- **`pipx` vs. `uv tool install`** — both work; prefer `uv tool
  install` if the project is already `uv`-first.

## Adopt-time decision hints

| Detected | Classification | Recommendation |
|---|---|---|
| Python + typer/click + uv | aligned | Stay. No action. |
| Python + argparse | aligned (stdlib) | Stay. Don't migrate to typer for aesthetics; migrate only if subcommand boilerplate is drowning the code (S, reversible). |
| Python + poetry | divergent | Tune (S): migrate to `uv` if CI is slow or the lockfile churns. |
| Single bash file, no tests | aligned but missing | Scaffold a minimal `tests/test-*.sh` (XS–S) as a follow-up. |
| Rust / Go / Zig CLI | unknown to Gaia | Stay. Document in `docs/knowledge.md`. Apply the rubric; don't propose migration. |
| Makefile as "CLI" | divergent (shape) | Stay if it works. Consider wrapping with a named entry point if users confuse target names with commands. |

## Seeding

```bash
gaia init --archetype cli-tool --name <project-name>
# or on an existing repo being adopted:
gaia adopt --seed --archetype cli-tool
```

The seed gives you the universal contract but **not** a Python or
Bash scaffold (that's outside Gaia's scope). Run `uv init --package`
or write the entry-point script by hand, then record the choice in
`docs/knowledge.md`.
