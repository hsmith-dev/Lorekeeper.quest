import { cn } from "@/lib/utils"

// Campaign role pill beside the campaign name (CampaignSwitcher, E0-UX.7).
// Purely informational: permissions are enforced server-side.

export type CampaignRole = "gm" | "co_gm" | "player"

const ROLE_LABEL: Record<CampaignRole, string> = {
  gm: "GM",
  co_gm: "Co-GM",
  player: "Player",
}

export interface RoleBadgeProps {
  role: CampaignRole
  className?: string
}

function RoleBadge({ role, className }: RoleBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground",
        className
      )}
    >
      {ROLE_LABEL[role]}
    </span>
  )
}

export { RoleBadge, ROLE_LABEL }
