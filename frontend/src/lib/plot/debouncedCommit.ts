// Debounced commit (#2043 slice 3): the plot board's plotline and arc nodes edit their
// beats through BodyListSection, whose prose editors write per keystroke. Each write
// lands on the node's draft at once, but the SAVE behind it is coalesced: `schedule`
// (re)arms one timer, `flush` runs a pending commit now (a collapse, a destroy — the
// moments the editor goes away and coalescing is moot), `cancel` drops it. One helper
// for both nodes so the flush points can't drift between them.
export type DebouncedCommit = {
  schedule: () => void;
  flush: () => void;
  cancel: () => void;
  readonly pending: boolean;
};

export function createDebouncedCommit(run: () => void, delayMs: number): DebouncedCommit {
  let timer: ReturnType<typeof setTimeout> | null = null;
  function cancel(): void {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }
  function flush(): void {
    if (timer === null) return;
    cancel();
    run();
  }
  function schedule(): void {
    cancel();
    timer = setTimeout(() => {
      timer = null;
      run();
    }, delayMs);
  }
  return {
    schedule,
    flush,
    cancel,
    get pending() {
      return timer !== null;
    },
  };
}
