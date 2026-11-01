import * as React from "react"
import { cva } from "class-variance-authority"
import { Check, Plus } from "lucide-react"

import { Input } from "@/components/ui/input"
import { useDebounce } from "@/hooks/useDebounce"
import { cn } from "@/lib/utils"

// WAI-ARIA combobox with list autocomplete. DOM focus stays on the input;
// the active option is conveyed through aria-activedescendant. Options are
// loaded asynchronously (debounced 150 ms) and stale responses are dropped.

const DEBOUNCE_MS = 150

const comboboxOptionVariants = cva(
  "flex min-h-11 w-full cursor-pointer select-none items-center gap-2 rounded-sm px-3 py-2 text-sm md:min-h-0 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      active: {
        true: "bg-muted text-foreground",
        false: "text-popover-foreground hover:bg-muted/60",
      },
      selected: {
        true: "font-medium",
        false: "",
      },
    },
    defaultVariants: {
      active: false,
      selected: false,
    },
  }
)

export interface ComboboxOption {
  value: string
  label: string
}

type ComboboxLabelling =
  | { "aria-label": string; "aria-labelledby"?: string }
  | { "aria-label"?: string; "aria-labelledby": string }

export type ComboboxProps<T extends ComboboxOption> = ComboboxLabelling & {
  loadOptions: (query: string) => Promise<T[]>
  value: T | null
  onChange: (option: T) => void
  onCreate?: (query: string) => void
  createLabel?: (query: string) => React.ReactNode
  placeholder?: string
  id?: string
  disabled?: boolean
  className?: string
}

type Item<T> = { kind: "option"; option: T } | { kind: "create"; query: string }

type LoadStatus = "idle" | "loading" | "ready" | "error"

function defaultCreateLabel(query: string): React.ReactNode {
  return `Create “${query}”…`
}

function Combobox<T extends ComboboxOption>({
  loadOptions,
  value,
  onChange,
  onCreate,
  createLabel = defaultCreateLabel,
  placeholder,
  id,
  disabled,
  className,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
}: ComboboxProps<T>) {
  const baseId = React.useId()
  const inputId = id ?? `${baseId}-input`
  const listboxId = `${baseId}-listbox`
  const optionId = (i: number) => `${baseId}-option-${i}`

  const [inputText, setInputText] = React.useState(value?.label ?? "")
  // The text the user has typed since the list last opened; "" lists everything.
  const [query, setQuery] = React.useState("")
  const [open, setOpen] = React.useState(false)
  const [options, setOptions] = React.useState<T[]>([])
  const [status, setStatus] = React.useState<LoadStatus>("idle")
  const [activeIndex, setActiveIndex] = React.useState(-1)

  const debouncedQuery = useDebounce(query, DEBOUNCE_MS)
  const loadOptionsRef = React.useRef(loadOptions)
  loadOptionsRef.current = loadOptions
  const requestIdRef = React.useRef(0)
  const pendingActiveRef = React.useRef<"first" | "last" | null>(null)

  // Keep the visible text in step with the selected option.
  React.useEffect(() => {
    setInputText(value?.label ?? "")
    setQuery("")
  }, [value?.value, value?.label])

  const trimmedQuery = query.trim()
  const showCreate =
    !!onCreate &&
    status === "ready" &&
    trimmedQuery.length > 0 &&
    !options.some(
      (o) => o.label.trim().toLowerCase() === trimmedQuery.toLowerCase()
    )

  const items: Item<T>[] = React.useMemo(() => {
    const list: Item<T>[] = options.map((option) => ({ kind: "option", option }))
    if (showCreate) list.push({ kind: "create", query: trimmedQuery })
    return list
  }, [options, showCreate, trimmedQuery])

  const applyPendingActive = React.useCallback((count: number) => {
    const pending = pendingActiveRef.current
    if (!pending) return
    pendingActiveRef.current = null
    if (count > 0) setActiveIndex(pending === "first" ? 0 : count - 1)
  }, [])

  // Load options whenever the list is open and the debounced query settles.
  React.useEffect(() => {
    if (!open) return
    // Wait for the debounce to settle so each keystroke doesn't fire a load.
    if (query !== debouncedQuery) return
    const requestId = ++requestIdRef.current
    setStatus("loading")
    loadOptionsRef.current(debouncedQuery).then(
      (result) => {
        if (requestId !== requestIdRef.current) return
        setOptions(result)
        setStatus("ready")
        setActiveIndex(-1)
      },
      () => {
        if (requestId !== requestIdRef.current) return
        setOptions([])
        setStatus("error")
        setActiveIndex(-1)
      }
    )
  }, [open, query, debouncedQuery])

  // Once fresh results (and the create row) are in, honour an arrow-key open.
  React.useEffect(() => {
    if (status === "ready" || status === "error") applyPendingActive(items.length)
  }, [status, items.length, applyPendingActive])

  // Keep the active option visible while arrowing through a long list.
  React.useEffect(() => {
    if (!open || activeIndex < 0) return
    const el = document.getElementById(optionId(activeIndex))
    el?.scrollIntoView?.({ block: "nearest" })
    // optionId is derived from a stable useId value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, activeIndex])

  const close = () => {
    requestIdRef.current++ // drop any in-flight response
    pendingActiveRef.current = null
    setOpen(false)
    setActiveIndex(-1)
    setOptions([])
    setStatus("idle")
  }

  const revert = () => {
    setInputText(value?.label ?? "")
    setQuery("")
  }

  const choose = (item: Item<T>) => {
    if (item.kind === "option") {
      onChange(item.option)
      setInputText(item.option.label)
      setQuery("")
    } else {
      onCreate?.(item.query)
      revert()
    }
    close()
  }

  const openWith = (pending: "first" | "last") => {
    pendingActiveRef.current = pending
    if (!open) {
      setOpen(true)
    } else {
      applyPendingActive(items.length)
    }
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault()
        if (!open) {
          openWith("first")
        } else if (items.length > 0) {
          setActiveIndex((i) => (i + 1) % items.length)
        }
        return
      case "ArrowUp":
        event.preventDefault()
        if (!open) {
          openWith("last")
        } else if (items.length > 0) {
          setActiveIndex((i) => (i <= 0 ? items.length - 1 : i - 1))
        }
        return
      case "Enter":
        if (!open) return
        // Never let Enter submit a surrounding form while the list is open.
        event.preventDefault()
        if (activeIndex >= 0 && activeIndex < items.length) {
          choose(items[activeIndex])
        }
        return
      case "Escape":
        if (open) {
          event.preventDefault()
          close()
        }
        return
      default:
        return
    }
  }

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const text = event.target.value
    setInputText(text)
    setQuery(text)
    setActiveIndex(-1)
    // Results for the previous text are stale: drop them and any in-flight load.
    requestIdRef.current++
    setOptions([])
    setStatus("loading")
    if (!open) setOpen(true)
  }

  const handleBlur = () => {
    if (open) close()
    revert()
  }

  const activeDescendant =
    open && activeIndex >= 0 && activeIndex < items.length
      ? optionId(activeIndex)
      : undefined

  let statusMessage: React.ReactNode = null
  if (open) {
    if (status === "loading" && options.length === 0) {
      statusMessage = <span className="text-muted-foreground">Loading…</span>
    } else if (status === "error") {
      statusMessage = <span className="text-danger">Couldn&rsquo;t load options</span>
    } else if (status === "ready" && options.length === 0) {
      statusMessage = <span className="text-muted-foreground">No matches</span>
    }
  }

  return (
    <div className={cn("relative w-full", className)}>
      <Input
        id={inputId}
        type="text"
        role="combobox"
        autoComplete="off"
        spellCheck={false}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-expanded={open}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={activeDescendant}
        placeholder={placeholder}
        disabled={disabled}
        value={inputText}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        onClick={() => {
          if (!open && !disabled) setOpen(true)
        }}
      />
      {/* Never display:none, so the status live region below stays mounted. */}
      <div
        className={cn(
          "absolute left-0 right-0 top-full z-50 mt-1",
          open &&
            "overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-xl"
        )}
        onMouseDown={(e) => e.preventDefault()}
      >
        <ul
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledBy}
          className={cn(
            "max-h-60 overflow-y-auto p-1",
            (!open || items.length === 0) && "hidden"
          )}
        >
          {open &&
            items.map((item, index) => {
              const isActive = index === activeIndex
              if (item.kind === "create") {
                return (
                  <li
                    key="__create__"
                    id={optionId(index)}
                    role="option"
                    aria-selected={isActive}
                    className={comboboxOptionVariants({ active: isActive })}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => choose(item)}
                  >
                    <Plus aria-hidden="true" />
                    <span className="truncate">{createLabel(item.query)}</span>
                  </li>
                )
              }
              const isSelected = value?.value === item.option.value
              return (
                <li
                  key={item.option.value}
                  id={optionId(index)}
                  role="option"
                  aria-selected={isActive}
                  className={comboboxOptionVariants({
                    active: isActive,
                    selected: isSelected,
                  })}
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => choose(item)}
                >
                  <span className="truncate">{item.option.label}</span>
                  {isSelected ? (
                    <Check aria-hidden="true" className="ml-auto" />
                  ) : null}
                </li>
              )
            })}
        </ul>
        <div
          role="status"
          aria-live="polite"
          className={cn("px-3 py-2 text-sm", !statusMessage && "sr-only")}
        >
          {statusMessage}
        </div>
      </div>
    </div>
  )
}

export { Combobox, comboboxOptionVariants }
