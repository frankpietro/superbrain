import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { apiFetch, ApiError, ApiParseError } from "@/lib/api";

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
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not attach an Authorization header", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const headers = init?.headers as Record<string, string> | undefined;
      expect(headers?.Authorization).toBeUndefined();
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

  it("throws ApiError for non-2xx responses", async () => {
    mockFetchOnce({ status: 500, body: { detail: "boom" } });

    await expect(apiFetch("/matches", schema)).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiParseError when the response fails zod validation", async () => {
    mockFetchOnce({ status: 200, body: { status: "degraded" } });

    await expect(apiFetch("/health", schema)).rejects.toBeInstanceOf(ApiParseError);
  });
});
