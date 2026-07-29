/**
 * The caretaker's whole contract (ADR-0050 §8 slice 0, #678).
 *
 * The caretaker never inspects a command, so these tests drive it the only way
 * a consumer can: commands whose closures mutate a plain value, then asserting
 * the value — not the caretaker's internals — after each undo/redo. The
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
    redo: () => log.push(tag),
    undo: () => log.splice(log.lastIndexOf(tag), 1),
    ...extra,
  };
}

describe("UndoCaretaker", () => {
  it("round-trips a lone command through record → undo → redo", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"]; // the actor already performed the change (§1)
    caretaker.record(tagged(log, "a", { label: "add a" }));

    expect(caretaker.undo()).toEqual({ label: "add a" });
    expect(log).toEqual([]);
    expect(caretaker.redo()).toEqual({ label: "add a" });
    expect(log).toEqual(["a"]);
  });

  it("recording never executes the command", () => {
    const caretaker = new UndoCaretaker();
    const log: string[] = [];
    caretaker.record(tagged(log, "a"));
    expect(log).toEqual([]);
  });

  it("collapses a three-command shared-id run into one undo step and one redo", () => {
    const caretaker = new UndoCaretaker();
    const log = ["edge-a", "edge-b", "self"];
    // The delete cascade of §4: edges first, then the node, one transaction.
    caretaker.record(tagged(log, "edge-a", { transaction: "t1", label: "delete edge" }));
    caretaker.record(tagged(log, "edge-b", { transaction: "t1", label: "delete edge" }));
    caretaker.record(tagged(log, "self", { transaction: "t1", label: "delete node" }));

    // One undo reverses the whole run (order proven by the LIFO test below),
    // announcing the gesture's concluding label.
    expect(caretaker.undo()).toEqual({ label: "delete node" });
    expect(log).toEqual([]);
    expect(caretaker.canUndo).toBe(false);

    // One redo replays it forward.
    expect(caretaker.redo()).toEqual({ label: "delete node" });
    expect(log).toEqual(["edge-a", "edge-b", "self"]);
    expect(caretaker.canRedo).toBe(false);
  });

  it("undoes a shared-id run LIFO", () => {
    const caretaker = new UndoCaretaker();
    const order: string[] = [];
    for (const tag of ["first", "second", "third"]) {
      caretaker.record({
        undo: () => order.push(`undo:${tag}`),
        redo: () => order.push(`redo:${tag}`),
        transaction: "t1",
      });
    }
    caretaker.undo();
    expect(order).toEqual(["undo:third", "undo:second", "undo:first"]);
    caretaker.redo();
    expect(order.slice(3)).toEqual(["redo:first", "redo:second", "redo:third"]);
  });

  it("closes a transaction when the next command arrives without its id", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a1", "a2", "b"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "a2", { transaction: "tA" }));
    caretaker.record(tagged(log, "b")); // untagged — its own single step, tA is closed

    caretaker.undo();
    expect(log).toEqual(["a1", "a2"]); // only b
    caretaker.undo();
    expect(log).toEqual([]); // the whole tA run
    expect(caretaker.canUndo).toBe(false);

    // And forward again from the bottom: the first redo must replay the whole
    // tA run, not one command of it, and the second brings back b alone.
    caretaker.redo();
    expect(log).toEqual(["a1", "a2"]);
    caretaker.redo();
    expect(log).toEqual(["a1", "a2", "b"]);
  });

  it("treats non-adjacent reuse of a transaction id as separate steps", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a1", "b", "a2"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "b"));
    caretaker.record(tagged(log, "a2", { transaction: "tA" })); // tA already closed by b

    caretaker.undo();
    expect(log).toEqual(["a1", "b"]);
    caretaker.undo();
    expect(log).toEqual(["a1"]);
  });

  it("keeps adjacent runs of different transactions as separate steps", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a1", "a2", "b1", "b2"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "a2", { transaction: "tA" }));
    caretaker.record(tagged(log, "b1", { transaction: "tB" }));
    caretaker.record(tagged(log, "b2", { transaction: "tB" }));

    caretaker.undo();
    expect(log).toEqual(["a1", "a2"]);
    caretaker.undo();
    expect(log).toEqual([]);
  });

  it("never reopens a closed run — an undo-fork cannot rejoin same-id runs", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a1", "b"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "b")); // closes tA
    caretaker.undo(); // discard b — tA's runs are now adjacent in the log
    expect(log).toEqual(["a1"]);
    log.push("c");
    caretaker.record(tagged(log, "c", { transaction: "tA" }));

    // Closure was recorded at record time, so the fork must not merge the two
    // gestures into one step: the first undo reverses only c.
    caretaker.undo();
    expect(log).toEqual(["a1"]);
    caretaker.undo();
    expect(log).toEqual([]);
  });

  it("closes an open transaction on undo/redo, not only on an untagged record", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"];
    caretaker.record(tagged(log, "a", { transaction: "tA" }));
    caretaker.undo();
    caretaker.redo(); // a round-trip through history is a user action — tA is over
    log.push("b");
    caretaker.record(tagged(log, "b", { transaction: "tA" }));

    caretaker.undo();
    expect(log).toEqual(["a"]); // b alone, not one merged tA step
  });

  it("treats an empty-string transaction id as no transaction", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a", "b"];
    // A consumer normalizing with `?? ""` must not accidentally group
    // unrelated gestures (null from untyped JS folds the same way).
    caretaker.record(tagged(log, "a", { transaction: "" }));
    caretaker.record(tagged(log, "b", { transaction: "" }));

    caretaker.undo();
    expect(log).toEqual(["a"]); // two steps, not one "" run
  });

  it("throws on record() from inside a replaying closure, leaving state consistent", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"];
    caretaker.record({
      // The slice-1 mistake: an undo closure routed through a committer that
      // records. The caretaker must fail loudly, not corrupt the log.
      undo: () => caretaker.record(tagged(log, "x")),
      redo: () => log.push("a"),
    });

    expect(() => caretaker.undo()).toThrow(/record\(\) during undo\/redo/);
    expect(caretaker.canUndo).toBe(true); // the step did not complete
    expect(caretaker.canRedo).toBe(false); // and nothing was recorded above it
  });

  it("keeps the cursor consistent when a closure throws mid-run", () => {
    const caretaker = new UndoCaretaker();
    const log = ["c1", "c2", "c3"];
    let broken = true;
    caretaker.record(tagged(log, "c1", { transaction: "t" }));
    caretaker.record({
      undo: () => {
        if (broken) throw new Error("boom");
        log.splice(log.lastIndexOf("c2"), 1);
      },
      redo: () => log.push("c2"),
      transaction: "t",
    });
    caretaker.record(tagged(log, "c3", { transaction: "t" }));

    // c3 undoes, c2 throws: the exception propagates but the cursor records
    // the partial progress.
    expect(() => caretaker.undo()).toThrow("boom");
    expect(log).toEqual(["c1", "c2"]);
    expect(caretaker.canUndo).toBe(true);

    // A retry continues the step from where it broke — c3 must NOT undo (or
    // its closure execute) a second time.
    broken = false;
    caretaker.undo();
    expect(log).toEqual([]);
    expect(caretaker.canUndo).toBe(false);
  });

  it("clears the redo stack when a new command is recorded after an undo", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"];
    caretaker.record(tagged(log, "a"));
    caretaker.undo();
    expect(caretaker.canRedo).toBe(true);

    log.push("b");
    caretaker.record(tagged(log, "b"));
    expect(caretaker.canRedo).toBe(false);
    expect(caretaker.redo()).toBe(null); // the undone future is gone
    expect(log).toEqual(["b"]);
  });

  it("bounds the stack, dropping the oldest step past the cap", () => {
    const caretaker = new UndoCaretaker(3);
    const log = ["a", "b", "c", "d"];
    for (const tag of ["a", "b", "c", "d"]) caretaker.record(tagged(log, tag));

    // Cap 3: "a" fell off the bottom, so only three undos are possible …
    for (const remaining of [3, 2, 1]) {
      expect(caretaker.canUndo).toBe(true);
      caretaker.undo();
      expect(log.length).toBe(remaining);
    }
    expect(caretaker.canUndo).toBe(false);
    expect(caretaker.undo()).toBe(null);
    // … and "a"'s change survives as the floor the stack can't reach below.
    expect(log).toEqual(["a"]);
  });

  it("never splits a transaction when enforcing the cap", () => {
    const caretaker = new UndoCaretaker(3);
    const log = ["a1", "a2", "b", "c"];
    caretaker.record(tagged(log, "a1", { transaction: "tA" }));
    caretaker.record(tagged(log, "a2", { transaction: "tA" }));
    caretaker.record(tagged(log, "b"));
    caretaker.record(tagged(log, "c")); // over cap: the whole tA run drops, not just a1

    caretaker.undo(); // c
    caretaker.undo(); // b
    expect(caretaker.canUndo).toBe(false);
    expect(log).toEqual(["a1", "a2"]);
  });

  it("never drops the newest step, even when its cascade alone exceeds the cap", () => {
    const caretaker = new UndoCaretaker(2);
    const log = ["t1", "t2", "t3"];
    // One gesture, three commands, cap two: the stack overshoots rather than
    // eating the gesture just performed — it must stay undoable.
    for (const tag of ["t1", "t2", "t3"]) caretaker.record(tagged(log, tag, { transaction: "t" }));
    expect(caretaker.canUndo).toBe(true);
    caretaker.undo();
    expect(log).toEqual([]);

    // Once a next step lands, the oversized run is history and droppable.
    caretaker.redo();
    log.push("d");
    caretaker.record(tagged(log, "d"));
    caretaker.undo(); // d
    expect(caretaker.canUndo).toBe(false); // the t run was dropped by the cap
    expect(log).toEqual(["t1", "t2", "t3"]);
  });

  it("keeps canUndo/canRedo correct at the stack ends", () => {
    const caretaker = new UndoCaretaker();
    expect(caretaker.canUndo).toBe(false);
    expect(caretaker.canRedo).toBe(false);

    const log = ["a"];
    caretaker.record(tagged(log, "a"));
    expect(caretaker.canUndo).toBe(true);
    expect(caretaker.canRedo).toBe(false);

    caretaker.undo();
    expect(caretaker.canUndo).toBe(false);
    expect(caretaker.canRedo).toBe(true);

    caretaker.redo();
    expect(caretaker.canUndo).toBe(true);
    expect(caretaker.canRedo).toBe(false);
  });

  it("peeks the next undo/redo step's label without consuming it", () => {
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

    caretaker.undo();
    expect(caretaker.undoLabel).toBe(null);
    expect(caretaker.redoLabel).toBe("delete node");
  });

  it("distinguishes an unlabelled step from nothing-to-undo by shape, not truthiness", () => {
    const caretaker = new UndoCaretaker();
    const log = ["a"];
    caretaker.record(tagged(log, "a")); // no label
    expect(caretaker.undo()).toEqual({ label: "" }); // undone, nothing to name
    expect(caretaker.undo()).toBe(null); // nothing left to undo
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
