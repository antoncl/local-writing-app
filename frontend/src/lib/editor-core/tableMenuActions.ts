// The "Table" entry of the unified selection menu (#1223). Replaces the old
// twelve-button ProseTableToolbar: the same TipTap commands, regrouped into
// Row / Column / Align / Header submenus plus a destructive "Delete table".
//
// Alignment is column-wide (setColumnAlign walks the table geometry), so its
// leaves call alignedTable rather than a plain chain command.
import type { Editor } from "@tiptap/core";
import type { ToolbarMenuAction } from "./selectionToolbar";
import { setColumnAlign } from "./alignedTable";

export function buildTableMenuAction(editor: Editor): ToolbarMenuAction {
  const run = (fn: (chain: ReturnType<Editor["chain"]>) => ReturnType<Editor["chain"]>) => () =>
    void fn(editor.chain().focus()).run();
  return {
    kind: "menu",
    id: "table",
    label: "Table",
    items: [
      {
        id: "table-row",
        label: "Row",
        items: [
          { id: "row-above", label: "Insert above", run: run((c) => c.addRowBefore()) },
          { id: "row-below", label: "Insert below", run: run((c) => c.addRowAfter()) },
          { separator: true, id: "row-sep" },
          { id: "row-delete", label: "Delete row", danger: true, run: run((c) => c.deleteRow()) },
        ],
      },
      {
        id: "table-column",
        label: "Column",
        items: [
          { id: "col-left", label: "Insert left", run: run((c) => c.addColumnBefore()) },
          { id: "col-right", label: "Insert right", run: run((c) => c.addColumnAfter()) },
          { separator: true, id: "col-sep" },
          { id: "col-delete", label: "Delete column", danger: true, run: run((c) => c.deleteColumn()) },
        ],
      },
      {
        id: "table-align",
        label: "Align",
        items: [
          { id: "align-left", label: "Left", run: () => setColumnAlign(editor, "left") },
          { id: "align-center", label: "Center", run: () => setColumnAlign(editor, "center") },
          { id: "align-right", label: "Right", run: () => setColumnAlign(editor, "right") },
        ],
      },
      {
        id: "table-header",
        label: "Header",
        items: [
          { id: "header-row", label: "Header row", run: run((c) => c.toggleHeaderRow()) },
          { id: "header-column", label: "Header column", run: run((c) => c.toggleHeaderColumn()) },
        ],
      },
      { separator: true, id: "table-sep" },
      { id: "table-delete", label: "Delete table", danger: true, run: run((c) => c.deleteTable()) },
    ],
  };
}
