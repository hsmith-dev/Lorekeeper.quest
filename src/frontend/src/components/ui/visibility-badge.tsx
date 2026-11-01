import * as React from "react"
import { Check, ChevronDown, Eye, Lock, UserRound, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { pushLayer } from "@/lib/layers"
import { usePreview } from "@/contexts/PreviewContext"

// Visibility pill: Eye "Party", Lock "GM only" or UserRound "Private". For a
// GM with `editable` it is a menu button (WAI-ARIA menu button with
// menuitemradio items). Widening to Party asks first: "Players will see this.
// Make visible?". Narrowing applies at once.
//
// Players never see the badge, except "Private" / "Shared" on their own
// journal entries. While "Preview as Player" is on, the GM sees the Player
// rendering. This is cosmetic: hiding data is the server's job (AD-13).

export type Visibility = "party" | "gm" | "private"

interface Look {
  label: string
  icon: LucideIcon
  className: string
}

const PARTY_LOOK = "border-border bg-transparent text-muted-foreground"
const GM_LOOK = "border-gm/40 bg-gm/14 text-gm"
const PRIVATE_LOOK = "border-info/40 bg-info/14 text-info"

const LOOKS: Record<Visibility, Look> = {
  party: { label: "Party", icon: Eye, className: PARTY_LOOK },
  gm: { label: "GM only", icon: Lock, className: GM_LOOK },
  private: { label: "Private", icon: UserRound, className: PRIVATE_LOOK },
}
const SHARED_LOOK: Look = { label: "Shared", icon: Eye, className: PARTY_LOOK }

const PILL =
  "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold [&_svg]:size-3.5 [&_svg]:shrink-0"
const FOCUS_RING =
  "ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"

export interface VisibilityBadgeProps {
  value: Visibility
  /** GM only: render as a menu button that can change the visibility. */
  editable?: boolean
  onChange?: (value: Visibility) => void
  /** Offer "Private" in the menu (it is still listed when it is the current value). */
  allowPrivate?: boolean
  /** Who is looking. Forced to "player" while preview is active. */
  audience?: "gm" | "player"
  /** Player's own journal entry: show "Private" or "Shared". */
  ownJournal?: boolean
  /** Own journal only: the private entry is shared with the party. */
  shared?: boolean
  className?: string
}

/** Menu options: Party and GM only, plus Private when allowed or current. */
function visibilityOptions(value: Visibility, allowPrivate: boolean): Visibility[] {
  return allowPrivate || value === "private" ? ["party", "gm", "private"] : ["party", "gm"]
}

/** What picking `next` does: nothing, ask first (widening to Party), or apply. */
function visibilityChoice(current: Visibility, next: Visibility): "noop" | "confirm" | "apply" {
  if (next === current) return "noop"
  return next === "party" ? "confirm" : "apply"
}

function Pill({ look, className }: { look: Look; className?: string }) {
  const Icon = look.icon
  return (
    <span className={cn(PILL, look.className, className)}>
      <Icon aria-hidden="true" />
      {look.label}
    </span>
  )
}

function VisibilityBadge({
  value,
  editable = false,
  onChange,
  allowPrivate = false,
  audience = "gm",
  ownJournal = false,
  shared = false,
  className,
}: VisibilityBadgeProps) {
  const { active: previewActive } = usePreview()
  const viewer = previewActive ? "player" : audience

  if (viewer === "player") {
    if (!ownJournal) return null
    const look = shared || value === "party" ? SHARED_LOOK : LOOKS.private
    return <Pill look={look} className={className} />
  }

  // Without onChange the menu's choices could do nothing: show the plain pill.
  if (!editable || !onChange) return <Pill look={LOOKS[value]} className={className} />

  return (
    <EditableVisibilityBadge
      value={value}
      onChange={onChange}
      allowPrivate={allowPrivate}
      className={className}
    />
  )
}

function EditableVisibilityBadge({
  value,
  onChange,
  allowPrivate,
  className,
}: {
  value: Visibility
  onChange: (value: Visibility) => void
  allowPrivate: boolean
  className?: string
}) {
  const [open, setOpen] = React.useState(false)
  const [confirming, setConfirming] = React.useState(false)
  const [activeIndex, setActiveIndex] = React.useState(0)

  const wrapperRef = React.useRef<HTMLSpanElement>(null)
  const triggerRef = React.useRef<HTMLButtonElement>(null)
  const itemRefs = React.useRef<(HTMLButtonElement | null)[]>([])
  const cancelRef = React.useRef<HTMLButtonElement>(null)

  const menuId = React.useId()
  const confirmTextId = React.useId()

  const options = visibilityOptions(value, allowPrivate)
  const look = LOOKS[value]
  const Icon = look.icon

  const focusTrigger = () => triggerRef.current?.focus()

  const openMenu = (index?: number) => {
    const checked = options.indexOf(value)
    setConfirming(false)
    setActiveIndex(index ?? (checked >= 0 ? checked : 0))
    setOpen(true)
  }

  const closeMenu = (returnFocus: boolean) => {
    setOpen(false)
    if (returnFocus) focusTrigger()
  }

  const cancelConfirm = () => {
    setConfirming(false)
    focusTrigger()
  }

  const choose = (next: Visibility) => {
    setOpen(false)
    const decision = visibilityChoice(value, next)
    if (decision === "confirm") {
      // Focus goes to Cancel, the safe choice.
      setConfirming(true)
      return
    }
    if (decision === "apply") onChange(next)
    focusTrigger()
  }

  const confirmParty = () => {
    setConfirming(false)
    onChange("party")
    focusTrigger()
  }

  // A change from outside makes an open menu or confirmation stale.
  React.useEffect(() => {
    setOpen(false)
    setConfirming(false)
  }, [value])

  // Focus follows the active menu item.
  React.useEffect(() => {
    if (open) itemRefs.current[activeIndex]?.focus()
  }, [open, activeIndex])

  React.useEffect(() => {
    if (confirming) cancelRef.current?.focus()
  }, [confirming])

  // Esc closes the menu, or cancels the confirmation, and returns focus to the
  // badge. Registered as a layer so an enclosing SlideOver stays open.
  React.useEffect(() => {
    if (!open) return
    // closeMenu only touches state setters and refs, so [open] is enough.
    return pushLayer(() => closeMenu(true))
  }, [open])

  React.useEffect(() => {
    if (!confirming) return
    return pushLayer(cancelConfirm)
  }, [confirming])

  // A click outside closes the menu, or drops the confirmation, without
  // moving focus. Focus leaving the wrapper does the same (onBlur below).
  React.useEffect(() => {
    if (!open && !confirming) return
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setOpen(false)
        setConfirming(false)
      }
    }
    document.addEventListener("pointerdown", onPointerDown)
    return () => document.removeEventListener("pointerdown", onPointerDown)
  }, [open, confirming])

  const onWrapperBlur = (event: React.FocusEvent<HTMLSpanElement>) => {
    const next = event.relatedTarget as Node | null
    if (next && !event.currentTarget.contains(next)) {
      setOpen(false)
      setConfirming(false)
    }
  }

  const onTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault()
      openMenu()
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      openMenu(options.length - 1)
    }
  }

  const onMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const n = options.length
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault()
        setActiveIndex((i) => (i + 1) % n)
        break
      case "ArrowUp":
        event.preventDefault()
        setActiveIndex((i) => (i - 1 + n) % n)
        break
      case "Home":
        event.preventDefault()
        setActiveIndex(0)
        break
      case "End":
        event.preventDefault()
        setActiveIndex(n - 1)
        break
      case "Tab":
        // Focus the badge first so the browser's own Tab moves on from it.
        focusTrigger()
        setOpen(false)
        break
      // Enter and Space activate the focused item through its click.
    }
  }

  return (
    <span ref={wrapperRef} onBlur={onWrapperBlur} className={cn("relative inline-flex flex-wrap items-center gap-2", className)}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`Visibility: ${look.label}`}
        onClick={() => (open ? closeMenu(false) : openMenu())}
        onKeyDown={onTriggerKeyDown}
        className={cn(PILL, look.className, FOCUS_RING, "cursor-pointer hover:brightness-110")}
      >
        <Icon aria-hidden="true" />
        {look.label}
        <ChevronDown aria-hidden="true" />
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Visibility"
          onKeyDown={onMenuKeyDown}
          className="absolute left-0 top-full z-50 mt-1 min-w-40 rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-xl"
        >
          {options.map((option, index) => {
            const optionLook = LOOKS[option]
            const OptionIcon = optionLook.icon
            const checked = option === value
            return (
              <button
                key={option}
                ref={(el) => {
                  itemRefs.current[index] = el
                }}
                type="button"
                role="menuitemradio"
                aria-checked={checked}
                tabIndex={-1}
                onClick={() => choose(option)}
                onMouseMove={() => index !== activeIndex && setActiveIndex(index)}
                className={cn(
                  "flex min-h-9 w-full items-center gap-2 rounded-sm px-2 text-left text-sm",
                  "focus:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  "[&_svg]:size-4 [&_svg]:shrink-0"
                )}
              >
                <OptionIcon aria-hidden="true" className="text-muted-foreground" />
                <span className="flex-1">{optionLook.label}</span>
                {checked ? <Check aria-hidden="true" /> : null}
              </button>
            )
          })}
        </div>
      )}

      {confirming && (
        <span role="group" aria-labelledby={confirmTextId} className="inline-flex flex-wrap items-center gap-2 text-xs">
          <span id={confirmTextId} className="text-foreground">
            Players will see this. Make visible?
          </span>
          <button
            type="button"
            onClick={confirmParty}
            className={cn(
              "inline-flex h-7 items-center rounded-md bg-primary px-2.5 font-medium text-primary-foreground hover:bg-primary/90",
              FOCUS_RING
            )}
          >
            Make visible
          </button>
          <button
            ref={cancelRef}
            type="button"
            onClick={cancelConfirm}
            className={cn(
              "inline-flex h-7 items-center rounded-md border border-input bg-background px-2.5 font-medium hover:bg-accent hover:text-accent-foreground",
              FOCUS_RING
            )}
          >
            Cancel
          </button>
        </span>
      )}
    </span>
  )
}

export { VisibilityBadge, visibilityChoice, visibilityOptions }
