import { defineConfig, devices } from "@playwright/test";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Thin browser-E2E smoke (#1352). This proves the *assembled* product boots in a
// real browser and the frontend↔backend wiring holds un-mocked — the one seam the
// vitest component tests (network-guard forbids real I/O) and the pytest
// TestClient integration tests structurally cannot reach.
//
// Two targets, ONE spec set. The server is picked by env, in priority order:
//   1. E2E_BASE_URL   → run against an already-serving origin; no webServer.
//   2. E2E_FROZEN_BIN → Playwright launches the frozen binary (release.yml). It
//      serves the bundle from `_MEIPASS/frontend_dist` — the true assembled
//      product. Playwright owns start/wait/kill (robust cross-platform, avoiding
//      the fragile bash background+taskkill #1350 flagged).
//   3. neither        → Playwright starts this worktree's backend from source,
//      serving the pre-built `frontend/dist` at `/` (same-origin `/api`, exactly
//      what ships). Requires `npm run build` first. This is the dev loop and the
//      every-PR gates.yml target.
//
// Deliberately tiny (a boot-and-wiring layer, never feature coverage) so it stays
// reliable rather than flaky. See #1351 for the full rationale.

const externalBaseUrl = process.env.E2E_BASE_URL;
const frozenBin = process.env.E2E_FROZEN_BIN;
// A non-8787 default so a local run never collides with Anton's primary backend.
const port = Number(process.env.E2E_PORT ?? 8799);
const baseURL = externalBaseUrl ?? `http://127.0.0.1:${port}`;

// Resolve this worktree's venv python for the managed-backend path.
const backendDir = fileURLToPath(new URL("../backend", import.meta.url));
const venvPython =
  process.platform === "win32"
    ? `${backendDir}/.venv/Scripts/python.exe`
    : `${backendDir}/.venv/bin/python`;
const python = existsSync(venvPython) ? venvPython : "python";

// Isolate the backend's machine config (config.yaml: recents, default projects
// folder, palette) to a throwaway dir. Two reasons: tests must never read or
// POLLUTE the real machine settings (create/open push onto recents on disk), and
// a fresh, empty config makes the create wizard's first step deterministic. The
// backend resolves its config dir from these platform vars (machine_settings.py:
// config_dir → APPDATA on win, HOME on mac, XDG_CONFIG_HOME on linux). Applies to
// the managed webServer only; the E2E_BASE_URL mode is the caller's to isolate.
const isolatedConfigHome = mkdtempSync(join(tmpdir(), "lwa-e2e-cfg-"));
const configEnv: Record<string, string> =
  process.platform === "win32"
    ? { APPDATA: isolatedConfigHome }
    : process.platform === "darwin"
      ? { HOME: isolatedConfigHome }
      : { XDG_CONFIG_HOME: isolatedConfigHome };

export default defineConfig({
  testDir: "./e2e",
  // `.e2e.ts` (not `.spec.ts`) keeps these files out of vitest's default globs,
  // so the network-guard setupFile never loads for them.
  testMatch: "**/*.e2e.ts",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL,
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: externalBaseUrl
    ? undefined
    : {
        // Frozen binary, or the source backend serving the pre-built bundle. Both
        // honor LWA_HOST/LWA_PORT (resolve_bind) and mount the SPA at `/`.
        command: frozenBin ? `"${frozenBin}"` : `${python} -m app.server`,
        cwd: frozenBin ? undefined : backendDir,
        url: baseURL,
        env: { LWA_HOST: "127.0.0.1", LWA_PORT: String(port), ...configEnv },
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        stdout: "pipe",
        stderr: "pipe",
      },
});
