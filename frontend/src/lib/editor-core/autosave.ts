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
  // Ceiling on how long a pane may stay dirty while the author keeps typing.
  // Required rather than optional: without it the idle debounce alone bounds
  // nothing, and that has to be a decision at every construction site rather
  // than a default someone can forget (#369).
  maxWaitMs: number;
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
  // Per-pane ceiling timers: at most one live per dirty run, never re-armed
  // while that run continues.
  #ceilingTimers = new Map<string, ReturnType<typeof setTimeout>>();
  #indicatorTimers = new Map<string, ReturnType<typeof setTimeout>>();

  constructor(opts: AutosaveSchedulerOptions) {
    this.#opts = opts;
  }

  // (Re)arm the idle debounce for a pane. Cancels any pending idle timer first,
  // then schedules a fresh one only if the pane currently wants saving. The
  // fire-time re-check via `shouldSave` guards against the pane no longer being
  // dirty (or having become a non-savable kind) by the time the timer elapses.
  //
  // The ceiling is armed once per dirty run and deliberately NOT re-armed by
  // later keystrokes. That asymmetry is the whole mechanism: the idle timer is
  // the one keystrokes push out, and the ceiling is the one they cannot. With
  // only the idle timer, an author typing without a full `idleMs` gap never
  // saves at all — the exposure is the length of the burst, not `idleMs` (#369).
  schedule(id: string): void {
    this.#clearIdle(id);
    if (!this.#opts.shouldSave(id)) {
      // Nothing to save any more, so the run is over and its ceiling with it.
      this.#clearCeiling(id);
      return;
    }
    this.#saveTimers.set(id, setTimeout(() => this.#fire(id), this.#opts.idleMs));
    if (!this.#ceilingTimers.has(id)) {
      this.#ceilingTimers.set(id, setTimeout(() => this.#fire(id), this.#opts.maxWaitMs));
    }
  }

  // Whichever timer got there first ends the run: both are dropped, then the
  // same fire-time `shouldSave` re-check applies.
  #fire(id: string): void {
    this.#clearIdle(id);
    this.#clearCeiling(id);
    if (!this.#opts.shouldSave(id)) return;
    this.#opts.save(id);
  }

  #clearIdle(id: string): void {
    const timer = this.#saveTimers.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.#saveTimers.delete(id);
    }
  }

  #clearCeiling(id: string): void {
    const timer = this.#ceilingTimers.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.#ceilingTimers.delete(id);
    }
  }

  // Cancel a pane's pending autosave (manual save / teardown). Ends the run, so
  // it drops the ceiling too — a pane that is being torn down or has just been
  // saved by hand has nothing left to bound.
  cancel(id: string): void {
    this.#clearIdle(id);
    this.#clearCeiling(id);
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
    for (const timer of this.#ceilingTimers.values()) clearTimeout(timer);
    for (const timer of this.#indicatorTimers.values()) clearTimeout(timer);
    this.#saveTimers.clear();
    this.#ceilingTimers.clear();
    this.#indicatorTimers.clear();
  }
}
