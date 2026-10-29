import { defineConfig } from "vite";

// Tauri serves the dev build from this fixed port (tauri.conf.json devUrl).
export default defineConfig({
  clearScreen: false,
  server: { port: 1420, strictPort: true, host: "127.0.0.1" },
  build: { target: "es2022", outDir: "dist", emptyOutDir: true },
});
