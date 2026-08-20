// @vitest-environment happy-dom
// markdown.ts is the load/save serializer between the editor's HTML and the
// on-disk scene Markdown, and it runs on every autosave. The invariant these
// lock is load→save idempotency: a markdown file that round-trips through the
// editor (md → html → md) must not drift, and the app-specific markers
// (embedded todo / character / mutation / close) must survive byte-for-byte.
// Characterization tests — they pin current behaviour so a serializer refactor
// can't silently rewrite prose.
import { describe, it, expect } from "vitest";
import { sceneMarkdownToHtml, editorHtmlToSceneMarkdown } from "./markdown";

/** One load→save cycle: markdown → editor HTML → markdown (what an open-then-save
 *  does to a file). */
async function roundTrip(md: string): Promise<string> {
  return editorHtmlToSceneMarkdown(await sceneMarkdownToHtml(md));
}

describe("markdown round-trip — standard prose constructs", () => {
  const canonical = [
    ["a heading", "# The Departure"],
    ["a level-2 heading", "## Chapter one"],
    ["bold", "This is **bold** text."],
    ["italic (underscore is turndown's canonical em)", "This is _emphasis_ here."],
    ["a blockquote", "> To be, or not to be."],
    ["two paragraphs", "First paragraph.\n\nSecond paragraph."],
  ] as const;

  for (const [label, md] of canonical) {
    it(`preserves ${label} unchanged`, async () => {
      expect(await roundTrip(md)).toBe(md);
    });
  }

  // A few constructs are re-emitted in turndown's canonical form on the first
  // save (a one-time normalization), then stay put. The invariant that matters
  // for autosave is that they DON'T drift further — no progressive corruption.
  it("normalizes lists and strikethrough to a stable form, then holds", async () => {
    const cases: [string, string][] = [
      ["This is ~~struck~~ text.", "This is ~struck~ text."], // ~~ → ~
      ["- one\n- two", "-   one\n-   two"], // bullet marker padded
      ["1. first\n2. second", "1.  first\n2.  second"], // ordered marker padded
    ];
    for (const [input, settled] of cases) {
      const once = await roundTrip(input);
      expect(once).toBe(settled); // documents the one-time normalization
      expect(await roundTrip(once)).toBe(once); // and no further drift
    }
  });

  it("is idempotent on a mixed document: a second round-trip changes nothing", async () => {
    const messy = "# Title\n\nSome *star-italic* and **bold** with\n\n- a\n- b\n\n> quote";
    const once = await roundTrip(messy);
    expect(await roundTrip(once)).toBe(once);
  });

  it("returns empty string for empty input without throwing", async () => {
    expect(await roundTrip("")).toBe("");
  });
});

describe("markdown round-trip — GFM tables", () => {
  it("preserves a table with column alignments", async () => {
    const md = [
      "| Character | Knows? |",
      "| :--- | :---: |",
      "| Mira | yes |",
      "| Jonas | no |",
    ].join("\n");
    const out = await roundTrip(md);
    expect(out).toContain("| Character | Knows? |");
    // Alignment survives: left (:---) and centre (:---:) markers preserved.
    expect(out).toContain(":---");
    expect(out).toContain(":---:");
    expect(out).toContain("| Mira | yes |");
    // And it settles — a second pass is stable.
    expect(await roundTrip(out)).toBe(out);
  });

  it("escapes a literal pipe inside a cell so the table shape survives", async () => {
    const md = ["| Note |", "| --- |", "| a \\| b |"].join("\n");
    const out = await roundTrip(md);
    expect(out).toContain("a \\| b");
    expect(await roundTrip(out)).toBe(out);
  });
});

describe("markdown round-trip — scene breaks (horizontalRule)", () => {
  // Scene breaks are inserted via the slash menu (#1239) and settle to the
  // dinkus turndown is now pinned to emit. The invariant: whatever thematic
  // break a writer typed, the file settles to `* * *` and stops drifting.
  it("keeps a `* * *` scene break byte-stable", async () => {
    expect(await roundTrip("* * *")).toBe("* * *");
  });

  it("normalizes other thematic breaks to `* * *`, then holds", async () => {
    for (const input of ["---", "***", "___"]) {
      const once = await roundTrip(input);
      expect(once).toBe("* * *");
      expect(await roundTrip(once)).toBe(once); // no further drift
    }
  });

  it("preserves a scene break between two paragraphs", async () => {
    const md = "The door closed.\n\n* * *\n\nMorning came.";
    const once = await roundTrip(md);
    expect(once).toContain("The door closed.");
    expect(once).toContain("* * *");
    expect(once).toContain("Morning came.");
    expect(await roundTrip(once)).toBe(once);
  });
});

describe("markdown round-trip — content-bearing markers stay byte-stable", () => {
  // Todo and character markers wrap prose, so they survive the serializer alone.
  const markers = [
    ["an embedded todo", "<!-- embedded-todo:id=todo1;status=open;note= -->fix this line<!-- /embedded-todo -->"],
    ["a done todo with a note", "<!-- embedded-todo:id=todo2;status=done;note=check%20the%20date -->the date<!-- /embedded-todo -->"],
    ["a character mark", "<!-- character:id=lore_1 -->Mira<!-- /character -->"],
  ] as const;

  for (const [label, md] of markers) {
    it(`round-trips ${label} unchanged`, async () => {
      expect(await roundTrip(md)).toBe(md);
    });
  }

  it("keeps a character mark intact when it sits inside a sentence", async () => {
    const md = "The lighthouse kept <!-- character:id=lore_1 -->Mira<!-- /character --> awake.";
    expect(await roundTrip(md)).toBe(md);
  });
});

// The mutation markers are empty-atom point comments: on load they become an
// empty <span> the editor's node view fills with a pill (so it's non-blank on
// save), but turndown treats a *bare* empty span as blank and drops it — so the
// pure serializer can't md→html→md them in isolation. The real path is
// md → editor → md; here each direction is locked separately.
describe("markdown load — mutation markers parse into editor spans", () => {
  it("parses a single-line mutation marker into a mutation span", async () => {
    const html = await sceneMarkdownToHtml("<!-- mutate:entity=lore_1;field=status;value=dead;id=mut1 -->");
    expect(html).toContain('data-mutation-entity="lore_1"');
    expect(html).toContain('data-mutation-id="mut1"');
    expect(html).toContain("status");
    expect(html).toContain("dead");
  });

  it("parses a multi-line carrier into one span carrying every field row", async () => {
    const html = await sceneMarkdownToHtml(
      [
        "<!-- mutate:entity=lore_1;id=unit1",
        "field=status;value=dead;id=row1",
        "field=mood;op=replace;value=grim;id=row2",
        "-->",
      ].join("\n"),
    );
    expect(html).toContain('data-mutation-id="unit1"');
    expect(html).toContain("row1");
    expect(html).toContain("row2");
    expect(html).toContain("grim");
  });

  it("parses a close marker into a close span", async () => {
    const html = await sceneMarkdownToHtml("<!-- mutate:close;ref=mut1;id=close1 -->");
    expect(html).toContain('data-mutation-close-ref="mut1"');
    expect(html).toContain('data-mutation-id="close1"');
  });

  it("leaves a malformed carrier untouched — never drops a hand-authored line", async () => {
    const bad = "<!-- mutate:entity=lore_1;id=unit1\nfield=status;BROKEN_ROW\n-->";
    const html = await sceneMarkdownToHtml(bad);
    expect(html).not.toContain("data-mutation-entity");
  });
});

describe("markdown save — editor mutation pills serialize back to markers", () => {
  // The spans as the MutationMark / MutationClose node views render them (a
  // non-blank pill), which is what editor.getHTML() hands turndown on save.
  it("serializes a single-row pill to a single-line marker (op=replace omitted)", () => {
    const rows = JSON.stringify([{ id: "mut1", field: "status", op: "replace", value: "dead" }]);
    const html = `<p><span class="mutation-pill" data-mutation-entity="lore_1" data-mutation-rows='${rows}' data-mutation-id="mut1">⤳ dead</span></p>`;
    expect(editorHtmlToSceneMarkdown(html)).toBe("<!-- mutate:entity=lore_1;field=status;value=dead;id=mut1 -->");
  });

  it("keeps a non-default op in the single-line marker", () => {
    const rows = JSON.stringify([{ id: "mut2", field: "aliases", op: "add", value: "Red" }]);
    const html = `<p><span class="mutation-pill" data-mutation-entity="lore_1" data-mutation-rows='${rows}' data-mutation-id="mut2">⤳ +Red</span></p>`;
    expect(editorHtmlToSceneMarkdown(html)).toBe("<!-- mutate:entity=lore_1;field=aliases;op=add;value=Red;id=mut2 -->");
  });

  it("serializes a multi-row pill to the multi-line carrier", () => {
    const rows = JSON.stringify([
      { id: "row1", field: "status", op: "replace", value: "dead" },
      { id: "row2", field: "mood", op: "replace", value: "grim" },
    ]);
    const html = `<p><span class="mutation-pill" data-mutation-entity="lore_1" data-mutation-rows='${rows}' data-mutation-id="unit1">⤳ 2 changes</span></p>`;
    expect(editorHtmlToSceneMarkdown(html)).toBe(
      [
        "<!-- mutate:entity=lore_1;id=unit1",
        "field=status;value=dead;id=row1",
        "field=mood;value=grim;id=row2",
        "-->",
      ].join("\n"),
    );
  });

  it("serializes a close pill to a close marker", () => {
    const html =
      '<p><span class="mutation-pill mutation-pill-close" data-mutation-close-ref="mut1" data-mutation-id="close1">Closes Honor</span></p>';
    expect(editorHtmlToSceneMarkdown(html)).toBe("<!-- mutate:close;ref=mut1;id=close1 -->");
  });
});
