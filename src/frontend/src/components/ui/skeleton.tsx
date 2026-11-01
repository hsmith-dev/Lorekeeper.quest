import * as React from "react"

import { cn } from "@/lib/utils"

/** Placeholder shaped like the content it stands in for (set the shape with
 *  className, e.g. "h-4 w-40"). Hidden from screen readers; pulses only when
 *  the user allows motion. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("rounded-md bg-muted motion-safe:animate-pulse", className)}
      {...props}
    />
  )
}
