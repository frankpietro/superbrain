# CI matrix strategy

## When to use

- **Libraries** or **CLI tools** with a declared range of supported
  runtime versions (Python 3.10+, Node LTS + current, …).
- **`multi-tenant-saas`** when the deploy target pin may drift from
  the dev machine; test against both.
- **`data-pipeline`** when inputs come from multiple Python or
  pandas versions in upstream consumers.

## When NOT to use

- **`personal-web-spa`** with a single deploy target (Vercel) on a
  single runtime version. One CI row, no matrix.
- Projects where the CI minutes budget is tight: matrices multiply
  cost. Pick the two endpoints (oldest supported + newest), not the
  full range.
- Projects with long-running test suites (>15 min): prefer a
  single-row CI + a nightly full-matrix job over a per-PR matrix.

## The recipe

Run the test suite on **N+1 dimensions** where each dimension is
one axis of variance that can break the build, capped at **three
dimensions maximum**.

### Dimension 1 — runtime version (mandatory)

- **Python projects**: at least `["3.12", "3.13"]` if the project
  supports both. `minimum + current` is the baseline. Add one
  middle version only if a user actually uses it.
- **Node projects**: `["lts", "current"]`. Dropping LTS as soon as
  a new LTS ships is a mistake; give it 3–6 months overlap.

### Dimension 2 — OS (optional)

- **CLI / library**: `["ubuntu-latest", "macos-latest",
  "windows-latest"]` if cross-platform support is claimed.
- **SaaS / pipeline**: Linux only is almost always right; mac/win
  are wasted CI minutes.

### Dimension 3 — DB / external service (optional)

- **SaaS** with Postgres support claimed across versions:
  `["postgres:15", "postgres:16"]`. Otherwise pin one version.
- **Pipeline** against multiple warehouses: rare; use nightly, not
  per-PR.

### Config shape (GitHub Actions)

```yaml
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false                 # see one failure per row, not just the first
      matrix:
        os: [ubuntu-latest]
        python: ["3.12", "3.13"]
        include:
          - os: macos-latest
            python: "3.13"             # one opportunistic mac row, not the full cross
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync --frozen
      - run: uv run pytest
```

Key decisions encoded above:

- `fail-fast: false` — you want ALL failures visible, not just the
  first one to surface.
- `include` adds a single extra row rather than exploding the
  matrix (2 pythons × 2 OS = 4 jobs; `include` keeps it at 3).
- `uv sync --frozen` is the CI-side contract: no lockfile drift.

## Trade-offs

- **Cost**: CI minutes per PR = (rows) × (suite duration). A
  2×1×1 matrix doubles CI cost; a 2×3×2 matrix is 12× a single
  row. Budget accordingly.
- **Benefit**: catches runtime-specific bugs (typing changes,
  dict-ordering assumptions, asyncio API changes, Node ESM/CJS
  boundaries) before a user reports them.
- **Alternatives**:
  - *Single-row CI + nightly matrix*: fast per-PR feedback, heavy
    drift-detection at night. Good for mature projects.
  - *Tox / nox locally*: developer-run matrix, CI runs one row.
    Cheap, shifts detection to the developer — works when the team
    is disciplined.
  - *CI only runs the matrix on main*: catches drift post-merge.
    Dangerous — regressions may land before detection.

## Failure modes

- **`fail-fast: true` hides failures** — first-job-fails cancels
  the rest. You see one symptom, fix it, re-run, see the next, fix
  it, re-run. Multiplies cycle time. Always `false`.
- **The matrix multiplies without `include`** — defining
  `os: [ubuntu, macos] python: [3.10, 3.11, 3.12]` creates 6 jobs.
  `include` adds specific rows; `exclude` removes. Prefer
  `include` for small additions.
- **Caching is per-matrix-row** — cache keys must include the
  matrix variables (`${{ runner.os }}-${{ matrix.python }}`) or
  rows trample each other's caches.
- **Flaky tests show up on one row only** — don't retry-until-green;
  that's how flaky tests hide. Mark flaky tests, fix them, or
  quarantine with a deadline.
- **The matrix becomes the project's truth** — when adding a new
  runtime version, update `pyproject.toml` / `package.json`
  `engines` / classifiers in the SAME PR as the matrix row.
  Otherwise dependents believe the wrong thing.

## Evidence

- The pattern is the default in mature Python libraries (FastAPI,
  httpx, pydantic, ruff itself) and all Node LTS-supporting
  projects.
- `actions/setup-python` and `actions/setup-node` are optimized
  for this shape (setup-action cache, matrix-aware key).
- Shopify's "Minimum Viable CI" post codifies the "2 endpoints
  beat full range" heuristic.

## See also

- `archetypes/cli-tool.md` — testing section.
- `archetypes/multi-tenant-saas.md` — GitHub Actions → GHCR build
  pipeline.
- `preferences.md` → Language and runtime (Python / Node version
  defaults).
