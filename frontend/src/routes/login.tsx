import * as React from "react";
import { useNavigate, useSearch, useRouter } from "@tanstack/react-router";
import { Brain, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorBanner } from "@/components/error-banner";

export function LoginPage() {
  const router = useRouter();
  const navigate = useNavigate();
  const setToken = useAuth((s) => s.setToken);
  const search = useSearch({ from: "/login" });

  const [token, setLocalToken] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.health();
      setToken(token.trim());
      try {
        await api.verifyToken();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          useAuth.getState().clear();
          setError("That token is not valid. Check with the owner who minted it.");
          return;
        }
      }
      const to = search.redirect ?? "/";
      await router.invalidate();
      navigate({ to });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `Cannot reach backend (${err.status || "network"}): ${err.message}`
          : err instanceof Error
            ? err.message
            : "Unexpected error",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background via-background to-accent/30 p-6">
      <Card className="w-full max-w-md shadow-lg animate-fade-in">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Brain className="h-5 w-5" aria-hidden="true" />
          </div>
          <CardTitle className="text-xl">Superbrain</CardTitle>
          <CardDescription>
            Enter your bearer token. Tokens are minted by the owner and stored only in this browser.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="token" className="text-sm font-medium">
                Bearer token
              </label>
              <Input
                id="token"
                type="password"
                autoComplete="off"
                placeholder="sb_…"
                value={token}
                onChange={(e) => setLocalToken(e.target.value)}
                required
                aria-label="Bearer token"
              />
            </div>
            {error ? <ErrorBanner title="Sign-in failed" description={error} /> : null}
            <Button type="submit" className="w-full" disabled={loading || !token.trim()}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              Continue
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              Tokens live in <code>localStorage</code> as <code>superbrain.auth</code>.
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
