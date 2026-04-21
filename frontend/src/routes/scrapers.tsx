import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Loader2, AlertCircle, CheckCircle2, CircleDot } from "lucide-react";
import { api } from "@/lib/api";
import { BOOKMAKER_LABEL, type ScraperStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/page-header";
import { ErrorBanner } from "@/components/error-banner";
import { Chart } from "@/components/plot";
import { toast } from "@/components/ui/toaster";
import { fmtTime } from "@/lib/format";

function statusBadge(status: ScraperStatus): React.ReactNode {
  const latest = status.last_run;
  if (!latest) {
    return (
      <Badge variant="outline" className="gap-1">
        <CircleDot className="h-3 w-3" /> never run
      </Badge>
    );
  }
  if (latest.status === "ok" && status.healthy) {
    return (
      <Badge variant="success" className="gap-1">
        <CheckCircle2 className="h-3 w-3" /> healthy
      </Badge>
    );
  }
  if (latest.status === "partial") {
    return (
      <Badge variant="warning" className="gap-1">
        <CircleDot className="h-3 w-3" /> partial
      </Badge>
    );
  }
  return (
    <Badge variant="destructive" className="gap-1">
      <AlertCircle className="h-3 w-3" /> {latest.status}
    </Badge>
  );
}

export function ScrapersPage() {
  const qc = useQueryClient();
  const statusQuery = useQuery({
    queryKey: ["scrapers", "status"],
    queryFn: () => api.scrapersStatus(),
    refetchInterval: 30_000,
  });

  const triggerMutation = useMutation({
    mutationFn: (bookmaker: string) => api.triggerScrape(bookmaker),
    onSuccess: (data, bookmaker) => {
      toast({
        variant: "success",
        title: `Triggered ${BOOKMAKER_LABEL[bookmaker as "sisal" | "goldbet" | "eurobet"]}`,
        description: `run_id ${data.run_id}`,
      });
      qc.invalidateQueries({ queryKey: ["scrapers"] });
    },
    onError: (err) =>
      toast({
        variant: "destructive",
        title: "Trigger failed",
        description:
          err instanceof Error
            ? err.message
            : "Backend refused the request (endpoint may not be wired yet).",
      }),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Scrapers"
        description="Per-bookmaker health, most recent rows, and the top unmapped markets flagged by each scraper."
      />

      {statusQuery.error ? (
        <ErrorBanner
          title="Failed to load scraper status"
          description={
            statusQuery.error instanceof Error ? statusQuery.error.message : String(statusQuery.error)
          }
        />
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {statusQuery.isLoading
          ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-80" />)
          : (statusQuery.data?.items ?? []).map((status) => {
              const history = status.history.slice().reverse();
              const xs = history.map((h) => h.run_id);
              const ys = history.map((h) => h.rows_written);
              return (
                <Card key={status.bookmaker}>
                  <CardHeader className="flex-row items-center justify-between space-y-0">
                    <div>
                      <CardTitle className="flex items-center gap-2">
                        {BOOKMAKER_LABEL[status.bookmaker]}
                      </CardTitle>
                      <p className="mt-1 text-xs text-muted-foreground">
                        last run{" "}
                        {status.last_run
                          ? fmtTime(status.last_run.started_at, "yyyy-MM-dd HH:mm:ss")
                          : "never"}
                      </p>
                    </div>
                    {statusBadge(status)}
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <div className="text-muted-foreground">rows written</div>
                        <div className="font-semibold">
                          {status.last_run?.rows_written.toLocaleString() ?? "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">rows rejected</div>
                        <div className="font-semibold">
                          {status.last_run?.rows_rejected.toLocaleString() ?? "—"}
                        </div>
                      </div>
                    </div>

                    <div className="h-36 rounded-md border border-border bg-muted/30 p-2">
                      {history.length > 0 ? (
                        <Chart
                          ariaLabel={`rows written per run — ${BOOKMAKER_LABEL[status.bookmaker]}`}
                          data={[
                            {
                              x: xs,
                              y: ys,
                              type: "scatter",
                              mode: "lines+markers",
                              line: { color: "hsl(155, 66%, 36%)", width: 2 },
                              marker: { size: 6 },
                              hovertemplate: "%{y:,} rows<extra></extra>",
                            },
                          ]}
                          layout={{
                            xaxis: { showticklabels: false, showgrid: false, zeroline: false },
                            yaxis: { gridcolor: "rgba(0,0,0,0.08)", zeroline: false },
                          }}
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                          No history yet.
                        </div>
                      )}
                    </div>

                    <div>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Top unmapped markets
                      </div>
                      {status.unmapped_markets_top.length === 0 ? (
                        <p className="text-xs text-muted-foreground">None — all markets parsed.</p>
                      ) : (
                        <ul className="space-y-1 text-sm">
                          {status.unmapped_markets_top.slice(0, 10).map((u) => (
                            <li key={u.name} className="flex items-center justify-between">
                              <span className="truncate pr-2">{u.name}</span>
                              <Badge variant="outline">{u.count}</Badge>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <Button
                      variant="outline"
                      className="w-full"
                      disabled={triggerMutation.isPending}
                      onClick={() => triggerMutation.mutate(status.bookmaker)}
                    >
                      {triggerMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                      ) : (
                        <Play className="h-4 w-4" aria-hidden="true" />
                      )}
                      Trigger scrape
                    </Button>
                  </CardContent>
                </Card>
              );
            })}
      </div>
    </div>
  );
}
