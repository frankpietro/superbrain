import { describe, expect, it } from "vitest";
import {
  CATEGORY_LABELS,
  categoryFor,
  fmtParams,
  humanNameFor,
  type MarketInfo,
} from "@/lib/markets";
import { groupByCategory } from "@/lib/odds-group";
import type { OddsSnapshot } from "@/lib/types";

const REGISTRY: MarketInfo[] = [
  { code: "match_1x2", human_name: "Match result (1X2)", category: "match_result", selections: ["1", "X", "2"] },
  { code: "goals_over_under", human_name: "Goals — total over/under", category: "goals", selections: ["OVER", "UNDER"] },
  { code: "corner_total", human_name: "Corners — total over/under", category: "corners", selections: ["OVER", "UNDER"] },
  { code: "cards_total", human_name: "Cards — total over/under", category: "cards", selections: ["OVER", "UNDER"] },
];

const byCode = new Map(REGISTRY.map((m) => [m.code, m]));

describe("markets helper", () => {
  it("resolves category for known codes", () => {
    expect(categoryFor("goals_over_under", byCode)).toBe("goals");
    expect(categoryFor("corner_total", byCode)).toBe("corners");
    expect(categoryFor("match_1x2", byCode)).toBe("match_result");
  });

  it("falls back to match_result for unknown codes", () => {
    expect(categoryFor("not_a_market", byCode)).toBe("match_result");
  });

  it("returns the human name when known, the raw code otherwise", () => {
    expect(humanNameFor("goals_over_under", byCode)).toBe("Goals — total over/under");
    expect(humanNameFor("future_exotic_market", byCode)).toBe("future_exotic_market");
  });

  it("has a label for every declared category", () => {
    for (const category of [
      "match_result",
      "goals",
      "corners",
      "cards",
      "shots",
      "combo",
      "halves",
    ] as const) {
      expect(CATEGORY_LABELS[category]).toBeTruthy();
    }
  });

  it("formats market params compactly", () => {
    expect(fmtParams({})).toBe("");
    expect(fmtParams({ threshold: 2.5 })).toBe("threshold=2.5");
    expect(fmtParams({ threshold: 2.5, team: "home" })).toBe("threshold=2.5 · team=home");
    expect(fmtParams({ threshold: null, team: "home" })).toBe("team=home");
  });
});

const makeRow = (overrides: Partial<OddsSnapshot>): OddsSnapshot => ({
  bookmaker: "sisal",
  market: "match_1x2",
  market_params: {},
  selection: "1",
  payout: 2.1,
  captured_at: "2026-04-21T12:00:00Z",
  ...overrides,
});

describe("groupByCategory", () => {
  it("buckets rows by MarketCategory and returns newest-first per bucket", () => {
    const rows = [
      makeRow({ market: "match_1x2", captured_at: "2026-04-21T10:00:00Z" }),
      makeRow({ market: "match_1x2", captured_at: "2026-04-21T11:00:00Z", bookmaker: "goldbet" }),
      makeRow({ market: "goals_over_under", captured_at: "2026-04-21T09:00:00Z" }),
      makeRow({ market: "corner_total", captured_at: "2026-04-21T12:00:00Z", bookmaker: "eurobet" }),
    ];
    const grouped = groupByCategory(rows, byCode);

    expect([...grouped.keys()].sort()).toEqual(["corners", "goals", "match_result"]);
    const matchBucket = grouped.get("match_result") ?? [];
    expect(matchBucket).toHaveLength(2);
    expect(matchBucket[0]?.captured_at).toBe("2026-04-21T11:00:00Z");
    expect(matchBucket[0]?.bookmaker).toBe("goldbet");
  });

  it("caps each bucket to perCategory rows, keeping the most recent", () => {
    const rows = Array.from({ length: 10 }).map((_, i) =>
      makeRow({
        market: "goals_over_under",
        captured_at: new Date(Date.UTC(2026, 3, 21, i, 0, 0)).toISOString(),
      }),
    );
    const grouped = groupByCategory(rows, byCode, { perCategory: 3 });
    const bucket = grouped.get("goals") ?? [];
    expect(bucket).toHaveLength(3);
    expect(bucket[0]?.captured_at).toBe("2026-04-21T09:00:00.000Z");
    expect(bucket[2]?.captured_at).toBe("2026-04-21T07:00:00.000Z");
  });

  it("routes unknown markets to the fallback match_result category", () => {
    const rows = [makeRow({ market: "some_new_market" })];
    const grouped = groupByCategory(rows, byCode);
    expect(grouped.get("match_result")).toHaveLength(1);
  });

  it("returns an empty map for no rows", () => {
    expect(groupByCategory([], byCode).size).toBe(0);
  });
});
