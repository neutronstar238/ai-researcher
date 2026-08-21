import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/static/",
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://127.0.0.1:8765" },
  },
  build: {
    outDir: "../web",
    emptyOutDir: false,
    assetsInlineLimit: 1_000_000,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        assetFileNames: "styles.css",
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
