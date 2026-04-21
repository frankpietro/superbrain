# Deploying the superbrain scheduler on Fly.io

The scheduler is the always-on worker that keeps Sisal, Goldbet and
Eurobet odds fresh every 15 minutes and runs the historical backfill
daily. It lives inside a single Fly.io machine on the free tier. Phase 5
ships the Dockerfile, `fly.toml` and the `python -m superbrain.scheduler`
entry point; the operator still runs the three Fly CLI commands below to
bring up the app the first time.

## Prerequisites

- A free Fly.io account with a payment method on file (required by Fly
  even on the free tier).
- `flyctl` installed locally (`brew install flyctl`).
- `fly auth login`.

## First-time setup

```bash
# 1. Register the app against the fly.toml in this repo.
fly launch --no-deploy --copy-config --name superbrain-scheduler \
           --region ams --org personal

# 2. Allocate the persistent Parquet lake volume (1 GB is plenty for the
#    top-5 leagues; grow with `fly volumes extend` later if needed).
fly volumes create superbrain_data --size 1 --region ams

# 3. Set the secrets the scrapers pick up via pydantic-settings.
#    None are strictly required today (all scrapers are unauthenticated),
#    but a contributor-tag secret keeps the audit log readable:
fly secrets set \
    SUPERBRAIN_SCHEDULER_LOG_LEVEL=INFO \
    SUPERBRAIN_SCHEDULER_BOOKMAKER_INTERVAL_MINUTES=15 \
    SUPERBRAIN_SCHEDULER_HISTORICAL_CRON="0 4 * * mon-fri"

# 4. Deploy. The first push builds the Dockerfile; subsequent pushes
#    reuse the cached layers.
fly deploy
```

## Verifying the scheduler is live

```bash
fly status                    # one machine, state = started
fly logs --app superbrain-scheduler \
  | grep scheduler.ready      # should print within a minute of deploy
fly ssh console -C \
    "ls /data/lake/scrape_runs"  # partitions appear after the first tick
```

## Updating the scheduler

Every subsequent deploy is just:

```bash
fly deploy
```

Fly sends `SIGTERM` 10 seconds before halting the machine. The runner
drains in-flight jobs on `SIGTERM`, so the only cost of a redeploy is a
missed tick at most. The GitHub Actions fallback covers that window.

## GitHub Actions fallback

`.github/workflows/scheduled-scrapes.yml` mirrors the Fly cadence:

| Cron (UTC) | Job | Command |
| --- | --- | --- |
| `*/15 * * * *` | bookmakers | `uv run python -m superbrain.scheduler --run-once --jobs bookmakers` |
| `15 4 * * *` | historical | `uv run python -m superbrain.scheduler --run-once --jobs historical` |

The workflow uploads the resulting Parquet diff as an artefact only — it
never pushes to the lake branch, so Fly stays the single source of
truth. The DB-level idempotency guarantees duplicate-safe ingestion if
both Fly and Actions ever race.

The workflow is guarded with
`if: github.repository == 'frankpietro/superbrain'` so forks do not
pointlessly burn minutes.

## Rolling back

```bash
fly releases              # pick a prior version
fly deploy --image <sha>  # redeploy that image
```

The Parquet lake is append-only with natural-key dedupe; rolling the
scheduler back never corrupts data.

## Local run (no Fly, no Docker)

```bash
uv sync --all-extras --dev
uv run python -m superbrain.scheduler --run-once --jobs bookmakers
uv run python -m superbrain.scheduler              # long-running loop
```

The local lake defaults to `./data/lake`; override with
`SUPERBRAIN_LAKE_PATH=/absolute/path`.
