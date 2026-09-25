// @vitest-environment happy-dom
// ADR-0095 §1: the pill's label follows the mutation-sets STORE, via a
// NodeView, so editing the set relabels every pill it anchors with NO
// document transaction. Built against a real TipTap editor (mirrors
// proseRoundTrip.test.ts / mutationNodes.test.ts).
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import { createMutationCloseMark, createMutationMark } from "./proseMarks";
import { proseStarterKit } from "./proseStarterKit";
import {
  mutationSetEntriesStore,
  mutationSetRosterLoadedStore,
} from "@/lib/stores/mutationSets";
import type { MutationSetEntrySummary } from "@/lib/types";

const editors: Editor[] = [];
function makeEditor(): Editor {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), createMutationMark(), createMutationCloseMark()],
    content: "<p></p>",
  });
  editors.push(editor);
  return editor;
}
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
  mutationSetEntriesStore.set([]);
  mutationSetRosterLoadedStore.set(false);
});

function summary(over: Partial<MutationSetEntrySummary> = {}): MutationSetEntrySummary {
  return {
    id: "s1",
    title: "",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "mira",
    row_count: 1,
    anchors: [],
    state: "active",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

function pillText(editor: Editor, anchorId: string): string | null {
  const el = editor.view.dom.querySelector(`.mutation-pill[data-mutation-id="${anchorId}"]`);
  return el ? el.textContent : null;
}

describe("the pill's label follows the store (ADR-0095 §1)", () => {
  it("relabels an existing pill when the set's title changes in the store — no doc transaction", () => {
    mutationSetEntriesStore.set([summary({ id: "s1", title: "Promotion" })]);
    mutationSetRosterLoadedStore.set(true);
    const editor = makeEditor();
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "s1", anchorId: "a1" } }).run();

    expect(pillText(editor, "a1")).toBe("⤳ Promotion");

    // Edit the set in the store (a save elsewhere) — the pill updates live.
    mutationSetEntriesStore.set([summary({ id: "s1", title: "Demotion" })]);
    expect(pillText(editor, "a1")).toBe("⤳ Demotion");
  });

  it("labels an untitled set from its row count", () => {
    mutationSetEntriesStore.set([summary({ id: "s1", title: "", row_count: 3 })]);
    mutationSetRosterLoadedStore.set(true);
    const editor = makeEditor();
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "s1", anchorId: "a1" } }).run();

    expect(pillText(editor, "a1")).toBe("⤳ 3 changes");
  });

  it("shows a missing pill once the roster has loaded and the set isn't in it", () => {
    mutationSetRosterLoadedStore.set(true); // loaded, roster empty
    const editor = makeEditor();
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "gone", anchorId: "a1" } }).run();

    const el = editor.view.dom.querySelector('.mutation-pill[data-mutation-id="a1"]');
    expect(el?.classList.contains("mutation-pill-missing")).toBe(true);
    expect(el?.getAttribute("title")).toMatch(/no longer exists/);
  });

  it("is NOT shown as missing before the roster has loaded", () => {
    // rosterLoaded still false (the default) — the roster fetch just hasn't
    // resolved yet, so a real pill must not flash "missing" during the load.
    const editor = makeEditor();
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "not-yet-loaded", anchorId: "a1" } }).run();

    const el = editor.view.dom.querySelector('.mutation-pill[data-mutation-id="a1"]');
    expect(el?.classList.contains("mutation-pill-missing")).toBe(false);
  });

  it("relabels a close pill's tooltip through the anchor→set store index too", () => {
    mutationSetEntriesStore.set([
      summary({ id: "s1", title: "Promotion", anchors: [{ anchor_id: "a1", scene_id: "sc1", scene_title: "Ch 1" }] }),
    ]);
    mutationSetRosterLoadedStore.set(true);
    const editor = makeEditor();
    editor.chain().insertContent({ type: "mutationClose", attrs: { ref: "a1", row: "", closeId: "c1" } }).run();

    const el = editor.view.dom.querySelector('.mutation-pill-close');
    expect(el?.getAttribute("title")).toBe("Closes Promotion");
  });
});
