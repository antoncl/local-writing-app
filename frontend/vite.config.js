import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { createLogger, defineConfig } from "vite";

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

export default defineConfig(({ command, mode }) => {
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
  } else if (command === "serve") {
    // Dev serve (Anton's stack): keep the pre-ADR-0072 behaviour EXACTLY — talk
    // to the backend on :8787 cross-origin, the same absolute base api.ts baked
    // in before. This is deliberately a build-time define, not a dev proxy: a
    // proxy would route the streaming chat response (response.body reader over a
    // backend StreamingResponse) through Vite, risking dev-only buffering. Only
    // the production build (no define) falls through to api.ts's same-origin
    // `/api`, which the packaged backend serves itself (ADR-0072 §1).
    define["import.meta.env.VITE_API_BASE"] = JSON.stringify("http://127.0.0.1:8787/api");
  }

  // Fail the production build on any warning, so a regression like a CSS
  // comment closed early by a stray `*/` (#538) cannot ship green again (#540).
  // svelte-check never runs the minifier, so that class of warning is invisible
  // to every other gate. Vite routes esbuild's CSS-minify warnings through
  // `config.logger.warn`; a logger that records them plus a closeBundle hook
  // that throws if any were seen turns the whole class into a hard failure.
  //
  // The bundle chunk-size advisory is deliberately excused: it is a standing
  // note about bundle bloat, not a per-build regression, and silencing it by
  // raising chunkSizeWarningLimit would mask a real signal. It still prints.
  const buildWarnings = [];
  const isExcused = (msg) =>
    typeof msg === "string" && msg.includes("Some chunks are larger");

  let customLogger;
  if (command === "build") {
    const base = createLogger();
    const record = (fn) => (msg, opts) => {
      if (!isExcused(msg)) buildWarnings.push(msg);
      fn(msg, opts);
    };
    customLogger = {
      ...base,
      warn: record(base.warn.bind(base)),
      warnOnce: record(base.warnOnce.bind(base)),
    };
  }

  const failOnBuildWarnings = {
    name: "fail-on-build-warnings",
    apply: "build",
    closeBundle() {
      if (buildWarnings.length === 0) return;
      const list = buildWarnings.map((w) => `  - ${w}`).join("\n");
      throw new Error(
        `Frontend build emitted ${buildWarnings.length} warning(s); builds ` +
          `must be warning-free (#540):\n${list}`,
      );
    },
  };

  return {
    plugins: [svelte(), failOnBuildWarnings],
    // Vitest reads this block. `setupFiles` runs once per test file, before any
    // test — here it installs the network guard that makes a test touching a
    // real backend fail loudly instead of silently hitting :8787 (#973).
    test: {
      setupFiles: ["./src/lib/test/network-guard.ts"],
    },
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
      // Component tests (#642) mount Svelte via @testing-library/svelte, which
      // needs the *client* build (`mount`). Vitest otherwise resolves Svelte's
      // server entry and fails with `mount(...) is not available on the
      // server`. Gate on VITEST so the app's dev/build resolution is untouched.
      ...(process.env.VITEST ? { conditions: ["browser"] } : {}),
    },
    server,
    define,
    customLogger,
  };
});
