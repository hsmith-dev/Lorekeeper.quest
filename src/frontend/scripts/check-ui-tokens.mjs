#!/usr/bin/env node
// UI token checks (DESIGN.md / CI-15). Dependency-free.
//
//   node scripts/check-ui-tokens.mjs [--src-dir <dir>]
//     Grep gate over src/**/*.{ts,tsx}. Fails (exit 1, file:line:col + class)
//     on colours that ignore the theme:
//       hardcoded-color   (text|bg|border[-side]|ring|fill|stroke|from|to|via|...)-(green|amber|red)-N,
//                         with any variant prefix (hover:, md:, dark: ...)
//       destructive-text  text-destructive not followed by -foreground (fails AA
//                         as text in dark themes; use text-danger)
//       arbitrary-color   hex / rgb( / rgba( / numeric hsl( inside a Tailwind
//                         arbitrary value, e.g. bg-[#123456]
//       style-color       hex / rgb( / numeric hsl( in a style colour property,
//                         e.g. style={{ color: "#fff" }}
//       svg-color         hex / rgb( / numeric hsl( in an SVG colour attribute,
//                         e.g. fill="#abc"
//     Token references such as hsl(var(--danger)) pass.
//
//   node scripts/check-ui-tokens.mjs --contrast [--themes-dir <dir>]
//     Every semantic token in every theme must reach >= 4.5:1 (WCAG AA text)
//     against that theme's `card`, its `background`, and its own 14% wash
//     composited over `card` (0.14 * token + 0.86 * card, in sRGB). `danger`
//     must also reach 4.5:1 on a `destructive` 20% wash over `card`, the
//     strongest wash text-danger sits on (bg-destructive/10..20, incl. hover).
//
//   node scripts/check-ui-tokens.mjs --self-test
//     Runs both checks against the committed fixtures in
//     scripts/fixtures/ui-tokens/ and fails if either check stops catching
//     what it should (or starts flagging clean code).

import { spawnSync } from "node:child_process";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const TOKENS = ["success", "warning", "info", "gm", "live", "danger"];
const MIN_RATIO = 4.5;
const WASH_ALPHA = 0.14;
const DESTRUCTIVE_WASH_ALPHA = 0.2;
const DESTRUCTIVE_WASH_LABEL = `destructive/${Math.round(DESTRUCTIVE_WASH_ALPHA * 100)} wash`;

const scriptDir = dirname(fileURLToPath(import.meta.url));
const fixturesDir = join(scriptDir, "fixtures", "ui-tokens");
const args = process.argv.slice(2);

/**
 * Grep-gate exceptions. Paths are relative to the scanned src dir, with "/".
 * Every entry needs a reason; an entry without one fails the check.
 * @type {{ file: string, rule: string, reason: string }[]}
 */
const ALLOWLIST = [];

const silent = { log() {}, error() {} };

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

// ---------------------------------------------------------------------------
// Contrast mode
// ---------------------------------------------------------------------------

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

/** @returns {{ code: number, failures: string[] }} */
function runContrast(themesDir, out = console) {
  let files;
  try {
    files = readdirSync(themesDir)
      .filter((f) => f.endsWith(".ts") && f !== "index.ts" && f !== "semantic.ts")
      .sort();
  } catch (err) {
    out.error(`Cannot read themes directory ${themesDir}: ${err.message}`);
    return { code: 2, failures: [] };
  }

  const themes = files.map((f) => parseThemeFile(join(themesDir, f)));
  if (themes.length === 0) {
    out.error(`No theme files found in ${themesDir}`);
    return { code: 2, failures: [] };
  }

  const failures = [];
  const rows = [];
  const dangerRows = [];
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

    // Error lines: text-danger on a bg-destructive/10..20 wash over card.
    if (colors.danger) {
      if (!colors.destructive) {
        failures.push(`${id}: surface "destructive" is missing`);
      } else {
        const danger = hslToRgb(parseHsl(colors.danger));
        const wash = composite(hslToRgb(parseHsl(colors.destructive)), card, DESTRUCTIVE_WASH_ALPHA);
        const ratio = contrast(danger, wash);
        dangerRows.push({ id, ratio });
        if (ratio < MIN_RATIO) {
          failures.push(
            `${id}: danger on ${DESTRUCTIVE_WASH_LABEL} is ${ratio.toFixed(2)}:1 (needs ${MIN_RATIO}:1)`,
          );
        }
      }
    }
  }

  const fmt = (r) => (r === undefined ? "  -  " : r.toFixed(2).padStart(5));
  out.log(`Semantic token contrast (min ${MIN_RATIO}:1) — ${themesDir}`);
  out.log(`${"theme".padEnd(12)}${"token".padEnd(10)}${"card".padStart(7)}${"bg".padStart(7)}${"wash".padStart(7)}`);
  for (const r of rows) {
    out.log(
      `${r.id.padEnd(12)}${r.token.padEnd(10)}  ${fmt(r.card)}  ${fmt(r.background)}  ${fmt(r.wash)}`,
    );
  }
  out.log(`\ndanger on ${DESTRUCTIVE_WASH_LABEL} over card`);
  for (const r of dangerRows) out.log(`${r.id.padEnd(12)}${"danger".padEnd(10)}  ${fmt(r.ratio)}`);

  if (failures.length > 0) {
    out.error(`\n${failures.length} contrast failure(s):`);
    for (const f of failures) out.error(`  FAIL ${f}`);
    return { code: 1, failures };
  }
  out.log(`\nAll ${rows.length * 3 + dangerRows.length} pairs pass.`);
  return { code: 0, failures };
}

// ---------------------------------------------------------------------------
// Grep mode (CI-15)
// ---------------------------------------------------------------------------

const COLOR_LITERAL = /(?<!url\(\s*["']?)#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])|(?<![a-zA-Z])rgba?\(|(?<![a-zA-Z])hsla?\(\s*[-+.\d]/;

const VARIANTS = String.raw`(?:[\w\-]+:)*`;
const UTILITY = String.raw`(?:text|bg|border(?:-[xytrblse])?|ring(?:-offset)?|fill|stroke|from|to|via|outline|divide|decoration|placeholder|caret|accent|shadow)`;

const RULES = [
  {
    rule: "hardcoded-color",
    re: new RegExp(String.raw`(?<![\w\-])(${VARIANTS}${UTILITY}-(?:green|amber|red)-\d+(?:\/\d+)?)(?![\w\-])`, "g"),
  },
  {
    rule: "destructive-text",
    re: new RegExp(String.raw`(?<![\w\-])(${VARIANTS}text-destructive(?!-foreground)(?:\/\d+)?)(?![\w\-])`, "g"),
  },
  {
    rule: "arbitrary-color",
    re: new RegExp(String.raw`(?<![\w\-])(${VARIANTS}[a-z][\w\-]*-\[([^\]\s"'\x60]+)\])`, "g"),
    test: (m) => COLOR_LITERAL.test(m[2]),
  },
  {
    // Object-literal style properties: color, background, borderColor,
    // boxShadow, "background-color", fill, stroke, outline, ...
    rule: "style-color",
    re: /(?<![\w-])(["']?[a-zA-Z-]*(?:[cC]olor|[bB]ackground|[bB]order|[sS]hadow|[fF]ill|[sS]troke|[oO]utline)[a-zA-Z-]*["']?\s*:\s*(["'\x60])([^"'\x60]*)\2)/g,
    test: (m) => COLOR_LITERAL.test(m[3]),
  },
  {
    rule: "svg-color",
    re: /(?<![\w-])((?:fill|stroke|color|stop-color|stopColor|flood-color|floodColor|lighting-color|lightingColor)\s*=\s*\{?\s*(["'\x60])([^"'\x60]*)\2)/g,
    test: (m) => COLOR_LITERAL.test(m[3]),
  },
];

function walk(dir, outFiles = []) {
  for (const name of readdirSync(dir).sort()) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, outFiles);
    else if (/\.(ts|tsx)$/.test(name)) outFiles.push(path);
  }
  return outFiles;
}

/** @returns {string[]} problems with the allowlist (empty when valid) */
function validateAllowlist(list) {
  const known = new Set(RULES.map((r) => r.rule));
  const problems = [];
  list.forEach((entry, i) => {
    if (!entry || typeof entry.file !== "string" || !entry.file.trim()) {
      problems.push(`ALLOWLIST[${i}] needs a "file"`);
    }
    if (!entry || !known.has(entry.rule)) {
      problems.push(`ALLOWLIST[${i}] needs a "rule" (one of ${[...known].join(", ")})`);
    }
    if (!entry || typeof entry.reason !== "string" || !entry.reason.trim()) {
      problems.push(`ALLOWLIST[${i}] needs a "reason"`);
    }
  });
  return problems;
}

/** @returns {{ file: string, line: number, col: number, rule: string, match: string }[]} */
function scanFile(path, rel) {
  const findings = [];
  const lines = readFileSync(path, "utf8").split(/\r?\n/);
  lines.forEach((text, i) => {
    for (const { rule, re, test } of RULES) {
      re.lastIndex = 0;
      for (const m of text.matchAll(re)) {
        if (test && !test(m)) continue;
        findings.push({ file: rel, line: i + 1, col: m.index + 1, rule, match: m[1] });
      }
    }
  });
  return findings;
}

/** @returns {{ code: number, findings: object[], fileCount: number }} */
function runScan(srcDir, allowlist = ALLOWLIST, out = console) {
  const problems = validateAllowlist(allowlist);
  if (problems.length > 0) {
    for (const p of problems) out.error(`check-ui-tokens: ${p}`);
    return { code: 2, findings: [], fileCount: 0 };
  }

  let files;
  try {
    files = walk(srcDir);
  } catch (err) {
    out.error(`Cannot read source directory ${srcDir}: ${err.message}`);
    return { code: 2, findings: [], fileCount: 0 };
  }

  const findings = [];
  for (const path of files) {
    const rel = relative(srcDir, path).split(sep).join("/");
    for (const f of scanFile(path, rel)) {
      if (allowlist.some((a) => a.file === f.file && a.rule === f.rule)) continue;
      findings.push(f);
    }
  }

  if (findings.length > 0) {
    out.error(`check-ui-tokens: ${findings.length} token violation(s) in ${srcDir}`);
    for (const f of findings) out.error(`  ${f.file}:${f.line}:${f.col}  ${f.rule}  ${f.match}`);
    out.error(
      "\nUse the theme tokens instead: success / warning / info / gm / live / danger" +
        " (washes /14, borders /40); readable error text is text-danger, destructive is a fill only.",
    );
    return { code: 1, findings, fileCount: files.length };
  }
  out.log(`check-ui-tokens: ${files.length} files scanned in ${srcDir}, no hardcoded colours.`);
  return { code: 0, findings, fileCount: files.length };
}

// ---------------------------------------------------------------------------
// Self-test
// ---------------------------------------------------------------------------

function runSelfTest() {
  const broken = [];
  const expect = (ok, message) => {
    if (!ok) broken.push(message);
  };

  // The real allowlist must be valid; an entry without a reason must be rejected.
  expect(validateAllowlist(ALLOWLIST).length === 0, "ALLOWLIST entries are valid");
  expect(
    validateAllowlist([{ file: "x.tsx", rule: "hardcoded-color", reason: "" }]).length > 0,
    "an allowlist entry without a reason is rejected",
  );

  // Bad fixture: every line marked `@expect <rule>` must be flagged with that
  // rule, and no unmarked line may be flagged.
  const badDir = join(fixturesDir, "bad");
  const bad = runScan(badDir, [], silent);
  expect(bad.code === 1, "scan of the bad fixture exits 1");
  let seeded = 0;
  for (const path of walk(badDir)) {
    const rel = relative(badDir, path).split(sep).join("/");
    readFileSync(path, "utf8")
      .split(/\r?\n/)
      .forEach((text, i) => {
        const line = i + 1;
        const onLine = bad.findings.filter((f) => f.file === rel && f.line === line);
        const marks = [...text.matchAll(/@expect\s+([\w-]+)/g)].map((m) => m[1]);
        if (marks.length === 0) {
          expect(onLine.length === 0, `bad/${rel}:${line} is unmarked but was flagged (${onLine.map((f) => f.match).join(", ")})`);
        }
        for (const rule of marks) {
          seeded++;
          expect(onLine.some((f) => f.rule === rule), `bad/${rel}:${line} is flagged as ${rule}`);
        }
      });
  }
  expect(seeded > 0, "the bad fixture has seeded lines");

  // An allowlist entry suppresses exactly its file + rule.
  const allowed = runScan(badDir, [{ file: "classes.tsx", rule: "hardcoded-color", reason: "self-test" }], silent);
  expect(
    allowed.findings.every((f) => !(f.file === "classes.tsx" && f.rule === "hardcoded-color")) &&
      allowed.findings.length < bad.findings.length,
    "an allowlist entry suppresses its file and rule",
  );

  // Clean fixture passes.
  const clean = runScan(join(fixturesDir, "clean"), [], silent);
  expect(
    clean.code === 0,
    `scan of the clean fixture exits 0 (flagged: ${clean.findings.map((f) => `${f.file}:${f.line} ${f.match}`).join("; ")})`,
  );

  // Contrast: bad-theme/ holds two themes. too-dark-danger fails every danger
  // row; wash-only-danger passes card, background and its own wash and fails
  // only the destructive-wash row (it would pass at /15, so it also pins the
  // alpha at /20).
  const badTheme = runContrast(join(fixturesDir, "bad-theme"), silent);
  expect(badTheme.code === 1, "contrast on the bad-theme fixture exits 1");
  const ofTheme = (id) => badTheme.failures.filter((f) => f.startsWith(`${id}: `));
  for (const surface of ["card", "background", "wash", DESTRUCTIVE_WASH_LABEL]) {
    expect(
      ofTheme("too-dark-danger").some((f) => f.startsWith(`too-dark-danger: danger on ${surface} is`)),
      `too-dark-danger fails danger on ${surface}`,
    );
  }
  const washOnly = ofTheme("wash-only-danger");
  expect(
    washOnly.length === 1 && washOnly[0].includes(`danger on ${DESTRUCTIVE_WASH_LABEL}`),
    `wash-only-danger fails only danger on ${DESTRUCTIVE_WASH_LABEL} (got: ${washOnly.join("; ") || "none"})`,
  );

  // Contrast: the real themes pass.
  const realThemes = runContrast(join(scriptDir, "..", "src", "themes"), silent);
  expect(realThemes.code === 0, "contrast on src/themes exits 0");

  // CLI dispatch and exit codes, by running this script as CI does.
  const self = fileURLToPath(import.meta.url);
  const cli = [
    [["--src-dir", join(fixturesDir, "bad")], 1],
    [["--src-dir", join(fixturesDir, "clean")], 0],
    [["--contrast", "--themes-dir", join(fixturesDir, "bad-theme")], 1],
  ];
  for (const [cliArgs, want] of cli) {
    const { status } = spawnSync(process.execPath, [self, ...cliArgs], { stdio: "ignore" });
    expect(status === want, `CLI ${cliArgs.join(" ")} exits ${want} (got ${status})`);
  }

  if (broken.length > 0) {
    console.error(`check-ui-tokens --self-test: ${broken.length} expectation(s) broke:`);
    for (const b of broken) console.error(`  FAIL ${b}`);
    return 1;
  }
  console.log(`check-ui-tokens --self-test: ${seeded} seeded lines caught, clean fixture passes, bad theme fails. OK.`);
  return 0;
}

// ---------------------------------------------------------------------------

if (args.includes("--self-test")) {
  process.exit(runSelfTest());
} else if (args.includes("--contrast")) {
  const themesDir = resolve(argValue("--themes-dir") ?? join(scriptDir, "..", "src", "themes"));
  process.exit(runContrast(themesDir).code);
} else {
  const srcDir = resolve(argValue("--src-dir") ?? join(scriptDir, "..", "src"));
  process.exit(runScan(srcDir).code);
}
