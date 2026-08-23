// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// A minimal fake WebSocket that lets the test fire lifecycle events. Instances
// are collected so we can assert opens and reconnects. The raw `new WebSocket`
// lives in lib/api.ts (ADR-0056), so we stub the factory it exports rather than
// the global — that also covers the URL the factory derives.
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  listeners: Record<string, Array<() => void>> = {};
  constructor() {
    FakeWebSocket.instances.push(this);
  }
  addEventListener(type: string, fn: () => void): void {
    (this.listeners[type] ??= []).push(fn);
  }
  fire(type: string): void {
    for (const fn of this.listeners[type] ?? []) fn();
  }
}

// A controllable factory stub so a test can also make the open throw.
const { openMock } = vi.hoisted(() => ({ openMock: vi.fn() }));
vi.mock("@/lib/api", () => ({ openSessionPresenceSocket: openMock }));

beforeEach(() => {
  FakeWebSocket.instances = [];
  openMock.mockReset();
  openMock.mockImplementation(() => new FakeWebSocket());
  vi.useFakeTimers();
  vi.resetModules(); // fresh module state (the `started`/`retry` singletons) per test
});

afterEach(() => {
  vi.useRealTimers();
});

describe("startSessionPresence", () => {
  it("opens one presence socket", async () => {
    const { startSessionPresence } = await import("@/lib/sessionPresence");
    startSessionPresence();
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("is idempotent — a second call opens no second socket", async () => {
    const { startSessionPresence } = await import("@/lib/sessionPresence");
    startSessionPresence();
    startSessionPresence();
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("reconnects after the socket closes mid-session", async () => {
    const { startSessionPresence } = await import("@/lib/sessionPresence");
    startSessionPresence();
    FakeWebSocket.instances[0].fire("close");
    // First backoff is 1s (2^0), well inside the server's grace window.
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("retries after the factory throws on open", async () => {
    openMock.mockImplementationOnce(() => {
      throw new Error("socket blocked");
    });
    const { startSessionPresence } = await import("@/lib/sessionPresence");
    startSessionPresence();
    expect(FakeWebSocket.instances).toHaveLength(0); // the throw created none
    vi.advanceTimersByTime(1000); // first backoff (2^0)
    expect(FakeWebSocket.instances).toHaveLength(1); // reconnect succeeded
  });

  it("backs off exponentially across repeated failures", async () => {
    const { startSessionPresence } = await import("@/lib/sessionPresence");
    startSessionPresence();
    FakeWebSocket.instances[0].fire("close"); // retry 0 -> 1s
    vi.advanceTimersByTime(1000);
    FakeWebSocket.instances[1].fire("close"); // retry 1 -> 2s
    vi.advanceTimersByTime(1999);
    expect(FakeWebSocket.instances).toHaveLength(2); // not yet
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(3);
  });
});
