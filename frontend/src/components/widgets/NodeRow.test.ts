// @vitest-environment happy-dom
import { describe, it, expect } from "vitest";
import { render } from "@/lib/test/component";
import NodeRow from "@/components/widgets/NodeRow.svelte";

// The tag pills carry their tag's colour when the caller passes a `tagColor`
// resolver, and stay neutral otherwise (#1447). Colour arrives as inline
// `--tag-*` custom props the .node-row-tag CSS reads; a neutral tag sets none.
const REAL_PILL = ".node-row-tag:not(.node-row-tag-probe):not(.node-row-tag-overflow)";

describe("NodeRow tags", () => {
  it("applies the tag's colour to its pill via tagColor", () => {
    const { container } = render(NodeRow, {
      props: {
        title: "Mara",
        tags: ["special", "plain"],
        tagColor: (t: string) => (t === "special" ? "#5b5ca8" : null),
      },
    });
    const pills = [...container.querySelectorAll(REAL_PILL)];
    const special = pills.find((p) => p.textContent === "special");
    const plain = pills.find((p) => p.textContent === "plain");
    expect(special?.getAttribute("style") ?? "").toContain("--tag-text: #5b5ca8");
    // A colourless tag gets no inline vars — it falls back to the neutral chip.
    expect(plain?.getAttribute("style") ?? "").toBe("");
  });

  it("leaves every pill neutral when no tagColor is passed", () => {
    const { container } = render(NodeRow, { props: { title: "Mara", tags: ["a", "b"] } });
    for (const p of container.querySelectorAll(REAL_PILL)) {
      expect(p.getAttribute("style") ?? "").toBe("");
    }
  });

  // The compact-density layout hangs off `.node-row-text.has-tags`: only a row
  // that actually has tags hands its tag column the flexible (measurable) grid
  // track, so a detail-only compact row is left alone (#1450).
  it("marks the text area .has-tags only when the row has tags", () => {
    const withTags = render(NodeRow, { props: { title: "Mara", tags: ["a"] } });
    expect(withTags.container.querySelector(".node-row-text.has-tags")).not.toBeNull();

    const noTags = render(NodeRow, { props: { title: "Mara" } });
    expect(noTags.container.querySelector(".node-row-text")).not.toBeNull();
    expect(noTags.container.querySelector(".node-row-text.has-tags")).toBeNull();
  });
});

// #316: an entry-type icon renders as a quiet leading glyph before the title,
// and only when the caller passes one (opt-in per type — rows without a typed
// icon are visually unchanged).
describe("NodeRow type icon (#316)", () => {
  it("renders the leading type-icon glyph when typeIcon is set", () => {
    const { container } = render(NodeRow, {
      props: { title: "Alice", typeIcon: "ti ti-user" },
    });
    const icon = container.querySelector(".node-row-type-icon i");
    expect(icon).not.toBeNull();
    expect(icon?.className).toContain("ti-user");
    // It leads the title (precedes the clickable label in DOM order).
    const glyph = container.querySelector(".node-row-type-icon");
    const label = container.querySelector(".node-row-click, .node-row-text");
    expect(glyph && label && !!(glyph.compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
  });

  it("renders no glyph when typeIcon is absent (unchanged rows)", () => {
    const { container } = render(NodeRow, { props: { title: "Alice" } });
    expect(container.querySelector(".node-row-type-icon")).toBeNull();
  });
});
