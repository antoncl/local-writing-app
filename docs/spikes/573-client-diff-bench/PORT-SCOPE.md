# #573 → client-side diff: port scope

The benchmark (see `RESULTS.md`) settled the *whether*: client-side compute is faithful
(parity 426/426) and 4–6.8× faster than CPython, sub-few-ms on any realistic scene. This
scopes the *how* — what moves, what the API becomes, and the decisions #573 still owns.
It deliberately scopes, it does not decide.

## What already exists (so the port is small)

- **Backend compute** — `snapshot_diff.py`: `diff_runs` (the prose runs, the superlinear part),
  `_field_diffs` (trivial, atomic `FieldDiff` pairs), and drift via `compare_witnesses` +
  `build_witness` (needs resolved entity state — backend-only).
- **Endpoint** — `POST /api/scenes/{id}/snapshots/{sid}/diff` → `SnapshotDiff {runs, fields,
  title_was, title_now, drift}`.
- **Client already owns the render + adopt half** — `frontend/src/lib/utils/diffRuns.ts`
  (`DiffRun` type, `groupRuns`, `renderDiffRuns`, `adoptRegion`) and
  `snapshotStrip.svelte.ts` (`park()` → `api.diffSnapshot` → render; `adopt` → buffer).
- **A body-returning read already exists** — `GET .../snapshots/{sid}` → `SnapshotDetail`
  (carries `body`). So the client can obtain the snapshot side **without** the server diffing;
  the live side it already holds in the buffer. **No new endpoint is needed to feed a client
  diff.**
- **The faithful port** — `snapshotDiff.ts` in this folder *is* the compute, ready to
  productionize.

## Target shape

- A frontend `diffCompute.ts` (productionized port) beside `diffRuns.ts` — compute and render
  living together: `diffRuns(was, now): DiffRun[]` and (optionally) `fieldDiffs(...):
  Record<string, FieldDiff>`.
- **Snapshot compare**: `park()` reads `SnapshotDetail.body` (existing endpoint) + the live
  buffer, computes runs client-side, renders. No `.../diff` call for runs.
- **AI lore editing (ADR-0046)**: computes proposed-vs-current runs and field-flips with the
  *same* util — pure client, zero server. It needs no drift, so its path is fully local
  regardless of the decisions below.

## Decisions #573 owns (scoped, not decided)

1. **Runs only, or runs + fields, client-side?** Runs carry all the cost → the clear win to
   move. Fields are trivial but need the snapshot's *normalised* metadata delivered to the
   client (`SnapshotDetail` carries `body`/`title` today, not metadata/status) — so moving
   fields means either extending `SnapshotDetail` or leaving `_field_diffs` server-side.
2. **Drift stays server** (witness building needs resolved entity state; not cheap to move).
   So the `.../diff` endpoint either (a) slims to a `.../drift` returning only `SnapshotDrift`,
   fetched on park, or (b) stays but stops computing runs. Either way AI editing bypasses it.
3. **Touch shipped 0.8.0 snapshot code, or forward-only?**
   - *Full* (recommended for the #573 goal): snapshot compare switches to client compute; the
     endpoint serves only drift (+ maybe fields). One shared mechanism — but edits shipped code.
   - *Forward-only*: leave snapshot as-is, build client compute for AI editing only. Two diff
     paths until a later unification — which undercuts #573's "one mechanism" point.

## Productionizing the port

- **Offsets → code-point / grapheme-aware** (the port uses UTF-16 units; §Caveats in
  `RESULTS.md`). Must fix before production so an emoji in prose cannot corrupt a run boundary,
  or guard BMP explicitly.
- **Types**: reuse the client's existing `DiffRun`; add a `FieldDiff` type mirroring the API
  model if fields move.
- Port `_field_diffs` + `same_rendered_value` only if fields move client.
- **Delete nothing on the backend** until the client path is proven at parity in a real browser.

## Test surface

- **Vitest parity gate vs the Python golden**: `gen_corpus.py` already emits `(was, now, runs)`;
  a vitest asserts the client port reproduces them exactly — the cross-language regression guard,
  exactly what `bench.ts` does now, run in CI.
- **Property tests over the `diff_fuzz` corpus**: runs reassemble to `was`/`now`; runs survive
  the *real* `sceneMarkdownToHtml` well-formed with no leaked syntax (the original #396 concern,
  answerable only on the frontend); the four named regressions from the fuzzer.
- Cross-browser correctness is engine-independent for BMP; timing is sub-ms everywhere, so a
  smoke check is optional.

## Sequencing (slices)

1. **`diffCompute.ts`** — productionize the port (code-point offsets, client types) behind a
   vitest parity gate vs the Python golden.
2. **Snapshot compare on client compute** — `park()` computes runs from `SnapshotDetail`; slim
   or split the endpoint per decision 2. Verify in-browser against shipped behaviour.
3. **ADR-0046** — AI lore editing consumes the same util for proposed-vs-current (no server).
4. *(optional)* move field diffs client; retire server run-compute.

## Risks

- **SequenceMatcher port correctness** — mitigated: parity 426/426 now, and the vitest golden
  gate keeps it.
- **Astral-char offset corruption** — fixed in slice 1.
- **Drift coupling** — left server-side by design; the AI path never touches it.
