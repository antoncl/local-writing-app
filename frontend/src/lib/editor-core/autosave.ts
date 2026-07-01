// Autosave scheduler — the debounce/timing heart of the editor panes, factored
// out of App.svelte (#14 P0) so the *timing* concern is separable from the
// editor domain (what a pane is, what "dirty" means, what "save" does). It owns
// only the per-key timers; the caller injects the three editor-specific hooks:
//   - `shouldSave(id)`  — is this pane dirty, idle, and of a savable kind? Re-run
//                         at fire time so a save that landed (or a switch to a
//                         non-savable kind) during the debounce window aborts.
//   - `save(id)`        — perform the save (already wrapped in the app's error
//                         runner by the caller).
//   - `clearIndicator(id)` — drop the pane's "recently saved" flag after the
//                         indicator window elapses.
//
// Pure timing, no reactive state, so this is a plain `.ts` unit — the reactive
// pane mutations happen inside the injected hooks.

export interface AutosaveSchedulerOptions {
  // Idle debounce before an autosave fires.
  idleMs: number;
  // How long the "Saved" indicator stays up after a successful save.
  indicatorMs: number;
  shouldSave: (id: string) => boolean;
  save: (id: string) => void;
  clearIndicator: (id: string) => void;
}

export class AutosaveScheduler {
  #opts: AutosaveSchedulerOptions;
  // Per-pane pending timers, keyed by pane id.
  #saveTimers = new Map<string, ReturnType<typeof setTimeout>>();
  #indicatorTimers = new Map<string, ReturnType<typeof setTimeout>>();

  constructor(opts: AutosaveSchedulerOptions) {
    this.#opts = opts;
  }

  // (Re)arm the idle debounce for a pane. Cancels any pending timer first, then
  // schedules a fresh one only if the pane currently wants saving. The fire-time
  // re-check via `shouldSave` guards against the pane no longer being dirty (or
  // having become a non-savable kind) by the time the timer elapses.
  schedule(id: string): void {
    this.cancel(id);
    if (!this.#opts.shouldSave(id)) return;
    const timer = setTimeout(() => {
      this.#saveTimers.delete(id);
      if (!this.#opts.shouldSave(id)) return;
      this.#opts.save(id);
    }, this.#opts.idleMs);
    this.#saveTimers.set(id, timer);
  }

  // Cancel a pane's pending autosave (manual save / teardown).
  cancel(id: string): void {
    const timer = this.#saveTimers.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.#saveTimers.delete(id);
    }
  }

  // Show the "Saved" indicator for `indicatorMs`, then clear it. Re-arming
  // resets the window so a fresh save extends it rather than stacking timers.
  flashSaved(id: string): void {
    const existing = this.#indicatorTimers.get(id);
    if (existing !== undefined) clearTimeout(existing);
    const timer = setTimeout(() => {
      this.#indicatorTimers.delete(id);
      this.#opts.clearIndicator(id);
    }, this.#opts.indicatorMs);
    this.#indicatorTimers.set(id, timer);
  }

  // Cancel a pending "Saved" indicator timer (pane teardown).
  cancelSavedIndicator(id: string): void {
    const timer = this.#indicatorTimers.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.#indicatorTimers.delete(id);
    }
  }

  // Clear every pending timer (app unmount / shutdown).
  dispose(): void {
    for (const timer of this.#saveTimers.values()) clearTimeout(timer);
    for (const timer of this.#indicatorTimers.values()) clearTimeout(timer);
    this.#saveTimers.clear();
    this.#indicatorTimers.clear();
  }
}
