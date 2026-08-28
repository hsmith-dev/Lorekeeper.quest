import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      // Precache the app shell only — journal/campaign data always comes from
      // the API and is never cached by the service worker. Offline support
      // here means "queue a note with no signal," not "browse cached data."
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        navigateFallbackDenylist: [/^\/api\//],
        // registerType: "autoUpdate" alone does NOT make a new worker take
        // over immediately — Workbox's default lifecycle leaves a new worker
        // "waiting" until every tab controlled by the OLD one closes, so a
        // "fresh" navigation in a brand-new tab can still be served by
        // whatever worker was already active, with a cached index.html that
        // references JS chunk filenames the last deploy already deleted
        // (Vite hashes them per build) → blank/broken page with no obvious
        // cause. This was reported twice this session ("admin portal not
        // showing", "reset-password blank screen"), both only fixed by a
        // manual hard refresh. skipWaiting + clientsClaim make a new worker
        // activate and take control the moment it's installed, for every
        // open tab, not just future ones — paired with the controllerchange
        // reload in main.tsx for tabs already open when that happens.
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
      },
      manifest: {
        name: "Lorekeeper",
        short_name: "Lorekeeper",
        description: "AI-powered journaling for gamers — chronicle your adventures, preserve your legend.",
        theme_color: "#D2A122",
        background_color: "#17120A",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
