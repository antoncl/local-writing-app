// @vitest-environment happy-dom
// Characterisation test (ADR-0091 §7), written BEFORE `EditorRail` adopts the
// shared `SplitHandle` widget: pins the drag contract — mousedown on the
// resize handle, live width updates as the (document-level, per AGENTS.md)
// mousemove fires, one `setWidth` persistence call on mouseup — so the
// extraction in the next commit can be checked against this test unchanged.
import { describe, expect, it, vi } from "vitest";
import { createRawSnippet } from "svelte";
import { render, fireEvent } from "@/lib/test/component";
import EditorRail from "./EditorRail.svelte";
import { editorRailLayout as layout, RAIL_WIDTH_MAX, RAIL_WIDTH_MIN } from "@/lib/stores/editorRailLayout.svelte";

function content() {
  return createRawSnippet(() => ({ render: () => `<div>details</div>` }));
}

describe("EditorRail — resize drag (characterisation, pre-SplitHandle)", () => {
  it("live-updates layout.width on mousemove after mousedown, clamps, and persists once on mouseup", async () => {
    layout.loadForProject(""); // defaults, no persistence side effects
    layout.side = "right";
    layout.width = 280;
    const setWidth = vi.spyOn(layout, "setWidth");

    render(EditorRail, { label: "Scene details", content: content() });

    const rail = document.querySelector(".editor-rail") as HTMLElement;
    const handle = document.querySelector(".rail-resize") as HTMLElement;
    expect(rail).not.toBeNull();
    expect(handle).not.toBeNull();
    // happy-dom reports a zero rect for every element by default (no layout
    // engine) — stub the rail's right edge so the drag anchor is observable.
    rail.getBoundingClientRect = () =>
      ({ left: 0, right: 700, top: 0, bottom: 0, width: 700, height: 0, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;

    await fireEvent.mouseDown(handle);
    expect(setWidth).not.toHaveBeenCalled();

    await fireEvent.mouseMove(window, { clientX: 400 });
    // anchorEdge (rail's right, 700) - clientX (400) = 300, within bounds.
    expect(layout.width).toBe(300);
    expect(setWidth).not.toHaveBeenCalled(); // not persisted mid-drag

    // Clamp: drag far enough to exceed RAIL_WIDTH_MAX / undershoot RAIL_WIDTH_MIN.
    await fireEvent.mouseMove(window, { clientX: -10_000 });
    expect(layout.width).toBe(RAIL_WIDTH_MAX);

    await fireEvent.mouseMove(window, { clientX: 10_000 });
    expect(layout.width).toBe(RAIL_WIDTH_MIN);

    await fireEvent.mouseUp(window);
    expect(setWidth).toHaveBeenCalledTimes(1);
    expect(setWidth).toHaveBeenCalledWith(RAIL_WIDTH_MIN);

    // A further mousemove after mouseup no longer drives the width.
    await fireEvent.mouseMove(window, { clientX: 0 });
    expect(layout.width).toBe(RAIL_WIDTH_MIN);
  });
});
