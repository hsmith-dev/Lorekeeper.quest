import { useEffect, useRef } from "react";

import { toast } from "@/components/ui/toast";
import { PREVIEW_READ_ONLY_TITLE } from "@/contexts/PreviewContext";
import { layerCount } from "./layers";
import { isPreviewActive } from "./preview";

// Keyboard shortcut registry (E0-UX.9). One shared append point for every
// epic: a component calls useShortcut(key, { scope, description }, handler),
// the help overlay (components/shell/ShortcutHelp.tsx, opened with "?") lists
// what is registered right now, grouped by scope.
//
// Guards, in the order dispatchShortcut applies them:
// - never while typing (input, textarea, select, contenteditable) or during
//   IME composition, and never inside a typeahead widget (menu, listbox, grid…);
// - never Esc: the layer stack (lib/layers.ts) owns it;
// - a plain or Shift+ key never fires while Ctrl, Meta or Alt is held;
// - Space never fires while focus is on an interactive element;
// - a shortcut goes quiet while a layer opened after it registered is open,
//   unless it was registered with overLayers;
// - while the help is open (suspendShortcuts) nothing registered before it fires;
// - WCAG 2.1.4: single-key shortcuts can be switched off per device;
// - `write` shortcuts show "Preview is read-only" instead of running in preview.
//
// One lazy document keydown listener, attached while anything is registered.

export type ShortcutScope = "global" | "page" | (string & {});

export interface ParsedShortcut {
  /** The KeyboardEvent.key to match; letters lower case, Space is " ". */
  key: string;
  shift: boolean;
  /** Mod: ⌘ on Apple platforms, Ctrl elsewhere. Only Mod+Enter is allowed. */
  mod: boolean;
  /** True for a key with no Mod (WCAG 2.1.4 "single-key" shortcut). */
  single: boolean;
  /** Key caps for display, e.g. ["Shift", "A"] or ["⌘", "Enter"]. */
  label: string[];
}

export interface ShortcutOptions {
  scope: ShortcutScope;
  description: string;
  /** Writes data: blocked (with a toast) while "Preview as Player" is on. */
  write?: boolean;
  /** Keep firing while a layer (SlideOver, menu) opened after it is open. */
  overLayers?: boolean;
  /** Fire on auto-repeat while the key is held. */
  allowRepeat?: boolean;
}

export interface ShortcutRegistration extends ShortcutOptions {
  key: string;
  handler: (event: KeyboardEvent) => void;
}

export interface ShortcutEntry extends ShortcutOptions {
  id: number;
  key: string;
  parsed: ParsedShortcut;
}

export interface ShortcutGroup {
  scope: string;
  label: string;
  items: ShortcutEntry[];
}

export const SHORTCUTS_STORAGE_KEY = "lk_shortcuts";
export const PREVIEW_BLOCKED_TEXT = PREVIEW_READ_ONLY_TITLE;

// ---------------------------------------------------------------------------
// Key grammar

const RESERVED = new Map<string, string>(
  [
    "Escape",
    "Esc",
    "Tab",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "Up",
    "Down",
    "Left",
    "Right",
    "Home",
    "End",
    "PageUp",
    "PageDown",
    "Backspace",
    "Delete",
    "Del",
    ...Array.from({ length: 12 }, (_, i) => `F${i + 1}`),
  ].map((k) => [k.toLowerCase(), k]),
);

function isApplePlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  const platform = nav.userAgentData?.platform || nav.platform || nav.userAgent || "";
  return /mac|iphone|ipad|ipod/i.test(platform);
}

function refuse(key: string, why: string): never {
  throw new Error(`useShortcut: "${key}" is not allowed (${why}).`);
}

/** Parse a shortcut such as "?", "j", "Shift+A", "Space" or "Mod+Enter". Throws on reserved keys. */
export function parseShortcut(key: string): ParsedShortcut {
  if (typeof key !== "string" || key.length === 0) refuse(String(key), "empty key");

  // "+" alone, or "...++" (a modifier then the plus key).
  let base: string;
  let mods: string[];
  if (key === "+") {
    base = "+";
    mods = [];
  } else if (key.endsWith("++")) {
    base = "+";
    mods = key.slice(0, -2).split("+");
  } else {
    const parts = key.split("+");
    base = parts[parts.length - 1];
    mods = parts.slice(0, -1);
  }
  if (base === "") refuse(key, "missing key");

  let shift = false;
  let mod = false;
  for (const m of mods) {
    const lower = m.toLowerCase();
    if (lower === "shift") {
      if (shift) refuse(key, "Shift twice");
      shift = true;
    } else if (lower === "mod") {
      if (mod) refuse(key, "Mod twice");
      mod = true;
    } else if (lower === "alt" || lower === "option" || lower === "opt") {
      refuse(key, "Alt combinations belong to the browser and assistive technology");
    } else if (["ctrl", "control", "meta", "cmd", "command", "super", "win"].includes(lower)) {
      refuse(key, `use Mod instead of ${m}; only Mod+Enter is registrable`);
    } else {
      refuse(key, `unknown modifier "${m}"`);
    }
  }

  const reserved = RESERVED.get(base.toLowerCase());
  if (reserved) {
    refuse(
      key,
      reserved === "Escape" || reserved === "Esc"
        ? "Escape is owned by the layer stack (lib/layers.ts)"
        : `${reserved} is a browser or screen-reader key`,
    );
  }

  const isMac = isApplePlatform();
  const modLabel = isMac ? "⌘" : "Ctrl";

  if (base.toLowerCase() === "enter") {
    if (!mod || shift) refuse(key, mod ? "only Mod+Enter is registrable" : "plain Enter activates the focused control");
    return { key: "Enter", shift: false, mod: true, single: false, label: [modLabel, "Enter"] };
  }
  if (mod) refuse(key, "Mod combinations other than Mod+Enter belong to the browser");

  let k: string;
  let cap: string;
  if (base.toLowerCase() === "space" || base === " ") {
    k = " ";
    cap = "Space";
  } else if ([...base].length === 1) {
    k = base;
    cap = base;
  } else {
    refuse(key, `unknown key "${base}"`);
  }

  const isLetter = k.toLowerCase() !== k.toUpperCase();
  if (isLetter) {
    if (!shift && k !== k.toLowerCase()) refuse(key, `write "Shift+${k}" for an upper-case letter`);
    k = k.toLowerCase();
    cap = k.toUpperCase();
  } else if (shift) {
    // "?" already implies Shift on most layouts; register the produced character.
    refuse(key, "Shift+ is only for letters; register the character it produces instead");
  }

  return {
    key: k,
    shift,
    mod: false,
    single: true,
    label: shift ? ["Shift", cap] : [cap],
  };
}

type KeyLike = Pick<KeyboardEvent, "key" | "shiftKey" | "ctrlKey" | "metaKey" | "altKey">;

/** True when `event` is the key combination `parsed` describes. */
export function matchesShortcut(parsed: ParsedShortcut, event: KeyLike): boolean {
  if (event.altKey) return false;
  if (parsed.mod) {
    const isMac = isApplePlatform();
    const modHeld = isMac ? event.metaKey : event.ctrlKey;
    const otherHeld = isMac ? event.ctrlKey : event.metaKey;
    return event.key === "Enter" && modHeld && !otherHeld && !event.shiftKey;
  }
  if (event.ctrlKey || event.metaKey) return false;
  const key = event.key === "Spacebar" ? " " : event.key;
  if (typeof key !== "string") return false;
  const isLetter = parsed.key.toLowerCase() !== parsed.key.toUpperCase();
  if (isLetter) {
    // Caps Lock gives "J" without Shift: still "j".
    return key.toLowerCase() === parsed.key && event.shiftKey === parsed.shift;
  }
  return key === parsed.key;
}

// ---------------------------------------------------------------------------
// Focus targets

interface ElementLike {
  tagName?: string;
  isContentEditable?: boolean;
  getAttribute?: (name: string) => string | null;
  hasAttribute?: (name: string) => boolean;
  parentElement?: ElementLike | null;
}

const TYPING_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);
const TYPING_ROLES = new Set(["textbox", "searchbox", "combobox", "spinbutton"]);
const INTERACTIVE_TAGS = new Set(["BUTTON", "INPUT", "TEXTAREA", "SELECT", "SUMMARY", "OPTION"]);
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
  "slider",
  "treeitem",
  "gridcell",
  ...TYPING_ROLES,
]);
// Composite widgets with their own typeahead: every printable key is theirs.
const TYPEAHEAD_ROLES = new Set(["menu", "menubar", "listbox", "tree", "treegrid", "grid"]);

const attr = (el: ElementLike, name: string) => el.getAttribute?.(name) ?? null;
const tag = (el: ElementLike) => (el.tagName ?? "").toUpperCase();

function ancestors(el: ElementLike | null | undefined): ElementLike[] {
  const out: ElementLike[] = [];
  for (let n = el ?? null; n && out.length < 200; n = n.parentElement ?? null) out.push(n);
  return out;
}

function editable(el: ElementLike): boolean {
  if (el.isContentEditable) return true;
  const ce = attr(el, "contenteditable");
  return ce !== null && ce.toLowerCase() !== "false";
}

/** Focus is somewhere text goes: input, textarea, select, a textbox role or contenteditable. */
export function isTypingTarget(el: ElementLike | null | undefined): boolean {
  if (!el) return false;
  if (TYPING_TAGS.has(tag(el))) return true;
  const role = attr(el, "role");
  if (role && TYPING_ROLES.has(role)) return true;
  return ancestors(el).some(editable);
}

/** Focus is on something Space activates or scrolls: a control, a link, or a tab stop. */
export function isInteractiveTarget(el: ElementLike | null | undefined): boolean {
  if (!el) return false;
  if (isTypingTarget(el)) return true;
  const t = tag(el);
  if (INTERACTIVE_TAGS.has(t)) return true;
  if ((t === "A" || t === "AREA") && attr(el, "href") !== null) return true;
  const role = attr(el, "role");
  if (role && INTERACTIVE_ROLES.has(role)) return true;
  const tabIndex = attr(el, "tabindex");
  return tabIndex !== null && Number(tabIndex) >= 0;
}

function inTypeaheadWidget(el: ElementLike | null | undefined): boolean {
  return ancestors(el).some((n) => {
    const role = attr(n, "role");
    return role !== null && TYPEAHEAD_ROLES.has(role);
  });
}

// ---------------------------------------------------------------------------
// Registry

interface InternalEntry extends ShortcutEntry {
  handler: (event: KeyboardEvent) => void;
  /** layerCount() when registered: a higher count now means a layer is above. */
  layers: number;
  /** Suspension depth when registered. */
  suspendDepth: number;
}

const entries: InternalEntry[] = [];
const listeners = new Set<() => void>();
let nextId = 1;
let version = 0;
let suspendDepth = 0;
let listening = false;
// undefined = storage not read yet.
let singleKeyCache: boolean | undefined;

function notify(): void {
  version += 1;
  for (const listener of [...listeners]) listener();
}

function onDocumentKeyDown(event: KeyboardEvent): void {
  dispatchShortcut(event, typeof document === "undefined" ? null : document.activeElement);
}

function syncListener(): void {
  if (typeof document === "undefined") return;
  if (entries.length > 0 && !listening) {
    document.addEventListener("keydown", onDocumentKeyDown);
    listening = true;
  } else if (entries.length === 0 && listening) {
    document.removeEventListener("keydown", onDocumentKeyDown);
    listening = false;
  }
}

/** Register a shortcut. Throws on a reserved key. Returns an idempotent remover. */
export function registerShortcut(reg: ShortcutRegistration): () => void {
  const parsed = parseShortcut(reg.key);
  const entry: InternalEntry = {
    id: nextId++,
    key: reg.key,
    parsed,
    scope: reg.scope,
    description: reg.description,
    write: reg.write === true,
    overLayers: reg.overLayers === true,
    allowRepeat: reg.allowRepeat === true,
    handler: reg.handler,
    layers: layerCount(),
    suspendDepth,
  };
  entries.push(entry);
  syncListener();
  notify();
  let removed = false;
  return () => {
    if (removed) return;
    removed = true;
    const i = entries.indexOf(entry);
    if (i >= 0) entries.splice(i, 1);
    syncListener();
    notify();
  };
}

type DispatchEvent = KeyLike &
  Pick<KeyboardEvent, "repeat" | "isComposing" | "keyCode" | "defaultPrevented" | "preventDefault">;

/**
 * Run the newest registered shortcut that `event` matches and every guard
 * allows. Calls preventDefault and returns true when one fired (or was
 * blocked by preview with a toast).
 */
export function dispatchShortcut(event: DispatchEvent, activeElement: ElementLike | null | undefined): boolean {
  if (entries.length === 0) return false;
  if (event.defaultPrevented) return false;
  if (event.isComposing || event.keyCode === 229) return false;
  if (event.key === "Escape" || event.key === "Esc") return false;
  if (isTypingTarget(activeElement)) return false;
  if (inTypeaheadWidget(activeElement)) return false;

  const layers = layerCount();
  const singleOn = singleKeyShortcutsEnabled();
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    if (!matchesShortcut(entry.parsed, event)) continue;
    if (event.repeat && !entry.allowRepeat) continue;
    if (suspendDepth > entry.suspendDepth) continue;
    if (layers > entry.layers && !entry.overLayers) continue;
    if (entry.parsed.single && !singleOn) continue;
    if (entry.parsed.key === " " && isInteractiveTarget(activeElement)) continue;

    event.preventDefault();
    if (entry.write && isPreviewActive()) {
      toast({ text: PREVIEW_BLOCKED_TEXT });
      return true;
    }
    entry.handler(event as KeyboardEvent);
    return true;
  }
  return false;
}

/** The registered (and so enabled) shortcuts, oldest first. */
export function listShortcuts(): ShortcutEntry[] {
  return entries.map(({ id, key, parsed, scope, description, write, overLayers, allowRepeat }) => ({
    id,
    key,
    parsed,
    scope,
    description,
    write,
    overLayers,
    allowRepeat,
  }));
}

/** "Global" first, then "page" (labelled `pageTitle`), then other scopes in first-registered order. */
export function groupShortcuts(list: readonly ShortcutEntry[], pageTitle?: string | null): ShortcutGroup[] {
  const byScope = new Map<string, ShortcutEntry[]>();
  for (const entry of list) {
    const items = byScope.get(entry.scope);
    if (items) items.push(entry);
    else byScope.set(entry.scope, [entry]);
  }
  const label = (scope: string) =>
    scope === "global" ? "Global" : scope === "page" ? pageTitle || "This page" : scope;
  const order = [...byScope.keys()].sort((a, b) => rank(a) - rank(b));
  return order.map((scope) => ({ scope, label: label(scope), items: byScope.get(scope)! }));
}

function rank(scope: string): number {
  return scope === "global" ? 0 : scope === "page" ? 1 : 2;
}

export function subscribeShortcuts(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getShortcutsVersion(): number {
  return version;
}

// ---------------------------------------------------------------------------
// Single-key switch (WCAG 2.1.4) and suspension

function localStore(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function singleKeyShortcutsEnabled(): boolean {
  if (singleKeyCache === undefined) {
    try {
      singleKeyCache = localStore()?.getItem(SHORTCUTS_STORAGE_KEY) !== "off";
    } catch {
      singleKeyCache = true;
    }
  }
  return singleKeyCache;
}

export function setSingleKeyShortcutsEnabled(enabled: boolean): void {
  singleKeyCache = enabled;
  try {
    const s = localStore();
    if (enabled) s?.removeItem(SHORTCUTS_STORAGE_KEY);
    else s?.setItem(SHORTCUTS_STORAGE_KEY, "off");
  } catch {
    // In memory only for this page load.
  }
  notify();
}

/** Forget the cached switch so the next read goes to storage (tests, other tabs). */
export function resetShortcutSettingsCache(): void {
  singleKeyCache = undefined;
}

/** Silence every shortcut registered so far (the help is open). Returns an idempotent resume. */
export function suspendShortcuts(): () => void {
  suspendDepth += 1;
  notify();
  let resumed = false;
  return () => {
    if (resumed) return;
    resumed = true;
    suspendDepth -= 1;
    notify();
  };
}

// ---------------------------------------------------------------------------
// Hook

export interface UseShortcutOptions extends ShortcutOptions {
  /** false: not registered (does not fire, not listed). */
  enabled?: boolean;
}

/**
 * Register `key` while the component is mounted and `enabled !== false`.
 * The key is parsed during render, so a reserved key throws right away.
 */
export function useShortcut(
  key: string,
  { scope, description, enabled = true, write = false, overLayers = false, allowRepeat = false }: UseShortcutOptions,
  handler: (event: KeyboardEvent) => void,
): void {
  parseShortcut(key);
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    if (!enabled) return;
    return registerShortcut({
      key,
      scope,
      description,
      write,
      overLayers,
      allowRepeat,
      handler: (event) => handlerRef.current(event),
    });
  }, [key, scope, description, enabled, write, overLayers, allowRepeat]);
}
