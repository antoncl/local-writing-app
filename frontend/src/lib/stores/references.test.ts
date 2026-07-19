import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

// Mock the HTTP client so we control when each referenceGraph() call resolves —
// the whole point of these tests is refresh ordering, not the network.
const { referenceGraph } = vi.hoisted(() => ({ referenceGraph: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { referenceGraph } }));

import {
  clearReferenceIndex,
  referenceIndexStore,
  refreshReferenceIndex,
  refreshReferenceIndexInBackground,
} from "./references";

// A deferred promise whose resolve is exposed, so a test can force a fetch to
// settle at a chosen moment (and thus in a chosen order relative to others).
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("refreshReferenceIndex generation token (#200)", () => {
  beforeEach(() => {
    referenceGraph.mockReset();
    clearReferenceIndex();
  });

  it("keeps the newest-issued refresh even when an earlier one resolves last", async () => {
    const first = deferred<{ refs: Record<string, string[]> }>();
    const second = deferred<{ refs: Record<string, string[]> }>();
    referenceGraph.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    const a = refreshReferenceIndex(); // older token
    const b = refreshReferenceIndex(); // newest token — its result must win

    second.resolve({ refs: { r2: ["t2"] } });
    await b;
    expect(get(referenceIndexStore).get("t2")).toEqual(new Set(["r2"]));

    // The stale earlier fetch resolves last and must NOT overwrite the newer index.
    first.resolve({ refs: { r1: ["t1"] } });
    await a;
    expect(get(referenceIndexStore).has("t1")).toBe(false);
    expect(get(referenceIndexStore).get("t2")).toEqual(new Set(["r2"]));
  });

  it("a clear supersedes an in-flight refresh so a late resolve can't repopulate", async () => {
    const inflight = deferred<{ refs: Record<string, string[]> }>();
    referenceGraph.mockReturnValueOnce(inflight.promise);

    const p = refreshReferenceIndex();
    clearReferenceIndex(); // e.g. project switch/close while the fetch is in flight
    inflight.resolve({ refs: { r: ["t"] } });
    await p;

    expect(get(referenceIndexStore).size).toBe(0);
  });

  it("rejects (does not swallow) so the awaited project-open path fails hard", async () => {
    referenceGraph.mockRejectedValueOnce(new Error("boom"));
    await expect(refreshReferenceIndex()).rejects.toThrow("boom");
  });
});

describe("refreshReferenceIndexInBackground (#200 fire-and-forget)", () => {
  beforeEach(() => {
    referenceGraph.mockReset();
    clearReferenceIndex();
  });

  it("swallows a rejection instead of surfacing an unhandled promise", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    referenceGraph.mockRejectedValueOnce(new Error("boom"));

    // Must return void and never throw/reject even though the fetch fails.
    expect(refreshReferenceIndexInBackground()).toBeUndefined();
    await flush();

    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("applies the index on success", async () => {
    referenceGraph.mockResolvedValueOnce({ refs: { alice: ["bob"] } });
    refreshReferenceIndexInBackground();
    await flush();
    expect(get(referenceIndexStore).get("bob")).toEqual(new Set(["alice"]));
  });
});
