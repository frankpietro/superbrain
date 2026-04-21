import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { apiFetch, ApiError, ApiParseError } from "@/lib/api";
import { useAuth } from "@/stores/auth";

const schema = z.object({ status: z.literal("ok") });

interface MockInit {
  status?: number;
  body?: unknown;
}

function mockFetchOnce(init: MockInit): void {
  const fetchImpl = vi.fn(
    async () =>
      new Response(JSON.stringify(init.body ?? {}), {
        status: init.status ?? 200,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetchImpl);
}

describe("apiFetch", () => {
  beforeEach(() => {
    useAuth.getState().setToken("sb_test");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    useAuth.getState().clear();
  });

  it("sends the bearer token and parses valid responses", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const headers = init?.headers as Record<string, string> | undefined;
      expect(headers?.Authorization).toBe("Bearer sb_test");
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const res = await apiFetch("/health", schema);
    expect(res).toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("clears the auth token on 401 responses and throws ApiError", async () => {
    mockFetchOnce({ status: 401, body: { detail: "invalid token" } });

    await expect(apiFetch("/matches", schema)).rejects.toBeInstanceOf(ApiError);
    expect(useAuth.getState().token).toBeNull();
  });

  it("throws ApiParseError when the response fails zod validation", async () => {
    mockFetchOnce({ status: 200, body: { status: "degraded" } });

    await expect(apiFetch("/health", schema)).rejects.toBeInstanceOf(ApiParseError);
  });

  it("refuses to call authenticated endpoints without a token", async () => {
    useAuth.getState().clear();
    await expect(apiFetch("/matches", schema)).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
    });
  });
});
