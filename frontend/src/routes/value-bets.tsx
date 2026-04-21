import * as React from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Sparkles, ArrowUpDown, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import {
  BOOKMAKER_LABEL,
  LEAGUE_LABEL,
  MARKET_LABEL,
  leagueEnum,
  marketEnum,
  type ValueBet,
} from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

const ALL_LEAGUES = "__all__";
const ALL_MARKETS = "__all__";

export function ValueBetsPage() {
  const [sortKey, setSortKey] = React.useState<SortKey>("edge");
  const [desc, setDesc] = React.useState(true);
  const [league, setLeague] = React.useState<string>(ALL_LEAGUES);
  const [market, setMarket] = React.useState<string>(ALL_MARKETS);
  const [minEdgeInput, setMinEdgeInput] = React.useState<string>("0.03");
  const [minEdge, setMinEdge] = React.useState<number>(0.03);
  const [limit, setLimit] = React.useState<number>(200);

  const query = useQuery({
    queryKey: ["bets", "value", league, market, minEdge, limit],
    queryFn: () =>
      api.valueBets({
        league: league === ALL_LEAGUES ? undefined : league,
        markets: market === ALL_MARKETS ? undefined : [market],
        min_edge: Number.isFinite(minEdge) ? minEdge : undefined,
        limit,
      }),
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

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = parseFloat(minEdgeInput);
    setMinEdge(Number.isFinite(parsed) && parsed >= 0 ? parsed : 0);
  };

  const computedAt = query.data?.computed_at;
  const totalCount = query.data?.count ?? sorted.length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Value bets"
        description="Model-vs-book edge across every upcoming fixture."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => query.refetch()}
            disabled={query.isFetching}
          >
            <RefreshCw
              className={cn("h-4 w-4", query.isFetching && "animate-spin")}
              aria-hidden="true"
            />
            Refresh
          </Button>
        }
      />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm text-muted-foreground">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="grid grid-cols-1 gap-4 md:grid-cols-4"
            onSubmit={applyFilters}
          >
            <div className="space-y-1.5">
              <label htmlFor="vb-league" className="text-sm font-medium">
                League
              </label>
              <Select value={league} onValueChange={setLeague}>
                <SelectTrigger id="vb-league" aria-label="League">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_LEAGUES}>All leagues</SelectItem>
                  {leagueEnum.options.map((l) => (
                    <SelectItem key={l} value={l}>
                      {LEAGUE_LABEL[l]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="vb-market" className="text-sm font-medium">
                Market
              </label>
              <Select value={market} onValueChange={setMarket}>
                <SelectTrigger id="vb-market" aria-label="Market">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_MARKETS}>All markets</SelectItem>
                  {marketEnum.options.map((m) => (
                    <SelectItem key={m} value={m}>
                      {MARKET_LABEL[m] ?? m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="vb-minedge" className="text-sm font-medium">
                Min edge
              </label>
              <Input
                id="vb-minedge"
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={minEdgeInput}
                onChange={(e) => setMinEdgeInput(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="vb-limit" className="text-sm font-medium">
                Limit
              </label>
              <Input
                id="vb-limit"
                type="number"
                step="10"
                min="1"
                max="500"
                value={limit}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  if (Number.isFinite(v) && v > 0) setLimit(v);
                }}
              />
            </div>
            <div className="md:col-span-4">
              <Button type="submit" variant="secondary" size="sm">
                Apply filters
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {query.error ? (
        <ErrorBanner
          title="Failed to load value bets"
          description={query.error instanceof Error ? query.error.message : String(query.error)}
        />
      ) : null}

      {query.isLoading ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">Loading…</CardContent>
        </Card>
      ) : sorted.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center gap-3 p-10 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-accent-foreground">
              <Sparkles className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">No value bets for this filter</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Either no upcoming fixtures have sufficient history, no bookmaker price clears the
                minimum edge, or the league/market filter is too strict.
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2 text-xs text-muted-foreground">
              <Badge variant="outline">model_prob</Badge>
              <Badge variant="outline">book_prob</Badge>
              <Badge variant="outline">edge ≥ {fmtPct(minEdge, 2)}</Badge>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="flex-row items-start justify-between space-y-0 pb-3">
            <div>
              <CardTitle className="text-sm text-muted-foreground">
                {totalCount} candidates (edge ≥ {fmtPct(minEdge, 2)})
              </CardTitle>
              {computedAt ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Computed {new Date(computedAt).toLocaleString()}
                </p>
              ) : null}
            </div>
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
                  <TableHead className="text-right">n</TableHead>
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
                    <TableCell className="text-right font-mono text-xs text-muted-foreground">
                      {bet.sample_size ?? 0}
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
      )}
    </div>
  );
}
