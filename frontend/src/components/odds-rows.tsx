import * as React from "react";
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
import { fmtOdds, fmtTime } from "@/lib/format";
import {
  fmtParams,
  humanNameFor,
  type MarketInfo,
} from "@/lib/markets";
import { BOOKMAKER_LABEL, type Bookmaker, type OddsSnapshot } from "@/lib/types";

const BOOKMAKER_BADGE: Record<Bookmaker, "default" | "secondary" | "outline"> = {
  sisal: "default",
  goldbet: "secondary",
  eurobet: "outline",
};

interface OddsRowsTableProps {
  rows: OddsSnapshot[];
  markets: Map<string, MarketInfo>;
  showMatch?: boolean;
  emptyMessage?: string;
}

export function OddsRowsTable({
  rows,
  markets,
  showMatch = true,
  emptyMessage,
}: OddsRowsTableProps) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
        {emptyMessage ?? "No rows yet."}
      </div>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[150px]">Captured</TableHead>
          <TableHead className="w-[90px]">Bookmaker</TableHead>
          {showMatch ? <TableHead>Match</TableHead> : null}
          <TableHead>Market</TableHead>
          <TableHead className="w-[120px]">Selection</TableHead>
          <TableHead className="w-[80px] text-right">Odds</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, i) => (
          <OddsRow
            key={`${row.bookmaker}-${row.run_id ?? ""}-${row.market}-${row.selection}-${row.captured_at}-${i}`}
            row={row}
            markets={markets}
            showMatch={showMatch}
          />
        ))}
      </TableBody>
    </Table>
  );
}

function OddsRow({
  row,
  markets,
  showMatch,
}: {
  row: OddsSnapshot;
  markets: Map<string, MarketInfo>;
  showMatch: boolean;
}): React.ReactElement {
  const marketHuman = humanNameFor(row.market, markets);
  const params = fmtParams(row.market_params);
  const matchLabel = row.match_label ?? matchLabelFromTeams(row);
  return (
    <TableRow>
      <TableCell className="font-mono text-xs text-muted-foreground">
        {fmtTime(row.captured_at, "yyyy-MM-dd HH:mm:ss")}
      </TableCell>
      <TableCell>
        <Badge variant={BOOKMAKER_BADGE[row.bookmaker]} className="font-normal">
          {BOOKMAKER_LABEL[row.bookmaker]}
        </Badge>
      </TableCell>
      {showMatch ? (
        <TableCell className="max-w-[260px] truncate">
          {row.match_id ? (
            <Link
              to="/matches/$id"
              params={{ id: row.match_id }}
              className="hover:underline"
              title={matchLabel}
            >
              {matchLabel}
            </Link>
          ) : (
            <span title={matchLabel}>{matchLabel}</span>
          )}
        </TableCell>
      ) : null}
      <TableCell>
        <div className="flex flex-col">
          <span className="text-sm">{marketHuman}</span>
          {params ? (
            <span className="font-mono text-xs text-muted-foreground">{params}</span>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="font-mono text-xs">{row.selection}</TableCell>
      <TableCell className="text-right font-mono">{fmtOdds(row.payout)}</TableCell>
    </TableRow>
  );
}

function matchLabelFromTeams(row: OddsSnapshot): string {
  if (row.home_team && row.away_team) return `${row.home_team} vs ${row.away_team}`;
  return row.bookmaker_event_id ?? "—";
}
