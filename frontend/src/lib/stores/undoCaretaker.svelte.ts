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
 *  oblivious to what they touch.
 *
 *  Two rules the closures' author must honour, because the caretaker cannot:
 *  - A recreated node returns with its **same id**, so edges re-added
 *    alongside it reconnect instead of dangling (§6).
 *  - A closure mutates state **directly** — never through a committer that
 *    `record`s. Recording from inside a replay would corrupt the log, so the
 *    caretaker throws on it rather than corrupt silently. */
export type Command = {
  undo: () => void;
  redo: () => void;
  /** Short human phrase — "delete node", "move node" — for the affordance
   *  tooltip and the `aria-live` announcement (§7). Omitting it degrades the
   *  announcement to a generic Undo/Redo, so it is encouraged, not required.
   *  When a transaction run reverses as one step, the announced label is the
   *  **last labelled command in the run** — put the gesture's name on the
   *  run's concluding command (a delete cascade ends on "delete node"). */
  label?: string;
  /** Implicit transaction membership (§4). Consecutive commands sharing an id
   *  collapse into one undo step; the run closes when the next command
   *  arrives without it — and any `undo()`/`redo()` closes it too, since a
   *  cascade is synchronous and no user action can land inside one. Closure
   *  is tracked at record time, so a closed run never reopens — not even
   *  when an undo discards the command that closed it. Absent or empty means
   *  the command is its own single step. */
  transaction?: string;
};

/** What `undo()`/`redo()` hand back for the §7 announcement: the reversed
 *  step happened, and `label` names it (`""` when no command in the run
 *  carried one). `null` from those methods means nothing happened at all —
 *  an object-or-null return so "undone but unlabelled" and "nothing to undo"
 *  can never be conflated by a truthiness check. */
export type ReversedStep = { label: string };

/** Memory backstop (§ Open). Counts commands, not steps, because commands are
 *  what hold captured state; generous because a command is small (closures
 *  over one node's worth of state) and the designer's graphs are tens of
 *  nodes. */
const DEFAULT_CAP = 200;

/** A recorded command plus the step it belongs to. `step` is resolved at
 *  record time — commands sharing a step number reverse as one — so run
 *  membership is a fact of the log, not something re-derived from id
 *  adjacency later (which an undo-fork could silently rejoin). */
type LogEntry = { command: Command; step: number };

export class UndoCaretaker {
  /** Executed commands in record order, with a cursor: everything below
   *  `#cursor` is undoable, everything at and above it is redoable.
   *  `$state.raw` deliberately: the array is only ever reassigned wholesale,
   *  and deep-proxying caller-owned commands (and their closures) would buy
   *  nothing while retaining a proxy per command for the stack's lifetime. */
  #log = $state.raw<LogEntry[]>([]);
  #cursor = $state(0);
  readonly #cap: number;

  #stepCounter = 0;
  /** The transaction id still accepting commands, if any — the record-time
   *  closure state the `transaction` doc describes. */
  #openId: string | undefined;
  #openStep = 0;
  /** True while undo/redo executes closures; `record` throws under it. */
  #replaying = false;

  /** Drive a disabled undo/redo button (§7) — the availability of undo is
   *  perceivable, not hidden behind a keystroke that silently no-ops. */
  canUndo = $derived(this.#cursor > 0);
  canRedo = $derived(this.#cursor < this.#log.length);

  /** `cap` is overridable for tests; consumers take the default. */
  constructor(cap: number = DEFAULT_CAP) {
    this.#cap = cap;
  }

  /** Log an already-performed change. Anything above the cursor — the redo
   *  stack — is discarded: after an undo, a new action forks history and the
   *  undone future is gone (standard undo semantics, and what keeps redo from
   *  ever replaying onto a state it no longer matches). */
  record(command: Command): void {
    if (this.#replaying) {
      throw new Error(
        "record() during undo/redo — a reversal closure must mutate state directly, " +
          "never through a committer that records",
      );
    }
    // `|| undefined` folds `""` (and a JS caller's null) into "no
    // transaction" — a groupable falsy id would merge unrelated gestures.
    const id = command.transaction || undefined;
    const step = id !== undefined && id === this.#openId ? this.#openStep : ++this.#stepCounter;
    this.#openId = id;
    this.#openStep = step;

    const kept = this.#log.slice(0, this.#cursor);
    kept.push({ command, step });
    // Enforce the cap by dropping whole steps from the oldest end — never a
    // partial transaction, which would leave a half-reversible cascade at the
    // bottom of the stack, and never the newest step: the cap is a backstop on
    // *history*, and taking the gesture just performed would break the one
    // promise the feature makes. A cascade longer than the whole cap simply
    // overshoots until the next step arrives and it becomes droppable history.
    while (kept.length > this.#cap) {
      const dropCount = this.#stepBounds(kept, 0).end + 1;
      if (dropCount >= kept.length) break;
      kept.splice(0, dropCount);
    }
    this.#log = kept;
    this.#cursor = kept.length;
  }

  /** Reverse one step — a lone command, or a whole shared-step run LIFO (§4:
   *  recreate self → re-add edge b → re-add edge a). Returns the reversed
   *  step for the `aria-live` announcement, or `null` when there was nothing
   *  to undo.
   *
   *  If a closure throws, the exception propagates, but the cursor stays
   *  consistent with the closures that actually ran — a retry continues the
   *  step from where it broke instead of double-executing what succeeded. */
  undo(): ReversedStep | null {
    if (this.#cursor === 0) return null;
    this.#openId = undefined;
    const end = this.#cursor - 1;
    const { start } = this.#stepBounds(this.#log, end);
    let i = end;
    this.#replaying = true;
    try {
      for (; i >= start; i--) {
        this.#log[i].command.undo();
      }
    } finally {
      this.#replaying = false;
      // On success i has walked past start; on a throw at i, everything
      // above i is undone and i itself still counts as applied.
      this.#cursor = i + 1;
    }
    return { label: this.#stepLabel(start, end) };
  }

  /** Replay one step forward — the same run `undo` reversed, in record order.
   *  Returns and errs like `undo`. */
  redo(): ReversedStep | null {
    if (this.#cursor >= this.#log.length) return null;
    this.#openId = undefined;
    const start = this.#cursor;
    const { end } = this.#stepBounds(this.#log, start);
    let i = start;
    this.#replaying = true;
    try {
      for (; i <= end; i++) {
        this.#log[i].command.redo();
      }
    } finally {
      this.#replaying = false;
      // On success i has walked past end; on a throw at i, everything below
      // i is applied and i itself is not.
      this.#cursor = i;
    }
    return { label: this.#stepLabel(start, end) };
  }

  /** The maximal run of entries sharing `log[index]`'s step — the one place
   *  run membership is defined. Step numbers are unique per run, so equality
   *  is the whole test. */
  #stepBounds(log: LogEntry[], index: number): { start: number; end: number } {
    const step = log[index].step;
    let start = index;
    while (start > 0 && log[start - 1].step === step) start--;
    let end = index;
    while (end + 1 < log.length && log[end + 1].step === step) end++;
    return { start, end };
  }

  /** The last labelled command in the run wins — see `Command.label`. */
  #stepLabel(start: number, end: number): string {
    for (let i = end; i >= start; i--) {
      const label = this.#log[i].command.label;
      if (label) return label;
    }
    return "";
  }
}
