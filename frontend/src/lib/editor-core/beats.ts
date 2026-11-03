// Roleplay beats (ADR-0070 Amendment 1): a beat is everything between an open
// marker (`characterOpen`, names the character) and the next close marker
// (`characterClose`, carries the interiority). Both are inline atoms, so a beat
// may span paragraphs, and the interiority is stored once, on the close marker.
//
// Markers pair in document order. Beats never nest, so an open marker followed
// by another open marker before any close is an orphan, and so is a close marker
// with no open marker before it. An orphan attributes nothing (decision 8).

import type { Node as PMNode } from "@tiptap/pm/model";
import { TextSelection, type EditorState, type Transaction } from "@tiptap/pm/state";

export const BEAT_OPEN = "characterOpen";
export const BEAT_CLOSE = "characterClose";

export type Beat = {
  characterId: string;
  /** Position of the open marker atom. */
  open: number;
  /** Position of the close marker atom. */
  close: number;
  internal: string;
};

export type BeatScan = {
  beats: Beat[];
  /** Positions of marker atoms with no partner. */
  orphans: number[];
};

/** Pair every beat marker in `doc`. One walk; exported for the decoration
 *  plugin, the slash menu and tests. */
export function scanBeats(doc: PMNode): BeatScan {
  const beats: Beat[] = [];
  const orphans: number[] = [];
  let pending: { characterId: string; pos: number } | null = null;
  doc.descendants((node, pos) => {
    if (node.isTextblock || node.isBlock) return true;
    if (node.type.name === BEAT_OPEN) {
      if (pending) orphans.push(pending.pos);
      pending = { characterId: String(node.attrs.characterId ?? ""), pos };
    } else if (node.type.name === BEAT_CLOSE) {
      if (pending) {
        beats.push({
          characterId: pending.characterId,
          open: pending.pos,
          close: pos,
          internal: String(node.attrs.internal ?? ""),
        });
        pending = null;
      } else {
        orphans.push(pos);
      }
    }
    return false;
  });
  if (pending) orphans.push((pending as { pos: number }).pos);
  return { beats, orphans };
}

/** The beat whose markers enclose `pos` (strictly after the open marker, at or
 *  before the close marker), or null. A cursor right after the close marker is
 *  outside the beat. */
export function beatAt(doc: PMNode, pos: number): Beat | null {
  return scanBeats(doc).beats.find((b) => pos > b.open && pos <= b.close) ?? null;
}

/** Why a roleplay turn can't start at the cursor (decision 5): shown on the
 *  slash menu's hint line and as the notice when another path tries. */
export function insideBeatReason(characterTitle: string): string {
  return `Inside ${characterTitle}'s beat: move the cursor outside it, or split the beat.`;
}

/** `/roleplay split` (decision 6): end the beat around `pos` there and start a
 *  new beat for the same character right after. Both halves keep a copy of the
 *  interiority. Returns the transaction and both close-marker positions in the
 *  new doc (to reveal them, so the author trims each), or null outside a beat. */
export function splitBeat(
  state: EditorState,
  pos: number,
): { tr: Transaction; closes: [number, number] } | null {
  const beat = beatAt(state.doc, pos);
  if (!beat) return null;
  const { schema } = state;
  const close = schema.nodes[BEAT_CLOSE].create({ internal: beat.internal });
  const open = schema.nodes[BEAT_OPEN].create({ characterId: beat.characterId });
  const tr = state.tr.insert(pos, [close, open]);
  tr.setSelection(TextSelection.create(tr.doc, pos + 2));
  return { tr, closes: [pos, beat.close + 2] };
}
