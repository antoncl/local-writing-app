// @vitest-environment happy-dom
// The shared in-pane popover primitive (#1573): portal the popover to <body>
// and pin it at viewport coords off its trigger, so a pane's `overflow` box
// can't clip it. Positioning maths are layout-driven (happy-dom reports zero
// rects), so these assert the structural contract — reparent, fixed position,
// clean teardown — which is what makes the popover escape the clip.
import { describe, expect, it } from "vitest";
import { anchoredPopover } from "./anchoredPopover";

describe("anchoredPopover", () => {
  it("portals the node to <body> and pins it fixed", () => {
    const anchor = document.createElement("button");
    const host = document.createElement("div");
    const pop = document.createElement("div");
    host.appendChild(pop); // starts nested under a would-be clipping container
    document.body.appendChild(anchor);
    document.body.appendChild(host);

    const handle = anchoredPopover(pop, { anchor });

    // Lifted out of its nesting container, straight under <body>.
    expect(pop.parentElement).toBe(document.body);
    // Fixed positioning is what resolves it against the viewport, not the
    // (clipped/transformed) pane — the action owns this, not the CSS.
    expect(pop.style.position).toBe("fixed");
    expect(pop.style.left).not.toBe("");
    expect(pop.style.top).not.toBe("");

    handle.destroy();
    expect(pop.isConnected).toBe(false);
  });

  it("no-ops positioning when the anchor is missing but still mounts", () => {
    const pop = document.createElement("div");
    document.body.appendChild(pop);
    const handle = anchoredPopover(pop, { anchor: null });
    expect(pop.parentElement).toBe(document.body);
    expect(pop.style.position).toBe("fixed");
    handle.destroy();
    expect(pop.isConnected).toBe(false);
  });
});
