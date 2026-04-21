import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BetsRecentPage } from "@/routes/bets-recent";
import { api } from "@/lib/api";
import type { OddsSnapshot } from "@/lib/types";

function renderPage() {
  const root = createRootRoute({ component: () => <BetsRecentPage /> });
  const matchRoute = createRoute({
    getParentRoute: () => root,
    path: "/matches/$id",
    component: () => <div>match</div>,
  });
  const index = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: () => <BetsRecentPage />,
  });
  const tree = root.addChildren([index, matchRoute]);
  const router = createRouter({
    routeTree: tree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={0}>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const ODDS_ROWS: OddsSnapshot[] = [
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
    captured_at: "2026-04-21T12:40:00Z",
  },
  {
    bookmaker: "goldbet",
    match_id: "m-1",
    match_label: "Juventus vs Inter",
    home_team: "Juventus",
    away_team: "Inter",
    market: "goals_over_under",
    market_params: { threshold: 2.5 },
    selection: "OVER",
    payout: 1.88,
    captured_at: "2026-04-21T12:30:00Z",
  },
  {
    bookmaker: "eurobet",
    market: "corner_total",
    market_params: { threshold: 9.5 },
    selection: "OVER",
    payout: 1.95,
    captured_at: "2026-04-21T12:20:00Z",
  },
];

const MARKET_LIST = {
  items: [
    { code: "match_1x2", human_name: "Match result (1X2)", category: "match_result", selections: ["1", "X", "2"] },
    { code: "goals_over_under", human_name: "Goals — total over/under", category: "goals", selections: ["OVER", "UNDER"] },
    { code: "corner_total", human_name: "Corners — total over/under", category: "corners", selections: ["OVER", "UNDER"] },
  ],
};

describe("BetsRecentPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "listOdds").mockResolvedValue({
      items: ODDS_ROWS,
      count: ODDS_ROWS.length,
      next_cursor: null,
    });
    vi.spyOn(api, "marketList").mockResolvedValue(MARKET_LIST);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders every odds row returned by the API", async () => {
    renderPage();
    expect(await screen.findByText("Match result (1X2)")).toBeInTheDocument();
    expect(screen.getByText("Goals — total over/under")).toBeInTheDocument();
    expect(screen.getByText("Corners — total over/under")).toBeInTheDocument();
    expect(screen.getByText("2.35")).toBeInTheDocument();
    expect(screen.getByText("1.88")).toBeInTheDocument();
    expect(screen.getByText("1.95")).toBeInTheDocument();
  });

  it("narrows rows client-side when two bookmakers are selected", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Match result (1X2)");
    await user.click(screen.getByRole("button", { name: /all bookmakers/i }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Sisal" }));
    await user.click(screen.getByRole("button", { name: /sisal/i }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Goldbet" }));

    const table = screen.getByRole("table");
    const tbody = table.querySelector("tbody")!;
    expect(within(tbody).queryByText("1.95")).toBeNull();
    expect(within(tbody).getByText("2.35")).toBeInTheDocument();
    expect(within(tbody).getByText("1.88")).toBeInTheDocument();
  });
});
