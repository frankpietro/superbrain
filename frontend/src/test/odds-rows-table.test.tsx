import * as React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { OddsRowsTable } from "@/components/odds-rows";
import type { MarketInfo } from "@/lib/markets";
import type { OddsSnapshot } from "@/lib/types";

function renderWithRouter(ui: React.ReactNode) {
  const root = createRootRoute({ component: () => <>{ui}</> });
  const placeholder = createRoute({
    getParentRoute: () => root,
    path: "/matches/$id",
    component: () => <div>match</div>,
  });
  const index = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: () => <>{ui}</>,
  });
  const tree = root.addChildren([index, placeholder]);
  const router = createRouter({
    routeTree: tree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  return render(<RouterProvider router={router} />);
}

const REGISTRY: MarketInfo[] = [
  { code: "match_1x2", human_name: "Match result (1X2)", category: "match_result", selections: ["1", "X", "2"] },
  { code: "goals_over_under", human_name: "Goals — total over/under", category: "goals", selections: ["OVER", "UNDER"] },
];
const byCode = new Map(REGISTRY.map((m) => [m.code, m]));

const rows: OddsSnapshot[] = [
  {
    bookmaker: "sisal",
    match_id: "m-1",
    match_label: "Juventus vs Inter",
    home_team: "Juventus",
    away_team: "Inter",
    market: "match_1x2",
    market_params: {},
    selection: "1",
    payout: 2.35,
    captured_at: "2026-04-21T12:30:00Z",
  },
  {
    bookmaker: "goldbet",
    market: "goals_over_under",
    market_params: { threshold: 2.5 },
    selection: "OVER",
    payout: 1.88,
    captured_at: "2026-04-21T12:40:00Z",
  },
];

describe("OddsRowsTable", () => {
  it("renders one row per odds snapshot with market + selection + odds", async () => {
    renderWithRouter(<OddsRowsTable rows={rows} markets={byCode} />);
    expect(await screen.findByText("Match result (1X2)")).toBeInTheDocument();
    expect(screen.getByText("Goals — total over/under")).toBeInTheDocument();
    expect(screen.getByText("threshold=2.5")).toBeInTheDocument();
    expect(screen.getByText("Juventus vs Inter")).toBeInTheDocument();
    expect(screen.getByText("2.35")).toBeInTheDocument();
    expect(screen.getByText("1.88")).toBeInTheDocument();
  });

  it("falls back to the home/away pair when match_label is missing and hides the match column when asked", () => {
    renderWithRouter(<OddsRowsTable rows={rows} markets={byCode} showMatch={false} />);
    expect(screen.queryByText("Juventus vs Inter")).toBeNull();
    expect(screen.queryByRole("columnheader", { name: /match/i })).toBeNull();
  });

  it("renders the empty-state message", async () => {
    renderWithRouter(<OddsRowsTable rows={[]} markets={byCode} emptyMessage="Nothing yet." />);
    expect(await screen.findByText("Nothing yet.")).toBeInTheDocument();
  });
});
