import { cn } from "@/lib/utils"

// Campaign role pill beside the campaign name (CampaignSwitcher, E0-UX.7)
// and on Sharing › Members rows (E0-Access.12).
// Purely informational: permissions are enforced server-side.

export type CampaignRole = "gm" | "co_gm" | "player"

const ROLE_LABEL: Record<CampaignRole, string> = {
  gm: "GM",
  co_gm: "Co-GM",
  player: "Player",
}

export interface RoleBadgeProps {
  role: CampaignRole
  /** Overrides the role's label (e.g. "Owner" on the Owner's Members row). */
  label?: string
  className?: string
}

function RoleBadge({ role, label, className }: RoleBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground",
        className
      )}
    >
      {label ?? ROLE_LABEL[role]}
    </span>
  )
}

export { RoleBadge, ROLE_LABEL }
