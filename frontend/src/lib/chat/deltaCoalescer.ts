// #2294: batch a streaming reply's deltas into one state write per frame.
//
// Every write to a streaming message re-renders the WHOLE accumulated text
// (markdown parse + sanitize + KaTeX + an `{@html}` DOM swap) and the scroll
// pin forces a layout. Applied per delta, that is O(reply length) work per
// token — O(n²) over a reply — and a local model sending one token per delta
// froze the tab. Buffering to one write per animation frame caps the render
// rate at the display's, whatever the chunk rate.

export interface DeltaBatch {
  content: string;
  thinking: string;
}

export interface DeltaCoalescer {
  /** Buffer a content delta; schedules a flush if none is pending. */
  content(text: string): void;
  /** Buffer a thinking delta; schedules a flush if none is pending. */
  thinking(text: string): void;
  /** Apply whatever is buffered now (a no-op when empty). Call before any
   *  step that reads the message — `done`, the abort path, the empty check. */
  flush(): void;
  /** Drop the buffer unapplied — for when the message itself is discarded. */
  cancel(): void;
}

type Scheduler = (cb: () => void) => () => void;

const frameScheduler: Scheduler = (cb) => {
  const handle = requestAnimationFrame(cb);
  return () => cancelAnimationFrame(handle);
};

export function createDeltaCoalescer(
  apply: (batch: DeltaBatch) => void,
  schedule: Scheduler = frameScheduler,
): DeltaCoalescer {
  let content = "";
  let thinking = "";
  let unschedule: (() => void) | null = null;

  function flush(): void {
    if (unschedule) {
      unschedule();
      unschedule = null;
    }
    if (!content && !thinking) return;
    const batch = { content, thinking };
    content = "";
    thinking = "";
    apply(batch);
  }

  function request(): void {
    if (unschedule) return;
    unschedule = schedule(() => {
      unschedule = null;
      flush();
    });
  }

  return {
    content(text) {
      content += text;
      request();
    },
    thinking(text) {
      thinking += text;
      request();
    },
    flush,
    cancel() {
      if (unschedule) {
        unschedule();
        unschedule = null;
      }
      content = "";
      thinking = "";
    },
  };
}
