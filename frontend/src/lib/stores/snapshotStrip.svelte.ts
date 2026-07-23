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
import type { DiffRun, DiffView, FieldDiff, Scene, Snapshot, SnapshotDrift } from "@/lib/types";
import { renderDiffRuns } from "@/lib/utils/diffRuns";

/** What the diff compares the snapshot against: the buffer, not the file.
 *  Autosave lags by up to six seconds and parking must not write. */
export type LiveState = {
  body: string;
  title: string;
  status: string;
  metadata: Record<string, unknown>;
  /** The lore entries the editor currently detects in the prose — the *now*
   *  side of the witness's dynamic axis (#439). Omitted when no prose editor
   *  reported: the backend keeps *not observed* distinct from *observed and
   *  empty*, and narrows membership drift rather than claiming a removal. */
  dynamic_context?: string[];
};

const NO_LIVE: LiveState = { body: "", title: "", status: "", metadata: {} };

/** No comparison was possible — the default until a park lands. */
const NO_DRIFT: SnapshotDrift = {
  available: false,
  comparable: true,
  truncated: false,
  entities: [],
};

/** How long a park may take before the pane admits it is working.
 *
 *  Anton's call, and the reasoning is that below a couple of seconds an
 *  indicator is worse than nothing: it flashes on every notch and reads as the
 *  app being slow rather than as it being busy. Past it the click looks
 *  unacknowledged, which is the only case worth spending an affordance on. */
const SLOW_PARK_MS = 2000;

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
  /** The title on each side. It flips like any other field — the colour means
   *  temporal provenance everywhere, and location carries the subject (§F). */
  titleWas = $state("");
  titleNow = $state("");

  // ---- the drift report (ADR-0043, #439) ------------------------------------
  //
  // It arrives on the diff payload rather than from a route of its own. A
  // restore is only reachable from a parked notch, and parking is what fetches
  // this — so ADR-0043's "restore reports drift" costs no extra request and the
  // report is already on screen when the author decides.
  //
  // Advisory throughout: it never gates `restore()`, and there is no
  // acknowledgement to clear.
  drift = $state<SnapshotDrift>(NO_DRIFT);

  /** Whether there is anything to say about the world underneath this notch —
   *  including the two things that are not findings but are still claims: that
   *  the comparison could not be made, and that it was **incomplete**.
   *
   *  `truncated` is load-bearing here. Gating on `entities.length` alone made a
   *  truncated-but-otherwise-clean report unrenderable, so the author read
   *  silence as "nothing else changed" — the one inference a truncated witness
   *  must never allow. */
  hasDriftToReport = $derived(
    this.parked !== null &&
      this.drift.available &&
      (!this.drift.comparable || this.drift.truncated || this.drift.entities.length > 0),
  );

  /** Whether the title itself changed. Colour only, never a glyph (§J). */
  titleDiffers = $derived(this.parked !== null && this.titleWas !== this.titleNow);
  /** The title for the version currently being read. */
  titleForView = $derived(this.view === "was" ? this.titleWas : this.titleNow);

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
  // Two monotonic tokens, because they guard two different things and sharing
  // one is a bug the author meets immediately.
  //
  // `#fetch` discards a diff for a notch already left. `#render` discards a
  // rendering for a view already left. They are independent: the author drives
  // *when* and *which* at once (§I), so a keypress lands mid-fetch constantly —
  // and with one shared token the flip cancelled the fetch it was waiting on,
  // leaving a parked notch with an empty overlay and no runs to flip.
  #fetch = 0;
  #render = 0;

  // ---- entering compare mode (#409 review) ----------------------------------
  //
  // **Parking does not switch the view until the payload is in hand.** It used
  // to set `parked` synchronously, so the pane entered compare mode a whole
  // round trip before it had anything to show: an empty title bar and an empty
  // page under a ribbon already naming the snapshot, and — stepping notch to
  // notch — the PREVIOUS snapshot's body and tints under the new one's
  // timestamp. Every one of those is the screen saying something untrue, on the
  // surface whose whole job is to be trusted about what changed.
  //
  // Swapping only once the runs are rendered removes all three at once and
  // needs no "pending" flag for consumers to remember to honour.
  /** The notch being fetched, while the view still shows where the author was. */
  pendingId = $state<string | null>(null);
  /** Whether that fetch has gone on long enough to be worth admitting to. */
  slow = $state(false);
  #slowTimer: ReturnType<typeof setTimeout> | null = null;

  #watchForSlow(): void {
    this.#stopWatchingForSlow();
    this.#slowTimer = setTimeout(() => {
      this.slow = true;
    }, SLOW_PARK_MS);
  }

  #stopWatchingForSlow(): void {
    if (this.#slowTimer !== null) clearTimeout(this.#slowTimer);
    this.#slowTimer = null;
  }

  #endPending(): void {
    this.#stopWatchingForSlow();
    this.pendingId = null;
    this.slow = false;
  }

  /** (Re)load this scene's snapshots, returning to Live. Returns a cancel fn
   *  for the caller's `$effect` teardown. */
  load(sceneId: string | null): () => void {
    this.#sceneId = sceneId;
    this.parked = null;
    this.#endPending();
    // `#clearDiff` cancels the in-flight fetch and render, which a scene change
    // needs just as much as a return to Live does.
    this.#clearDiff();
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
    if (!snapshotId || !sceneId) {
      // Live needs no round trip, so it happens at once.
      this.parked = null;
      this.#endPending();
      this.#clearDiff();
      return;
    }
    const seq = ++this.#fetch;
    const fresh = () => seq === this.#fetch && this.#sceneId === sceneId;
    this.pendingId = snapshotId;
    this.#watchForSlow();
    try {
      const diff = await api.diffSnapshot(sceneId, snapshotId, this.readLive?.() ?? NO_LIVE);
      if (!fresh()) return;
      // Render before anything is shown, so the swap below is one step.
      const html = await renderDiffRuns(diff.runs, this.view);
      if (!fresh()) return;
      this.#render++;
      this.runs = diff.runs;
      this.fields = diff.fields;
      this.titleWas = diff.title_was;
      this.titleNow = diff.title_now;
      this.drift = diff.drift ?? NO_DRIFT;
      this.bodyHtml = html;
      this.parked = snapshotId;
    } catch {
      // Can't read it → stay where the author already was rather than dropping
      // them somewhere neither state explains.
    } finally {
      if (fresh()) this.#endPending();
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
    if (this.parked !== null) void this.#renderBody();
  }

  /** Render the runs into the overlay at the current view. Guarded on its own
   *  token so a slow render for a view already left cannot land, and so it
   *  cannot cancel an in-flight fetch. */
  async #renderBody(): Promise<void> {
    const seq = ++this.#render;
    const html = await renderDiffRuns(this.runs, this.view);
    if (seq === this.#render) this.bodyHtml = html;
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

  /**
   * Drop the compare payload and cancel anything still on its way to replace it.
   *
   * **Bumping both tokens is the point**, not housekeeping. Clearing the fields
   * without them left an in-flight fetch and an in-flight render still passing
   * their own freshness checks, so returning to Live repopulated everything this
   * just emptied — and the next notch then rendered the *previous* snapshot's
   * body, tint and field pairs under its own timestamp until its fetch landed.
   * `load()` always bumped them; the Live path is the one that did not.
   */
  #clearDiff(): void {
    // `view` deliberately survives — see the field's comment.
    this.#fetch++;
    this.#render++;
    this.bodyHtml = "";
    this.runs = [];
    this.fields = {};
    this.titleWas = "";
    this.titleNow = "";
    this.drift = NO_DRIFT;
  }

  /** ← → along the time axis. Right past the newest lands on Live (§I), which
   *  is why this walks the index rather than wrapping. */
  step(direction: -1 | 1): void {
    if (this.snapshots.length === 0) return;
    // While a park is in flight the author's position is the one they are
    // moving TO; stepping again from the old one would walk backwards.
    const from = this.pendingId ?? this.parked;
    if (from === null) {
      // From Live, only ← means anything: it steps back onto the newest.
      if (direction === -1) void this.park(this.snapshots[this.snapshots.length - 1].id);
      return;
    }
    const fromIndex = this.snapshots.findIndex((item) => item.id === from);
    const next = fromIndex + direction;
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
      // The camera witnesses the same world an automatic capture does, so an
      // explicit snapshot is not the weaker record of the two.
      await api.captureSnapshot(sceneId, this.readLive?.()?.dynamic_context);
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
