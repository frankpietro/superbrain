import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { DataPage } from "@/routes/data";
import { api } from "@/lib/api";
import type { DataOverviewResponse } from "@/lib/types";

// Plotly pulls in large canvas deps that don't play well with jsdom — swap
// the Chart for a lightweight stand-in that records its labels/values.
vi.mock("@/components/plot", () => ({
  Chart: ({ ariaLabel }: { ariaLabel?: string }) => (
    <div data-testid="chart" aria-label={ariaLabel} />
  ),
}));

function renderPage() {
  const root = createRootRoute({ component: () => <DataPage /> });
  const index = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: () => <DataPage />,
  });
  const tree = root.addChildren([index]);
  const router = createRouter({
    routeTree: tree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const OVERVIEW: DataOverviewResponse = {
  generated_at: "2026-04-21T22:30:00Z",
  lake_root: "data/lake",
  tables: [
    {
      name: "matches",
      root: "data/lake/matches",
      partition_keys: ["league", "season"],
      exists: true,
      total_rows: 760,
      columns: [
        { name: "match_id", dtype: "String" },
        { name: "match_date", dtype: "Date" },
      ],
      partitions: [
        { values: { league: "serie_a", season: "2023-24" }, rows: 380 },
        { values: { league: "premier_league", season: "2023-24" }, rows: 380 },
      ],
      samples: [
        { match_id: "abc", match_date: "2023-09-01" },
      ],
    },
    {
      name: "team_match_stats",
      root: "data/lake/team_match_stats",
      partition_keys: ["league", "season"],
      exists: true,
      total_rows: 0,
      columns: [],
      partitions: [],
      samples: [],
    },
    {
      name: "odds",
      root: "data/lake/odds",
      partition_keys: ["bookmaker", "market", "season"],
      exists: true,
      total_rows: 123,
      columns: [{ name: "payout", dtype: "Float64" }],
      partitions: [
        { values: { bookmaker: "sisal", market: "match_1x2", season: "2025-26" }, rows: 123 },
      ],
      samples: [{ payout: "2.15" }],
    },
    {
      name: "team_elo",
      root: "data/lake/team_elo",
      partition_keys: ["year_month"],
      exists: false,
      total_rows: 0,
      columns: [],
      partitions: [],
      samples: [],
    },
    {
      name: "scrape_runs",
      root: "data/lake/scrape_runs",
      partition_keys: ["bookmaker", "year_month"],
      exists: true,
      total_rows: 0,
      columns: [],
      partitions: [],
      samples: [],
    },
    {
      name: "simulation_runs",
      root: "data/lake/simulation_runs",
      partition_keys: ["created_date"],
      exists: true,
      total_rows: 0,
      columns: [],
      partitions: [],
      samples: [],
    },
  ],
};

describe("DataPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "dataOverview").mockResolvedValue(OVERVIEW);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a summary card, breakdown charts, partition table and sample rows", async () => {
    renderPage();

    expect(await screen.findByText("Data")).toBeInTheDocument();
    expect(await screen.findByText("data/lake")).toBeInTheDocument();
    expect(await screen.findByText(/Grand total/i)).toBeInTheDocument();
    expect(screen.getByText("883 rows")).toBeInTheDocument();

    expect(await screen.findByText("Rows by league")).toBeInTheDocument();
    expect(screen.getByText("Rows by year")).toBeInTheDocument();

    expect(screen.getByText("serie_a")).toBeInTheDocument();
    expect(screen.getByText("premier_league")).toBeInTheDocument();

    expect(screen.getAllByText("match_id").length).toBeGreaterThan(0);
    expect(screen.getByText("abc")).toBeInTheDocument();
  });
});
