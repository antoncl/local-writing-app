// @vitest-environment happy-dom
// The shared per-row Library-shelf affordances (#723), extracted from the
// near-verbatim copies in Prompts.svelte / PlotTemplates.svelte. Pins the three
// states — not-a-Library-row (nothing), shelved (clone + hide), hidden (un-hide)
// — and that the aria-labels the pane tests depend on are preserved.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import LibraryRowActions from "./LibraryRowActions.svelte";
import { openProjectHidden, hideLibraryEntry } from "@/lib/stores/hiddenLibrary";

beforeEach(() => {
  localStorage.clear();
  openProjectHidden("test-project");
});
afterEach(() => {
  openProjectHidden(null);
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("LibraryRowActions", () => {
  it("renders nothing for a non-Library entry (the writer's own / an owned clone)", () => {
    const { container } = render(LibraryRowActions, {
      props: { entry: { id: "x", title: "Mine", is_library: false }, noun: "prompt", onClone: vi.fn() },
    });
    expect(container.querySelector("button")).toBeNull();
  });

  it("offers Clone + Hide on a shelved Library row, and fires onClone with the id", async () => {
    const onClone = vi.fn();
    render(LibraryRowActions, {
      props: { entry: { id: "p1", title: "Alpha", is_library: true }, noun: "prompt", onClone },
    });
    expect(screen.getByLabelText("Hide Alpha from this project")).toBeInTheDocument();
    // The clone tooltip carries the pane's noun; hide/un-hide read the title only.
    const clone = screen.getByLabelText("Clone Alpha into this project");
    expect(clone.getAttribute("title")).toBe("Clone this shipped prompt into an editable copy in this project");
    await fireEvent.click(clone);
    expect(onClone).toHaveBeenCalledWith("p1");
  });

  it("uses the given noun in the clone tooltip (template vs prompt)", () => {
    render(LibraryRowActions, {
      props: { entry: { id: "t1", title: "Three-Act", is_library: true }, noun: "template", onClone: vi.fn() },
    });
    expect(screen.getByLabelText("Clone Three-Act into this project").getAttribute("title")).toBe(
      "Clone this shipped template into an editable copy in this project",
    );
  });

  it("swaps to a single un-hide once the row is hidden", async () => {
    render(LibraryRowActions, {
      props: { entry: { id: "p2", title: "Beta", is_library: true }, noun: "prompt", onClone: vi.fn() },
    });
    hideLibraryEntry("p2");
    await tick();
    // Clone + hide are gone; only the way back remains.
    expect(screen.queryByLabelText("Hide Beta from this project")).toBeNull();
    expect(screen.queryByLabelText("Clone Beta into this project")).toBeNull();
    expect(screen.getByLabelText("Show Beta again")).toBeInTheDocument();
  });
});
