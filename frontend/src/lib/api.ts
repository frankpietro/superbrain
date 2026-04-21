import { z, type ZodType } from "zod";
import { sanitizeBearerToken } from "@/lib/auth-token";
import { getAuthToken, useAuth } from "@/stores/auth";
import {
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
  authRequired?: boolean;
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
  const { method = "GET", body, query, signal, authRequired = true } = opts;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const token = getAuthToken();
  if (token) {
    // Belt-and-braces: the auth store already sanitizes, but a stale
    // localStorage entry from a pre-fix build could still carry an unsafe
    // character. Reject here before fetch() crashes with the cryptic
    // "String contains non ISO-8859-1 code point" error.
    const check = sanitizeBearerToken(token);
    if (!check.ok) {
      useAuth.getState().clear();
      throw new ApiError(
        `Stored token is unusable (${check.reason}). Re-enter it on the login page.`,
        401,
        { detail: "invalid stored token" },
      );
    }
    headers.Authorization = `Bearer ${check.token}`;
  }
  if (authRequired && !token) {
    throw new ApiError("Not authenticated", 401, { detail: "missing token" });
  }

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
    if (response.status === 401) {
      useAuth.getState().clear();
    }
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
  health: () => apiFetch("/health", healthResponse, { authRequired: false }),
  verifyToken: () => apiFetch("/matches", matchesResponse, { query: { limit: 1 } }),
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
  valueBets: (params?: { league?: string; min_edge?: number }) =>
    apiFetch("/bets/value", valueBetsResponse, { query: params }),
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
    market: string;
    threshold?: number;
    edge_cutoff?: number;
  }) =>
    apiFetch(
      "/backtest/run",
      z.object({
        job_id: z.string().optional(),
        status: z.string().optional(),
        detail: z.string().optional(),
      }),
      { method: "POST", body },
    ),
};
