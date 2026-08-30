import { describe, it, expect } from "vitest";
import { isDownwardLayerMove } from "@/lib/utils/fieldLayerMove";

// Chain ordered farthest-ancestor first, project-local last (#1677).
const layers = [{ id: "universe" }, { id: "series" }, { id: "book" }];

describe("isDownwardLayerMove", () => {
  it("is true moving to a NEARER layer (series -> book) — un-shares the field", () => {
    expect(isDownwardLayerMove(layers, "series", "book")).toBe(true);
    expect(isDownwardLayerMove(layers, "universe", "book")).toBe(true);
  });

  it("is false moving to a FARTHER layer (book -> series) — only widens visibility", () => {
    expect(isDownwardLayerMove(layers, "book", "series")).toBe(false);
    expect(isDownwardLayerMove(layers, "book", "universe")).toBe(false);
  });

  it("is false for a no-op move to the same layer", () => {
    expect(isDownwardLayerMove(layers, "series", "series")).toBe(false);
  });

  it("declines to warn when a layer id is unresolvable", () => {
    expect(isDownwardLayerMove(layers, "series", "ghost")).toBe(false);
    expect(isDownwardLayerMove(layers, "ghost", "book")).toBe(false);
  });
});
