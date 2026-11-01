import * as React from "react"
import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

export interface EmptyStateProps {
  /** A lucide icon component, rendered at 40px and hidden from screen readers. */
  icon: LucideIcon
  /** One plain sentence saying what will appear here. */
  children: React.ReactNode
  /** At most one action element (usually a Button). */
  action?: React.ReactNode
  className?: string
}

/** "Nothing here yet": dashed panel, one icon, one sentence, one optional action. */
export function EmptyState({ icon: Icon, children, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border px-4 py-16 text-center",
        className,
      )}
    >
      <Icon className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
      <p className="max-w-prose text-sm text-muted-foreground">{children}</p>
      {action && <div>{action}</div>}
    </div>
  )
}
