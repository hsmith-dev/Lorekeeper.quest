import { CircleAlert } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { apiErrorMessage } from "@/utils/apiError"

export interface InlineErrorProps {
  /** A request error (the backend's `detail` is shown) or a ready message. */
  error: unknown
  /** When given, a "Retry" button calls it. */
  onRetry?: () => void
  /** Message used when the error carries no `detail`. */
  fallback?: string
  className?: string
}

/** One-line request error with an optional Retry. Owns no form state, so the
 *  surrounding form keeps whatever the user typed. */
export function InlineError({ error, onRetry, fallback, className }: InlineErrorProps) {
  const resolved: unknown = typeof error === "string" && error ? error : apiErrorMessage(error, fallback)
  // FastAPI 422s carry `detail` as an array of objects; never render that.
  const message =
    typeof resolved === "string" && resolved ? resolved : apiErrorMessage(undefined, fallback)
  return (
    <div
      role="alert"
      className={cn("flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-danger", className)}
    >
      <span className="flex min-w-0 items-start gap-2">
        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 break-words">{message}</span>
      </span>
      {onRetry && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-11 text-foreground md:h-9"
          onClick={() => onRetry()}
        >
          Retry
        </Button>
      )}
    </div>
  )
}
