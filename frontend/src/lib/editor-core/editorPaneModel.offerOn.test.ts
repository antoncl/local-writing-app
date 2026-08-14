// isEditorPaneDirty's offer_on arm (ADR-0054 §4 / S4b). Editing the ＋New
// targeting allow-list must arm autosave the same way editing inputs does — and,
// like inputs, must never mark a non-prompt pane dirty (no offer_on baseline).
import { describe, expect, it } from "vitest";
import { isEditorPaneDirty } from "./editorPaneModel";
import type { EditableDocument } from "@/lib/types";

function promptScene(offerOn: string[]): EditableDocument {
  return {
    id: "prompt_1",
    title: "Impersonate",
    body: "brief",
    entry_type: "prompt:general",
    metadata: {},
    inputs: [],
    offer_on: offerOn,
  } as unknown as EditableDocument;
}

// The unchanged non-offer_on args, so only the last param varies below.
const base = (scene: EditableDocument) =>
  [scene, scene.title, scene.body ?? "", "", scene.entry_type, {}] as const;

describe("isEditorPaneDirty — offer_on (S4b)", () => {
  it("is clean when the draft allow-list equals the baseline", () => {
    const scene = promptScene(["lore:character"]);
    expect(isEditorPaneDirty(...base(scene), [], ["lore:character"])).toBe(false);
  });

  it("is dirty when the draft allow-list diverges (add)", () => {
    const scene = promptScene(["lore:character"]);
    expect(isEditorPaneDirty(...base(scene), [], ["lore:character", "plot:card"])).toBe(true);
  });

  it("is dirty when the draft allow-list diverges (clear)", () => {
    const scene = promptScene(["lore:character"]);
    expect(isEditorPaneDirty(...base(scene), [], [])).toBe(true);
  });

  it("order is significant — a reordered list reads as an edit", () => {
    const scene = promptScene(["lore:character", "plot:card"]);
    expect(isEditorPaneDirty(...base(scene), [], ["plot:card", "lore:character"])).toBe(true);
  });

  it("never marks a non-prompt pane dirty (no offer_on baseline)", () => {
    const lore = {
      id: "lore_1",
      title: "Hero",
      body: "b",
      entry_type: "lore:character",
      metadata: {},
    } as unknown as EditableDocument;
    // A non-prompt scene has no offer_on; the store still passes the pane's
    // (empty) draftOfferOn, which must be inert here.
    expect(isEditorPaneDirty(lore, lore.title, "b", "", lore.entry_type, {}, undefined, [])).toBe(false);
  });
});
