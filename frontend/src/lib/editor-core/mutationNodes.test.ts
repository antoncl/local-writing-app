// @vitest-environment happy-dom
// ADR-0095 §1/§3/§7: the pill's id-mechanics and paste/cut/copy reconciler,
// plus the reveal helpers. Built against a REAL TipTap editor (mirrors
// proseRoundTrip.test.ts) so the reconciler's transaction/position handling
// is pinned against the actual schema, not a hand-rolled doc double. A true
// browser clipboard event can't be simulated in happy-dom, so "paste" here
// is `insertContent` (the same doc-mutating effect a paste has) followed by
// calling `reconcile` directly — the same call ProseBodyView's onUpdate
// makes once a paste-shaped transaction lands.
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { createMutationCloseMark, createMutationMark } from "./proseMarks";
import { proseStarterKit } from "./proseStarterKit";
import {
  MutationPasteReconciler,
  anchorIdFromRevealTarget,
  createMutationId,
  findMutationNodePos,
  mutationSetLabel,
  recordMutationClipboard,
  resetMutationClipboardForTest,
  resolveMutationRevealAnchor,
  revealMutationPill,
  type MutationPasteDeps,
} from "./mutationNodes";
import type { CopyMutationSetResult, MutationMarkerRecord } from "@/lib/types";

const editors: Editor[] = [];
function makeEditor(html = "<p></p>"): Editor {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), createMutationMark(), createMutationCloseMark()],
    content: html,
  });
  editors.push(editor);
  return editor;
}
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
  resetMutationClipboardForTest();
  vi.restoreAllMocks();
});

function anchorAttrs(editor: Editor, anchorId: string): { setId: string; anchorId: string } | null {
  let hit: { setId: string; anchorId: string } | null = null;
  editor.state.doc.descendants((node) => {
    if (node.type.name === "mutation" && node.attrs.anchorId === anchorId) {
      hit = { setId: String(node.attrs.setId ?? ""), anchorId: String(node.attrs.anchorId ?? "") };
    }
  });
  return hit;
}

function baseDeps(over: Partial<MutationPasteDeps> = {}): MutationPasteDeps {
  return {
    isManuscript: () => true,
    knownProjectAnchorIds: () => new Set<string>(),
    copySet: vi.fn(async (): Promise<CopyMutationSetResult> => {
      throw new Error("not stubbed");
    }),
    onNotice: vi.fn(),
    ...over,
  };
}

describe("mutationSetLabel", () => {
  it("prefers the title", () => {
    expect(
      mutationSetLabel({ title: "Promotion", rows: [{ field: "rank", op: "replace", value: "Captain" }] }),
    ).toBe("Promotion");
  });
  it("falls back to the sole row's auto-label for an untitled single-row set (the pre-ADR-0095 rule)", () => {
    expect(mutationSetLabel({ title: "", rows: [{ field: "rank", op: "replace", value: "Captain" }] })).toBe(
      "rank → Captain",
    );
  });
  it("falls back to a row count for an untitled multi-row set", () => {
    expect(
      mutationSetLabel({
        title: "",
        rows: [
          { field: "rank", op: "replace", value: "Captain" },
          { field: "title", op: "replace", value: "The Wolf" },
          { field: "eyes", op: "replace", value: "silver" },
        ],
      }),
    ).toBe("3 changes");
  });
  it("is empty for no entry (not yet in the roster)", () => {
    expect(mutationSetLabel(undefined)).toBe("");
  });
});

describe("reveal helpers (ADR-0095 §3/§4)", () => {
  it("anchorIdFromRevealTarget splits a composite id on the first dot", () => {
    expect(anchorIdFromRevealTarget("mut_anchor.mut_row")).toBe("mut_anchor");
    expect(anchorIdFromRevealTarget("mut_anchor")).toBe("mut_anchor");
  });

  it("revealMutationPill finds a pill by its bare anchor id", () => {
    const el = document.createElement("div");
    el.innerHTML = '<span class="mutation-pill" data-mutation-id="a1"></span>';
    document.body.appendChild(el);
    expect(revealMutationPill(el, "a1")).toBe(true);
    expect(el.querySelector(".mutation-pill")?.classList.contains("mutation-pill-revealed")).toBe(true);
    el.remove();
  });

  it("revealMutationPill finds the same pill by a composite <anchor>.<row> id", () => {
    const el = document.createElement("div");
    el.innerHTML = '<span class="mutation-pill" data-mutation-id="a1"></span>';
    document.body.appendChild(el);
    expect(revealMutationPill(el, "a1.row1")).toBe(true);
    el.remove();
  });

  it("revealMutationPill returns false when nothing matches", () => {
    const el = document.createElement("div");
    expect(revealMutationPill(el, "missing")).toBe(false);
  });

  it("resolveMutationRevealAnchor resolves a composite id with no fetch", async () => {
    const getEntityMutations = vi.fn();
    const anchor = await resolveMutationRevealAnchor(getEntityMutations, "ent1", "a1.row1", "scene1");
    expect(anchor).toBe("a1");
    expect(getEntityMutations).not.toHaveBeenCalled();
  });

  it("resolveMutationRevealAnchor finds a bare row id's anchor, preferring the open scene", async () => {
    const records: MutationMarkerRecord[] = [
      { marker_id: "a1.row1", entity_id: "ent1", field: "f", op: "replace", value: "v", name: "", group: "", unit_id: "a1", unit_name: "", anchor_id: "a1", set_id: "s1", row_id: "row1", scene_id: "elsewhere", offset: 0, line: 1, scene_path: "" },
      { marker_id: "a2.row1", entity_id: "ent1", field: "f", op: "replace", value: "v", name: "", group: "", unit_id: "a2", unit_name: "", anchor_id: "a2", set_id: "s1", row_id: "row1", scene_id: "scene1", offset: 0, line: 1, scene_path: "" },
    ];
    const getEntityMutations = vi.fn(async () => ({ items: records }));
    const anchor = await resolveMutationRevealAnchor(getEntityMutations, "ent1", "row1", "scene1");
    expect(anchor).toBe("a2"); // the record in the OPEN scene wins
  });

  it("resolveMutationRevealAnchor falls back to manuscript order when none is in the open scene", async () => {
    const records: MutationMarkerRecord[] = [
      { marker_id: "a1.row1", entity_id: "ent1", field: "f", op: "replace", value: "v", name: "", group: "", unit_id: "a1", unit_name: "", anchor_id: "a1", set_id: "s1", row_id: "row1", scene_id: "chapter1", offset: 0, line: 1, scene_path: "" },
    ];
    const getEntityMutations = vi.fn(async () => ({ items: records }));
    const anchor = await resolveMutationRevealAnchor(getEntityMutations, "ent1", "row1", "chapter9");
    expect(anchor).toBe("a1");
  });

  it("resolveMutationRevealAnchor returns the input id when nothing matches", async () => {
    const getEntityMutations = vi.fn(async () => ({ items: [] }));
    expect(await resolveMutationRevealAnchor(getEntityMutations, "ent1", "row1", "s")).toBe("row1");
  });
});

describe("MutationPasteReconciler — paste/copy (ADR-0095 §7)", () => {
  it("an anchor pasted with a known-elsewhere id becomes a copy: new id, setId cleared at once, then filled in once copySet resolves", async () => {
    const editor = makeEditor();
    const reconciler = new MutationPasteReconciler();
    reconciler.seed(editor);
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "orig-set", anchorId: "pasted-anchor" } }).run();

    let resolveCopy!: (r: CopyMutationSetResult) => void;
    const copySet = vi.fn(
      () => new Promise<CopyMutationSetResult>((resolve) => { resolveCopy = resolve; }),
    );
    const deps = baseDeps({ knownProjectAnchorIds: () => new Set(["pasted-anchor"]), copySet });

    reconciler.reconcile(editor, deps);

    // Synchronously: a fresh id, no original id left, setId cleared at once —
    // never even briefly naming the original set (ADR-0095 §7 anti-goal).
    expect(anchorAttrs(editor, "pasted-anchor")).toBeNull();
    const nodes: { setId: string; anchorId: string }[] = [];
    editor.state.doc.descendants((node) => {
      if (node.type.name === "mutation") nodes.push({ setId: String(node.attrs.setId ?? ""), anchorId: String(node.attrs.anchorId ?? "") });
    });
    expect(nodes).toHaveLength(1);
    expect(nodes[0].anchorId).not.toBe("pasted-anchor");
    expect(nodes[0].setId).toBe("");
    const newAnchorId = nodes[0].anchorId;
    expect(copySet).toHaveBeenCalledWith("orig-set");

    resolveCopy({ entry: { id: "copied-set" } as never, dropped_rows: [] });
    await Promise.resolve();
    await Promise.resolve();

    expect(anchorAttrs(editor, newAnchorId)?.setId).toBe("copied-set");
  });

  it("one undo after a paste-copy resolves removes the pasted pill entirely — no intermediate missing pill (review fix #2236)", async () => {
    const editor = makeEditor();
    const reconciler = new MutationPasteReconciler();
    reconciler.seed(editor);
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "orig-set", anchorId: "pasted-anchor" } }).run();

    let resolveCopy!: (r: CopyMutationSetResult) => void;
    const copySet = vi.fn(
      () => new Promise<CopyMutationSetResult>((resolve) => { resolveCopy = resolve; }),
    );
    const deps = baseDeps({ knownProjectAnchorIds: () => new Set(["pasted-anchor"]), copySet });

    reconciler.reconcile(editor, deps);
    resolveCopy({ entry: { id: "copied-set" } as never, dropped_rows: [] });
    await Promise.resolve();
    await Promise.resolve();

    // The fill-in landed (setId is no longer empty) before undo is tried.
    const filled: string[] = [];
    editor.state.doc.descendants((node) => {
      if (node.type.name === "mutation") filled.push(String(node.attrs.setId ?? ""));
    });
    expect(filled).toEqual(["copied-set"]);

    editor.commands.undo();

    // The fill-in dispatch is not its own undo step (`addToHistory: false`),
    // so the one undo reaches the paste itself and removes the pill outright
    // — never landing on the intermediate "missing set" state.
    const remaining: string[] = [];
    editor.state.doc.descendants((node) => {
      if (node.type.name === "mutation") remaining.push(String(node.attrs.anchorId ?? ""));
    });
    expect(remaining).toEqual([]);
  });

  it("leaves the pill missing (no setId) when copySet fails, and surfaces a notice", async () => {
    const editor = makeEditor();
    const reconciler = new MutationPasteReconciler();
    reconciler.seed(editor);
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "orig-set", anchorId: "pasted-anchor" } }).run();
    const onNotice = vi.fn();
    const deps = baseDeps({
      knownProjectAnchorIds: () => new Set(["pasted-anchor"]),
      copySet: vi.fn(async () => { throw new Error("boom"); }),
      onNotice,
    });

    reconciler.reconcile(editor, deps);
    await Promise.resolve();
    await Promise.resolve();

    const nodes: string[] = [];
    editor.state.doc.descendants((node) => {
      if (node.type.name === "mutation") nodes.push(String(node.attrs.setId ?? ""));
    });
    expect(nodes).toEqual([""]);
    expect(onNotice).toHaveBeenCalled();
  });

  it("a cut's first paste keeps the same anchor and set; a second paste of the same clipboard is a copy", async () => {
    const editor = makeEditor();
    const reconciler = new MutationPasteReconciler();
    reconciler.seed(editor);
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "the-set", anchorId: "cut-anchor" } }).run();
    reconciler.reconcile(editor, baseDeps()); // establishes the baseline, no ledger yet

    // Simulate the cut: the app records it AND forgets the id locally (the
    // ProseBodyView cut handler does both in one place).
    recordMutationClipboard("cut", ["cut-anchor"]);
    reconciler.forget(["cut-anchor"]);
    // ...the cut also deletes the node from the doc.
    const pos = findMutationNodePos(editor, "cut-anchor");
    const node = pos !== null ? editor.state.doc.nodeAt(pos) : null;
    if (pos !== null && node) editor.view.dispatch(editor.state.tr.delete(pos, pos + node.nodeSize));

    // First paste: pasted back in, same ids.
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "the-set", anchorId: "cut-anchor" } }).run();
    const copySet = vi.fn(async (): Promise<CopyMutationSetResult> => ({ entry: { id: "copy-1" } as never, dropped_rows: [] }));
    reconciler.reconcile(editor, baseDeps({ copySet }));
    expect(anchorAttrs(editor, "cut-anchor")).toEqual({ setId: "the-set", anchorId: "cut-anchor" });
    expect(copySet).not.toHaveBeenCalled();

    // Second paste of the SAME clipboard (ledger not re-recorded) is a copy.
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "the-set", anchorId: "cut-anchor" } }).run();
    reconciler.reconcile(editor, baseDeps({ copySet }));
    expect(copySet).toHaveBeenCalledWith("the-set");
  });

  it("content from outside the app is a copy when its anchor id already exists in the project", () => {
    const editor = makeEditor();
    const reconciler = new MutationPasteReconciler();
    reconciler.seed(editor);
    const copySet = vi.fn(async (): Promise<CopyMutationSetResult> => ({ entry: { id: "copy-1" } as never, dropped_rows: [] }));
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "the-set", anchorId: "outside-anchor" } }).run();

    reconciler.reconcile(editor, baseDeps({ knownProjectAnchorIds: () => new Set(["outside-anchor"]), copySet }));

    expect(copySet).toHaveBeenCalledWith("the-set");
  });

  it("content from outside the app with an unknown anchor id is kept as pasted", () => {
    const editor = makeEditor();
    const reconciler = new MutationPasteReconciler();
    reconciler.seed(editor);
    const copySet = vi.fn();
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "the-set", anchorId: "brand-new" } }).run();

    reconciler.reconcile(editor, baseDeps({ copySet }));

    expect(anchorAttrs(editor, "brand-new")).toEqual({ setId: "the-set", anchorId: "brand-new" });
    expect(copySet).not.toHaveBeenCalled();
  });

  it("drops an anchor pasted into a non-manuscript body", () => {
    const editor = makeEditor();
    const reconciler = new MutationPasteReconciler();
    reconciler.seed(editor);
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "the-set", anchorId: "a1" } }).run();

    reconciler.reconcile(editor, baseDeps({ isManuscript: () => false }));

    let count = 0;
    editor.state.doc.descendants((node) => {
      if (node.type.name === "mutation") count += 1;
    });
    expect(count).toBe(0);
  });

  it("repoints a close pasted together with its anchor to the anchor's new id", () => {
    const editor = makeEditor();
    const reconciler = new MutationPasteReconciler();
    reconciler.seed(editor);
    editor
      .chain()
      .insertContent({ type: "mutation", attrs: { setId: "the-set", anchorId: "dup-anchor" } })
      .insertContent({ type: "mutationClose", attrs: { ref: "dup-anchor", row: "", closeId: createMutationId() } })
      .run();

    reconciler.reconcile(editor, baseDeps({ knownProjectAnchorIds: () => new Set(["dup-anchor"]) }));

    let ref = "";
    let anchorId = "";
    editor.state.doc.descendants((node) => {
      if (node.type.name === "mutationClose") ref = String(node.attrs.ref ?? "");
      if (node.type.name === "mutation") anchorId = String(node.attrs.anchorId ?? "");
    });
    expect(anchorId).not.toBe("dup-anchor");
    expect(ref).toBe(anchorId);
  });
});
