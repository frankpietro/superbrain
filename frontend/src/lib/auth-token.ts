/**
 * Bearer-token sanitization.
 *
 * Tokens travel in the HTTP `Authorization` header, which rejects any code
 * point above U+00FF. We tighten further and require printable ASCII so that
 * invisible/zero-width/whitespace characters pasted from rich sources (Notion,
 * password managers, chat apps) can't silently poison the header value and
 * crash `fetch()` with:
 *
 *   TypeError: Failed to read the 'headers' property from 'RequestInit':
 *   String contains non ISO-8859-1 code point.
 */

export type SanitizeResult =
  | { ok: true; token: string }
  | { ok: false; reason: string };

// Allowed range: printable ASCII minus space (0x21–0x7E). RFC 6750 lets tokens
// use a slightly wider character class, but real bearer tokens — UUIDs, JWTs,
// opaque base64-url strings, or plain dev passwords — always fit in this set
// and rejecting anything else is the behaviour owners actually want.
const VALID_CHAR = /^[\x21-\x7E]+$/;

export function sanitizeBearerToken(raw: unknown): SanitizeResult {
  if (typeof raw !== "string") {
    return { ok: false, reason: "Token must be a string." };
  }
  // Strip leading/trailing whitespace. JS `\s` covers NBSP (U+00A0) and the
  // U+2000..U+200A block, but not zero-width / format characters, so peel
  // those off explicitly before the match-all whitespace trim.
  const zeroWidth = /[\u200B-\u200F\u2060\uFEFF]/g;
  const trimmed = raw.replace(zeroWidth, "").replace(/^\s+|\s+$/gu, "");
  if (trimmed.length === 0) {
    return { ok: false, reason: "Token is empty." };
  }
  if (!VALID_CHAR.test(trimmed)) {
    const offenders = Array.from(trimmed)
      .filter((ch) => !/^[\x21-\x7E]$/.test(ch))
      .map((ch) => `U+${ch.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`);
    const preview = offenders.slice(0, 3).join(", ");
    const suffix = offenders.length > 3 ? ` (+${offenders.length - 3} more)` : "";
    return {
      ok: false,
      reason: `Token contains characters that browsers refuse in HTTP headers: ${preview}${suffix}. Retype it as plain ASCII.`,
    };
  }
  return { ok: true, token: trimmed };
}
