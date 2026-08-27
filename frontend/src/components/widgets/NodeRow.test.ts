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
});
