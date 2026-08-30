import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { copyFileSync } from "node:fs";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [
    react(),
    {
      // maplibre-gl v6 ships its worker as a prebuilt ESM asset; vite copies
      // it into dist/assets verbatim, and the worker's own
      // `import "./maplibre-gl-shared.mjs"` then 404s in production (vite
      // bundles the shared chunk into index-*.js but never emits it beside
      // the worker). No worker ⇒ no parsed tiles ⇒ a black map with a live
      // style and attribution. Re-emit the package's own shared chunk next
      // to the worker so the relative import resolves.
      name: "maplibre-worker-shared-chunk",
      closeBundle() {
        copyFileSync(
          resolve(__dirname, "node_modules/maplibre-gl/dist/maplibre-gl-shared.mjs"),
          resolve(__dirname, "dist/assets/maplibre-gl-shared.mjs"),
        );
      },
    },
  ],
  server: {
    port: 5173,
    proxy: {
      // keep API calls same-origin during dev; backend runs on :8000
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
