import { useQuery } from "@tanstack/react-query"
import { TriangleAlert } from "lucide-react"
import { Link } from "react-router-dom"

import { cn } from "@/lib/utils"
import { getMe } from "@/services/api"

export interface ModelMissingNoticeProps {
  /** Lower-case model description, e.g. "speech model". */
  model: string
  /** The feature that needs it, e.g. "Live captions". */
  feature: string
  /** Download size shown to admins, e.g. "~1.5 GB". */
  sizeLabel?: string
  /** false when the model server can't be reached (rather than not installed). */
  reachable?: boolean
  className?: string
}

/** Existing install flow: Admin → System → Model Library. */
export const MODEL_LIBRARY_HREF = "/admin?tab=system"

/** "This feature needs a model that isn't there." Admins get a link to the
 *  Model Library; everyone else is told to ask their admin. */
export function ModelMissingNotice({
  model,
  feature,
  sizeLabel,
  reachable = true,
  className,
}: ModelMissingNoticeProps) {
  const { data: profile } = useQuery({
    queryKey: ["me"],
    queryFn: () => getMe().then((r) => r.data),
    staleTime: 60_000,
  })
  // While the profile loads (or if it fails) treat the viewer as non-admin.
  const isAdmin = profile?.is_admin ?? false

  const adminLink = (
    <Link
      to={MODEL_LIBRARY_HREF}
      className="rounded-sm font-medium underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      Admin › Models
    </Link>
  )

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/14 p-4 text-sm text-foreground",
        className,
      )}
    >
      <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
      <div className="min-w-0 space-y-1">
        <p className="font-semibold">{feature} is unavailable</p>
        <p>
          {reachable ? `The ${model} isn't installed.` : `The ${model} isn't reachable.`}{" "}
          {isAdmin ? (
            reachable ? (
              <>
                An admin can add it in {adminLink}
                {sizeLabel ? ` (${sizeLabel})` : ""}.
              </>
            ) : (
              <>An admin can check it in {adminLink}.</>
            )
          ) : (
            "Ask your admin."
          )}
        </p>
      </div>
    </div>
  )
}
