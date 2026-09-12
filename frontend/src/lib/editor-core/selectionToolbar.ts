// Shared types for ProseBodyView's floating selection toolbar.
//
// One menu, keyed to context (#1223): the host builds the action list — the
// formatting commands + the AI "Revise" menu + a "Style" block menu + "To-do",
// and (only when the caret is in a table) a "Table" menu whose commands live in
// grouped submenus. The presentational ProseSelectionToolbar renders buttons,
// one-level dropdowns, and the Table menu's nested submenus from these types.

export type EdgeRect = { top: number; bottom: number; left: number; right: number };

/** Where the floating toolbar goes for a selection anchored at `anchor`, inside
 *  a frame with viewport bounds `frame` (and inner width `frameWidth`), on a
 *  viewport of `viewport`. Pure — no DOM. Same numbers the body has used since #1223. */
export function placeSelectionToolbar(
  anchor: EdgeRect,
  frame: EdgeRect,
  frameWidth: number,
  viewport: { width: number; height: number },
  { toolbarHeight = 42, margin = 10 }: { toolbarHeight?: number; margin?: number } = {},
): { x: number; y: number; placement: "above" | "below" } {
  const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);
  const visibleTop = Math.max(frame.top, 0) + margin;
  const visibleBottom = Math.min(frame.bottom, viewport.height) - margin;
  const anchorTop = anchor.top;
  const anchorBottom = anchor.bottom;
  const hasRoomAbove = anchorTop - toolbarHeight - margin >= visibleTop;
  const placement = hasRoomAbove ? "above" : "below";
  const preferredY = placement === "above" ? anchorTop - margin : anchorBottom + margin;
  const minY = placement === "above" ? visibleTop + toolbarHeight : visibleTop;
  const maxY = placement === "above" ? visibleBottom : visibleBottom - toolbarHeight;
  const toolbarHalfWidth = Math.min(360, Math.max(140, frameWidth / 2 - margin));
  const unclampedX = (anchor.left + anchor.right) / 2;
  const minX = Math.max(frame.left, 0) + toolbarHalfWidth;
  const maxX = Math.min(frame.right, viewport.width) - toolbarHalfWidth;
  return {
    x:
      minX <= maxX
        ? clamp(unclampedX, minX, maxX)
        : (Math.max(frame.left, 0) + Math.min(frame.right, viewport.width)) / 2,
    y: clamp(preferredY, minY, maxY),
    placement,
  };
}

export type FloatingMenuState = {
  visible: boolean;
  x: number;
  y: number;
  wordCount: number;
  placement: "above" | "below";
};

export type ToolbarButtonAction = {
  kind: "button";
  id: string;
  label: string;
  run: () => void | Promise<void>;
  /** Destructive action (e.g. Delete table) — rendered in the danger colour. */
  danger?: boolean;
};

// Entries inside a dropdown popover. A leaf runs a command; a submenu opens a
// side-flyout of its own entries (used only by the Table menu's Row/Column/…
// groups); a separator draws a divider. Discriminate with `"separator" in e`
// (separator) then `"items" in e` (submenu), else a leaf.
export type ToolbarMenuLeaf = {
  id: string;
  label: string;
  run: () => void | Promise<void>;
  danger?: boolean;
};

export type ToolbarSubmenu = {
  id: string;
  label: string;
  items: ToolbarMenuEntry[];
};

export type ToolbarSeparator = { separator: true; id: string };

export type ToolbarMenuEntry = ToolbarMenuLeaf | ToolbarSubmenu | ToolbarSeparator;

export type ToolbarMenuAction = {
  kind: "menu";
  id: string;
  label: string;
  items: ToolbarMenuEntry[];
};

export type ToolbarAction = ToolbarButtonAction | ToolbarMenuAction;

export function isToolbarSeparator(e: ToolbarMenuEntry): e is ToolbarSeparator {
  return "separator" in e;
}

export function isToolbarSubmenu(e: ToolbarMenuEntry): e is ToolbarSubmenu {
  return "items" in e;
}

// Decide which way a dropdown should open and how tall it may be before it must
// scroll, so it never clips off-screen (#1227). Given the anchor's top/bottom
// viewport edges (a trigger button, or a submenu's parent row) and the viewport
// height, it prefers opening DOWNWARD — the conventional direction — and flips
// up only when down genuinely lacks room and up has more. `maxHeight` is the
// space on the chosen side (floored so the menu stays usable and scrolls rather
// than clips). Pure, so it's unit-tested without layout.
export function verticalDropFit(
  anchorTop: number,
  anchorBottom: number,
  viewportHeight: number,
  { margin = 10, typical = 300, minHeight = 120 }: { margin?: number; typical?: number; minHeight?: number } = {},
): { up: boolean; maxHeight: number } {
  const below = viewportHeight - anchorBottom - margin;
  const above = anchorTop - margin;
  const up = below < typical && above > below;
  return { up, maxHeight: Math.max(minHeight, Math.round(up ? above : below)) };
}
