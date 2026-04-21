import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Search } from "lucide-react";
import { api } from "@/lib/api";
import { LEAGUE_LABEL, leagueEnum, type League, type Match } from "@/lib/types";
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
import { MatchCard } from "@/components/match-card";
import { ErrorBanner } from "@/components/error-banner";
import { usePreferences } from "@/stores/preferences";

function defaultRange(): { from: string; to: string } {
  const today = new Date();
  const from = new Date(today);
  from.setDate(from.getDate() - 15);
  const to = new Date(today);
  to.setDate(to.getDate() + 7);
  return { from: toIsoDate(from), to: toIsoDate(to) };
}

function toIsoDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function todayIso(): string {
  return toIsoDate(new Date());
}

export function MatchesPage() {
  const selectedLeagues = usePreferences((s) => s.selectedLeagues);
  const setSelectedLeagues = usePreferences((s) => s.setSelectedLeagues);
  const initial = React.useMemo(defaultRange, []);
  const [dateFrom, setDateFrom] = React.useState(initial.from);
  const [dateTo, setDateTo] = React.useState(initial.to);
  const [search, setSearch] = React.useState("");
  const [debouncedSearch, setDebouncedSearch] = React.useState("");
  const [expandedId, setExpandedId] = React.useState<string | null>(null);

  React.useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(search), 250);
    return () => window.clearTimeout(handle);
  }, [search]);

  const query = useQuery({
    queryKey: ["matches", selectedLeagues, dateFrom, dateTo],
    queryFn: () =>
      api.listMatches({
        leagues: selectedLeagues.length ? selectedLeagues : undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
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

  const { upcoming, past } = React.useMemo(
    () => partitionMatches(query.data?.items ?? [], debouncedSearch),
    [query.data, debouncedSearch],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Matches"
        description="Recent results and upcoming fixtures. Click a card to see stats or the latest 1X2 odds."
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

      {query.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : (
        <MatchesSections
          upcoming={upcoming}
          past={past}
          expandedId={expandedId}
          onToggle={(id) => setExpandedId((current) => (current === id ? null : id))}
        />
      )}
    </div>
  );
}

function partitionMatches(
  items: Match[],
  searchTerm: string,
): { upcoming: Match[]; past: Match[] } {
  const today = todayIso();
  const needle = searchTerm.trim().toLowerCase();
  const filtered = needle
    ? items.filter(
        (m) =>
          m.home_team.toLowerCase().includes(needle) ||
          m.away_team.toLowerCase().includes(needle),
      )
    : items;
  const upcoming = filtered
    .filter((m) => m.match_date >= today)
    .sort((a, b) => a.match_date.localeCompare(b.match_date));
  const past = filtered
    .filter((m) => m.match_date < today)
    .sort((a, b) => b.match_date.localeCompare(a.match_date));
  return { upcoming, past };
}

function MatchesSections({
  upcoming,
  past,
  expandedId,
  onToggle,
}: {
  upcoming: Match[];
  past: Match[];
  expandedId: string | null;
  onToggle: (id: string) => void;
}) {
  if (upcoming.length === 0 && past.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        No fixtures match those filters.
      </div>
    );
  }
  return (
    <div className="space-y-8">
      <MatchesSection
        title="Upcoming"
        count={upcoming.length}
        emptyMessage="No upcoming fixtures in this range."
        matches={upcoming}
        variant="future"
        expandedId={expandedId}
        onToggle={onToggle}
      />
      <MatchesSection
        title="Past"
        count={past.length}
        emptyMessage="No past fixtures in this range."
        matches={past}
        variant="past"
        expandedId={expandedId}
        onToggle={onToggle}
      />
    </div>
  );
}

function MatchesSection({
  title,
  count,
  emptyMessage,
  matches,
  variant,
  expandedId,
  onToggle,
}: {
  title: string;
  count: number;
  emptyMessage: string;
  matches: Match[];
  variant: "past" | "future";
  expandedId: string | null;
  onToggle: (id: string) => void;
}) {
  return (
    <section aria-labelledby={`matches-${variant}-heading`} className="space-y-3">
      <div className="flex items-center justify-between">
        <h2
          id={`matches-${variant}-heading`}
          className="text-sm font-semibold uppercase tracking-wide text-muted-foreground"
        >
          {title}
          <span className="ml-2 font-normal text-muted-foreground/70">({count})</span>
        </h2>
      </div>
      {matches.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {emptyMessage}
        </div>
      ) : (
        <div className="space-y-3">
          {matches.map((m) => (
            <MatchCard
              key={m.match_id}
              match={m}
              variant={variant}
              expanded={expandedId === m.match_id}
              onToggle={() => onToggle(m.match_id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
