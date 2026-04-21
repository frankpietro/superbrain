import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type MarketCategory =
  | "match_result"
  | "goals"
  | "corners"
  | "cards"
  | "shots"
  | "combo"
  | "halves";

export const CATEGORY_LABELS: Record<MarketCategory, string> = {
  match_result: "Match result",
  goals: "Goals",
  corners: "Corners",
  cards: "Cards",
  shots: "Shots",
  combo: "Combo",
  halves: "Halves",
};

export const CATEGORY_ORDER: MarketCategory[] = [
  "match_result",
  "goals",
  "corners",
  "cards",
  "shots",
  "combo",
  "halves",
];

export interface MarketInfo {
  code: string;
  human_name: string;
  category: MarketCategory;
  selections: string[];
}

const UNKNOWN_CATEGORY: MarketCategory = "match_result";

function narrowCategory(raw: string): MarketCategory {
  if (
    raw === "match_result" ||
    raw === "goals" ||
    raw === "corners" ||
    raw === "cards" ||
    raw === "shots" ||
    raw === "combo" ||
    raw === "halves"
  ) {
    return raw;
  }
  return UNKNOWN_CATEGORY;
}

export function useMarketRegistry(): {
  byCode: Map<string, MarketInfo>;
  items: MarketInfo[];
  isLoading: boolean;
  error: unknown;
} {
  const query = useQuery({
    queryKey: ["markets", "list"],
    queryFn: () => api.marketList(),
    staleTime: 10 * 60_000,
  });
  const items: MarketInfo[] = (query.data?.items ?? []).map((m) => ({
    code: m.code,
    human_name: m.human_name,
    category: narrowCategory(m.category),
    selections: m.selections,
  }));
  const byCode = new Map(items.map((m) => [m.code, m]));
  return { byCode, items, isLoading: query.isLoading, error: query.error };
}

export function categoryFor(
  code: string,
  byCode: Map<string, MarketInfo>,
): MarketCategory {
  return byCode.get(code)?.category ?? UNKNOWN_CATEGORY;
}

export function humanNameFor(
  code: string,
  byCode: Map<string, MarketInfo>,
): string {
  return byCode.get(code)?.human_name ?? code;
}

export function fmtParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== null && v !== undefined);
  if (entries.length === 0) return "";
  return entries.map(([k, v]) => `${k}=${String(v)}`).join(" · ");
}
