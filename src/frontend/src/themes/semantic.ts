// Only type imports here: Node runs this file directly with type stripping.
import type { ThemeColors } from "../types/theme";

/** The six semantic colour tokens added by DESIGN.md (E0-UX.1). */
export const SEMANTIC_TOKEN_KEYS = ["success", "warning", "info", "gm", "live", "danger"] as const;

export type SemanticTokenKey = (typeof SEMANTIC_TOKEN_KEYS)[number];

/**
 * Fill in any semantic token a (custom, imported) theme is missing.
 *
 * Custom themes predate these keys, so each missing key falls back to the
 * dark fallback when the theme's `background` lightness is <= 50% (or cannot
 * be parsed), otherwise to the light fallback. Keys the theme already has
 * are kept. Returns a new object; the input is not mutated.
 */
export function withSemanticFallback(
  colors: Partial<ThemeColors>,
  darkFallback: ThemeColors,
  lightFallback: ThemeColors,
): ThemeColors {
  const lightness = parseFloat(
    String(colors.background ?? "").trim().split(/\s+/)[2]?.replace("%", "") ?? "",
  );
  const fallback = !Number.isNaN(lightness) && lightness > 50 ? lightFallback : darkFallback;

  const result = { ...colors } as ThemeColors;
  for (const key of SEMANTIC_TOKEN_KEYS) {
    const value = result[key];
    if (typeof value !== "string" || value.trim() === "") {
      result[key] = fallback[key];
    }
  }
  return result;
}
