import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { focusInitial, handleTabKey, restoreFocus } from "../lib/focusTrap";
import { layerCount, pushLayer } from "../lib/layers";
import { activateSlideOver, deactivateSlideOver, type Registration } from "../lib/slideOverRegistry";

export type SlideOverSize = "default" | "wide";

export interface SlideOverPushOptions {
  /** Title shown in the header (and named by aria-labelledby) while this entry is on top. */
  title: string;
  render: () => ReactNode;
  /** Back button text, shown as "← {backLabel}". Defaults to "Back to {previous title}". */
  backLabel?: string;
}

export interface SlideOverApi {
  push: (options: SlideOverPushOptions) => void;
  pop: () => void;
  /** Number of pushed entries above the root content (0 = root). */
  depth: number;
}

const SlideOverContext = createContext<SlideOverApi | null>(null);

/** Push/pop nested panels from inside a SlideOver's content. */
export function useSlideOver(): SlideOverApi {
  const ctx = useContext(SlideOverContext);
  if (!ctx) throw new Error("useSlideOver must be used inside a <SlideOver>");
  return ctx;
}

// One-open-at-a-time: see lib/slideOverRegistry.ts.

let nextEntryKey = 1;

interface StackEntry extends SlideOverPushOptions {
  key: number;
}

interface SavedLevel {
  scrollTop: number;
  focus: Element | null;
}

interface SlideOverProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** "default" = md:max-w-lg, "wide" = md:max-w-3xl. Always full width below md. */
  size?: SlideOverSize;
  /** Name used in the dev warning when another SlideOver replaces this one. Defaults to `title`. */
  name?: string;
}

export function SlideOver({ open, onClose, title, children, size = "default", name }: SlideOverProps) {
  const headingId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const scrollRefs = useRef<(HTMLDivElement | null)[]>([]);
  const savedRef = useRef<SavedLevel[]>([]);
  const pendingFocusRef = useRef<"initial" | "restore" | null>(null);

  const [stack, setStack] = useState<StackEntry[]>([]);
  const [superseded, setSuperseded] = useState(false);

  const depthRef = useRef(0);
  depthRef.current = stack.length;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const push = useCallback((options: SlideOverPushOptions) => {
    const level = depthRef.current;
    const active = document.activeElement;
    savedRef.current[level] = {
      scrollTop: scrollRefs.current[level]?.scrollTop ?? 0,
      focus: active && panelRef.current?.contains(active) ? active : null,
    };
    depthRef.current = level + 1;
    pendingFocusRef.current = "initial";
    setStack((s) => [...s, { ...options, key: nextEntryKey++ }]);
  }, []);

  const pop = useCallback(() => {
    if (depthRef.current === 0) return;
    depthRef.current -= 1;
    pendingFocusRef.current = "restore";
    setStack((s) => s.slice(0, -1));
  }, []);

  // Focus and scroll after a push/pop has rendered.
  useLayoutEffect(() => {
    const mode = pendingFocusRef.current;
    pendingFocusRef.current = null;
    if (!mode) return;
    const level = stack.length;
    const container = scrollRefs.current[level] ?? null;
    if (mode === "initial") {
      if (container) container.scrollTop = 0;
      focusInitial(container, headingRef.current);
      return;
    }
    const saved = savedRef.current[level];
    savedRef.current.length = level;
    const prior = saved?.focus;
    if (prior instanceof HTMLElement && prior.isConnected && panelRef.current?.contains(prior)) {
      prior.focus({ preventScroll: true });
    } else {
      focusInitial(container, headingRef.current);
    }
    if (container && saved) container.scrollTop = saved.scrollTop;
    // Keyed on the top entry, so a pop+push in one handler still refocuses.
  }, [stack.length ? stack[stack.length - 1].key : 0]);

  // Closing drops any pushed entries; a later open starts at the root again.
  useEffect(() => {
    if (open) return;
    setSuperseded(false);
    setStack((s) => (s.length ? [] : s));
    savedRef.current = [];
  }, [open]);

  // While open: registry, Esc layer, Tab trap, initial focus, focus return.
  // Idempotent under StrictMode's double-run (cleanup restores the opener,
  // so the second run captures the same opener again).
  useLayoutEffect(() => {
    if (!open || superseded) return;

    const active = document.activeElement;
    const opener = active instanceof HTMLElement && active !== document.body ? active : null;
    const reg: Registration<HTMLElement> = {
      name: name ?? title,
      returnTarget: opener,
      supersede: () => {},
      contains: (t) => t instanceof Node && !!panelRef.current?.contains(t),
      push: (options) => push(options as SlideOverPushOptions),
    };
    activateSlideOver(reg, import.meta.env.DEV ? (m) => console.warn(m) : null);

    const removeLayer = pushLayer(() => {
      if (depthRef.current > 0) pop();
      else onCloseRef.current();
    });
    const ownLayerCount = layerCount();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || e.defaultPrevented) return;
      const panel = panelRef.current;
      if (!panel) return;
      // A layer opened above this one (e.g. a portaled popover) owns Tab.
      if (layerCount() > ownLayerCount && !panel.contains(document.activeElement)) return;
      handleTabKey(panel, e, document.activeElement, headingRef.current);
    };
    document.addEventListener("keydown", onKeyDown);

    let done = false;
    const deactivate = (restore: boolean) => {
      if (done) return;
      done = true;
      removeLayer();
      document.removeEventListener("keydown", onKeyDown);
      deactivateSlideOver(reg);
      if (restore) restoreFocus(reg.returnTarget);
    };
    reg.supersede = () => {
      deactivate(false);
      setSuperseded(true);
      onCloseRef.current();
    };

    focusInitial(scrollRefs.current[depthRef.current] ?? null, headingRef.current);

    return () => deactivate(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, superseded]);

  const api = useMemo<SlideOverApi>(() => ({ push, pop, depth: stack.length }), [push, pop, stack.length]);

  if (superseded) return null;

  const top = stack[stack.length - 1];
  const currentTitle = top ? top.title : title;
  const backLabel = top
    ? top.backLabel ?? `Back to ${stack.length > 1 ? stack[stack.length - 2].title : title}`
    : null;

  const levels: { key: string | number; render: () => ReactNode }[] = [
    { key: "root", render: () => children },
    ...stack.map((e) => ({ key: e.key, render: e.render })),
  ];
  const topIndex = levels.length - 1;
  const widthClass = size === "wide" ? "md:max-w-3xl" : "md:max-w-lg";

  return (
    <>
      <div
        aria-hidden="true"
        className={`fixed inset-0 z-40 bg-black/40 transition-opacity duration-300 ${open ? "opacity-100" : "opacity-0 pointer-events-none"}`}
        onClick={onClose}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        className={`fixed top-[var(--lk-preview-offset,0px)] bottom-0 right-0 z-50 w-full ${widthClass} bg-background border-l border-border flex flex-col shadow-2xl transition-[transform,visibility] duration-300 ease-in-out ${open ? "translate-x-0 visible" : "translate-x-full invisible"}`}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between px-5 py-4 border-b border-border bg-background shrink-0">
          <div className="min-w-0 flex flex-col items-start gap-1">
            {backLabel && (
              <button
                type="button"
                onClick={pop}
                className="relative tap-target text-sm text-muted-foreground hover:text-foreground rounded-md transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <span aria-hidden="true">←</span> {backLabel}
              </button>
            )}
            <h2
              ref={headingRef}
              id={headingId}
              tabIndex={-1}
              className="max-w-full font-bold text-lg text-foreground truncate pr-4 focus:outline-none"
              style={{ fontFamily: "var(--font-heading)" }}
            >
              {currentTitle}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="relative tap-target p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors shrink-0"
            aria-label="Close"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <SlideOverContext.Provider value={api}>
          {levels.map((level, i) => (
            <div
              key={level.key}
              ref={(el) => {
                scrollRefs.current[i] = el;
              }}
              hidden={i !== topIndex}
              className="flex-1 overflow-y-auto px-5 py-5"
            >
              {level.render()}
            </div>
          ))}
        </SlideOverContext.Provider>
      </div>
    </>
  );
}
