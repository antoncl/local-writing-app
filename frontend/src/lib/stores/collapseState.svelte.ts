// Per-view fold-state persistence (ADR-0036 / #112). A pane that renders a view
// through ViewNodeList binds this controller's `collapsed` set into the wrapper;
// the controller seeds it from the view's persisted `ui.collapsed`, and — as the
// user folds/unfolds — debounces a lock-free PUT /api/views/{id}/ui back. For a
// pane's *default* (unselected) view the id is `view_default_<kind>`, which the
// backend materializes on the first write (so nothing exists until the user
// actually folds something).
//
// Reusable + instance-scoped: each rendering pane owns one. The change-detection
// lives in a component `$effect` that calls `observe()` (which reads the set, so
// the effect tracks it); the controller compares against the last-persisted
// snapshot so returning to the seed state, or to any persisted state, is a no-op.

import { SvelteSet } from "svelte/reactivity";
import { api } from "@/lib/api";

const DEBOUNCE_MS = 600;

function snapshot(set: Iterable<string>): string {
  return [...set].sort().join("\n");
}

export class CollapseState {
  // The live collapsed ViewGroup.key set — pass straight to ViewNodeList.
  collapsed = new SvelteSet<string>();

  #viewId: string | null = null;
  // Serialized set as last written to (or seeded from) disk; a write is skipped
  // while the live set matches it (covers "returned to the seed/persisted state").
  #lastPersisted = "";
  #timer: ReturnType<typeof setTimeout> | null = null;

  // Point the controller at a view id and seed `collapsed` from its persisted
  // fold state. Flushes any pending write for the previous view first. A 404
  // (unmaterialized default) or missing `ui` seeds an empty set. Idempotent per
  // id, and race-guarded against a fast re-bind.
  async bind(viewId: string): Promise<void> {
    if (viewId === this.#viewId) return;
    await this.flush();
    this.#viewId = viewId;
    let seed: string[] = [];
    try {
      seed = (await api.getView(viewId)).ui?.collapsed ?? [];
    } catch {
      seed = []; // 404 (no file yet) or transient — start expanded.
    }
    if (this.#viewId !== viewId) return; // a newer bind won.
    this.#lastPersisted = snapshot(seed);
    this.collapsed.clear();
    for (const key of seed) this.collapsed.add(key);
  }

  // Called from a component `$effect`: reads the set (so the effect tracks it)
  // and schedules a persist when it diverges from what's on disk.
  observe(): void {
    const snap = snapshot(this.collapsed);
    if (snap === this.#lastPersisted) return;
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = setTimeout(() => {
      this.#timer = null;
      void this.#write();
    }, DEBOUNCE_MS);
  }

  // Persist any pending write immediately (call on unmount).
  async flush(): Promise<void> {
    if (this.#timer === null) return;
    clearTimeout(this.#timer);
    this.#timer = null;
    await this.#write();
  }

  async #write(): Promise<void> {
    if (!this.#viewId) return;
    const snap = snapshot(this.collapsed);
    if (snap === this.#lastPersisted) return;
    try {
      await api.updateViewUi(this.#viewId, { collapsed: [...this.collapsed] });
      this.#lastPersisted = snap;
    } catch {
      // Fold state is disposable — a failed persist just retries on the next change.
    }
  }
}
