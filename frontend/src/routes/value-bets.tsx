import * as React from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Sparkles, ArrowUpDown } from "lucide-react";
import { api } from "@/lib/api";
import { BOOKMAKER_LABEL, LEAGUE_LABEL, MARKET_LABEL, type ValueBet } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";
import { ErrorBanner } from "@/components/error-banner";
import { Badge } from "@/components/ui/badge";
import { fmtOdds, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

type SortKey = "edge" | "decimal_odds" | "model_prob";

export function ValueBetsPage() {
  const [sortKey, setSortKey] = React.useState<SortKey>("edge");
  const [desc, setDesc] = React.useState(true);

  const query = useQuery({
    queryKey: ["bets", "value"],
    queryFn: () => api.valueBets(),
  });

  const sorted = React.useMemo<ValueBet[]>(() => {
    const items = query.data?.items ?? [];
    return [...items].sort((a, b) => {
      const delta = (b[sortKey] ?? 0) - (a[sortKey] ?? 0);
      return desc ? delta : -delta;
    });
  }, [query.data, sortKey, desc]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setDesc((d) => !d);
    else {
      setSortKey(key);
      setDesc(true);
    }
  };

  if (query.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Value bets" />
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">Loading…</CardContent>
        </Card>
      </div>
    );
  }

  if (query.error) {
    return (
      <div className="space-y-6">
        <PageHeader title="Value bets" />
        <ErrorBanner
          title="Failed to load value bets"
          description={query.error instanceof Error ? query.error.message : String(query.error)}
        />
      </div>
    );
  }

  if (sorted.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Value bets"
          description="Model-vs-book edge across every live fixture."
        />
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-accent-foreground">
              <Sparkles className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Engine not yet wired</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Value-bet generation ships in phase 4b (feature ablation + clustering + probability).
                Until then, this screen stays empty on purpose — no placeholders, no fake edges.
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-muted-foreground">
              <Badge variant="outline">coming in phase 4b</Badge>
              <Badge variant="outline">model_prob</Badge>
              <Badge variant="outline">book_prob</Badge>
              <Badge variant="outline">edge</Badge>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Value bets"
        description={`${sorted.length} candidates across all live fixtures.`}
      />
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm text-muted-foreground">Top edges</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Match</TableHead>
                <TableHead>Market</TableHead>
                <TableHead>Selection</TableHead>
                <TableHead>Book</TableHead>
                <TableHead className="cursor-pointer text-right" onClick={() => toggleSort("decimal_odds")}>
                  <div className="inline-flex items-center gap-1">
                    Odds <ArrowUpDown className="h-3 w-3" />
                  </div>
                </TableHead>
                <TableHead className="cursor-pointer text-right" onClick={() => toggleSort("model_prob")}>
                  <div className="inline-flex items-center gap-1">
                    Model P <ArrowUpDown className="h-3 w-3" />
                  </div>
                </TableHead>
                <TableHead className="text-right">Book P</TableHead>
                <TableHead className="cursor-pointer text-right" onClick={() => toggleSort("edge")}>
                  <div className="inline-flex items-center gap-1">
                    Edge <ArrowUpDown className="h-3 w-3" />
                  </div>
                </TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((bet) => (
                <TableRow key={`${bet.match_id}-${bet.market}-${bet.selection}-${bet.bookmaker}`}>
                  <TableCell>
                    <div className="font-medium">{bet.match_label}</div>
                    <div className="text-xs text-muted-foreground">{LEAGUE_LABEL[bet.league]}</div>
                  </TableCell>
                  <TableCell>{MARKET_LABEL[bet.market] ?? bet.market}</TableCell>
                  <TableCell className="font-mono text-xs">{bet.selection}</TableCell>
                  <TableCell>{BOOKMAKER_LABEL[bet.bookmaker]}</TableCell>
                  <TableCell className="text-right font-mono">{fmtOdds(bet.decimal_odds)}</TableCell>
                  <TableCell className="text-right font-mono">{fmtPct(bet.model_prob)}</TableCell>
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {fmtPct(bet.book_prob)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-mono font-semibold",
                      bet.edge > 0 ? "text-success" : "text-destructive",
                    )}
                  >
                    {fmtPct(bet.edge, 2)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" asChild>
                      <Link to="/matches/$id" params={{ id: bet.match_id }}>
                        Open
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
