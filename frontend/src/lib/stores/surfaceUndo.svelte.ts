// The per-surface undo glue every caretaker surface shares (ADR-0050): one
// `UndoCaretaker` history, the §7 visible-control state (can/titles/busy) and
// aria-live announcement, busy-gated undo/redo, and the §3 surface-scoped
// chord handler. The node canvases (`GraphUndoController`) and the metadata
// rail (`RailUndoController`, #2438) extend it with their own gesture
// recorders; the caretaker itself stays domain-agnostic.
import { UndoCaretaker, UndoCancelled, type Command } from "@/lib/stores/undoCaretaker.svelte";
import { undoChordOf } from "@/lib/utils/undoChord";

export class SurfaceUndo {
  // Reassigned wholesale on reset — one caretaker per loaded document (§3:
  // per-surface history; a fresh instance keeps one document's history from
  // bleeding into the next).
  #caretaker = $state(new UndoCaretaker());

  /** What the `aria-live` region reads out (§7). */
  announcement = $state("");

  /** A surface that must not take a reversal right now (read-only, parked)
   *  overrides this; while true nothing is undoable and the chord is inert. */
  protected locked(): boolean {
    return false;
  }

  get canUndo(): boolean {
    return !this.locked() && this.#caretaker.canUndo;
  }
  get canRedo(): boolean {
    return !this.locked() && this.#caretaker.canRedo;
  }
  /** True while an async inverse call is in flight (ADR-0053 §7) — a
   *  backend-backed surface folds this into its control's disabled state so a
   *  second reversal can't start mid-flight. Layout-only surfaces never set it. */
  get busy(): boolean {
    return this.#caretaker.busy;
  }
  /** Resolves once no undo/redo is in flight (ADR-0053 §7). A backend-backed
   *  surface's committer awaits this before a fresh content op so the op queues
   *  behind an in-flight reversal instead of racing `record()`. */
  whenIdle(): Promise<void> {
    return this.#caretaker.whenIdle();
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

  /** Drop the history (a new document, or the old one's history no longer applies). */
  reset(): void {
    this.#caretaker = new UndoCaretaker();
  }

  /** Record a command (AFTER the actor applied it — §1 self-report). */
  record(command: Command): void {
    this.#caretaker.record(command);
  }

  /** Async so a backend-backed inverse completes before the announcement (§7);
   *  a no-op for sync surfaces (the awaited closures resolve at once).
   *  Short-circuits while busy so a mashed chord doesn't announce a misleading
   *  "Nothing to undo" over an in-flight step. A closure that throws
   *  `UndoCancelled` (a declined destructive reversal, S6b) is announced as
   *  cancelled, not surfaced as an error — the caretaker left the step undoable. */
  async undo(): Promise<void> {
    if (this.locked() || this.#caretaker.busy) return;
    try {
      const step = await this.#caretaker.undo();
      this.#announce(step === null ? "Nothing to undo" : `Undid ${step.label || "change"}`);
    } catch (error) {
      if (error instanceof UndoCancelled) return void this.#announce("Undo cancelled");
      throw error;
    }
  }

  async redo(): Promise<void> {
    if (this.locked() || this.#caretaker.busy) return;
    try {
      const step = await this.#caretaker.redo();
      this.#announce(step === null ? "Nothing to redo" : `Redid ${step.label || "change"}`);
    } catch (error) {
      if (error instanceof UndoCancelled) return void this.#announce("Redo cancelled");
      throw error;
    }
  }

  /** A repeat of the same message toggles a trailing no-break space —
   *  identical text re-assigned is not re-announced by screen readers. */
  #announce(text: string): void {
    this.announcement = this.announcement === text ? `${text} ` : text;
  }

  /**
   * The surface-scoped chord handler (§3) — attached to the surface's own
   * element (`.view-designer`, `.plot-board`, the rail's scope), riding
   * bubbling from whatever inside has focus, never `svelte:window`, so one
   * surface's Ctrl+Z can't reach another's caretaker. Chords inside a text
   * input stay with the input's native undo (`undoChordOf`).
   */
  handleKeydown = (event: KeyboardEvent): void => {
    const chord = undoChordOf(event);
    if (!chord) return;
    event.preventDefault();
    event.stopPropagation();
    // Fire-and-forget: the chord is handled (preventDefault above); the async
    // reversal settles on its own and the caretaker's busy gate absorbs a mash.
    void (chord === "undo" ? this.undo() : this.redo());
  };
}
