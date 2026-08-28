import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "./contexts/ThemeContext";
import { TourProvider } from "./contexts/TourContext";
import { TourOverlay } from "./components/TourOverlay";
import { TutorialWelcomePrompt } from "./components/TutorialWelcomePrompt";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NavBar } from "./components/NavBar";
import { ChatWidget } from "./components/ChatWidget";
import { Footer } from "./components/Footer";

// Lazy-loaded: everything past the core "log in → journal → history" loop.
// Each of these used to be one static import in this file, which meant every
// visitor downloaded AdminPage, the model-evaluation UI inside SettingsPage,
// and 18 other routes most people never open, all in the same ~550KB chunk
// as the homepage. React.lazy + Suspense below gives each its own chunk,
// fetched only the first time its route is actually visited. The named
// `.then(m => ({ default: m.XPage }))` adapter is needed because every page
// in this app uses a named export (`export function XPage()`), not a
// default export — React.lazy only accepts a module with a default export.
const EntryDetailPage = lazy(() => import("./pages/EntryDetailPage").then((m) => ({ default: m.EntryDetailPage })));
const ChatPage = lazy(() => import("./pages/ChatPage").then((m) => ({ default: m.ChatPage })));
const CharactersPage = lazy(() => import("./pages/CharactersPage").then((m) => ({ default: m.CharactersPage })));
const CharacterSheetsPage = lazy(() =>
  import("./pages/CharacterSheetsPage").then((m) => ({ default: m.CharacterSheetsPage }))
);
const QuestsPage = lazy(() => import("./pages/QuestsPage").then((m) => ({ default: m.QuestsPage })));
const SessionPlansPage = lazy(() => import("./pages/SessionPlansPage").then((m) => ({ default: m.SessionPlansPage })));
const TimelinePage = lazy(() => import("./pages/TimelinePage").then((m) => ({ default: m.TimelinePage })));
const SourcesPage = lazy(() => import("./pages/SourcesPage").then((m) => ({ default: m.SourcesPage })));
const RecordSessionPage = lazy(() => import("./pages/RecordSessionPage").then((m) => ({ default: m.RecordSessionPage })));
const AnalyticsPage = lazy(() => import("./pages/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })));
const SharingPage = lazy(() => import("./pages/SharingPage").then((m) => ({ default: m.SharingPage })));
const SharedCampaignPage = lazy(() =>
  import("./pages/SharedCampaignPage").then((m) => ({ default: m.SharedCampaignPage }))
);
const JoinCampaignPage = lazy(() => import("./pages/JoinCampaignPage").then((m) => ({ default: m.JoinCampaignPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const SubscribePage = lazy(() => import("./pages/SubscribePage").then((m) => ({ default: m.SubscribePage })));
const FeedbackPage = lazy(() => import("./pages/FeedbackPage").then((m) => ({ default: m.FeedbackPage })));
const ShorthandPage = lazy(() => import("./pages/ShorthandPage").then((m) => ({ default: m.ShorthandPage })));
const AdminPage = lazy(() => import("./pages/AdminPage").then((m) => ({ default: m.AdminPage })));
const TermsPage = lazy(() => import("./pages/TermsPage").then((m) => ({ default: m.TermsPage })));
const PrivacyPage = lazy(() => import("./pages/PrivacyPage").then((m) => ({ default: m.PrivacyPage })));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem("lk_token");
  return token ? <>{children}</> : <Navigate to="/login" replace />;
}

// Shown only for the brief moment a lazy route's chunk is downloading (near-
// instant on repeat visits/fast connections — Vite prefetches nothing extra
// here, this is just the plain Suspense fallback).
function RouteLoading() {
  return (
    <div className="flex-1 flex items-center justify-center py-24 text-sm text-muted-foreground">
      Loading…
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <TourProvider>
          <div className="min-h-screen flex flex-col">
          <NavBar />
          <main className="flex-1 flex flex-col">
          <Suspense fallback={<RouteLoading />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/shared/:token" element={<SharedCampaignPage />} />
            <Route path="/join/:token" element={<JoinCampaignPage />} />
            <Route path="/" element={<HomePage />} />
            <Route path="/dashboard" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
            <Route path="/history" element={<PrivateRoute><HistoryPage /></PrivateRoute>} />
            <Route path="/journal/:id" element={<PrivateRoute><EntryDetailPage /></PrivateRoute>} />
            <Route path="/chat" element={<PrivateRoute><ChatPage /></PrivateRoute>} />
            <Route path="/timeline" element={<PrivateRoute><TimelinePage /></PrivateRoute>} />
            <Route path="/characters" element={<PrivateRoute><CharactersPage /></PrivateRoute>} />
            <Route path="/character-sheets" element={<PrivateRoute><CharacterSheetsPage /></PrivateRoute>} />
            <Route path="/quests" element={<PrivateRoute><QuestsPage /></PrivateRoute>} />
            <Route path="/session-plans" element={<PrivateRoute><SessionPlansPage /></PrivateRoute>} />
            <Route path="/sources" element={<PrivateRoute><SourcesPage /></PrivateRoute>} />
            <Route path="/record" element={<PrivateRoute><RecordSessionPage /></PrivateRoute>} />
            <Route path="/analytics" element={<PrivateRoute><AnalyticsPage /></PrivateRoute>} />
            <Route path="/sharing" element={<PrivateRoute><SharingPage /></PrivateRoute>} />
            <Route path="/settings" element={<PrivateRoute><SettingsPage /></PrivateRoute>} />
            <Route path="/subscribe" element={<PrivateRoute><SubscribePage /></PrivateRoute>} />
            <Route path="/feedback" element={<PrivateRoute><FeedbackPage /></PrivateRoute>} />
            <Route path="/shorthand" element={<PrivateRoute><ShorthandPage /></PrivateRoute>} />
            <Route path="/admin" element={<PrivateRoute><AdminPage /></PrivateRoute>} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
          </Routes>
          </Suspense>
          </main>
          <Footer />
          </div>
          <ChatWidget />
          <TourOverlay />
          <TutorialWelcomePrompt />
        </TourProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
