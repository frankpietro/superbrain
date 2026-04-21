import { categoryFor, type MarketCategory, type MarketInfo } from "@/lib/markets";
import type { OddsSnapshot } from "@/lib/types";

export interface GroupByCategoryOptions {
  perCategory?: number;
}

export function groupByCategory(
  rows: OddsSnapshot[],
  byCode: Map<string, MarketInfo>,
  opts: GroupByCategoryOptions = {},
): Map<MarketCategory, OddsSnapshot[]> {
  const perCategory = opts.perCategory ?? 6;
  const sorted = rows.slice().sort((a, b) => (a.captured_at < b.captured_at ? 1 : -1));
  const groups = new Map<MarketCategory, OddsSnapshot[]>();
  for (const row of sorted) {
    const category = categoryFor(row.market, byCode);
    const bucket = groups.get(category);
    if (bucket) {
      if (bucket.length < perCategory) bucket.push(row);
    } else {
      groups.set(category, [row]);
    }
  }
  return groups;
}
