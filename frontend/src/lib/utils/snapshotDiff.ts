/**
 * The snapshot / entry diff, computed in the browser (#573, ADR-0046 slice 0).
 *
 * A faithful TypeScript port of the backend's `diff_runs`
 * (`backend/app/services/project/snapshot_diff.py` + `markdown_scan.py`), with a
 * from-scratch `difflib.SequenceMatcher` (`isjunk` supported; `autojunk` is
 * always False, as the backend uses it). It produces the same provenance-tagged
 * `DiffRun[]` the server used to — warm `now` / cool `was` / shared `equal` —
 * which `diffRuns.ts` renders into the flip (ADR-0044).
 *
 * **Parity is a gate, not a hope.** `snapshotDiff.test.ts` asserts this reproduces
 * the backend's runs byte-for-byte over `diffRuns.fixtures.json` (whose `runs` are
 * generated from `snapshot_diff.py`). #573's spike measured the same port at
 * parity across 426 fuzzed cases and 4–6.8× faster than CPython.
 *
 * **Offsets are UTF-16 code units** (the backend uses Python code points). Run
 * boundaries fall at token / markdown-construct edges, never mid-token, so a
 * surrogate pair is never split; the two engines can only differ on where a
 * boundary lands *around* an astral character, which BMP prose (all fiction, the
 * whole fixture corpus) never contains. If astral-exact parity is ever needed,
 * this is the seam to make code-point-aware.
 *
 * **Whitespace classification follows JS, not Python `re`.** A few rare characters
 * are classed oppositely by the two — BOM (U+FEFF) is whitespace to JS but not
 * Python; NEL (U+0085) and FS–US (U+001C–U+001F) the reverse — so a body carrying
 * one of them would tokenise, and thus diff, slightly differently from the
 * backend. None occur in fiction prose, and once the client is the diff authority
 * (#573) the JS classification is simply the standard.
 *
 * This module only computes `runs` (the prose diff). Field diffs (`FieldDiff`) and
 * drift stay where their inputs live; see `PORT-SCOPE.md` in the #573 spike.
 */
import type { DiffRun } from "@/lib/types";

type Interval = [number, number];
type Region = [number, number, number, number]; // was_start, was_end, now_start, now_end

const run = (kind: DiffRun["kind"], text: string, stacked = false): DiffRun => ({ kind, text, stacked });

// ===========================================================================
// difflib.SequenceMatcher  (isjunk supported; autojunk=False everywhere here)
// ===========================================================================
type IsJunk = ((s: string) => boolean) | null;

class SequenceMatcher {
  private a: string[];
  private b: string[];
  private isjunk: IsJunk;
  private b2j = new Map<string, number[]>();
  private bjunk = new Set<string>();
  private matchingBlocks: [number, number, number][] | null = null;
  private fullbcount: Map<string, number> | null = null;

  constructor(isjunk: IsJunk, a: string[], b: string[]) {
    this.isjunk = isjunk;
    this.a = a;
    this.b = b;
    this.chainB();
  }

  private chainB(): void {
    const b2j = new Map<string, number[]>();
    for (let i = 0; i < this.b.length; i++) {
      const elt = this.b[i];
      const arr = b2j.get(elt);
      if (arr) arr.push(i);
      else b2j.set(elt, [i]);
    }
    const bjunk = new Set<string>();
    if (this.isjunk) {
      for (const elt of b2j.keys()) if (this.isjunk(elt)) bjunk.add(elt);
      for (const elt of bjunk) b2j.delete(elt);
    }
    // autojunk = False: no popular-element pruning.
    this.b2j = b2j;
    this.bjunk = bjunk;
  }

  private isbjunk(elt: string): boolean {
    return this.bjunk.has(elt);
  }

  findLongestMatch(alo: number, ahi: number, blo: number, bhi: number): [number, number, number] {
    const { a, b, b2j } = this;
    let besti = alo;
    let bestj = blo;
    let bestsize = 0;
    let j2len = new Map<number, number>();
    for (let i = alo; i < ahi; i++) {
      const newj2len = new Map<number, number>();
      const js = b2j.get(a[i]);
      if (js) {
        for (const j of js) {
          if (j < blo) continue;
          if (j >= bhi) break;
          const k = (j2len.get(j - 1) ?? 0) + 1;
          newj2len.set(j, k);
          if (k > bestsize) {
            besti = i - k + 1;
            bestj = j - k + 1;
            bestsize = k;
          }
        }
      }
      j2len = newj2len;
    }
    while (besti > alo && bestj > blo && !this.isbjunk(b[bestj - 1]) && a[besti - 1] === b[bestj - 1]) {
      besti--;
      bestj--;
      bestsize++;
    }
    while (
      besti + bestsize < ahi &&
      bestj + bestsize < bhi &&
      !this.isbjunk(b[bestj + bestsize]) &&
      a[besti + bestsize] === b[bestj + bestsize]
    ) {
      bestsize++;
    }
    while (besti > alo && bestj > blo && this.isbjunk(b[bestj - 1]) && a[besti - 1] === b[bestj - 1]) {
      besti--;
      bestj--;
      bestsize++;
    }
    while (
      besti + bestsize < ahi &&
      bestj + bestsize < bhi &&
      this.isbjunk(b[bestj + bestsize]) &&
      a[besti + bestsize] === b[bestj + bestsize]
    ) {
      bestsize++;
    }
    return [besti, bestj, bestsize];
  }

  getMatchingBlocks(): [number, number, number][] {
    if (this.matchingBlocks) return this.matchingBlocks;
    const la = this.a.length;
    const lb = this.b.length;
    const queue: [number, number, number, number][] = [[0, la, 0, lb]];
    const matching: [number, number, number][] = [];
    while (queue.length) {
      const [alo, ahi, blo, bhi] = queue.pop()!;
      const [i, j, k] = this.findLongestMatch(alo, ahi, blo, bhi);
      if (k) {
        matching.push([i, j, k]);
        if (alo < i && blo < j) queue.push([alo, i, blo, j]);
        if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
      }
    }
    matching.sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2]);
    const nonAdjacent: [number, number, number][] = [];
    let i1 = 0;
    let j1 = 0;
    let k1 = 0;
    for (const [i2, j2, k2] of matching) {
      if (i1 + k1 === i2 && j1 + k1 === j2) {
        k1 += k2;
      } else {
        if (k1) nonAdjacent.push([i1, j1, k1]);
        i1 = i2;
        j1 = j2;
        k1 = k2;
      }
    }
    if (k1) nonAdjacent.push([i1, j1, k1]);
    nonAdjacent.push([la, lb, 0]);
    this.matchingBlocks = nonAdjacent;
    return nonAdjacent;
  }

  getOpcodes(): [string, number, number, number, number][] {
    const answer: [string, number, number, number, number][] = [];
    let i = 0;
    let j = 0;
    for (const [ai, bj, size] of this.getMatchingBlocks()) {
      let tag = "";
      if (i < ai && j < bj) tag = "replace";
      else if (i < ai) tag = "delete";
      else if (j < bj) tag = "insert";
      if (tag) answer.push([tag, i, ai, j, bj]);
      i = ai + size;
      j = bj + size;
      if (size) answer.push(["equal", ai, i, bj, j]);
    }
    return answer;
  }

  ratio(): number {
    let matches = 0;
    for (const mb of this.getMatchingBlocks()) matches += mb[2];
    const T = this.a.length + this.b.length;
    return T ? (2.0 * matches) / T : 1.0;
  }

  quickRatio(): number {
    if (!this.fullbcount) {
      const c = new Map<string, number>();
      for (const elt of this.b) c.set(elt, (c.get(elt) ?? 0) + 1);
      this.fullbcount = c;
    }
    const avail = new Map<string, number>();
    let matches = 0;
    for (const elt of this.a) {
      const numb = avail.has(elt) ? avail.get(elt)! : (this.fullbcount.get(elt) ?? 0);
      avail.set(elt, numb - 1);
      if (numb > 0) matches++;
    }
    const T = this.a.length + this.b.length;
    return T ? (2.0 * matches) / T : 1.0;
  }
}

// ===========================================================================
// markdown_scan.py
// ===========================================================================
const LINE_MARKER = /^[ \t]*(?:>[ \t]?|(?:[-*+]|\d+[.)])[ \t]+|#{1,6}[ \t]+|\|)/;
const EMPHASIS = "*_~";
const REFERENCE_LINK_Y = /\[[^\]\n]*\]\[[^\]\n]*\]/y;
const REFERENCE_DEF_Y = /\[[^\]\n]+\]:[ \t]*\S+/y;
const TABLE_DELIMITER = /^[ \t]*:?-{1,}:?([ \t]*\|[ \t]*:?-{1,}:?)+[ \t]*$/;
const SETEXT_UNDERLINE = /^[ \t]*(=+|-{2,})[ \t]*$/;
const CODE_FENCE = /^[ \t]*(```|~~~)/;
const INDENTED_CODE = /^(?: {4}|\t)/;

const MARKER_PAIRS: [string, string][] = [
  ["<!-- embedded-todo:", "<!-- /embedded-todo -->"],
  ["<!-- character:", "<!-- /character -->"],
];

type Scanned = { end: number; span?: Interval; delimiter?: [number, number, string] };
type Scan = Scanned | "UNSCANNABLE" | null;

function markerPairEnd(block: string, start: number, commentEnd: number): number {
  for (const [opener, closer] of MARKER_PAIRS) {
    if (block.startsWith(opener, start)) {
      const close = block.indexOf(closer, commentEnd);
      if (close >= 0) return close + closer.length;
    }
  }
  return commentEnd;
}

function scanEscape(block: string, i: number): Scan {
  if (block[i] !== "\\" || i + 1 >= block.length) return null;
  return { end: i + 2, span: [i, i + 2] };
}
function scanHtmlComment(block: string, i: number): Scan {
  if (!block.startsWith("<!--", i)) return null;
  const close = block.indexOf("-->", i + 4);
  if (close < 0) return "UNSCANNABLE";
  const end = markerPairEnd(block, i, close + 3);
  return { end, span: [i, end] };
}
function scanReferenceLink(block: string, i: number): Scan {
  if (block[i] !== "[") return null;
  REFERENCE_LINK_Y.lastIndex = i;
  let m = REFERENCE_LINK_Y.exec(block);
  if (!m) {
    REFERENCE_DEF_Y.lastIndex = i;
    m = REFERENCE_DEF_Y.exec(block);
  }
  if (!m) return null;
  const end = i + m[0].length;
  return { end, span: [i, end] };
}
function scanCodeSpan(block: string, i: number): Scan {
  if (block[i] !== "`") return null;
  const r = runLength(block, i, "`");
  const close = findBacktickRun(block, i + r, r);
  if (close < 0) return "UNSCANNABLE";
  return { end: close + r, span: [i, close + r] };
}
function scanAutolink(block: string, i: number): Scan {
  if (block[i] !== "<") return null;
  const close = block.indexOf(">", i + 1);
  if (close > 0 && !block.slice(i, close).includes("\n")) return { end: close + 1, span: [i, close + 1] };
  return "UNSCANNABLE";
}
function scanLink(block: string, i: number): Scan {
  if (block[i] !== "[" && !(block[i] === "!" && block.startsWith("![", i))) return null;
  const end = linkEnd(block, i);
  if (end === null) return { end: i + 1 };
  return { end, span: [i, end] };
}
function scanEmphasis(block: string, i: number): Scan {
  const char = block[i];
  if (!EMPHASIS.includes(char)) return null;
  const r = runLength(block, i, char);
  return { end: i + r, delimiter: [i, i + r, char.repeat(r)] };
}

// TRIGGERS inverted to opening char -> ordered handlers (see markdown_scan.py).
const SCANNERS: Map<string, ((b: string, i: number) => Scan)[]> = new Map([
  ["\\", [scanEscape]],
  ["<", [scanHtmlComment, scanAutolink]],
  ["[", [scanReferenceLink, scanLink]],
  ["`", [scanCodeSpan]],
  ["!", [scanLink]],
  ["*", [scanEmphasis]],
  ["_", [scanEmphasis]],
  ["~", [scanEmphasis]],
]);

function scanAt(block: string, i: number): Scan {
  const handlers = SCANNERS.get(block[i]);
  if (!handlers) return null;
  for (const h of handlers) {
    const res = h(block, i);
    if (res !== null) return res;
  }
  return null;
}

function protectedIntervals(block: string): Interval[] | null {
  const spans: Interval[] = [];
  const delimiters: [number, number, string][] = [];
  let index = 0;
  const length = block.length;
  while (index < length) {
    const scanned = scanAt(block, index);
    if (scanned === null) {
      index++;
      continue;
    }
    if (scanned === "UNSCANNABLE") return null;
    if (scanned.span) spans.push(scanned.span);
    if (scanned.delimiter) delimiters.push(scanned.delimiter);
    index = scanned.end;
  }
  const paired = pairDelimiters(delimiters);
  if (paired === null) return null;
  spans.push(...paired, ...lineMarkerIntervals(block));
  return mergeIntervals(spans);
}

function runLength(block: string, start: number, char: string): number {
  let index = start;
  while (index < block.length && block[index] === char) index++;
  return index - start;
}
function findBacktickRun(block: string, start: number, r: number): number {
  let index = start;
  while (index < block.length) {
    if (block[index] !== "`") {
      index++;
      continue;
    }
    const here = runLength(block, index, "`");
    if (here === r) return index;
    index += here;
  }
  return -1;
}
function linkEnd(block: string, start: number): number | null {
  let index = start + (block[start] === "!" ? 2 : 1);
  let depth = 1;
  while (index < block.length && depth) {
    if (block[index] === "\\") {
      index += 2;
      continue;
    }
    if (block[index] === "[") depth++;
    else if (block[index] === "]") depth--;
    index++;
  }
  if (depth || index >= block.length || block[index] !== "(") return null;
  depth = 1;
  index++;
  while (index < block.length && depth) {
    if (block[index] === "\\") {
      index += 2;
      continue;
    }
    if (block[index] === "(") depth++;
    else if (block[index] === ")") depth--;
    index++;
  }
  return depth ? null : index;
}
function pairDelimiters(delimiters: [number, number, string][]): Interval[] | null {
  const spans: Interval[] = [];
  const openRuns = new Map<string, [number, number][]>();
  for (const [start, end, marker] of delimiters) {
    let stack = openRuns.get(marker);
    if (!stack) {
      stack = [];
      openRuns.set(marker, stack);
    }
    if (stack.length) {
      const opened = stack.pop()!;
      spans.push([opened[0], end]);
    } else {
      stack.push([start, end]);
    }
  }
  for (const stack of openRuns.values()) if (stack.length) return null;
  return spans;
}
function lineMarkerIntervals(block: string): Interval[] {
  const spans: Interval[] = [];
  let start = 0;
  for (const seg of block.split("\n")) {
    const marker = LINE_MARKER.exec(seg);
    if (marker && marker[0]) {
      spans.push([Math.max(0, start - 1), start + marker[0].length]);
    }
    start += seg.length + 1; // + "\n"
  }
  return spans;
}
function firstLineIsStructural(block: string): boolean {
  const marker = LINE_MARKER.exec(block.split("\n", 1)[0]);
  return !!(marker && marker[0]);
}
function isCodeBlock(block: string): boolean {
  const lines = block.split("\n").filter((l) => l.trim());
  if (lines.length === 0) return false;
  if (CODE_FENCE.test(lines[0])) return true;
  return lines.every((l) => INDENTED_CODE.test(l));
}
function isStructured(block: string): boolean {
  const lines = block.split("\n");
  return (
    lines.some((l) => LINE_MARKER.test(l) || TABLE_DELIMITER.test(l) || SETEXT_UNDERLINE.test(l)) ||
    isCodeBlock(block)
  );
}
const CONTAINER_BREAKS = ["\n", "|"];
function escapesContainer(block: string, start: number, end: number): boolean {
  if (!isStructured(block)) return false;
  const slice = block.slice(start, end);
  return CONTAINER_BREAKS.some((c) => slice.includes(c));
}
function mergeIntervals(spans: Interval[]): Interval[] {
  if (spans.length === 0) return [];
  const sorted = [...spans].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged: Interval[] = [sorted[0]];
  for (let i = 1; i < sorted.length; i++) {
    const [s, e] = sorted[i];
    const last = merged[merged.length - 1];
    if (s <= last[1]) last[1] = Math.max(last[1], e);
    else merged.push([s, e]);
  }
  return merged;
}

// ===========================================================================
// snapshot_diff.py
// ===========================================================================
const BLOCK_SPLIT = /(\r?\n(?:[ \t]*\r?\n)+)/;
const TOKEN_RE = /\S+|\s+/g;
const MAX_WORD_DIFF_TOKENS = 2000;
const SAME_BLOCK_RATIO = 0.5;
const ALIGN_LOOKAHEAD = 4;
const SETTLE_PASSES = 12;

const isWhitespaceToken = (t: string): boolean => t.length > 0 && !/\S/.test(t);
const tokenize = (s: string): string[] => s.match(TOKEN_RE) ?? [];

/** Provenance-tagged runs over two markdown bodies, oldest state first. */
export function diffRuns(was: string, now: string): DiffRun[] {
  const wasBlocks = was.split(BLOCK_SPLIT);
  const nowBlocks = now.split(BLOCK_SPLIT);
  const runs: DiffRun[] = [];
  const matcher = new SequenceMatcher(null, wasBlocks, nowBlocks);
  for (const [op, i1, i2, j1, j2] of matcher.getOpcodes()) {
    if (op === "equal") runs.push(run("equal", wasBlocks.slice(i1, i2).join("")));
    else if (op === "insert") runs.push(run("now", nowBlocks.slice(j1, j2).join(""), true));
    else if (op === "delete") runs.push(run("was", wasBlocks.slice(i1, i2).join(""), true));
    else runs.push(...alignBlocks(wasBlocks.slice(i1, i2), nowBlocks.slice(j1, j2)));
  }
  return coalesce(runs);
}

function alignBlocks(wasBlocks: string[], nowBlocks: string[]): DiffRun[] {
  const runs: DiffRun[] = [];
  let i = 0;
  let j = 0;
  while (i < wasBlocks.length && j < nowBlocks.length) {
    if (isARewriteOf(wasBlocks[i], nowBlocks[j])) {
      runs.push(...blockRuns(wasBlocks[i], nowBlocks[j]));
      i++;
      j++;
      continue;
    }
    const aheadNow = firstMatch(wasBlocks[i], nowBlocks, j + 1, j + 1 + ALIGN_LOOKAHEAD);
    const aheadWas = firstMatch(nowBlocks[j], wasBlocks, i + 1, i + 1 + ALIGN_LOOKAHEAD);
    if (aheadNow !== null && (aheadWas === null || aheadNow - j <= aheadWas - i)) {
      runs.push(run("now", nowBlocks.slice(j, aheadNow).join(""), true));
      j = aheadNow;
    } else if (aheadWas !== null) {
      runs.push(run("was", wasBlocks.slice(i, aheadWas).join(""), true));
      i = aheadWas;
    } else {
      runs.push(...stackedPair(wasBlocks[i], nowBlocks[j]));
      i++;
      j++;
    }
  }
  if (i < wasBlocks.length) runs.push(run("was", wasBlocks.slice(i).join(""), true));
  if (j < nowBlocks.length) runs.push(run("now", nowBlocks.slice(j).join(""), true));
  return runs;
}

function firstMatch(block: string, candidates: string[], start: number, stop: number): number | null {
  for (let index = start; index < Math.min(stop, candidates.length); index++) {
    if (isARewriteOf(block, candidates[index])) return index;
  }
  return null;
}

function tooLargeToDiff(...blocks: string[]): boolean {
  return blocks.some((b) => tokenize(b).length > MAX_WORD_DIFF_TOKENS);
}

function isARewriteOf(was: string, now: string): boolean {
  const wasTokens = tokenize(was);
  const nowTokens = tokenize(now);
  if (wasTokens.length === 0 || nowTokens.length === 0) return false;
  if (Math.max(wasTokens.length, nowTokens.length) > MAX_WORD_DIFF_TOKENS) return false;
  const matcher = new SequenceMatcher(isWhitespaceToken, wasTokens, nowTokens);
  if (matcher.quickRatio() < SAME_BLOCK_RATIO) return false;
  return matcher.ratio() >= SAME_BLOCK_RATIO;
}

function blockRuns(was: string, now: string): DiffRun[] {
  if (was === now) return [run("equal", was)];
  const regions = changedRegions(was, now);
  if (regions === null) return stackedPair(was, now);
  const runs = emitRuns(regions, was, now);
  if (!reassembles(runs, was, now)) return stackedPair(was, now);
  return runs;
}

function changedRegions(was: string, now: string): Region[] | null {
  const wasIntervals = protectedIntervals(was);
  const nowIntervals = protectedIntervals(now);
  if (wasIntervals === null || nowIntervals === null) return null;
  if (tooLargeToDiff(was, now)) return null;
  if (isCodeBlock(was) || isCodeBlock(now)) return null;
  const regions = settle(tokenRegions(was, now), was, now, wasIntervals, nowIntervals);
  if (regions === null || needsStacking(regions, was, now)) return null;
  return regions;
}

function tokenRegions(was: string, now: string): Region[] {
  const wasTokens = tokenize(was);
  const nowTokens = tokenize(now);
  const wasOffsets = offsets(wasTokens);
  const nowOffsets = offsets(nowTokens);
  const matcher = new SequenceMatcher(isWhitespaceToken, wasTokens, nowTokens);
  const out: Region[] = [];
  for (const [op, i1, i2, j1, j2] of matcher.getOpcodes()) {
    if (op !== "equal") out.push([wasOffsets[i1], wasOffsets[i2], nowOffsets[j1], nowOffsets[j2]]);
  }
  return out;
}

function emitRuns(regions: Region[], was: string, now: string): DiffRun[] {
  const runs: DiffRun[] = [];
  let wasCursor = 0;
  for (const [wasStart, wasEnd, nowStart, nowEnd] of regions) {
    if (wasStart > wasCursor) runs.push(run("equal", was.slice(wasCursor, wasStart)));
    if (wasEnd > wasStart) runs.push(run("was", was.slice(wasStart, wasEnd)));
    if (nowEnd > nowStart) runs.push(run("now", now.slice(nowStart, nowEnd)));
    wasCursor = wasEnd;
  }
  if (wasCursor < was.length) runs.push(run("equal", was.slice(wasCursor)));
  return runs.filter((r) => r.text);
}

function reassembles(runs: DiffRun[], was: string, now: string): boolean {
  return (
    runs
      .filter((r) => r.kind !== "now")
      .map((r) => r.text)
      .join("") === was &&
    runs
      .filter((r) => r.kind !== "was")
      .map((r) => r.text)
      .join("") === now
  );
}

function stackedPair(was: string, now: string): DiffRun[] {
  return [run("was", was, true), run("now", now, true)];
}

function needsStacking(regions: Region[], was: string, now: string): boolean {
  return regions.some(
    (region) =>
      (region[0] === 0 && firstLineIsStructural(was)) ||
      (region[2] === 0 && firstLineIsStructural(now)) ||
      escapesContainer(was, region[0], region[1]) ||
      escapesContainer(now, region[2], region[3]),
  );
}

function offsets(tokens: string[]): number[] {
  const out = [0];
  for (const token of tokens) out.push(out[out.length - 1] + token.length);
  return out;
}

function snap(position: number, intervals: Interval[], left: boolean): number {
  for (const [start, end] of intervals) {
    if (start < position && position < end) return left ? start : end;
  }
  return position;
}

function expandOutOfConstructs(regions: Region[], wasIntervals: Interval[], nowIntervals: Interval[]): Region[] {
  let changed = true;
  while (changed) {
    changed = false;
    const grown: Region[] = [];
    for (const region of regions) {
      const [wasStart, wasEnd, nowStart, nowEnd] = region;
      const wider: Region = [
        snap(wasStart, wasIntervals, true),
        snap(wasEnd, wasIntervals, false),
        snap(nowStart, nowIntervals, true),
        snap(nowEnd, nowIntervals, false),
      ];
      if (wider[0] !== region[0] || wider[1] !== region[1] || wider[2] !== region[2] || wider[3] !== region[3])
        changed = true;
      const last = grown[grown.length - 1];
      if (grown.length && (wider[0] <= last[1] || wider[2] <= last[3])) {
        grown[grown.length - 1] = [last[0], Math.max(last[1], wider[1]), last[2], Math.max(last[3], wider[3])];
        changed = true;
      } else {
        grown.push(wider);
      }
    }
    regions = grown;
  }
  return regions;
}

function settle(
  regions: Region[],
  was: string,
  now: string,
  wasIntervals: Interval[],
  nowIntervals: Interval[],
): Region[] | null {
  for (let pass = 0; pass < SETTLE_PASSES; pass++) {
    regions = expandOutOfConstructs(regions, wasIntervals, nowIntervals);
    const aligned: Region[] = [];
    let wasCursor = 0;
    let nowCursor = 0;
    let changed = false;
    for (const region of regions) {
      let [wasStart, , nowStart] = region;
      const [, wasEnd, , nowEnd] = region;
      const common = commonPrefix(was.slice(wasCursor, wasStart), now.slice(nowCursor, nowStart));
      if (wasCursor + common !== wasStart || nowCursor + common !== nowStart) {
        wasStart = wasCursor + common;
        nowStart = nowCursor + common;
        changed = true;
      }
      aligned.push([wasStart, wasEnd, nowStart, nowEnd]);
      wasCursor = wasEnd;
      nowCursor = nowEnd;
    }
    if (aligned.length && was.slice(wasCursor) !== now.slice(nowCursor)) {
      const common = commonSuffix(was.slice(wasCursor), now.slice(nowCursor));
      const last = aligned[aligned.length - 1];
      aligned[aligned.length - 1] = [last[0], was.length - common, last[2], now.length - common];
      changed = true;
    }
    regions = mergeTouching(aligned);
    if (!changed) return regions;
  }
  return null;
}

function commonPrefix(left: string, right: string): number {
  const limit = Math.min(left.length, right.length);
  let index = 0;
  while (index < limit && left[index] === right[index]) index++;
  return index;
}
function commonSuffix(left: string, right: string): number {
  const limit = Math.min(left.length, right.length);
  let index = 0;
  while (index < limit && left[left.length - 1 - index] === right[right.length - 1 - index]) index++;
  return index;
}
function mergeTouching(regions: Region[]): Region[] {
  const merged: Region[] = [];
  for (const region of regions) {
    const last = merged[merged.length - 1];
    if (merged.length && (region[0] <= last[1] || region[2] <= last[3])) {
      merged[merged.length - 1] = [last[0], Math.max(last[1], region[1]), last[2], Math.max(last[3], region[3])];
    } else {
      merged.push([...region] as Region);
    }
  }
  return merged;
}

function coalesce(runs: DiffRun[]): DiffRun[] {
  const out: DiffRun[] = [];
  for (const r of runs) {
    if (!r.text) continue;
    const last = out[out.length - 1];
    if (out.length && last.kind === r.kind && last.stacked === r.stacked) last.text += r.text;
    else out.push({ ...r });
  }
  return out;
}
