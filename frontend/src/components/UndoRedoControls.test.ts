// @vitest-environment happy-dom
// UndoRedoControls RENDER + wiring guard (ADR-0050 §7). The visible control is
// the a11y story a bare keybinding can't tell, so its named/disabled/announce
// behaviour is asserted on a real mount ([[reference_component_test_harness]]).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import UndoRedoControls from "./UndoRedoControls.svelte";

const props = (over: Record<string, unknown> = {}) => ({
  canUndo: false,
  canRedo: false,
  undoTitle: "Undo",
  redoTitle: "Redo",
  announcement: "",
  onUndo: vi.fn(),
  onRedo: vi.fn(),
  ...over,
});

describe("UndoRedoControls", () => {
  it("renders named undo/redo buttons", () => {
    render(UndoRedoControls, { props: props() });
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Redo" })).toBeInTheDocument();
  });

  it("disables each button when its direction is unavailable", () => {
    render(UndoRedoControls, { props: props({ canUndo: false, canRedo: true }) });
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Redo" })).toBeEnabled();
  });

  it("invokes the handlers on click", async () => {
    const onUndo = vi.fn();
    const onRedo = vi.fn();
    render(UndoRedoControls, { props: props({ canUndo: true, canRedo: true, onUndo, onRedo }) });
    await fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    expect(onUndo).toHaveBeenCalledOnce();
    expect(onRedo).toHaveBeenCalledOnce();
  });

  it("announces what just reversed in a live region", () => {
    render(UndoRedoControls, { props: props({ announcement: "Undid move node" }) });
    expect(screen.getByText("Undid move node")).toBeInTheDocument();
  });

  it("applies the peek titles as button tooltips", () => {
    render(UndoRedoControls, { props: props({ undoTitle: "Undo move node", redoTitle: "Redo move node" }) });
    expect(screen.getByRole("button", { name: "Undo" })).toHaveAttribute("title", "Undo move node");
    expect(screen.getByRole("button", { name: "Redo" })).toHaveAttribute("title", "Redo move node");
  });
});
