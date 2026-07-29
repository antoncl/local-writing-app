// The designer's undo/redo controller (ADR-0050 slice 1, #681) — the glue
// between the canvas component and the caretaker: one per-view history,
// the gesture recorders the committers call, the Ctrl+Z/Y/Shift+Z chord
// handler, and the §7 announcement state. Extracted from ViewBodyView so the
// component stays under the size cap and this layer — everything reversible —
// is reachable by unit tests (SvelteFlow itself is not headless-testable).
//
// The controller records commands built by `designerCommands`; the commands
// replay through the `DesignerGraphPort` — raw array swaps on the component's
// rune state, deliberately NOT the recording committers (the caretaker throws
// on `record` during a replay).
import { UndoCaretaker } from "@/lib/stores/undoCaretaker.svelte";
import {
  addNodeCommand,
  configCommands,
  connectCommand,
  deleteCommands,
  moveNodesCommand,
  type DesignerGraphPort,
  type XY,
} from "@/lib/views/designerCommands";

type NodeLike = { id: string; position: XY };
type EdgeLike = { id: string; source: string; target: string };
type ConnectionLike = {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export class DesignerUndoController<N extends NodeLike, E extends EdgeLike> {
  // Reassigned wholesale on reset — one caretaker per loaded view (§3:
  // per-surface history; a fresh instance keeps one document's history from
  // bleeding into the next).
  #caretaker = $state(new UndoCaretaker());
  readonly #port: DesignerGraphPort<N, E>;
  /** Pre-drag positions of the dragged set, captured on dragstart so the
   *  whole gesture records as ONE command on release (#187). */
  #dragStart: Map<string, XY> | null = null;
  /** Edge ids as of `onbeforeconnect` — BEFORE SvelteFlow appends. The
   *  appended edge is then the one whose id is novel; endpoint matching
   *  can't tell it apart from a pre-existing duplicate (xyflow dedupes the
   *  append but still fires `onconnect`, and recording that phantom would
   *  make undo delete a live wire). */
  #preConnectIds: Set<string> | null = null;

  /** What the `aria-live` region reads out (§7). */
  announcement = $state("");

  constructor(port: DesignerGraphPort<N, E>) {
    this.#port = port;
  }

  get canUndo(): boolean {
    return this.#caretaker.canUndo;
  }
  get canRedo(): boolean {
    return this.#caretaker.canRedo;
  }
  /** Button tooltips: "Undo <label>" when a step is peekable. */
  get undoTitle(): string {
    const label = this.#caretaker.undoLabel;
    return label ? `Undo ${label}` : "Undo";
  }
  get redoTitle(): string {
    const label = this.#caretaker.redoLabel;
    return label ? `Redo ${label}` : "Redo";
  }

  /** Drop the history — a new document hydrated, or a kind re-anchor reset
   *  the graph (old-kind history would restore nodes whose types/fields no
   *  longer exist). In-flight gesture captures die with it. */
  reset(): void {
    this.#caretaker = new UndoCaretaker();
    this.#dragStart = null;
    this.#preConnectIds = null;
  }

  /** The palette created a node (record AFTER appending — §1 self-report). */
  recordAdd(node: N): void {
    this.#caretaker.record(addNodeCommand(this.#port, node));
  }

  /** A deletion — the ✕ button's node + incident edges, or the delete key's
   *  whole selection. One transaction; the node returns with its id (§6). */
  recordDelete(nodes: N[], edges: E[]): void {
    if (nodes.length === 0 && edges.length === 0) return;
    for (const c of deleteCommands(this.#port, nodes, edges)) this.#caretaker.record(c);
  }

  /** A config edit plus the incident edges its validity sweep dropped. */
  recordConfig(id: string, before: unknown, after: unknown, droppedEdges: E[]): void {
    const port = this.#port as DesignerGraphPort<N & { data: { cfg: unknown } }, E>;
    for (const c of configCommands(port, id, before, after, droppedEdges)) this.#caretaker.record(c);
  }

  /** `onbeforeconnect` hook: snapshot the edge ids before SvelteFlow appends,
   *  so `onConnect` can identify the new edge by id novelty. */
  beforeConnect(): void {
    this.#preConnectIds = new Set(this.#port.getEdges().map((e) => e.id));
  }

  /**
   * The connect gesture. SvelteFlow has already appended the new edge to the
   * bound array when `onconnect` fires; the `beforeConnect` snapshot names it
   * by novelty, `normalize` then settles the array (selfloop typing,
   * superseded edges dropped), and the diff becomes one command. When xyflow
   * deduped the gesture (re-drawing an existing wire), no id is novel and
   * nothing records — the canvas didn't change, so undo must not either.
   */
  onConnect(_conn: ConnectionLike, normalize: () => void): void {
    const seen = this.#preConnectIds;
    this.#preConnectIds = null;
    const edges = this.#port.getEdges();
    const appended = seen ? edges.find((e) => !seen.has(e.id)) : undefined;
    const before = appended ? edges.filter((e) => e.id !== appended.id) : [...edges];
    normalize();
    if (!appended) return; // dedupe, or no snapshot — nothing changed, nothing to reverse
    const after = this.#port.getEdges();
    const afterIds = new Set(after.map((e) => e.id));
    const added = after.filter((e) => e.id === appended.id);
    const removed = before.filter((e) => !afterIds.has(e.id));
    if (added.length > 0 || removed.length > 0) {
      this.#caretaker.record(connectCommand(this.#port, added, removed));
    }
  }

  /** Capture the dragged set's positions at gesture start. */
  dragStart(nodes: N[]): void {
    this.#dragStart = new Map(nodes.map((n) => [n.id, { ...n.position }]));
  }

  /** One command for the whole drag; a drag that went nowhere records nothing. */
  dragStop(nodes: N[]): void {
    const start = this.#dragStart;
    this.#dragStart = null;
    if (!start) return;
    const command = moveNodesCommand(
      this.#port,
      nodes
        .filter((n) => start.has(n.id))
        .map((n) => ({ id: n.id, from: start.get(n.id)!, to: { ...n.position } })),
    );
    if (command) this.#caretaker.record(command);
  }

  undo(): void {
    const step = this.#caretaker.undo();
    this.#announce(step === null ? "Nothing to undo" : `Undid ${step.label || "change"}`);
  }

  redo(): void {
    const step = this.#caretaker.redo();
    this.#announce(step === null ? "Nothing to redo" : `Redid ${step.label || "change"}`);
  }

  /** A repeat of the same message toggles a trailing no-break space —
   *  identical text re-assigned is not re-announced by screen readers. */
  #announce(text: string): void {
    this.announcement = this.announcement === text ? `${text} ` : text;
  }

  /**
   * The designer-scoped chord handler (§3) — attached to the `.view-designer`
   * section, riding bubbling from whatever inside has focus, never
   * `svelte:window`. Chords inside a text input stay with the input's native
   * undo. Ctrl+Z → undo; Ctrl+Y and Ctrl+Shift+Z → redo (TipTap's redo — §3
   * uniformity).
   */
  handleKeydown = (event: KeyboardEvent): void => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    const key = event.key.toLowerCase();
    if (key !== "z" && key !== "y") return;
    if (isEditableTarget(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    if (key === "z" && !event.shiftKey) this.undo();
    else this.redo();
  };
}

// Deliberately NOT `<select>`: a select has no native undo, so swallowing the
// chord there would dead-zone Ctrl+Z at the exact moment an author wants to
// revert the option they just picked.
function isEditableTarget(t: EventTarget | null): boolean {
  return (
    t instanceof HTMLInputElement ||
    t instanceof HTMLTextAreaElement ||
    (t instanceof HTMLElement && t.isContentEditable)
  );
}
