#!/usr/bin/env node
// Checks the focus-trap helpers (src/lib/focusTrap.ts) and the Esc layer
// stack (src/lib/layers.ts). Dependency-free: node:assert, no test runner.
// Imports the .ts files directly, so it needs Node >= 22.18 (type stripping).
//
//   node scripts/check-focus-trap.mjs

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// layers.ts and restoreFocus touch `document` lazily; give them a minimal fake.
const listeners = new Set();
let fakeMain = null;
globalThis.document = {
  querySelector: (sel) => (sel === "main" ? fakeMain : null),
  addEventListener: (type, fn) => type === "keydown" && listeners.add(fn),
  removeEventListener: (type, fn) => type === "keydown" && listeners.delete(fn),
};
function keydown(init) {
  const ev = { key: "Escape", isComposing: false, keyCode: 27, defaultPrevented: false, ...init };
  ev.preventDefault = () => {
    ev.defaultPrevented = true;
  };
  for (const fn of [...listeners]) fn(ev);
  return ev;
}

const { nextFocusIndex, handleTabKey, getFocusable, focusInitial, restoreFocus } = await import("../src/lib/focusTrap.ts");
const { activateSlideOver, deactivateSlideOver, activeSlideOver } = await import("../src/lib/slideOverRegistry.ts");
const { pushLayer, closeTopLayer, layerCount } = await import("../src/lib/layers.ts");

let focused = null;
function el(name, { tabIndex = 0, hidden = false, rects = 1 } = {}) {
  const e = {
    name,
    tabIndex,
    hidden,
    getClientRects: () => ({ length: rects }),
    focus: () => {
      focused = e;
    },
  };
  return e;
}
const container = (items) => ({ querySelectorAll: () => items });
function key(k, shiftKey = false) {
  return {
    key: k,
    shiftKey,
    prevented: false,
    preventDefault() {
      this.prevented = true;
    },
  };
}
const tab = (shift = false) => key("Tab", shift);

try {
  // nextFocusIndex
  assert.equal(nextFocusIndex(3, 2, false), 0, "last + Tab wraps to first");
  assert.equal(nextFocusIndex(3, 0, true), 2, "first + Shift+Tab wraps to last");
  assert.equal(nextFocusIndex(3, 0, false), 1, "first + Tab -> second");
  assert.equal(nextFocusIndex(3, 2, true), 1, "last + Shift+Tab -> middle");
  assert.equal(nextFocusIndex(3, -1, false), 0, "outside + Tab -> first");
  assert.equal(nextFocusIndex(3, -1, true), 2, "outside + Shift+Tab -> last");
  assert.equal(nextFocusIndex(0, -1, false), -1, "nothing to focus");

  // getFocusable filters
  const a = el("a");
  const b = el("b");
  const c = el("c");
  const neg = el("neg", { tabIndex: -1 });
  const hid = el("hid", { hidden: true });
  const none = el("none", { rects: 0 });
  const box = container([a, neg, b, hid, none, c]);
  assert.deepEqual(getFocusable(box).map((x) => x.name), ["a", "b", "c"], "drops tabIndex<0, hidden, no rects");

  // handleTabKey
  const heading = el("heading", { tabIndex: -1 });
  let ev = tab();
  handleTabKey(box, ev, c, heading);
  assert.equal(focused, a, "Tab on last -> first");
  assert.ok(ev.prevented, "default Tab prevented");

  ev = tab(true);
  handleTabKey(box, ev, a, heading);
  assert.equal(focused, c, "Shift+Tab on first -> last");
  assert.ok(ev.prevented, "default Shift+Tab prevented");

  handleTabKey(box, tab(), { name: "body" }, heading);
  assert.equal(focused, a, "focus outside + Tab -> first");
  handleTabKey(box, tab(true), { name: "body" }, heading);
  assert.equal(focused, c, "focus outside + Shift+Tab -> last");

  handleTabKey(box, tab(), a, heading);
  assert.equal(focused, b, "Tab steps forward");

  focused = heading;
  ev = tab();
  handleTabKey(container([neg]), ev, heading, heading);
  assert.equal(focused, heading, "no focusables -> heading keeps focus");
  assert.ok(ev.prevented, "default prevented with no focusables");

  const notTab = key("a");
  assert.equal(handleTabKey(box, notTab, a, heading), null, "non-Tab returns null");
  assert.equal(notTab.prevented, false, "non-Tab keys untouched");

  // focusInitial
  focusInitial(box, heading);
  assert.equal(focused, a, "first focusable in content");
  focusInitial(container([]), heading);
  assert.equal(focused, heading, "no focusable content -> heading");

  // restoreFocus: opener still connected -> opener; gone -> main (tabindex=-1); no main -> no-op
  const opener = { ...el("opener"), isConnected: true };
  opener.focus = () => {
    focused = opener;
  };
  opener.focus = () => {
    focused = opener;
    document.activeElement = opener;
  };
  restoreFocus(opener);
  assert.equal(focused, opener, "close returns focus to a connected opener");
  const attrs = {};
  fakeMain = {
    hasAttribute: (n) => n in attrs,
    setAttribute: (n, v) => {
      attrs[n] = v;
    },
    focus: () => {
      focused = fakeMain;
    },
  };
  // connected but unfocusable (focus() is a no-op) -> main
  document.activeElement = null;
  fakeMain = {
    hasAttribute: () => true,
    setAttribute: () => {},
    focus: () => {
      focused = fakeMain;
    },
  };
  restoreFocus({ ...opener, isConnected: true, focus: () => {} });
  assert.equal(focused, fakeMain, "unfocusable opener -> main");
  fakeMain = {
    hasAttribute: (n) => n in attrs,
    setAttribute: (n, v) => {
      attrs[n] = v;
    },
    focus: () => {
      focused = fakeMain;
    },
  };
  restoreFocus({ ...opener, isConnected: false });
  assert.equal(focused, fakeMain, "opener gone -> main");
  assert.equal(attrs.tabindex, "-1", "main gets tabindex=-1");
  attrs.tabindex = "0";
  restoreFocus(null);
  assert.equal(attrs.tabindex, "0", "existing main tabindex kept");
  fakeMain = null;
  focused = null;
  restoreFocus(null);
  assert.equal(focused, null, "no main -> no-op");

  // slideOverRegistry: a second open replaces (never stacks) the first
  const warnings = [];
  const superseded = [];
  const regA = {
    name: "Veyra",
    returnTarget: "cardA",
    supersede: () => superseded.push("A"),
    contains: (t) => t === "inside-A",
  };
  assert.equal(activateSlideOver(regA, (m) => warnings.push(m)), null, "first open replaces nothing");
  assert.equal(activeSlideOver(), regA);
  const regB = {
    name: "Bell Tower",
    returnTarget: "inside-A",
    supersede: () => superseded.push("B"),
    contains: (t) => t === "inside-B",
  };
  assert.equal(activateSlideOver(regB, (m) => warnings.push(m)), regA, "second open supersedes the first");
  assert.deepEqual(superseded, ["A"], "first is told to close");
  assert.equal(activeSlideOver(), regB, "second is active");
  assert.equal(regB.returnTarget, "cardA", "opener inside the old panel -> inherit its return target");
  assert.equal(warnings.length, 1, "one dev warning");
  assert.ok(warnings[0].includes("Veyra") && warnings[0].includes("Bell Tower"), "warning names both");
  deactivateSlideOver(regA);
  assert.equal(activeSlideOver(), regB, "stale deactivate is ignored");

  // An opener outside the old panel (shortcut, page button) keeps its own target.
  const regC = { name: "Shortcut", returnTarget: "page-button", supersede: () => {}, contains: () => false };
  activateSlideOver(regC, null);
  assert.equal(regC.returnTarget, "page-button", "opener on the page is not overwritten");
  assert.equal(warnings.length, 1, "no warning without a warn sink (prod)");
  // No opener captured (focus on body) -> inherit.
  const regD = { name: "D", returnTarget: null, supersede: () => {} };
  activateSlideOver(regD, null);
  assert.equal(regD.returnTarget, "page-button", "no opener -> inherit");
  deactivateSlideOver(regD);
  assert.equal(activeSlideOver(), null, "closing clears the registry");

  // reduced-motion CSS
  const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
  const start = css.indexOf("@media (prefers-reduced-motion: reduce)");
  assert.ok(start >= 0, "reduced-motion block exists");
  const end = css.indexOf("\n}", start);
  assert.ok(end > start, "reduced-motion block is closed");
  const block = css.slice(start, end);
  for (const rule of [
    "animation-duration: 0.01ms !important",
    "animation-delay: 0s !important",
    "animation-iteration-count: 1 !important",
    "transition-duration: 0.01ms !important",
    "transition-delay: 0s !important",
  ]) {
    assert.ok(block.includes(rule), `reduced-motion rule: ${rule}`);
  }

  // layers: top-only Esc
  const calls = [];
  assert.equal(layerCount(), 0, "starts empty");
  assert.equal(listeners.size, 0, "listener is lazy");
  const removeA = pushLayer(() => calls.push("A"));
  const removeB = pushLayer(() => calls.push("B"));
  assert.equal(layerCount(), 2, "two layers");
  assert.equal(listeners.size, 1, "one document listener");

  const esc = keydown();
  assert.deepEqual(calls, ["B"], "only the top layer runs");
  assert.ok(esc.defaultPrevented, "handled Esc is prevented");

  keydown({ isComposing: true });
  keydown({ keyCode: 229 });
  keydown({ defaultPrevented: true });
  keydown({ key: "Enter" });
  keydown({ repeat: true });
  assert.deepEqual(calls, ["B"], "IME / defaultPrevented / other keys / auto-repeat ignored");

  removeB();
  removeB(); // idempotent
  assert.equal(layerCount(), 1, "remove is idempotent");
  keydown();
  assert.deepEqual(calls, ["B", "A"], "after removal, next layer is top");

  assert.equal(closeTopLayer(), true, "closeTopLayer reports a layer");
  assert.deepEqual(calls, ["B", "A", "A"], "closeTopLayer runs top handler");
  removeA();
  assert.equal(layerCount(), 0, "empty again");
  assert.equal(listeners.size, 0, "listener removed when empty");
  assert.equal(closeTopLayer(), false, "closeTopLayer with no layers");
} catch (err) {
  console.error(`check-focus-trap: FAIL ${err.message}`);
  process.exit(1);
}

console.log("check-focus-trap: ok");
