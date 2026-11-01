import { Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "./contexts/ThemeContext";
import { TourProvider } from "./contexts/TourContext";
import { TourOverlay } from "./components/TourOverlay";
import { TutorialWelcomePrompt } from "./components/TutorialWelcomePrompt";
import { NavBar } from "./components/NavBar";
import { ChatWidget } from "./components/ChatWidget";
import { Toaster } from "./components/ui/toast";
import { Footer } from "./components/Footer";
import { PreviewBanner } from "./components/shell/PreviewBanner";
import { RouteAnnouncer } from "./components/shell/RouteAnnouncer";
import { ShortcutHelp } from "./components/shell/ShortcutHelp";
import { LegacyRedirect, RouteLoading, RoutePage } from "./components/shell/RouteGate";
import { CurrentCampaignProvider } from "./hooks/useCurrentCampaign";
import { CampaignEventsSubscriber } from "./hooks/useCampaignEvents";
import { PAGE_ROUTES, activeRedirects } from "./lib/routes";
import { NotFoundPage } from "./pages/NotFoundPage";

// Routes come from the registry in lib/routes.ts (E0-UX.8): a feature epic
// adds a page there with one line, and its nav entry and any redirect waiting
// on it switch on by themselves. Pages past the core "log in → journal →
// history" loop are lazy (one chunk each, see lazyPage); RoutePage wraps each
// one in its own Suspense.

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

const REDIRECTS = activeRedirects();
const REDIRECTED = new Set(REDIRECTS.map((r) => r.from));
const ROUTES = PAGE_ROUTES.filter((r) => !REDIRECTED.has(r.path));

/** Active redirects first, then page routes they don't own, then `*`. No hooks
 *  (scripts/check-routes.mjs reads its element tree directly). */
export function AppRoutes() {
  return (
    <Routes>
      {REDIRECTS.map((r) => (
        <Route key={`redirect:${r.from}`} path={r.from} element={<LegacyRedirect to={r.to} />} />
      ))}
      {ROUTES.map((r) => (
        // Keyed so each route mounts fresh: no stale page title or
        // Suspense content carries over between routes.
        <Route key={r.path} path={r.path} element={<RoutePage key={r.path} route={r} />} />
      ))}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <CurrentCampaignProvider>
          <CampaignEventsSubscriber />
          <TourProvider>
          <RouteAnnouncer />
          <div className="min-h-screen flex flex-col">
          <PreviewBanner />
          <NavBar />
          <main id="main" tabIndex={-1} className="flex-1 flex flex-col">
          <Suspense fallback={<RouteLoading />}>
          <AppRoutes />
          </Suspense>
          </main>
          <Footer />
          </div>
          <ChatWidget />
          <Toaster />
          <ShortcutHelp />
          <TourOverlay />
          <TutorialWelcomePrompt />
        </TourProvider>
          </CurrentCampaignProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
