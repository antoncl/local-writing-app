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
// Out of scope by design: the title (its input has native undo), the body (its
// own TipTap/CodeMirror history), stop edits (they write the mutation set),
// layer-override resets (a server save), entry-type changes, AI-review adoption.
import { UndoCaretaker, type Command } from "@/lib/stores/undoCaretaker.svelte";
import { undoChordOf } from "@/lib/utils/undoChord";
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

export class RailUndoController {
  #caretaker = $state(new UndoCaretaker());
  readonly #port: RailUndoPort;

  /** What the `aria-live` region reads out (§7). */
  announcement = $state("");
  /** Bumped on every record, so the rail host can keep the chord reachable
   *  when the clicked control vanished with the change (focus fell to body). */
  recorded = $state(0);

  constructor(port: RailUndoPort) {
    this.#port = port;
  }

  get canUndo(): boolean {
    return !this.#port.locked() && this.#caretaker.canUndo;
  }
  get canRedo(): boolean {
    return !this.#port.locked() && this.#caretaker.canRedo;
  }
  get undoTitle(): string {
    const label = this.#caretaker.undoLabel;
    return label ? `Undo ${label}` : "Undo";
  }
  get redoTitle(): string {
    const label = this.#caretaker.redoLabel;
    return label ? `Redo ${label}` : "Redo";
  }

  /** Drop the history — a different node, or the node reloaded from disk. */
  reset(): void {
    this.#caretaker = new UndoCaretaker();
    this.announcement = "";
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
    this.#record({
      label,
      transaction: session ? `rail:${session}` : undefined,
      undo: () => write("before"),
      redo: () => write("after"),
    });
  }

  /** A status change from the rail's status control. */
  recordStatus(before: string, next: string): void {
    if (before === next) return;
    this.#record({
      label: "Status change",
      undo: () => this.#port.applyStatus(before),
      redo: () => this.#port.applyStatus(next),
    });
  }

  #record(command: Command): void {
    this.#caretaker.record(command);
    this.recorded += 1;
  }

  async undo(): Promise<void> {
    if (this.#port.locked() || this.#caretaker.busy) return;
    const step = await this.#caretaker.undo();
    this.#announce(step === null ? "Nothing to undo" : `Undid ${step.label || "change"}`);
  }

  async redo(): Promise<void> {
    if (this.#port.locked() || this.#caretaker.busy) return;
    const step = await this.#caretaker.redo();
    this.#announce(step === null ? "Nothing to redo" : `Redid ${step.label || "change"}`);
  }

  #announce(text: string): void {
    this.announcement = this.announcement === text ? `${text} ` : text;
  }

  /** The rail-scoped chord handler (§3): attached to the rail's own wrapper,
   *  never `svelte:window`, so a chord in the body or another pane can't reach
   *  this history. Inside a text input the input's native undo keeps it. */
  handleKeydown = (event: KeyboardEvent): void => {
    const chord = undoChordOf(event);
    if (!chord) return;
    event.preventDefault();
    event.stopPropagation();
    void (chord === "undo" ? this.undo() : this.redo());
  };
}
