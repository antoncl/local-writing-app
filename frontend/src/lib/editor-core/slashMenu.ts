// Shared types + constants for ProseBodyView's slash-command menu.
// Both the host (which owns the menu state, builds the command list, and
// handles keyboard nav) and the presentational ProseSlashMenu component
// import these.

export const TABLE_GRID_MAX_ROWS = 8;
export const TABLE_GRID_MAX_COLS = 8;

export type SlashMenuState = {
  visible: boolean;
  x: number;
  y: number;
  selectedIndex: number;
  mode: "commands" | "table-grid";
  gridRows: number;
  gridCols: number;
};

export type SlashCommand = {
  label: string;
  description: string;
  group: string;
  autocompleteTo?: string;
  run: (args?: string[]) => void | Promise<void>;
};
