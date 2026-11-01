#!/usr/bin/env node
// UI token checks (DESIGN.md / CI-15). Dependency-free.
//
//   node scripts/check-ui-tokens.mjs --contrast [--themes-dir <dir>]
//     Every semantic token in every theme must reach >= 4.5:1 (WCAG AA text)
//     against that theme's `card`, its `background`, and its own 14% wash
//     composited over `card` (0.14 * token + 0.86 * card, in sRGB).
//
//   node scripts/check-ui-tokens.mjs
//     The source grep check arrives in E0-UX.2; for now this is a no-op.

import { readdirSync, readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const TOKENS = ["success", "warning", "info", "gm", "live", "danger"];
const MIN_RATIO = 4.5;
const WASH_ALPHA = 0.14;

const scriptDir = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);

function argValue(flag) {
  const i = args.indexOf(flag);
  if (i === -1) return undefined;
  const value = args[i + 1];
  if (!value || value.startsWith("--")) {
    console.error(`${flag} needs a value`);
    process.exit(2);
  }
  return value;
}

/** Parse "H S% L%" (no hsl()) into [h, s, l] with s, l in 0..1. */
function parseHsl(triplet) {
  const m = /^\s*(-?[\d.]+)\s+([\d.]+)%\s+([\d.]+)%\s*$/.exec(triplet);
  if (!m) return null;
  return [Number(m[1]), Number(m[2]) / 100, Number(m[3]) / 100];
}

/** HSL -> sRGB channels in 0..1. */
function hslToRgb([h, s, l]) {
  const hue = ((h % 360) + 360) % 360;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
  const m = l - c / 2;
  let rgb;
  if (hue < 60) rgb = [c, x, 0];
  else if (hue < 120) rgb = [x, c, 0];
  else if (hue < 180) rgb = [0, c, x];
  else if (hue < 240) rgb = [0, x, c];
  else if (hue < 300) rgb = [x, 0, c];
  else rgb = [c, 0, x];
  return rgb.map((v) => v + m);
}

function luminance(rgb) {
  const [r, g, b] = rgb.map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function composite(fg, bg, alpha) {
  return fg.map((v, i) => alpha * v + (1 - alpha) * bg[i]);
}

/** Pull `key: "H S% L%"` pairs out of a theme file's colors object. */
function parseThemeFile(path) {
  const src = readFileSync(path, "utf8");
  const id = /\bid:\s*["']([^"']+)["']/.exec(src)?.[1] ?? basename(path, ".ts");
  const colors = {};
  const re = /["']?([a-z][a-z-]*)["']?\s*:\s*["']([^"']+)["']/g;
  for (const [, key, value] of src.matchAll(re)) {
    if (parseHsl(value)) colors[key] = value;
  }
  return { id, colors };
}

function runContrast() {
  const themesDir = resolve(argValue("--themes-dir") ?? join(scriptDir, "..", "src", "themes"));
  let files;
  try {
    files = readdirSync(themesDir)
      .filter((f) => f.endsWith(".ts") && f !== "index.ts" && f !== "semantic.ts")
      .sort();
  } catch (err) {
    console.error(`Cannot read themes directory ${themesDir}: ${err.message}`);
    return 2;
  }

  const themes = files.map((f) => parseThemeFile(join(themesDir, f)));
  if (themes.length === 0) {
    console.error(`No theme files found in ${themesDir}`);
    return 2;
  }

  const failures = [];
  const rows = [];
  for (const { id, colors } of themes) {
    if (!colors.card) {
      failures.push(`${id}: surface "card" is missing`);
      continue;
    }
    const card = hslToRgb(parseHsl(colors.card));
    const background = colors.background ? hslToRgb(parseHsl(colors.background)) : null;
    for (const token of TOKENS) {
      if (!colors[token]) {
        failures.push(`${id}: token "${token}" is missing`);
        continue;
      }
      const fg = hslToRgb(parseHsl(colors[token]));
      const surfaces = {
        card,
        background,
        wash: composite(fg, card, WASH_ALPHA),
      };
      const ratios = {};
      for (const [surface, rgb] of Object.entries(surfaces)) {
        if (!rgb) {
          failures.push(`${id}: surface "${surface}" is missing`);
          continue;
        }
        const ratio = contrast(fg, rgb);
        ratios[surface] = ratio;
        if (ratio < MIN_RATIO) {
          failures.push(
            `${id}: ${token} on ${surface} is ${ratio.toFixed(2)}:1 (needs ${MIN_RATIO}:1)`,
          );
        }
      }
      rows.push({ id, token, ...ratios });
    }
  }

  const fmt = (r) => (r === undefined ? "  -  " : r.toFixed(2).padStart(5));
  console.log(`Semantic token contrast (min ${MIN_RATIO}:1) — ${themesDir}`);
  console.log(`${"theme".padEnd(12)}${"token".padEnd(10)}${"card".padStart(7)}${"bg".padStart(7)}${"wash".padStart(7)}`);
  for (const r of rows) {
    console.log(
      `${r.id.padEnd(12)}${r.token.padEnd(10)}  ${fmt(r.card)}  ${fmt(r.background)}  ${fmt(r.wash)}`,
    );
  }

  if (failures.length > 0) {
    console.error(`\n${failures.length} contrast failure(s):`);
    for (const f of failures) console.error(`  FAIL ${f}`);
    return 1;
  }
  console.log(`\nAll ${rows.length * 3} pairs pass.`);
  return 0;
}

if (args.includes("--contrast")) {
  process.exit(runContrast());
} else {
  console.log("check-ui-tokens: the source grep check arrives in E0-UX.2. Run with --contrast for the theme contrast check.");
  process.exit(0);
}
