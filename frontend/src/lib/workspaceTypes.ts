// Tiled workspace shell wire types (#32). Extracted from types.ts to keep that
// barrel under the file-size cap; re-exported from `@/lib/types` so it stays
// the single import surface.

// --- Tiled workspace shell (#32) ------------------------------------------
// A PanelId names a piece of content shown as a tab — a fixed region ("lore")
// or an editor document ("editor_1"). The layout is a tree: Split nodes tile
// their children with splitters; TabGroup leaves stack panels as tabs.
// (The former floating-MDI PaneId/PaneState geometry types are gone with the
// paneLayout shim — #157.)

export type PanelId = string;

export type TabGroup = {
  kind: "group";
  id: string;
  tabs: PanelId[];
  active: PanelId | null;
};

export type SplitDir = "row" | "col";

export type Split = {
  kind: "split";
  id: string;
  dir: SplitDir;
  children: LayoutNode[];
  // Flex fractions parallel to `children` (sum ≈ 1).
  sizes: number[];
};

export type LayoutNode = Split | TabGroup;
