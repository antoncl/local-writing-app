// @vitest-environment happy-dom
import { describe, it, expect } from "vitest";
import { flushSync } from "svelte";
import { wireReviewFreeze } from "./reviewFreeze.svelte";
import type { ReviewCommitter } from "@/lib/stores/editorPanes.svelte";

// The AI-review freeze wiring must signal begin/endReviewLock only on a genuine
// review-state transition — never on the host (App) recreating the inline
// `onReviewFreeze` arrow every render. #1965: tracking that arrow's identity re-ran
// the effect on unrelated App churn, thrashing begin/endReviewLock into an unbounded
// flush loop (~127k PUT/409 in one report). These pin the contract off NodeEditor,
// which is far too heavy to mount.

const committer: ReviewCommitter = {
  hasChanges: () => false,
  commit: () => Promise.resolve(true),
  discard: () => {},
};

describe("wireReviewFreeze (#1965)", () => {
  it("freezes exactly once when the review begins, and ignores host-callback identity churn", () => {
    let reviewing = $state(false);
    // Stands in for App recreating the inline `onReviewFreeze` arrow each render: a
    // reactive value the signal getter reads. The fix must keep it OUT of the
    // effect's dependency set (read via untrack), so bumping it never re-fires.
    let arrowNonce = $state(0);
    const signals: Array<ReviewCommitter | null> = [];
    const freezes = () => signals.filter((c) => c !== null).length;

    const stop = $effect.root(() => {
      wireReviewFreeze({
        entryId: () => "plot_1",
        reviewing: () => reviewing,
        committer: () => committer,
        signal: () => {
          void arrowNonce;
          return (_id, c) => signals.push(c);
        },
      });
    });

    flushSync();
    expect(freezes()).toBe(0); // not reviewing yet

    reviewing = true;
    flushSync();
    expect(freezes()).toBe(1); // the single freeze

    // The host re-renders five times, each with a fresh arrow identity. Pre-#1965
    // every one re-ran the effect and re-signalled freeze (the loop's engine);
    // post-fix they are inert.
    for (let i = 0; i < 5; i++) {
      arrowNonce += 1;
      flushSync();
    }
    expect(freezes()).toBe(1);

    stop();
  });

  it("ignores a replaced scene object that keeps the same id (the Accept-all 409 loop)", () => {
    // NodeEditor reads the id as `scene?.id`, and the pane store replaces the
    // scene-bearing pane object on EVERY `panes` reassignment — including each
    // failed save's `saving` flip. Tracking the object (not the id's value)
    // re-ran the effect per reassignment: thaw → re-freeze → `firstLock` flush on
    // the dirty pane → 409 → `saving` flip → re-run: ~8k PUTs in two minutes.
    const host = $state({ scene: { id: "lore_1" } as { id: string } | null });
    const signals: Array<ReviewCommitter | null> = [];

    const stop = $effect.root(() => {
      wireReviewFreeze({
        entryId: () => host.scene?.id ?? null,
        reviewing: () => true,
        committer: () => committer,
        signal: () => (_id, c) => signals.push(c),
      });
    });

    flushSync();
    expect(signals).toEqual([committer]); // frozen once at entry

    for (let i = 0; i < 5; i++) {
      host.scene = { id: "lore_1" }; // same node, new object
      flushSync();
    }
    expect(signals).toEqual([committer]); // no thaw/re-freeze churn

    host.scene = { id: "lore_2" }; // a genuine switch still re-freezes
    flushSync();
    expect(signals).toEqual([committer, null, committer]);

    stop();
  });

  it("thaws (null) when the review ends", () => {
    let reviewing = $state(true);
    const signals: Array<ReviewCommitter | null> = [];

    const stop = $effect.root(() => {
      wireReviewFreeze({
        entryId: () => "plot_1",
        reviewing: () => reviewing,
        committer: () => committer,
        signal: () => (_id, c) => signals.push(c),
      });
    });

    flushSync();
    expect(signals.at(-1)).toBe(committer); // frozen at entry

    reviewing = false;
    flushSync();
    expect(signals.at(-1)).toBe(null); // thawed on exit

    stop();
  });

  it("does not signal for a node with no id", () => {
    const signals: Array<ReviewCommitter | null> = [];

    const stop = $effect.root(() => {
      wireReviewFreeze({
        entryId: () => null,
        reviewing: () => true,
        committer: () => committer,
        signal: () => (_id, c) => signals.push(c),
      });
    });

    flushSync();
    expect(signals).toEqual([]);

    stop();
  });
});
