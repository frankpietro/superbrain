import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";
import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/stores/auth";
import { LoginPage } from "@/routes/login";
import { DashboardPage } from "@/routes/dashboard";
import { MatchesPage } from "@/routes/matches";
import { MatchDetailPage } from "@/routes/match-detail";
import { ScrapersPage } from "@/routes/scrapers";
import { ValueBetsPage } from "@/routes/value-bets";
import { BacktestPage } from "@/routes/backtest";
import { SettingsPage } from "@/routes/settings";

function requireAuth(path: string): void {
  if (!useAuth.getState().token) {
    throw redirect({
      to: "/login",
      search: { redirect: path },
    });
  }
}

const rootRoute = createRootRoute({
  component: () => <Outlet />,
});

interface LoginSearch {
  redirect?: string;
}

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): LoginSearch =>
    typeof search.redirect === "string" ? { redirect: search.redirect } : {},
  component: LoginPage,
});

const shellRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "_shell",
  beforeLoad: ({ location }) => {
    requireAuth(location.pathname);
  },
  component: AppShell,
});

const dashboardRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/",
  component: DashboardPage,
});

const matchesRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/matches",
  component: MatchesPage,
});

const matchDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/matches/$id",
  component: MatchDetailPage,
});

const scrapersRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/scrapers",
  component: ScrapersPage,
});

const valueBetsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/bets/value",
  component: ValueBetsPage,
});

const backtestRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/backtest",
  component: BacktestPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/settings",
  component: SettingsPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  shellRoute.addChildren([
    dashboardRoute,
    matchesRoute,
    matchDetailRoute,
    scrapersRoute,
    valueBetsRoute,
    backtestRoute,
    settingsRoute,
  ]),
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
});
