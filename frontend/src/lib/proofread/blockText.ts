// Proofreading (ADR-0102 §2): the text an engine lints, one text block at a
// time, and the way back from an offset in that text to a document position.
//
// Text nodes are concatenated in order and a hard break becomes "\n". Any other
// inline leaf contributes nothing: the mutation anchor and its close (ADR-0095)
// are points, and the text around them already carries its own spaces. Code
// blocks are not prose and are skipped.
import type { Node as PMNode } from "@tiptap/pm/model";

export type BlockText = {
  /** Document position where the block's content starts. */
  start: number;
  /** Document position where the block's content ends. */
  end: number;
  text: string;
  /** `pos[i]` is the document position of UTF-16 unit `i` of `text`. */
  pos: number[];
};

const HARD_BREAK = "hardBreak";

/** One block's text and position map. */
export function blockText(block: PMNode, start: number): BlockText {
  let text = "";
  const pos: number[] = [];
  block.forEach((child, offset) => {
    const at = start + offset;
    if (child.isText) {
      const t = child.text ?? "";
      for (let i = 0; i < t.length; i++) pos.push(at + i);
      text += t;
    } else if (child.type.name === HARD_BREAK) {
      pos.push(at);
      text += "\n";
    }
  });
  return { start, end: start + block.content.size, text, pos };
}

/** Every prose text block of `doc`, in document order. */
export function textBlocks(doc: PMNode): BlockText[] {
  const blocks: BlockText[] = [];
  doc.descendants((node, nodePos) => {
    if (!node.isTextblock) return true;
    if (!node.type.spec.code) blocks.push(blockText(node, nodePos + 1));
    return false;
  });
  return blocks;
}

/** The document range of `[from, to)` in `block`'s text. An empty range is the
 *  position right after the character before it, so an insertion lands next to
 *  the text it follows rather than after an atom that happens to sit there. */
export function docRange(block: BlockText, from: number, to: number): { from: number; to: number } {
  if (to > from) return { from: block.pos[from], to: block.pos[to - 1] + 1 };
  const at = from > 0 ? block.pos[from - 1] + 1 : (block.pos[0] ?? block.start);
  return { from: at, to: at };
}
