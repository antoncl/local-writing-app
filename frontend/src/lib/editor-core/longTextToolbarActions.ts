// The rail's metadata long_text fields get their own floating-toolbar action
// list (#1884 slice 1) — the same mechanism ProseBodyView uses
// (ProseSelectionToolbar + ToolbarAction), but only the formatting subset: no
// Revise (AI), no To-do (both are body-only concerns).
import type { Editor } from "@tiptap/core";
import type { ToolbarAction, ToolbarMenuEntry } from "./selectionToolbar";
import { buildTableMenuAction } from "./tableMenuActions";
import { setColumnAlign } from "./alignedTable";

/** The rail long_text field's floating-toolbar actions (#1884 slice 1): the
 *  formatting subset of the body's menu — no Revise, no To-do. `hasText` = a
 *  non-empty text selection; `inTable` = caret inside a table. */
export function buildLongTextToolbarActions(editor: Editor, hasText: boolean, inTable: boolean): ToolbarAction[] {
  const actions: ToolbarAction[] = [];
  if (hasText) {
    const styleItems: ToolbarMenuEntry[] = [
      { id: "paragraph", label: "Paragraph", run: () => void editor.chain().focus().setParagraph().run() },
      { id: "heading-1", label: "Heading 1", run: () => void editor.chain().focus().toggleHeading({ level: 1 }).run() },
      { id: "heading-2", label: "Heading 2", run: () => void editor.chain().focus().toggleHeading({ level: 2 }).run() },
      { id: "heading-3", label: "Heading 3", run: () => void editor.chain().focus().toggleHeading({ level: 3 }).run() },
      { separator: true, id: "style-sep" },
      { id: "bullet-list", label: "Bullet list", run: () => void editor.chain().focus().toggleBulletList().run() },
      { id: "numbered-list", label: "Numbered list", run: () => void editor.chain().focus().toggleOrderedList().run() },
      { id: "quote", label: "Quote", run: () => void editor.chain().focus().toggleBlockquote().run() },
    ];
    if (!inTable) {
      styleItems.push(
        { separator: true, id: "style-sep-2" },
        {
          id: "insert-table",
          label: "Insert table",
          run: () => void editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
        },
      );
    }
    actions.push(
      { kind: "button", id: "bold", label: "B", run: () => void editor.chain().focus().toggleBold().run() },
      { kind: "button", id: "italic", label: "I", run: () => void editor.chain().focus().toggleItalic().run() },
      { kind: "button", id: "strike", label: "S", run: () => void editor.chain().focus().toggleStrike().run() },
      { kind: "menu", id: "style", label: "Style", items: styleItems },
    );
  }
  if (inTable) actions.push(buildTableMenuAction(editor, (align) => setColumnAlign(editor, align)));
  return actions;
}
