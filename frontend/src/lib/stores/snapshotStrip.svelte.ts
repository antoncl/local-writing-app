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
import { confirmService } from "@/lib/stores/confirmService.svelte";
import type {
  DiffRun,
  DiffView,
  FieldDiff,
  LoreEntry,
  Scene,
  Snapshot,
  SnapshotDetail,
  SnapshotDrift,
  SnapshotList,
} from "@/lib/types";
import { adoptRegion, renderDiffRuns } from "@/lib/utils/diffRuns";
import { diffRuns, fieldDiffs } from "@/lib/utils/snapshotDiff";
import { inNotchOrder, notchWhen } from "@/lib/utils/snapshotTime";

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

/** The drift call itself failed, so the comparison could not be built. This is
 *  **not** `NO_DRIFT`: a failed fetch is not evidence of an unchanged world
 *  (ADR-0043 — "a live side that would not build is not evidence"), so it must
 *  degrade to `comparable:false`, which the rail surfaces as "couldn't compare",
 *  never swallow as the silent all-clear `available:false` would give. */
const DRIFT_UNCOMPARABLE: SnapshotDrift = {
  available: true,
  comparable: false,
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

/** How long a snapshot description may be.
 *
 *  Mirrors `SNAPSHOT_DESCRIPTION_MAX` in
 *  `backend/app/services/project/scene_snapshots.py`, which is the authority —
 *  it collapses to one line and truncates regardless of what the client sends.
 *  This exists so the input stops the author at the same point rather than
 *  accepting text the server will silently drop, and it lives here rather than
 *  inline in the markup so the pairing has one place to be found and changed. */
export const SNAPSHOT_DESCRIPTION_MAX = 280;

/** What a strip is bound to. A manuscript scene keeps its own `/scenes` routes —
 *  they carry the entity-drift witness the node routes deliberately do not
 *  (ADR-0087 §5). Any other snapshot-eligible kind uses the `/nodes` routes with
 *  an optional authoring `layer` for a book override's history (§3b). */
export type SnapshotTarget =
  | { kind: "scene"; sceneId: string }
  | { kind: "node"; nodeId: string; layer: string | null };

/** The document a restore hands back — a `Scene` from the scene routes, or the
 *  re-folded node from the node routes (lore is the only kind the surface
 *  restores today, ADR-0088 S1). The controller only forwards it to the host. */
export type RestoredDocument = Scene | LoreEntry;

/** The snapshot calls the controller makes, bound to one target. Built once per
 *  `load()` so the scene-vs-node dispatch lives in a single place and every
 *  method below just calls `#backend.*` (one traversal, not six). `drift` is
 *  `null` for a node target: the entity-drift witness is a scene concern with no
 *  node route, so a node park skips it and the client-side content diff still
 *  runs. `key` identifies the binding for the in-flight freshness guards. */
interface SnapshotBackend {
  key: string;
  list: () => Promise<SnapshotList>;
  read: (id: string) => Promise<SnapshotDetail>;
  drift:
    | ((
        id: string,
        dynamicContext: string[] | null,
        metadata: Record<string, unknown>,
        body: string,
      ) => Promise<SnapshotDrift>)
    | null;
  restore: (id: string) => Promise<RestoredDocument>;
  capture: (dynamicContext: string[] | undefined) => Promise<Snapshot>;
  pin: (id: string) => Promise<Snapshot>;
  describe: (id: string, description: string) => Promise<Snapshot>;
  del: (id: string) => Promise<SnapshotList>;
}

function sceneBackend(sceneId: string): SnapshotBackend {
  return {
    key: `scene:${sceneId}`,
    list: () => api.listSnapshots(sceneId),
    read: (id) => api.readSnapshot(sceneId, id),
    drift: (id, dyn, meta, body) => api.snapshotDrift(sceneId, id, dyn, meta, body),
    restore: (id) => api.restoreSnapshot(sceneId, id),
    capture: (dyn) => api.captureSnapshot(sceneId, dyn),
    pin: (id) => api.pinSnapshot(sceneId, id),
    describe: (id, description) => api.setSnapshotDescription(sceneId, id, description),
    del: (id) => api.deleteSnapshot(sceneId, id),
  };
}

function nodeBackend(nodeId: string, layer: string | null): SnapshotBackend {
  return {
    key: `node:${nodeId}:${layer ?? ""}`,
    list: () => api.listNodeSnapshots(nodeId, layer),
    read: (id) => api.readNodeSnapshot(nodeId, id, layer),
    // No node-scoped witness route (ADR-0087 §5): a node park skips the drift
    // call and keeps only the client-side content diff.
    drift: null,
    restore: (id) => api.restoreNodeSnapshot(nodeId, id, layer),
    // A non-scene node has no dynamic-context witness to send.
    capture: () => api.captureNodeSnapshot(nodeId, layer),
    pin: (id) => api.pinNodeSnapshot(nodeId, id, layer),
    describe: (id, description) => api.setNodeSnapshotDescription(nodeId, id, description, layer),
    del: (id) => api.deleteNodeSnapshot(nodeId, id, layer),
  };
}

function backendFor(target: SnapshotTarget): SnapshotBackend {
  return target.kind === "scene"
    ? sceneBackend(target.sceneId)
    : nodeBackend(target.nodeId, target.layer);
}

export class SnapshotStripController {
  /** Oldest first **by content time** (`inNotchOrder`) — the order the strip
   *  lays out, and therefore the order ← / → walk. Deliberately not the
   *  backend's listing order, which is by record time: that is the right key for
   *  thinning and the wrong one for a track laid out by age (#458). */
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
  /** Hand the restored document back to the host, which owns the buffer. A
   *  scene restore hands back the `Scene`; a node restore the re-folded node —
   *  the host dispatches by kind (ADR-0088 S1). */
  onRestored: ((restored: RestoredDocument) => void | Promise<void>) | null = null;
  /** Hand a re-projected body to the host after adopting a region (Amendment
   *  4). Distinct from `onRestored`: no backend round trip and no `Scene` — only
   *  the prose changes, and the host writes it into the buffer marked dirty. */
  onAdopt: ((body: string) => void | Promise<void>) | null = null;
  /** Read the buffer's current state for the diff. Deliberately NOT a flush:
   *  parking is a reading gesture, and writing the file to read it would touch
   *  mtime, which is what the session-gap capture trigger reads. */
  readLive: (() => LiveState) | null = null;

  /** The active binding — the target's api dispatch, built in `load()`. `null`
   *  before the first load and after a null load. Its `key` is the freshness
   *  token every in-flight guard compares against, in place of the old scene id. */
  #backend: SnapshotBackend | null = null;
  // Two monotonic tokens, because they guard two different things and sharing
  // one is a bug the author meets immediately.
  //
  // `#fetch` discards a diff for a notch already left. `#render` discards a
  // rendering for a view already left. They are independent: the author drives
  // *when* and *which* at once (§I), so a keypress lands mid-fetch constantly —
  // and with one shared token the flip cancelled the fetch it was waiting on,
  // leaving a parked notch with an empty overlay and no runs to flip.
  #fetch = 0;
  // A park that arrived before `load()` gave this controller a target (ADR-0090
  // Amendment 2 §2: a review item's source pane may be created by the same
  // gesture that parks it). Applied once, by the next `load()` that has a
  // backend; dropped by a `load(null)`.
  #pendingPark: string | null = null;
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

  /** (Re)load this target's snapshots, returning to Live. A bare scene id is
   *  accepted as shorthand for the scene target, so the manuscript call sites and
   *  their tests are unchanged. Returns a cancel fn for the caller's `$effect`
   *  teardown. */
  load(target: string | SnapshotTarget | null): () => void {
    const resolved: SnapshotTarget | null =
      target === null
        ? null
        : typeof target === "string"
          ? { kind: "scene", sceneId: target }
          : target;
    const backend = resolved ? backendFor(resolved) : null;
    this.#backend = backend;
    this.parked = null;
    this.#endPending();
    // `#clearDiff` cancels the in-flight fetch and render, which a target change
    // needs just as much as a return to Live does.
    this.#clearDiff();
    if (!backend) {
      this.snapshots = [];
      this.#pendingPark = null;
      return () => {};
    }
    void this.refresh();
    if (this.#pendingPark !== null) {
      const pending = this.#pendingPark;
      this.#pendingPark = null;
      void this.park(pending);
    }
    return () => {
      if (this.#backend?.key === backend.key) this.#backend = null;
    };
  }

  async refresh(): Promise<void> {
    const backend = this.#backend;
    if (!backend) return;
    try {
      const list = await backend.list();
      if (this.#backend?.key === backend.key) this.snapshots = inNotchOrder(list.snapshots);
    } catch {
      // A strip that cannot list is an empty strip, not an error dialog: the
      // author is writing, and this is a safety net rather than the task.
      if (this.#backend?.key === backend.key) this.snapshots = [];
    }
  }

  /** Park on a snapshot (or return to Live with `null`). Reading never touches
   *  the live buffer — it stays mounted and hidden underneath (§G).
   *
   *  **The content diff is computed here in the browser** (#573): `readSnapshot`
   *  hands over the frozen "was" side, the live buffer is the "now" side, and
   *  `diffRuns` / `fieldDiffs` produce the runs and the flip locally — no server
   *  round-trip for the prose. Drift is the one half that stays server-side (the
   *  "now" witness needs resolved entity state), so it rides a slim `.../drift`
   *  call in parallel. §G still puts the diff at the discrete moment the author
   *  parks; the runs carry all the text, so every later flip is a re-render. */
  async park(snapshotId: string | null): Promise<void> {
    const backend = this.#backend;
    if (snapshotId && !backend) {
      // No target yet — the pane is still mounting. Keep the intent for the
      // `load()` that follows rather than silently returning to Live.
      this.#pendingPark = snapshotId;
      return;
    }
    if (!snapshotId || !backend) {
      // Live needs no round trip, so it happens at once.
      this.parked = null;
      this.#endPending();
      this.#clearDiff();
      return;
    }
    const seq = ++this.#fetch;
    const fresh = () => seq === this.#fetch && this.#backend?.key === backend.key;
    this.pendingId = snapshotId;
    this.#watchForSlow();
    try {
      const live = this.readLive?.() ?? NO_LIVE;
      // The frozen side and the drift report in parallel. Drift is advisory
      // (ADR-0043), so a drift failure must not drop the author out of a snapshot
      // they can otherwise read — but it degrades to "couldn't compare", not to a
      // silent all-clear (a failed fetch is not evidence of an unchanged world).
      // A node target has no witness route (ADR-0087 §5): drift resolves straight
      // to NO_DRIFT and the client-side content diff below still runs. A missing
      // snapshot body cannot be rendered, so that one still throws.
      const driftPromise = backend.drift
        ? backend
            // The buffer (metadata + body) rides along so the now-witness reads
            // the same "now" the client-side flip below does, not stale disk (#581).
            .drift(snapshotId, live.dynamic_context ?? null, live.metadata, live.body)
            .catch(() => DRIFT_UNCOMPARABLE)
        : Promise.resolve(NO_DRIFT);
      const [snapshot, drift] = await Promise.all([backend.read(snapshotId), driftPromise]);
      if (!fresh()) return;
      const runs = diffRuns(snapshot.body, live.body);
      // Render before anything is shown, so the swap below is one step.
      const html = await renderDiffRuns(runs, this.view);
      if (!fresh()) return;
      this.#render++;
      this.runs = runs;
      this.fields = fieldDiffs(snapshot.metadata, snapshot.status, live.metadata, live.status);
      this.titleWas = snapshot.title;
      this.titleNow = live.title;
      this.drift = drift ?? NO_DRIFT;
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
   * Adopt one region while parked (ADR-0044 Amendment 4). `clicked` is the side
   * of the run the author clicked — the overlay reads it from the run's class.
   *
   * **No round trip.** The runs carry both versions, so this re-projects them
   * locally and re-renders from what is already in hand; the diff is never
   * re-requested, which is what keeps regions settled earlier from resurfacing.
   * When the scene actually changes (the snapshot side won), the new body rides
   * `onAdopt` into the buffer in the background — the same buffer restore writes,
   * so §G holds: the compare view is not an editing surface.
   *
   * `busy` guards the same gate restore/capture/pin use, for two reasons: it
   * serialises against those gestures (a click must not write the buffer
   * underneath an in-flight restore), and — because region ids are positional
   * and shift when one collapses — it blocks a second click landing before the
   * re-render repaints, which would otherwise resolve a stale id.
   */
  async adopt(regionId: number, clicked: "now" | "was"): Promise<void> {
    if (this.parked === null || this.busy) return;
    this.busy = true;
    try {
      const { runs, body } = adoptRegion(this.runs, regionId, clicked);
      this.runs = runs;
      if (body !== null) await this.onAdopt?.(body);
      await this.#renderBody();
    } catch {
      // Leave the strip as it was; a failed adopt must not move the author.
    } finally {
      this.busy = false;
    }
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
    const backend = this.#backend;
    if (!backend || this.busy) return;
    this.busy = true;
    try {
      await this.flushScene?.();
      // The camera witnesses the same world an automatic capture does, so an
      // explicit snapshot is not the weaker record of the two. (A node backend
      // ignores the dynamic context — a non-scene node carries no witness, §5.)
      await backend.capture(this.readLive?.()?.dynamic_context);
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
    const backend = this.#backend;
    const snapshotId = this.parked;
    if (!backend || !snapshotId || this.busy) return false;
    this.busy = true;
    try {
      await this.flushScene?.();
      const restored = await backend.restore(snapshotId);
      await this.onRestored?.(restored);
      await this.refresh();
      await this.park(null);
      return true;
    } catch {
      return false;
    } finally {
      this.busy = false;
    }
  }

  // ---- author gestures: pin · describe · delete (ADR-0043 Amdt 1, #468) -----
  //
  // All three act on the parked notch and on nothing else — delete is reachable
  // only here, the same rule restore follows, so "the report is on screen when
  // you act" holds for every gesture. None flushes: they touch the sidecar's
  // authorial half, not the scene file, so there is no buffer to lose.

  /** Pin the parked automatic snapshot so thinning cannot drop it. The notch
   *  redraws as `kept` (taller, a step darker) under the author's cursor —
   *  honest feedback that the tier changed. One-directional: no unpin, because
   *  `kept` is exactly "not thinnable" and there is no explicit/automatic origin
   *  to fall back to. The button that offers it is shown only on a `thinned`
   *  notch, so a pinned one simply stops offering it. */
  async pin(): Promise<void> {
    const backend = this.#backend;
    const id = this.parked;
    if (!backend || !id || this.busy) return;
    this.busy = true;
    try {
      await backend.pin(id);
      await this.refresh();
    } catch {
      // Leave the strip as it was; a failed pin must not move the author.
    } finally {
      this.busy = false;
    }
  }

  /** Set (or clear, with `""`) the parked snapshot's one-line description.
   *
   *  **The unchanged-text guard lives here, not in the component**, so it is
   *  reachable by a test: the strip has no component harness, and a guard in
   *  the blur handler could be dropped with the suite still green. Closing the
   *  editor without editing is the common gesture, and it must cost neither a
   *  sidecar write nor a re-list. */
  async describe(description: string): Promise<void> {
    const backend = this.#backend;
    const id = this.parked;
    if (!backend || !id || this.busy) return;
    const next = description.trim();
    if (next === (this.current?.description ?? "")) return;
    this.busy = true;
    try {
      await backend.describe(id, next);
      await this.refresh();
    } catch {
      // Leave the strip as it was.
    } finally {
      this.busy = false;
    }
  }

  /** Delete the parked snapshot. **The one gesture that confirms**, because it
   *  is the one that is irreversible — restore captures first and so does not.
   *  The confirmation names what is going (ADR-0043). Deliberately no
   *  "don't show again": a gate in front of the only irreversible action is the
   *  one place the click-through habit has not already been spent. */
  del(): void {
    const backend = this.#backend;
    const id = this.parked;
    const target = this.current;
    if (!backend || !id || !target || this.busy) return;
    const when = notchWhen(target);
    const named = target.description ? `“${target.description}” (${when})` : `the snapshot from ${when}`;
    confirmService.request({
      title: "Delete snapshot",
      message: `Delete ${named}? Its words are the only copy — this cannot be undone.`,
      confirmLabel: "Delete snapshot",
      destructive: true,
      cannotBeUndone: true,
      // Capture the binding now: the confirm resolves later, and by then the
      // author may have moved to another node — delete must still target the one
      // they confirmed, not wherever they landed.
      onConfirm: () => this.#removeParked(backend, id),
    });
  }

  async #removeParked(backend: SnapshotBackend, id: string): Promise<void> {
    this.busy = true;
    try {
      await backend.del(id);
      // Back to Live first — the parked id no longer exists — then re-list so
      // the gap is gone from the strip.
      await this.park(null);
      await this.refresh();
    } finally {
      this.busy = false;
    }
  }
}
