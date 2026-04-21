import { Moon, Sun, SunMoon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/page-header";
import { usePreferences, type Theme } from "@/stores/preferences";

export function SettingsPage() {
  const theme = usePreferences((s) => s.theme);
  const setTheme = usePreferences((s) => s.setTheme);
  const timezone = usePreferences((s) => s.timezone);
  const setTimezone = usePreferences((s) => s.setTimezone);

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Theme and display preferences." />

      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>Theme follows the system by default.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-3 gap-2">
            {(["light", "dark", "system"] as Theme[]).map((t) => {
              const Icon = t === "light" ? Sun : t === "dark" ? Moon : SunMoon;
              const active = theme === t;
              return (
                <Button
                  key={t}
                  variant={active ? "default" : "outline"}
                  onClick={() => setTheme(t)}
                  className="justify-center capitalize"
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  {t}
                </Button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Regional</CardTitle>
          <CardDescription>Kickoff times are rendered in your local timezone.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor="tz" className="text-sm font-medium">
              Timezone
            </label>
            <Select value={timezone} onValueChange={setTimezone}>
              <SelectTrigger id="tz" aria-label="Timezone">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {["UTC", "Europe/Rome", "Europe/London", "Europe/Madrid", "Europe/Berlin"].map(
                  (tz) => (
                    <SelectItem key={tz} value={tz}>
                      {tz}
                    </SelectItem>
                  ),
                )}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="api-base" className="text-sm font-medium">
              API base URL
            </label>
            <Input
              id="api-base"
              value={import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8100"}
              readOnly
              aria-readonly
            />
            <p className="text-xs text-muted-foreground">
              Configured via <code>VITE_API_BASE_URL</code> at build time.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
