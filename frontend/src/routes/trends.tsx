import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, Timer } from "lucide-react";
import { api } from "@/lib/api";
import { MARKET_LABEL, type TrendsVariabilityRow } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/page-header";
import { ErrorBanner } from "@/components/error-banner";
import { Chart } from "@/components/plot";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const GROUP_LABEL: Record<"market" | "team" | "match", string> = {
  market: "Bet type",
  team: "Team",
  match: "Match",
};

const WINDOW_OPTIONS: { value: number; label: string }[] = [
  { value: 24, label: "Last 24h" },
  { value: 72, label: "Last 3 days" },
  { value: 168, label: "Last 7 days" },
  { value: 24 * 30, label: "Last 30 days" },
];

const BUCKET_OPTIONS: { value: number; label: string }[] = [
  { value: 3, label: "3h buckets" },
  { value: 6, label: "6h buckets" },
  { value: 12, label: "12h buckets" },
  { value: 24, label: "24h buckets" },
];

function fmtPct(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`;
}

function rowLabel(group: "market" | "team" | "match", row: TrendsVariabilityRow): string {
  if (group === "market") return MARKET_LABEL[row.key] ?? row.label;
  return row.label;
}

export function TrendsPage() {
  const [group, setGroup] = useState<"market" | "team" | "match">("market");
  const [windowHours, setWindowHours] = useState<number>(168);
  const [bucketHours, setBucketHours] = useState<number>(6);

  const variabilityQuery = useQuery({
    queryKey: ["trends", "variability", group, windowHours],
    queryFn: () =>
      api.trendsVariability({
        group_by: group,
        since_hours: windowHours,
        min_points: 3,
        limit: 25,
      }),
  });

  const ttkQuery = useQuery({
    queryKey: ["trends", "ttk", bucketHours, windowHours],
    queryFn: () =>
      api.trendsTimeToKickoff({
        bucket_hours: bucketHours,
        since_hours: windowHours,
        min_points: 3,
      }),
  });

  const variabilityItems = useMemo(
    () => variabilityQuery.data?.items ?? [],
    [variabilityQuery.data],
  );
  const chartItems = useMemo(() => variabilityItems.slice(0, 12), [variabilityItems]);
  const totalSeries = variabilityQuery.data?.total_series ?? 0;
  const ttkBuckets = ttkQuery.data?.buckets ?? [];

  const anyError = variabilityQuery.error || ttkQuery.error;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trends"
        description="How volatile the odds are by bet type, match, and team — plus how quickly quotes typically move as kickoff approaches."
        actions={
          <Select
            value={String(windowHours)}
            onValueChange={(v) => setWindowHours(Number(v))}
          >
            <SelectTrigger className="w-40">
              <SelectValue placeholder="Window" />
            </SelectTrigger>
            <SelectContent>
              {WINDOW_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={String(opt.value)}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      {anyError ? (
        <ErrorBanner
          title="Some trend data failed to load"
          description={anyError instanceof Error ? anyError.message : String(anyError)}
        />
      ) : null}

      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4" aria-hidden="true" />
              Odds variability
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Coefficient of variation (stddev / mean) averaged over every selection tracked at
              least 3 times in the chosen window. Higher means the line moves more.
            </p>
          </div>
          <Badge variant="outline">
            {totalSeries.toLocaleString()} series
          </Badge>
        </CardHeader>
        <CardContent className="space-y-4">
          <Tabs value={group} onValueChange={(v) => setGroup(v as typeof group)}>
            <TabsList>
              <TabsTrigger value="market">{GROUP_LABEL.market}</TabsTrigger>
              <TabsTrigger value="match">{GROUP_LABEL.match}</TabsTrigger>
              <TabsTrigger value="team">{GROUP_LABEL.team}</TabsTrigger>
            </TabsList>
            <TabsContent value={group}>
              {variabilityQuery.isLoading ? (
                <Skeleton className="h-64 w-full" />
              ) : variabilityItems.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  No selections with at least 3 snapshots in the chosen window yet.
                </p>
              ) : (
                <div className="space-y-4">
                  <div className="h-64 rounded-md border border-border bg-muted/30 p-2">
                    <Chart
                      ariaLabel={`average coefficient of variation per ${group}`}
                      data={[
                        {
                          type: "bar",
                          orientation: "h",
                          x: chartItems
                            .slice()
                            .reverse()
                            .map((r) => r.avg_cv_pct),
                          y: chartItems
                            .slice()
                            .reverse()
                            .map((r) => rowLabel(group, r)),
                          marker: { color: "hsl(155, 66%, 36%)" },
                          hovertemplate: "%{y}<br>avg CV %{x:.2f}%<extra></extra>",
                        },
                      ]}
                      layout={{
                        margin: { t: 8, r: 16, b: 32, l: 140 },
                        xaxis: { title: "avg CV (%)", gridcolor: "rgba(0,0,0,0.08)" },
                        yaxis: { automargin: true },
                      }}
                    />
                  </div>

                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{GROUP_LABEL[group]}</TableHead>
                        <TableHead className="text-right">Series</TableHead>
                        <TableHead className="text-right">Samples</TableHead>
                        <TableHead className="text-right">Avg CV</TableHead>
                        <TableHead className="text-right">Avg range</TableHead>
                        <TableHead className="text-right">Max CV</TableHead>
                        <TableHead className="text-right">Avg payout</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {variabilityItems.map((row) => (
                        <TableRow key={row.key}>
                          <TableCell className="font-medium">{rowLabel(group, row)}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {row.series_count.toLocaleString()}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {row.observation_count.toLocaleString()}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtPct(row.avg_cv_pct, 2)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtPct(row.avg_range_pct, 2)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtPct(row.max_cv_pct, 2)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {row.avg_payout.toFixed(2)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Timer className="h-4 w-4" aria-hidden="true" />
              Change likelihood vs time to kickoff
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              For every consecutive pair of captures, this buckets the midpoint's distance to
              kickoff and reports how often odds moved and by how much.
            </p>
          </div>
          <Select
            value={String(bucketHours)}
            onValueChange={(v) => setBucketHours(Number(v))}
          >
            <SelectTrigger className="w-36">
              <SelectValue placeholder="Bucket" />
            </SelectTrigger>
            <SelectContent>
              {BUCKET_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={String(opt.value)}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent className="space-y-4">
          {ttkQuery.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : ttkBuckets.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Not enough consecutive captures to infer a time-to-kickoff pattern yet.
            </p>
          ) : (
            <>
              <div className="h-64 rounded-md border border-border bg-muted/30 p-2">
                <Chart
                  ariaLabel="odds change magnitude vs hours to kickoff"
                  data={[
                    {
                      type: "bar",
                      name: "mean |Δ|%",
                      x: ttkBuckets.map((b) => b.hours_min + (b.hours_max - b.hours_min) / 2),
                      y: ttkBuckets.map((b) => b.mean_abs_delta_pct),
                      marker: { color: "hsl(155, 66%, 36%)" },
                      hovertemplate:
                        "%{x:.0f}h to kickoff<br>mean |Δ| %{y:.2f}%<extra></extra>",
                    },
                    {
                      type: "scatter",
                      mode: "lines+markers",
                      name: "P(change)",
                      x: ttkBuckets.map((b) => b.hours_min + (b.hours_max - b.hours_min) / 2),
                      y: ttkBuckets.map((b) => b.prob_any_change * 100),
                      line: { color: "hsl(22, 86%, 48%)", width: 2 },
                      marker: { size: 6 },
                      yaxis: "y2",
                      hovertemplate:
                        "%{x:.0f}h to kickoff<br>change probability %{y:.0f}%<extra></extra>",
                    },
                  ]}
                  layout={{
                    showlegend: true,
                    legend: { orientation: "h", y: -0.25 },
                    margin: { t: 8, r: 48, b: 40, l: 48 },
                    xaxis: { title: "hours to kickoff (bucket midpoint)" },
                    yaxis: { title: "mean |Δ| (%)", gridcolor: "rgba(0,0,0,0.08)" },
                    yaxis2: {
                      title: "change prob. (%)",
                      overlaying: "y",
                      side: "right",
                      range: [0, 100],
                    },
                  }}
                />
              </div>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Hours to kickoff</TableHead>
                    <TableHead className="text-right">Transitions</TableHead>
                    <TableHead className="text-right">Series</TableHead>
                    <TableHead className="text-right">Mean |Δ|</TableHead>
                    <TableHead className="text-right">Median |Δ|</TableHead>
                    <TableHead className="text-right">P90 |Δ|</TableHead>
                    <TableHead className="text-right">P(change)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ttkBuckets.map((b) => (
                    <TableRow key={`${b.hours_min}-${b.hours_max}`}>
                      <TableCell className="font-medium tabular-nums">
                        {b.hours_min.toFixed(0)}–{b.hours_max.toFixed(0)}h
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {b.n_transitions.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {b.n_series.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtPct(b.mean_abs_delta_pct, 2)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtPct(b.median_abs_delta_pct, 2)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtPct(b.p90_abs_delta_pct, 2)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtPct(b.prob_any_change * 100, 0)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
