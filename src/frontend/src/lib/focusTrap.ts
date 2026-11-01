// Focus-trap helpers for modal surfaces (SlideOver). No runtime imports, so
// Node's type stripping can load this file directly (scripts/check-focus-trap.mjs).

export const FOCUSABLE_SELECTOR = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])",
  "textarea:not([disabled])",
  "iframe",
  "summary",
  "audio[controls]",
  "video[controls]",
  '[contenteditable]:not([contenteditable="false"])',
  "[tabindex]",
].join(",");

/** Minimal shapes so the helpers can be exercised with fake elements in Node. */
export interface FocusableLike {
  tabIndex: number;
  hidden?: boolean;
  focus(options?: FocusOptions): void;
  getClientRects(): { length: number };
}

export interface ContainerLike {
  querySelectorAll(selector: string): ArrayLike<FocusableLike> & Iterable<FocusableLike>;
}

export interface TabKeyEventLike {
  key: string;
  shiftKey: boolean;
  preventDefault(): void;
}

/**
 * Tabbable descendants of `container`, in DOM order. Re-queried on every call
 * so content that appears or disappears while the trap is active is respected.
 * Drops negative tabIndex, `hidden`, and anything without client rects
 * (display:none ancestors, detached nodes).
 */
export function getFocusable<T extends FocusableLike>(container: { querySelectorAll(selector: string): ArrayLike<T> & Iterable<T> }): T[] {
  return Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
    (el) => el.tabIndex >= 0 && !el.hidden && el.getClientRects().length > 0,
  );
}

/**
 * Index to move to on Tab. `current` is -1 when focus is outside the list.
 * Returns -1 when there is nothing to focus.
 */
export function nextFocusIndex(count: number, current: number, shift: boolean): number {
  if (count <= 0) return -1;
  if (current < 0 || current >= count) return shift ? count - 1 : 0;
  return shift ? (current - 1 + count) % count : (current + 1) % count;
}

/**
 * Handle a Tab keydown inside a trap. Always prevents the default move and
 * focuses the computed target (or `fallback` when the container has no
 * focusables). Returns the element focused, or null if the key wasn't Tab.
 */
export function handleTabKey(
  container: ContainerLike,
  event: TabKeyEventLike,
  active: unknown,
  fallback: FocusableLike | null,
): FocusableLike | null {
  if (event.key !== "Tab") return null;
  event.preventDefault();
  const items = getFocusable(container);
  const current = items.indexOf(active as FocusableLike);
  const next = nextFocusIndex(items.length, current, event.shiftKey);
  const target = next < 0 ? fallback : items[next];
  target?.focus();
  return target ?? null;
}

/** Focus the first focusable in `content`, else the heading (tabIndex=-1). */
export function focusInitial(content: ContainerLike | null, heading: FocusableLike | null): void {
  const first = content ? getFocusable(content)[0] : undefined;
  (first ?? heading)?.focus();
}

/**
 * Return focus to `el` if it is still in the document; otherwise focus `main`
 * (giving it tabindex=-1 if it has none). No `main` → no-op.
 */
export function restoreFocus(el: HTMLElement | null | undefined): void {
  if (el && el.isConnected) {
    el.focus();
    // focus() fails silently on hidden/disabled/inert elements.
    if (typeof document === "undefined" || document.activeElement === el) return;
  }
  if (typeof document === "undefined") return;
  const main = document.querySelector("main");
  if (!main) return;
  if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
  main.focus();
}
