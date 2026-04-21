# Gaia outbox

Pending upstream promotions for this project. Agents working here
flag generalizable learnings (those that would help any Gaia-seeded
project) as entries below. **Nothing in this file is pushed to Gaia
automatically.** The user opens a dedicated Cursor chat in the Gaia
repo to drain the outbox into real PRs against `core/` or
`reference/`.

Entry format:

  ---
  id: <YYYY-MM-DD-NN>
  tier: core | reference | archetype:<name>
  target: <optional path in gaia, e.g. core/AGENTS.md>
  date: <YYYY-MM-DD>
  status: pending | promoted | dropped
  title: <one line>
  ---
  <free-form markdown body: why, what to change, links>

Use `gaia outbox add ...` to append entries with the right shape.
Use `gaia outbox list` to see what's pending here.

---
id: 2026-04-21-01
tier: reference
target: reference/patterns/bookmaker-scrapers.md
date: 2026-04-21
status: pending
title: Akamai-protected JSON APIs: curl_cffi over Playwright as default
---

Bookmakers like Goldbet front their hidden JSON APIs with Akamai Bot Manager (JA3/TLS fingerprinting). A 20-minute time-box during phase 3 found curl_cffi with impersonate='chrome124' clears the edge, removing the need for a Chromium binary and 'playwright install'. Recommend codifying in a scrapers pattern: try curl_cffi first, fall back to Playwright only if the fingerprint route aborts. Include the mandatory-headers gotcha (missing an X-* header returns 403 even with valid Akamai cookies) and the reactive cookie-refresh strategy (one warmup GET against the public landing page, then refresh on first 403). Reference implementation: src/superbrain/scrapers/bookmakers/goldbet/client.py.

---
id: 2026-04-21-02
tier: reference
target: reference/patterns/scraper-idempotency-testing.md
date: 2026-04-21
status: pending
title: Test scraper idempotency by freezing datetime.now()
---

Our OddsSnapshot dedupe key includes captured_at, so two identical scrape runs in a test produce distinct rows because time advances between runs. Idempotency tests must monkeypatch datetime.now() to a frozen instant inside both the scraper and the parser modules so that both runs stamp identical captured_at values, letting Lake.ingest_odds exercise its real dedupe path. Applies to any scraper whose natural key includes a capture timestamp. Reference: tests/scrapers/bookmakers/goldbet/test_scraper.py::test_scrape_is_idempotent.
