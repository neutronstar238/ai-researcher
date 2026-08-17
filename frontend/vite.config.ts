import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, ws: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    // 允许隧道/公网域名访问（cpolar 等会改写 Host 头）；.cpolar.cn 覆盖所有随机子域
    allowedHosts: [".cpolar.cn"],
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, ws: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    exclude: ["tests/e2e/**", "node_modules/**"],
  },
});
