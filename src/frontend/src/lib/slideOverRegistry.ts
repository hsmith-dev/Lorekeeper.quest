// One-open-at-a-time registry for SlideOver. Pages render their own
// <SlideOver>, so "replace, not stack" is enforced here: the newest open
// instance wins, the previous one is superseded (told to close; it renders
// nothing). The newcomer inherits the previous return-focus target, because
// its own opener lived inside the panel that just vanished.
// No runtime imports (loadable by Node type stripping).

/** A level pushed into the active SlideOver (see SlideOverPushOptions). */
export interface SlideOverPushRequest {
  title: string;
  render: () => unknown;
  backLabel?: string;
}

export interface Registration<T = unknown> {
  name: string;
  returnTarget: T | null;
  supersede: () => void;
  /** True when `target` is inside this SlideOver's panel. */
  contains?: (target: unknown) => boolean;
  /** Push a level into this SlideOver (e.g. the shortcut help), so nothing closes. */
  push?: (options: SlideOverPushRequest) => void;
}

let active: Registration | null = null;

/**
 * Make `reg` the active SlideOver. If another one is active it is superseded,
 * `reg` takes over its return target when its own opener is inside the old
 * panel (or missing), and `warn` is called with a message
 * naming both. Returns the superseded registration, or null.
 */
export function activateSlideOver<T>(
  reg: Registration<T>,
  warn: ((message: string) => void) | null,
): Registration | null {
  const prev = active;
  if (prev && prev !== reg) {
    warn?.(
      `SlideOver "${reg.name}" opened while SlideOver "${prev.name}" was open; closing "${prev.name}". Only one SlideOver may be open at a time.`,
    );
    // Inherit only when the newcomer's opener vanishes with the old panel
    // (or there is none); an opener on the page keeps its own target.
    if (reg.returnTarget == null || prev.contains?.(reg.returnTarget)) {
      reg.returnTarget = prev.returnTarget as T | null;
    }
    active = reg;
    prev.supersede();
    return prev;
  }
  active = reg;
  return null;
}

/** Clear `reg` if it is still the active SlideOver. */
export function deactivateSlideOver(reg: Registration): void {
  if (active === reg) active = null;
}

export function activeSlideOver(): Registration | null {
  return active;
}
