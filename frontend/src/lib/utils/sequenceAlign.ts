/**
 * The two-phase alignment `diffRuns` uses to align markdown blocks, extracted
 * (ADR-0096 §3, S2) to operate on plain string arrays by INDEX rather than by
 * markdown block, so a list's items can be aligned the same way the body
 * aligns paragraphs. `snapshotDiff.ts`'s `diffRuns`/`alignBlocks` are rebuilt
 * on `alignSequences` so their output stays byte-identical (parity corpus,
 * `diffRuns.fixtures.json`); `listCompare.ts` is the other consumer.
 *
 * Phase 1 anchors on exact equality (`SequenceMatcher(null, was, now)`).
 * Phase 2 runs only inside a `replace` span: a greedy left-to-right pass that
 * pairs a "rewrite" of itself (`isARewriteOf`, at least half its tokens
 * shared) ahead of a lookahead match on either side, and falls back to one
 * unpaired stacked pair when neither side has one within `ALIGN_LOOKAHEAD`.
 */
import { SequenceMatcher } from "@/lib/utils/sequenceMatcher";

export const MAX_WORD_DIFF_TOKENS = 2000;
const SAME_BLOCK_RATIO = 0.5;
const ALIGN_LOOKAHEAD = 4;
const TOKEN_RE = /\S+|\s+/g;

export const isWhitespaceToken = (t: string): boolean => t.length > 0 && !/\S/.test(t);
export const tokenize = (s: string): string[] => s.match(TOKEN_RE) ?? [];

/** Whether `now` reads as a rewrite of `was`: at least half their tokens (by
 *  `SequenceMatcher` ratio, ignoring whitespace tokens) are shared. Empty
 *  strings and anything past `MAX_WORD_DIFF_TOKENS` are never a rewrite of
 *  anything. */
export function isARewriteOf(was: string, now: string): boolean {
  const wasTokens = tokenize(was);
  const nowTokens = tokenize(now);
  if (wasTokens.length === 0 || nowTokens.length === 0) return false;
  if (Math.max(wasTokens.length, nowTokens.length) > MAX_WORD_DIFF_TOKENS) return false;
  const matcher = new SequenceMatcher(isWhitespaceToken, wasTokens, nowTokens);
  if (matcher.quickRatio() < SAME_BLOCK_RATIO) return false;
  return matcher.ratio() >= SAME_BLOCK_RATIO;
}

/** One step of the alignment, in output order. `equal`/`insert`/`delete` carry
 *  a half-open index RANGE (possibly spanning several items); `rewrite` and
 *  `unpaired` each pair exactly one `was` index with exactly one `now` index. */
export type AlignOp =
  | { op: "equal"; wasStart: number; wasEnd: number; nowStart: number; nowEnd: number }
  | { op: "insert"; nowStart: number; nowEnd: number }
  | { op: "delete"; wasStart: number; wasEnd: number }
  | { op: "rewrite"; was: number; now: number }
  | { op: "unpaired"; was: number; now: number };

/** The alignment of two sequences, phase 1 then phase 2, as index ops. */
export function alignSequences(was: string[], now: string[]): AlignOp[] {
  const ops: AlignOp[] = [];
  const matcher = new SequenceMatcher(null, was, now);
  for (const [op, i1, i2, j1, j2] of matcher.getOpcodes()) {
    if (op === "equal") ops.push({ op: "equal", wasStart: i1, wasEnd: i2, nowStart: j1, nowEnd: j2 });
    else if (op === "insert") ops.push({ op: "insert", nowStart: j1, nowEnd: j2 });
    else if (op === "delete") ops.push({ op: "delete", wasStart: i1, wasEnd: i2 });
    else ops.push(...alignReplaceSpan(was, now, i1, i2, j1, j2));
  }
  return ops;
}

function alignReplaceSpan(was: string[], now: string[], i1: number, i2: number, j1: number, j2: number): AlignOp[] {
  const ops: AlignOp[] = [];
  let i = i1;
  let j = j1;
  while (i < i2 && j < j2) {
    if (isARewriteOf(was[i], now[j])) {
      ops.push({ op: "rewrite", was: i, now: j });
      i++;
      j++;
      continue;
    }
    const aheadNow = firstMatchIndex(was[i], now, j + 1, Math.min(j2, j + 1 + ALIGN_LOOKAHEAD));
    const aheadWas = firstMatchIndex(now[j], was, i + 1, Math.min(i2, i + 1 + ALIGN_LOOKAHEAD));
    if (aheadNow !== null && (aheadWas === null || aheadNow - j <= aheadWas - i)) {
      ops.push({ op: "insert", nowStart: j, nowEnd: aheadNow });
      j = aheadNow;
    } else if (aheadWas !== null) {
      ops.push({ op: "delete", wasStart: i, wasEnd: aheadWas });
      i = aheadWas;
    } else {
      ops.push({ op: "unpaired", was: i, now: j });
      i++;
      j++;
    }
  }
  if (i < i2) ops.push({ op: "delete", wasStart: i, wasEnd: i2 });
  if (j < j2) ops.push({ op: "insert", nowStart: j, nowEnd: j2 });
  return ops;
}

function firstMatchIndex(block: string, candidates: string[], start: number, stop: number): number | null {
  for (let index = start; index < stop; index++) {
    if (isARewriteOf(block, candidates[index])) return index;
  }
  return null;
}
