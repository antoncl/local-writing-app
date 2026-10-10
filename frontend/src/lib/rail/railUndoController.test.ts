// @vitest-environment happy-dom
// #2438: the metadata rail's per-pane undo — per-field commands, edit sessions
// as one step, a lock while read-only / at a stop, and the rail-scoped chord.
import { describe, expect, it } from "vitest";
import { RailUndoController } from "./railUndoController.svelte";
import type { EntryMetadata } from "@/lib/types";

function harness(initial: EntryMetadata = {}, initialStatus = "draft") {
  const state = { metadata: initial, status: initialStatus, locked: false, applies: 0 };
  const ctl = new RailUndoController({
    getMetadata: () => state.metadata,
    applyMetadata: (next) => {
      state.metadata = next;
      state.applies += 1;
    },
    getStatus: () => state.status,
    applyStatus: (next) => {
      state.status = next;
    },
    fieldLabel: (id) => id.toUpperCase(),
    locked: () => state.locked,
  });
  // What NodeEditor's rail `metadataChange` does: record, then assign.
  const write = (next: EntryMetadata, session?: string) => {
    ctl.recordMetadata(state.metadata, next, session);
    state.metadata = next;
  };
  return { ctl, state, write };
}

describe("RailUndoController", () => {
  it("undoes a cleared tag list and redoes it", async () => {
    const { ctl, state, write } = harness({ tags: ["a", "b"], pov: "Mara" });
    write({ pov: "Mara" });

    expect(ctl.undoTitle).toBe("Undo TAGS change");
    await ctl.undo();
    expect(state.metadata).toEqual({ pov: "Mara", tags: ["a", "b"] });
    await ctl.redo();
    expect(state.metadata).toEqual({ pov: "Mara" });
  });

  it("restores only its own field — a later edit to another field survives", async () => {
    const { ctl, state, write } = harness({ tags: ["a"] });
    write({ tags: [] });
    write({ tags: [], pov: "Bob" });
    // Undo the pov step, then the tags step: each touches only its key.
    await ctl.undo();
    expect(state.metadata).toEqual({ tags: [] });
    state.metadata = { tags: [], mood: "grim" }; // an unrecorded change in between
    await ctl.undo();
    expect(state.metadata).toEqual({ tags: ["a"], mood: "grim" });
  });

  it("collapses one edit session into one step, and separate sessions into separate steps", async () => {
    const { ctl, state, write } = harness({});
    write({ alias: "M" }, "alias#1");
    write({ alias: "Ma" }, "alias#1");
    write({ alias: "Mar" }, "alias#1");
    write({ alias: "Mara" }, "alias#2");

    await ctl.undo();
    expect(state.metadata).toEqual({ alias: "Mar" });
    await ctl.undo();
    expect(state.metadata).toEqual({});
    expect(ctl.canUndo).toBe(false);
  });

  it("records nothing for a write that changes nothing", () => {
    const { ctl, write } = harness({ tags: ["a"] });
    write({ tags: ["a"] });
    expect(ctl.canUndo).toBe(false);
  });

  it("undoes a status change", async () => {
    const { ctl, state } = harness({}, "draft");
    ctl.recordStatus("draft", "final");
    state.status = "final";
    await ctl.undo();
    expect(state.status).toBe("draft");
  });

  it("does nothing while locked, and reports nothing undoable", async () => {
    const { ctl, state, write } = harness({ tags: ["a"] });
    write({});
    state.locked = true;
    expect(ctl.canUndo).toBe(false);
    await ctl.undo();
    expect(state.metadata).toEqual({});
    state.locked = false;
    expect(ctl.canUndo).toBe(true);
  });

  it("reset drops the history", () => {
    const { ctl, write } = harness({ tags: ["a"] });
    write({});
    ctl.reset();
    expect(ctl.canUndo).toBe(false);
  });

  it("handles the chord outside a text input, and leaves it to a text input", async () => {
    const { ctl, state, write } = harness({ tags: ["a"] });
    write({});

    const input = document.createElement("input");
    const inInput = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, cancelable: true });
    input.dispatchEvent(inInput); // sets event.target
    ctl.handleKeydown(inInput);
    expect(inInput.defaultPrevented).toBe(false);

    const button = document.createElement("button");
    const onButton = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, cancelable: true });
    button.dispatchEvent(onButton);
    ctl.handleKeydown(onButton);
    expect(onButton.defaultPrevented).toBe(true);
    await Promise.resolve();
    await Promise.resolve();
    expect(state.metadata).toEqual({ tags: ["a"] });
  });
});
