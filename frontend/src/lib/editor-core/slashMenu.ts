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
  /** A scene verb (scene break, mutate, the cursor prompts — roleplay only
   *  makes sense in a scene): offered in a manuscript body only. Unscoped
   *  commands are formatting and belong to every prose body (#1893). */
  scope?: "manuscript";
  run: (args?: string[]) => void | Promise<void>;
};

/** The commands a body of `kind` offers: every unscoped command, plus the
 *  scene verbs when the body is a scene. */
export function slashCommandsForKind<T extends { scope?: "manuscript" }>(commands: T[], kind: string): T[] {
  return commands.filter((command) => command.scope === undefined || command.scope === kind);
}
