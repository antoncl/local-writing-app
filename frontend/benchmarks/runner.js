// Benchmark runner. Sweeps pattern count × text size × window size,
// timing both matchers. Writes results to the page and to a markdown
// blob the user can download or copy into results.md.

import { generatePatterns, flattenPatterns, generateText, randomWindow, mulberry32 } from './synthetic.js';
import { RegexMatcher } from './regex-matcher.js';
import { AhoCorasickMatcher } from './ac-matcher.js';

const PATTERN_COUNTS = [100, 1000, 5000, 10000];
const TEXT_SIZES = [1024, 50 * 1024, 500 * 1024]; // 1KB, 50KB, 500KB
const WINDOW_SIZES = [50, 200, 2000];

const WINDOW_BATCH = 2000;     // calls per timing sample
const WINDOW_SAMPLES = 10;     // samples per window-size scenario
const FULL_SCAN_ITERATIONS = 5;
const COMPILE_ITERATIONS = 3;

function median(arr) {
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function timeIt(fn, iterations) {
  // Warm-up
  fn();
  const samples = [];
  for (let i = 0; i < iterations; i++) {
    const t0 = performance.now();
    fn();
    samples.push(performance.now() - t0);
  }
  return median(samples);
}

// Batch-timed variant. Browser performance.now() typically has 100µs
// resolution (and as coarse as 1ms with cross-origin isolation), so any
// individual call faster than the resolution times as zero. Batch N
// invocations per sample and divide. Returns per-call time.
function timeBatched(fn, batch, samples) {
  // Warm-up
  for (let i = 0; i < batch; i++) fn(i);
  const times = [];
  for (let s = 0; s < samples; s++) {
    const t0 = performance.now();
    for (let i = 0; i < batch; i++) fn(i);
    times.push((performance.now() - t0) / batch);
  }
  return median(times);
}

function heapBytes() {
  // performance.memory is Chrome-only and an estimate. Better than nothing.
  return performance.memory ? performance.memory.usedJSHeapSize : null;
}

function fmtMs(ms) {
  if (ms < 0.01) return ms.toFixed(4);
  if (ms < 1) return ms.toFixed(3);
  if (ms < 10) return ms.toFixed(2);
  return ms.toFixed(1);
}

function fmtBytes(b) {
  if (b == null) return 'n/a';
  if (b < 1024) return b + 'B';
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + 'KB';
  return (b / (1024 * 1024)).toFixed(2) + 'MB';
}

function fmtSize(n) {
  if (n < 1024) return n + 'B';
  if (n < 1024 * 1024) return (n / 1024) + 'KB';
  return (n / (1024 * 1024)) + 'MB';
}

export async function runBenchmark(onProgress) {
  const log = (s) => onProgress && onProgress(s);
  const rng = mulberry32(42);
  const results = [];

  for (const patternCount of PATTERN_COUNTS) {
    log(`\n=== ${patternCount} patterns ===`);
    const rawPatterns = generatePatterns(patternCount, 7);
    const flat = flattenPatterns(rawPatterns);
    log(`  ${rawPatterns.length} canonical + aliases = ${flat.length} total patterns`);

    // Compile
    const heap0 = heapBytes();
    const compileRegexMs = timeIt(() => new RegexMatcher(flat), COMPILE_ITERATIONS);
    const heapAfterRegex = heapBytes();
    const compileAcMs = timeIt(() => new AhoCorasickMatcher(flat), COMPILE_ITERATIONS);
    const heapAfterAc = heapBytes();

    log(`  compile regex=${fmtMs(compileRegexMs)}ms ac=${fmtMs(compileAcMs)}ms`);

    const regexMatcher = new RegexMatcher(flat);
    const acMatcher = new AhoCorasickMatcher(flat);

    // Sanity: agreement check on a small text
    const sanityText = generateText(rawPatterns, 4096, 99);
    const regexHits = regexMatcher.scan(sanityText);
    const acHits = acMatcher.scan(sanityText);
    const regexIds = new Set(regexHits.map(h => `${h.start}:${h.end}:${h.id}`));
    const acIds = new Set(acHits.map(h => `${h.start}:${h.end}:${h.id}`));
    const onlyRegex = [...regexIds].filter(x => !acIds.has(x)).length;
    const onlyAc = [...acIds].filter(x => !regexIds.has(x)).length;
    log(`  sanity: regex=${regexHits.length} ac=${acHits.length} agreement-mismatch onlyR=${onlyRegex} onlyA=${onlyAc}`);

    for (const textSize of TEXT_SIZES) {
      const text = generateText(rawPatterns, textSize, 13);
      log(`  text ${fmtSize(textSize)} (actual ${text.length}ch)`);

      // Full-text scan
      const fullRegexMs = timeIt(() => regexMatcher.scan(text), FULL_SCAN_ITERATIONS);
      const fullAcMs = timeIt(() => acMatcher.scan(text), FULL_SCAN_ITERATIONS);
      const fullRegexHits = regexMatcher.scan(text).length;
      log(`    full-scan: regex=${fmtMs(fullRegexMs)}ms ac=${fmtMs(fullAcMs)}ms (${fullRegexHits} hits)`);

      results.push({
        patternCount,
        flatPatterns: flat.length,
        textSize,
        actualTextLen: text.length,
        scenario: 'full-scan',
        regexMs: fullRegexMs,
        acMs: fullAcMs,
        hits: fullRegexHits,
      });

      // Per-keystroke window scan — batched timing because individual
      // calls are below performance.now() resolution.
      for (const windowSize of WINDOW_SIZES) {
        const windows = [];
        const windowCount = Math.min(WINDOW_BATCH, 500);
        for (let i = 0; i < windowCount; i++) {
          windows.push(randomWindow(text, windowSize, rng).text);
        }
        const winRegexMs = timeBatched(
          (i) => regexMatcher.scan(windows[i % windows.length]),
          WINDOW_BATCH,
          WINDOW_SAMPLES,
        );
        const winAcMs = timeBatched(
          (i) => acMatcher.scan(windows[i % windows.length]),
          WINDOW_BATCH,
          WINDOW_SAMPLES,
        );

        log(`    window ${windowSize}ch: regex=${fmtMs(winRegexMs)}ms ac=${fmtMs(winAcMs)}ms`);

        results.push({
          patternCount,
          flatPatterns: flat.length,
          textSize,
          actualTextLen: text.length,
          windowSize,
          scenario: 'window-scan',
          regexMs: winRegexMs,
          acMs: winAcMs,
          hits: null,
        });
      }
    }

    // Record compile + memory rows
    results.push({
      patternCount,
      flatPatterns: flat.length,
      scenario: 'compile',
      regexMs: compileRegexMs,
      acMs: compileAcMs,
      regexHeap: heap0 != null ? heapAfterRegex - heap0 : null,
      acHeap: heap0 != null ? heapAfterAc - heapAfterRegex : null,
    });
  }

  return results;
}

export function resultsToMarkdown(results) {
  const lines = [];
  lines.push('# Matcher benchmark results\n');
  lines.push('Comparing regex-OR vs Aho-Corasick at varied scale.');
  lines.push('Times are median across samples. Window scans are batch-timed');
  lines.push('(2000 calls per sample, 10 samples) to overcome the 100µs');
  lines.push('`performance.now()` resolution; reported time is per-call.');
  lines.push('Heap deltas are `performance.memory` estimates and frequently');
  lines.push('read as zero — treat as unreliable.\n');
  lines.push('## Compile + memory\n');
  lines.push('| Patterns | Flat | Regex compile | AC compile | Regex heap | AC heap |');
  lines.push('|---:|---:|---:|---:|---:|---:|');
  for (const r of results.filter(x => x.scenario === 'compile')) {
    lines.push(`| ${r.patternCount} | ${r.flatPatterns} | ${fmtMs(r.regexMs)}ms | ${fmtMs(r.acMs)}ms | ${fmtBytes(r.regexHeap)} | ${fmtBytes(r.acHeap)} |`);
  }

  lines.push('\n## Full-text scan\n');
  lines.push('| Patterns | Text | Hits | Regex | AC | Ratio (AC/Regex) |');
  lines.push('|---:|---:|---:|---:|---:|---:|');
  for (const r of results.filter(x => x.scenario === 'full-scan')) {
    const ratio = r.regexMs > 0 ? (r.acMs / r.regexMs).toFixed(2) : 'n/a';
    lines.push(`| ${r.patternCount} | ${fmtSize(r.textSize)} | ${r.hits} | ${fmtMs(r.regexMs)}ms | ${fmtMs(r.acMs)}ms | ${ratio}x |`);
  }

  lines.push('\n## Per-keystroke window scan (median over 200 windows)\n');
  lines.push('| Patterns | Text | Window | Regex | AC | Ratio (AC/Regex) |');
  lines.push('|---:|---:|---:|---:|---:|---:|');
  for (const r of results.filter(x => x.scenario === 'window-scan')) {
    const ratio = r.regexMs > 0 ? (r.acMs / r.regexMs).toFixed(2) : 'n/a';
    lines.push(`| ${r.patternCount} | ${fmtSize(r.textSize)} | ${r.windowSize}ch | ${fmtMs(r.regexMs)}ms | ${fmtMs(r.acMs)}ms | ${ratio}x |`);
  }

  // Decision section — pull the per-keystroke window scan at 5000 patterns
  // (typical Honorverse-scale), 200ch window (a paragraph), 50KB text
  // (a long scene).
  const decisionRow = results.find(r =>
    r.scenario === 'window-scan' && r.patternCount === 5000 && r.windowSize === 200 && r.textSize === 50 * 1024
  );
  lines.push('\n## Decision\n');
  if (decisionRow) {
    const r = decisionRow;
    lines.push(`Reference scenario: 5000 patterns, 200ch window (paragraph), 50KB text (scene).`);
    lines.push(`- regex-OR: **${fmtMs(r.regexMs)}ms** per keystroke`);
    lines.push(`- AC:       **${fmtMs(r.acMs)}ms** per keystroke`);
    let verdict;
    if (r.regexMs < 1.0) {
      verdict = 'Regex-OR wins — sub-1ms per keystroke. Ship it; matches backend.';
    } else if (r.regexMs > 5.0) {
      verdict = 'Regex-OR exceeds 5ms — switch to AC.';
    } else if (r.acMs < r.regexMs * 0.5) {
      verdict = 'Borderline — AC is materially faster. Switch to AC.';
    } else {
      verdict = 'Borderline — regex-OR acceptable. Stay simple.';
    }
    lines.push(`\n**Verdict:** ${verdict}\n`);
  } else {
    lines.push('Reference row not found.');
  }

  return lines.join('\n');
}
