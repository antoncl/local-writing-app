// @vitest-environment happy-dom
/**
 * The GraphUndoController — the extracted testable layer between the
 * SvelteFlow canvas and the caretaker (#681 review). Driven exactly the way
 * the canvas drives it: a fake port over plain arrays, synthetic
 * KeyboardEvents, and assertions on the graph plus the announcement.
 * happy-dom (not node) because the chord handler needs real KeyboardEvent and
 * element targets; no component is mounted.
 */
import { describe, expect, it } from "vitest";
import { GraphUndoController } from "./graphUndoController.svelte";
import type { GraphPort, XY } from "@/lib/graph/graphCommands";

type TestNode = { id: string; position: XY; data: { kind: string; cfg: Record<string, unknown> } };
type TestEdge = { id: string; source: string; target: string };

function makeSurface(nodes: TestNode[] = [], edges: TestEdge[] = []) {
  const graph = { nodes, edges };
  const port: GraphPort<TestNode, TestEdge> = {
    getNodes: () => graph.nodes,
    setNodes: (n) => (graph.nodes = n),
    getEdges: () => graph.edges,
    setEdges: (e) => (graph.edges = e),
  };
  return { graph, port, ctl: new GraphUndoController(port) };
}

const node = (id: string, x = 0, y = 0): TestNode => ({ id, position: { x, y }, data: { kind: "all", cfg: {} } });
const edge = (id: string, source: string, target: string): TestEdge => ({ id, source, target });

function chord(key: string, extra: Partial<KeyboardEventInit> = {}): KeyboardEvent {
  return new KeyboardEvent("keydown", { key, ctrlKey: true, bubbles: true, cancelable: true, ...extra });
}

describe("GraphUndoController", () => {
  it("routes Ctrl+Z to undo, Ctrl+Y and Ctrl+Shift+Z to redo", () => {
    const { graph, ctl } = makeSurface([]);
    const added = node("a0");
    graph.nodes = [added];
    ctl.recordAdd(added);

    ctl.handleKeydown(chord("z"));
    expect(graph.nodes).toEqual([]);
    expect(ctl.announcement).toBe("Undid add node");

    ctl.handleKeydown(chord("y"));
    expect(graph.nodes.map((n) => n.id)).toEqual(["a0"]);
    expect(ctl.announcement).toBe("Redid add node");

    ctl.handleKeydown(chord("z"));
    ctl.handleKeydown(chord("z", { shiftKey: true }));
    expect(graph.nodes.map((n) => n.id)).toEqual(["a0"]); // shift+z redid
  });

  it("announces the empty ends instead of silently no-opping", () => {
    const { ctl } = makeSurface();
    ctl.handleKeydown(chord("z"));
    expect(ctl.announcement).toBe("Nothing to undo");
    ctl.handleKeydown(chord("y"));
    expect(ctl.announcement).toBe("Nothing to redo");
  });

  it("re-announces an identical message by toggling a trailing no-break space", () => {
    const { ctl } = makeSurface();
    ctl.undo();
    const first = ctl.announcement;
    ctl.undo();
    expect(ctl.announcement).not.toBe(first); // changed text = re-announced
    expect(ctl.announcement.trimEnd()).toBe(first.trimEnd()); // same words
  });

  it("leaves chords inside text inputs to the input's native undo — but not selects", () => {
    const { graph, ctl } = makeSurface([]);
    const added = node("a0");
    graph.nodes = [added];
    ctl.recordAdd(added);

    const input = document.createElement("input");
    const fromInput = chord("z");
    Object.defineProperty(fromInput, "target", { value: input });
    ctl.handleKeydown(fromInput);
    expect(graph.nodes.map((n) => n.id)).toEqual(["a0"]); // untouched

    // A select has no native undo — swallowing the chord there would dead-zone
    // Ctrl+Z at the exact moment an author reverts the option they just picked.
    const select = document.createElement("select");
    const fromSelect = chord("z");
    Object.defineProperty(fromSelect, "target", { value: select });
    ctl.handleKeydown(fromSelect);
    expect(graph.nodes).toEqual([]);
  });

  it("ignores chords with Alt held or other keys", () => {
    const { graph, ctl } = makeSurface([]);
    const added = node("a0");
    graph.nodes = [added];
    ctl.recordAdd(added);
    ctl.handleKeydown(chord("z", { altKey: true }));
    ctl.handleKeydown(chord("x"));
    ctl.handleKeydown(new KeyboardEvent("keydown", { key: "z" })); // no modifier
    expect(graph.nodes.map((n) => n.id)).toEqual(["a0"]);
  });

  it("records a connect from the pre-append snapshot and undoes both halves", () => {
    // The canvas flow: beforeConnect() → SvelteFlow appends → onConnect(),
    // whose normalize drops the superseded wire.
    const { graph, ctl } = makeSurface([node("a"), node("b"), node("out")], [edge("old", "a", "out")]);
    ctl.beforeConnect();
    graph.edges = [...graph.edges, edge("new", "b", "out")]; // the append
    ctl.onConnect({ source: "b", target: "out" }, () => {
      graph.edges = graph.edges.filter((e) => e.id !== "old"); // normalize supersedes
    });

    expect(graph.edges.map((e) => e.id)).toEqual(["new"]);
    ctl.undo();
    expect(graph.edges.map((e) => e.id)).toEqual(["old"]);
    ctl.redo();
    expect(graph.edges.map((e) => e.id)).toEqual(["new"]);
  });

  it("records nothing when xyflow deduped the connect (re-drawing an existing wire)", () => {
    // xyflow's addEdge returns the array unchanged for a duplicate connection
    // but still fires onconnect — recording the phantom would make the next
    // undo delete a live wire.
    const { graph, ctl } = makeSurface([node("a"), node("out")], [edge("e1", "a", "out")]);
    ctl.beforeConnect();
    // no append happened
    ctl.onConnect({ source: "a", target: "out" }, () => {});
    expect(ctl.canUndo).toBe(false);
    expect(graph.edges.map((e) => e.id)).toEqual(["e1"]);
  });

  it("collapses a drag into one step and skips a drag that went nowhere", () => {
    const { graph, ctl } = makeSurface([node("a0", 0, 0)]);
    ctl.dragStart(graph.nodes);
    graph.nodes[0].position = { x: 30, y: 40 }; // what the canvas drag does
    ctl.dragStop(graph.nodes);
    expect(ctl.canUndo).toBe(true);
    ctl.undo();
    expect(graph.nodes[0].position).toEqual({ x: 0, y: 0 });
    expect(ctl.announcement).toBe("Undid move node");

    ctl.redo();
    ctl.dragStart(graph.nodes);
    ctl.dragStop(graph.nodes); // no movement — no step
    ctl.undo();
    expect(graph.nodes[0].position).toEqual({ x: 0, y: 0 }); // the drag, not a no-op
  });

  it("reset() drops the history and any in-flight gesture capture", () => {
    const { graph, ctl } = makeSurface([node("a0", 0, 0)]);
    ctl.recordAdd(graph.nodes[0]);
    ctl.dragStart(graph.nodes);
    ctl.reset();
    expect(ctl.canUndo).toBe(false);
    graph.nodes[0].position = { x: 9, y: 9 };
    ctl.dragStop(graph.nodes); // stale capture died with the reset
    expect(ctl.canUndo).toBe(false);
  });

  it("exposes peek titles for the button tooltips", () => {
    const { graph, ctl } = makeSurface([]);
    expect(ctl.undoTitle).toBe("Undo");
    expect(ctl.redoTitle).toBe("Redo");
    const added = node("a0");
    graph.nodes = [added];
    ctl.recordAdd(added);
    expect(ctl.undoTitle).toBe("Undo add node");
    ctl.undo();
    expect(ctl.redoTitle).toBe("Redo add node");
  });
});
