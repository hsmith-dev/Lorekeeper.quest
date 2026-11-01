import { useCallback, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";

import { SlideOver } from "@/components/SlideOver";
import { usePreview } from "@/contexts/PreviewContext";
import { findRoute } from "@/lib/routes";
import {
  getShortcutsVersion,
  groupShortcuts,
  listShortcuts,
  setSingleKeyShortcutsEnabled,
  singleKeyShortcutsEnabled,
  subscribeShortcuts,
  suspendShortcuts,
  useShortcut,
  type ShortcutGroup,
} from "@/lib/shortcuts";
import { activeSlideOver } from "@/lib/slideOverRegistry";

// The keyboard shortcut help (E0-UX.9). "?" anywhere, or "Keyboard shortcuts"
// in the profile menu, opens it. It lists exactly what is registered right now
// (lib/shortcuts.ts), grouped by scope, and holds the WCAG 2.1.4 switch for
// single-key shortcuts.
//
// It is one SlideOver: when another SlideOver is open the help is pushed into
// it as a level ("← Back to …"), so the user's panel is not closed and Esc
// goes back to it. Otherwise it opens its own SlideOver. While it is showing,
// every other shortcut is suspended.

export const SHORTCUT_HELP_TITLE = "Keyboard shortcuts";

let openHelp: (() => void) | null = null;
// Mounted ShortcutHelpContent instances: > 0 means the help is already showing
// (standalone or pushed into a host SlideOver).
let mountedHelp = 0;

/** Push the help into the active SlideOver as a level. False when none is open (or it can't push). */
export function pushHelpIntoActiveSlideOver(): boolean {
  const host = activeSlideOver();
  if (!host?.push) return false;
  host.push({ title: SHORTCUT_HELP_TITLE, render: () => <ShortcutHelpContent /> });
  return true;
}

/** Open the help (from the profile menu, or anything else). No-op before <ShortcutHelp /> mounts. */
export function openShortcutHelp(): void {
  openHelp?.();
}

export interface ShortcutListProps {
  groups: ShortcutGroup[];
  previewing: boolean;
  /** Single-key shortcuts are on. */
  enabled: boolean;
  onToggle: () => void;
}

/** The help's content: the single-key switch, then one section per scope. */
export function ShortcutList({ groups, previewing, enabled, onToggle }: ShortcutListProps) {
  const id = useId();
  const switchLabelId = `${id}-switch`;
  const switchHintId = `${id}-hint`;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 rounded-md border border-border p-3">
        <div className="min-w-0">
          <p id={switchLabelId} className="text-sm font-medium text-foreground">
            Single-key shortcuts
          </p>
          <p id={switchHintId} className="text-xs text-muted-foreground">
            Shortcuts without Ctrl or ⌘, such as ?. Turn them off if they get in the way of speech input or
            other assistive technology. You can still open this list from the profile menu.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-labelledby={switchLabelId}
          aria-describedby={switchHintId}
          onClick={onToggle}
          className="group inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-md ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <span
            aria-hidden="true"
            className={`flex h-6 w-11 items-center rounded-full border border-border p-0.5 transition-colors ${
              enabled ? "bg-primary" : "bg-muted"
            }`}
          >
            <span
              className={`size-[1.125rem] rounded-full bg-background shadow transition-transform ${
                enabled ? "translate-x-5" : "translate-x-0"
              }`}
            />
          </span>
        </button>
      </div>

      {groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">No keyboard shortcuts on this page.</p>
      ) : (
        groups.map((group, gi) => {
          const headingId = `${id}-group-${gi}`;
          return (
            <section key={group.scope} aria-labelledby={headingId}>
              <h3
                id={headingId}
                className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground"
              >
                {group.label}
              </h3>
              <dl className="divide-y divide-border rounded-md border border-border">
                {group.items.map((item) => (
                  <div key={item.id} className="flex items-start gap-4 px-3 py-2.5">
                    <dt className="flex w-24 shrink-0 flex-wrap items-center gap-1">
                      {item.parsed.label.map((cap, ci) => (
                        <kbd
                          key={ci}
                          className="inline-flex min-w-7 items-center justify-center rounded border border-border bg-muted px-1.5 py-0.5 font-mono-tabular text-foreground"
                        >
                          {cap}
                        </kbd>
                      ))}
                    </dt>
                    <dd className="min-w-0 flex-1 text-sm text-foreground">
                      {item.description}
                      {previewing && item.write && (
                        <span className="block text-xs text-muted-foreground">Not available in preview</span>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          );
        })
      )}
    </div>
  );
}

/** The live help: reads the registry, suspends other shortcuts while mounted. */
function ShortcutHelpContent() {
  useEffect(() => {
    mountedHelp += 1;
    const resume = suspendShortcuts();
    return () => {
      mountedHelp -= 1;
      resume();
    };
  }, []);
  const version = useSyncExternalStore(subscribeShortcuts, getShortcutsVersion, getShortcutsVersion);
  const { pathname } = useLocation();
  const { active: previewing } = usePreview();
  const pageTitle = findRoute(pathname)?.title;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const groups = useMemo(() => groupShortcuts(listShortcuts(), pageTitle), [version, pageTitle]);
  const enabled = singleKeyShortcutsEnabled();

  return (
    <ShortcutList
      groups={groups}
      previewing={previewing}
      enabled={enabled}
      onToggle={() => setSingleKeyShortcutsEnabled(!enabled)}
    />
  );
}

/** Mount once, inside the router (App.tsx). Registers "?" and owns the standalone SlideOver. */
export function ShortcutHelp() {
  const [open, setOpen] = useState(false);
  const openRef = useRef(false);
  openRef.current = open;

  const show = useCallback(() => {
    if (openRef.current || mountedHelp > 0) return;
    if (pushHelpIntoActiveSlideOver()) return;
    openRef.current = true;
    setOpen(true);
  }, []);

  useEffect(() => {
    openHelp = show;
    return () => {
      if (openHelp === show) openHelp = null;
    };
  }, [show]);

  useShortcut("?", { scope: "global", description: "Show keyboard shortcuts", overLayers: true }, show);

  // Mounted only while open: a SlideOver that stays mounted while closed is
  // still `visibility: hidden` on the frame it opens, so its initial focus()
  // would fail silently and focus would stay on the page behind it.
  if (!open) return null;
  return (
    <SlideOver open onClose={() => setOpen(false)} title={SHORTCUT_HELP_TITLE} name={SHORTCUT_HELP_TITLE}>
      <ShortcutHelpContent />
    </SlideOver>
  );
}
