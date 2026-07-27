# #573 spike — is server-side diffing a premature optimization? Benchmark

**Question.** The snapshot compare diff is computed server-side (`snapshot_diff.py`,
`difflib.SequenceMatcher`). #573 argues that was premature optimization and it belongs
client-side. Before committing to that, measure the actual performance cost of moving the
computation into the browser.

**Answer.** There is no cost. A faithful TypeScript port of the whole engine runs **4–6.8×
faster than CPython** on every input class, and even the largest realistic scene diffs in
**~1.3 ms** — on the main thread, before counting the network round-trip the server path
also pays. Moving the diff client-side is a performance *win*, not a hit.

## What was ported

A from-scratch, faithful TS port (`snapshotDiff.ts`) of:

- `backend/app/services/project/snapshot_diff.py` — the full pipeline (`diff_runs`,
  `_align_blocks`, `_block_runs`, `_changed_regions`, `_settle`, …);
- `backend/app/services/markdown_scan.py` — the construct scanner (`protected_intervals`
  and the seven inline handlers, `is_code_block`, `escapes_container`, …);
- **Python's `difflib.SequenceMatcher`**, ported from CPython including `isjunk` handling
  and `find_longest_match` / `get_opcodes` / `ratio` / `quick_ratio` (`autojunk=False`, as
  the backend uses it).

Not ported: `_field_diffs` (an O(fields) dict comparison — trivially portable and not a
perf factor) and drift (backend-only, needs the stored witness).

## Faithfulness

Parity is the whole point — a fast port of a *different* algorithm measures nothing. The
Python engine and the TS port were run over the same 426-case corpus and their runs
compared exactly (`kind`, `text`, `stacked`):

```
PARITY: 426/426 cases match Python exactly  ✓
```

## Method

- **Corpus** (`gen_corpus.py`, seeded, deterministic): the 400-case markdown fuzzer that
  already guards the backend diff (`backend/tests/diff_fuzz.py` — prose seeded with
  emphasis, links, code spans, markers, blockquotes, lists, tables + a plausible edit),
  plus synthetic full scenes at ~500 / ~1500 / ~4000 words with realistic edits (a few
  word changes across paragraphs, an inserted paragraph, an occasional full rewrite), plus
  a `worst-para` stress case (one ~1500-token paragraph with every third word replaced).
- **Timing**: per bucket, warm up once (JIT / caches), then loop the whole bucket for ≥1.5 s
  and ≥3 iterations; report mean ms per `diff_runs` call. Python via `time.perf_counter`;
  TS via `process.hrtime.bigint()`.
- **Environment**: same machine (Windows 11). TS on Node v24.14.1 — the V8 that ships in
  Chromium, so representative of the browser. Python is the backend venv's CPython.
- **Reproduce**:
  ```bash
  PYTHONPATH=<worktree>/backend <primary-venv>/python.exe \
      docs/spikes/573-client-diff-bench/gen_corpus.py /tmp/corpus.json
  node docs/spikes/573-client-diff-bench/bench.ts /tmp/corpus.json
  ```

## Results (mean ms per diff, two representative runs)

| bucket      |   n | avg words | py ms/call | ts ms/call | TS speedup |
|-------------|----:|----------:|-----------:|-----------:|-----------:|
| fuzz        | 400 |        37 |     0.3297 |    ~0.056  |     ~5.9×  |
| scene-500   |   8 |       510 |     3.4907 |    ~0.65   |     ~5.4×  |
| scene-1500  |   8 |      1530 |     3.3748 |    ~0.84   |     ~4.0×  |
| scene-4000  |   6 |      4079 |     5.3228 |    ~1.29   |     ~4.1×  |
| worst-para  |   4 |      1500 |     1.2133 |    ~0.18   |     ~6.8×  |

Stable across runs (±a few %). TS is faster on every bucket.

## Interpretation

- **The largest realistic scene diffs in ~1.3 ms client-side.** A typical edit-sized scene
  (500–1500 words) is well under 1 ms. This is imperceptible on the main thread; no web
  worker needed.
- **The comparison understates the win.** These numbers are *compute only*. The server path
  additionally pays request assembly, JSON serialization of the runs, and a network
  round-trip (the endpoint is a POST that ships the live buffer precisely because the server
  doesn't have it). The client path pays none of that.
- **Why TS wins:** V8's JIT on tight string/array loops beats interpreted CPython here; the
  work is small-integer and string comparison, exactly V8's strength.

### Caveats

- V8 == Chrome; Firefox (SpiderMonkey) and Safari (JSC) may differ but stay the same order
  of magnitude — all sub-few-ms.
- Numbers are warm (JIT settled). A cold first call is slower but still ms-scale.
- The port uses UTF-16 offsets where Python uses code points — identical for BMP text
  (all fiction prose, the entire corpus). A production client port would want code-point or
  grapheme-aware offsets to stay exact on astral characters (emoji).

## Conclusion for #573

The premature-optimization hunch is confirmed. There is no performance reason to compute the
diff on the server; the browser does it faster and without a round-trip. A client-side diff
utility emitting the same `DiffRun` / `FieldDiff` shapes would serve both snapshot compare
and AI lore editing (ADR-0046) with no server dependency. The faithful port here (parity
426/426) is most of the porting work already done.
