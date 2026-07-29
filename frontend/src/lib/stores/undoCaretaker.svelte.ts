// The undo/redo caretaker (ADR-0050, #678) — the domain-agnostic half of the
// command pattern. Actors self-report reversible changes as commands; this
// store only holds them and replays them backward/forward. Its entire
// vocabulary is "a reversible command" and "a transaction id" (§2): it never
// learns what a command reverses, which is what lets a second node surface
// (ADR-0048) mount the same class with its own command vocabulary.
//
// Named "caretaker" (the memento pattern's word) because "history" is already
// taken twice over in this repo — chat history and snapshot version history
// (ADR-0043/0044) are unrelated features.
//
// Per-surface instances, no app-wide bus (§3): each node surface constructs
// its own caretaker, the same way TipTap and CodeMirror each own their
// library's history. History is in-session only (§5) — commands carry
// closures, closures don't serialize, and that is uniform with the other
// body views rather than a regression.

/** A self-reported reversible change (ADR-0050 §5).
 *
 *  The actor performs its mutation first and then `record`s the command —
 *  recording never executes anything. `undo`/`redo` are reversal closures:
 *  the command captures whatever state it needs (a deleted node speaks at the
 *  instant of death, full state in hand — §1), and the caretaker stays
 *  oblivious to what they touch. The one invariant the closures' author must
 *  honour, because the caretaker cannot: a recreated node returns with its
 *  **same id**, so edges re-added alongside it reconnect instead of
 *  dangling (§6). */
export type Command = {
  undo: () => void;
  redo: () => void;
  /** Short human phrase — "delete node", "move node" — for the affordance
   *  tooltip and the `aria-live` announcement (§7). Omitting it degrades the
   *  announcement to a generic Undo/Redo, so it is encouraged, not required. */
  label?: string;
  /** Implicit transaction membership (§4). Consecutive commands sharing an id
   *  collapse into one undo step; the run closes when the next command
   *  arrives without it. Absent = the command is its own single step. A
   *  cascading gesture must mint a **fresh** id — two back-to-back gestures
   *  reusing one id would read as a single run. */
  transaction?: string;
};

/** Memory backstop (§ Open). Counts commands, not steps, because commands are
 *  what hold captured state; generous because a command is small (closures
 *  over one node's worth of state) and the designer's graphs are tens of
 *  nodes. */
const DEFAULT_CAP = 200;

export class UndoCaretaker {
  /** Executed commands in record order, with a cursor: everything below
   *  `#cursor` is undoable, everything at and above it is redoable. */
  #commands = $state<Command[]>([]);
  #cursor = $state(0);
  readonly #cap: number;

  /** Drive a disabled undo/redo button (§7) — the availability of undo is
   *  perceivable, not hidden behind a keystroke that silently no-ops. */
  canUndo = $derived(this.#cursor > 0);
  canRedo = $derived(this.#cursor < this.#commands.length);

  /** `cap` is overridable for tests; consumers take the default. */
  constructor(cap: number = DEFAULT_CAP) {
    this.#cap = cap;
  }

  /** Log an already-performed change. Anything above the cursor — the redo
   *  stack — is discarded: after an undo, a new action forks history and the
   *  undone future is gone (standard undo semantics, and what keeps redo from
   *  ever replaying onto a state it no longer matches). */
  record(command: Command): void {
    const kept = this.#commands.slice(0, this.#cursor);
    kept.push(command);
    // Enforce the cap by dropping whole steps from the oldest end — never a
    // partial transaction, which would leave a half-reversible cascade at the
    // bottom of the stack, and never the newest step: the cap is a backstop on
    // *history*, and taking the gesture just performed would break the one
    // promise the feature makes. A cascade longer than the whole cap simply
    // overshoots until the next step arrives and it becomes droppable history.
    while (kept.length > this.#cap) {
      const oldestStep = this.#stepEnd(kept, 0) + 1;
      if (oldestStep >= kept.length) break;
      kept.splice(0, oldestStep);
    }
    this.#commands = kept;
    this.#cursor = kept.length;
  }

  /** Reverse one step — a lone command, or a whole shared-id run LIFO (§4:
   *  recreate self → re-add edge b → re-add edge a). Returns the step's label
   *  for the `aria-live` announcement (`""` when no command in the run carried
   *  one), or `null` when there was nothing to undo. */
  undo(): string | null {
    if (this.#cursor === 0) return null;
    const end = this.#cursor - 1;
    const start = this.#stepStart(this.#commands, end);
    for (let i = end; i >= start; i--) {
      this.#commands[i].undo();
    }
    this.#cursor = start;
    return this.#stepLabel(start, end);
  }

  /** Replay one step forward — the same run `undo` reversed, in record order.
   *  Returns like `undo`. */
  redo(): string | null {
    if (this.#cursor >= this.#commands.length) return null;
    const end = this.#stepEnd(this.#commands, this.#cursor);
    const start = this.#cursor;
    for (let i = start; i <= end; i++) {
      this.#commands[i].redo();
    }
    this.#cursor = end + 1;
    return this.#stepLabel(start, end);
  }

  /** First index of the maximal consecutive same-transaction run containing
   *  `index`. An untagged command is a run of one. */
  #stepStart(commands: Command[], index: number): number {
    const id = commands[index].transaction;
    if (id === undefined) return index;
    let start = index;
    while (start > 0 && commands[start - 1].transaction === id) start--;
    return start;
  }

  /** Last index of that run. */
  #stepEnd(commands: Command[], index: number): number {
    const id = commands[index].transaction;
    if (id === undefined) return index;
    let end = index;
    while (end + 1 < commands.length && commands[end + 1].transaction === id) end++;
    return end;
  }

  /** A run's label is the **last** labelled command in it — a cascade ends on
   *  the command that names the gesture ("delete edge a", "delete edge b",
   *  then the labelled "delete node"). */
  #stepLabel(start: number, end: number): string {
    for (let i = end; i >= start; i--) {
      const label = this.#commands[i].label;
      if (label) return label;
    }
    return "";
  }
}
