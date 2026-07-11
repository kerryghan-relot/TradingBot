import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the JSON API to the Flask backend on :8501, so the
// front and API share an origin during development. `build` emits static
// assets into `dist/`, which Flask serves in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8501",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
