import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { MatchesTable } from "@/components/matches-table";
import type { Match } from "@/lib/types";

function renderWithRouter(ui: React.ReactNode) {
  const root = createRootRoute({ component: () => <>{ui}</> });
  const placeholder = createRoute({
    getParentRoute: () => root,
    path: "/matches/$id",
    component: () => <div>match</div>,
  });
  const index = createRoute({ getParentRoute: () => root, path: "/", component: () => <>{ui}</> });
  const tree = root.addChildren([index, placeholder]);
  const router = createRouter({
    routeTree: tree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  return render(<RouterProvider router={router} />);
}

const sampleMatches: Match[] = [
  {
    match_id: "m-1",
    league: "serie_a",
    season: "2024-25",
    match_date: "2026-04-21",
    home_team: "Juventus",
    away_team: "Inter",
    source: "fixture",
  },
  {
    match_id: "m-2",
    league: "premier_league",
    season: "2024-25",
    match_date: "2026-04-21",
    home_team: "Arsenal",
    away_team: "Chelsea",
    source: "fixture",
  },
];

describe("MatchesTable", () => {
  it("renders rows for every match", async () => {
    renderWithRouter(<MatchesTable matches={sampleMatches} showKickoff={false} />);
    expect(await screen.findByText("Juventus")).toBeInTheDocument();
    expect(await screen.findByText("Chelsea")).toBeInTheDocument();
    expect(screen.getByText("Serie A")).toBeInTheDocument();
    expect(screen.getByText("Premier League")).toBeInTheDocument();
  });

  it("renders an empty state when there are no matches", async () => {
    renderWithRouter(<MatchesTable matches={[]} emptyMessage="No fixtures today." />);
    expect(await screen.findByText("No fixtures today.")).toBeInTheDocument();
  });
});
