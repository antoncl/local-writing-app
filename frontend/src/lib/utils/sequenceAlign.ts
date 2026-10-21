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
 * pairs a "rewrite" of itself (`isARewriteOf`, at least half its words
 * shared) ahead of a lookahead match on either side, and falls back to one
 * unpaired stacked pair when neither side has one within the look-ahead.
 */
import { SequenceMatcher } from "@/lib/utils/sequenceMatcher";

export const MAX_WORD_DIFF_TOKENS = 2000;
const SAME_BLOCK_RATIO = 0.5;
const ALIGN_LOOKAHEAD = 4;
/** The body's look-ahead, in paragraphs. Until #2591 the body aligned its
 *  blank-line separators as items too, so `ALIGN_LOOKAHEAD`'s 4 items reached
 *  2 paragraphs — the reach the body's pairing was tested at. Lists never had
 *  separators and keep their 4. */
export const BODY_ALIGN_LOOKAHEAD = 2;
// A word (letters, digits, `_`, joined by an inner apostrophe or hyphen) or one
// punctuation mark, each carrying the whitespace after it; a block's leading
// whitespace is a token of its own. The backend's `TOKEN` (snapshot_diff.py),
// whose note says why (#2600) — `[\p{L}\p{N}_]` is Python's Unicode `\w`.
const TOKEN_RE = /\s+|[\p{L}\p{N}_]+(?:['’-][\p{L}\p{N}_]+)*\s*|[^\p{L}\p{N}_\s]\s*/gu;

export const tokenize = (s: string): string[] => s.match(TOKEN_RE) ?? [];
/** What the matcher compares: the token without its trailing whitespace (a
 *  leading-whitespace token is its own key). */
export const tokenKey = (t: string): string => t.trimEnd() || t;
/** The matcher's `isjunk`: a key with no letter or digit (punctuation, leading
 *  whitespace) may not anchor a match — except a table's `|`, which is
 *  structure an in-cell edit must anchor on. The backend's `_is_junk`. */
export const isJunkKey = (key: string): boolean => key !== "|" && !/[\p{L}\p{N}_]/u.test(key);

/** Whether `now` reads as a rewrite of `was`: at least half their words (by
 *  `SequenceMatcher` ratio over word keys; punctuation is left out) are shared. Empty
 *  strings and anything past `MAX_WORD_DIFF_TOKENS` are never a rewrite of
 *  anything.
 *
 *  Symmetric, so no caller can ask it backwards (#2591): `isjunk` applies to
 *  the matcher's second sequence only, and one real paragraph pair scored 0.74
 *  one way round and under 0.5 the other. `quickRatio` is a bag count and
 *  already symmetric, so only the real ratio is asked again. */
export function isARewriteOf(was: string, now: string): boolean {
  // Words only (#2600) — the backend's `_is_a_rewrite_of` says why.
  const wasTokens = tokenize(was).map(tokenKey).filter((key) => !isJunkKey(key));
  const nowTokens = tokenize(now).map(tokenKey).filter((key) => !isJunkKey(key));
  if (wasTokens.length === 0 || nowTokens.length === 0) return false;
  if (Math.max(wasTokens.length, nowTokens.length) > MAX_WORD_DIFF_TOKENS) return false;
  const matcher = new SequenceMatcher(isJunkKey, wasTokens, nowTokens);
  if (matcher.quickRatio() < SAME_BLOCK_RATIO) return false;
  if (matcher.ratio() >= SAME_BLOCK_RATIO) return true;
  return new SequenceMatcher(isJunkKey, nowTokens, wasTokens).ratio() >= SAME_BLOCK_RATIO;
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
export function alignSequences(was: string[], now: string[], lookahead = ALIGN_LOOKAHEAD): AlignOp[] {
  const ops: AlignOp[] = [];
  const matcher = new SequenceMatcher(null, was, now);
  for (const [op, i1, i2, j1, j2] of matcher.getOpcodes()) {
    if (op === "equal") ops.push({ op: "equal", wasStart: i1, wasEnd: i2, nowStart: j1, nowEnd: j2 });
    else if (op === "insert") ops.push({ op: "insert", nowStart: j1, nowEnd: j2 });
    else if (op === "delete") ops.push({ op: "delete", wasStart: i1, wasEnd: i2 });
    else ops.push(...alignReplaceSpan(was, now, [i1, i2, j1, j2], lookahead));
  }
  return ops;
}

function alignReplaceSpan(
  was: string[],
  now: string[],
  [i1, i2, j1, j2]: [number, number, number, number],
  lookahead: number,
): AlignOp[] {
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
    const aheadNow = firstMatchIndex(was[i], now, j + 1, Math.min(j2, j + 1 + lookahead));
    const aheadWas = firstMatchIndex(now[j], was, i + 1, Math.min(i2, i + 1 + lookahead));
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
