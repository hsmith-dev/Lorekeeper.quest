import * as React from "react"
import { WifiOff } from "lucide-react"

import { cn } from "@/lib/utils"

function subscribe(onChange: () => void) {
  window.addEventListener("online", onChange)
  window.addEventListener("offline", onChange)
  return () => {
    window.removeEventListener("online", onChange)
    window.removeEventListener("offline", onChange)
  }
}

const getOnline = () => navigator.onLine
const getServerOnline = () => true

/** true while the browser reports a network connection. */
export function useOnlineStatus(): boolean {
  return React.useSyncExternalStore(subscribe, getOnline, getServerOnline)
}

/** "You're offline — changes are paused", shown only while offline. */
export function OfflineNotice({ className }: { className?: string }) {
  const online = useOnlineStatus()
  if (online) return null
  return (
    <div
      role="status"
      className={cn(
        "flex items-center gap-2 rounded-lg border border-warning/40 bg-warning/14 px-3 py-2 text-sm text-foreground",
        className,
      )}
    >
      <WifiOff className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
      <span>You're offline — changes are paused</span>
    </div>
  )
}
