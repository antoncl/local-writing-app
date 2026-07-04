import { fileURLToPath, URL } from "node:url";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    // Fail loudly if 5173 is already taken instead of silently drifting to
    // 5174 (which is Claude's reserved isolated-instance port). A stale dev
    // server holding 5173 should surface as an error, not a port swap.
    strictPort: true,
  },
});
