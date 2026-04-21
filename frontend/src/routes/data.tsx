import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database, FileStack } from "lucide-react";
import { api } from "@/lib/api";
import type { DataPartition, DataTableOverview } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/page-header";
import { ErrorBanner } from "@/components/error-banner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Chart } from "@/components/plot";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const TABLE_LABELS: Record<string, string> = {
  matches: "Matches",
  team_match_stats: "Team match stats",
  odds: "Odds",
  team_elo: "Team Elo",
  scrape_runs: "Scrape runs",
  simulation_runs: "Simulation runs",
};

function fmt(n: number): string {
  return n.toLocaleString();
}

function partitionLabel(p: DataPartition, keys: string[]): string {
  return keys.map((k) => `${k}=${p.values[k] ?? ""}`).join(" · ");
}

function yearOfSeason(season: string): string | null {
  const m = /^(\d{4})/.exec(season);
  return m?.[1] ?? null;
}

/** Bucket partitions along one key and pick a shape suited to its cardinality. */
function aggregateBy(
  partitions: DataPartition[],
  key: string,
): { label: string; rows: number }[] {
  const totals = new Map<string, number>();
  for (const p of partitions) {
    const label = p.values[key] ?? "—";
    totals.set(label, (totals.get(label) ?? 0) + p.rows);
  }
  return Array.from(totals.entries())
    .map(([label, rows]) => ({ label, rows }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function DataPage() {
  const query = useQuery({
    queryKey: ["data", "overview"],
    queryFn: () => api.dataOverview(),
  });

  const tables = useMemo(() => query.data?.tables ?? [], [query.data]);
  const initialTab = useMemo(() => {
    const firstRich = tables.find((t) => t.total_rows > 0);
    return firstRich?.name ?? tables[0]?.name ?? "matches";
  }, [tables]);
  const [activeTab, setActiveTab] = useState<string>(initialTab);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data"
        description="Inventory of the lake: rows per league and season, schemas, and a few real rows from each table."
      />

      {query.error ? (
        <ErrorBanner
          title="Failed to load lake overview"
          description={query.error instanceof Error ? query.error.message : String(query.error)}
        />
      ) : null}

      {query.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <>
          <Summary tables={tables} lakeRoot={query.data?.lake_root ?? ""} />
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="flex flex-wrap">
              {tables.map((t) => (
                <TabsTrigger key={t.name} value={t.name}>
                  {TABLE_LABELS[t.name] ?? t.name}
                  <span className="ml-2 text-xs text-muted-foreground">
                    {fmt(t.total_rows)}
                  </span>
                </TabsTrigger>
              ))}
            </TabsList>
            {tables.map((t) => (
              <TabsContent key={t.name} value={t.name} className="space-y-4">
                <TableDetail table={t} />
              </TabsContent>
            ))}
          </Tabs>
        </>
      )}
    </div>
  );
}

function Summary({ tables, lakeRoot }: { tables: DataTableOverview[]; lakeRoot: string }) {
  const total = tables.reduce((acc, t) => acc + t.total_rows, 0);
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm text-muted-foreground">
          <Database className="h-4 w-4" aria-hidden="true" />
          Lake at <code className="rounded bg-muted px-1 py-0.5 text-xs">{lakeRoot}</code>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 md:grid-cols-6">
        {tables.map((t) => (
          <div
            key={t.name}
            className="rounded-md border border-border bg-card/50 p-3"
          >
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              {TABLE_LABELS[t.name] ?? t.name}
            </div>
            <div className="mt-1 text-2xl font-semibold">{fmt(t.total_rows)}</div>
            <div className="text-xs text-muted-foreground">
              {t.partitions.length} partitions · {t.columns.length} cols
            </div>
          </div>
        ))}
        <div className="col-span-2 rounded-md border border-border bg-primary/5 p-3 md:col-span-6">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            Grand total
          </div>
          <div className="mt-1 text-2xl font-semibold">{fmt(total)} rows</div>
        </div>
      </CardContent>
    </Card>
  );
}

function TableDetail({ table }: { table: DataTableOverview }) {
  if (!table.exists) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          No data directory on disk yet.
        </CardContent>
      </Card>
    );
  }
  if (table.total_rows === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          The table exists but is empty.
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-4">
      <BreakdownCards table={table} />
      <PartitionTable table={table} />
      <SchemaCard table={table} />
      <SamplesCard table={table} />
    </div>
  );
}

function BreakdownCards({ table }: { table: DataTableOverview }) {
  const leagueBuckets = table.partition_keys.includes("league")
    ? aggregateBy(table.partitions, "league")
    : null;
  const seasonBuckets = table.partition_keys.includes("season")
    ? aggregateBy(table.partitions, "season")
    : null;
  const yearBuckets = seasonBuckets
    ? aggregateBy(
        table.partitions.map((p) => ({
          ...p,
          values: {
            ...p.values,
            year: yearOfSeason(p.values.season ?? "") ?? "—",
          },
        })),
        "year",
      )
    : null;
  const bookmakerBuckets = table.partition_keys.includes("bookmaker")
    ? aggregateBy(table.partitions, "bookmaker")
    : null;

  const charts: { title: string; data: { label: string; rows: number }[] }[] = [];
  if (leagueBuckets) charts.push({ title: "Rows by league", data: leagueBuckets });
  if (yearBuckets) charts.push({ title: "Rows by year", data: yearBuckets });
  if (seasonBuckets && !yearBuckets)
    charts.push({ title: "Rows by season", data: seasonBuckets });
  if (bookmakerBuckets)
    charts.push({ title: "Rows by bookmaker", data: bookmakerBuckets });

  if (charts.length === 0) return null;

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {charts.map((c) => (
        <Card key={c.title}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{c.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-56 w-full">
              <Chart
                ariaLabel={c.title}
                data={[
                  {
                    type: "bar",
                    x: c.data.map((d) => d.label),
                    y: c.data.map((d) => d.rows),
                    marker: { color: "hsl(221, 83%, 53%)" },
                    hovertemplate: "%{x}: %{y:,} rows<extra></extra>",
                  },
                ]}
                layout={{
                  margin: { t: 16, r: 16, b: 56, l: 48 },
                  xaxis: { tickangle: -30 },
                  yaxis: { gridcolor: "rgba(127,127,127,0.15)", zeroline: false },
                }}
              />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function PartitionTable({ table }: { table: DataTableOverview }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileStack className="h-4 w-4" aria-hidden="true" />
          Partitions
          <Badge variant="secondary" className="font-normal">
            {table.partitions.length}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="max-h-80 overflow-y-auto rounded-md border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                {table.partition_keys.map((k) => (
                  <TableHead key={k}>{k}</TableHead>
                ))}
                <TableHead className="text-right">rows</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {table.partitions.map((p) => (
                <TableRow key={partitionLabel(p, table.partition_keys)}>
                  {table.partition_keys.map((k) => (
                    <TableCell key={k} className="font-mono text-xs">
                      {p.values[k] ?? "—"}
                    </TableCell>
                  ))}
                  <TableCell className="text-right font-mono text-xs">
                    {fmt(p.rows)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

function SchemaCard({ table }: { table: DataTableOverview }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          Schema <span className="text-muted-foreground">({table.columns.length})</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          {table.columns.map((c) => (
            <Badge key={c.name} variant="secondary" className="font-mono text-xs">
              {c.name}
              <span className="ml-2 text-muted-foreground">{c.dtype}</span>
            </Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function SamplesCard({ table }: { table: DataTableOverview }) {
  if (table.samples.length === 0) return null;
  const headers = table.columns.map((c) => c.name);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          Sample rows <span className="text-muted-foreground">({table.samples.length})</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-md border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                {headers.map((h) => (
                  <TableHead key={h} className="whitespace-nowrap">
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {table.samples.map((row, i) => (
                <TableRow key={i}>
                  {headers.map((h) => (
                    <TableCell
                      key={h}
                      className="max-w-[260px] truncate font-mono text-xs"
                      title={row[h] ?? ""}
                    >
                      {row[h] ?? <span className="text-muted-foreground">null</span>}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
