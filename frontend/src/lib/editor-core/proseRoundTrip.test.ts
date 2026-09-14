// @vitest-environment happy-dom
// The full scene round-trip through a REAL TipTap editor (#1866). The
// characterization tests in utils/markdown.test.ts drive turndown with
// hand-authored HTML strings — they never call editor.getHTML(), so a change
// in how a custom node/mark serialises (attribute order, wrapper, class, a
// StarterKit default that leaks an extra node) would keep those green while
// real saves regress. This test mounts the production extension set and takes
// the loop the app actually takes on every save:
//     markdown -> sceneMarkdownToHtml -> editor.setContent -> editor.getHTML
//                 -> editorHtmlToSceneMarkdown -> markdown
// so getHTML()'s shape is pinned against the TipTap version in the lockfile.
import { afterEach, describe, expect, it } from "vitest";
import { Editor, type Extensions } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import {
  AISuggestion,
  TodoAnchor,
  createCharacterMark,
  createMutationCloseMark,
  createMutationMark,
} from "./proseMarks";
import { tableExtensions } from "./alignedTable";
import { editorHtmlToSceneMarkdown, sceneMarkdownToHtml } from "../utils/markdown";

// A live editor schedules a DOM observer flush that fires after the environment
// is torn down, so every editor is destroyed after the test that made it.
const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

/** The production prose extension set (mirrors ProseBodyView.svelte). The
 *  marker factories take resolver callbacks that only affect the pill's visible
 *  label — turndown reconstructs each marker from its data-* attributes, not its
 *  text — so stub resolvers keep the round-trip faithful. */
function proseExtensions(): Extensions {
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3] },
      link: false,
      underline: false,
      trailingNode: false,
    }),
    AISuggestion,
    createCharacterMark({ colorForId: () => "", titleForId: () => "Character" }),
    createMutationMark({ labelForMarker: () => "label" }),
    createMutationCloseMark({ labelForClose: () => "Closes" }),
    TodoAnchor,
    ...tableExtensions,
  ];
}

/** Mount a real editor on `html` and return its serialised HTML. */
function editorHtml(html: string): string {
  const editor = new Editor({ element: document.createElement("div"), extensions: proseExtensions(), content: html });
  editors.push(editor);
  return editor.getHTML();
}

/** The full save-shaped loop: on-disk markdown, into the editor, back to disk. */
async function roundTrip(markdown: string): Promise<string> {
  const html = await sceneMarkdownToHtml(markdown);
  return editorHtmlToSceneMarkdown(editorHtml(html));
}

describe("scene round-trip through a real editor (#1866)", () => {
  // Each is already in the canonical on-disk form the save side emits, so a
  // faithful editor must reproduce it exactly after a full loop.
  it.each([
    ["a character mark in prose", "The lighthouse kept <!-- character:id=lore_1 -->Mira<!-- /character --> awake."],
    ["an embedded todo", "<!-- embedded-todo:id=todo1;status=open;note= -->fix this line<!-- /embedded-todo -->"],
    ["a single-row mutation pill", "<!-- mutate:entity=lore_1;field=status;value=dead;id=mut1 -->"],
    ["a mutation close pill", "<!-- mutate:close;ref=mut1;id=close1 -->"],
    ["a heading and a paragraph", "# Title\n\nA paragraph of prose."],
  ])("preserves %s byte-for-byte", async (_label, markdown) => {
    expect(await roundTrip(markdown)).toBe(markdown);
  });

  it("serialises a bullet list stably (idempotent after the first loop)", async () => {
    // A tight list is re-emitted in turndown's loose form (each <li> carries a
    // <p>), so it is not byte-equal to a hand-tightened input — but it must be a
    // FIXED POINT: a second loop changes nothing. That stability is the real
    // invariant, and a v3 list-serialisation change would break it.
    const once = await roundTrip("- one\n- two");
    expect(await roundTrip(once)).toBe(once);
    expect(once).toContain("- one");
    expect(once).toContain("- two");
  });

  it("keeps a fenced code block's language across the loop", async () => {
    const out = await roundTrip("```js\nconst x = 1;\n```");
    // The language tag rides a `language-*` class on <code>; a v3 CodeBlock
    // prefix change would drop it here (turndown reads the class).
    expect(out).toBe("```js\nconst x = 1;\n```");
  });

  it("keeps GFM table column alignment across the loop", async () => {
    // The align attribute serialises as an inline text-align style through the
    // consolidated v3 @tiptap/extension-table; turndown maps it back to the
    // :--/--: separator. Assert the alignment markers survive (whitespace in the
    // separator row is normalised by marked, so match the colons, not the row).
    const out = await roundTrip("| A | B |\n| :-- | --: |\n| 1 | 2 |");
    const separator = out.split("\n")[1] ?? "";
    expect(separator).toMatch(/:-+\s*\|\s*-+:/); // left-aligned A, right-aligned B
  });

  it("does not leak a trailing empty paragraph (trailingNode is off)", () => {
    // StarterKit v3 bundles TrailingNode on by default; if the opt-out ever
    // regresses, getHTML() gains a permanent trailing <p></p> that drifts the
    // saved body once anything defeats the .trim() cushion.
    expect(editorHtml("<p>hello</p>")).toBe("<p>hello</p>");
  });
});
