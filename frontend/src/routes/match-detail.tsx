import * as React from "react";
import { useParams, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import { BOOKMAKER_LABEL, LEAGUE_LABEL, MARKET_LABEL, type Bookmaker } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { PageHeader } from "@/components/page-header";
import { TeamCrest } from "@/components/team-crest";
import { ErrorBanner } from "@/components/error-banner";
import { fmtDate, fmtOdds, fmtTime } from "@/lib/format";

type OddsCell = { payout: number; capturedAt: string; selection: string };
type OddsRow = {
  marketKey: string;
  humanName: string;
  cells: Partial<Record<Bookmaker, Record<string, OddsCell>>>;
  selections: string[];
};

function pivot(
  snapshots: Array<{
    bookmaker: Bookmaker;
    market: string;
    selection: string;
    payout: number;
    captured_at: string;
    market_params: Record<string, unknown>;
  }>,
): OddsRow[] {
  const rows = new Map<string, OddsRow>();
  for (const s of snapshots) {
    const paramKey = Object.entries(s.market_params)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${k}=${String(v)}`)
      .join(",");
    const key = paramKey ? `${s.market}|${paramKey}` : s.market;
    const human = MARKET_LABEL[s.market] ?? s.market;
    const label = paramKey ? `${human} · ${paramKey}` : human;
    let row = rows.get(key);
    if (!row) {
      row = { marketKey: key, humanName: label, cells: {}, selections: [] };
      rows.set(key, row);
    }
    const bmCells = row.cells[s.bookmaker] ?? {};
    const prev = bmCells[s.selection];
    if (!prev || prev.capturedAt < s.captured_at) {
      bmCells[s.selection] = {
        payout: s.payout,
        capturedAt: s.captured_at,
        selection: s.selection,
      };
    }
    row.cells[s.bookmaker] = bmCells;
    if (!row.selections.includes(s.selection)) row.selections.push(s.selection);
  }
  return Array.from(rows.values()).sort((a, b) => a.humanName.localeCompare(b.humanName));
}

const MAPPED_MARKETS = new Set(Object.keys(MARKET_LABEL));

export function MatchDetailPage() {
  const { id } = useParams({ from: "/_shell/matches/$id" });
  const [onlyMapped, setOnlyMapped] = React.useState(true);

  const matchQuery = useQuery({
    queryKey: ["match", id],
    queryFn: () => api.getMatch(id),
  });
  const oddsQuery = useQuery({
    queryKey: ["odds", id],
    queryFn: () => api.listOdds({ match_id: id }),
  });

  const rows = React.useMemo(() => {
    if (!oddsQuery.data) return [];
    const pivoted = pivot(oddsQuery.data.items);
    return onlyMapped
      ? pivoted.filter((r) => MAPPED_MARKETS.has(r.marketKey.split("|")[0] ?? r.marketKey))
      : pivoted;
  }, [oddsQuery.data, onlyMapped]);

  const bookmakers: Bookmaker[] = ["sisal", "goldbet", "eurobet"];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/matches">
            <ArrowLeft className="mr-1 h-4 w-4" aria-hidden="true" />
            Back to matches
          </Link>
        </Button>
      </div>

      {matchQuery.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : matchQuery.error ? (
        <ErrorBanner
          title="Failed to load match"
          description={
            matchQuery.error instanceof Error ? matchQuery.error.message : String(matchQuery.error)
          }
        />
      ) : matchQuery.data ? (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <Badge variant="outline">{LEAGUE_LABEL[matchQuery.data.league]}</Badge>
              <Badge variant="secondary">{matchQuery.data.season}</Badge>
              <span className="text-xs text-muted-foreground">
                {fmtDate(matchQuery.data.match_date, "EEEE d MMMM yyyy")}
                {matchQuery.data.kickoff_at
                  ? ` · KO ${fmtTime(matchQuery.data.kickoff_at)}`
                  : ""}
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <PageHeader
              className="mb-0"
              title={`${matchQuery.data.home_team} vs ${matchQuery.data.away_team}`}
            />
            <div className="mt-4 flex items-center gap-6 text-sm text-muted-foreground">
              <div className="flex items-center gap-2">
                <TeamCrest name={matchQuery.data.home_team} />
                <span className="font-medium text-foreground">{matchQuery.data.home_team}</span>
              </div>
              <span className="text-xs">vs</span>
              <div className="flex items-center gap-2">
                <TeamCrest name={matchQuery.data.away_team} />
                <span className="font-medium text-foreground">{matchQuery.data.away_team}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-2 space-y-0 pb-3">
          <CardTitle>Odds grid</CardTitle>
          <Tabs value={onlyMapped ? "mapped" : "all"} onValueChange={(v) => setOnlyMapped(v === "mapped")}>
            <TabsList>
              <TabsTrigger value="mapped">Mapped markets</TabsTrigger>
              <TabsTrigger value="all">All markets</TabsTrigger>
            </TabsList>
            <TabsContent value="mapped" />
            <TabsContent value="all" />
          </Tabs>
        </CardHeader>
        <CardContent className="p-0">
          {oddsQuery.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : oddsQuery.error ? (
            <div className="p-4">
              <ErrorBanner
                title="Failed to load odds"
                description={
                  oddsQuery.error instanceof Error ? oddsQuery.error.message : String(oddsQuery.error)
                }
              />
            </div>
          ) : rows.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              No odds captured yet for this fixture.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[240px]">Market</TableHead>
                  <TableHead className="w-[140px]">Selection</TableHead>
                  {bookmakers.map((bm) => (
                    <TableHead key={bm} className="w-[120px] text-right">
                      {BOOKMAKER_LABEL[bm]}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) =>
                  row.selections.map((sel, idx) => (
                    <TableRow key={`${row.marketKey}-${sel}`}>
                      {idx === 0 ? (
                        <TableCell rowSpan={row.selections.length} className="font-medium align-top">
                          {row.humanName}
                        </TableCell>
                      ) : null}
                      <TableCell className="font-mono text-xs text-muted-foreground">{sel}</TableCell>
                      {bookmakers.map((bm) => {
                        const cell = row.cells[bm]?.[sel];
                        if (!cell) {
                          return (
                            <TableCell key={bm} className="text-right text-muted-foreground">
                              —
                            </TableCell>
                          );
                        }
                        return (
                          <TableCell key={bm} className="text-right font-mono">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span tabIndex={0} aria-label={`${BOOKMAKER_LABEL[bm]} ${sel} ${fmtOdds(cell.payout)}`}>
                                  {fmtOdds(cell.payout)}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>
                                updated {fmtTime(cell.capturedAt, "yyyy-MM-dd HH:mm:ss")}
                              </TooltipContent>
                            </Tooltip>
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  )),
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
