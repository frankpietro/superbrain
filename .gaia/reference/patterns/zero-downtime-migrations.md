# Zero-downtime schema migrations

## When to use

- **`multi-tenant-saas`** with live users: any schema change made
  while the app is serving traffic.
- **`data-pipeline`** whose inputs include a long-running production
  DB: migrations must not block reads during the ETL window.
- Any project where a migration failure mid-deploy would force a
  rollback that drops data.

## When NOT to use

- Pre-launch projects with no users: apply migrations synchronously,
  restart the app, move on. The overhead of the recipe below is not
  worth it.
- `personal-web-spa`: no backend, nothing to migrate.
- Throwaway prototypes: ship fast, record the decision in
  `docs/knowledge.md` under "Open questions" with the trigger "first
  paying user".

## The recipe — expand, migrate, contract

Every schema change is split into **three deploys**. Never combine
them.

### 1. Expand

Add the new shape without removing the old.

- Add a **nullable** column (not `NOT NULL`), without a default that
  rewrites the whole table.
- Add the index `CONCURRENTLY` (Postgres: `CREATE INDEX CONCURRENTLY`).
- Add the new table; leave the old one untouched.
- Backwards-compatible code change: app reads both shapes, writes
  to both shapes (or writes new + reads old fallback). Never writes
  to only one shape at this point.

Ship this deploy. Run integration tests in production-like.

### 2. Backfill

Copy old → new in small batches, off the hot path.

- Prefer a dedicated worker / job, not an app-server request path.
- Batch size: 1k–10k rows, tunable. Sleep between batches if the DB
  load is contested.
- The backfill must be **idempotent**: if it crashes, re-running it
  completes without corruption. Use `ON CONFLICT DO NOTHING` or
  explicit "is this row already migrated?" checks.
- Run the backfill with the expand deploy still live. The app stays
  functional throughout.

Verify: `SELECT count(*) FROM t WHERE new_col IS NULL` goes to zero.

### 3. Contract

Remove the old shape now that everything reads + writes the new one.

- Change the app to stop reading / writing the old shape. Deploy.
- Once the app has been on the new-shape-only build for a safe
  window (days, not minutes), drop the old column / table / index.

Never combine step 3 with step 1 of the next change.

## Trade-offs

- **Cost**: every schema change becomes at least three PRs and
  three deploys; engineering velocity drops ~30% on DB-heavy work.
- **Benefit**: a botched migration never takes the site down.
  Rollback is always "revert the app deploy"; the DB is always
  forwards-compatible.
- **Alternatives**:
  - *Maintenance window*: announce downtime, migrate synchronously.
    Works for single-operator apps; does not work for paying
    customers.
  - *Blue-green*: run two DB instances, swap. Operationally heavy,
    warranted only at very large scale.
  - *Online migration tools*: pt-online-schema-change (MySQL),
    pg-osc / gh-ost. Good for big tables; adds a dependency.

## Failure modes

- **Non-nullable column added with a default in step 1** — rewrites
  the whole table, locks writes for the duration. Use a nullable
  column + backfill + `SET NOT NULL` in step 3 after backfill
  completes.
- **Forgetting the concurrent index** — `CREATE INDEX` without
  `CONCURRENTLY` takes a heavy lock. Hard to spot in small-table
  tests; catastrophic on a big table.
- **Backfill worker reusing app connections** — saturates the pool.
  Give the backfill its own connection.
- **Dropping the old column before every replica has caught up** —
  reads from lagged replicas break. Wait for replication lag to
  clear before step 3's drop.
- **Alembic `autogenerate` missing server-side default changes** —
  a known SQLAlchemy quirk. Review every `alembic revision
  --autogenerate` diff by hand; record the Alembic cost params in
  `docs/knowledge.md`.

## Evidence

- GitHub's "online schema changes" engineering posts (ghost /
  gh-ost) codified the expand/backfill/contract pattern.
- Stripe and Shopify have published very similar protocols;
  Shopify's "Zero-downtime schema changes in PostgreSQL" is a
  good primer.
- The pattern is the default in the `strong_migrations` Ruby gem,
  and is roughly what Django + `django-pg-zero-downtime-migrations`
  enforces.
- Gaia's `multi-tenant-saas` archetype assumes Alembic; Alembic
  supports the pattern but does not enforce it. This pattern is
  the enforcement.

## See also

- `archetypes/multi-tenant-saas.md` → Known gotchas (Alembic
  autogenerate review).
- `preferences.md` → Backend → Migrations (Alembic as the default).
