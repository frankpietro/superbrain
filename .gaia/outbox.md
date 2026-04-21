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

---
id: 2026-04-21-03
tier: reference
target: reference/patterns/apscheduler-cron.md
date: 2026-04-21
status: pending
title: APScheduler from_crontab weekday indexing gotcha
---

APScheduler's CronTrigger.from_crontab uses APScheduler-native weekday indexing (0=Mon..6=Sun), not POSIX cron (0=Sun..6=Sat). A crontab string like "0 4 * * 1-5" therefore fires Tue-Sat, not Mon-Fri. Recommendation for any Gaia-seeded project using APScheduler: always pass named weekdays ("mon-fri") in crontab strings, or build CronTrigger(day_of_week=...) directly. Surfaced during Phase 5 of superbrain; cost ~20 min of failing trigger tests.

---
id: 2026-04-21-04
tier: reference
target: reference/preferences.md
date: 2026-04-21
status: pending
title: Filter pytest-asyncio unraisable-exception leak on Python 3.12
---

pytest-asyncio 1.x leaks an event loop + socket per module boundary on Python 3.12 via _temporary_event_loop_policy. When filterwarnings=['error'] is set (which we recommend), any later test that triggers gc.collect() (hypothesis' register_random does this on its own) converts those leaks into session-level failures via PytestUnraisableExceptionWarning. Until pytest-asyncio ships a fix, projects that use both async tests and filterwarnings=error should add 'ignore::pytest.PytestUnraisableExceptionWarning' to their pyproject.toml filterwarnings list. Consider documenting this in Tier-2 preferences under the testing section.

---
id: 2026-04-21-05
tier: reference
target: reference/patterns/frontend-plotly-sizing.md
date: 2026-04-21
status: pending
title: react-plotly.js: wrapper must have concrete dimensions
---

When using react-plotly.js with useResizeHandler and style={{ width: '100%', height: '100%' }} on the inner <Plot>, the wrapper div MUST have concrete width/height. A bare <div> (no className, no inline size) collapses and Plotly's 100% has nothing to resolve against, so it falls back to its default autosize (~450×700 px) and overflows the parent slot — visibly leaking y-axis tick labels across surrounding UI. Proposed Gaia reference pattern: a short entry under reference/patterns/frontend-plotly-sizing.md recommending that any shared Chart/Plot wrapper default its outermost div to h-full w-full (or equivalent) and document the failure mode. Caught in superbrain's scrapers page; see docs/knowledge.md Gotchas (2026-04-21) and fix/scraper-card-chart-overflow.

---
id: 2026-04-21-06
tier: reference
target: reference/patterns/radix-multiselect.md
date: 2026-04-21
status: pending
title: Multi-select dropdown: stop Radix closing on every click
---

Radix DropdownMenuCheckboxItem closes the menu on select by default; for a multi-select UX callers want the menu to stay open across several toggles. The clean fix is to bake `onSelect: preventDefault` into the shadcn wrapper primitive itself, keeping callers terse. Worth a pattern snippet. See superbrain PR #34 and frontend/src/components/ui/dropdown-menu.tsx.
