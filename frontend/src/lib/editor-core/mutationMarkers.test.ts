// @vitest-environment happy-dom
// #2424: accepting an inline AI draft moves each existing mutation pill to its
// `⟦<anchor id>⟧` marker. Real TipTap editor + the real AiSuggestionController,
// so the accept flow, the aiSuggestion mark and MutationPasteReconciler are
// exercised together.
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { AISuggestion, createMutationCloseMark, createMutationMark } from "./proseMarks";
import { proseStarterKit } from "./proseStarterKit";
import { MutationPasteReconciler, type MutationPasteDeps } from "./mutationNodes";
import { AiSuggestionController } from "./aiSuggestion.svelte";
import { markerNotice } from "./mutationMarkers";

const A = "mut_0123456789ab";
const C = "mut_aaaaaaaaaaaa";
const SET = "mset_1";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

type Json = Record<string, unknown>;
const pill = (anchorId = A): Json => ({ type: "mutation", attrs: { setId: SET, anchorId } });
const close = (): Json => ({ type: "mutationClose", attrs: { ref: A, row: "", closeId: C } });
const para = (...content: Json[]): Json => ({ type: "paragraph", content });
const text = (t: string, suggestion = false): Json => ({
  type: "text",
  text: t,
  ...(suggestion ? { marks: [{ type: "aiSuggestion", attrs: { suggestionId: "ai-1" } }] } : {}),
});

function setup(content: Json[]) {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), AISuggestion, createMutationMark(), createMutationCloseMark()],
    content: { type: "doc", content },
  });
  editors.push(editor);
  const onNotice = vi.fn();
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => null,
    getDocumentKind: () => "manuscript",
    getPromptCtx: () => ({ promptEntries: [] }) as never,
    onInvocationCost: () => {},
    addCharacterCost: () => {},
    onRequestInputsDialog: () => {},
    onNotice,
    onOpenChat: () => {},
  });
  ctrl.suggestionId = "ai-1";
  return { editor, ctrl, onNotice };
}

function nodesOf(editor: Editor, type: string) {
  const out: { pos: number; attrs: Record<string, unknown> }[] = [];
  editor.state.doc.descendants((node, pos) => {
    if (node.type.name === type) out.push({ pos, attrs: { ...node.attrs } });
  });
  return out;
}
const plain = (editor: Editor) => editor.state.doc.textBetween(0, editor.state.doc.content.size, "|", "#");
const hasSuggestionMark = (editor: Editor) => {
  let found = false;
  editor.state.doc.descendants((node) => {
    if (node.marks.some((m) => m.type.name === "aiSuggestion")) found = true;
  });
  return found;
};

describe("accepting a draft with mutation markers (#2424)", () => {
  it("moves the pill to its marker mid-sentence, keeping its attrs and id", () => {
    const { editor, ctrl, onNotice } = setup([
      para(text("Beats: "), pill()),
      para(text(`He walked ⟦${A}⟧ home.`, true)),
    ]);
    const reconciler = new MutationPasteReconciler();
    reconciler.seed(editor);
    ctrl.accept();

    const pills = nodesOf(editor, "mutation");
    expect(pills).toHaveLength(1);
    expect(pills[0].attrs).toEqual({ setId: SET, anchorId: A });
    // The pill now sits after "He walked ", in the second paragraph.
    expect(plain(editor)).toBe("Beats: |He walked # home.");
    expect(editor.state.doc.resolve(pills[0].pos).parentOffset).toBe("He walked ".length);
    expect(plain(editor)).not.toContain("⟦");
    expect(hasSuggestionMark(editor)).toBe(false);

    // The paste reconciler sees one known pill: no re-mint, no copy.
    const deps: MutationPasteDeps = {
      isManuscript: () => true,
      knownProjectAnchorIds: () => new Set<string>(),
      copySet: vi.fn(),
    };
    expect(reconciler.reconcile(editor, deps)).toBe(false);
    expect(nodesOf(editor, "mutation")[0].attrs).toEqual({ setId: SET, anchorId: A });
    expect(onNotice).toHaveBeenCalledWith("Placed 1 change in the draft.");
  });

  it("moves a close pill by its closeId", () => {
    const { editor, ctrl } = setup([
      para(text("Beats: "), close()),
      para(text(`Until ⟦${C}⟧ here.`, true)),
    ]);
    ctrl.accept();
    const closes = nodesOf(editor, "mutationClose");
    expect(closes).toHaveLength(1);
    expect(closes[0].attrs).toEqual({ ref: A, row: "", closeId: C });
    expect(editor.state.doc.resolve(closes[0].pos).parentOffset).toBe("Until ".length);
    expect(plain(editor)).not.toContain("⟦");
  });

  it("removes an unknown marker; a pill without a marker stays put", () => {
    const { editor, ctrl, onNotice } = setup([
      para(text("Beats: "), pill()),
      para(text("One ⟦mut_ffffffffffff⟧ two.", true)),
    ]);
    ctrl.accept();
    expect(plain(editor)).toBe("Beats: #|One  two.");
    const pills = nodesOf(editor, "mutation");
    expect(pills).toHaveLength(1);
    expect(editor.state.doc.resolve(pills[0].pos).parent.textContent).toBe("Beats: ");
    expect(onNotice).toHaveBeenCalledWith(
      "1 marker didn't match a change in this scene and was removed.",
    );
  });

  it("takes backticks the model echoed from the brief along with the marker", () => {
    const { editor, ctrl } = setup([
      para(text("Beats: "), pill()),
      para(text(`He knelt \`⟦${A}⟧\` before her.`, true)),
    ]);
    ctrl.accept();
    expect(plain(editor)).toBe("Beats: |He knelt # before her.");
    expect(nodesOf(editor, "mutation")).toHaveLength(1);
  });

  it("moves a pill whose id is legacy-derived, not minted with mut_ (#2435 parity)", () => {
    const legacy = "unit7_1a2b3c";
    const { editor, ctrl } = setup([
      para(text("Beats: "), pill(legacy)),
      para(text(`He knelt ⟦${legacy}⟧ before her.`, true)),
    ]);
    ctrl.accept();
    expect(plain(editor)).toBe("Beats: |He knelt # before her.");
    expect(nodesOf(editor, "mutation")).toHaveLength(1);
  });

  it("leaves an unknown non-mut_ bracket in the text", () => {
    const { editor, ctrl } = setup([para(text("Beats.")), para(text("A ⟦note⟧ stays.", true))]);
    ctrl.accept();
    expect(plain(editor)).toBe("Beats.|A ⟦note⟧ stays.");
  });

  it("a duplicate marker for one id leaves a single pill, at the first", () => {
    const { editor, ctrl } = setup([
      para(text("Beats: "), pill()),
      para(text(`A ⟦${A}⟧ b ⟦${A}⟧ c.`, true)),
    ]);
    ctrl.accept();
    const pills = nodesOf(editor, "mutation");
    expect(pills).toHaveLength(1);
    expect(editor.state.doc.resolve(pills[0].pos).parentOffset).toBe("A ".length);
    expect(plain(editor)).toBe("Beats: |A # b  c.");
  });

  it("a suggestion without markers accepts exactly as before", () => {
    const { editor, ctrl, onNotice } = setup([
      para(text("Beats: "), pill()),
      para(text("Plain draft.", true)),
    ]);
    ctrl.accept();
    expect(plain(editor)).toBe("Beats: #|Plain draft.");
    expect(nodesOf(editor, "mutation")).toHaveLength(1);
    expect(hasSuggestionMark(editor)).toBe(false);
    expect(onNotice).not.toHaveBeenCalled();
  });
});

describe("markerNotice", () => {
  it("is plain words and null when nothing happened", () => {
    expect(markerNotice(3, 2)).toBe(
      "Placed 3 changes in the draft. 2 markers didn't match a change in this scene and were removed.",
    );
    expect(markerNotice(0, 0)).toBeNull();
  });
});
