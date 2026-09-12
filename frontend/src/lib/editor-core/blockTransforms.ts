// The Style menu's block transforms, one implementation for every prose
// editor (#1893): a heading or a wrap (list, quote) applied to the selection.
// A selection covering part of one paragraph is extracted into its own block —
// the text before and after stay paragraphs — so "make this sentence a
// heading" does not swallow the paragraph around it. A whole-block or
// multi-block selection falls through to TipTap's own command. Headings are
// SET, not toggled: the menu's "Paragraph" entry is the way back.
import type { Editor } from "@tiptap/core";
import type { Fragment, Node as ProseMirrorNode } from "@tiptap/pm/model";

export type HeadingLevel = 1 | 2 | 3;
export type BlockWrapType = "blockquote" | "bulletList" | "orderedList";

export function setSelectionHeading(editor: Editor, level: HeadingLevel): void {
  const headingType = editor.state.schema.nodes.heading;
  const extracted =
    headingType !== undefined &&
    extractPartialTextSelection(editor, (content) => headingType.create({ level }, content));
  if (!extracted) editor.chain().focus().setHeading({ level }).run();
}

export function wrapSelectionBlock(editor: Editor, type: BlockWrapType): void {
  if (extractSelectionToBlockWrap(editor, type)) return;
  if (type === "blockquote") editor.chain().focus().toggleBlockquote().run();
  else if (type === "bulletList") editor.chain().focus().toggleBulletList().run();
  else editor.chain().focus().toggleOrderedList().run();
}

function extractSelectionToBlockWrap(editor: Editor, type: BlockWrapType): boolean {
  const { schema } = editor.state;
  const paragraphType = schema.nodes.paragraph;
  const blockquoteType = schema.nodes.blockquote;
  const bulletListType = schema.nodes.bulletList;
  const orderedListType = schema.nodes.orderedList;
  const listItemType = schema.nodes.listItem;
  if (!paragraphType) return false;

  return extractPartialTextSelection(editor, (selectedContent) => {
    const paragraph = paragraphType.create(null, selectedContent);
    if (type === "blockquote") {
      return blockquoteType ? blockquoteType.create(null, paragraph) : null;
    }
    if (!listItemType) return null;
    const listItem = listItemType.create(null, paragraph);
    if (type === "bulletList") {
      return bulletListType ? bulletListType.create(null, listItem) : null;
    }
    return orderedListType ? orderedListType.create(null, listItem) : null;
  });
}

/** Extract a selection that covers PART of one top-level paragraph into the
 *  block `createSelectedBlock` builds from it, leaving the text before and
 *  after as paragraphs. Returns false — nothing dispatched — when the
 *  selection is empty, spans blocks, sits in a nested block, or covers the
 *  whole paragraph (TipTap's own command is the right tool then). */
function extractPartialTextSelection(
  editor: Editor,
  createSelectedBlock: (selectedContent: Fragment) => ProseMirrorNode | null,
): boolean {
  const { state, view } = editor;
  const { selection } = state;
  const { $from: fromR, $to: toR, from, to } = selection;
  const parent = fromR.parent;
  const paragraphType = state.schema.nodes.paragraph;

  if (selection.empty || !paragraphType || !fromR.sameParent(toR) || fromR.depth !== 1 || !parent.isTextblock) {
    return false;
  }

  const parentStart = fromR.start();
  const parentEnd = fromR.end();
  if (from === parentStart && to === parentEnd) {
    return false;
  }

  const beforeContent = parent.content.cut(0, from - parentStart);
  const selectedContent = parent.content.cut(from - parentStart, to - parentStart);
  const afterContent = parent.content.cut(to - parentStart, parent.content.size);
  if (selectedContent.size === 0) return false;
  const selectedBlock = createSelectedBlock(selectedContent);
  if (!selectedBlock) return false;

  const paragraphOf = (content: Fragment) => (content.size === 0 ? null : paragraphType.create(null, content));
  const replacementNodes = [paragraphOf(beforeContent), selectedBlock, paragraphOf(afterContent)].filter(
    (n): n is ProseMirrorNode => n !== null,
  );

  const transaction = state.tr.replaceWith(fromR.before(), fromR.after(), replacementNodes);
  view.dispatch(transaction.scrollIntoView());
  view.focus();
  return true;
}
