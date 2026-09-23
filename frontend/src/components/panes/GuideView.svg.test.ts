// The Ollama context guide's diagrams live as committed .svg files under
// docs/ollama-context/ so GitHub renders them as images. The in-app viewer can't
// load images (the bundle copies no assets), so scripts/gen_guides.py inlines
// each `![](*.svg)` ref into the bundled markdown as raw <svg>. GuideView renders
// guides with a plain `new Marked()` and {@html} (no sanitiser), so the diagrams
// only appear if that inlined <svg> survives Marked instead of being escaped.
// This pins both halves: the bundle inlined the SVGs (three of them, no leftover
// `![](*.svg)` refs) and Marked passes the raw SVG through — so a broken ref, a
// stray blank line inside an SVG, or a Marked bump fails here rather than
// silently shipping blank figures.
import { describe, expect, it } from "vitest";
import { Marked } from "marked";
import { guides } from "@/lib/generated/guides";

// Every guide that ships diagrams, with how many it inlines. Adding a diagram to
// a guide (or a new diagram-bearing guide, #2148) means adding it here.
const DIAGRAM_GUIDES: Array<[id: string, count: number]> = [
  ["ollama-context", 3],
  ["ai-context", 4],
];

describe.each(DIAGRAM_GUIDES)("%s guide diagrams", (id, count) => {
  it(`bundle inlines the ${count} SVGs and Marked passes them through raw`, () => {
    const guide = guides.find((g) => g.id === id);
    expect(guide, `${id} guide is bundled`).toBeDefined();

    // The bundle carries raw inline <svg>, not `![](*.svg)` image refs.
    expect((guide!.markdown.match(/<svg/g) ?? []).length).toBe(count);
    expect(guide!.markdown).not.toMatch(/!\[[^\]]*\]\([^)]*\.svg\)/);

    const html = new Marked().parse(guide!.markdown) as string;
    expect((html.match(/<svg/g) ?? []).length).toBe(count);
    expect(html).not.toContain("&lt;svg");
    expect(html).not.toContain("<img");
  });
});
