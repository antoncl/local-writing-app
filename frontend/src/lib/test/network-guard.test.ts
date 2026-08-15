import { describe, it, expect } from "vitest";
import { drainNetworkAttempts } from "@/lib/test/network-guard";

// Meta-test: the network guard (network-guard.ts, wired as a vitest setupFile in
// vite.config.js) must actually be installed for EVERY test file — otherwise a
// mount test can silently hit a real backend on :8787 again (#973). This pins
// that the guarded globals are stubbed AND that attempts are recorded (the
// afterEach uses the record to fail a test that leaks). Each case drains its own
// deliberate attempts so the guard's afterEach doesn't flag this test.

describe("network guard (test-isolation)", () => {
  it("rejects fetch instead of hitting a real backend, and records it", async () => {
    await expect((globalThis.fetch as unknown as (u: string) => Promise<unknown>)("/api/views")).rejects.toThrow(
      /must not touch the network/,
    );
    expect(drainNetworkAttempts()).toEqual(["fetch /api/views"]);
  });

  it("makes the streaming/XHR primitives throw, and records them", () => {
    const g = globalThis as unknown as Record<string, new () => unknown>;
    expect(() => new g.EventSource()).toThrow(/must not touch the network/);
    expect(() => new g.WebSocket()).toThrow(/must not touch the network/);
    expect(() => new g.XMLHttpRequest()).toThrow(/must not touch the network/);
    expect(drainNetworkAttempts()).toEqual(["new EventSource()", "new WebSocket()", "new XMLHttpRequest()"]);
  });
});
