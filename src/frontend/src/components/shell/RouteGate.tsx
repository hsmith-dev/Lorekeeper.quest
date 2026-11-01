import { Suspense, useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useCampaigns } from "@/hooks/useCampaigns";
import { isLoggedIn, useNavAudience } from "@/hooks/useNavAudience";
import { NOT_FOUND_TITLE, canView, redirectTarget, type PageRoute } from "@/lib/routes";
import { NotFound } from "@/pages/NotFoundPage";
import { setRouteTitle } from "./RouteAnnouncer";

// Rendering one registry route (E0-UX.8): login check, role gate, the route's
// default title and the lazy-chunk fallback. Gating is cosmetic (AD-13): it
// only stops the shell rendering a page the server would refuse anyway, and it
// looks exactly like a missing page so "hidden" can't be told from "missing".

// Shown only while a lazy page's chunk is downloading. RouteAnnouncer waits
// for `data-route-loading` to go before it announces and moves focus.
export function RouteLoading() {
  return (
    <div data-route-loading="" className="flex-1 flex items-center justify-center py-24 text-sm text-muted-foreground">
      Loading…
    </div>
  );
}

export function RoutePage({ route }: { route: PageRoute }) {
  const audience = useNavAudience();
  const loggedIn = isLoggedIn();
  const isPrivate = route.auth !== "public";
  const visible = canView(route, audience);
  // A route some audience can't open waits for the first campaign list, so a
  // Player's hard load of a GM URL never fetches the page chunk. A failed list
  // stops waiting (no campaign: no gating, see navAudience).
  const campaignsPending = useCampaigns({ enabled: loggedIn }).isPending && loggedIn;
  const holding = campaignsPending && !route.roles.includes("player");
  // A gated route takes the not-found title, never its own.
  const title = visible ? route.title : NOT_FOUND_TITLE;

  useEffect(() => {
    // While holding, no title yet: the route's own would hint that it exists.
    if ((isPrivate && !loggedIn) || holding) return;
    setRouteTitle(title);
    return () => setRouteTitle(null);
  }, [title, isPrivate, loggedIn, holding]);

  if (isPrivate && !loggedIn) return <Navigate to="/login" replace />;
  if (holding) return <RouteLoading />;
  // The page component is never rendered, so its chunk is never loaded.
  if (!visible) return <NotFound />;
  const Page = route.page;
  return (
    <Suspense fallback={<RouteLoading />}>
      <Page />
    </Suspense>
  );
}

/** A legacy URL: replace it with `to`, keeping the query string and hash. */
export function LegacyRedirect({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate replace to={redirectTarget(to, location.search, location.hash)} />;
}
