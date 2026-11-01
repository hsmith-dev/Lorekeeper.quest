#!/usr/bin/env node
// Static touch-target audit (E0-UX.9). Every interactive control in
// components/ui/*, components/shell/*, components/SlideOver.tsx and
// components/NavBar.tsx must be at least 44x44 px at 375 px, or carry the
// `tap-target` hit area (index.css) on a positioned element. Nothing may be
// revealed only on hover.
//
// What counts as interactive: button, a, Link, input, select, textarea,
// summary, button.tsx's Comp, and any tag with an interactive role. <Button>
// and <Input> usages are skipped: those primitives are audited where they are
// defined.
//
// Class strings are resolved from literals (including template literals and
// the branches of conditionals), same-file `const` strings and cva bases.
// Only classes with no variant prefix, or with `max-md:` / `max-sm:`, apply at
// 375 px. Elements hidden there (`hidden`, `sr-only`, type="hidden") are skipped.
//
// It prints the checklist (paste it into the PR description). A failure, an
// allowlist entry with no reason, or a stale allowlist entry exits 1.
//
//   node scripts/check-touch-targets.mjs              # audit the real files
//   node scripts/check-touch-targets.mjs --self-test  # run the inline fixtures

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const componentsDir = join(frontendDir, "src", "components");

/** Allowlisted failures. `match` is a substring of the element's opening tag. */
export const ALLOWLIST = [
  {
    file: "src/components/ui/model-missing-notice.tsx",
    match: "<Link",
    reason: "Inline link inside a sentence; WCAG 2.5.8 exempts inline targets whose size is set by the line of text.",
  },
];

// ---------------------------------------------------------------------------
// Scanning

const INTERACTIVE_TAGS = new Set(["button", "a", "Link", "input", "select", "textarea", "summary", "Comp"]);
const SKIPPED_TAGS = new Set(["Button", "Input"]);
const INTERACTIVE_ROLES = new Set([
  "button",
  "link",
  "checkbox",
  "radio",
  "switch",
  "tab",
  "menuitem",
  "menuitemcheckbox",
  "menuitemradio",
  "option",
  "combobox",
  "slider",
  "spinbutton",
  "textbox",
  "searchbox",
  "treeitem",
]);

/** Skip a JS string/template starting at `i` (the quote). Returns the index after it. */
function skipString(src, i) {
  const q = src[i];
  let j = i + 1;
  while (j < src.length) {
    const c = src[j];
    if (c === "\\") {
      j += 2;
      continue;
    }
    if (q === "`" && c === "$" && src[j + 1] === "{") {
      j = skipBraces(src, j + 1);
      continue;
    }
    if (c === q) return j + 1;
    j++;
  }
  return j;
}

/** Skip a balanced {...} starting at `i` (the brace). Returns the index after it. */
function skipBraces(src, i) {
  let depth = 0;
  let j = i;
  while (j < src.length) {
    const c = src[j];
    if (c === '"' || c === "'" || c === "`") {
      j = skipString(src, j);
      continue;
    }
    if (c === "/" && src[j + 1] === "/") {
      j = src.indexOf("\n", j);
      if (j < 0) return src.length;
      continue;
    }
    if (c === "/" && src[j + 1] === "*") {
      j = src.indexOf("*/", j) + 2;
      if (j < 2) return src.length;
      continue;
    }
    if (c === "{" || c === "(" || c === "[") depth++;
    else if (c === "}" || c === ")" || c === "]") {
      depth--;
      if (depth === 0) return j + 1;
    }
    j++;
  }
  return j;
}

/** Opening JSX tags: { tag, text, attrs, line }. */
export function scanTags(src) {
  const out = [];
  const re = /<([A-Za-z][\w.]*)(?=[\s>/])/g;
  let m;
  while ((m = re.exec(src))) {
    const start = m.index;
    // Generics (useRef<T>, forwardRef<A, B>) sit right after an identifier;
    // a comparison `a < b` has a space after `<`, which the regex excludes.
    if (start > 0 && /[\w$.)\]]/.test(src[start - 1])) continue;
    const attrs = {};
    let j = m.index + m[0].length;
    let end = -1;
    while (j < src.length) {
      const c = src[j];
      if (c === ">") {
        end = j + 1;
        break;
      }
      if (c === "/" && src[j + 1] === ">") {
        end = j + 2;
        break;
      }
      if (c === "{") {
        // Spread or comment: {...props}
        j = skipBraces(src, j);
        continue;
      }
      const am = /^([A-Za-z_][\w-:]*)(\s*=\s*)?/.exec(src.slice(j));
      if (am && am[0].length > 0) {
        const name = am[1];
        j += am[0].length;
        if (!am[2]) {
          attrs[name] = { kind: "bool" };
          continue;
        }
        const v = src[j];
        if (v === '"' || v === "'") {
          const k = skipString(src, j);
          attrs[name] = { kind: "string", value: src.slice(j + 1, k - 1) };
          j = k;
        } else if (v === "{") {
          const k = skipBraces(src, j);
          attrs[name] = { kind: "expr", value: src.slice(j + 1, k - 1) };
          j = k;
        } else {
          j++;
        }
        continue;
      }
      j++;
    }
    if (end < 0) continue;
    const line = src.slice(0, start).split("\n").length;
    out.push({ tag: m[1], text: src.slice(start, end), attrs, line });
    re.lastIndex = end;
  }
  return out;
}

/** `const NAME = <initializer>` for every top-level-looking const in the file. */
export function scanConsts(src) {
  const consts = new Map();
  const re = /\bconst\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*/g;
  let m;
  while ((m = re.exec(src))) {
    const start = m.index + m[0].length;
    let j = start;
    let depth = 0;
    while (j < src.length) {
      const c = src[j];
      if (c === '"' || c === "'" || c === "`") {
        j = skipString(src, j);
        continue;
      }
      if (c === "{" || c === "(" || c === "[") depth++;
      else if (c === "}" || c === ")" || c === "]") {
        if (depth === 0) break;
        depth--;
      } else if (depth === 0 && c === ";") break;
      else if (depth === 0 && c === "\n") {
        const prev = src.slice(start, j).trimEnd().slice(-1);
        const next = src.slice(j + 1).trimStart()[0];
        const continues = /[=+?:(,[{&|]/.test(prev) || /[+?:.)\]}&|]/.test(next ?? "");
        if (!continues) break;
      }
      j++;
    }
    if (!consts.has(m[1])) consts.set(m[1], src.slice(start, j).trim());
  }
  return consts;
}

/** Every string literal (and template literal static part) in an expression. */
function literals(expr) {
  const out = [];
  let j = 0;
  while (j < expr.length) {
    const c = expr[j];
    if (c === '"' || c === "'") {
      const k = skipString(expr, j);
      out.push(expr.slice(j + 1, k - 1));
      j = k;
      continue;
    }
    if (c === "`") {
      const k = skipString(expr, j);
      const body = expr.slice(j + 1, k - 1);
      // Static parts, then recurse into ${...}.
      let s = 0;
      let p = 0;
      while (p < body.length) {
        if (body[p] === "$" && body[p + 1] === "{") {
          out.push(body.slice(s, p));
          const q = skipBraces(body, p + 1);
          out.push(...literals(body.slice(p + 2, q - 1)));
          out.push(...identifierClasses(body.slice(p + 2, q - 1)));
          s = p = q;
          continue;
        }
        p++;
      }
      out.push(body.slice(s));
      j = k;
      continue;
    }
    j++;
  }
  return out;
}

let currentConsts = new Map();
let resolving = new Set();

/** Class strings referenced through same-file consts (and cva bases) in `expr`. */
function identifierClasses(expr) {
  const out = [];
  // Strip strings first so identifiers inside them don't count.
  const bare = expr.replace(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`/g, '""');
  for (const m of bare.matchAll(/(?<![\w$.])([A-Za-z_$][\w$]*)/g)) {
    const name = m[1];
    const init = currentConsts.get(name);
    if (init === undefined || resolving.has(name)) continue;
    resolving.add(name);
    out.push(...resolveExpr(init));
    resolving.delete(name);
  }
  return out;
}

function resolveExpr(expr) {
  const cva = /^cva\(\s*/.exec(expr);
  if (cva) {
    // Only the base (first argument) applies to every variant.
    const rest = expr.slice(cva[0].length);
    const q = rest[0];
    if (q === '"' || q === "'" || q === "`") return literals(rest.slice(0, skipString(rest, 0)));
    return [];
  }
  return [...literals(expr), ...identifierClasses(expr)];
}

/** All classes an element's className can carry (union over branches). */
export function elementClasses(tagInfo, consts) {
  const a = tagInfo.attrs.className ?? tagInfo.attrs.class;
  if (!a || a.kind === "bool") return [];
  if (a.kind === "string") return split(a.value);
  currentConsts = consts;
  resolving = new Set();
  try {
    return split(resolveExpr(a.value.trim()).join(" "));
  } finally {
    currentConsts = new Map();
  }
}

const split = (s) => s.split(/\s+/).filter(Boolean);

/** Variant prefixes and the utility: "md:hover:h-10" → { variants: ["md","hover"], util: "h-10" }. */
function parseClass(cls) {
  const parts = [];
  let depth = 0;
  let cur = "";
  for (const c of cls) {
    if (c === "[") depth++;
    if (c === "]") depth--;
    if (c === ":" && depth === 0) {
      parts.push(cur);
      cur = "";
    } else cur += c;
  }
  return { variants: parts, util: cur.replace(/^!/, "") };
}

const APPLIES_AT_375 = new Set(["max-md", "max-sm"]);
/** Utilities that apply at a 375 px viewport with no interaction. */
function baseUtils(classes) {
  return classes
    .map(parseClass)
    .filter((c) => c.variants.every((v) => APPLIES_AT_375.has(v)))
    .map((c) => c.util);
}

function sizeOf(util, axis) {
  // axis: "h" or "w"
  const re = new RegExp(`^(?:min-${axis}|${axis}|size)-(.+)$`);
  const m = re.exec(util);
  if (!m) return null;
  const v = m[1];
  if (axis === "w" && v === "full") return Infinity;
  const arb = /^\[(\d+(?:\.\d+)?)(px|rem)\]$/.exec(v);
  if (arb) return Number(arb[1]) * (arb[2] === "rem" ? 16 : 1);
  if (/^\d+(\.\d+)?$/.test(v)) return Number(v) * 4;
  return null;
}

const POSITIONED = new Set(["relative", "absolute", "fixed", "sticky"]);
const HIDES = new Set(["opacity-0", "invisible", "hidden"]);
const REVEALS = new Set(["opacity-100", "visible", "block", "flex", "inline-flex"]);
const HOVERS = new Set(["hover", "group-hover", "peer-hover"]);

function isInteractive(t) {
  if (SKIPPED_TAGS.has(t.tag)) return false;
  if (INTERACTIVE_TAGS.has(t.tag)) return true;
  const role = t.attrs.role;
  return role?.kind === "string" && INTERACTIVE_ROLES.has(role.value);
}

/** Audit one source file. Returns [{ line, tag, text, ok, why }]. */
export function auditSource(src) {
  const consts = scanConsts(src);
  const results = [];
  for (const t of scanTags(src)) {
    const classes = elementClasses(t, consts);
    const all = classes.map(parseClass);
    const base = baseUtils(classes);

    // Hover-only reveal (any element, interactive or not).
    const hidden = base.some((u) => HIDES.has(u));
    const hoverReveal = all.some((c) => c.variants.some((v) => HOVERS.has(v)) && REVEALS.has(c.util));
    const baseReveal = base.some((u) => REVEALS.has(u) && u !== "block" && u !== "flex" && u !== "inline-flex");
    if (hidden && hoverReveal && !baseReveal) {
      results.push({ line: t.line, tag: t.tag, text: t.text, ok: false, why: "revealed only on hover" });
      continue;
    }

    if (!isInteractive(t)) continue;
    const type = t.attrs.type;
    if (type?.kind === "string" && type.value === "hidden") continue;
    if (base.includes("hidden") || base.includes("sr-only")) continue;

    if (base.includes("tap-target")) {
      const positioned = base.some((u) => POSITIONED.has(u));
      results.push({
        line: t.line,
        tag: t.tag,
        text: t.text,
        ok: positioned,
        why: positioned ? "tap-target" : "tap-target without a positioned class (relative/absolute/fixed/sticky)",
      });
      continue;
    }

    const h = Math.max(0, ...base.map((u) => sizeOf(u, "h") ?? 0));
    const w = Math.max(0, ...base.map((u) => sizeOf(u, "w") ?? 0), base.includes("flex-1") ? Infinity : 0);
    const ok = h >= 44 && w >= 44;
    const fmt = (n) => (n === Infinity ? "full" : `${n}px`);
    results.push({
      line: t.line,
      tag: t.tag,
      text: t.text,
      ok,
      why: ok ? `${fmt(h)} x ${fmt(w)}` : `height ${h ? fmt(h) : "unset"}, width ${w ? fmt(w) : "unset"} (need 44 x 44 or tap-target)`,
    });
  }
  return results;
}

/** Apply the allowlist. Returns { rows, failures, problems }. */
export function applyAllowlist(byFile, allowlist) {
  const problems = [];
  const used = new Set();
  for (const entry of allowlist) {
    if (!entry.reason || !String(entry.reason).trim()) {
      problems.push(`allowlist entry ${entry.file} "${entry.match}" has no reason`);
    }
  }
  const rows = [];
  for (const [file, results] of byFile) {
    for (const r of results) {
      let row = { file, ...r };
      if (!r.ok) {
        const i = allowlist.findIndex((e) => e.file === file && r.text.includes(e.match));
        if (i >= 0) {
          used.add(i);
          row = { ...row, ok: true, allowed: allowlist[i].reason };
        }
      }
      rows.push(row);
    }
  }
  allowlist.forEach((e, i) => {
    if (!used.has(i)) problems.push(`stale allowlist entry: ${e.file} "${e.match}" matches no failing element`);
  });
  return { rows, failures: rows.filter((r) => !r.ok), problems };
}

function auditedFiles() {
  const list = (dir) =>
    readdirSync(dir)
      .filter((f) => f.endsWith(".tsx"))
      .sort()
      .map((f) => join(dir, f));
  return [
    ...list(join(componentsDir, "ui")),
    ...list(join(componentsDir, "shell")),
    join(componentsDir, "SlideOver.tsx"),
    join(componentsDir, "NavBar.tsx"),
    join(componentsDir, "ThemeSelector.tsx"),
  ];
}

const summary = (text) => text.replace(/\s+/g, " ").slice(0, 70) + (text.length > 70 ? "…" : "");

function runAudit() {
  const byFile = new Map();
  for (const path of auditedFiles()) {
    byFile.set(relative(frontendDir, path), auditSource(readFileSync(path, "utf8")));
  }
  const { rows, failures, problems } = applyAllowlist(byFile, ALLOWLIST);

  console.log("Touch-target checklist (375 px, ≥ 44 x 44 or tap-target):\n");
  for (const [file] of byFile) {
    const fileRows = rows.filter((r) => r.file === file);
    if (fileRows.length === 0) continue;
    console.log(`**${file}**`);
    for (const r of fileRows) {
      const mark = r.ok ? "x" : " ";
      const note = r.allowed ? `allowlisted: ${r.allowed}` : r.why;
      console.log(`- [${mark}] L${r.line} \`${summary(r.text)}\` — ${note}`);
    }
    console.log("");
  }
  for (const p of problems) console.error(`ERROR: ${p}`);
  for (const f of failures) console.error(`FAIL: ${f.file}:${f.line} <${f.tag}> ${f.why}`);
  if (failures.length || problems.length) {
    console.error(`\ncheck-touch-targets: ${failures.length} failing element(s), ${problems.length} allowlist problem(s).`);
    process.exit(1);
  }
  console.log(`check-touch-targets: ${rows.length} interactive element(s) OK.`);
}

// ---------------------------------------------------------------------------
// Self-test

function selfTest() {
  let failed = 0;
  const expect = (name, cond) => {
    if (cond) console.log(`ok   ${name}`);
    else {
      failed++;
      console.error(`FAIL ${name}`);
    }
  };
  const one = (src) => auditSource(src);

  expect("44px own box passes", one(`const X = () => <button className="min-h-11 min-w-11">x</button>`)[0]?.ok === true);
  expect("size-11 passes", one(`const X = () => <button className="size-11">x</button>`)[0]?.ok === true);
  expect("w-full + h-11 passes", one(`const X = () => <a href="#" className="flex h-11 w-full">x</a>`)[0]?.ok === true);
  expect("flex-1 width passes", one(`const X = () => <button className="min-h-11 flex-1">x</button>`)[0]?.ok === true);
  expect("arbitrary px passes", one(`const X = () => <button className="h-[48px] w-[44px]">x</button>`)[0]?.ok === true);
  expect("36px fails", one(`const X = () => <button className="px-4 py-2">x</button>`)[0]?.ok === false);
  expect("height only fails", one(`const X = () => <button className="min-h-11">x</button>`)[0]?.ok === false);
  expect("md: size does not count", one(`const X = () => <button className="h-9 w-9 md:h-11 md:w-11">x</button>`)[0]?.ok === false);
  expect("max-md: size counts", one(`const X = () => <button className="max-md:h-11 max-md:w-11 h-9">x</button>`)[0]?.ok === true);
  expect("tap-target + relative passes", one(`const X = () => <button className="relative tap-target p-1">x</button>`)[0]?.ok === true);
  expect("tap-target alone fails", one(`const X = () => <button className="tap-target p-1">x</button>`)[0]?.ok === false);
  expect(
    "same-file const resolves",
    one(`const ITEM = "flex min-h-11 w-full"\nconst X = () => <button className={ITEM}>x</button>`)[0]?.ok === true,
  );
  expect(
    "cn() of const + literal resolves",
    one(`const RING =\n  "focus:ring"\nconst X = () => <button className={cn("relative", RING, "tap-target")}>x</button>`)[0]?.ok === true,
  );
  expect(
    "cva base resolves, variants ignored",
    one(
      `const v = cva("inline-flex min-h-11", { variants: { size: { lg: "min-w-11" } } })\nconst X = () => <button className={v({ size })}>x</button>`,
    )[0]?.ok === false,
  );
  expect(
    "cva base with both dimensions passes",
    one(`const v = cva("min-h-11 min-w-11", { variants: {} })\nconst X = () => <Comp className={cn(v({ a }), b && "x")} />`)[0]?.ok === true,
  );
  expect(
    "template literal resolves",
    one("const X = () => <Link to=\"/\" className={`flex min-h-11 w-full ${a ? \"x\" : \"y\"}`}>x</Link>")[0]?.ok === true,
  );
  expect("role=menuitem div is audited", one(`const X = () => <div role="menuitem" className="py-1">x</div>`)[0]?.ok === false);
  expect("<Button> usage skipped", one(`const X = () => <Button size="sm">x</Button>`).length === 0);
  expect("<Input role=combobox> skipped", one(`const X = () => <Input role="combobox" />`).length === 0);
  expect("hidden element skipped", one(`const X = () => <input type="file" className="hidden" />`).length === 0);
  expect("sr-only element skipped", one(`const X = () => <a href="#main" className="sr-only">skip</a>`).length === 0);
  expect("type=hidden skipped", one(`const X = () => <input type="hidden" />`).length === 0);
  expect("generic is not a tag", one(`const r = useRef<HTMLButtonElement>(null)`).length === 0);
  expect(
    "hover-only reveal fails",
    one(`const X = () => <div className="opacity-0 group-hover:opacity-100"><span /></div>`)[0]?.why === "revealed only on hover",
  );
  expect(
    "hover reveal with a base reveal passes",
    one(`const X = () => <div className="opacity-0 max-md:opacity-100 hover:opacity-100" />`).length === 0,
  );
  expect("hover color change is fine", one(`const X = () => <div className="hover:bg-muted" />`).length === 0);

  const byFile = new Map([["f.tsx", one(`const X = () => <a href="#" className="underline">x</a>`)]]);
  const allowed = applyAllowlist(byFile, [{ file: "f.tsx", match: "<a", reason: "inline" }]);
  expect("allowlist covers a failure", allowed.failures.length === 0 && allowed.problems.length === 0);
  const noReason = applyAllowlist(byFile, [{ file: "f.tsx", match: "<a", reason: " " }]);
  expect("allowlist entry without a reason fails", noReason.problems.some((p) => /no reason/.test(p)));
  const stale = applyAllowlist(byFile, [
    { file: "f.tsx", match: "<a", reason: "inline" },
    { file: "f.tsx", match: "<button", reason: "gone" },
  ]);
  expect("stale allowlist entry fails", stale.problems.some((p) => /stale/.test(p)));

  if (failed) {
    console.error(`\ncheck-touch-targets --self-test: ${failed} fixture(s) failed.`);
    process.exit(1);
  }
  console.log("\ncheck-touch-targets --self-test: all fixtures behave.");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes("--self-test")) selfTest();
  else runAudit();
}
