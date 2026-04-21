import * as React from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2, Play } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import {
  type BacktestRunResponse,
  LEAGUE_LABEL,
  leagueEnum,
  marketEnum,
  MARKET_LABEL,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { toast } from "@/components/ui/toaster";
import { fmtDate, fmtOdds, fmtPct } from "@/lib/format";

const ALL_MARKETS = "__all__";

type SortKey = "match_date" | "edge" | "model_probability" | "decimal_odds" | "profit";

export function BacktestPage() {
  const [league, setLeague] = React.useState<string>("serie_a");
  const [season, setSeason] = React.useState<string>("2024-25");
  const [market, setMarket] = React.useState<string>("match_1x2");
  const [threshold, setThreshold] = React.useState<string>("");
  const [edgeCutoff, setEdgeCutoff] = React.useState<string>("0.05");
  const [stake, setStake] = React.useState<string>("1");
  const [minHistory, setMinHistory] = React.useState<string>("6");
  const [sortKey, setSortKey] = React.useState<SortKey>("edge");
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("desc");

  const runMutation = useMutation<BacktestRunResponse>({
    mutationFn: () =>
      api.runBacktest({
        league,
        season,
        market: market === ALL_MARKETS ? undefined : market,
        threshold: threshold.trim() ? Number(threshold) : undefined,
        edge_cutoff: Number.isFinite(parseFloat(edgeCutoff)) ? parseFloat(edgeCutoff) : undefined,
        stake: Number.isFinite(parseFloat(stake)) ? parseFloat(stake) : undefined,
        min_history_matches: Number.isFinite(parseInt(minHistory, 10))
          ? parseInt(minHistory, 10)
          : undefined,
      }),
    onSuccess: (data) => {
      toast({
        variant: "success",
        title: `Backtest complete`,
        description: `${data.summary.n_bets} bets across ${data.fixtures_considered} fixtures`,
      });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 400) {
        toast({
          variant: "destructive",
          title: "Cannot run backtest",
          description: typeof err.payload === "object" && err.payload && "detail" in err.payload
            ? String((err.payload as { detail: unknown }).detail)
            : err.message,
        });
        return;
      }
      toast({
        variant: "destructive",
        title: "Backtest failed",
        description: err instanceof Error ? err.message : String(err),
      });
    },
  });

  const report = runMutation.data;

  const sortedBets = React.useMemo(() => {
    if (!report) return [];
    const rows = [...report.bets];
    rows.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return rows;
  }, [report, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Backtest"
        description="Sliding-window ROI over a league, season, and (optional) market. Engine walks fixtures chronologically with a strict no-leakage guard."
      />
      <Card>
        <CardHeader>
          <CardTitle>Run a backtest</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="grid grid-cols-1 gap-4 md:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              runMutation.mutate();
            }}
          >
            <div className="space-y-1.5">
              <label htmlFor="bt-league" className="text-sm font-medium">
                League
              </label>
              <Select value={league} onValueChange={setLeague}>
                <SelectTrigger id="bt-league" aria-label="League">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {leagueEnum.options.map((l) => (
                    <SelectItem key={l} value={l}>
                      {LEAGUE_LABEL[l]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="bt-season" className="text-sm font-medium">
                Season
              </label>
              <Input
                id="bt-season"
                value={season}
                onChange={(e) => setSeason(e.target.value)}
                placeholder="2024-25"
                pattern="\d{4}-\d{2}"
                required
              />
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <label htmlFor="bt-market" className="text-sm font-medium">
                Market
              </label>
              <Select value={market} onValueChange={setMarket}>
                <SelectTrigger id="bt-market" aria-label="Market">
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
              <label htmlFor="bt-threshold" className="text-sm font-medium">
                Threshold (line, optional)
              </label>
              <Input
                id="bt-threshold"
                type="number"
                step="0.5"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                placeholder="e.g. 2.5"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="bt-edge" className="text-sm font-medium">
                Edge cutoff
              </label>
              <Input
                id="bt-edge"
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={edgeCutoff}
                onChange={(e) => setEdgeCutoff(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="bt-stake" className="text-sm font-medium">
                Stake per bet
              </label>
              <Input
                id="bt-stake"
                type="number"
                step="0.5"
                min="0.01"
                value={stake}
                onChange={(e) => setStake(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="bt-min-history" className="text-sm font-medium">
                Min history matches
              </label>
              <Input
                id="bt-min-history"
                type="number"
                step="1"
                min="1"
                value={minHistory}
                onChange={(e) => setMinHistory(e.target.value)}
              />
            </div>
            <div className="md:col-span-2">
              <Button type="submit" disabled={runMutation.isPending}>
                {runMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Play className="h-4 w-4" aria-hidden="true" />
                )}
                Run
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {report ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <SummaryTile label="Fixtures" value={String(report.fixtures_considered)} />
            <SummaryTile
              label="Bets placed"
              value={`${report.summary.n_bets} (${report.summary.n_wins}W / ${report.summary.n_losses}L)`}
              sub={report.summary.n_unresolved > 0 ? `${report.summary.n_unresolved} unresolved` : undefined}
            />
            <SummaryTile
              label="ROI"
              value={fmtPct(report.summary.roi, 2)}
              emphasis={roiColor(report.summary.roi)}
            />
            <SummaryTile label="Hit rate" value={fmtPct(report.summary.hit_rate, 1)} />
            <SummaryTile
              label="Total staked"
              value={report.summary.total_stake.toFixed(2)}
            />
            <SummaryTile
              label="Total profit"
              value={report.summary.total_profit.toFixed(2)}
              emphasis={roiColor(report.summary.total_profit)}
            />
            <SummaryTile label="Sharpe" value={report.summary.sharpe.toFixed(2)} />
            <SummaryTile
              label="Avg stake"
              value={
                report.summary.n_bets > 0
                  ? (report.summary.total_stake / Math.max(1, report.summary.n_bets)).toFixed(2)
                  : "—"
              }
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Placed bets</CardTitle>
            </CardHeader>
            <CardContent>
              {sortedBets.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No value bets were produced with these parameters. Try lowering the edge cutoff,
                  widening the market, or relaxing the threshold.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <SortableHeader label="Date" active={sortKey === "match_date"} dir={sortDir} onClick={() => toggleSort("match_date")} />
                        <TableHead>Match</TableHead>
                        <TableHead>Market / Selection</TableHead>
                        <TableHead>Book</TableHead>
                        <SortableHeader label="Odds" active={sortKey === "decimal_odds"} dir={sortDir} onClick={() => toggleSort("decimal_odds")} className="text-right" />
                        <SortableHeader label="P(model)" active={sortKey === "model_probability"} dir={sortDir} onClick={() => toggleSort("model_probability")} className="text-right" />
                        <SortableHeader label="Edge" active={sortKey === "edge"} dir={sortDir} onClick={() => toggleSort("edge")} className="text-right" />
                        <TableHead className="text-right">Result</TableHead>
                        <SortableHeader label="Profit" active={sortKey === "profit"} dir={sortDir} onClick={() => toggleSort("profit")} className="text-right" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {sortedBets.map((b) => (
                        <TableRow key={`${b.match_id}-${b.market}-${b.selection}-${b.bookmaker}`}>
                          <TableCell>{fmtDate(b.match_date)}</TableCell>
                          <TableCell>
                            {b.home_team} <span className="text-muted-foreground">vs</span> {b.away_team}
                          </TableCell>
                          <TableCell>
                            <span className="font-medium">{MARKET_LABEL[b.market] ?? b.market}</span>
                            <span className="text-muted-foreground"> · {b.selection}</span>
                          </TableCell>
                          <TableCell className="capitalize">{b.bookmaker}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtOdds(b.decimal_odds)}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtPct(b.model_probability, 1)}</TableCell>
                          <TableCell className={`text-right tabular-nums ${b.edge > 0 ? "text-emerald-600" : "text-rose-600"}`}>
                            {fmtPct(b.edge, 1)}
                          </TableCell>
                          <TableCell className="text-right">
                            {b.won === true ? (
                              <Badge className="bg-emerald-600 hover:bg-emerald-600">Win</Badge>
                            ) : b.won === false ? (
                              <Badge variant="destructive">Loss</Badge>
                            ) : (
                              <Badge variant="secondary">—</Badge>
                            )}
                          </TableCell>
                          <TableCell className={`text-right tabular-nums ${b.profit > 0 ? "text-emerald-600" : b.profit < 0 ? "text-rose-600" : ""}`}>
                            {b.profit.toFixed(2)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}

function SummaryTile({
  label,
  value,
  sub,
  emphasis,
}: {
  label: string;
  value: string;
  sub?: string;
  emphasis?: "pos" | "neg";
}) {
  const color =
    emphasis === "pos" ? "text-emerald-600" : emphasis === "neg" ? "text-rose-600" : "";
  return (
    <Card>
      <CardContent className="pt-5">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
        {sub ? <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div> : null}
      </CardContent>
    </Card>
  );
}

function SortableHeader({
  label,
  active,
  dir,
  onClick,
  className,
}: {
  label: string;
  active: boolean;
  dir: "asc" | "desc";
  onClick: () => void;
  className?: string;
}) {
  return (
    <TableHead className={className}>
      <button
        type="button"
        onClick={onClick}
        className="inline-flex items-center gap-1 text-left font-medium hover:underline"
      >
        {label}
        {active ? <span aria-hidden="true">{dir === "asc" ? "▲" : "▼"}</span> : null}
      </button>
    </TableHead>
  );
}

function roiColor(value: number): "pos" | "neg" | undefined {
  if (value > 0) return "pos";
  if (value < 0) return "neg";
  return undefined;
}
