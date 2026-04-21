# Data pipeline

## When to use

You are building a **batch analytical workload**: ETL, metrics
rollups, ad-hoc analysis that will be re-run, a scheduled report, a
one-off investigation that will graduate into a recurring job. The
inputs are data (files, a warehouse, an API), the outputs are
datasets / tables / charts / a written report.

If the output is an interactive dashboard, pair this with one of the
other archetypes for the UI.

## Reference stack

- **Language**: Python 3.12
- **Package manager**: `uv`
- **In-process dataframes**: `polars` (preferred) or `duckdb`
- **Pandas**: only when an external library forces it
- **Notebooks**: `.py` cells (Jupytext-style) or
  [Hex](https://hex.tech) projects. Never commit `.ipynb`.
- **Plotting**: `plotly.graph_objects` (always). No matplotlib.
- **Tests**: `pytest` — at least smoke tests on the transforms.
- **Lint/format**: `ruff`
- **Scheduling (when needed)**: cron / GitHub Actions cron / Airflow
  only if a real fleet demands it.

## Why these choices

- **Polars over Pandas**: order-of-magnitude performance, sane API,
  lazy evaluation when data gets big.
- **DuckDB**: the right tool when the workload is SQL-shaped and the
  data is parquet on disk or in S3.
- **Plotly graph_objects, not Express**: explicit figures compose
  better with dashboards and scripted exports. **Never matplotlib.**
- **`.py` notebooks over `.ipynb`**: clean diffs, code review works,
  no binary outputs in git.
- **Hex for exploratory**: when collaboration and interactive
  dashboards matter more than version control. **Never modify the
  YAML that represents a Hex project by hand** — write code in
  separate Python files and reference them from Hex cells.

## Known gotchas

- **Polars `.collect()` is where things actually run.** Profile by
  `collect(streaming=True)` when data exceeds RAM.
- **DuckDB connections are not thread-safe** by default. One
  connection per thread, or use the connection pool.
- **Plotly figures in Jupyter have a different renderer than in a
  browser.** For reproducible HTML output, use `fig.write_html(...)`.
- **Time zones bite.** Always store UTC, convert at the edge.

## Folder layout

```
<project-name>/
  pyproject.toml
  uv.lock
  src/
    <project_name>/
      __init__.py
      io/                  # data loaders (parquet, API, warehouse)
      transforms/          # pure functions on polars/duckdb
      plots/               # plotly.graph_objects factories
      jobs/                # entry points: ETL, report, …
  notebooks/
    <name>.py              # jupytext cells
  tests/
  data/                    # gitignored; inputs for local testing
  out/                     # gitignored; derived artifacts
```

## Alternatives considered

- **Polars → Pandas** — stay on pandas if the codebase is big and
  the performance is acceptable. Migrate (S–M, reversible per
  module) when a specific transform becomes a bottleneck.
  Cross-compile compatibility layers are not worth the complexity.
- **DuckDB → PostgreSQL / ClickHouse / BigQuery** — cloud
  warehouses are right when the dataset is multi-TB or shared
  across a team. For local / single-machine workloads, DuckDB
  is faster *and* cheaper. Stay on whatever the data actually
  lives in.
- **Plotly → Matplotlib / Seaborn / Altair / Bokeh / Plotnine** —
  matplotlib is an **operator-specific veto** here (see
  `preferences.md`). Altair / Plotnine are fine for static
  analytical plots but don't compose into Plotly dashboards.
  **On adoption**, propose a swap for matplotlib imports (S,
  reversible, often mechanical) — the hard rule is operator's.
- **Jupyter `.ipynb` → `.py` + `# %%`** — migrate (XS per
  notebook, scripted via `jupytext --to py`); it's one of the
  cheapest wins and unblocks code review.
- **Airflow / Prefect / Dagster vs. cron** — orchestrators earn
  their weight only when you have >10 recurring jobs or cross-job
  dependencies. Start with GitHub Actions cron or a single cron
  entry; adopt Dagster when the dependency graph hurts.
- **Hex vs. Jupyter vs. Databricks** — pick one per project and
  document it. Hex's YAML must never be edited by hand (operator
  rule).

## Adopt-time decision hints

| Detected | Classification | Recommendation |
|----------|----------------|----------------|
| polars + duckdb + pytest + ruff + plotly | aligned | Stay. No action. |
| pandas everywhere | divergent | Stay at adoption. Propose per-module polars migration in follow-ups *only* when a concrete pain (memory, speed) exists. |
| `matplotlib` imports | divergent (hard rule) | Propose a Refactor (S, reversible): replace imports + `plt.show()`/`plt.savefig()` with `plotly.graph_objects` + `fig.write_html()` / `fig.show()`. Often mechanical. |
| `.ipynb` committed | divergent | Propose `jupytext --to py:percent` migration (XS per notebook) in a follow-up PR; add `.ipynb` to `.gitignore`. |
| Hex project YAML in repo with inline code | divergent (hard rule) | Move code into separate `.py` files; the YAML references them. Tune (S, reversible). |
| Airflow for < 5 jobs | divergent | Stay. Propose simplification only if the Airflow overhead is cited as a pain point in Phase 1. |
| No tests on transforms | missing | Propose a `tests/` scaffold with at least smoke tests on each transform module as a follow-up (S). |

## Seeding

```bash
gaia init --archetype data-pipeline --name <project-name>
# or, on an existing repo being adopted:
gaia adopt --seed --archetype data-pipeline
```

After seed, `uv init --lib` inside the project root (Gaia doesn't
scaffold the Python package for you), then record the data sources
and cadence in `docs/knowledge.md` → Architecture.
