import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into dist/, which rdebug_ide.app serves at /ui/. The dev server proxies
// /api to a running rdebug-ide so the same code works in both places without an
// environment-specific base URL baked into the bundle.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // A sourcemap in a debug tool's shipped bundle is a liability, not a
    // convenience: it would publish the source of a tool whose whole point is
    // inspecting someone else's binaries.
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8760",
        changeOrigin: false,
        // SSE must not be buffered by the dev proxy, or the events arrive in a
        // lump at the end and the whole point of a stream is lost.
        configure(proxy) {
          proxy.on("proxyRes", (proxyRes) => {
            if (String(proxyRes.headers["content-type"] || "")
              .includes("text/event-stream")) {
              proxyRes.headers["x-accel-buffering"] = "no";
            }
          });
        },
      },
    },
  },
});