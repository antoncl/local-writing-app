// Pure-logic test for the plot-board edge layers (ADR-0048 S7 Slice 6a). The
// SvelteFlow canvas is not headless-testable ([[reference_svelteflow_headless_limits]]),
// so the derived-edge logic lives — and is verified — here; the compositing is
// browser-checked.
import { describe, expect, it } from "vitest";
import {
  buildBoardEdges,
  CARD_SOURCE_HANDLE,
  CARD_TARGET_HANDLE,
  CAUSAL_MARKER_COLOR,
  CAUSAL_WARN_COLOR,
  causalWarnMessage,
  type CausalEdgeData,
  type EdgeLayer,
} from "./plotBoardEdges";
import type { PlotBoardBeat, PlotBoardProjection } from "@/lib/types";

function projection(cards: PlotBoardProjection["cards"]): PlotBoardProjection {
  return { board_id: "b", board_revision: "r", layout: {}, plotlines: [], arcs: [], containers: [], cards, diagnostics: [] };
}

const beat = (plotline_id: string, beat_id: string): PlotBoardBeat => ({
  plotline_id,
  plotline_title: plotline_id,
  plotline_color: null,
  beat_id,
  title: beat_id,
  number: 1,
  holder_kind: "plot:plotline",
  character_id: null,
  character_name: null,
  character_initial: null,
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
  causal_links: [],
  story_order: 0,
  story_movable: true,
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

  describe("causal layer", () => {
    it("draws one directed edge per authored target", () => {
      const p = projection([
        card("a", { causal_links: ["b", "c"] }),
        card("b"),
        card("c"),
      ]);
      expect(pairs(buildBoardEdges(p, layers("causal"))).sort()).toEqual(["a->b", "a->c"]);
    });

    it("carries an arrowhead + distinct class + id namespace (direction is authored)", () => {
      const p = projection([card("a", { causal_links: ["b"] }), card("b")]);
      const edges = buildBoardEdges(p, layers("causal"));
      expect(edges).toHaveLength(1);
      expect(edges[0].class).toBe("causal-edge");
      expect(edges[0].id).toBe("causal:a->b");
      expect(edges[0].markerEnd).toBeTruthy(); // the derived layers omit this
    });

    it("skips a self-link and a target that isn't a live card (defensive)", () => {
      const p = projection([card("a", { causal_links: ["a", "ghost", "b"] }), card("b")]);
      expect(pairs(buildBoardEdges(p, layers("causal")))).toEqual(["a->b"]);
    });

    it("is silent unless the causal layer is on", () => {
      const p = projection([card("a", { causal_links: ["b"] }), card("b")]);
      expect(buildBoardEdges(p, layers("manuscript"))).toEqual([]);
    });
  });

  describe("late-cause flag (Slice 7, ADR-0097 §8)", () => {
    const dataOf = (e: { data?: unknown }) => e.data as CausalEdgeData;

    it("flags a causal edge whose cause happens after its effect in story time", () => {
      const p = projection([
        card("a", { story_order: 1, title: "Cause", causal_links: ["b"] }),
        card("b", { story_order: 0, title: "Effect" }),
      ]);
      const [edge] = buildBoardEdges(p, layers("causal"));
      expect(edge.class).toContain("causal-warn");
      expect(dataOf(edge).outOfOrder).toBe(true);
      // Carries both titles so the edge composes a concrete why/what-to-do message.
      expect(dataOf(edge)).toMatchObject({ sourceTitle: "Cause", targetTitle: "Effect" });
      expect(edge.markerEnd).toMatchObject({ color: CAUSAL_WARN_COLOR });
    });

    it("does not flag a causal edge that runs with story time", () => {
      const p = projection([card("a", { story_order: 0, causal_links: ["b"] }), card("b", { story_order: 1 })]);
      const [edge] = buildBoardEdges(p, layers("causal"));
      expect(edge.class).toBe("causal-edge");
      expect(dataOf(edge).outOfOrder).toBe(false);
      expect(edge.markerEnd).toMatchObject({ color: CAUSAL_MARKER_COLOR });
    });

    it("ignores manuscript order: a cause told later but happening earlier is clean", () => {
      // The cause's scene is read LAST (sequence 5) yet it happens first in story time.
      const p = projection([
        card("a", { sequence: 5, story_order: 0, causal_links: ["b"] }),
        card("b", { sequence: 1, story_order: 1 }),
      ]);
      expect(dataOf(buildBoardEdges(p, layers("causal"))[0]).outOfOrder).toBe(false);
    });

    it("flags unwritten cards too (every card has a story position)", () => {
      const p = projection([
        card("a", { sequence: null, story_order: 3, causal_links: ["b"] }),
        card("b", { sequence: null, story_order: 2 }),
      ]);
      expect(dataOf(buildBoardEdges(p, layers("causal"))[0]).outOfOrder).toBe(true);
    });

    it("fires without the manuscript layer on (not gated on other layers)", () => {
      const p = projection([
        card("a", { story_order: 1, causal_links: ["b"] }),
        card("b", { story_order: 0 }),
      ]);
      const [edge] = buildBoardEdges(p, layers("causal"));
      expect(dataOf(edge).outOfOrder).toBe(true);
    });
  });

  describe("causalWarnMessage (the copy the reader sees — un-headless-testable in the edge)", () => {
    it("names both cards and states why + what to do", () => {
      const msg = causalWarnMessage("Cause", "Effect");
      // Both cards, so the warning is concrete, not a generic colour.
      expect(msg).toContain("“Cause”");
      expect(msg).toContain("“Effect”");
      // WHY (happens after its effect in story time) + WHAT to do (move the source earlier).
      expect(msg).toMatch(/happens after it in story time/);
      expect(msg).toMatch(/Move “Cause” earlier/);
    });

    it("interpolates the source (not the target) into the fix", () => {
      // The action names the card to MOVE — the source (cause), not the effect.
      expect(causalWarnMessage("Setup", "Payoff")).toContain("Move “Setup” earlier");
    });
  });

  it("anchors every edge to the card node's source/target handles", () => {
    // Load-bearing + un-headless-testable: xyflow renders nothing unless these
    // resolve to PlotCardNodeFlow's Handle ids. Pin them so a rename on either
    // side (the wrapper reads the SAME constants) fails here instead of silently
    // dropping every edge in the real browser.
    const p = projection([
      card("a", { sequence: 0, beats: [beat("arc", "b1")], causal_links: ["b"] }),
      card("b", { sequence: 1, beats: [beat("arc", "b1")] }),
    ]);
    const edges = buildBoardEdges(p, layers("manuscript", "causal"));
    expect(edges.length).toBeGreaterThan(0);
    for (const e of edges) {
      expect(e.sourceHandle).toBe(CARD_SOURCE_HANDLE);
      expect(e.targetHandle).toBe(CARD_TARGET_HANDLE);
    }
  });

  it("emits both layers together with disjoint ids (Slice 7 needs both at once)", () => {
    const p = projection([
      card("a", { sequence: 0, beats: [beat("arc", "b1")], causal_links: ["b"] }),
      card("b", { sequence: 1, beats: [beat("arc", "b1")] }),
    ]);
    const edges = buildBoardEdges(p, layers("manuscript", "causal"));
    expect(edges).toHaveLength(2);
    expect(new Set(edges.map((e) => e.id)).size).toBe(2);
    expect(edges.map((e) => e.class).sort()).toEqual(["causal-edge", "manuscript-edge"]);
  });

  describe("per-plotline focus (Slice 5b; #911 — cards outlined, edges recede)", () => {
    // A board with two threads plus a manuscript spine over all four.
    const twoThreads = () =>
      projection([
        card("p1", { sequence: 0, beats: [beat("P", "b1")] }),
        card("p2", { sequence: 1, beats: [beat("P", "b1")] }),
        card("q1", { sequence: 2, beats: [beat("Q", "b1")] }),
        card("q2", { sequence: 3, beats: [beat("Q", "b1")] }),
      ]);
    const cls = (e: { class?: unknown }) => String(e.class ?? "");

    it("tags no edge when nothing is focused", () => {
      const edges = buildBoardEdges(twoThreads(), layers("manuscript"));
      expect(edges.every((e) => !cls(e).includes("edge-dimmed"))).toBe(true);
    });

    it("dims EVERY edge when a plotline is focused — the thread is shown by outlining its CARDS", () => {
      const edges = buildBoardEdges(twoThreads(), layers("manuscript"), "P");
      expect(edges.length).toBeGreaterThan(0);
      // Every edge recedes; none is a special 'lit' focus edge (that lived only where a
      // beat had 2+ cards — the "first beat only" artefact this replaced).
      expect(edges.every((e) => cls(e).includes("edge-dimmed"))).toBe(true);
      expect(edges.every((e) => !cls(e).includes("edge-focused"))).toBe(true);
    });

    it("draws NO edges of its own — focus adds no chain when no layer is toggled", () => {
      const edges = buildBoardEdges(twoThreads(), layers(), "P");
      expect(edges).toEqual([]);
    });
  });
});
