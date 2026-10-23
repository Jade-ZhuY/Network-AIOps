import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.AIOPS_API_PROXY || "http://127.0.0.1:18081";
  return {
    plugins: [react()],
    base: mode === "production" ? "/static/" : "/",
    build: {
      outDir: fileURLToPath(new URL("../app/web/dist", import.meta.url)),
      emptyOutDir: true,
      sourcemap: false,
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target,
          changeOrigin: false,
          timeout: 200_000,
          proxyTimeout: 200_000,
        },
        "/health": { target, changeOrigin: false },
        "/docs": { target, changeOrigin: false },
        "/openapi.json": { target, changeOrigin: false },
      },
    },
    test: {
      globals: true,
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      clearMocks: true,
      restoreMocks: true,
      css: false,
    },
  };
});
