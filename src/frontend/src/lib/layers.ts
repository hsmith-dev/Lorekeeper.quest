// Global Esc layer stack. Each open overlay registers one handler; Esc runs
// only the topmost. One document keydown listener, attached lazily while any
// layer exists. No runtime imports (loadable by Node type stripping).

type EscapeHandler = () => void;

interface Layer {
  onEscape: EscapeHandler;
}

const stack: Layer[] = [];
let listening = false;

function onKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape" && event.key !== "Esc") return;
  // An inner widget (combobox, menu) already consumed it, or an IME is composing.
  if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return;
  // Holding Esc must not unwind every pushed level and then close.
  if (event.repeat) return;
  if (stack.length === 0) return;
  event.preventDefault();
  closeTopLayer();
}

function syncListener(): void {
  if (typeof document === "undefined") return;
  if (stack.length > 0 && !listening) {
    document.addEventListener("keydown", onKeyDown);
    listening = true;
  } else if (stack.length === 0 && listening) {
    document.removeEventListener("keydown", onKeyDown);
    listening = false;
  }
}

/** Register a layer on top of the stack. Returns an idempotent remover. */
export function pushLayer(onEscape: EscapeHandler): () => void {
  const layer: Layer = { onEscape };
  stack.push(layer);
  syncListener();
  let removed = false;
  return () => {
    if (removed) return;
    removed = true;
    const i = stack.indexOf(layer);
    if (i >= 0) stack.splice(i, 1);
    syncListener();
  };
}

/** Run the top layer's Esc handler. Returns false when no layer is open. */
export function closeTopLayer(): boolean {
  const top = stack[stack.length - 1];
  if (!top) return false;
  top.onEscape();
  return true;
}

export function layerCount(): number {
  return stack.length;
}
