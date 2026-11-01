#!/usr/bin/env node
// Checks the custom-theme fallback for the semantic colour tokens
// (src/themes/semantic.ts). Dependency-free: node:assert, no test runner.
// Imports the .ts file directly, so it needs Node >= 22.18 (type stripping).
//
//   node scripts/check-semantic-fallback.mjs

import assert from "node:assert/strict";
import { SEMANTIC_TOKEN_KEYS, withSemanticFallback } from "../src/themes/semantic.ts";

const dark = Object.fromEntries(SEMANTIC_TOKEN_KEYS.map((k) => [k, `dark-${k}`]));
const light = Object.fromEntries(SEMANTIC_TOKEN_KEYS.map((k) => [k, `light-${k}`]));

function assertAllKeys(result) {
  for (const k of SEMANTIC_TOKEN_KEYS) {
    assert.equal(typeof result[k], "string", `missing ${k}`);
    assert.notEqual(result[k], "", `empty ${k}`);
  }
}

try {
  const darkCustom = withSemanticFallback({ background: "220 10% 8%", gm: "custom-gm" }, dark, light);
  assert.equal(darkCustom.gm, "custom-gm", "present custom key is kept");
  for (const k of SEMANTIC_TOKEN_KEYS.filter((k) => k !== "gm")) {
    assert.equal(darkCustom[k], dark[k], `dark background: ${k}`);
  }
  assertAllKeys(darkCustom);

  const lightCustom = withSemanticFallback({ background: "40 30% 96%" }, dark, light);
  for (const k of SEMANTIC_TOKEN_KEYS) assert.equal(lightCustom[k], light[k], `light background: ${k}`);
  assertAllKeys(lightCustom);

  const unparseable = withSemanticFallback({ background: "oops" }, dark, light);
  for (const k of SEMANTIC_TOKEN_KEYS) assert.equal(unparseable[k], dark[k], `"oops" background: ${k}`);
  assertAllKeys(unparseable);
} catch (err) {
  console.error(`check-semantic-fallback: FAIL ${err.message}`);
  process.exit(1);
}

console.log("check-semantic-fallback: all cases pass.");
