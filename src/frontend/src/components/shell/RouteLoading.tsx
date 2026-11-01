// Shown while a lazy page's chunk downloads, or while the shell waits for the
// campaign list (useRoleSettling). RouteAnnouncer waits for
// `data-route-loading` to go before it announces and moves focus.
export function RouteLoading() {
  return (
    <div data-route-loading="" className="flex-1 flex items-center justify-center py-24 text-sm text-muted-foreground">
      Loading…
    </div>
  );
}
