// @vitest-environment happy-dom
// The close marker's node view and `/roleplay split` through a REAL TipTap
// editor (ADR-0070 Amendment 1, decisions 4 and 6). The point of decision 4 is
// that editing the interiority never rebuilds the marker's DOM, so these tests
// hold on to the DOM elements and check they survive.
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync } from "svelte";
import { Editor } from "@tiptap/core";

import { proseStarterKit } from "./proseStarterKit";
import { BeatCloseMarker, BeatOpenMarker, splitBeatAtCursor } from "./beatMarkers";
import { scanBeats } from "./beats";
import { InteriorityReveal, INTERIORITY_META, interiorityAnyRevealed } from "./interiorityReveal";
import { sceneMarkdownToHtml } from "../utils/markdown";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
  document.body.innerHTML = "";
});

async function mountScene(markdown: string): Promise<Editor> {
  const element = document.createElement("div");
  document.body.appendChild(element);
  const editor = new Editor({
    element,
    extensions: [
      proseStarterKit(),
      BeatOpenMarker,
      BeatCloseMarker.configure({ colorForId: () => "red", proofreadNodeId: () => null }),
      InteriorityReveal.configure({ colorForId: () => "red", titleForId: () => "Elias" }),
    ],
    content: await sceneMarkdownToHtml(markdown),
  });
  editors.push(editor);
  return editor;
}

const closeDom = (editor: Editor) => editor.view.dom.querySelector<HTMLElement>("span.beat-close")!;

function reveal(editor: Editor): void {
  const [beat] = scanBeats(editor.state.doc).beats;
  editor.view.dispatch(editor.state.tr.setMeta(INTERIORITY_META.toggleOne, beat.close));
  flushSync();
}

/** The nested editor mounted in a revealed close marker, once it has loaded
 *  its value (the markdown load is async). */
async function innerEditor(editor: Editor, loaded: string): Promise<Editor> {
  let inner: Editor | undefined;
  await vi.waitFor(() => {
    const dom = closeDom(editor).querySelector<HTMLElement & { editor?: Editor }>(".interiority-block .ProseMirror");
    inner = dom?.editor;
    expect(inner?.getText()).toBe(loaded);
  });
  return inner!;
}

const BEAT = "<!-- character:id=lore_1 -->She fired.\n\nThen ran.<!-- /character:id=lore_1;internal=Steady. -->";

describe("the close marker's node view", () => {
  it("is one handle per beat, coloured, and opens the interiority in the long-text editor", async () => {
    const editor = await mountScene(BEAT);
    const dom = closeDom(editor);
    expect(dom.style.getPropertyValue("--character-color")).toBe("red");
    expect(dom.querySelector(".interiority-block")).toBeNull();
    reveal(editor);
    expect(dom.querySelector(".interiority-handle")?.getAttribute("aria-expanded")).toBe("true");
    await innerEditor(editor, "Steady.");
  });

  it("writes an edit to the close marker's interiority without rebuilding the marker", async () => {
    const editor = await mountScene(BEAT);
    reveal(editor);
    const dom = closeDom(editor);
    const block = dom.querySelector(".interiority-block");
    (await innerEditor(editor, "Steady.")).commands.insertContentAt(1, "Hold ");
    flushSync();
    const [beat] = scanBeats(editor.state.doc).beats;
    expect(beat.internal).toBe("Hold Steady.");
    // Same marker element, same open box: nothing was redrawn.
    expect(closeDom(editor)).toBe(dom);
    expect(dom.querySelector(".interiority-block")).toBe(block);
  });

  it("keeps the box open while the author types in the beat's prose", async () => {
    const editor = await mountScene(BEAT);
    reveal(editor);
    const dom = closeDom(editor);
    editor.commands.insertContentAt(3, "x");
    flushSync();
    expect(closeDom(editor)).toBe(dom);
    expect(dom.querySelector(".interiority-block")).not.toBeNull();
  });

  it("shows an end marker with no beat as broken, and never opens it", async () => {
    const editor = await mountScene("Narration.<!-- /character:id=lore_1;internal=Lost. -->");
    const dom = closeDom(editor);
    expect(dom.classList.contains("beat-marker-broken")).toBe(true);
    editor.view.dispatch(editor.state.tr.setMeta(INTERIORITY_META.revealAll, true));
    flushSync();
    expect(dom.querySelector(".interiority-block")).toBeNull();
  });
});

describe("a read-only body", () => {
  it("opens the interiority read-only, and an edit there never reaches the marker", async () => {
    const editor = await mountScene(BEAT);
    editor.setEditable(false);
    reveal(editor);
    const inner = await innerEditor(editor, "Steady.");
    expect(inner.isEditable).toBe(false);
    inner.commands.insertContentAt(1, "Hold ");
    flushSync();
    expect(scanBeats(editor.state.doc).beats[0].internal).toBe("Steady.");
  });
});

describe("/roleplay split", () => {
  it("ends the beat at the cursor, starts a new one, and reveals both copies of the interiority", async () => {
    const editor = await mountScene(BEAT);
    // Inside the second paragraph, before "Then".
    const pos = editor.state.doc.child(0).nodeSize + 1;
    editor.commands.setTextSelection(pos);
    splitBeatAtCursor(editor.view);
    flushSync();
    const { beats, orphans } = scanBeats(editor.state.doc);
    expect(orphans).toEqual([]);
    expect(beats.map((b) => [b.characterId, b.internal])).toEqual([
      ["lore_1", "Steady."],
      ["lore_1", "Steady."],
    ]);
    expect(editor.state.doc.textBetween(beats[0].open, beats[0].close, "\n")).toBe("She fired.\n");
    expect(editor.state.doc.textBetween(beats[1].open, beats[1].close, "\n")).toBe("Then ran.");
    expect(interiorityAnyRevealed(editor.state)).toBe(true);
    expect(editor.view.dom.querySelectorAll(".interiority-block")).toHaveLength(2);
  });

  it("does nothing outside a beat", async () => {
    const editor = await mountScene(`Narration.\n\n${BEAT}`);
    editor.commands.setTextSelection(2);
    const before = editor.state.doc;
    splitBeatAtCursor(editor.view);
    expect(editor.state.doc.eq(before)).toBe(true);
  });
});
