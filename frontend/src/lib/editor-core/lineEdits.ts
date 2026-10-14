/** Placing a model's line edits (#2460) on the document.
 *
 *  A line-edit reply is a list of `{find, replace, reason}` against the revised
 *  selection. The model quotes text, it does not give positions, so each `find`
 *  is located in the selection here, and only when that is unambiguous: an edit
 *  is placed iff its `find` occurs exactly once across the selection's text
 *  blocks (never spanning two blocks). Anything else is dropped — a wrong
 *  guess would put a strike-through on the wrong words. */
import type { Node as PMNode } from "@tiptap/pm/model";
import type { LineEdit } from "@/lib/types";

/** An edit located in the document, in document positions. */
export type PlacedEdit = { from: number; to: number; find: string; replace: string; reason: string };

export type PlacementResult = {
  /** Sorted by `from`; never overlapping. */
  placed: PlacedEdit[];
  /** Edits that could not be placed (absent, ambiguous, overlapping). A no-op
   *  edit (`find === replace`) is silently ignored and is not counted. */
  dropped: number;
};

/** Stands in for an inline leaf (hard break, pill) so a `find` can't span it. */
const LEAF = "￼";

/** Typographic characters a model tends to flatten to ASCII. Strictly 1:1 (no
 *  ellipsis), so `posOf` indices stay valid on the normalized text. */
const TYPOGRAPHIC: Record<string, string> = {
  "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
  "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
  "—": "-", "–": "-", "‒": "-", "―": "-",
  " ": " ", " ": " ",
};
const normalize = (s: string) => s.split("").map((c) => TYPOGRAPHIC[c] ?? c).join("");

/** One text block's visible text within [from, to], with each character's
 *  document position. */
type BlockText = { text: string; posOf: number[] };

function blockTexts(doc: PMNode, from: number, to: number): BlockText[] {
  const blocks: BlockText[] = [];
  doc.nodesBetween(from, to, (node, pos) => {
    if (!node.isTextblock) return true;
    let text = "";
    const posOf: number[] = [];
    node.descendants((child, offset) => {
      const childPos = pos + 1 + offset;
      if (child.isText) {
        const run = child.text ?? "";
        for (let i = 0; i < run.length; i++) {
          const at = childPos + i;
          if (at >= from && at < to) {
            text += run[i];
            posOf.push(at);
          }
        }
      } else if (child.isLeaf && childPos >= from && childPos < to) {
        text += LEAF;
        posOf.push(childPos);
      }
      return true;
    });
    if (text) blocks.push({ text, posOf });
    return false;
  });
  return blocks;
}

/** Every start index of `find` in `text`, overlapping ones included. */
function occurrences(text: string, find: string): number[] {
  const hits: number[] = [];
  let at = text.indexOf(find);
  while (at !== -1) {
    hits.push(at);
    at = text.indexOf(find, at + 1);
  }
  return hits;
}

export function placeLineEdits(doc: PMNode, from: number, to: number, edits: LineEdit[]): PlacementResult {
  const blocks = blockTexts(doc, from, to);
  const placed: PlacedEdit[] = [];
  let dropped = 0;
  for (const edit of edits) {
    if (edit.find === edit.replace) continue;
    if (!edit.find) {
      dropped += 1;
      continue;
    }
    // Matched on typographic-normalized text (1:1, so indices line up with `text`).
    const find = normalize(edit.find);
    const hits: { block: BlockText; at: number }[] = [];
    for (const block of blocks) {
      for (const at of occurrences(normalize(block.text), find)) hits.push({ block, at });
    }
    if (hits.length !== 1) {
      dropped += 1;
      continue;
    }
    const { block, at } = hits[0];
    const start = block.posOf[at];
    const end = block.posOf[at + find.length - 1] + 1;
    // Model order wins: a later edit overlapping an already-placed one is dropped.
    if (placed.some((p) => start < p.to && p.from < end)) {
      dropped += 1;
      continue;
    }
    // `find` becomes the document's own text for the range: the review plugin re-checks it.
    const docFind = block.text.slice(at, at + find.length);
    placed.push({ from: start, to: end, find: docFind, replace: edit.replace, reason: edit.reason });
  }
  placed.sort((a, b) => a.from - b.from);
  return { placed, dropped };
}
