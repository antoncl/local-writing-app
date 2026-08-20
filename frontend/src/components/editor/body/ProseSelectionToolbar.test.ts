// @vitest-environment happy-dom
// ProseSelectionToolbar is the single floating prose menu (#1223). These lock
// the render contract the host relies on: buttons and one-level dropdowns from a
// text selection, the Table menu's nested submenus in a table, the danger
// styling for destructive commands, and the word-count that hides when zero.
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ProseSelectionToolbar from "./ProseSelectionToolbar.svelte";
import type { FloatingMenuState, ToolbarAction } from "@/lib/editor-core/selectionToolbar";

const menu = (over: Partial<FloatingMenuState> = {}): FloatingMenuState => ({
  visible: true,
  x: 100,
  y: 100,
  wordCount: 3,
  placement: "above",
  ...over,
});

const formatting: ToolbarAction[] = [
  { kind: "button", id: "bold", label: "B", run: vi.fn() },
  {
    kind: "menu",
    id: "style",
    label: "Style",
    items: [
      { id: "paragraph", label: "Paragraph", run: vi.fn() },
      { separator: true, id: "style-sep" },
      { id: "quote", label: "Quote", run: vi.fn() },
    ],
  },
];

const tableAction: ToolbarAction = {
  kind: "menu",
  id: "table",
  label: "Table",
  items: [
    {
      id: "table-row",
      label: "Row",
      items: [
        { id: "row-above", label: "Insert above", run: vi.fn() },
        { id: "row-delete", label: "Delete row", danger: true, run: vi.fn() },
      ],
    },
    { separator: true, id: "table-sep" },
    { id: "table-delete", label: "Delete table", danger: true, run: vi.fn() },
  ],
};

describe("ProseSelectionToolbar (#1223)", () => {
  it("renders nothing when the menu is hidden", () => {
    render(ProseSelectionToolbar, {
      props: { menu: menu({ visible: false }), actions: formatting, openMenuId: null, onRun: vi.fn(), onToggleMenu: vi.fn() },
    });
    expect(screen.queryByText("B")).not.toBeInTheDocument();
  });

  it("shows the word count, and hides it when zero (empty-selection, in-table)", () => {
    const { unmount } = render(ProseSelectionToolbar, {
      props: { menu: menu({ wordCount: 3 }), actions: formatting, openMenuId: null, onRun: vi.fn(), onToggleMenu: vi.fn() },
    });
    expect(screen.getByText("3 words")).toBeInTheDocument();
    unmount();
    render(ProseSelectionToolbar, {
      props: { menu: menu({ wordCount: 0 }), actions: [tableAction], openMenuId: null, onRun: vi.fn(), onToggleMenu: vi.fn() },
    });
    expect(screen.queryByText(/words?$/)).not.toBeInTheDocument();
  });

  it("a top-level button runs via onRun; a menu button toggles via onToggleMenu", async () => {
    const onRun = vi.fn();
    const onToggleMenu = vi.fn();
    render(ProseSelectionToolbar, {
      props: { menu: menu(), actions: formatting, openMenuId: null, onRun, onToggleMenu },
    });
    await fireEvent.mouseDown(screen.getByText("B"));
    expect(onRun).toHaveBeenCalledOnce();
    await fireEvent.mouseDown(screen.getByText("Style"));
    expect(onToggleMenu).toHaveBeenCalledWith("style");
  });

  it("an open dropdown renders its leaves and separators; a leaf calls onRun", async () => {
    const onRun = vi.fn();
    render(ProseSelectionToolbar, {
      props: { menu: menu(), actions: formatting, openMenuId: "style", onRun, onToggleMenu: vi.fn() },
    });
    expect(screen.getByText("Paragraph")).toBeInTheDocument();
    expect(screen.getByText("Quote")).toBeInTheDocument();
    // A leaf-only dropdown keeps scroll (no `has-submenus`), so a tall menu caps + scrolls.
    expect(screen.getByText("Paragraph").closest(".toolbar-menu-popover")).not.toHaveClass("has-submenus");
    await fireEvent.mouseDown(screen.getByText("Quote"));
    expect(onRun).toHaveBeenCalledOnce();
  });

  it("the Table menu opens submenus on hover, and a submenu leaf fires through onRun", async () => {
    const onRun = vi.fn();
    render(ProseSelectionToolbar, {
      props: { menu: menu({ wordCount: 0 }), actions: [tableAction], openMenuId: "table", onRun, onToggleMenu: vi.fn() },
    });
    // The Row/Delete-table groups show; the submenu's leaves are hidden until hover.
    expect(screen.getByText("Row")).toBeInTheDocument();
    expect(screen.getByText("Delete table")).toBeInTheDocument();
    expect(screen.queryByText("Insert above")).not.toBeInTheDocument();

    // A submenu-hosting dropdown opts out of scroll (overflow:auto would sprout a
    // scrollbar when a submenu flies out sideways) via `has-submenus`.
    expect(screen.getByText("Row").closest(".toolbar-menu-popover")).toHaveClass("has-submenus");

    await fireEvent.mouseEnter(screen.getByText("Row"));
    expect(screen.getByText("Insert above")).toBeInTheDocument();
    await fireEvent.mouseDown(screen.getByText("Insert above"));
    expect(onRun).toHaveBeenCalledOnce();
  });
});
