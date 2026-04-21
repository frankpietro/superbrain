import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { BOOKMAKER_LABEL, bookmakerEnum, type Bookmaker } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/page-header";
import { ErrorBanner } from "@/components/error-banner";
import { OddsRowsTable } from "@/components/odds-rows";
import { CATEGORY_LABELS, useMarketRegistry, type MarketCategory } from "@/lib/markets";

const PAGE_SIZE = 100;
const ALL_MARKETS = "__all__";
const DEFAULT_WINDOW_MS = 24 * 60 * 60 * 1000;

function toLocalDatetimeInput(isoUtc: string): string {
  // `datetime-local` inputs want `YYYY-MM-DDTHH:mm` in the user's local
  // timezone. Convert the UTC ISO string to that shape; trailing seconds /
  // milliseconds / `Z` all have to go.
  const d = new Date(isoUtc);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalDatetimeInput(local: string): string | undefined {
  // Treat the input as local time, convert to a UTC ISO string.
  if (!local) return undefined;
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString();
}

export function BetsRecentPage() {
  const [selectedBookmakers, setSelectedBookmakers] = React.useState<Bookmaker[]>([]);
  const [marketCode, setMarketCode] = React.useState<string>(ALL_MARKETS);
  const defaultSinceLocal = React.useMemo(
    () => toLocalDatetimeInput(new Date(Date.now() - DEFAULT_WINDOW_MS).toISOString()),
    [],
  );
  const [sinceLocal, setSinceLocal] = React.useState<string>(defaultSinceLocal);
  const [cursorStack, setCursorStack] = React.useState<string[]>([]);

  const markets = useMarketRegistry();
  const marketsByCategory = React.useMemo(() => {
    const groups = new Map<MarketCategory, { code: string; human_name: string }[]>();
    for (const m of markets.items) {
      const bucket = groups.get(m.category);
      if (bucket) bucket.push({ code: m.code, human_name: m.human_name });
      else groups.set(m.category, [{ code: m.code, human_name: m.human_name }]);
    }
    return groups;
  }, [markets.items]);

  const activeBookmaker =
    selectedBookmakers.length === 1 ? selectedBookmakers[0] : undefined;
  const capturedFrom = fromLocalDatetimeInput(sinceLocal);
  const currentCursor = cursorStack[cursorStack.length - 1];

  const oddsQuery = useQuery({
    queryKey: [
      "bets",
      "recent",
      activeBookmaker ?? null,
      marketCode,
      capturedFrom ?? null,
      currentCursor ?? null,
    ],
    queryFn: () =>
      api.listOdds({
        bookmaker: activeBookmaker,
        market: marketCode === ALL_MARKETS ? undefined : marketCode,
        captured_from: capturedFrom,
        limit: PAGE_SIZE,
        cursor: currentCursor,
      }),
  });

  // When the user has two bookmakers checked, the backend can only filter by
  // one — narrow on the client so the chips behave intuitively.
  const rows = React.useMemo(() => {
    const items = oddsQuery.data?.items ?? [];
    if (selectedBookmakers.length === 0 || selectedBookmakers.length === 3) return items;
    const allowed = new Set(selectedBookmakers);
    return items.filter((r) => allowed.has(r.bookmaker));
  }, [oddsQuery.data, selectedBookmakers]);

  // Any filter change resets pagination.
  React.useEffect(() => {
    setCursorStack([]);
  }, [activeBookmaker, marketCode, capturedFrom]);

  const toggleBookmaker = (bm: Bookmaker) => {
    setSelectedBookmakers((prev) =>
      prev.includes(bm) ? prev.filter((b) => b !== bm) : [...prev, bm],
    );
  };

  const nextCursor = oddsQuery.data?.next_cursor ?? null;
  const canGoNext = Boolean(nextCursor);
  const canGoPrev = cursorStack.length > 0;

  const goNext = () => {
    if (!nextCursor) return;
    setCursorStack((s) => [...s, nextCursor]);
  };
  const goPrev = () => setCursorStack((s) => s.slice(0, -1));

  const bookmakers = bookmakerEnum.options;
  const categories = Array.from(marketsByCategory.entries()).sort(([a], [b]) =>
    CATEGORY_LABELS[a].localeCompare(CATEGORY_LABELS[b]),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Recent bets"
        description="Every scraped odds row across providers, newest first."
      />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm text-muted-foreground">Filters</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="justify-between">
                {selectedBookmakers.length === 0
                  ? "All bookmakers"
                  : selectedBookmakers.length === 1
                    ? BOOKMAKER_LABEL[selectedBookmakers[0] as Bookmaker]
                    : `${selectedBookmakers.length} selected`}
                <ChevronDown className="ml-2 h-4 w-4 opacity-60" aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="w-[200px]">
              <DropdownMenuLabel>Bookmakers</DropdownMenuLabel>
              {bookmakers.map((bm) => (
                <DropdownMenuCheckboxItem
                  key={bm}
                  checked={selectedBookmakers.includes(bm)}
                  onCheckedChange={() => toggleBookmaker(bm)}
                >
                  {BOOKMAKER_LABEL[bm]}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <Select value={marketCode} onValueChange={setMarketCode}>
            <SelectTrigger aria-label="Market">
              <SelectValue placeholder="All markets" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_MARKETS}>All markets</SelectItem>
              {categories.map(([category, markets]) => (
                <React.Fragment key={category}>
                  <div className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {CATEGORY_LABELS[category]}
                  </div>
                  {markets
                    .slice()
                    .sort((a, b) => a.human_name.localeCompare(b.human_name))
                    .map((m) => (
                      <SelectItem key={m.code} value={m.code}>
                        {m.human_name}
                      </SelectItem>
                    ))}
                </React.Fragment>
              ))}
            </SelectContent>
          </Select>

          <Input
            type="datetime-local"
            value={sinceLocal}
            onChange={(e) => setSinceLocal(e.target.value)}
            aria-label="Captured from"
          />

          <Button
            variant="outline"
            onClick={() => oddsQuery.refetch()}
            disabled={oddsQuery.isFetching}
          >
            <RefreshCw
              className={`mr-2 h-4 w-4 ${oddsQuery.isFetching ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            Refresh
          </Button>
        </CardContent>
      </Card>

      {oddsQuery.error ? (
        <ErrorBanner
          title="Failed to load bets"
          description={oddsQuery.error instanceof Error ? oddsQuery.error.message : String(oddsQuery.error)}
        />
      ) : null}

      <Card>
        <CardContent className="p-0">
          {oddsQuery.isLoading || markets.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : (
            <OddsRowsTable
              rows={rows}
              markets={markets.byCode}
              emptyMessage="No bets match those filters."
            />
          )}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <div>
          Page {cursorStack.length + 1} · {rows.length} row
          {rows.length === 1 ? "" : "s"} shown
          {oddsQuery.data?.count !== undefined ? ` · server returned ${oddsQuery.data.count}` : ""}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={goPrev} disabled={!canGoPrev}>
            Previous
          </Button>
          <Button variant="outline" size="sm" onClick={goNext} disabled={!canGoNext}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
