// Structural test-isolation guard (#973). Wired as a vitest `setupFile`, so it
// runs for EVERY test file — the node logic suite and the happy-dom component
// suite alike — before any test executes.
//
// Why it exists: unit/component tests must never touch a real network. happy-dom
// ships a working `fetch`, and `api.ts`'s baseUrl falls back to
// `http://127.0.0.1:8787/api` under `vitest run` (VITE_API_BASE is set only in
// `--mode claude`). So a component test that renders a component which fetches on
// mount, without mocking `@/lib/api`, silently hits whatever backend is listening
// on :8787 — Anton's dev backend — and gets a `409 "No project is open."` (no
// project was opened in the test). That was the recurring, un-root-caused noise
// in #973: every logged 409 came from HappyDOM, not the app.
//
// Two layers of protection:
//   1. The network globals are replaced with stubs that never reach the wire, so
//      a real request is impossible regardless of the test.
//   2. Each attempt is recorded, and an afterEach FAILS the test if any were made.
//      This runs outside the component's own try/catch — the leaky calls in #973
//      sit inside `catch {}` (which is why they were "harmless"), so a throw alone
//      would be swallowed and the leak would stay invisible. The afterEach makes a
//      swallowed leak loud too.
//
// The right fix for a flagged test is to mock `@/lib/api` (see
// components/dialogs/TagManagerDialog.test.ts). A test that genuinely needs a
// stubbed transport can `vi.stubGlobal("fetch", …)` and drain the record.
//
// This is the test-side twin of the backend `scripts/check_http_client.py` gate:
// the same "all backend I/O goes through one audited path" boundary, enforced on
// both sides of the wire (ADR-0056).
import { afterEach } from "vitest";

const MESSAGE =
  "Tests must not touch the network: mock '@/lib/api' (see " +
  "components/dialogs/TagManagerDialog.test.ts) instead of letting a component " +
  "fetch a real backend on mount (#973).";

const attempts: string[] = [];

function record(call: string): void {
  attempts.push(call);
}

/** Take and clear the recorded network attempts (for the guard's own meta-test). */
export function drainNetworkAttempts(): string[] {
  return attempts.splice(0, attempts.length);
}

// Assign directly on globalThis (not vi.stubGlobal) so a stray
// vi.unstubAllGlobals() in some test's teardown can't quietly re-expose the real
// network for the rest of that file.
const g = globalThis as unknown as Record<string, unknown>;

g.fetch = (input: unknown) => {
  const target = typeof input === "string" ? input : String((input as { url?: string })?.url ?? "");
  record(`fetch ${target}`.trim());
  // Reject rather than throw synchronously, matching real fetch's promise shape,
  // so a `.catch()`-only caller is handled the same as an `await`ed one.
  return Promise.reject(new Error(MESSAGE));
};

for (const name of ["EventSource", "WebSocket", "XMLHttpRequest"] as const) {
  g[name] = class {
    constructor() {
      record(`new ${name}()`);
      throw new Error(MESSAGE);
    }
  };
}

afterEach(() => {
  const leaked = drainNetworkAttempts();
  if (leaked.length > 0) {
    throw new Error(`Test made ${leaked.length} network attempt(s): ${leaked.join("; ")}. ${MESSAGE}`);
  }
});
