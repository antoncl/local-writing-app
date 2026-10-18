// Shared types + constants for ProseBodyView's slash-command menu.
// Both the host (which owns the menu state, builds the command list, and
// handles keyboard nav) and the presentational ProseSlashMenu component
// import these.

export const TABLE_GRID_MAX_ROWS = 8;
export const TABLE_GRID_MAX_COLS = 8;
/** Rows a PageUp/PageDown moves the slash-menu highlight (#2454). */
export const SLASH_PAGE_STEP = 5;

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
  /** Longer text for the menu's hint line in place of `description` — e.g. a
   *  prompt's one-line summary (#2546). Display only: the filter never matches
   *  it, so a sentence of prose doesn't make every word a command prefix. */
  hint?: string;
  autocompleteTo?: string;
  /** A scene verb (scene break, mutate, the cursor prompts — roleplay only
   *  makes sense in a scene): offered in a manuscript body only. Unscoped
   *  commands (e.g. Table) belong to every prose body (#1893). */
  scope?: "manuscript";
  run: (args?: string[]) => void | Promise<void>;
};

/** Where a PageUp/PageDown/Home/End press moves the slash-menu highlight —
 *  clamped, never wrapping — or `null` when the key isn't a jump. A modified
 *  press (Shift+Home extends a selection, Ctrl+End jumps the doc) stays the
 *  editor's (#2454). */
export function slashJumpIndex(
  event: Pick<KeyboardEvent, "key" | "shiftKey" | "ctrlKey" | "metaKey" | "altKey">,
  index: number,
  count: number,
): number | null {
  if (count <= 0 || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return null;
  const jump = { PageDown: SLASH_PAGE_STEP, PageUp: -SLASH_PAGE_STEP, Home: -count, End: count }[event.key];
  if (jump === undefined) return null;
  return Math.min(count - 1, Math.max(0, index + jump));
}

/** The commands a body of `kind` offers: every unscoped command, plus the
 *  scene verbs when the body is a scene. */
export function slashCommandsForKind<T extends { scope?: "manuscript" }>(commands: T[], kind: string): T[] {
  return commands.filter((command) => command.scope === undefined || command.scope === kind);
}
