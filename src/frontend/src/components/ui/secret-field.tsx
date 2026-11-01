import * as React from "react"
import { Lock } from "lucide-react"

import { cn } from "@/lib/utils"
import { usePreview } from "@/contexts/PreviewContext"

// Wraps a GM-only field inside a Party record: dashed gm border, 6% gm wash
// and a lock label ("GM notes · GM only"). Its accessible name starts with
// "GM only" so screen-reader users hear the visibility first.
//
// Not rendering for Players (or in preview) is cosmetic. A Player's API
// response must never contain the field in the first place (AD-13).

export interface SecretFieldProps {
  /** The field's label, e.g. "GM notes". */
  label: React.ReactNode
  /** id of the wrapped input, so the label also names it. */
  htmlFor?: string
  audience?: "gm" | "player"
  className?: string
  children: React.ReactNode
}

function SecretField({ label, htmlFor, audience = "gm", className, children }: SecretFieldProps) {
  const { active } = usePreview()
  const labelId = React.useId()
  if (active || audience === "player") return null

  const Label = htmlFor ? "label" : "span"
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className={cn("rounded-lg border border-dashed border-gm/50 bg-gm/6 p-3", className)}
    >
      <div className="mb-2 flex items-center gap-1.5 text-sm font-medium text-foreground">
        <Lock aria-hidden="true" className="size-3.5 shrink-0 text-gm" />
        <Label id={labelId} htmlFor={htmlFor}>
          <span className="sr-only">GM only: </span>
          {label}
          <span aria-hidden="true" className="text-gm">
            {" "}
            · GM only
          </span>
        </Label>
      </div>
      {children}
    </div>
  )
}

export { SecretField }
