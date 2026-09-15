// The Ollama context guide is the first bundled guide to embed inline SVG
// diagrams. GuideView renders guides with a plain `new Marked()` and `{@html}`
// (no sanitiser), so the diagrams only appear if Marked passes the raw <svg>
// through instead of escaping it — this pins that, and the diagram count, so an
// edit that breaks the passthrough (a stray blank line inside an SVG, a Marked
// bump) fails here rather than silently shipping blank figures.
import { describe, expect, it } from "vitest";
import { Marked } from "marked";
import { guides } from "@/lib/generated/guides";

describe("ollama-context guide diagrams", () => {
  it("survives Marked as raw inline SVG, all three diagrams", () => {
    const guide = guides.find((g) => g.id === "ollama-context");
    expect(guide, "ollama-context guide is bundled").toBeDefined();

    const html = new Marked().parse(guide!.markdown) as string;
    expect((html.match(/<svg/g) ?? []).length).toBe(3);
    expect(html).not.toContain("&lt;svg");
  });
});
