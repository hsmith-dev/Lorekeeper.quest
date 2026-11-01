import * as React from "react"
import { Eye } from "lucide-react"

import { cn } from "@/lib/utils"
import { usePreview } from "@/contexts/PreviewContext"

// Under a focused Party field, tells the GM "Visible to players". The hint is
// always in the DOM (hidden until focus) so aria-describedby on the field
// never points at nothing. GM-only fields use SecretField instead.
// Cosmetic guidance only; visibility is enforced server-side (AD-13).

export interface FieldVisibilityHintProps {
  /** A single field element; it receives aria-describedby. */
  children: React.ReactElement<{ "aria-describedby"?: string }>
  audience?: "gm" | "player"
  className?: string
}

function FieldVisibilityHint({ children, audience = "gm", className }: FieldVisibilityHintProps) {
  const { active } = usePreview()
  const hintId = React.useId()
  const [focused, setFocused] = React.useState(false)

  if (active || audience === "player") return children

  const describedBy = [children.props["aria-describedby"], hintId].filter(Boolean).join(" ")

  return (
    <div
      className={className}
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        const next = event.relatedTarget as Node | null
        if (!next || !event.currentTarget.contains(next)) setFocused(false)
      }}
    >
      {React.cloneElement(children, { "aria-describedby": describedBy })}
      <p
        id={hintId}
        hidden={!focused}
        className={cn("mt-1 items-center gap-1 text-xs text-muted-foreground", focused && "flex")}
      >
        <Eye aria-hidden="true" className="size-3.5 shrink-0" />
        Visible to players
      </p>
    </div>
  )
}

export { FieldVisibilityHint }
