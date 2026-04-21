import { z, type ZodType } from "zod";
import {
  backtestRunResponseSchema,
  dataOverviewResponse,
  healthResponse,
  matchesResponse,
  matchSchema,
  matchStatsResponse,
  oddsResponse,
  scrapeRunsResponse,
  scraperStatusResponse,
  valueBetsResponse,
  marketListResponse,
  trendsVariabilityResponse,
  trendsTimeToKickoffResponse,
} from "@/lib/types";

export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export class ApiParseError extends Error {
  readonly issues: z.ZodIssue[];

  constructor(message: string, issues: z.ZodIssue[]) {
    super(message);
    this.name = "ApiParseError";
    this.issues = issues;
  }
}

export function getBaseUrl(): string {
  const url = import.meta.env.VITE_API_BASE_URL;
  if (!url) {
    // Default for local dev; still explicit so CI-time misconfiguration is obvious.
    return "http://localhost:8100";
  }
  return url.replace(/\/$/, "");
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null | string[]>;
  signal?: AbortSignal;
}

function buildQuery(query?: RequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const v of value) params.append(key, String(v));
    } else {
      params.append(key, String(value));
    }
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export async function apiFetch<T>(
  path: string,
  schema: ZodType<T>,
  opts: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, query, signal } = opts;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const url = `${getBaseUrl()}${path}${buildQuery(query)}`;
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    throw new ApiError(
      err instanceof Error ? `Network error: ${err.message}` : "Network error",
      0,
      null,
    );
  }

  const ct = response.headers.get("content-type") ?? "";
  const raw: unknown = ct.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const detail =
      (typeof raw === "object" && raw !== null && "detail" in raw && (raw as { detail?: unknown }).detail) ||
      response.statusText ||
      "Request failed";
    throw new ApiError(typeof detail === "string" ? detail : "Request failed", response.status, raw);
  }

  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    throw new ApiParseError(
      `Malformed response from ${path}: ${parsed.error.issues.map((i) => i.message).join("; ")}`,
      parsed.error.issues,
    );
  }
  return parsed.data;
}

export const api = {
  health: () => apiFetch("/health", healthResponse),
  listMatches: (params: {
    leagues?: string[];
    date_from?: string;
    date_to?: string;
    search?: string;
    limit?: number;
  }) => apiFetch("/matches", matchesResponse, { query: params }),
  getMatch: (id: string) => apiFetch(`/matches/${encodeURIComponent(id)}`, matchSchema),
  getMatchStats: (id: string) =>
    apiFetch(`/matches/${encodeURIComponent(id)}/stats`, matchStatsResponse),
  listOdds: (params: {
    match_id?: string;
    bookmaker?: string;
    market?: string;
    season?: string;
    captured_from?: string;
    limit?: number;
    cursor?: string;
  }) => apiFetch("/odds", oddsResponse, { query: params }),
  scrapersRuns: (params?: { limit?: number; bookmaker?: string }) =>
    apiFetch("/scrapers/runs", scrapeRunsResponse, { query: params }),
  scrapersStatus: () => apiFetch("/scrapers/status", scraperStatusResponse),
  triggerScrape: (bookmaker: string) =>
    apiFetch(`/scrapers/${encodeURIComponent(bookmaker)}/run`, z.object({ run_id: z.string() }), {
      method: "POST",
    }),
  valueBets: (params?: {
    league?: string;
    min_edge?: number;
    markets?: string[];
    limit?: number;
    n_clusters?: number;
    quantile?: number;
    min_matches?: number;
    min_history_matches?: number;
  }) => apiFetch("/bets/value", valueBetsResponse, { query: params }),
  marketList: () => apiFetch("/bets/markets", marketListResponse),
  trendsVariability: (params: {
    group_by: "market" | "team" | "match";
    league?: string;
    bookmaker?: string;
    since_hours?: number;
    min_points?: number;
    limit?: number;
  }) => apiFetch("/trends/variability", trendsVariabilityResponse, { query: params }),
  trendsTimeToKickoff: (params?: {
    bucket_hours?: number;
    league?: string;
    bookmaker?: string;
    market?: string;
    since_hours?: number;
    min_points?: number;
  }) => apiFetch("/trends/time-to-kickoff", trendsTimeToKickoffResponse, { query: params }),
  runBacktest: (body: {
    league: string;
    season: string;
    market?: string;
    threshold?: number;
    edge_cutoff?: number;
    stake?: number;
    min_history_matches?: number;
    n_clusters?: number;
  }) => apiFetch("/backtest/run", backtestRunResponseSchema, { method: "POST", body }),
  dataOverview: () => apiFetch("/data/overview", dataOverviewResponse),
};
