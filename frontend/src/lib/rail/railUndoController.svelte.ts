// Undo/redo for a node editor's metadata rail (#2438, ADR-0050). One history
// per editor pane — the pane's NodeEditor owns the controller and `reset()`s it
// whenever the pane shows a different node or the node's metadata is reloaded
// from disk (old commands would restore values onto the wrong document).
//
// Commands are per FIELD, never whole-metadata snapshots (ADR-0050 §1): a step
// records each changed key's before/after value, and its inverse writes only
// those keys back onto the CURRENT metadata. Undoing a tag removal therefore
// leaves a field edited afterwards alone. A replay writes through the port's
// `apply*` (the editor's own state + autosave), never back through the
// recording entry point — the caretaker throws on `record` during a replay.
//
// One field-edit session (open a text field → type → leave) is one step: the
// rail passes a session id with each write, and consecutive commands sharing it
// collapse through the caretaker's transaction mechanism.
//
// The caretaker glue (control state, announcement, busy-gated undo/redo, the
// rail-scoped chord) is the shared `SurfaceUndo`; this adds the recorders and
// the lock.
//
// Out of scope by design: the title (its input has native undo), the body (its
// own TipTap/CodeMirror history), stop edits (they write the mutation set),
// layer-override resets (a server save), entry-type changes, AI-review adoption.
import { SurfaceUndo } from "@/lib/stores/surfaceUndo.svelte";
import type { Command } from "@/lib/stores/undoCaretaker.svelte";
import type { EntryMetadata, MetadataValue } from "@/lib/types";

export type RailUndoPort = {
  getMetadata: () => EntryMetadata;
  applyMetadata: (next: EntryMetadata) => void;
  getStatus: () => string;
  applyStatus: (next: string) => void;
  fieldLabel: (fieldId: string) => string;
  // True while the rail must not take a base-metadata reversal: read-only, or
  // parked at a mutation stop (rail writes then target the stop's set).
  locked: () => boolean;
};

type FieldChange = { key: string; had: boolean; before: MetadataValue; hasAfter: boolean; after: MetadataValue };

function clone<T>(value: T): T {
  return value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T);
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export class RailUndoController extends SurfaceUndo {
  readonly #port: RailUndoPort;

  /** Bumped on every record, so the rail host can keep the chord reachable
   *  when the clicked control vanished with the change (focus fell to body). */
  recorded = $state(0);

  constructor(port: RailUndoPort) {
    super();
    this.#port = port;
  }

  protected override locked(): boolean {
    return this.#port.locked();
  }

  /** Drop the history — a different node, or the node reloaded from disk. */
  override reset(): void {
    super.reset();
    this.announcement = "";
  }

  override record(command: Command): void {
    super.record(command);
    this.recorded += 1;
  }

  /** A rail metadata write: `before` is the metadata just replaced, `next` the
   *  new one. Records one command over the keys that changed (none → nothing). */
  recordMetadata(before: EntryMetadata, next: EntryMetadata, session?: string): void {
    const keys = new Set([...Object.keys(before), ...Object.keys(next)]);
    const changes: FieldChange[] = [];
    for (const key of keys) {
      const had = key in before;
      const hasAfter = key in next;
      if (had === hasAfter && same(before[key], next[key])) continue;
      changes.push({ key, had, before: clone(before[key]), hasAfter, after: clone(next[key]) });
    }
    if (changes.length === 0) return;
    const label = `${changes.map((c) => this.#port.fieldLabel(c.key)).join(", ")} change`;
    const write = (side: "before" | "after") => {
      const current = { ...this.#port.getMetadata() };
      for (const c of changes) {
        const present = side === "before" ? c.had : c.hasAfter;
        if (present) current[c.key] = clone(c[side]);
        else delete current[c.key];
      }
      this.#port.applyMetadata(current);
    };
    this.record({
      label,
      transaction: session ? `rail:${session}` : undefined,
      undo: () => write("before"),
      redo: () => write("after"),
    });
  }

  /** A status change from the rail's status control. */
  recordStatus(before: string, next: string): void {
    if (before === next) return;
    this.record({
      label: "Status change",
      undo: () => this.#port.applyStatus(before),
      redo: () => this.#port.applyStatus(next),
    });
  }
}
