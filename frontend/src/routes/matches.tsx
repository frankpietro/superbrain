import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Search } from "lucide-react";
import { api } from "@/lib/api";
import { LEAGUE_LABEL, leagueEnum, type League } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/page-header";
import { MatchesTable } from "@/components/matches-table";
import { ErrorBanner } from "@/components/error-banner";
import { usePreferences } from "@/stores/preferences";

export function MatchesPage() {
  const selectedLeagues = usePreferences((s) => s.selectedLeagues);
  const setSelectedLeagues = usePreferences((s) => s.setSelectedLeagues);
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [debouncedSearch, setDebouncedSearch] = React.useState("");

  React.useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(search), 250);
    return () => window.clearTimeout(handle);
  }, [search]);

  const query = useQuery({
    queryKey: ["matches", selectedLeagues, dateFrom, dateTo, debouncedSearch],
    queryFn: () =>
      api.listMatches({
        leagues: selectedLeagues.length ? selectedLeagues : undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        search: debouncedSearch || undefined,
        limit: 500,
      }),
  });

  const toggleLeague = (league: League) => {
    const next = selectedLeagues.includes(league)
      ? selectedLeagues.filter((l) => l !== league)
      : [...selectedLeagues, league];
    setSelectedLeagues(next);
  };

  const leagues = leagueEnum.options;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Matches"
        description="Fixture catalog across the five leagues. Click a row to see its odds grid."
      />
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm text-muted-foreground">Filters</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="justify-between">
                {selectedLeagues.length === 0
                  ? "All leagues"
                  : `${selectedLeagues.length} selected`}
                <ChevronDown className="ml-2 h-4 w-4 opacity-60" aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="w-[220px]">
              <DropdownMenuLabel>Leagues</DropdownMenuLabel>
              {leagues.map((league) => (
                <DropdownMenuCheckboxItem
                  key={league}
                  checked={selectedLeagues.includes(league)}
                  onCheckedChange={() => toggleLeague(league)}
                >
                  {LEAGUE_LABEL[league]}
                </DropdownMenuCheckboxItem>
              ))}
              {selectedLeagues.length > 0 ? (
                <button
                  type="button"
                  className="mt-1 flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent"
                  onClick={() => setSelectedLeagues([])}
                >
                  <Check className="h-3 w-3" aria-hidden="true" />
                  Clear selection
                </button>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
          <Input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            aria-label="Date from"
          />
          <Input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            aria-label="Date to"
          />
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search team…"
              className="pl-8"
              aria-label="Team search"
            />
          </div>
        </CardContent>
      </Card>

      {query.error ? (
        <ErrorBanner
          title="Failed to load matches"
          description={query.error instanceof Error ? query.error.message : String(query.error)}
        />
      ) : null}

      <Card>
        <CardContent className="p-0">
          {query.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : (
            <MatchesTable matches={query.data?.items ?? []} showKickoff={false} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
