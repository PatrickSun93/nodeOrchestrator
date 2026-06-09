import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // ws: true is required for Vite to proxy WebSocket upgrade requests.
      // Without it, Vite silently drops WS upgrades — the browser WS never
      // connects, events never arrive, and the room view stays empty.
      "/rooms": { target: "http://127.0.0.1:8000", ws: true },
      "/events": "http://127.0.0.1:8000",
      "/plugins": "http://127.0.0.1:8000",
      "/login": "http://127.0.0.1:8000",
      "/logout": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
