import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TeamCrest } from "@/components/team-crest";
import { api } from "@/lib/api";
import {
  BOOKMAKER_LABEL,
  LEAGUE_LABEL,
  type Bookmaker,
  type Match,
  type TeamMatchStatsRow,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { fmtDate, fmtOdds } from "@/lib/format";

interface MatchCardProps {
  match: Match;
  variant: "past" | "future";
  expanded: boolean;
  onToggle: () => void;
}

export function MatchCard({ match, variant, expanded, onToggle }: MatchCardProps) {
  const headerId = `match-card-${match.match_id}`;
  const panelId = `${headerId}-panel`;
  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        id={headerId}
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={onToggle}
        className={cn(
          "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors",
          "hover:bg-accent/40 focus-visible:bg-accent/40 focus:outline-none",
        )}
      >
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">{LEAGUE_LABEL[match.league]}</Badge>
            <span>{fmtDate(match.match_date, "EEE d MMM yyyy")}</span>
            {variant === "past" ? (
              <Badge variant="secondary" className="uppercase tracking-wide">
                FT
              </Badge>
            ) : (
              <Badge variant="secondary" className="uppercase tracking-wide">
                Upcoming
              </Badge>
            )}
          </div>
          {variant === "past" ? (
            <PastSummary match={match} />
          ) : (
            <FutureSummary match={match} />
          )}
        </div>
        <div className="shrink-0 text-muted-foreground" aria-hidden="true">
          {expanded ? (
            <ChevronUp className="h-5 w-5" />
          ) : (
            <ChevronDown className="h-5 w-5" />
          )}
        </div>
      </button>
      {expanded ? (
        <div id={panelId} role="region" aria-labelledby={headerId}>
          <CardContent className="border-t border-border bg-muted/20 p-4">
            {variant === "past" ? (
              <PastExpanded match={match} />
            ) : (
              <FutureExpanded match={match} />
            )}
          </CardContent>
        </div>
      ) : null}
    </Card>
  );
}

function PastSummary({ match }: { match: Match }) {
  const homeGoals = match.home_goals;
  const awayGoals = match.away_goals;
  const score =
    homeGoals != null && awayGoals != null
      ? `${homeGoals} – ${awayGoals}`
      : "— – —";
  const xgLine =
    match.home_xg != null || match.away_xg != null
      ? `xG ${fmtOdds(match.home_xg)} – ${fmtOdds(match.away_xg)}`
      : null;
  return (
    <div className="flex items-center gap-4">
      <TeamColumn name={match.home_team} align="end" />
      <div className="flex min-w-[96px] flex-col items-center">
        <span className="text-xl font-semibold tabular-nums">{score}</span>
        {xgLine ? (
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {xgLine}
          </span>
        ) : null}
      </div>
      <TeamColumn name={match.away_team} align="start" />
    </div>
  );
}

function FutureSummary({ match }: { match: Match }) {
  return (
    <div className="flex items-center gap-4">
      <TeamColumn name={match.home_team} align="end" />
      <div className="flex min-w-[96px] flex-col items-center">
        <span className="text-lg font-medium text-muted-foreground">vs</span>
      </div>
      <TeamColumn name={match.away_team} align="start" />
    </div>
  );
}

function TeamColumn({ name, align }: { name: string; align: "start" | "end" }) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 items-center gap-2",
        align === "end" ? "justify-end" : "justify-start",
      )}
    >
      {align === "end" ? (
        <>
          <span className="truncate font-medium">{name}</span>
          <TeamCrest name={name} />
        </>
      ) : (
        <>
          <TeamCrest name={name} />
          <span className="truncate font-medium">{name}</span>
        </>
      )}
    </div>
  );
}

function PastExpanded({ match }: { match: Match }) {
  const statsQuery = useQuery({
    queryKey: ["match-stats", match.match_id],
    queryFn: () => api.getMatchStats(match.match_id),
    staleTime: 60_000,
  });

  if (statsQuery.isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
      </div>
    );
  }
  if (statsQuery.error) {
    return (
      <p className="text-sm text-destructive">
        Failed to load stats:{" "}
        {statsQuery.error instanceof Error
          ? statsQuery.error.message
          : String(statsQuery.error)}
      </p>
    );
  }
  const data = statsQuery.data;
  if (!data || (!data.home && !data.away)) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          No detailed stats captured for this fixture yet.
        </p>
        <Link
          to="/matches/$id"
          params={{ id: match.match_id }}
          className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          Open match page
          <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <StatsTable home={data.home} away={data.away} />
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/matches/$id" params={{ id: match.match_id }}>
            Match page
            <ExternalLink className="ml-1 h-3.5 w-3.5" />
          </Link>
        </Button>
      </div>
    </div>
  );
}

type StatDef = {
  key: keyof TeamMatchStatsRow;
  label: string;
  format?: (v: number) => string;
};

const STAT_DEFS: StatDef[] = [
  { key: "goals", label: "Goals" },
  { key: "xg", label: "Expected goals (xG)", format: (v) => v.toFixed(2) },
  { key: "ht_goals", label: "Half-time goals" },
  { key: "shots", label: "Shots" },
  { key: "shots_on_target", label: "Shots on target" },
  { key: "shots_off_target", label: "Shots off target" },
  { key: "shots_in_box", label: "Shots in box" },
  { key: "big_chances", label: "Big chances" },
  { key: "big_chances_missed", label: "Big chances missed" },
  { key: "corners", label: "Corners" },
  { key: "fouls", label: "Fouls" },
  { key: "yellow_cards", label: "Yellow cards" },
  { key: "red_cards", label: "Red cards" },
  { key: "offsides", label: "Offsides" },
  {
    key: "possession_pct",
    label: "Possession",
    format: (v) => `${v.toFixed(0)}%`,
  },
  { key: "passes", label: "Passes" },
  {
    key: "pass_accuracy_pct",
    label: "Pass accuracy",
    format: (v) => `${v.toFixed(0)}%`,
  },
  { key: "tackles", label: "Tackles" },
  { key: "interceptions", label: "Interceptions" },
  { key: "aerials_won", label: "Aerials won" },
  { key: "saves", label: "Saves" },
  { key: "xga", label: "xGA", format: (v) => v.toFixed(2) },
  { key: "ppda", label: "PPDA", format: (v) => v.toFixed(2) },
];

function fmtStat(value: unknown, format?: (v: number) => string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return format ? format(value) : String(value);
}

function StatsTable({
  home,
  away,
}: {
  home: TeamMatchStatsRow | null;
  away: TeamMatchStatsRow | null;
}) {
  const rows = STAT_DEFS.filter((def) => {
    const h = home?.[def.key];
    const a = away?.[def.key];
    return (
      (typeof h === "number" && Number.isFinite(h)) ||
      (typeof a === "number" && Number.isFinite(a))
    );
  });
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Stats row present but every metric is empty.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="py-1.5 text-right font-medium">
              {home?.team ?? "Home"}
            </th>
            <th className="py-1.5 text-center text-xs uppercase tracking-wide text-muted-foreground">
              Stat
            </th>
            <th className="py-1.5 text-left font-medium">
              {away?.team ?? "Away"}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((def) => (
            <tr key={def.key as string} className="border-b border-border/50">
              <td className="py-1 text-right tabular-nums">
                {fmtStat(home?.[def.key], def.format)}
              </td>
              <td className="py-1 text-center text-xs text-muted-foreground">
                {def.label}
              </td>
              <td className="py-1 text-left tabular-nums">
                {fmtStat(away?.[def.key], def.format)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type OnexTwoCell = { payout: number; capturedAt: string };
type OnexTwoPerBookmaker = Partial<
  Record<Bookmaker, { "1"?: OnexTwoCell; X?: OnexTwoCell; "2"?: OnexTwoCell }>
>;

function latestOneXTwo(
  snapshots: Array<{
    bookmaker: Bookmaker;
    market: string;
    selection: string;
    payout: number;
    captured_at: string;
  }>,
): OnexTwoPerBookmaker {
  const out: OnexTwoPerBookmaker = {};
  for (const s of snapshots) {
    if (s.market !== "match_1x2") continue;
    if (!["1", "X", "2"].includes(s.selection)) continue;
    const bm = (out[s.bookmaker] ??= {});
    const slot = s.selection as "1" | "X" | "2";
    const prev = bm[slot];
    if (!prev || prev.capturedAt < s.captured_at) {
      bm[slot] = { payout: s.payout, capturedAt: s.captured_at };
    }
  }
  return out;
}

function FutureExpanded({ match }: { match: Match }) {
  const oddsQuery = useQuery({
    queryKey: ["match-1x2", match.match_id],
    queryFn: () =>
      api.listOdds({ match_id: match.match_id, market: "match_1x2" }),
    staleTime: 30_000,
  });

  if (oddsQuery.isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
      </div>
    );
  }
  if (oddsQuery.error) {
    return (
      <p className="text-sm text-destructive">
        Failed to load odds:{" "}
        {oddsQuery.error instanceof Error
          ? oddsQuery.error.message
          : String(oddsQuery.error)}
      </p>
    );
  }
  const latest = latestOneXTwo(oddsQuery.data?.items ?? []);
  const bookmakers = (Object.keys(latest) as Bookmaker[]).sort();
  if (bookmakers.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          No 1X2 odds captured yet for this fixture.
        </p>
        <Link
          to="/matches/$id"
          params={{ id: match.match_id }}
          className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          Open full odds grid
          <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-1.5 text-left font-medium">Bookmaker</th>
              <th className="py-1.5 text-right font-medium">1</th>
              <th className="py-1.5 text-right font-medium">X</th>
              <th className="py-1.5 text-right font-medium">2</th>
            </tr>
          </thead>
          <tbody>
            {bookmakers.map((bm) => {
              const cell = latest[bm] ?? {};
              return (
                <tr key={bm} className="border-b border-border/50">
                  <td className="py-1">{BOOKMAKER_LABEL[bm]}</td>
                  <td className="py-1 text-right tabular-nums">
                    {fmtOdds(cell["1"]?.payout)}
                  </td>
                  <td className="py-1 text-right tabular-nums">
                    {fmtOdds(cell.X?.payout)}
                  </td>
                  <td className="py-1 text-right tabular-nums">
                    {fmtOdds(cell["2"]?.payout)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/matches/$id" params={{ id: match.match_id }}>
            Full odds grid
            <ExternalLink className="ml-1 h-3.5 w-3.5" />
          </Link>
        </Button>
      </div>
    </div>
  );
}
