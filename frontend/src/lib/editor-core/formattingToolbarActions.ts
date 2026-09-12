// The floating selection toolbar's formatting core, shared by the prose body
// (ProseBodyView) and the rail's long_text fields (MetadataLongTextEditor,
// #1884 slice 1): the marks (B/I/S), the Style menu — blocks, plus "Insert
// table" when the caret is not in one — and the Table menu when it is. The
// table capability follows the editor, not the document kind (#1893): a lore
// entry's body and a Backstory field get the same table a scene does. Each
// host composes its own list from these parts — the body adds Revise and
// To-do, which are body-only concerns — so the formatting subset is spelled
// once and the two menus cannot drift.
import type { Editor } from "@tiptap/core";
import type { ToolbarAction, ToolbarMenuEntry } from "./selectionToolbar";
import { buildTableMenuAction } from "./tableMenuActions";
import { setColumnAlign } from "./alignedTable";

export type HeadingLevel = 1 | 2 | 3;
export type BlockWrapType = "blockquote" | "bulletList" | "orderedList";

/** How a host applies the Style menu's block transforms. The defaults are
 *  TipTap's own toggles on the whole textblock; the body overrides both to
 *  extract a partial selection into its own block first. */
export type BlockTransforms = {
  setHeading?: (level: HeadingLevel) => void;
  wrapBlock?: (type: BlockWrapType) => void;
};

export type FormattingToolbarParts = {
  /** B / I / S — present only with a text selection. */
  marks: ToolbarAction[];
  /** The Style menu — present only with a text selection. */
  style: ToolbarAction | null;
  /** The Table menu — present only with the caret in a table. */
  table: ToolbarAction | null;
};

function defaultTransforms(editor: Editor): Required<BlockTransforms> {
  return {
    setHeading: (level) => void editor.chain().focus().toggleHeading({ level }).run(),
    wrapBlock: (type) => {
      if (type === "blockquote") void editor.chain().focus().toggleBlockquote().run();
      else if (type === "bulletList") void editor.chain().focus().toggleBulletList().run();
      else void editor.chain().focus().toggleOrderedList().run();
    },
  };
}

/** The formatting parts of the floating toolbar. `hasText` = a non-empty text
 *  selection; `inTable` = caret inside a table. */
export function formattingToolbarParts(
  editor: Editor,
  hasText: boolean,
  inTable: boolean,
  transforms: BlockTransforms = {},
): FormattingToolbarParts {
  const { setHeading, wrapBlock } = { ...defaultTransforms(editor), ...transforms };
  let marks: ToolbarAction[] = [];
  let style: ToolbarAction | null = null;
  if (hasText) {
    const styleItems: ToolbarMenuEntry[] = [
      { id: "paragraph", label: "Paragraph", run: () => void editor.chain().focus().setParagraph().run() },
      { id: "heading-1", label: "Heading 1", run: () => setHeading(1) },
      { id: "heading-2", label: "Heading 2", run: () => setHeading(2) },
      { id: "heading-3", label: "Heading 3", run: () => setHeading(3) },
      { separator: true, id: "style-sep" },
      { id: "bullet-list", label: "Bullet list", run: () => wrapBlock("bulletList") },
      { id: "numbered-list", label: "Numbered list", run: () => wrapBlock("orderedList") },
      { id: "quote", label: "Quote", run: () => wrapBlock("blockquote") },
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
    marks = [
      { kind: "button", id: "bold", label: "B", run: () => void editor.chain().focus().toggleBold().run() },
      { kind: "button", id: "italic", label: "I", run: () => void editor.chain().focus().toggleItalic().run() },
      { kind: "button", id: "strike", label: "S", run: () => void editor.chain().focus().toggleStrike().run() },
    ];
    style = { kind: "menu", id: "style", label: "Style", items: styleItems };
  }
  const table = inTable ? buildTableMenuAction(editor, (align) => setColumnAlign(editor, align)) : null;
  return { marks, style, table };
}

/** The rail long_text field's floating-toolbar actions (#1884 slice 1): the
 *  formatting parts and nothing else — no Revise, no To-do. */
export function buildLongTextToolbarActions(editor: Editor, hasText: boolean, inTable: boolean): ToolbarAction[] {
  const { marks, style, table } = formattingToolbarParts(editor, hasText, inTable);
  return [...marks, ...(style ? [style] : []), ...(table ? [table] : [])];
}
