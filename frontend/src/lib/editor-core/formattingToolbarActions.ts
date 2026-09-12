// The floating selection toolbar's formatting core, shared by the prose body
// (ProseBodyView) and the rail's long_text fields (MetadataLongTextEditor,
// #1884 slice 1): the marks (B/I/S), the Style menu — blocks, plus "Insert
// table" when the caret is not in one — and the Table menu when it is. The
// table follows the editor, not the document kind (#1893): a lore entry's
// body and a Backstory field get the same table a scene does. Each host
// composes its list from these parts — the body adds Revise and To-do, which
// are scene concerns — so the formatting subset is spelled once and the two
// menus cannot drift.
import type { Editor } from "@tiptap/core";
import type { ToolbarAction, ToolbarMenuAction, ToolbarMenuEntry } from "./selectionToolbar";
import { buildTableMenuAction } from "./tableMenuActions";
import { setSelectionHeading, wrapSelectionBlock } from "./blockTransforms";

export type FormattingToolbarParts = {
  /** B / I / S — present only with a text selection. */
  marks: ToolbarAction[];
  /** The Style menu — present only with a text selection. */
  style: ToolbarMenuAction | null;
  /** The Table menu — present only with the caret in a table. */
  table: ToolbarMenuAction | null;
};

/** The formatting parts of the floating toolbar. `hasText` = a non-empty text
 *  selection; `inTable` = caret inside a table. */
export function formattingToolbarParts(editor: Editor, hasText: boolean, inTable: boolean): FormattingToolbarParts {
  const table = inTable ? buildTableMenuAction(editor) : null;
  if (!hasText) return { marks: [], style: null, table };

  const styleItems: ToolbarMenuEntry[] = [
    { id: "paragraph", label: "Paragraph", run: () => void editor.chain().focus().setParagraph().run() },
    { id: "heading-1", label: "Heading 1", run: () => setSelectionHeading(editor, 1) },
    { id: "heading-2", label: "Heading 2", run: () => setSelectionHeading(editor, 2) },
    { id: "heading-3", label: "Heading 3", run: () => setSelectionHeading(editor, 3) },
    { separator: true, id: "style-sep" },
    { id: "bullet-list", label: "Bullet list", run: () => wrapSelectionBlock(editor, "bulletList") },
    { id: "numbered-list", label: "Numbered list", run: () => wrapSelectionBlock(editor, "orderedList") },
    { id: "quote", label: "Quote", run: () => wrapSelectionBlock(editor, "blockquote") },
  ];
  if (!inTable) {
    styleItems.push(
      { separator: true, id: "style-sep-2" },
      { id: "insert-table", label: "Insert table", run: () => insertTableAfterSelection(editor) },
    );
  }
  return {
    marks: [
      { kind: "button", id: "bold", label: "B", run: () => void editor.chain().focus().toggleBold().run() },
      { kind: "button", id: "italic", label: "I", run: () => void editor.chain().focus().toggleItalic().run() },
      { kind: "button", id: "strike", label: "S", run: () => void editor.chain().focus().toggleStrike().run() },
    ],
    style: { kind: "menu", id: "style", label: "Style", items: styleItems },
    table,
  };
}

/** The menu only exists over a text selection, and TipTap's `insertTable`
 *  REPLACES the selection — so collapse it to its end first: the table lands
 *  after the selected text, which stays. */
function insertTableAfterSelection(editor: Editor): void {
  editor
    .chain()
    .focus()
    .setTextSelection(editor.state.selection.to)
    .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
    .run();
}

/** The formatting parts as one list — the toolbar of a host with nothing to
 *  add (the rail's long_text field). */
export function formattingToolbarActions(editor: Editor, hasText: boolean, inTable: boolean): ToolbarAction[] {
  const { marks, style, table } = formattingToolbarParts(editor, hasText, inTable);
  return [...marks, ...(style ? [style] : []), ...(table ? [table] : [])];
}
