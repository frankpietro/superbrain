import * as React from "react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MatchCard } from "@/components/match-card";
import type { Match } from "@/lib/types";
import * as apiModule from "@/lib/api";

function Harness({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      }),
  );
  const [router] = React.useState(() => {
    const root = createRootRoute({ component: () => <Outlet /> });
    const index = createRoute({
      getParentRoute: () => root,
      path: "/",
      component: () => <Slot />,
    });
    const placeholder = createRoute({
      getParentRoute: () => root,
      path: "/matches/$id",
      component: () => <div>match</div>,
    });
    const tree = root.addChildren([index, placeholder]);
    return createRouter({
      routeTree: tree,
      history: createMemoryHistory({ initialEntries: ["/"] }),
    });
  });
  return (
    <QueryClientProvider client={client}>
      <SlotContext.Provider value={children}>
        <RouterProvider router={router} />
      </SlotContext.Provider>
    </QueryClientProvider>
  );
}

const SlotContext = React.createContext<React.ReactNode>(null);
function Slot() {
  return <>{React.useContext(SlotContext)}</>;
}

function renderWithProviders(ui: React.ReactNode) {
  return render(<Harness>{ui}</Harness>);
}

const pastMatch: Match = {
  match_id: "m-past",
  league: "serie_a",
  season: "2024-25",
  match_date: "2024-09-01",
  home_team: "Roma",
  away_team: "Lazio",
  home_goals: 2,
  away_goals: 1,
  home_xg: 1.73,
  away_xg: 0.91,
  source: "fixture",
};

const futureMatch: Match = {
  match_id: "m-future",
  league: "premier_league",
  season: "2024-25",
  match_date: "2030-05-04",
  home_team: "Arsenal",
  away_team: "Chelsea",
  source: "fixture",
};

describe("MatchCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders FT score and xG for a past match", async () => {
    renderWithProviders(
      <MatchCard match={pastMatch} variant="past" expanded={false} onToggle={() => {}} />,
    );
    expect(await screen.findByText("Roma")).toBeInTheDocument();
    expect(screen.getByText("Lazio")).toBeInTheDocument();
    expect(screen.getByText("2 – 1")).toBeInTheDocument();
    expect(screen.getByText(/xG 1\.73 – 0\.91/)).toBeInTheDocument();
  });

  it("omits xG line when both sides are null", async () => {
    const m = { ...pastMatch, home_xg: null, away_xg: null };
    renderWithProviders(
      <MatchCard match={m} variant="past" expanded={false} onToggle={() => {}} />,
    );
    expect(await screen.findByText("Roma")).toBeInTheDocument();
    expect(screen.queryByText(/^xG /)).not.toBeInTheDocument();
  });

  it("renders 'vs' for a future match without showing odds until expanded", async () => {
    renderWithProviders(
      <MatchCard match={futureMatch} variant="future" expanded={false} onToggle={() => {}} />,
    );
    expect(await screen.findByText("Arsenal")).toBeInTheDocument();
    expect(screen.getByText("vs")).toBeInTheDocument();
    expect(screen.queryByText("Bookmaker")).not.toBeInTheDocument();
  });

  it("fetches 1X2 odds only when the future card is expanded", async () => {
    const listOdds = vi.spyOn(apiModule.api, "listOdds").mockResolvedValue({
      items: [
        {
          bookmaker: "sisal",
          market: "match_1x2",
          selection: "1",
          payout: 1.72,
          captured_at: "2026-04-20T12:00:00Z",
          market_params: {},
        },
        {
          bookmaker: "sisal",
          market: "match_1x2",
          selection: "X",
          payout: 3.6,
          captured_at: "2026-04-20T12:00:00Z",
          market_params: {},
        },
        {
          bookmaker: "sisal",
          market: "match_1x2",
          selection: "2",
          payout: 4.2,
          captured_at: "2026-04-20T12:00:00Z",
          market_params: {},
        },
      ],
    });
    const user = userEvent.setup();
    function Controlled() {
      const [open, setOpen] = React.useState(false);
      return (
        <MatchCard
          match={futureMatch}
          variant="future"
          expanded={open}
          onToggle={() => setOpen((o) => !o)}
        />
      );
    }
    renderWithProviders(<Controlled />);
    expect(listOdds).not.toHaveBeenCalled();
    const button = await screen.findByRole("button", { name: /Arsenal/i });
    await user.click(button);
    await waitFor(() =>
      expect(listOdds).toHaveBeenCalledWith({
        match_id: "m-future",
        market: "match_1x2",
      }),
    );
    expect(await screen.findByText("Sisal")).toBeInTheDocument();
    expect(await screen.findByText("1.72")).toBeInTheDocument();
  });

  it("fires onToggle when the header is clicked", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    renderWithProviders(
      <MatchCard match={pastMatch} variant="past" expanded={false} onToggle={onToggle} />,
    );
    const button = await screen.findByRole("button", { name: /Roma/i });
    await user.click(button);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
