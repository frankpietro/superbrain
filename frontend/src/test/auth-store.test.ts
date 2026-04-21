import { beforeEach, describe, expect, it } from "vitest";
import { getAuthToken, useAuth } from "@/stores/auth";

describe("auth store", () => {
  beforeEach(() => {
    useAuth.getState().clear();
  });

  it("starts with no token", () => {
    expect(useAuth.getState().token).toBeNull();
    expect(getAuthToken()).toBeNull();
  });

  it("persists a token to localStorage", () => {
    useAuth.getState().setToken("sb_test_token");
    expect(useAuth.getState().token).toBe("sb_test_token");
    expect(getAuthToken()).toBe("sb_test_token");

    const raw = localStorage.getItem("superbrain.auth");
    expect(raw).not.toBeNull();
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    expect(parsed).toMatchObject({ state: { token: "sb_test_token" } });
  });

  it("clears the token", () => {
    useAuth.getState().setToken("sb_x");
    useAuth.getState().clear();
    expect(useAuth.getState().token).toBeNull();
  });

  it("rejects a token containing non-ISO-8859-1 characters", () => {
    useAuth.getState().setToken("dev\u2013token"); // en-dash
    expect(useAuth.getState().token).toBeNull();
  });

  it("strips surrounding whitespace before persisting", () => {
    useAuth.getState().setToken("  sb_trimmed\n");
    expect(useAuth.getState().token).toBe("sb_trimmed");
  });

  it("refuses an empty or whitespace-only token", () => {
    useAuth.getState().setToken("");
    expect(useAuth.getState().token).toBeNull();
    useAuth.getState().setToken("   ");
    expect(useAuth.getState().token).toBeNull();
  });
});
