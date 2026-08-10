import { describe, expect, it } from "vitest";
import { loadEdgeLayers, saveEdgeLayers, toggleEdgeLayer } from "./edgeLayerPrefs";
import type { EdgeLayer } from "./plotBoardEdges";

// A Map-backed Storage stand-in, so the pref logic is exercised without a DOM.
function fakeStorage(seed: Record<string, string> = {}) {
  const map = new Map(Object.entries(seed));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    has: (k: string) => map.has(k),
  };
}

const KEY = "plotBoard.edgeLayers";

describe("edgeLayerPrefs", () => {
  it("defaults to no active layers (a quiet board)", () => {
    expect(loadEdgeLayers(fakeStorage())).toEqual(new Set());
  });

  it("round-trips saved layers", () => {
    const store = fakeStorage();
    saveEdgeLayers(new Set<EdgeLayer>(["manuscript", "beats"]), store);
    expect(loadEdgeLayers(store)).toEqual(new Set(["manuscript", "beats"]));
  });

  it("drops the key when nothing is active (leaves no trace)", () => {
    const store = fakeStorage({ [KEY]: JSON.stringify(["manuscript"]) });
    saveEdgeLayers(new Set(), store);
    expect(store.has(KEY)).toBe(false);
  });

  it("ignores unknown / stale layer names in storage", () => {
    // e.g. a future "causal" pref read back on a downgrade, or corruption.
    const store = fakeStorage({ [KEY]: JSON.stringify(["manuscript", "causal", 7]) });
    expect(loadEdgeLayers(store)).toEqual(new Set(["manuscript"]));
  });

  it("degrades to empty on corrupt JSON, never throwing", () => {
    const store = fakeStorage({ [KEY]: "{not json" });
    expect(loadEdgeLayers(store)).toEqual(new Set());
  });

  it("is inert with no storage available", () => {
    expect(loadEdgeLayers(null)).toEqual(new Set());
    expect(() => saveEdgeLayers(new Set(["beats"]), null)).not.toThrow();
  });

  it("toggles a layer on and off, returning a fresh set", () => {
    const empty = new Set<EdgeLayer>();
    const on = toggleEdgeLayer(empty, "manuscript");
    expect(on).toEqual(new Set(["manuscript"]));
    expect(empty).toEqual(new Set()); // original untouched
    expect(toggleEdgeLayer(on, "manuscript")).toEqual(new Set());
  });
});
