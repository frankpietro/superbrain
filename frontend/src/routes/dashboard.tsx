import { useQuery } from "@tanstack/react-query";
import { Activity, Calendar, Sparkles, CircleAlert, CircleCheck, CircleDot } from "lucide-react";
import { format } from "date-fns";
import { api } from "@/lib/api";
import { BOOKMAKER_LABEL, type ScraperStatus } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/page-header";
import { MatchesTable } from "@/components/matches-table";
import { ErrorBanner } from "@/components/error-banner";
import { cn } from "@/lib/utils";

function healthColor(status: ScraperStatus | undefined): {
  label: string;
  className: string;
  Icon: React.ComponentType<{ className?: string }>;
} {
  if (!status || !status.last_run) {
    return {
      label: "never",
      className: "bg-muted text-muted-foreground",
      Icon: CircleDot,
    };
  }
  if (status.healthy && status.last_run.status === "ok") {
    return {
      label: status.last_run.status,
      className: "bg-success/15 text-success",
      Icon: CircleCheck,
    };
  }
  if (status.last_run.status === "partial") {
    return {
      label: "partial",
      className: "bg-warning/15 text-warning",
      Icon: CircleDot,
    };
  }
  return {
    label: status.last_run.status,
    className: "bg-destructive/15 text-destructive",
    Icon: CircleAlert,
  };
}

export function DashboardPage() {
  const today = format(new Date(), "yyyy-MM-dd");
  const matchesQuery = useQuery({
    queryKey: ["matches", "today", today],
    queryFn: () => api.listMatches({ date_from: today, date_to: today, limit: 200 }),
  });
  const statusQuery = useQuery({
    queryKey: ["scrapers", "status"],
    queryFn: () => api.scrapersStatus(),
  });
  const valueQuery = useQuery({
    queryKey: ["bets", "value"],
    queryFn: () => api.valueBets(),
  });

  const todayMatches = matchesQuery.data?.items ?? [];
  const valueCount = valueQuery.data?.items.length ?? 0;
  const anyError = matchesQuery.error || statusQuery.error || valueQuery.error;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Today's fixtures, scraper health, and the value-bet pipeline at a glance."
      />

      {anyError ? (
        <ErrorBanner
          title="Some data failed to load"
          description={anyError instanceof Error ? anyError.message : String(anyError)}
        />
      ) : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm text-muted-foreground">Fixtures today</CardTitle>
            <Calendar className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          </CardHeader>
          <CardContent>
            {matchesQuery.isLoading ? (
              <Skeleton className="h-8 w-12" />
            ) : (
              <div className="text-3xl font-bold">{todayMatches.length}</div>
            )}
            <p className="mt-1 text-xs text-muted-foreground">
              {matchesQuery.isLoading ? "loading" : "scheduled across the five leagues"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm text-muted-foreground">Value bets</CardTitle>
            <Sparkles className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          </CardHeader>
          <CardContent>
            {valueQuery.isLoading ? (
              <Skeleton className="h-8 w-12" />
            ) : (
              <div className="text-3xl font-bold">{valueCount}</div>
            )}
            <p className="mt-1 text-xs text-muted-foreground">
              {valueCount === 0 ? "engine not yet wired (phase 4b)" : "candidates with positive edge"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm text-muted-foreground">Scraper health</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          </CardHeader>
          <CardContent>
            {statusQuery.isLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-5/6" />
                <Skeleton className="h-4 w-4/6" />
              </div>
            ) : (
              <ul className="space-y-2">
                {statusQuery.data?.items.map((status) => {
                  const { label, className, Icon } = healthColor(status);
                  return (
                    <li
                      key={status.bookmaker}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="font-medium">{BOOKMAKER_LABEL[status.bookmaker]}</span>
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                          className,
                        )}
                      >
                        <Icon className="h-3 w-3" aria-hidden="true" />
                        {label}
                      </span>
                    </li>
                  );
                }) ?? null}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Matches today</CardTitle>
        </CardHeader>
        <CardContent>
          {matchesQuery.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : (
            <MatchesTable matches={todayMatches} emptyMessage="No fixtures today." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
