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
 * This module computes the two client-side halves of the compare view: `runs`
 * (the prose diff, above) and `fieldDiffs` (the atomic field flip, below). Drift
 * is the third half and stays on the server — building the "now" witness needs
 * resolved entity state the client does not have (#583); see `PORT-SCOPE.md` in
 * the #573 spike.
 */
import type { DiffRun, FieldDiff } from "@/lib/types";
import { SequenceMatcher } from "@/lib/utils/sequenceMatcher";
import { alignSequences, isWhitespaceToken, tokenize, MAX_WORD_DIFF_TOKENS } from "@/lib/utils/sequenceAlign";

type Interval = [number, number];
type Region = [number, number, number, number]; // was_start, was_end, now_start, now_end

const run = (kind: DiffRun["kind"], text: string, stacked = false): DiffRun => ({ kind, text, stacked });

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
const SETTLE_PASSES = 12;

/** Provenance-tagged runs over two markdown bodies, oldest state first. Built
 *  on `alignSequences` (ADR-0096 §3, S2): phase 1's equal/insert/delete ops
 *  become runs directly; a `replace` span's `rewrite` pairs go through
 *  `blockRuns` (the body's own scalar-region diff) and its `unpaired` pairs
 *  stack, exactly as `alignBlocks` did before the extraction. */
export function diffRuns(was: string, now: string): DiffRun[] {
  const wasBlocks = was.split(BLOCK_SPLIT);
  const nowBlocks = now.split(BLOCK_SPLIT);
  const runs: DiffRun[] = [];
  for (const op of alignSequences(wasBlocks, nowBlocks)) {
    if (op.op === "equal") runs.push(run("equal", wasBlocks.slice(op.wasStart, op.wasEnd).join("")));
    else if (op.op === "insert") runs.push(run("now", nowBlocks.slice(op.nowStart, op.nowEnd).join(""), true));
    else if (op.op === "delete") runs.push(run("was", wasBlocks.slice(op.wasStart, op.wasEnd).join(""), true));
    else if (op.op === "rewrite") runs.push(...blockRuns(wasBlocks[op.was], nowBlocks[op.now]));
    else runs.push(...stackedPair(wasBlocks[op.was], nowBlocks[op.now]));
  }
  return coalesce(runs);
}

function tooLargeToDiff(...blocks: string[]): boolean {
  return blocks.some((b) => tokenize(b).length > MAX_WORD_DIFF_TOKENS);
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

// ===========================================================================
// _field_diffs + same_rendered_value  (the field flip — ADR-0044 §F, #583)
// ===========================================================================
//
// The atomic side of the compare view. A field value resolves in one blink, so
// §F flips it rather than interleaving — the client needs only the pair. This is
// a faithful port of the backend `_field_diffs` (`snapshot_diff.py`) and
// `same_rendered_value` (`field_values.py`), gated at parity against the Python
// golden by `fieldDiffs.test.ts` / `fieldDiffs.fixtures.json`.
//
// **Value equality follows JS**, where the backend leans on Python `==`: `===`
// for scalars, a structural walk for arrays/objects. The two agree on every
// JSON-shaped field value — the only equality Python has and JS lacks is
// `True == 1` / `False == 0`, and a field carries one type, so a boolean is
// never compared against a number.

// `id` is identity and never flips; `title` and `schema_version` are the file's
// own bookkeeping, not authored fields. Mirrors `NON_FIELD_KEYS`.
const NON_FIELD_KEYS = new Set(["id", "title", "schema_version"]);

function isBlank(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value as object).length === 0;
  return false;
}

function valuesEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, index) => valuesEqual(item, b[index]));
  }
  if (a && b && typeof a === "object" && typeof b === "object") {
    const aKeys = Object.keys(a as object);
    const bKeys = Object.keys(b as object);
    return (
      aKeys.length === bKeys.length &&
      aKeys.every((key) =>
        valuesEqual((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key]),
      )
    );
  }
  return false;
}

/** Whether two field values are the same *as the rail renders them*. A missing
 *  key and an empty one are the same absence to a reader — the row reads
 *  "(none)" either way — so they must not flip (`same_rendered_value`). */
export function sameRenderedValue(was: unknown, now: unknown): boolean {
  const wasBlank = isBlank(was);
  const nowBlank = isBlank(now);
  if (wasBlank || nowBlank) return wasBlank && nowBlank;
  return valuesEqual(was, now);
}

/** Every field whose value differs between the frozen snapshot and the live
 *  buffer, both sides carried — the atomic flip (§F).
 *
 *  `status` travels beside the metadata because that is where the scene file
 *  keeps it (top-level, not in the field map) while the rail renders it as one
 *  row among the fields. The frontend always holds both statuses, so unlike the
 *  backend request (where `status: None` meant "not sent") it is always compared. */
export function fieldDiffs(
  wasMetadata: Record<string, unknown>,
  wasStatus: string,
  nowMetadata: Record<string, unknown>,
  nowStatus: string,
): Record<string, FieldDiff> {
  const was: Record<string, unknown> = { ...wasMetadata, status: wasStatus };
  const now: Record<string, unknown> = { ...nowMetadata, status: nowStatus };
  const keys = new Set<string>();
  for (const key of [...Object.keys(was), ...Object.keys(now)]) {
    if (!NON_FIELD_KEYS.has(key)) keys.add(key);
  }
  const diffs: Record<string, FieldDiff> = {};
  for (const key of [...keys].sort()) {
    const wasValue = was[key];
    const nowValue = now[key];
    if (!sameRenderedValue(wasValue, nowValue)) {
      diffs[key] = {
        was: wasValue === undefined ? null : wasValue,
        now: nowValue === undefined ? null : nowValue,
      };
    }
  }
  return diffs;
}

/** One list item's diff state, for a field whose value is (or was) an array —
 *  ADR-0044's one-colour rule: the tint says which version a bit of text
 *  belongs to, so an item present on both sides carries none (#2125). A
 *  non-array side is treated as empty (or as a single stringified item when
 *  it's a non-empty scalar), so a field that changed shape still diffs
 *  sensibly. Items compare by `text` (`String(x)` / the joined-member
 *  reading) — the compare key, unaffected by `itemLabel` — the order is
 *  every `was` item first (in its own order), then every `now`-only item (in
 *  its own order).
 *
 *  `itemLabel` (ADR-0091 §7, #2133) lets a caller resolve a reference item to
 *  its title for DISPLAY only: `label` defaults to `text` when omitted, so two
 *  ids sharing one title still stay two distinct pills (the compare key is
 *  never the label). */
export function listDiff(
  was: unknown,
  now: unknown,
  itemLabel?: (item: unknown) => string,
): { state: "same" | "was" | "now"; text: string; label: string }[] | null {
  if (!Array.isArray(was) && !Array.isArray(now)) return null;
  const toItems = (value: unknown): unknown[] => {
    if (Array.isArray(value)) return value;
    if (value === null || value === undefined || value === "") return [];
    return [value];
  };
  const labelOf = (item: unknown): string => (itemLabel ? itemLabel(item) : listItemText(item));
  const wasItems = toItems(was);
  const nowItems = toItems(now);
  // Multiset, not set: a duplicated item removed (or added) is a change too —
  // counted by TEXT, never by label, so label resolution can't merge or split
  // what the compare key says are duplicates.
  const nowCounts = new Map<string, number>();
  for (const item of nowItems) {
    const text = listItemText(item);
    nowCounts.set(text, (nowCounts.get(text) ?? 0) + 1);
  }
  const out: { state: "same" | "was" | "now"; text: string; label: string }[] = [];
  for (const item of wasItems) {
    const text = listItemText(item);
    const left = nowCounts.get(text) ?? 0;
    if (left > 0) {
      nowCounts.set(text, left - 1);
      out.push({ state: "same", text, label: labelOf(item) });
    } else {
      out.push({ state: "was", text, label: labelOf(item) });
    }
  }
  for (const item of nowItems) {
    const text = listItemText(item);
    const left = nowCounts.get(text) ?? 0;
    if (left > 0) {
      nowCounts.set(text, left - 1);
      out.push({ state: "now", text, label: labelOf(item) });
    }
  }
  return out;
}

/** One list item as the text a pill shows and compares by. A scalar is its
 *  string; a record item (an ADR-0089 group item — a relationship with its
 *  key reference and members) is its non-empty member values joined with
 *  " · ", the same reading the search corpus gives such an item, never
 *  "[object Object]". */
export function listItemText(item: unknown): string {
  if (item !== null && typeof item === "object" && !Array.isArray(item)) {
    return Object.values(item as Record<string, unknown>)
      .filter((member) => member !== null && member !== undefined && member !== "")
      .map(String)
      .join(" · ");
  }
  return String(item);
}
