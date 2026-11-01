import { Compass } from "lucide-react";
import { Link } from "react-router-dom";

import { usePageTitle } from "@/components/shell/RouteAnnouncer";
import { RouteLoading } from "@/components/shell/RouteLoading";
import { Button } from "@/components/ui/button";
import { isLoggedIn, useNavAudience, useRoleSettling } from "@/hooks/useNavAudience";
import { NOT_FOUND_MESSAGE, NOT_FOUND_TITLE, isRouteRegistered, type NavAudience } from "@/lib/routes";

// The one not-found page (E0-UX.8). Unknown URLs, role-gated routes and API
// 404s all render this, with the same copy, title and announcement, so a Player
// opening a GM URL can't tell "hidden" from "missing".

/** Where "home" is: / logged out, Portal for Players once registered, else Dashboard. */
export function notFoundHome(loggedIn: boolean, audience: NavAudience): { to: string; label: string } {
  if (!loggedIn) return { to: "/", label: "Go to the home page" };
  if (audience === "player" && isRouteRegistered("/portal")) return { to: "/portal", label: "Go to your Portal" };
  return { to: "/dashboard", label: "Go to your Journal" };
}

/** Render inside a page on a 404, or for a route the user can't open. */
export function NotFound() {
  usePageTitle(NOT_FOUND_TITLE);
  const audience = useNavAudience();
  const home = notFoundHome(isLoggedIn(), audience);
  return (
    <div className="max-w-2xl mx-auto w-full px-4 py-10 md:py-16">
      <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border px-4 py-16 text-center">
        <Compass className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-2xl font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
          {NOT_FOUND_TITLE}
        </h1>
        <p className="max-w-prose text-sm text-muted-foreground">{NOT_FOUND_MESSAGE}</p>
        <Button asChild className="h-11">
          <Link to={home.to}>{home.label}</Link>
        </Button>
      </div>
    </div>
  );
}

/** The `*` route. Waits like a gated route does, so timing gives nothing away. */
export function NotFoundPage() {
  if (useRoleSettling()) return <RouteLoading />;
  return <NotFound />;
}
