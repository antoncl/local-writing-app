/**
 * The designer's command vocabulary (ADR-0050 §8 slice 1, #681), driven the
 * way the canvas will drive it: builders capture mementos from a live graph,
 * the real UndoCaretaker records and replays them, and the assertions read
 * the graph — including the ADR's §6 identity invariant (a deleted node
 * returns with its original id, so its edges reconnect).
 */
import { describe, expect, it } from "vitest";
import { UndoCaretaker } from "@/lib/stores/undoCaretaker.svelte";
import {
  addNodeCommand,
  configCommands,
  connectCommand,
  deleteCommands,
  moveNodesCommand,
  type DesignerGraphPort,
  type XY,
} from "./designerCommands";

type TestNode = { id: string; position: XY; data: { cfg: Record<string, unknown> } };
type TestEdge = { id: string; source: string; target: string };

function makeGraph(nodes: TestNode[] = [], edges: TestEdge[] = []) {
  const graph = { nodes, edges };
  const port: DesignerGraphPort<TestNode, TestEdge> = {
    getNodes: () => graph.nodes,
    setNodes: (n) => (graph.nodes = n),
    getEdges: () => graph.edges,
    setEdges: (e) => (graph.edges = e),
  };
  return { graph, port };
}

const node = (id: string, x = 0, y = 0, cfg: Record<string, unknown> = {}): TestNode => ({
  id,
  position: { x, y },
  data: { cfg },
});
const edge = (id: string, source: string, target: string): TestEdge => ({ id, source, target });

describe("designerCommands", () => {
  it("round-trips an add through the caretaker", () => {
    const { graph, port } = makeGraph([node("out")]);
    const caretaker = new UndoCaretaker();

    const added = node("a0", 10, 20);
    graph.nodes = [...graph.nodes, added]; // the committer mutates first (§1)
    caretaker.record(addNodeCommand(port, added));

    expect(caretaker.undo()).toEqual({ label: "add node" });
    expect(graph.nodes.map((n) => n.id)).toEqual(["out"]);
    caretaker.redo();
    expect(graph.nodes.map((n) => n.id)).toEqual(["out", "a0"]);
    expect(graph.nodes[1].position).toEqual({ x: 10, y: 20 });
  });

  it("captures an add's birth position even if the live node is later mutated in place", () => {
    const { graph, port } = makeGraph([]);
    const caretaker = new UndoCaretaker();
    const added = node("a0", 10, 20);
    graph.nodes = [added];
    caretaker.record(addNodeCommand(port, added));

    added.position.x = 999; // what a SvelteFlow drag does through the $state proxy
    caretaker.undo();
    caretaker.redo();
    expect(graph.nodes[0].position).toEqual({ x: 10, y: 20 }); // the memento, not the drift
  });

  it("undoes a delete as one step, restoring the node with its original id and its edges (§6)", () => {
    const doomed = node("a1", 5, 5, { field: "tags" });
    const { graph, port } = makeGraph([node("out"), doomed], [edge("e1", "a1", "out"), edge("e2", "src", "a1")]);
    const caretaker = new UndoCaretaker();

    const incident = graph.edges.filter((e) => e.source === "a1" || e.target === "a1");
    const commands = deleteCommands(port, [doomed], incident);
    // The committer mutates first, then records the whole cascade.
    graph.nodes = graph.nodes.filter((n) => n.id !== "a1");
    graph.edges = graph.edges.filter((e) => e.source !== "a1" && e.target !== "a1");
    for (const c of commands) caretaker.record(c);

    // ONE undo step (the shared transaction), announcing the gesture.
    expect(caretaker.undo()).toEqual({ label: "delete node" });
    expect(caretaker.canUndo).toBe(false);
    expect(graph.nodes.map((n) => n.id)).toContain("a1"); // same id — edges reconnect
    expect(graph.edges.map((e) => e.id).sort()).toEqual(["e1", "e2"]);
    const restored = graph.nodes.find((n) => n.id === "a1");
    expect(restored?.data.cfg).toEqual({ field: "tags" });
    expect(restored?.position).toEqual({ x: 5, y: 5 });

    // One redo re-deletes everything.
    caretaker.redo();
    expect(graph.nodes.map((n) => n.id)).toEqual(["out"]);
    expect(graph.edges).toEqual([]);
  });

  it("labels a multi-node deletion by count", () => {
    const a = node("a1");
    const b = node("a2");
    const { graph, port } = makeGraph([node("out"), a, b], []);
    const caretaker = new UndoCaretaker();
    const commands = deleteCommands(port, [a, b], []);
    graph.nodes = [graph.nodes[0]];
    for (const c of commands) caretaker.record(c);

    expect(caretaker.undoLabel).toBe("delete 2 nodes");
    expect(caretaker.undo()).toEqual({ label: "delete 2 nodes" });
    expect(graph.nodes.map((n) => n.id).sort()).toEqual(["a1", "a2", "out"]);
  });

  it("mints a fresh transaction per deletion so two deletes stay two steps", () => {
    const a = node("a1");
    const b = node("a2");
    const { graph, port } = makeGraph([a, b], []);
    const caretaker = new UndoCaretaker();

    for (const doomed of [a, b]) {
      const commands = deleteCommands(port, [doomed], []);
      graph.nodes = graph.nodes.filter((n) => n.id !== doomed.id);
      for (const c of commands) caretaker.record(c);
    }
    caretaker.undo();
    expect(graph.nodes.map((n) => n.id)).toEqual(["a2"]); // only the second delete reversed
    caretaker.undo();
    expect(graph.nodes.map((n) => n.id).sort()).toEqual(["a1", "a2"]);
  });

  it("round-trips a config edit, restoring dropped edges with the old config in one step", () => {
    const target = node("a1", 0, 0, { field: "tags" });
    const { graph, port } = makeGraph([node("out"), target], [edge("e1", "a1", "out")]);
    const caretaker = new UndoCaretaker();

    const before = target.data.cfg;
    const after = { field: "status" };
    // The committer applies the patch, drops the now-invalid edge, records.
    graph.nodes = graph.nodes.map((n) => (n.id === "a1" ? { ...n, data: { cfg: after } } : n));
    const dropped = graph.edges;
    graph.edges = [];
    for (const c of configCommands(port, "a1", before, after, dropped)) caretaker.record(c);

    expect(caretaker.undo()).toEqual({ label: "edit node" }); // one step, edit's label
    expect(graph.nodes.find((n) => n.id === "a1")?.data.cfg).toEqual({ field: "tags" });
    expect(graph.edges.map((e) => e.id)).toEqual(["e1"]);
    expect(caretaker.canUndo).toBe(false);

    caretaker.redo();
    expect(graph.nodes.find((n) => n.id === "a1")?.data.cfg).toEqual({ field: "status" });
    expect(graph.edges).toEqual([]);
  });

  it("keeps a plain config edit a single untagged command", () => {
    const target = node("a1", 0, 0, { mode: "keep" });
    const { graph, port } = makeGraph([target], []);
    const commands = configCommands(port, "a1", target.data.cfg, { mode: "drop" });
    expect(commands).toHaveLength(1);
    expect(commands[0].transaction).toBeUndefined();
    void graph;
  });

  it("returns no commands for a deep-equal no-op edit", () => {
    // Committers rebuild object-valued patches every commit; a re-picked
    // identical option must not cost the author an empty undo step.
    const { port } = makeGraph([node("a1")], []);
    const before: Record<string, unknown> = { match: { by: "ref" } };
    const after: Record<string, unknown> = { match: { by: "ref" } };
    expect(configCommands(port, "a1", before, after)).toEqual([]);
  });

  it("preserves everything else on the node's data when swapping cfg", () => {
    type KindedNode = TestNode & { data: { kind: string; cfg: Record<string, unknown> } };
    const target: KindedNode = { id: "a1", position: { x: 0, y: 0 }, data: { kind: "filter", cfg: { mode: "keep" } } };
    const graph = { nodes: [target] as KindedNode[], edges: [] as TestEdge[] };
    const port: DesignerGraphPort<KindedNode, TestEdge> = {
      getNodes: () => graph.nodes,
      setNodes: (n) => (graph.nodes = n),
      getEdges: () => graph.edges,
      setEdges: (e) => (graph.edges = e),
    };
    const [cmd] = configCommands(port, "a1", target.data.cfg, { mode: "drop" });
    cmd.undo();
    // The canvas keys everything off data.kind — a cfg swap must not eat it.
    expect(graph.nodes[0].data.kind).toBe("filter");
    cmd.redo();
    expect(graph.nodes[0].data.kind).toBe("filter");
    expect(graph.nodes[0].data.cfg).toEqual({ mode: "drop" });
  });

  it("mints a fresh transaction per config gesture so two edge-dropping edits stay two steps", () => {
    const target = node("a1", 0, 0, { field: "tags" });
    const { graph, port } = makeGraph([target], [edge("e1", "a1", "out"), edge("e2", "src", "a1")]);
    const caretaker = new UndoCaretaker();
    for (const [after, droppedId] of [
      [{ field: "status" }, "e1"],
      [{ field: "color" }, "e2"],
    ] as const) {
      const before = graph.nodes[0].data.cfg;
      const dropped = graph.edges.filter((e) => e.id === droppedId);
      graph.nodes = graph.nodes.map((n) => (n.id === "a1" ? { ...n, data: { cfg: after } } : n));
      graph.edges = graph.edges.filter((e) => e.id !== droppedId);
      for (const c of configCommands(port, "a1", before, after, dropped)) caretaker.record(c);
    }
    caretaker.undo();
    expect(graph.edges.map((e) => e.id)).toEqual(["e2"]); // only the second gesture reversed
    expect(graph.nodes[0].data.cfg).toEqual({ field: "status" });
    caretaker.undo();
    expect(graph.edges.map((e) => e.id).sort()).toEqual(["e1", "e2"]);
    expect(graph.nodes[0].data.cfg).toEqual({ field: "tags" });
  });

  it("round-trips a connect that displaced a superseded edge", () => {
    const { graph, port } = makeGraph(
      [node("out"), node("a1"), node("a2")],
      [edge("new", "a2", "out")], // post-normalize: the old wire was displaced
    );
    const caretaker = new UndoCaretaker();
    const displaced = edge("old", "a1", "out");
    caretaker.record(connectCommand(port, [graph.edges[0]], [displaced]));

    expect(caretaker.undo()).toEqual({ label: "connect" });
    expect(graph.edges.map((e) => e.id)).toEqual(["old"]);
    caretaker.redo();
    expect(graph.edges.map((e) => e.id)).toEqual(["new"]);
  });

  it("collapses a drag to one command and skips a drag that went nowhere", () => {
    const a = node("a1", 30, 40);
    const { graph, port } = makeGraph([a], []);

    expect(moveNodesCommand(port, [{ id: "a1", from: { x: 30, y: 40 }, to: { x: 30, y: 40 } }])).toBe(null);

    const cmd = moveNodesCommand(port, [{ id: "a1", from: { x: 0, y: 0 }, to: { x: 30, y: 40 } }]);
    expect(cmd?.label).toBe("move node");
    cmd?.undo();
    expect(graph.nodes[0].position).toEqual({ x: 0, y: 0 });
    cmd?.redo();
    expect(graph.nodes[0].position).toEqual({ x: 30, y: 40 });
  });

  it("labels a multi-select drag by count and moves only the dragged nodes", () => {
    const { graph, port } = makeGraph([node("a1", 10, 0), node("a2", 20, 0), node("out", 99, 99)], []);
    const cmd = moveNodesCommand(port, [
      { id: "a1", from: { x: 0, y: 0 }, to: { x: 10, y: 0 } },
      { id: "a2", from: { x: 5, y: 0 }, to: { x: 20, y: 0 } },
      { id: "out", from: { x: 99, y: 99 }, to: { x: 99, y: 99 } }, // unmoved rider
    ]);
    expect(cmd?.label).toBe("move 2 nodes");
    cmd?.undo();
    expect(graph.nodes.map((n) => n.position.x)).toEqual([0, 5, 99]);
  });
});
