/**
 * The caretaker's whole contract (ADR-0050 §8 slice 0, #678; async support
 * ADR-0053 §7, #902).
 *
 * The caretaker never inspects a command, so these tests drive it the only way
 * a consumer can: commands whose closures mutate a plain value, then asserting
 * the value — not the caretaker's internals — after each undo/redo. Undo/redo
 * are async (a backend-backed surface reverses by awaiting a server inverse),
 * so every call is awaited; sync closures still work, awaited or not. The
 * domain-agnosticism itself is asserted structurally at the bottom: the module
 * imports nothing from the canvas or any node/edge module.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { UndoCaretaker, type Command } from "./undoCaretaker.svelte";

/** A command over a shared counter-like log: `redo` appends its tag, `undo`
 *  removes it. The log's content after a sequence of operations is therefore
 *  a full trace of which closures ran, in which order. */
function tagged(log: string[], tag: string, extra: Partial<Command> = {}): Command {
  return {
    redo: () => void log.push(tag),
    undo: () => void log.splice(log.lastIndexOf(tag), 1),
    ...extra,
  };
}

describe("UndoCaretaker", () => {
  it("round-trips a lone command through record → undo → redo", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"]; // the actor already performed the change (§1)
    caretaker.record(tagged(log, "a", { label: "add a" }));

    expect(await caretaker.undo()).toEqual({ label: "add a" });
    expect(log).toEqual([]);
    expect(await caretaker.redo()).toEqual({ label: "add a" });
    expect(log).toEqual(["a"]);
  });

  it("recording never executes the command", () => {
    const caretaker = new UndoCaretaker();
    const log: string[] = [];
    caretaker.record(tagged(log, "a"));
    expect(log).toEqual([]);
  });

  it("collapses a three-command shared-id run into one undo step and one redo", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["edge-a", "edge-b", "self"];
    // The delete cascade of §4: edges first, then the node, one transaction.
    caretaker.record(tagged(log, "edge-a", { transaction: "t1", label: "delete edge" }));
    caretaker.record(tagged(log, "edge-b", { transaction: "t1", label: "delete edge" }));
    caretaker.record(tagged(log, "self", { transaction: "t1", label: "delete node" }));

    // One undo reverses the whole run (order proven by the LIFO test below),
    // announcing the gesture's concluding label.
    expect(await caretaker.undo()).toEqual({ label: "delete node" });
    expect(log).toEqual([]);
    expect(caretaker.canUndo).toBe(false);

    // One redo replays it forward.
    expect(await caretaker.redo()).toEqual({ label: "delete node" });
    expect(log).toEqual(["edge-a", "edge-b", "self"]);
    expect(caretaker.canRedo).toBe(false);
  });

  it("undoes a shared-id run LIFO", async () => {
    const caretaker = new UndoCaretaker();
    const order: string[] = [];
    for (const tag of ["first", "second", "third"]) {
      caretaker.record({
        undo: () => void order.push(`undo:${tag}`),
        redo: () => void order.push(`redo:${tag}`),
        transaction: "t1",
      });
    }
    await caretaker.undo();
    expect(order).toEqual(["undo:third", "undo:second", "undo:first"]);
    await caretaker.redo();
    expect(order.slice(3)).toEqual(["redo:first", "redo:second", "redo:third"]);
  });

  it("closes a transaction when the next command arrives without its id", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a1", "a2", "b"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "a2", { transaction: "tA" }));
    caretaker.record(tagged(log, "b")); // untagged — its own single step, tA is closed

    await caretaker.undo();
    expect(log).toEqual(["a1", "a2"]); // only b
    await caretaker.undo();
    expect(log).toEqual([]); // the whole tA run
    expect(caretaker.canUndo).toBe(false);

    // And forward again from the bottom: the first redo must replay the whole
    // tA run, not one command of it, and the second brings back b alone.
    await caretaker.redo();
    expect(log).toEqual(["a1", "a2"]);
    await caretaker.redo();
    expect(log).toEqual(["a1", "a2", "b"]);
  });

  it("treats non-adjacent reuse of a transaction id as separate steps", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a1", "b", "a2"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "b"));
    caretaker.record(tagged(log, "a2", { transaction: "tA" })); // tA already closed by b

    await caretaker.undo();
    expect(log).toEqual(["a1", "b"]);
    await caretaker.undo();
    expect(log).toEqual(["a1"]);
  });

  it("keeps adjacent runs of different transactions as separate steps", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a1", "a2", "b1", "b2"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "a2", { transaction: "tA" }));
    caretaker.record(tagged(log, "b1", { transaction: "tB" }));
    caretaker.record(tagged(log, "b2", { transaction: "tB" }));

    await caretaker.undo();
    expect(log).toEqual(["a1", "a2"]);
    await caretaker.undo();
    expect(log).toEqual([]);
  });

  it("never reopens a closed run — an undo-fork cannot rejoin same-id runs", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a1", "b"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "b")); // closes tA
    await caretaker.undo(); // discard b — tA's runs are now adjacent in the log
    expect(log).toEqual(["a1"]);
    log.push("c");
    caretaker.record(tagged(log, "c", { transaction: "tA" }));

    // Closure was recorded at record time, so the fork must not merge the two
    // gestures into one step: the first undo reverses only c.
    await caretaker.undo();
    expect(log).toEqual(["a1"]);
    await caretaker.undo();
    expect(log).toEqual([]);
  });

  it("closes an open transaction on undo/redo, not only on an untagged record", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"];
    caretaker.record(tagged(log, "a", { transaction: "tA" }));
    await caretaker.undo();
    await caretaker.redo(); // a round-trip through history is a user action — tA is over
    log.push("b");
    caretaker.record(tagged(log, "b", { transaction: "tA" }));

    await caretaker.undo();
    expect(log).toEqual(["a"]); // b alone, not one merged tA step
  });

  it("treats an empty-string transaction id as no transaction", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a", "b"];
    // A consumer normalizing with `?? ""` must not accidentally group
    // unrelated gestures (null from untyped JS folds the same way).
    caretaker.record(tagged(log, "a", { transaction: "" }));
    caretaker.record(tagged(log, "b", { transaction: "" }));

    await caretaker.undo();
    expect(log).toEqual(["a"]); // two steps, not one "" run
  });

  it("throws on record() from inside a replaying closure, leaving state consistent", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"];
    caretaker.record({
      // The slice-1 mistake: an undo closure routed through a committer that
      // records. The caretaker must fail loudly, not corrupt the log.
      undo: () => caretaker.record(tagged(log, "x")),
      redo: () => void log.push("a"),
    });

    await expect(caretaker.undo()).rejects.toThrow(/record\(\) during undo\/redo/);
    expect(caretaker.canUndo).toBe(true); // the step did not complete
    expect(caretaker.canRedo).toBe(false); // and nothing was recorded above it
  });

  it("keeps the cursor consistent when a closure throws mid-run", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["c1", "c2", "c3"];
    let broken = true;
    caretaker.record(tagged(log, "c1", { transaction: "t" }));
    caretaker.record({
      undo: () => {
        if (broken) throw new Error("boom");
        log.splice(log.lastIndexOf("c2"), 1);
      },
      redo: () => void log.push("c2"),
      transaction: "t",
    });
    caretaker.record(tagged(log, "c3", { transaction: "t" }));

    // c3 undoes, c2 throws: the exception propagates but the cursor records
    // the partial progress.
    await expect(caretaker.undo()).rejects.toThrow("boom");
    expect(log).toEqual(["c1", "c2"]);
    expect(caretaker.canUndo).toBe(true);

    // A retry continues the step from where it broke — c3 must NOT undo (or
    // its closure execute) a second time.
    broken = false;
    await caretaker.undo();
    expect(log).toEqual([]);
    expect(caretaker.canUndo).toBe(false);
  });

  it("clears the redo stack when a new command is recorded after an undo", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"];
    caretaker.record(tagged(log, "a"));
    await caretaker.undo();
    expect(caretaker.canRedo).toBe(true);

    log.push("b");
    caretaker.record(tagged(log, "b"));
    expect(caretaker.canRedo).toBe(false);
    expect(await caretaker.redo()).toBe(null); // the undone future is gone
    expect(log).toEqual(["b"]);
  });

  it("bounds the stack, dropping the oldest step past the cap", async () => {
    const caretaker = new UndoCaretaker(3);
    const log = ["a", "b", "c", "d"];
    for (const tag of ["a", "b", "c", "d"]) caretaker.record(tagged(log, tag));

    // Cap 3: "a" fell off the bottom, so only three undos are possible …
    for (const remaining of [3, 2, 1]) {
      expect(caretaker.canUndo).toBe(true);
      await caretaker.undo();
      expect(log.length).toBe(remaining);
    }
    expect(caretaker.canUndo).toBe(false);
    expect(await caretaker.undo()).toBe(null);
    // … and "a"'s change survives as the floor the stack can't reach below.
    expect(log).toEqual(["a"]);
  });

  it("never splits a transaction when enforcing the cap", async () => {
    const caretaker = new UndoCaretaker(3);
    const log = ["a1", "a2", "b", "c"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "a2", { transaction: "tA" }));
    caretaker.record(tagged(log, "b"));
    caretaker.record(tagged(log, "c")); // over cap: the whole tA run drops, not just a1

    await caretaker.undo(); // c
    await caretaker.undo(); // b
    expect(caretaker.canUndo).toBe(false);
    expect(log).toEqual(["a1", "a2"]);
  });

  it("never drops the newest step, even when its cascade alone exceeds the cap", async () => {
    const caretaker = new UndoCaretaker(2);
    const log = ["t1", "t2", "t3"];
    // One gesture, three commands, cap two: the stack overshoots rather than
    // eating the gesture just performed — it must stay undoable.
    for (const tag of ["t1", "t2", "t3"]) caretaker.record(tagged(log, tag, { transaction: "t" }));
    expect(caretaker.canUndo).toBe(true);
    await caretaker.undo();
    expect(log).toEqual([]);

    // Once a next step lands, the oversized run is history and droppable.
    await caretaker.redo();
    log.push("d");
    caretaker.record(tagged(log, "d"));
    await caretaker.undo(); // d
    expect(caretaker.canUndo).toBe(false); // the t run was dropped by the cap
    expect(log).toEqual(["t1", "t2", "t3"]);
  });

  it("keeps canUndo/canRedo correct at the stack ends", async () => {
    const caretaker = new UndoCaretaker();
    expect(caretaker.canUndo).toBe(false);
    expect(caretaker.canRedo).toBe(false);

    const log = ["a"];
    caretaker.record(tagged(log, "a"));
    expect(caretaker.canUndo).toBe(true);
    expect(caretaker.canRedo).toBe(false);

    await caretaker.undo();
    expect(caretaker.canUndo).toBe(false);
    expect(caretaker.canRedo).toBe(true);

    await caretaker.redo();
    expect(caretaker.canUndo).toBe(true);
    expect(caretaker.canRedo).toBe(false);
  });

  it("peeks the next undo/redo step's label without consuming it", async () => {
    const caretaker = new UndoCaretaker();
    expect(caretaker.undoLabel).toBe(null);
    expect(caretaker.redoLabel).toBe(null);

    const log = ["e", "n"];
    caretaker.record(tagged(log, "e", { transaction: "t", label: "delete edge" }));
    caretaker.record(tagged(log, "n", { transaction: "t", label: "delete node" }));
    // The whole run is one step; the peek shows the same label undo() returns.
    expect(caretaker.undoLabel).toBe("delete node");
    expect(caretaker.redoLabel).toBe(null);
    expect(log).toEqual(["e", "n"]); // peeking executed nothing

    await caretaker.undo();
    expect(caretaker.undoLabel).toBe(null);
    expect(caretaker.redoLabel).toBe("delete node");
  });

  it("distinguishes an unlabelled step from nothing-to-undo by shape, not truthiness", async () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"];
    caretaker.record(tagged(log, "a")); // no label
    expect(await caretaker.undo()).toEqual({ label: "" }); // undone, nothing to name
    expect(await caretaker.undo()).toBe(null); // nothing left to undo
  });

  // ── async support (ADR-0053 §7) ──────────────────────────────────────────

  it("awaits an async closure before running the next command in a run", async () => {
    const caretaker = new UndoCaretaker();
    const order: string[] = [];
    const gate: { release?: () => void } = {};
    // A slow first-to-reverse command (the LIFO tail) and a fast one after it:
    // the fast one must not run until the slow one's promise settles.
    caretaker.record({
      undo: () => void order.push("fast-undo"),
      redo: () => void order.push("fast-redo"),
      transaction: "t",
    });
    caretaker.record({
      undo: () =>
        new Promise<void>((resolve) => {
          order.push("slow-undo-start");
          gate.release = () => {
            order.push("slow-undo-end");
            resolve();
          };
        }),
      redo: () => void order.push("slow-redo"),
      transaction: "t",
    });

    const done = caretaker.undo(); // LIFO: slow (recorded last) reverses first
    await Promise.resolve();
    expect(order).toEqual(["slow-undo-start"]); // fast has NOT run yet
    gate.release!();
    await done;
    expect(order).toEqual(["slow-undo-start", "slow-undo-end", "fast-undo"]);
  });

  it("busy-gates a re-entrant undo while an async step is in flight", async () => {
    const caretaker = new UndoCaretaker();
    const log: string[] = [];
    let runs = 0;
    const gate: { release?: () => void } = {};
    caretaker.record({
      undo: () =>
        new Promise<void>((resolve) => {
          runs += 1;
          gate.release = resolve;
        }),
      redo: () => void log.push("x"),
    });

    const first = caretaker.undo();
    await Promise.resolve();
    expect(caretaker.busy).toBe(true);
    // A mashed second Ctrl+Z must no-op, not race a second inverse call.
    expect(await caretaker.undo()).toBe(null);
    expect(runs).toBe(1);
    gate.release!();
    await first;
    expect(caretaker.busy).toBe(false);
    expect(caretaker.canUndo).toBe(false); // the single step completed once
  });

  it("busy-gates a re-entrant redo while an async step is in flight", async () => {
    const caretaker = new UndoCaretaker();
    const gate: { release?: () => void } = {};
    let redos = 0;
    caretaker.record({
      undo: () => {},
      redo: () =>
        new Promise<void>((resolve) => {
          redos += 1;
          gate.release = resolve;
        }),
    });
    await caretaker.undo();

    const first = caretaker.redo();
    await Promise.resolve();
    expect(await caretaker.redo()).toBe(null);
    expect(redos).toBe(1);
    gate.release!();
    await first;
  });

  it("imports nothing from the canvas or any node/edge module (§2)", () => {
    // The load-bearing acceptance of #678: the caretaker's ignorance is what
    // lets a second surface reuse it. Scoped to import statements so a future
    // legitimate import — or a comment mentioning the canvas by name — cannot
    // false-positive the guard into being weakened.
    const source = readFileSync(new URL("./undoCaretaker.svelte.ts", import.meta.url), "utf8");
    const imports = source.match(/^\s*import\b.*/gm) ?? [];
    for (const line of imports) {
      expect(line).not.toMatch(/@xyflow|svelteflow|flownode|flowedge|viewbody/i);
    }
  });
});
