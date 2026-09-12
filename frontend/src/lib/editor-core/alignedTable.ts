// Table extensions + column alignment shared by the body editor and the
// rail's long_text fields (#1884 slice 1, moved out of ProseBodyView).
//
// AlignedTableCell/AlignedTableHeader add an `align` attribute (serialized as
// `text-align` inline style) on top of the stock TipTap table extensions.
// setColumnAlign applies it to every cell in the caret's column, walking the
// table geometry directly rather than TipTap's single-cell setCellAttribute.
import type { Editor } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import Table from "@tiptap/extension-table";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TableRow from "@tiptap/extension-table-row";

export const AlignedTableCell = TableCell.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      align: {
        default: null,
        parseHTML: (element: HTMLElement) => element.style.textAlign || element.getAttribute("align") || null,
        renderHTML: (attributes: { align?: string | null }) =>
          attributes.align ? { style: `text-align: ${attributes.align}` } : {},
      },
    };
  },
});

export const AlignedTableHeader = TableHeader.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      align: {
        default: null,
        parseHTML: (element: HTMLElement) => element.style.textAlign || element.getAttribute("align") || null,
        renderHTML: (attributes: { align?: string | null }) =>
          attributes.align ? { style: `text-align: ${attributes.align}` } : {},
      },
    };
  },
});

/** Column-wide alignment: every cell in the caret's column gets `align` (falls
 *  back to setCellAttribute when the caret isn't in a cell). */
export function setColumnAlign(editor: Editor, align: "left" | "center" | "right"): void {
  const { state, view } = editor;
  const { $from: fromR } = state.selection;
  let tablePos = -1;
  let tableNode: ProseMirrorNode | null = null;
  let tableDepth = -1;
  for (let d = fromR.depth; d >= 0; d--) {
    const node = fromR.node(d);
    if (node.type.name === "table") {
      tablePos = fromR.before(d);
      tableNode = node;
      tableDepth = d;
      break;
    }
  }
  if (!tableNode || tablePos < 0 || fromR.depth < tableDepth + 2) {
    editor.chain().focus().setCellAttribute("align", align).run();
    return;
  }
  const cellIndex = fromR.index(tableDepth + 1);
  let tr = state.tr;
  let rowPos = tablePos + 1;
  for (let i = 0; i < tableNode.childCount; i++) {
    const row = tableNode.child(i);
    let cellPos = rowPos + 1;
    for (let j = 0; j < row.childCount; j++) {
      const cell = row.child(j);
      if (j === cellIndex) {
        tr = tr.setNodeMarkup(cellPos, null, { ...cell.attrs, align });
        break;
      }
      cellPos += cell.nodeSize;
    }
    rowPos += row.nodeSize;
  }
  view.dispatch(tr);
  editor.commands.focus();
}

/** The table extension set every prose editor installs — spelled once, so the
 *  two hosts cannot drift. Not resizable (#1896): the markdown table carries no
 *  column widths, so a dragged width never survived a reload — an affordance
 *  that lied. */
export const tableExtensions = [Table, TableRow, AlignedTableHeader, AlignedTableCell];
