import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

// WAI-ARIA radio group: one tab stop (roving tabindex), arrows move focus
// and selection together, disabled options are skipped.

const segmentedControlVariants = cva(
  "inline-flex items-stretch gap-1 rounded-md border border-border bg-background p-1",
  {
    variants: {
      size: {
        default: "",
        table: "gap-1.5 p-1.5",
      },
    },
    defaultVariants: {
      size: "default",
    },
  }
)

const segmentedItemVariants = cva(
  "inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-sm px-3 text-sm ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      size: {
        default: "",
        table: "min-h-14 px-4 text-base [&_svg]:size-5",
      },
      selected: {
        true: "bg-muted text-foreground font-medium",
        false: "text-muted-foreground hover:text-foreground hover:bg-muted/60",
      },
    },
    defaultVariants: {
      size: "default",
      selected: false,
    },
  }
)

export interface SegmentedControlOption<T extends string> {
  value: T
  label: React.ReactNode
  icon?: LucideIcon
  disabled?: boolean
}

type SegmentedLabelling =
  | { "aria-label": string; "aria-labelledby"?: string }
  | { "aria-label"?: string; "aria-labelledby": string }

export type SegmentedControlProps<T extends string> = SegmentedLabelling &
  VariantProps<typeof segmentedControlVariants> & {
    options: readonly SegmentedControlOption<T>[]
    value: T | null | undefined
    onValueChange: (value: T) => void
    className?: string
    id?: string
  }

function SegmentedControl<T extends string>({
  options,
  value,
  onValueChange,
  size,
  className,
  id,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
}: SegmentedControlProps<T>) {
  const itemRefs = React.useRef<(HTMLButtonElement | null)[]>([])

  const selectedIndex = options.findIndex((o) => o.value === value)
  const firstEnabled = options.findIndex((o) => !o.disabled)
  const tabStopIndex =
    selectedIndex >= 0 && !options[selectedIndex].disabled
      ? selectedIndex
      : firstEnabled

  const select = (index: number) => {
    const option = options[index]
    if (!option || option.disabled) return
    itemRefs.current[index]?.focus()
    if (option.value !== value) onValueChange(option.value)
  }

  // Find the next enabled index from `start` stepping by `step`, wrapping.
  const step = (start: number, delta: 1 | -1): number => {
    const n = options.length
    for (let i = 1; i <= n; i++) {
      const idx = (((start + delta * i) % n) + n) % n
      if (!options[idx].disabled) return idx
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
      case "ArrowDown":
        target = step(index, 1)
        break
      case "ArrowLeft":
      case "ArrowUp":
        target = step(index, -1)
        break
      case "Home":
        target = firstEnabled
        break
      case "End": {
        for (let i = options.length - 1; i >= 0; i--) {
          if (!options[i].disabled) {
            target = i
            break
          }
        }
        break
      }
      default:
        return
    }
    event.preventDefault()
    if (target !== null && target >= 0) select(target)
  }

  return (
    <div
      role="radiogroup"
      id={id}
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      className={cn(segmentedControlVariants({ size }), className)}
    >
      {options.map((option, index) => {
        const isSelected = index === selectedIndex
        const Icon = option.icon
        return (
          <button
            key={option.value}
            ref={(el) => {
              itemRefs.current[index] = el
            }}
            type="button"
            role="radio"
            aria-checked={isSelected}
            disabled={option.disabled}
            tabIndex={index === tabStopIndex ? 0 : -1}
            onClick={() => select(index)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            className={segmentedItemVariants({ size, selected: isSelected })}
          >
            {Icon ? <Icon aria-hidden="true" /> : null}
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

export { SegmentedControl, segmentedControlVariants, segmentedItemVariants }
