// Read aloud (#2570): the text a reading speaks, split into sentences that each
// know the document range they cover - so the current one can be highlighted,
// clicked to, and flagged. Pure: a ProseMirror doc in, sentences out.
//
// Story text only: a textblock's text nodes. Inline atoms (mutation pills) are
// skipped, marks (TODO anchors, characters) are just marks on text that is kept.
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";

export type ReadAloudSentence = { text: string; from: number; to: number };

type Span = { start: number; end: number };

/** Sentence spans of `text` (UTF-16 offsets): Intl.Segmenter, or - where the
 *  runtime has none - a split after sentence punctuation followed by space. */
function sentenceSpans(text: string): Span[] {
  const Segmenter = (Intl as { Segmenter?: typeof Intl.Segmenter }).Segmenter;
  if (Segmenter) {
    const spans: Span[] = [];
    for (const part of new Segmenter(undefined, { granularity: "sentence" }).segment(text)) {
      spans.push({ start: part.index, end: part.index + part.segment.length });
    }
    return spans;
  }
  const spans: Span[] = [];
  let start = 0;
  const boundary = /[.!?…]+["')\]”’»]*\s+/g;
  for (let m = boundary.exec(text); m; m = boundary.exec(text)) {
    spans.push({ start, end: m.index + m[0].length });
    start = m.index + m[0].length;
  }
  if (start < text.length) spans.push({ start, end: text.length });
  return spans;
}

/** The sentences of the doc between `from` and `to`, in reading order. A
 *  sentence never spans two textblocks, and a range that starts or ends
 *  mid-sentence reads only the part inside it. */
export function collectSentences(doc: ProseMirrorNode, from: number, to: number): ReadAloudSentence[] {
  const sentences: ReadAloudSentence[] = [];
  doc.nodesBetween(from, to, (node, pos) => {
    if (!node.isTextblock) return true;
    let text = "";
    const positions: number[] = []; // doc position of each character of `text`
    node.forEach((child, offset) => {
      const childPos = pos + 1 + offset;
      if (child.isText) {
        const value = child.text ?? "";
        for (let i = 0; i < value.length; i++) {
          const at = childPos + i;
          if (at >= from && at < to) {
            text += value[i];
            positions.push(at);
          }
        }
      } else if (child.type.name === "hardBreak" && childPos >= from && childPos < to) {
        text += " "; // a line break must not glue the words either side of it
        positions.push(childPos);
      }
    });
    for (const { start, end } of sentenceSpans(text)) {
      const raw = text.slice(start, end);
      const lead = raw.length - raw.trimStart().length;
      const trimmed = raw.trim();
      if (!trimmed) continue;
      sentences.push({
        text: trimmed,
        from: positions[start + lead],
        to: positions[start + lead + trimmed.length - 1] + 1,
      });
    }
    return false;
  });
  return sentences;
}
