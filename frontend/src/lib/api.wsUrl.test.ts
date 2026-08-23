// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach } from "vitest";

import { openSessionPresenceSocket } from "@/lib/api";

// The presence socket (#1378) derives its ws:// URL from the same base the HTTP
// client uses, swapping http(s)->ws(s). The test build bakes VITE_API_BASE (the
// dev stack's absolute cross-origin base), so this pins the absolute-base path;
// the packaged app's relative "/api" resolves the same way against the origin.
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("openSessionPresenceSocket", () => {
  it("opens the live socket at the ws:// form of the API base", () => {
    let opened = "";
    class CapturingWebSocket {
      constructor(url: string) {
        opened = url;
      }
    }
    vi.stubGlobal("WebSocket", CapturingWebSocket as unknown as typeof WebSocket);

    openSessionPresenceSocket();

    expect(opened).toBe("ws://127.0.0.1:8787/api/session/live");
  });
});
