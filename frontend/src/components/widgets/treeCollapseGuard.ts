// Collapse defer-guard for ViewNodeTree (#112 step 4c-iv-c). A single-click on a
// collapsible row defers its toggle past the double-click window so a fast second
// click (which opens an editor / starts a rename) can cancel it — without the
// defer the row visibly toggles for a beat before the editor opens on top.
//
// Per-instance and non-reactive (just a timer): ViewNodeList owns one and threads
// it down. `defer` schedules the toggle; any row's double-click calls `cancel`.

const GUARD_MS = 200;

export class CollapseGuard {
  #timer: ReturnType<typeof setTimeout> | null = null;

  defer(toggle: () => void): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = setTimeout(() => {
      this.#timer = null;
      toggle();
    }, GUARD_MS);
  }

  cancel(): void {
    if (this.#timer !== null) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
  }
}
