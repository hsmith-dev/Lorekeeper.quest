import * as React from "react"
import { CircleAlert, Info, Undo2, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

// In-house toast (DESIGN.md / EXPERIENCE.md): a module-level store read with
// useSyncExternalStore, so any module can call toast() and <Toaster /> (mounted
// once in App.tsx) renders it without a provider. Max 3 visible; 6 s info,
// 10 s undo, failures persist; timers pause on hover or focus.

export type ToastKind = "info" | "undo" | "failure"

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface ToastOptions {
  text: string
  kind?: ToastKind
  action?: ToastAction
}

export interface ToastItem {
  id: number
  text: string
  kind: ToastKind
  action?: ToastAction
  /** Milliseconds left before auto-dismiss; null for toasts that persist. */
  remaining: number | null
  paused: boolean
}

export interface ToastAnnouncement {
  text: string
  /** Increments on every toast, so identical text is announced again. */
  key: number
}

export interface ToastState {
  toasts: readonly ToastItem[]
  announcement: ToastAnnouncement | null
}

export const MAX_TOASTS = 3

export const TOAST_DURATIONS: Record<ToastKind, number | null> = {
  info: 6_000,
  undo: 10_000,
  failure: null,
}

let state: ToastState = { toasts: [], announcement: null }
let nextId = 1
const listeners = new Set<() => void>()
const timers = new Map<number, { handle: ReturnType<typeof setTimeout>; startedAt: number }>()

function setState(next: ToastState) {
  state = next
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getToastState(): ToastState {
  return state
}

function clearTimer(id: number) {
  const timer = timers.get(id)
  if (timer) {
    clearTimeout(timer.handle)
    timers.delete(id)
  }
}

function startTimer(id: number, ms: number) {
  clearTimer(id)
  timers.set(id, { handle: setTimeout(() => dismissToast(id), ms), startedAt: Date.now() })
}

/** Show a toast and return its id. */
export function toast({ text, kind = "info", action }: ToastOptions): number {
  const id = nextId++
  const remaining = TOAST_DURATIONS[kind]
  let toasts = [...state.toasts]
  while (toasts.length >= MAX_TOASTS) {
    // Evict the oldest toast that would time out anyway; only when every
    // visible toast is a failure does the oldest failure make way.
    const evictIndex = toasts.findIndex((t) => t.kind !== "failure")
    const [evicted] = toasts.splice(evictIndex === -1 ? 0 : evictIndex, 1)
    clearTimer(evicted.id)
  }
  toasts.push({ id, text, kind, action, remaining, paused: false })
  setState({
    toasts,
    announcement: { text, key: (state.announcement?.key ?? 0) + 1 },
  })
  if (remaining !== null) startTimer(id, remaining)
  return id
}

export function dismissToast(id: number) {
  clearTimer(id)
  if (!state.toasts.some((t) => t.id === id)) return
  setState({ ...state, toasts: state.toasts.filter((t) => t.id !== id) })
}

/** Stop a toast's timer, keeping the time it has left. Idempotent. */
export function pauseToast(id: number) {
  const item = state.toasts.find((t) => t.id === id)
  if (!item || item.paused) return
  let remaining = item.remaining
  const timer = timers.get(id)
  if (timer && remaining !== null) {
    remaining = Math.max(0, remaining - (Date.now() - timer.startedAt))
  }
  clearTimer(id)
  setState({
    ...state,
    toasts: state.toasts.map((t) => (t.id === id ? { ...t, remaining, paused: true } : t)),
  })
}

/** Restart a paused toast's timer with the time it had left. Idempotent. */
export function resumeToast(id: number) {
  const item = state.toasts.find((t) => t.id === id)
  if (!item || !item.paused) return
  setState({
    ...state,
    toasts: state.toasts.map((t) => (t.id === id ? { ...t, paused: false } : t)),
  })
  if (item.remaining !== null) startTimer(id, item.remaining)
}

/** Run a toast's action, then dismiss it even if the action throws. */
export function runToastAction(item: Pick<ToastItem, "id" | "action">) {
  try {
    item.action?.onClick()
  } finally {
    dismissToast(item.id)
  }
}

const BADGE_PREFIX = /^\(\d+\) /

/** Prefix document.title with "(n) "; 0, negative or NaN removes the badge.
 *  Strips any existing badge first, so call it again after a title change. */
export function setTitleBadge(n: number) {
  if (typeof document === "undefined") return
  const count = Number.isFinite(n) && n > 0 ? Math.floor(n) : 0
  const base = document.title.replace(BADGE_PREFIX, "")
  document.title = count > 0 ? `(${count}) ${base}` : base
}

const toastApi = { toast, dismiss: dismissToast, setTitleBadge } as const

export function useToast() {
  return toastApi
}

function useToastState() {
  return React.useSyncExternalStore(subscribe, getToastState, getToastState)
}

const KIND_ICON: Record<ToastKind, { icon: typeof Info; className: string }> = {
  info: { icon: Info, className: "text-muted-foreground" },
  undo: { icon: Undo2, className: "text-muted-foreground" },
  failure: { icon: CircleAlert, className: "text-danger" },
}

function ToastCard({ item }: { item: ToastItem }) {
  const [hovered, setHovered] = React.useState(false)
  const [focused, setFocused] = React.useState(false)
  const hold = hovered || focused

  React.useEffect(() => {
    if (hold) pauseToast(item.id)
    else resumeToast(item.id)
  }, [hold, item.id])

  const { icon: Icon, className: iconClassName } = KIND_ICON[item.kind]

  return (
    <div
      className="pointer-events-auto flex w-full items-start gap-3 rounded-lg border border-border bg-popover p-3 text-sm text-popover-foreground shadow-xl md:w-96"
      // Touch taps fire enter with no leave, so only real pointers hover.
      onPointerEnter={(e) => {
        if (e.pointerType !== "touch") setHovered(true)
      }}
      onPointerLeave={(e) => {
        if (e.pointerType !== "touch") setHovered(false)
      }}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false)
      }}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", iconClassName)} aria-hidden="true" />
      <p className="min-w-0 flex-1 self-center break-words">{item.text}</p>
      {item.action && (
        <Button
          variant="outline"
          size="sm"
          className="h-11 shrink-0 md:h-9"
          onClick={() => runToastAction(item)}
        >
          {item.action.label}
        </Button>
      )}
      <Button
        variant="ghost"
        size="icon"
        className="h-11 w-11 shrink-0 md:h-9 md:w-9"
        aria-label="Dismiss notification"
        onClick={() => dismissToast(item.id)}
      >
        <X aria-hidden="true" />
      </Button>
    </div>
  )
}

/** Mount once (App.tsx). Renders the visible stack and the polite live region. */
export function Toaster() {
  const { toasts, announcement } = useToastState()
  const [spoken, setSpoken] = React.useState("")

  // Clear, then set shortly after, so repeated text is read again. A timeout
  // (not requestAnimationFrame) still fires in background tabs.
  React.useEffect(() => {
    if (!announcement) return
    setSpoken("")
    const timer = setTimeout(() => setSpoken(announcement.text), 50)
    return () => clearTimeout(timer)
  }, [announcement])

  return (
    <>
      {toasts.length > 0 && (
        <section
          aria-label="Notifications"
          className="pointer-events-none fixed inset-x-0 bottom-0 z-[70] flex flex-col items-center gap-2 px-4 pb-4 md:left-auto md:items-end"
        >
          {toasts.map((item) => (
            <ToastCard key={item.id} item={item} />
          ))}
        </section>
      )}
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {spoken}
      </div>
    </>
  )
}
