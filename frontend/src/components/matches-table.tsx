import { Link } from "@tanstack/react-router";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TeamCrest } from "@/components/team-crest";
import { fmtDate, fmtTime } from "@/lib/format";
import { LEAGUE_LABEL, type Match } from "@/lib/types";

interface MatchesTableProps {
  matches: Match[];
  showKickoff?: boolean;
  emptyMessage?: string;
}

export function MatchesTable({ matches, showKickoff = true, emptyMessage }: MatchesTableProps) {
  if (matches.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        {emptyMessage ?? "No fixtures found."}
      </div>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[120px]">Date</TableHead>
          {showKickoff ? <TableHead className="w-[80px]">Kickoff</TableHead> : null}
          <TableHead>Home</TableHead>
          <TableHead>Away</TableHead>
          <TableHead className="w-[160px]">League</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {matches.map((m) => (
          <TableRow
            key={m.match_id}
            className="cursor-pointer"
            tabIndex={0}
            role="link"
            aria-label={`Open ${m.home_team} vs ${m.away_team}`}
          >
            <TableCell className="text-muted-foreground">
              <Link to="/matches/$id" params={{ id: m.match_id }} className="block">
                {fmtDate(m.match_date)}
              </Link>
            </TableCell>
            {showKickoff ? (
              <TableCell className="font-mono text-xs text-muted-foreground">
                <Link to="/matches/$id" params={{ id: m.match_id }}>
                  {fmtTime(m.kickoff_at ?? null)}
                </Link>
              </TableCell>
            ) : null}
            <TableCell>
              <Link to="/matches/$id" params={{ id: m.match_id }} className="flex items-center gap-2">
                <TeamCrest name={m.home_team} />
                <span className="font-medium">{m.home_team}</span>
              </Link>
            </TableCell>
            <TableCell>
              <Link to="/matches/$id" params={{ id: m.match_id }} className="flex items-center gap-2">
                <TeamCrest name={m.away_team} />
                <span className="font-medium">{m.away_team}</span>
              </Link>
            </TableCell>
            <TableCell>
              <Badge variant="outline">{LEAGUE_LABEL[m.league]}</Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
