import * as React from "react"
import { cva } from "class-variance-authority"
import { useLocation, useNavigate } from "react-router-dom"

import { cn } from "@/lib/utils"

// WAI-ARIA tabs with manual activation: arrows/Home/End move focus only,
// Enter/Space (or click) activates. In routeMode the active tab follows the
// URL and activation pushes a history entry, so Back returns to the
// previous tab.

const tabsListVariants = cva(
  "flex flex-wrap gap-1.5 border-b border-border pb-3"
)

const tabVariants = cva(
  "inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-md px-3 text-sm ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      active: {
        true: "bg-muted text-foreground font-medium",
        false: "text-muted-foreground hover:text-foreground hover:bg-muted/60",
      },
    },
    defaultVariants: {
      active: false,
    },
  }
)

export interface TabItem {
  value: string
  label: React.ReactNode
  /** Route for routeMode; activation navigates here (push). */
  to?: string
  disabled?: boolean
  /** Panel content; falls back to `children` for the active tab. */
  content?: React.ReactNode
}

type TabsLabelling =
  | { "aria-label": string; "aria-labelledby"?: string }
  | { "aria-label"?: string; "aria-labelledby": string }

export type TabsProps = TabsLabelling & {
  tabs: readonly TabItem[]
  value?: string
  defaultValue?: string
  onValueChange?: (value: string) => void
  routeMode?: boolean
  /** Rendered inside the active panel when that tab has no `content` (e.g. `<Outlet />`). */
  children?: React.ReactNode
  className?: string
  panelClassName?: string
}

function normalisePath(path: string): string {
  return path.length > 1 ? path.replace(/\/+$/, "") : path
}

/** Longest `to` that equals the pathname or is a `/`-boundary prefix of it. */
function matchRouteTab(
  tabs: readonly TabItem[],
  pathname: string
): string | undefined {
  const current = normalisePath(pathname)
  let best: TabItem | undefined
  for (const tab of tabs) {
    if (!tab.to) continue
    const to = normalisePath(tab.to)
    const matches =
      current === to ||
      (to === "/" ? current.startsWith("/") : current.startsWith(`${to}/`))
    if (matches && (!best || to.length > normalisePath(best.to!).length)) {
      best = tab
    }
  }
  return best?.value
}

function Tabs({
  tabs,
  value,
  defaultValue,
  onValueChange,
  routeMode = false,
  children,
  className,
  panelClassName,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
}: TabsProps) {
  const baseId = React.useId()
  const location = useLocation()
  const navigate = useNavigate()
  const tabRefs = React.useRef<(HTMLButtonElement | null)[]>([])

  const [uncontrolled, setUncontrolled] = React.useState<string | undefined>(
    defaultValue
  )

  const routeMatch = routeMode
    ? matchRouteTab(tabs, location.pathname)
    : undefined
  let activeValue: string | undefined
  if (routeMode) {
    activeValue = routeMatch
  } else {
    activeValue = value !== undefined ? value : uncontrolled
  }
  if (!tabs.some((t) => t.value === activeValue)) {
    activeValue = (tabs.find((t) => !t.disabled) ?? tabs[0])?.value
  }

  const activeIndex = tabs.findIndex((t) => t.value === activeValue)

  const tabId = (i: number) => `${baseId}-tab-${i}`
  const panelId = (i: number) => `${baseId}-panel-${i}`

  const activate = (index: number) => {
    const tab = tabs[index]
    if (!tab || tab.disabled) return
    // In routeMode the URL decides the active tab; a tab without `to` can't win.
    if (routeMode && !tab.to) return
    if (routeMode) {
      if (tab.to && normalisePath(tab.to) !== normalisePath(location.pathname)) {
        navigate(tab.to)
      }
    } else if (value === undefined) {
      setUncontrolled(tab.value)
    }
    // In routeMode compare with the URL match, not the no-match fallback.
    const current = routeMode ? routeMatch : activeValue
    if (tab.value !== current) onValueChange?.(tab.value)
  }

  const focusTab = (index: number) => {
    tabRefs.current[index]?.focus()
  }

  const step = (start: number, delta: 1 | -1): number => {
    const n = tabs.length
    for (let i = 1; i <= n; i++) {
      const idx = (((start + delta * i) % n) + n) % n
      if (!tabs[idx].disabled) return idx
    }
    return start
  }

  const handleKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    index: number
  ) => {
    let target: number | null = null
    switch (event.key) {
      case "ArrowRight":
        target = step(index, 1)
        break
      case "ArrowLeft":
        target = step(index, -1)
        break
      case "Home":
        target = tabs.findIndex((t) => !t.disabled)
        break
      case "End":
        for (let i = tabs.length - 1; i >= 0; i--) {
          if (!tabs[i].disabled) {
            target = i
            break
          }
        }
        break
      case "Enter":
      case " ":
        event.preventDefault()
        activate(index)
        return
      default:
        return
    }
    event.preventDefault()
    if (target !== null && target >= 0) focusTab(target)
  }

  // Roving tab stop: the active tab, or the first enabled one.
  const tabStop =
    activeIndex >= 0 && !tabs[activeIndex].disabled
      ? activeIndex
      : tabs.findIndex((t) => !t.disabled)

  return (
    <div className={className}>
      <div
        role="tablist"
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-orientation="horizontal"
        className={tabsListVariants()}
      >
        {tabs.map((tab, index) => {
          const isActive = index === activeIndex
          return (
            <button
              key={tab.value}
              ref={(el) => {
                tabRefs.current[index] = el
              }}
              type="button"
              role="tab"
              id={tabId(index)}
              aria-selected={isActive}
              aria-controls={panelId(index)}
              disabled={tab.disabled}
              tabIndex={index === tabStop ? 0 : -1}
              onClick={() => activate(index)}
              onKeyDown={(e) => handleKeyDown(e, index)}
              className={tabVariants({ active: isActive })}
            >
              {tab.label}
            </button>
          )
        })}
      </div>
      {tabs.map((tab, index) => {
        const isActive = index === activeIndex
        return (
          <div
            key={tab.value}
            role="tabpanel"
            id={panelId(index)}
            aria-labelledby={tabId(index)}
            hidden={!isActive}
            tabIndex={isActive ? 0 : -1}
            className={cn(
              "pt-4 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              panelClassName
            )}
          >
            {isActive ? (tab.content ?? children) : null}
          </div>
        )
      })}
    </div>
  )
}

export { Tabs, tabsListVariants, tabVariants }
