import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.tsx";
import { ErrorBoundary } from "./components/ErrorBoundary.tsx";
import "./index.css";

// Companion to vite.config.ts's skipWaiting/clientsClaim: those make a new
// service worker take control of every open tab the moment it activates,
// but taking control isn't the same as this tab's already-loaded React app
// getting the new code — the page just silently starts talking to a worker
// serving different files than what it was built against. Reloading once,
// guarded against firing twice, is the standard fix (see Workbox's own docs
// for this exact pattern) and is what actually resolves the stale-shell
// blank-screen reports from this session instead of requiring a manual hard
// refresh.
if ("serviceWorker" in navigator) {
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloading) return;
    reloading = true;
    window.location.reload();
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
