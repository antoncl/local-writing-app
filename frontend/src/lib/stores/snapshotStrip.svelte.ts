// Snapshot-strip state for one scene pane (ADR-0043 / ADR-0044, #401).
//
// A per-instance rune controller, the same shape as `LoreScrubController`: the
// pane owns its position on the strip. `parked === null` is **Live** — the
// editable buffer, the rest position — and any other value is a snapshot id,
// which flips the body to a read-only overlay. Position is the mode (§B).
//
// The strip is the scrubber's third axis: layer (ADR-0042), story time
// (ADR-0013), and here real time. Same gesture, different axis.
//
// **Why the two hooks.** Autosave writes on a 6-second idle debounce, so at any
// moment the file on disk can be a few keystrokes behind the buffer. Capture
// photographs the *file*; restore overwrites it. Either one run against a dirty
// pane would quietly drop the author's most recent words — the exact failure
// this feature exists to prevent — so both flush first, and the flush is the
// host's job because the pane store owns the document lifecycle.
import { api } from "@/lib/api";
import type { DiffRun, DiffView, FieldDiff, Scene, Snapshot } from "@/lib/types";
import { renderDiffRuns } from "@/lib/utils/diffRuns";

/** What the diff compares the snapshot against: the buffer, not the file.
 *  Autosave lags by up to six seconds and parking must not write. */
export type LiveState = { body: string; title: string; status: string; metadata: Record<string, unknown> };

const NO_LIVE: LiveState = { body: "", title: "", status: "", metadata: {} };

export class SnapshotStripController {
  /** Oldest first, as the backend lists them — the order the strip lays out. */
  snapshots = $state<Snapshot[]>([]);
  /** `null` = Live. Otherwise the parked snapshot's id. */
  parked = $state<string | null>(null);
  /** Rendered HTML of the parked snapshot's body, for the read-only overlay. */
  bodyHtml = $state("");
  busy = $state(false);

  // ---- the compare axis (ADR-0044 §F/§I, #409) ------------------------------
  //
  // `which version am I reading` — Active · Snapshot · Both. It is the SECOND
  // axis: `parked` is *when*, this is *which*, and the two are driven at once
  // (left hand on the letters, right hand on the arrows).
  //
  // **It survives stepping between notches.** Resetting to Both on each step
  // would fight exactly that two-handed gesture — the author picks a version to
  // read and then walks time in it.
  view = $state<DiffView>("both");
  /** Provenance-tagged runs from the last park. One payload serves all three
   *  view states, so a flip re-renders and never refetches. */
  runs = $state<DiffRun[]>([]);
  /** Only the fields whose value differs, both sides carried. */
  fields = $state<Record<string, FieldDiff>>({});

  index = $derived(
    this.parked === null ? -1 : this.snapshots.findIndex((item) => item.id === this.parked),
  );
  current = $derived(this.index < 0 ? null : this.snapshots[this.index]);

  /** Write any pending edits before a capture or a restore reads the file. */
  flushScene: (() => Promise<void>) | null = null;
  /** Hand the restored document back to the host, which owns the buffer. */
  onRestored: ((scene: Scene) => void | Promise<void>) | null = null;
  /** Read the buffer's current state for the diff. Deliberately NOT a flush:
   *  parking is a reading gesture, and writing the file to read it would touch
   *  mtime, which is what the session-gap capture trigger reads. */
  readLive: (() => LiveState) | null = null;

  #sceneId: string | null = null;
  // A monotonic token, so a slow read for a notch the author has already left
  // cannot overwrite the body they are looking at now.
  #seq = 0;

  /** (Re)load this scene's snapshots, returning to Live. Returns a cancel fn
   *  for the caller's `$effect` teardown. */
  load(sceneId: string | null): () => void {
    this.#sceneId = sceneId;
    this.parked = null;
    this.#clearDiff();
    this.#seq++;
    if (!sceneId) {
      this.snapshots = [];
      return () => {};
    }
    void this.refresh();
    return () => {
      if (this.#sceneId === sceneId) this.#sceneId = null;
    };
  }

  async refresh(): Promise<void> {
    const sceneId = this.#sceneId;
    if (!sceneId) return;
    try {
      const list = await api.listSnapshots(sceneId);
      if (this.#sceneId === sceneId) this.snapshots = list.snapshots;
    } catch {
      // A strip that cannot list is an empty strip, not an error dialog: the
      // author is writing, and this is a safety net rather than the task.
      if (this.#sceneId === sceneId) this.snapshots = [];
    }
  }

  /** Park on a snapshot (or return to Live with `null`). Reading never touches
   *  the live buffer — it stays mounted and hidden underneath (§G).
   *
   *  **This is the one call.** §G puts the diff at the discrete moment the
   *  author parks; diffing continuously against the buffer as they type would
   *  put an HTTP round-trip back in the typing loop. The runs carry all the
   *  text, so every later flip is a re-render of this payload. */
  async park(snapshotId: string | null): Promise<void> {
    const sceneId = this.#sceneId;
    this.parked = snapshotId;
    if (!snapshotId || !sceneId) {
      this.#clearDiff();
      return;
    }
    const seq = ++this.#seq;
    const fresh = () => seq === this.#seq && this.#sceneId === sceneId;
    try {
      const diff = await api.diffSnapshot(sceneId, snapshotId, this.readLive?.() ?? NO_LIVE);
      const html = await renderDiffRuns(diff.runs, this.view);
      if (fresh()) {
        this.runs = diff.runs;
        this.fields = diff.fields;
        this.bodyHtml = html;
      }
    } catch {
      // Can't read it → don't show a blank page pretending to be a snapshot.
      if (fresh()) {
        this.parked = null;
        this.#clearDiff();
      }
    }
  }

  /**
   * A · S · B — which version is being read.
   *
   * A pure version flip re-renders the body and the rail and **nothing else**.
   * It never refetches (the runs already carry both versions) and never touches
   * `snapshots`, so the strip's keyed `{#each}` cannot rebuild the notch track —
   * rebuilding it on a flip was half of the flicker the mockup hit.
   */
  setView(view: DiffView): void {
    if (view === this.view) return;
    this.view = view;
    if (this.parked === null) return;
    const seq = ++this.#seq;
    void renderDiffRuns(this.runs, view).then((html) => {
      if (seq === this.#seq) this.bodyHtml = html;
    });
  }

  /** `a` and `s` toggle against Both, so one key both enters and leaves a single
   *  version; `b` is the way back regardless of where you are. */
  toggleView(view: "now" | "was"): void {
    this.setView(this.view === view ? "both" : view);
  }

  /** The value to show for a changed field: the side currently being read. In
   *  `both` that is the live value — a field is atomic, so it flips rather than
   *  interleaving, and there is no third thing to show (§F). */
  fieldSide(): "now" | "was" {
    return this.view === "was" ? "was" : "now";
  }

  #clearDiff(): void {
    // `view` deliberately survives — see the field's comment.
    this.bodyHtml = "";
    this.runs = [];
    this.fields = {};
  }

  /** ← → along the time axis. Right past the newest lands on Live (§I), which
   *  is why this walks the index rather than wrapping. */
  step(direction: -1 | 1): void {
    if (this.snapshots.length === 0) return;
    if (this.parked === null) {
      // From Live, only ← means anything: it steps back onto the newest.
      if (direction === -1) void this.park(this.snapshots[this.snapshots.length - 1].id);
      return;
    }
    const next = this.index + direction;
    if (next >= this.snapshots.length) {
      void this.park(null);
      return;
    }
    void this.park(this.snapshots[Math.max(0, next)].id);
  }

  /** The camera. Returns to Live afterwards: the author marked *this* state, so
   *  the useful place to be is the one they were already in. */
  async capture(): Promise<void> {
    const sceneId = this.#sceneId;
    if (!sceneId || this.busy) return;
    this.busy = true;
    try {
      await this.flushScene?.();
      await api.captureSnapshot(sceneId);
      await this.refresh();
      await this.park(null);
    } catch {
      // Leave the strip as it was; a failed capture must not move the author.
    } finally {
      this.busy = false;
    }
  }

  /**
   * Restore the parked snapshot. **One call** — the backend captures the
   * current state and restores atomically; a client-side capture-then-restore
   * can half-fail into a snapshot nobody asked for (#395).
   *
   * No confirmation, deliberately: the restore is undoable *because* it
   * captured first, and a gate in front of a reversible action is the friction
   * that teaches people to click through gates (ADR-0043 Amendment 1).
   */
  async restore(): Promise<boolean> {
    const sceneId = this.#sceneId;
    const snapshotId = this.parked;
    if (!sceneId || !snapshotId || this.busy) return false;
    this.busy = true;
    try {
      await this.flushScene?.();
      const scene = await api.restoreSnapshot(sceneId, snapshotId);
      await this.onRestored?.(scene);
      await this.refresh();
      await this.park(null);
      return true;
    } catch {
      return false;
    } finally {
      this.busy = false;
    }
  }
}
