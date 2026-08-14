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
  return { board_id: "b", board_revision: "r", layout: {}, plotlines: [], containers: [], cards };
}

const beat = (plotline_id: string, beat_id: string): PlotBoardBeat => ({
  plotline_id,
  plotline_title: plotline_id,
  plotline_color: null,
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
  causal_links: [],
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
      expect(buildBoardEdges(p, layers("manuscript", "beats"))).toEqual([]);
    });
  });

  describe("out-of-order diagnostic (Slice 7)", () => {
    const dataOf = (e: { data?: unknown }) => e.data as CausalEdgeData;

    it("flags a causal edge whose cause is revealed after its effect", () => {
      // “Cause” is read 2nd (seq 1) but leads to “Effect”, read 1st (seq 0).
      const p = projection([
        card("a", { sequence: 1, title: "Cause", causal_links: ["b"] }),
        card("b", { sequence: 0, title: "Effect" }),
      ]);
      const [edge] = buildBoardEdges(p, layers("causal"));
      expect(edge.class).toContain("causal-warn");
      expect(dataOf(edge).outOfOrder).toBe(true);
      // Carries both titles so the edge composes a concrete why/what-to-do message.
      expect(dataOf(edge)).toMatchObject({ sourceTitle: "Cause", targetTitle: "Effect" });
      expect(edge.markerEnd).toMatchObject({ color: CAUSAL_WARN_COLOR });
    });

    it("does not flag a causal edge that runs with reveal order", () => {
      const p = projection([card("a", { sequence: 0, causal_links: ["b"] }), card("b", { sequence: 1 })]);
      const [edge] = buildBoardEdges(p, layers("causal"));
      expect(edge.class).toBe("causal-edge");
      expect(dataOf(edge).outOfOrder).toBe(false);
      expect(edge.markerEnd).toMatchObject({ color: CAUSAL_MARKER_COLOR });
    });

    it("treats equal reveal ranks as in order (only strictly-after warns)", () => {
      // Two cards on one scene share a rank — the cause is not strictly after the effect.
      const p = projection([card("a", { sequence: 3, causal_links: ["b"] }), card("b", { sequence: 3 })]);
      expect(dataOf(buildBoardEdges(p, layers("causal"))[0]).outOfOrder).toBe(false);
    });

    it("exempts an edge touching a card with no reveal position (null sequence)", () => {
      // An off-page source or target holds no reveal-order position → can't be out of order.
      const p = projection([
        card("a", { sequence: null, causal_links: ["b"] }),
        card("b", { sequence: 0, causal_links: ["c"] }),
        card("c", { sequence: null }),
      ]);
      const edges = buildBoardEdges(p, layers("causal"));
      expect(edges.every((e) => !dataOf(e).outOfOrder)).toBe(true);
      expect(edges.every((e) => e.class === "causal-edge")).toBe(true);
    });

    it("fires without the manuscript layer on (not gated on other layers)", () => {
      const p = projection([
        card("a", { sequence: 1, causal_links: ["b"] }),
        card("b", { sequence: 0 }),
      ]);
      // Only the causal layer is on; the warning still resolves from the cards' sequences.
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
      // WHY (revealed later / cause after effect) + WHAT to do (move the source earlier).
      expect(msg).toMatch(/read later/);
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
    const edges = buildBoardEdges(p, layers("manuscript", "beats", "causal"));
    expect(edges.length).toBeGreaterThan(0);
    for (const e of edges) {
      expect(e.sourceHandle).toBe(CARD_SOURCE_HANDLE);
      expect(e.targetHandle).toBe(CARD_TARGET_HANDLE);
    }
  });

  it("emits all three layers together with disjoint ids (Slice 7 needs ≥2 at once)", () => {
    const p = projection([
      card("a", { sequence: 0, beats: [beat("arc", "b1")], causal_links: ["b"] }),
      card("b", { sequence: 1, beats: [beat("arc", "b1")] }),
    ]);
    const edges = buildBoardEdges(p, layers("manuscript", "beats", "causal"));
    expect(edges).toHaveLength(3);
    expect(new Set(edges.map((e) => e.id)).size).toBe(3);
    expect(edges.map((e) => e.class).sort()).toEqual(["beat-edge", "causal-edge", "manuscript-edge"]);
  });

  describe("per-plotline focus (Slice 5b)", () => {
    // A board with two threads (P focused, Q not) plus a manuscript spine over all four.
    const twoThreads = () =>
      projection([
        card("p1", { sequence: 0, beats: [beat("P", "b1")] }),
        card("p2", { sequence: 1, beats: [beat("P", "b1")] }), // P:b1 chain p1->p2
        card("q1", { sequence: 2, beats: [beat("Q", "b1")] }),
        card("q2", { sequence: 3, beats: [beat("Q", "b1")] }), // Q:b1 chain q1->q2
      ]);
    const classOf = (edges: { id: unknown; class?: unknown }[], id: string) =>
      String(edges.find((e) => e.id === id)?.class ?? "");

    it("tags no edge when nothing is focused", () => {
      const edges = buildBoardEdges(twoThreads(), layers("manuscript", "beats"));
      const cls = (e: { class?: unknown }) => String(e.class ?? "");
      expect(edges.every((e) => !cls(e).includes("edge-focused") && !cls(e).includes("edge-dimmed"))).toBe(true);
    });

    it("lights the focused thread and dims every other edge", () => {
      const edges = buildBoardEdges(twoThreads(), layers("manuscript", "beats"), "P");
      // The focused plotline's beat chain reads LOUD.
      expect(classOf(edges, "beat:P:b1:p1->p2")).toContain("edge-focused");
      // Another thread's beats + the manuscript spine recede.
      expect(classOf(edges, "beat:Q:b1:q1->q2")).toContain("edge-dimmed");
      expect(classOf(edges, "ms:p1->p2")).toContain("edge-dimmed");
      expect(classOf(edges, "ms:q1->q2")).toContain("edge-dimmed");
      // Focused edges are never also dimmed.
      expect(classOf(edges, "beat:P:b1:p1->p2")).not.toContain("edge-dimmed");
    });

    it("draws the focused thread's chain even with the beats layer off (self-contained)", () => {
      // No layers toggled: focus alone lights the thread — the 'see the threads' payoff.
      const edges = buildBoardEdges(twoThreads(), layers(), "P");
      expect(pairs(edges)).toEqual(["p1->p2"]);
      expect(edges[0].class).toContain("beat-edge");
      expect(edges[0].class).toContain("edge-focused");
    });

    it("does not duplicate the focused chain when the beats layer is also on", () => {
      const edges = buildBoardEdges(twoThreads(), layers("beats"), "P");
      // Both beat chains present, each once — the focus chain reuses the layer's edge id.
      expect(new Set(edges.map((e) => e.id)).size).toBe(edges.length);
      expect(edges.filter((e) => e.id === "beat:P:b1:p1->p2")).toHaveLength(1);
      expect(classOf(edges, "beat:P:b1:p1->p2")).toContain("edge-focused");
      expect(classOf(edges, "beat:Q:b1:q1->q2")).toContain("edge-dimmed");
    });
  });
});
