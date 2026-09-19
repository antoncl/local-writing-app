// Pure helpers behind the body/list-tab scroll-position memory (#2013),
// extracted so they're unit-testable without mounting ProseBodyView or
// ReferenceListTab (TipTap isn't mountable under happy-dom, and
// ReferenceListTab's ViewNodeList mount is flaky for the same reason — see
// reference_svelteflow_headless_limits-style traps).

/** What a `loadScene` load should do about a remembered scroll position. A
 *  "reconcile" load (a same-id, out-of-band write-back, e.g. an embedded-TODO
 *  replace) leaves scroll alone: `"skip"`. Only a genuine "boundary" open (a
 *  real node switch) restores — `"now"` when the frame has laid out, or
 *  `"defer"` when it has no height yet (`clientHeight === 0`): a frame that
 *  is `display: none` because the node reopened on a list tab can't receive a
 *  scrollTop, so the caller holds the offset and applies it when the frame is
 *  next laid out (the writer clicks back to Body). */
export function scrollRestorePlan(
  mode: "boundary" | "reconcile",
  clientHeight: number,
): "now" | "defer" | "skip" {
  if (mode !== "boundary") return "skip";
  return clientHeight > 0 ? "now" : "defer";
}

/** Apply a deferred restore the first time `el` has a laid-out height. The
 *  frame goes from `display: none` to laid out when its body tab is selected,
 *  which only a ResizeObserver sees (no event fires). `getPending` is read at
 *  observe time so a later boundary load can replace or clear the offset;
 *  `clear` runs after a successful apply. Returns a disconnect function; a
 *  no-op where ResizeObserver is missing (happy-dom). */
export function applyScrollWhenLaidOut(
  el: HTMLElement,
  getPending: () => number | null,
  clear: () => void,
): () => void {
  if (typeof ResizeObserver === "undefined") return () => {};
  const observer = new ResizeObserver(() => {
    const pending = getPending();
    if (pending === null || el.clientHeight === 0) return;
    el.scrollTop = pending;
    clear();
  });
  observer.observe(el);
  return () => observer.disconnect();
}

/** The slice of BodyMemory this helper needs — narrow so a test can pass a
 *  bare object instead of the real store. */
export interface ScrollMemoryLike {
  rememberScroll(nodeId: string, surface: string, top: number): void;
}

/** Wire a passive, rAF-throttled `scroll` listener onto `el`: on each frame
 *  (never more than once per animation frame, however many scroll events fired
 *  in it) it asks `getKey()` for the CURRENT node id / surface and records
 *  `el.scrollTop` under it. `getKey` is called at fire time, not capture time,
 *  because the host component (ProseBodyView) isn't remounted on a node
 *  switch — the open node can move on between when the listener was attached
 *  and when a given scroll event fires. Returns an unsubscribe function. */
export function rememberScrollOnScroll(
  el: HTMLElement,
  getKey: () => { nodeId: string; surface: string } | null,
  memory: ScrollMemoryLike,
): () => void {
  let scheduled = false;
  const onScroll = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      const key = getKey();
      if (key) memory.rememberScroll(key.nodeId, key.surface, el.scrollTop);
    });
  };
  el.addEventListener("scroll", onScroll, { passive: true });
  return () => el.removeEventListener("scroll", onScroll);
}
