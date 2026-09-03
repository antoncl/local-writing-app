// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// The wire scope (`X-Project-Root`) must survive a re-instantiation of api.ts while
// a project is open — otherwise the next project-scoped fetch goes out unscoped and
// the backend answers 409 "No project is open." (#965). Storage-backed recovery is
// the fix; these tests pin it. `Headers(...)` normalizes the plain-object headers
// that `request()` assembles.
const SCOPE_KEY = "lwa.projectScopeRoot";
const ROOT = "D:\\Projects\\Book";

function stubFetch(json: unknown) {
  const mock = vi.fn().mockResolvedValue({ ok: true, json: async () => json } as Response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

function scopeHeaderOf(mock: ReturnType<typeof vi.fn>, callIndex: number): string | null {
  const init = mock.mock.calls[callIndex][1] as RequestInit;
  return new Headers(init.headers).get("X-Project-Root");
}

describe("api wire scope (#965)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.resetModules(); // force a fresh api.ts instance per test
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("omits X-Project-Root before any project is open", async () => {
    const mock = stubFetch({});
    const { api } = await import("@/lib/api");
    await api.listTagEntries();
    expect(scopeHeaderOf(mock, 0)).toBeNull();
  });

  it("openProject sets the scope header and persists it to sessionStorage", async () => {
    const mock = stubFetch({ root_path: ROOT });
    const { api } = await import("@/lib/api");
    await api.openProject(ROOT);
    expect(sessionStorage.getItem(SCOPE_KEY)).toBe(ROOT);
    await api.listTagEntries();
    expect(scopeHeaderOf(mock, 1)).toBe(encodeURIComponent(ROOT));
  });

  it("recovers the scope from sessionStorage when api.ts is re-instantiated mid-session", async () => {
    // A project was opened, then the module got re-evaluated (e.g. a Vite hot
    // update) so its variable is back to null — but sessionStorage still holds the
    // tab's open project. The next fetch must still carry the scope, not 409.
    sessionStorage.setItem(SCOPE_KEY, ROOT);
    const mock = stubFetch({});
    const { api } = await import("@/lib/api"); // inits projectScopeRoot from storage
    await api.listTagEntries();
    expect(scopeHeaderOf(mock, 0)).toBe(encodeURIComponent(ROOT));
  });
});
