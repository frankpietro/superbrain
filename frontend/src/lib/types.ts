// Types hand-written from the phase-1/phase-3 pydantic models
// (`superbrain.core.models` and `superbrain.core.markets`).
// TODO(phase-7): replace with `openapi-typescript` output once the
// Phase-6 backend exposes a stable `/openapi.json`.

import { z } from "zod";

export const leagueEnum = z.enum([
  "serie_a",
  "premier_league",
  "la_liga",
  "bundesliga",
  "ligue_1",
]);
export type League = z.infer<typeof leagueEnum>;

export const LEAGUE_LABEL: Record<League, string> = {
  serie_a: "Serie A",
  premier_league: "Premier League",
  la_liga: "La Liga",
  bundesliga: "Bundesliga",
  ligue_1: "Ligue 1",
};

export const bookmakerEnum = z.enum(["sisal", "goldbet", "eurobet"]);
export type Bookmaker = z.infer<typeof bookmakerEnum>;

export const BOOKMAKER_LABEL: Record<Bookmaker, string> = {
  sisal: "Sisal",
  goldbet: "Goldbet",
  eurobet: "Eurobet",
};

export const marketEnum = z.enum([
  "corner_total",
  "corner_team",
  "corner_1x2",
  "corner_combo",
  "corner_first_to",
  "corner_handicap",
  "goals_over_under",
  "goals_both_teams",
  "goals_team",
  "goals_exact",
  "cards_total",
  "cards_team",
  "match_1x2",
  "match_double_chance",
  "multigol",
  "multigol_team",
  "score_exact",
  "score_ht_ft",
  "shots_total",
  "shots_on_target_total",
  "combo_1x2_over_under",
  "combo_btts_over_union",
  "combo_btts_over_under",
  "halves_over_under",
]);
export type Market = z.infer<typeof marketEnum>;

export const MARKET_LABEL: Record<string, string> = {
  corner_total: "Corners — total O/U",
  corner_team: "Corners — per team",
  corner_1x2: "Corners — 1X2",
  corner_combo: "Corners — combo",
  corner_first_to: "Corners — first to N",
  corner_handicap: "Corners — handicap",
  goals_over_under: "Goals — over/under",
  goals_both_teams: "Both teams to score",
  goals_team: "Goals — per team",
  goals_exact: "Goals — exact",
  cards_total: "Cards — total O/U",
  cards_team: "Cards — per team",
  match_1x2: "Match — 1X2",
  match_double_chance: "Match — double chance",
  multigol: "Multigoal",
  multigol_team: "Multigoal — per team",
  score_exact: "Exact score",
  score_ht_ft: "HT/FT",
  shots_total: "Shots — total O/U",
  shots_on_target_total: "Shots on target — O/U",
  combo_1x2_over_under: "1X2 + O/U combo",
  combo_btts_over_under: "BTTS + O/U combo",
  halves_over_under: "Halves — O/U",
};

export const matchSchema = z.object({
  match_id: z.string(),
  league: leagueEnum,
  season: z.string(),
  match_date: z.string(),
  home_team: z.string(),
  away_team: z.string(),
  home_goals: z.number().int().nullable().optional(),
  away_goals: z.number().int().nullable().optional(),
  home_xg: z.number().nullable().optional(),
  away_xg: z.number().nullable().optional(),
  kickoff_at: z.string().nullable().optional(),
  source: z.string().optional(),
});
export type Match = z.infer<typeof matchSchema>;

export const matchesResponse = z.object({
  items: z.array(matchSchema),
  total: z.number().int().nonnegative().optional(),
});
export type MatchesResponse = z.infer<typeof matchesResponse>;

export const teamMatchStatsSchema = z.object({
  team: z.string(),
  is_home: z.boolean(),
  goals: z.number().int().nullable().optional(),
  goals_conceded: z.number().int().nullable().optional(),
  ht_goals: z.number().int().nullable().optional(),
  ht_goals_conceded: z.number().int().nullable().optional(),
  shots: z.number().int().nullable().optional(),
  shots_on_target: z.number().int().nullable().optional(),
  shots_off_target: z.number().int().nullable().optional(),
  shots_in_box: z.number().int().nullable().optional(),
  corners: z.number().int().nullable().optional(),
  fouls: z.number().int().nullable().optional(),
  yellow_cards: z.number().int().nullable().optional(),
  red_cards: z.number().int().nullable().optional(),
  offsides: z.number().int().nullable().optional(),
  possession_pct: z.number().nullable().optional(),
  passes: z.number().int().nullable().optional(),
  pass_accuracy_pct: z.number().nullable().optional(),
  tackles: z.number().int().nullable().optional(),
  interceptions: z.number().int().nullable().optional(),
  aerials_won: z.number().int().nullable().optional(),
  saves: z.number().int().nullable().optional(),
  big_chances: z.number().int().nullable().optional(),
  big_chances_missed: z.number().int().nullable().optional(),
  xg: z.number().nullable().optional(),
  xga: z.number().nullable().optional(),
  ppda: z.number().nullable().optional(),
  source: z.string().nullable().optional(),
});
export type TeamMatchStatsRow = z.infer<typeof teamMatchStatsSchema>;

export const matchStatsResponse = z.object({
  match_id: z.string(),
  home: teamMatchStatsSchema.nullable(),
  away: teamMatchStatsSchema.nullable(),
});
export type MatchStats = z.infer<typeof matchStatsResponse>;

export const oddsSnapshotSchema = z.object({
  bookmaker: bookmakerEnum,
  bookmaker_event_id: z.string().optional(),
  match_id: z.string().nullable().optional(),
  match_label: z.string().optional(),
  match_date: z.string().optional(),
  season: z.string().optional(),
  league: leagueEnum.nullable().optional(),
  home_team: z.string().optional(),
  away_team: z.string().optional(),
  market: z.string(),
  market_params: z.record(z.unknown()),
  selection: z.string(),
  payout: z.number().positive(),
  captured_at: z.string(),
  source: z.string().optional(),
  run_id: z.string().optional(),
});
export type OddsSnapshot = z.infer<typeof oddsSnapshotSchema>;

export const oddsResponse = z.object({
  items: z.array(oddsSnapshotSchema),
  count: z.number().int().nonnegative().optional(),
  next_cursor: z.string().nullable().optional(),
});
export type OddsResponse = z.infer<typeof oddsResponse>;

export const scrapeRunSchema = z.object({
  run_id: z.string(),
  bookmaker: bookmakerEnum.nullable(),
  scraper: z.string(),
  started_at: z.string(),
  finished_at: z.string().nullable(),
  status: z.string(),
  rows_written: z.number().int(),
  rows_rejected: z.number().int(),
  error_message: z.string().nullable(),
  host: z.string().nullable().optional(),
});
export type ScrapeRun = z.infer<typeof scrapeRunSchema>;

export const scrapeRunsResponse = z.object({
  items: z.array(scrapeRunSchema),
});
export type ScrapeRunsResponse = z.infer<typeof scrapeRunsResponse>;

export const scraperStatusSchema = z.object({
  bookmaker: bookmakerEnum,
  last_run: scrapeRunSchema.nullable(),
  healthy: z.boolean(),
  unmapped_markets_top: z.array(z.object({ name: z.string(), count: z.number().int() })),
  history: z.array(
    z.object({
      run_id: z.string(),
      started_at: z.string(),
      rows_written: z.number().int(),
      status: z.string(),
    }),
  ),
});
export type ScraperStatus = z.infer<typeof scraperStatusSchema>;

export const scraperStatusResponse = z.object({
  items: z.array(scraperStatusSchema),
});
export type ScraperStatusResponse = z.infer<typeof scraperStatusResponse>;

export const valueBetSchema = z.object({
  match_id: z.string(),
  match_label: z.string(),
  league: leagueEnum,
  market: z.string(),
  selection: z.string(),
  market_params: z.record(z.unknown()).optional(),
  bookmaker: bookmakerEnum,
  decimal_odds: z.number().positive(),
  book_prob: z.number().min(0).max(1),
  model_prob: z.number().min(0).max(1),
  edge: z.number(),
  sample_size: z.number().int().nonnegative().optional(),
  captured_at: z.string().optional(),
  kickoff_at: z.string().nullable().optional(),
});
export type ValueBet = z.infer<typeof valueBetSchema>;

export const valueBetsResponse = z.object({
  items: z.array(valueBetSchema),
  count: z.number().int().nonnegative().optional(),
  computed_at: z.string().optional(),
  note: z.string().nullable().optional(),
});
export type ValueBetsResponse = z.infer<typeof valueBetsResponse>;

export const marketListResponse = z.object({
  items: z.array(
    z.object({
      code: z.string(),
      human_name: z.string(),
      category: z.string(),
      selections: z.array(z.string()),
    }),
  ),
});

export const healthResponse = z.object({
  status: z.string(),
  version: z.string().optional(),
});

export const trendsVariabilityRowSchema = z.object({
  key: z.string(),
  label: z.string(),
  series_count: z.number().int().nonnegative(),
  observation_count: z.number().int().nonnegative(),
  avg_cv_pct: z.number(),
  max_cv_pct: z.number(),
  avg_range_pct: z.number(),
  avg_payout: z.number(),
  leagues: z.array(z.string()),
});
export type TrendsVariabilityRow = z.infer<typeof trendsVariabilityRowSchema>;

export const trendsVariabilityResponse = z.object({
  group_by: z.string(),
  since_hours: z.number().int(),
  min_points: z.number().int(),
  total_series: z.number().int(),
  items: z.array(trendsVariabilityRowSchema),
});
export type TrendsVariabilityResponse = z.infer<typeof trendsVariabilityResponse>;

export const trendsTtkBucketSchema = z.object({
  hours_min: z.number(),
  hours_max: z.number(),
  n_transitions: z.number().int().nonnegative(),
  n_series: z.number().int().nonnegative(),
  mean_abs_delta_pct: z.number(),
  median_abs_delta_pct: z.number(),
  p90_abs_delta_pct: z.number(),
  prob_any_change: z.number(),
});
export type TrendsTtkBucket = z.infer<typeof trendsTtkBucketSchema>;

export const trendsTimeToKickoffResponse = z.object({
  bucket_hours: z.number().int(),
  total_transitions: z.number().int().nonnegative(),
  buckets: z.array(trendsTtkBucketSchema),
});
export type TrendsTimeToKickoffResponse = z.infer<typeof trendsTimeToKickoffResponse>;

export const backtestRunRequestSchema = z.object({
  league: z.string(),
  season: z.string(),
  market: z.string().nullable().optional(),
  edge_cutoff: z.number(),
  threshold: z.number().nullable().optional(),
  stake: z.number(),
  min_history_matches: z.number().int(),
  n_clusters: z.number().int().nullable().optional(),
});

export const backtestBetRowSchema = z.object({
  match_id: z.string(),
  match_date: z.string(),
  home_team: z.string(),
  away_team: z.string(),
  market: z.string(),
  selection: z.string(),
  bookmaker: z.string(),
  decimal_odds: z.number(),
  model_probability: z.number(),
  edge: z.number(),
  stake: z.number(),
  won: z.boolean().nullable(),
  payout: z.number(),
  profit: z.number(),
});
export type BacktestBetRow = z.infer<typeof backtestBetRowSchema>;

export const backtestSummarySchema = z.object({
  n_bets: z.number().int(),
  n_wins: z.number().int(),
  n_losses: z.number().int(),
  n_unresolved: z.number().int(),
  total_stake: z.number(),
  total_profit: z.number(),
  roi: z.number(),
  hit_rate: z.number(),
  sharpe: z.number(),
});
export type BacktestSummary = z.infer<typeof backtestSummarySchema>;

export const backtestRunResponseSchema = z.object({
  request: backtestRunRequestSchema,
  fixtures_considered: z.number().int(),
  summary: backtestSummarySchema,
  bets: z.array(backtestBetRowSchema),
});
export type BacktestRunResponse = z.infer<typeof backtestRunResponseSchema>;

export const dataColumnSchema = z.object({
  name: z.string(),
  dtype: z.string(),
});
export type DataColumn = z.infer<typeof dataColumnSchema>;

export const dataPartitionSchema = z.object({
  values: z.record(z.string()),
  rows: z.number().int().nonnegative(),
});
export type DataPartition = z.infer<typeof dataPartitionSchema>;

export const dataTableOverviewSchema = z.object({
  name: z.string(),
  root: z.string(),
  partition_keys: z.array(z.string()),
  exists: z.boolean(),
  total_rows: z.number().int().nonnegative(),
  columns: z.array(dataColumnSchema),
  partitions: z.array(dataPartitionSchema),
  samples: z.array(z.record(z.string().nullable())),
});
export type DataTableOverview = z.infer<typeof dataTableOverviewSchema>;

export const dataOverviewResponse = z.object({
  generated_at: z.string(),
  lake_root: z.string(),
  tables: z.array(dataTableOverviewSchema),
});
export type DataOverviewResponse = z.infer<typeof dataOverviewResponse>;
