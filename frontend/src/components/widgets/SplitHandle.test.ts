// @vitest-environment happy-dom
// SplitHandle (ADR-0091 §7) — the shared pane-divider gesture: global
// mousemove/mouseup added on drag start and removed on end (AGENTS.md), the
// separator role/orientation, and the host-supplied callbacks doing the
// actual work (this widget carries no size state of its own).
import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@/lib/test/component";
import SplitHandle from "./SplitHandle.svelte";

describe("SplitHandle", () => {
  it("renders a separator with the given orientation and label", () => {
    render(SplitHandle, {
      orientation: "vertical",
      label: "Resize the candidate list",
      onDragStart: () => {},
      onDrag: () => {},
      onDragEnd: () => {},
    });
    const handle = document.querySelector('[role="separator"]') as HTMLElement;
    expect(handle).not.toBeNull();
    expect(handle.getAttribute("aria-orientation")).toBe("vertical");
    expect(handle.getAttribute("aria-label")).toBe("Resize the candidate list");
  });

  it("calls onDragStart on mousedown, onDrag on a document mousemove, onDragEnd on mouseup", async () => {
    const onDragStart = vi.fn();
    const onDrag = vi.fn();
    const onDragEnd = vi.fn();
    render(SplitHandle, { orientation: "vertical", label: "Resize", onDragStart, onDrag, onDragEnd });
    const handle = document.querySelector('[role="separator"]') as HTMLElement;

    await fireEvent.mouseDown(handle, { clientX: 100 });
    expect(onDragStart).toHaveBeenCalledTimes(1);
    expect(onDrag).not.toHaveBeenCalled();

    await fireEvent.mouseMove(window, { clientX: 80 });
    await fireEvent.mouseMove(window, { clientX: 60 });
    expect(onDrag).toHaveBeenCalledTimes(2);

    await fireEvent.mouseUp(window);
    expect(onDragEnd).toHaveBeenCalledTimes(1);

    // The listeners are torn down on mouseup — a further move drives nothing.
    await fireEvent.mouseMove(window, { clientX: 10 });
    expect(onDrag).toHaveBeenCalledTimes(2);
  });

  it("passes a host class through alongside its own", () => {
    render(SplitHandle, {
      orientation: "horizontal",
      label: "Resize",
      onDragStart: () => {},
      onDrag: () => {},
      onDragEnd: () => {},
      class: "rail-resize",
    });
    const handle = document.querySelector('[role="separator"]') as HTMLElement;
    expect(handle.className).toContain("rail-resize");
    expect(handle.className).toContain("split-handle");
    expect(handle.className).toContain("horizontal");
  });
});
