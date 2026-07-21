import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// Where `scripts/dev_backend.py` publishes the port Claude Code assigned it.
const backendPortFile = fileURLToPath(
  new URL("../tmp/dev-backend-port", import.meta.url),
);

/**
 * The isolated backend's base URL, discovered at startup.
 *
 * Under the worktree-first policy several sessions run at once, so the port
 * cannot be baked into a tracked file — every worktree would get the same one.
 * `frontend/.env.claude` used to hardcode :8788 and was exactly that bug.
 *
 * Failing loudly matters here: defaulting to :8787 on a missing file would
 * quietly point Claude's verification at Anton's backend and mutate his
 * projects, which is the whole thing this isolation exists to prevent.
 */
function claudeBackendBase() {
  let port;
  try {
    port = readFileSync(backendPortFile, "utf8").trim();
  } catch {
    throw new Error(
      `--mode claude needs the isolated backend's port, but ${backendPortFile} ` +
        `does not exist. Start the "backend-claude" launch config first; it ` +
        `publishes the port there.`,
    );
  }
  if (!/^\d+$/.test(port)) {
    throw new Error(
      `${backendPortFile} contains "${port}", not a port number.`,
    );
  }
  return `http://127.0.0.1:${port}/api`;
}

export default defineConfig(({ mode }) => {
  // Anton's stack, unchanged: pinned and strict, so a stale server holding
  // 5173 surfaces as an error instead of silently drifting to another port.
  const server = { host: "127.0.0.1", port: 5173, strictPort: true };
  const define = {};

  if (mode === "claude") {
    // Claude Code picked this port (autoPort) and told the Browser pane about
    // it, so bind exactly that one. Run by hand without PORT, take any free
    // port rather than defaulting to 5173 and stealing Anton's.
    const assigned = Number(process.env.PORT);
    server.port = Number.isInteger(assigned) && assigned > 0 ? assigned : 0;
    server.strictPort = server.port !== 0;
    define["import.meta.env.VITE_API_BASE"] = JSON.stringify(claudeBackendBase());
  }

  return {
    plugins: [svelte()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server,
    define,
  };
});
