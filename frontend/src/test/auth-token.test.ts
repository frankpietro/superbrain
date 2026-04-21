import { describe, expect, it } from "vitest";
import { sanitizeBearerToken } from "@/lib/auth-token";

describe("sanitizeBearerToken", () => {
  it("accepts a plain ASCII token", () => {
    const result = sanitizeBearerToken("dev-token");
    expect(result).toEqual({ ok: true, token: "dev-token" });
  });

  it("accepts a realistic opaque bearer token", () => {
    const token = "sb_9fA3-BxQ_z1k2P.Vm7N~t4R8s";
    const result = sanitizeBearerToken(token);
    expect(result).toEqual({ ok: true, token });
  });

  it("trims surrounding ASCII whitespace", () => {
    const result = sanitizeBearerToken("  dev-token\n");
    expect(result).toEqual({ ok: true, token: "dev-token" });
  });

  it("trims exotic whitespace (NBSP, ZWSP) that break header headers", () => {
    const result = sanitizeBearerToken("\u00a0dev-token\u200b");
    expect(result).toEqual({ ok: true, token: "dev-token" });
  });

  it("rejects an empty input", () => {
    const result = sanitizeBearerToken("");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/empty/i);
  });

  it("rejects whitespace-only input", () => {
    const result = sanitizeBearerToken("   \u00a0  ");
    expect(result.ok).toBe(false);
  });

  it("rejects a smart-quoted token with a helpful offender dump", () => {
    const result = sanitizeBearerToken("dev\u2013token"); // en-dash
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toContain("U+2013");
      expect(result.reason).toMatch(/plain ASCII/i);
    }
  });

  it("rejects embedded whitespace", () => {
    const result = sanitizeBearerToken("dev token");
    expect(result.ok).toBe(false);
  });

  it("rejects emoji", () => {
    const result = sanitizeBearerToken("dev-token-\uD83D\uDD25");
    expect(result.ok).toBe(false);
  });

  it("rejects non-string inputs", () => {
    expect(sanitizeBearerToken(undefined).ok).toBe(false);
    expect(sanitizeBearerToken(null).ok).toBe(false);
    expect(sanitizeBearerToken(42).ok).toBe(false);
  });
});
