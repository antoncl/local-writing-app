// Pure-logic test for the plot-board edge layers (ADR-0048 S7 Slice 6a). The
// SvelteFlow canvas is not headless-testable ([[reference_svelteflow_headless_limits]]),
// so the derived-edge logic lives — and is verified — here; the compositing is
// browser-checked.
import { describe, expect, it } from "vitest";
import { buildBoardEdges, type EdgeLayer } from "./plotBoardEdges";
import type { PlotBoardBeat, PlotBoardProjection } from "@/lib/types";

function projection(cards: PlotBoardProjection["cards"]): PlotBoardProjection {
  return { board_id: "b", board_revision: "r", layout: {}, plotlines: [], containers: [], cards };
}

const beat = (instance_id: string, beat_id: string): PlotBoardBeat => ({
  instance_id,
  instance_title: instance_id,
  beat_id,
  title: beat_id,
});

const card = (
  id: string,
  over: Partial<PlotBoardProjection["cards"][number]> = {},
): PlotBoardProjection["cards"][number] => ({
  id,
  title: id,
  synopsis: "",
  plotline: null,
  scene: null,
  container: null,
  page_status: null,
  beats: [],
  sequence: null,
  ...over,
});

const layers = (...on: EdgeLayer[]) => new Set<EdgeLayer>(on);
// An edge as a source→target pair, for order-independent-of-id assertions.
const pairs = (edges: { source: string; target: string }[]) => edges.map((e) => `${e.source}->${e.target}`);

describe("buildBoardEdges", () => {
  it("draws nothing when no layer is active (the quiet default)", () => {
    const p = projection([card("a", { sequence: 0 }), card("b", { sequence: 1 })]);
    expect(buildBoardEdges(p, layers())).toEqual([]);
  });

  describe("manuscript layer", () => {
    it("chains cards consecutively in reading order", () => {
      const p = projection([
        card("c", { sequence: 2 }),
        card("a", { sequence: 0 }),
        card("b", { sequence: 1 }),
      ]);
      expect(pairs(buildBoardEdges(p, layers("manuscript")))).toEqual(["a->b", "b->c"]);
    });

    it("skips cards with no scene (no reveal-order position)", () => {
      const p = projection([
        card("a", { sequence: 0 }),
        card("floating", { sequence: null }),
        card("b", { sequence: 1 }),
      ]);
      expect(pairs(buildBoardEdges(p, layers("manuscript")))).toEqual(["a->b"]);
    });

    it("chains cards sharing a scene in projection order", () => {
      // n cards on one scene share a rank; the tie-break is projection order.
      const p = projection([
        card("a", { sequence: 0 }),
        card("b1", { sequence: 1 }),
        card("b2", { sequence: 1 }),
      ]);
      expect(pairs(buildBoardEdges(p, layers("manuscript")))).toEqual(["a->b1", "b1->b2"]);
    });

    it("emits no edges for a single ranked card", () => {
      expect(buildBoardEdges(projection([card("a", { sequence: 0 })]), layers("manuscript"))).toEqual([]);
    });

    it("gives every edge a stable, unique id", () => {
      const p = projection([card("a", { sequence: 0 }), card("b", { sequence: 1 })]);
      const edges = buildBoardEdges(p, layers("manuscript"));
      expect(edges.map((e) => e.id)).toEqual(["ms:a->b"]);
      expect(new Set(edges.map((e) => e.id)).size).toBe(edges.length);
      expect(edges.every((e) => e.class === "manuscript-edge")).toBe(true);
    });
  });

  describe("beats layer", () => {
    it("chains the cards fulfilling one beat, ordered by reading order", () => {
      const p = projection([
        card("mid", { sequence: 1, beats: [beat("arc", "b1")] }),
        card("first", { sequence: 0, beats: [beat("arc", "b1")] }),
        card("last", { sequence: 2, beats: [beat("arc", "b1")] }),
      ]);
      expect(pairs(buildBoardEdges(p, layers("beats")))).toEqual(["first->mid", "mid->last"]);
    });

    it("keeps beats from different arcs/ids in separate chains", () => {
      const p = projection([
        card("a", { sequence: 0, beats: [beat("arc", "b1")] }),
        card("b", { sequence: 1, beats: [beat("arc", "b1"), beat("arc", "b2")] }),
        card("c", { sequence: 2, beats: [beat("arc", "b2")] }),
      ]);
      // b1: a->b ; b2: b->c — b joins both chains, no cross-beat edge.
      expect(pairs(buildBoardEdges(p, layers("beats"))).sort()).toEqual(["a->b", "b->c"]);
    });

    it("does not conflate the same beat id across two arcs", () => {
      const p = projection([
        card("x", { sequence: 0, beats: [beat("arcA", "b1")] }),
        card("y", { sequence: 1, beats: [beat("arcB", "b1")] }),
      ]);
      // Same beat_id "b1" but different instances → two singleton groups → no edge.
      expect(buildBoardEdges(p, layers("beats"))).toEqual([]);
    });

    it("orders scene-less cards after ranked ones within a beat", () => {
      const p = projection([
        card("offpage", { sequence: null, beats: [beat("arc", "b1")] }),
        card("onpage", { sequence: 0, beats: [beat("arc", "b1")] }),
      ]);
      expect(pairs(buildBoardEdges(p, layers("beats")))).toEqual(["onpage->offpage"]);
    });

    it("gives beat edges a distinct class and id namespace", () => {
      const p = projection([
        card("a", { sequence: 0, beats: [beat("arc", "b1")] }),
        card("b", { sequence: 1, beats: [beat("arc", "b1")] }),
      ]);
      const edges = buildBoardEdges(p, layers("beats"));
      expect(edges).toHaveLength(1);
      expect(edges[0].class).toBe("beat-edge");
      expect(edges[0].id.startsWith("beat:")).toBe(true);
    });
  });

  it("emits both layers together with disjoint ids (Slice 7 needs ≥2 at once)", () => {
    const p = projection([
      card("a", { sequence: 0, beats: [beat("arc", "b1")] }),
      card("b", { sequence: 1, beats: [beat("arc", "b1")] }),
    ]);
    const edges = buildBoardEdges(p, layers("manuscript", "beats"));
    expect(edges).toHaveLength(2);
    expect(new Set(edges.map((e) => e.id)).size).toBe(2);
    expect(edges.map((e) => e.class).sort()).toEqual(["beat-edge", "manuscript-edge"]);
  });
});
