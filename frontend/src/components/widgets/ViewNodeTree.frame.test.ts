// @vitest-environment happy-dom
// ADR-0066 Amendment 2 (#1191): `frameParents` wraps a real-node parent's
// children in the shared `.node-row-group-children` tier panel, so a container
// node (a Lore Nest) reads as HOLDING its members instead of sitting above flat
// siblings. Opt-in — off, the children render flat. Pins the ViewNodeTree
// branch the CSS can't assert.
import { describe, expect, it } from "vitest";
import { tick } from "svelte";
import { render } from "@/lib/test/component";
import Fixture from "./ViewNodeTreeFrameFixture.svelte";

describe("ViewNodeTree — frameParents (ADR-0066 Amendment 2)", () => {
  it("frames a real-node parent's children in the tier panel, child nested inside", async () => {
    const { container } = render(Fixture, { props: { frameParents: true } });
    await tick();
    const panel = container.querySelector(".node-row-group-children");
    expect(panel).not.toBeNull();
    // The child renders INSIDE the panel — contained, not a flat sibling.
    expect(panel?.querySelector('[data-node-id="c1"]')).not.toBeNull();
    // The parent header itself sits OUTSIDE the panel (above it).
    expect(panel?.querySelector('[data-node-id="p1"]')).toBeNull();
  });

  it("without frameParents the children stay flat — no panel", async () => {
    const { container } = render(Fixture, { props: { frameParents: false } });
    await tick();
    expect(container.querySelector(".node-row-group-children")).toBeNull();
    // The child still renders (unframed), so the flag is presentation-only.
    expect(container.querySelector('[data-node-id="c1"]')).not.toBeNull();
  });
});
