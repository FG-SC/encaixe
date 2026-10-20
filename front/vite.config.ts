/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Production build goes to front/dist, served by FastAPI at / (no Node process at runtime).
// The dev server is for development only; it proxies the API.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false, chunkSizeWarningLimit: 900 },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "happy-dom", include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"] },
});
