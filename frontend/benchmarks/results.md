# Matcher benchmark results

Run: 2026-06-20, Chrome (via Vite dev server), Windows 11.
Source: open `/benchmarks/matcher.html` in browser, click "Run benchmark", click "Download results.md".

Comparing **regex-OR** vs **Aho-Corasick** for the implicit-context matcher.
Times are median across samples. Window scans are batch-timed (2000 calls
per sample, 10 samples) to overcome the 100µs `performance.now()` resolution;
reported time is per-call. Heap deltas are `performance.memory` estimates and
frequently read as zero — treat as unreliable on this run; profile in DevTools
if memory becomes a concern.

Both implementations have identical word-boundary semantics (apostrophe is
word-extending so "Bob" doesn't match in "Bob's"). Agreement verified at
5000 patterns × 50KB text — both find the same 147 hits at the same positions.

## Compile + memory

| Patterns | Flat (with aliases) | Regex compile | AC compile | Regex heap | AC heap |
|---:|---:|---:|---:|---:|---:|
| 100 | 247 | 0.100ms | 0.300ms | 0B | 0B |
| 1000 | 2418 | 0.500ms | 0.600ms | 0B | 0B |
| 5000 | 12283 | 2.10ms | 4.90ms | 0B | 0B |
| 10000 | 24665 | 4.30ms | 7.90ms | 0B | -71668B |

Regex-OR compile is roughly 2× faster than AC, but both finish in single-digit
milliseconds even at 10k patterns. Compile fires only on entity-set change,
not per keystroke — both are fine.

## Full-text scan

Fires on document open or paste. Acceptable threshold: <50ms.

| Patterns | Text | Hits | Regex | AC | Ratio (AC/Regex) |
|---:|---:|---:|---:|---:|---:|
| 100 | 50KB | 147 | 0.300ms | 1.20ms | 4.00x |
| 100 | 500KB | 1474 | 2.80ms | 8.30ms | 2.96x |
| 1000 | 50KB | 147 | 0.500ms | 1.30ms | 2.60x |
| 1000 | 500KB | 1476 | 4.70ms | 13.1ms | 2.79x |
| 5000 | 50KB | 147 | 0.500ms | 1.30ms | 2.60x |
| 5000 | 500KB | 1473 | 5.00ms | 13.9ms | 2.78x |
| 10000 | 50KB | 146 | 0.500ms | 1.70ms | 3.40x |
| 10000 | 500KB | 1469 | 5.20ms | 17.6ms | 3.38x |

Regex-OR is **2.6–4×** faster across the board. Worst case (10k patterns,
500KB text) is 5.2ms — well under threshold.

## Per-keystroke window scan

The scenario that determines feel. We rescan a window of `maxPatternLen + editSize`
characters around the cursor on each keystroke. Acceptable threshold: <1ms.

| Patterns | Text | Window | Regex | AC | Ratio (AC/Regex) |
|---:|---:|---:|---:|---:|---:|
| 5000 | 50KB | 50ch | 0.0005ms | 0.0013ms | 2.70x |
| 5000 | 50KB | 200ch | 0.0018ms | 0.0053ms | 2.92x |
| 5000 | 50KB | 2000ch | 0.018ms | 0.053ms | 2.93x |
| 5000 | 500KB | 50ch | 0.0005ms | 0.0012ms | 2.45x |
| 5000 | 500KB | 200ch | 0.0018ms | 0.0050ms | 2.74x |
| 5000 | 500KB | 2000ch | 0.019ms | 0.052ms | 2.79x |
| 10000 | 50KB | 50ch | 0.0005ms | 0.0017ms | 3.67x |
| 10000 | 50KB | 200ch | 0.0018ms | 0.0066ms | 3.64x |
| 10000 | 50KB | 2000ch | 0.019ms | 0.068ms | 3.59x |
| 10000 | 500KB | 50ch | 0.0005ms | 0.0018ms | 3.50x |
| 10000 | 500KB | 200ch | 0.0019ms | 0.0068ms | 3.59x |
| 10000 | 500KB | 2000ch | 0.019ms | 0.068ms | 3.64x |

(Full table — including 100 and 1000 pattern rows — in the on-page report
when you re-run.)

Both implementations are **far** below the 1ms threshold. Even pasting a
2000-char paragraph into a 500KB document with 10k patterns is sub-100µs
for regex-OR.

## Decision

Reference scenario: 5000 patterns (Honorverse-scale), 200ch window (a typed
sentence triggering a rescan back to the start of the longest pattern), 50KB
text (a long scene body).

- **regex-OR: 0.0018ms** per keystroke (1.8µs)
- **AC:       0.0053ms** per keystroke (5.3µs)

**Verdict: regex-OR wins.** Three reasons:

1. **3× faster on the per-keystroke path**, and absolute numbers are
   microseconds — both implementations are imperceptible, but regex-OR
   leaves more headroom for other per-keystroke work (decoration patching,
   any future linting, etc.).
2. **Matches the backend.** [helpers.py:587 `_alias_match`](../../backend/app/services/ai/helpers.py:587)
   is regex-OR. Frontend matcher reuses the same shape — no two-implementation
   maintenance burden.
3. **Less code.** Regex matcher is ~30 LOC; AC is ~120. Smaller surface,
   nothing custom to debug.

The AC win on theoretical complexity (O(n) regardless of pattern count) does
not materialize in practice at our scale — V8's compiled regex engine plus
the trie-fused alternation gives regex-OR a constant-factor advantage that
swamps the asymptotic difference up to 10k patterns. Honorverse-scale is
~5k patterns; we have a 5x headroom before crossing that scale.

**Re-evaluate AC** only if:
- A project crosses ~50k patterns (5x our worst-case), or
- Per-keystroke window scan ever measures > 1ms in real usage.

## How to re-run

```
cd frontend && npm run dev
# open http://127.0.0.1:5173/benchmarks/matcher.html
# click "Run benchmark" (~3 minutes)
# click "Download results.md"
```
