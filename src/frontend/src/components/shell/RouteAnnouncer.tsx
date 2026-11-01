import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";

import { setTitleBadge } from "@/components/ui/toast";
import { formatDocumentTitle } from "@/lib/routes";

// Route announcements (E0-UX.8, NFR-10). On every route change the document
// title follows the page, a polite live region reads the title out, and focus
// moves to the page's h1 so screen-reader and keyboard users start at the top
// of the new page instead of on a link that no longer exists.
//
// Titles come from a tiny external store with two slots: the route default
// (set by RoutePage from the registry) and a stack of page overrides
// (usePageTitle, incl. NotFound). React runs child effects before parent
// effects, so a single slot would let the route default overwrite the page's
// own title; with two slots the override wins whatever order effects run in.

export interface PageTitle {
  title: string;
  detail?: string;
}

interface Override extends PageTitle {
  id: number;
}

let routeDefault: PageTitle | null = null;
const overrides: Override[] = [];
let nextId = 1;
let snapshot: PageTitle | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  const top = overrides[overrides.length - 1];
  const next: PageTitle | null = top ? { title: top.title, detail: top.detail } : routeDefault;
  if (next?.title !== snapshot?.title || next?.detail !== snapshot?.detail) snapshot = next;
  for (const l of listeners) l();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The effective title: the newest page override, else the route default. */
export function getPageTitle(): PageTitle | null {
  return snapshot;
}

/** Set (or with null, clear) the route's default title. */
export function setRouteTitle(title: string | null, detail?: string): void {
  routeDefault = title === null ? null : { title, detail };
  emit();
}

/** Push a page override; returns an idempotent remover. */
export function pushTitleOverride(title: string, detail?: string): () => void {
  const entry: Override = { id: nextId++, title, detail };
  overrides.push(entry);
  emit();
  return () => {
    const i = overrides.findIndex((o) => o.id === entry.id);
    if (i === -1) return;
    overrides.splice(i, 1);
    emit();
  };
}

/** For checks: drop every title. */
export function resetPageTitles(): void {
  routeDefault = null;
  overrides.length = 0;
  emit();
}

/**
 * A page's own title, beating the route default while the page is mounted.
 * `detail` (e.g. "214 entities") is announced, not put in document.title.
 */
export function usePageTitle(title: string, detail?: string): void {
  useEffect(() => pushTitleOverride(title, detail), [title, detail]);
}

/** "World" or "World, 214 entities". */
export function announcementText(title: string, detail?: string): string {
  return detail ? `${title}, ${detail}` : title;
}

const BADGE = /^\((\d+)\) /;

/** Write "{title} · Lorekeeper", keeping any "(n) " badge already there. */
export function applyDocumentTitle(title: string): void {
  if (typeof document === "undefined") return;
  const badge = BADGE.exec(document.title);
  document.title = formatDocumentTitle(title);
  setTitleBadge(badge ? Number(badge[1]) : 0);
}

const SETTLE_MS = 150;
const LOADING_SELECTOR = "[data-route-loading]";

/** Focus the page's first h1 (made focusable), else <main>. */
function focusPageHeading(): void {
  const main = document.querySelector("main");
  if (!main) return;
  const active = document.activeElement;
  // Something inside the page already took focus (e.g. an autofocus input).
  if (active && active !== document.body && active !== main && main.contains(active)) return;
  const h1 = main.querySelector("h1");
  const target: HTMLElement = h1 ?? main;
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

/** Visually hidden polite live region, title tracking and focus on route change. */
export function RouteAnnouncer() {
  const location = useLocation();
  const current = useSyncExternalStore(subscribe, getPageTitle, getPageTitle);
  const [message, setMessage] = useState("");

  // The first load (incl. a redirect right after it) is not announced.
  const settledOnce = useRef(false);
  const pending = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The document title always tracks the effective title.
  useEffect(() => {
    if (current) applyDocumentTitle(current.title);
  }, [current]);

  // The pathname last settled on. A query/hash-only change (filters,
  // setSearchParams) is not a new page: no announcement, focus stays put.
  const settledPath = useRef<string | null>(null);
  const pathname = useRef(location.pathname);
  pathname.current = location.pathname;

  // A navigation to another path after the first load starts a pending announcement.
  useEffect(() => {
    if (!settledOnce.current) return; // still the first load (e.g. a redirect)
    if (location.pathname === settledPath.current) return;
    pending.current = true;
    setMessage(""); // clear first so the same title is announced again
  }, [location.pathname]);

  // Wait for the title to settle (and a lazy page to load), then announce.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const settle = () => {
      if (document.querySelector(LOADING_SELECTOR)) {
        timer.current = setTimeout(settle, SETTLE_MS);
        return;
      }
      timer.current = null;
      if (!settledOnce.current) {
        settledOnce.current = true;
        settledPath.current = pathname.current;
        return;
      }
      if (!pending.current) return;
      pending.current = false;
      settledPath.current = pathname.current;
      const title = getPageTitle();
      if (title) setMessage(announcementText(title.title, title.detail));
      focusPageHeading();
    };
    timer.current = setTimeout(settle, SETTLE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [location.pathname, current]);

  return (
    <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </div>
  );
}
