import * as React from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2, Play } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { LEAGUE_LABEL, leagueEnum, marketEnum, MARKET_LABEL } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/page-header";
import { toast } from "@/components/ui/toaster";

export function BacktestPage() {
  const [league, setLeague] = React.useState<string>("serie_a");
  const [season, setSeason] = React.useState<string>("2024-25");
  const [market, setMarket] = React.useState<string>("match_1x2");
  const [threshold, setThreshold] = React.useState<string>("2.5");
  const [edgeCutoff, setEdgeCutoff] = React.useState<string>("0.03");

  const runMutation = useMutation({
    mutationFn: () =>
      api.runBacktest({
        league,
        season,
        market,
        threshold: Number.isFinite(parseFloat(threshold)) ? parseFloat(threshold) : undefined,
        edge_cutoff: Number.isFinite(parseFloat(edgeCutoff)) ? parseFloat(edgeCutoff) : undefined,
      }),
    onSuccess: (data) => {
      toast({
        variant: "success",
        title: "Backtest queued",
        description: data.job_id ? `job_id ${data.job_id}` : "accepted",
      });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 501) {
        toast({
          variant: "default",
          title: "Backtest engine not yet wired",
          description:
            "The endpoint exists but returns 501 until phase 4b lands. See docs/knowledge.md → Deferred.",
        });
        return;
      }
      toast({
        variant: "destructive",
        title: "Backtest failed",
        description: err instanceof Error ? err.message : String(err),
      });
    },
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Backtest"
        description="Sliding-window ROI over a league, season, market. Engine ships in phase 4b — the form is wired so only the compute layer is missing."
      />
      <Card>
        <CardHeader>
          <CardTitle>Run a backtest</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="grid grid-cols-1 gap-4 md:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              runMutation.mutate();
            }}
          >
            <div className="space-y-1.5">
              <label htmlFor="bt-league" className="text-sm font-medium">
                League
              </label>
              <Select value={league} onValueChange={setLeague}>
                <SelectTrigger id="bt-league" aria-label="League">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {leagueEnum.options.map((l) => (
                    <SelectItem key={l} value={l}>
                      {LEAGUE_LABEL[l]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="bt-season" className="text-sm font-medium">
                Season
              </label>
              <Input
                id="bt-season"
                value={season}
                onChange={(e) => setSeason(e.target.value)}
                placeholder="2024-25"
                pattern="\d{4}-\d{2}"
                required
              />
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <label htmlFor="bt-market" className="text-sm font-medium">
                Market
              </label>
              <Select value={market} onValueChange={setMarket}>
                <SelectTrigger id="bt-market" aria-label="Market">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {marketEnum.options.map((m) => (
                    <SelectItem key={m} value={m}>
                      {MARKET_LABEL[m] ?? m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="bt-threshold" className="text-sm font-medium">
                Threshold (line)
              </label>
              <Input
                id="bt-threshold"
                type="number"
                step="0.5"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="bt-edge" className="text-sm font-medium">
                Edge cutoff
              </label>
              <Input
                id="bt-edge"
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={edgeCutoff}
                onChange={(e) => setEdgeCutoff(e.target.value)}
              />
            </div>
            <div className="md:col-span-2">
              <Button type="submit" disabled={runMutation.isPending}>
                {runMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Play className="h-4 w-4" aria-hidden="true" />
                )}
                Run
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
