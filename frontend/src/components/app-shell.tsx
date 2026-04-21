import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  BarChart3,
  Brain,
  CircleUserRound,
  Clock,
  GanttChart,
  LayoutDashboard,
  ListOrdered,
  Receipt,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { useAuth } from "@/stores/auth";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface NavLink {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  children?: NavLink[];
}

const NAV: NavLink[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/matches", label: "Matches", icon: ListOrdered },
  { to: "/scrapers", label: "Scrapers", icon: Activity },
  {
    to: "/bets",
    label: "Bets",
    icon: Receipt,
    children: [
      { to: "/bets", label: "Recent", icon: Clock },
      { to: "/bets/value", label: "Value", icon: Sparkles },
    ],
  },
  { to: "/backtest", label: "Backtest", icon: GanttChart },
  { to: "/trends", label: "Trends", icon: TrendingUp },
];

function isActive(to: string, pathname: string): boolean {
  if (to === "/") return pathname === "/";
  if (to === "/bets") return pathname === "/bets";
  return pathname === to || pathname.startsWith(`${to}/`);
}

export function AppShell() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const clearToken = useAuth((s) => s.clear);

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 flex-none self-start overflow-y-auto border-r border-border bg-card/50 p-4 md:flex md:flex-col">
        <div className="mb-6 flex items-center gap-2 px-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Brain className="h-4 w-4" aria-hidden="true" />
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">Superbrain</div>
            <div className="text-xs text-muted-foreground">value-bet console</div>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((item) => {
            const Icon = item.icon;
            const hasChildren = (item.children?.length ?? 0) > 0;
            if (hasChildren) {
              const sectionActive =
                pathname === item.to || pathname.startsWith(`${item.to}/`);
              return (
                <div key={item.to} className="flex flex-col gap-0.5">
                  <div
                    className={cn(
                      "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                      sectionActive
                        ? "text-foreground"
                        : "text-muted-foreground",
                    )}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    {item.label}
                  </div>
                  <div className="ml-5 flex flex-col gap-0.5 border-l border-border pl-2">
                    {(item.children ?? []).map((child) => {
                      const ChildIcon = child.icon;
                      const active = isActive(child.to, pathname);
                      return (
                        <Link
                          key={child.to}
                          to={child.to}
                          className={cn(
                            "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                            active
                              ? "bg-accent text-accent-foreground"
                              : "text-muted-foreground hover:bg-muted hover:text-foreground",
                          )}
                          aria-current={active ? "page" : undefined}
                        >
                          <ChildIcon className="h-3.5 w-3.5" aria-hidden="true" />
                          {child.label}
                        </Link>
                      );
                    })}
                  </div>
                </div>
              );
            }
            const active = isActive(item.to, pathname);
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                aria-current={active ? "page" : undefined}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto space-y-1">
          <Link
            to="/settings"
            className={cn(
              "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
              pathname.startsWith("/settings")
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <CircleUserRound className="h-4 w-4" aria-hidden="true" />
            Settings
          </Link>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-muted-foreground"
            onClick={clearToken}
          >
            Sign out
          </Button>
        </div>
      </aside>
      <main className="flex-1 overflow-x-hidden">
        <header className="flex h-14 items-center justify-between border-b border-border px-6 md:hidden">
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-primary" aria-hidden="true" />
            <span className="text-sm font-semibold">Superbrain</span>
          </div>
          <Button variant="ghost" size="sm" onClick={clearToken}>
            Sign out
          </Button>
        </header>
        <div className="mx-auto max-w-[1400px] p-6 md:p-8">
          <div className="mb-6 flex items-center gap-2 text-xs text-muted-foreground md:hidden">
            <BarChart3 className="h-3 w-3" />
            Mobile nav: swipe nav via URL.
          </div>
          <div className="animate-fade-in">
            <Outlet />
          </div>
        </div>
      </main>
    </div>
  );
}
