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

describe("ollama-context guide diagrams", () => {
  it("bundle inlines the three SVGs and Marked passes them through raw", () => {
    const guide = guides.find((g) => g.id === "ollama-context");
    expect(guide, "ollama-context guide is bundled").toBeDefined();

    // The bundle carries raw inline <svg>, not `![](*.svg)` image refs.
    expect((guide!.markdown.match(/<svg/g) ?? []).length).toBe(3);
    expect(guide!.markdown).not.toMatch(/!\[[^\]]*\]\([^)]*\.svg\)/);

    const html = new Marked().parse(guide!.markdown) as string;
    expect((html.match(/<svg/g) ?? []).length).toBe(3);
    expect(html).not.toContain("&lt;svg");
    expect(html).not.toContain("<img");
  });
});
