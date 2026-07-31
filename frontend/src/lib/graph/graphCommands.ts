// The shared undo command vocabulary for node-canvas surfaces (ADR-0050 §8
// slice 1, #681; generalized off the view designer in S7c/#760 as the plot
// board became the second consumer the ADR anticipated).
//
// Each builder captures the memento a gesture needs to reverse itself and
// returns caretaker `Command`s — the graph-side half of the split the ADR
// makes: the caretaker (`undoCaretaker.svelte.ts`) knows only commands; this
// module knows nodes and edges and nothing about the stack. It lives outside
// any component because SvelteFlow is not headless-testable (§7 slice 0) —
// everything reversible is exercised by the sibling `.test.ts` against a fake
// port; a canvas only supplies the port and the gesture boundaries.
//
// Commands mutate through a `GraphPort` — direct array swaps on the surface's
// rune state, deliberately NOT the recording committers: the caretaker throws
// on `record` during a replay, and these closures are the replay.
//
// Mementos are shallow clones with the `position` cloned a level deeper:
// SvelteFlow drags mutate `node.position` **in place** through the `$state`
// proxy, so an uncloned capture would silently follow later drags instead of
// remembering its moment. Everything else on a node/edge is replaced
// wholesale by the committers, so object identity is a stable snapshot.

import type { Command } from "@/lib/stores/undoCaretaker.svelte";

export type XY = { x: number; y: number };
type Identified = { id: string };
type Positioned = Identified & { position: XY };

/** The surface-side mutators the closures replay through. */
export type GraphPort<N extends Identified, E extends Identified> = {
  getNodes(): N[];
  setNodes(nodes: N[]): void;
  getEdges(): E[];
  setEdges(edges: E[]): void;
};

// Fresh id per cascading gesture (ADR-0050 §4): the caretaker groups
// consecutive same-id commands into one step, so two gestures must never
// share an id. Module-level monotonic — uniqueness is all that matters.
let txCounter = 0;
function mintTransaction(): string {
  return `tx${++txCounter}`;
}

function cloneNode<N extends Positioned>(node: N): N {
  return { ...node, position: { ...node.position } };
}

/** The palette created a node (§1: "I created node N"; memento = birth state).
 *  Record AFTER appending — recording never executes. */
export function addNodeCommand<N extends Positioned, E extends Identified>(
  port: GraphPort<N, E>,
  node: N,
): Command {
  const memento = cloneNode(node);
  return {
    label: "add node",
    undo: () => port.setNodes(port.getNodes().filter((n) => n.id !== memento.id)),
    redo: () => port.setNodes([...port.getNodes(), memento]),
  };
}

function deleteEdgeCommand<N extends Identified, E extends Identified>(
  port: GraphPort<N, E>,
  edge: E,
  transaction: string,
): Command {
  const memento = { ...edge };
  return {
    label: "delete edge",
    transaction,
    undo: () => port.setEdges([...port.getEdges(), memento]),
    redo: () => port.setEdges(port.getEdges().filter((e) => e.id !== memento.id)),
  };
}

/**
 * A deletion — the ✕ button's node + incident edges, or the delete key's
 * whole selection. One transaction: edges first, the nodes last, so undo's
 * LIFO replay recreates every node **before** re-adding the edges that
 * reference it (§4), and each node returns with its original id so those
 * edges reconnect instead of dangling (§6 — the memento carries identity).
 * The concluding command carries the gesture's announcement label.
 */
export function deleteCommands<N extends Positioned, E extends Identified>(
  port: GraphPort<N, E>,
  nodes: N[],
  edges: E[],
): Command[] {
  const transaction = mintTransaction();
  const commands: Command[] = edges.map((e) => deleteEdgeCommand(port, e, transaction));
  nodes.forEach((node, index) => {
    const memento = cloneNode(node);
    const last = index === nodes.length - 1;
    commands.push({
      label: last ? (nodes.length > 1 ? `delete ${nodes.length} nodes` : "delete node") : "delete node",
      transaction,
      undo: () => port.setNodes([...port.getNodes(), memento]),
      redo: () => port.setNodes(port.getNodes().filter((n) => n.id !== memento.id)),
    });
  });
  return commands;
}

/**
 * A config edit (`updateNodeData`), plus the incident edges the edit's
 * validity sweep dropped — a payload flip silently deletes wires, so the undo
 * must bring them back with the old config or the graph "restores" into a
 * shape the author never saw. Cfg mementos are the whole before/after objects
 * (the committers replace cfg wholesale, so references are stable snapshots).
 *
 * Returns `[]` for a no-op edit (nothing dropped, cfg deep-equal) — the
 * committers rebuild object-valued patch payloads on every commit, so a
 * re-picked identical option must not cost the author an empty undo step.
 * The decision lives HERE, not in the canvas component, so a test can reach
 * it.
 */
export function configCommands<C, N extends Identified & { data: { cfg: C } }, E extends Identified>(
  port: GraphPort<N, E>,
  id: string,
  before: C,
  after: C,
  removedEdges: E[] = [],
): Command[] {
  if (removedEdges.length === 0 && JSON.stringify(before) === JSON.stringify(after)) return [];
  const setCfg = (cfg: C) =>
    port.setNodes(port.getNodes().map((n) => (n.id === id ? { ...n, data: { ...n.data, cfg } } : n)));
  const edit: Command = {
    label: "edit node",
    undo: () => setCfg(before),
    redo: () => setCfg(after),
  };
  if (removedEdges.length === 0) return [edit];
  const transaction = mintTransaction();
  edit.transaction = transaction;
  return [...removedEdges.map((e) => deleteEdgeCommand(port, e, transaction)), edit];
}

/**
 * A connect gesture: SvelteFlow appended the new edge and `normalizeEdges`
 * may have dropped superseded ones — one command covering both, diffed by the
 * caller. Undo removes what appeared and restores what was displaced.
 */
export function connectCommand<N extends Identified, E extends Identified>(
  port: GraphPort<N, E>,
  added: E[],
  removed: E[],
): Command {
  const addedMementos = added.map((e) => ({ ...e }));
  const removedMementos = removed.map((e) => ({ ...e }));
  const addedIds = new Set(addedMementos.map((e) => e.id));
  const removedIds = new Set(removedMementos.map((e) => e.id));
  return {
    label: "connect",
    undo: () => port.setEdges([...port.getEdges().filter((e) => !addedIds.has(e.id)), ...removedMementos]),
    redo: () => port.setEdges([...port.getEdges().filter((e) => !removedIds.has(e.id)), ...addedMementos]),
  };
}

/**
 * A completed drag — ONE command for the whole gesture (#187: never
 * one-per-frame), built from the positions captured on `onnodedragstart`.
 * Returns `null` for a drag that ended where it began (a click-ish gesture
 * records nothing).
 */
export function moveNodesCommand<N extends Positioned, E extends Identified>(
  port: GraphPort<N, E>,
  moves: { id: string; from: XY; to: XY }[],
): Command | null {
  const real = moves
    .filter((m) => m.from.x !== m.to.x || m.from.y !== m.to.y)
    .map((m) => ({ id: m.id, from: { ...m.from }, to: { ...m.to } }));
  if (real.length === 0) return null;
  const apply = (side: "from" | "to") => {
    const byId = new Map(real.map((m) => [m.id, m[side]]));
    port.setNodes(
      port.getNodes().map((n) => {
        const position = byId.get(n.id);
        return position ? { ...n, position: { ...position } } : n;
      }),
    );
  };
  return {
    label: real.length > 1 ? `move ${real.length} nodes` : "move node",
    undo: () => apply("from"),
    redo: () => apply("to"),
  };
}
