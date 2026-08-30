// @vitest-environment happy-dom
// #1697: ViewNodeTree stamps `RowCtx.levelHasCollapsible` (does this recursion
// level hold a collapsible node?), which the Lore pane feeds to RowCaret's
// `reserveGutter`. A flat leaf-only level reclaims the caret gutter; a level with
// a collapsible sibling keeps it so the leaf's title stays aligned (ADR-0066 A1).
import { describe, expect, it } from "vitest";
import { tick } from "svelte";
import { render } from "@/lib/test/component";
import Fixture from "./ViewNodeTreeCaretFixture.svelte";

describe("ViewNodeTree — leaf caret gutter (#1697)", () => {
  it("a flat leaf-only level reclaims the gutter (no caret, no gutter)", async () => {
    const { container } = render(Fixture, { props: { mixed: false } });
    await tick();
    expect(container.querySelectorAll(".row-caret-gutter").length).toBe(0);
    expect(container.querySelectorAll(".row-caret").length).toBe(0);
  });

  it("a leaf sharing a level with a collapsible sibling reserves the gutter", async () => {
    const { container } = render(Fixture, { props: { mixed: true } });
    await tick();
    // The collapsible parent renders a real caret button.
    expect(container.querySelectorAll(".row-caret").length).toBe(1);
    // The top-level leaf keeps its gutter (aligns under the parent's caret)...
    expect(container.querySelector('[data-node-id="b"] .row-caret-gutter')).not.toBeNull();
    // ...while the parent's own child, alone at its level, reclaims it.
    expect(container.querySelector('[data-node-id="k"] .row-caret-gutter')).toBeNull();
  });
});
