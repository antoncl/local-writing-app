# Prose measurement harness

Measures the built-in prose prompts (*Draft scene*, *Continue*) against an invented
book across four style notes and a no-note case. Method and thresholds:
[`docs/design/measuring-prose-quality.md`](../../../docs/design/measuring-prose-quality.md)
(ADR-0101). This folder is piece H1: the runner, the script checks, the noise band
and the parity guard; "Judge (H2)" below adds the model judge. The builder test and the
blind-pairs page come later.

It drives a worktree dev backend **over HTTP, in the frontend's own call sequence**, so
every call runs the real backend code. It never reimplements backend logic.

## Isolation

- The backend is `scripts/dev_backend.py`: a port derived from this checkout's path and a
  throwaway config directory (`LWA_CONFIG_DIR` = `tmp/claude-config`). Provider keys are
  written there, never into your real config.
- `lwa_client.discover_backend()` reads `tmp/dev-backend-port` of *this* checkout and
  **refuses** a missing file or port 8787 (your own server).
- Keys come from environment variables (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`,
  `OPENAI_API_KEY`) and are never printed or logged.
- Fixtures live under `tmp/benchmark-fixtures/prose/`, runs under
  `tmp/benchmark-runs/prose/` (both gitignored).

## Run it

Use the backend venv's Python (`<py>` below), from the repo root.

1. Start the dev backend, backgrounded, and wait for its `verified` line:

   ```powershell
   <py> scripts/dev_backend.py
   ```

2. Pick the models: copy `models.example.yaml` to `models.yaml` and edit (the harness
   reads `models.yaml` if present). The shipped entry is a local Ollama model.

3. Generate the fixture projects (two per style case, via the HTTP API; `--regen` rebuilds):
   the four briefs in `<case>`, the two Continue lead-ins in `<case>-continue`, so a lead-in
   never sees the briefs' later events in its story so far. A fixture built from an older
   `book.yaml` is refused by `run.py`: regenerate it.

   ```powershell
   <py> scripts/benchmark/prose/fixture_gen.py
   ```

4. Set the provider keys in the environment (cloud models only), then set up the backend
   (keys, project AI policy, one assistant per model):

   ```powershell
   <py> scripts/benchmark/prose/setup_backend.py
   ```

5. **Parity (once per prompt, and whenever the frontend's sequence changes).** Start this
   checkout's frontend (`npm run dev --prefix frontend -- --mode claude`), open the fixture
   project in it, and run *Draft scene* by hand on one brief with the same assistant. Leave
   the inputs blank and type `Draft the scene.` as the first message: that is what the
   harness sends (see "The opening message" below). Run the harness on that brief
   (`run.py --cases frank --models <name> --drafts 1`), then compare the two chats. The
   hand run's side is its chat id, read through the backend like the harness's own:

   ```powershell
   <py> scripts/benchmark/prose/parity.py <run>/frank/<model>/draft_scene/<brief>/meta_1.json chat_<id> --case frank
   ```

   It prints every difference and exits 1 on any. A difference fails the harness, not the
   change under test.

6. **Baseline: the A/A.** Run the unchanged baseline twice, then the band:

   ```powershell
   <py> scripts/benchmark/prose/run.py --drafts 3
   <py> scripts/benchmark/prose/run.py --drafts 3
   <py> scripts/benchmark/prose/report.py <runA>
   <py> scripts/benchmark/prose/report.py <runB>
   <py> scripts/benchmark/prose/report.py --band <runA> <runB> --out band.json
   ```

   The band is refused unless both runs have the same prompt hashes, `book.yaml` and model
   list. Each run folder holds every draft (`draft_<n>.md`), its `meta_<n>.json` (the saved
   chat record, cache blocks, usage, cost, wall time), `run.json`, and after `report.py`,
   `checks.json` and `report.md`.

7. **After a change**, rerun and compare against the baseline:

   ```powershell
   <py> scripts/benchmark/prose/run.py --drafts 3
   <py> scripts/benchmark/prose/report.py --compare <new> --baseline <runA> <runB>
   ```

A draft whose step fails (truncated, garbled, error, timeout) is recorded as `out_of_reach`
or `error` in its meta and counted in the report, never retried unless `--retries` says so.

## Judge (H2)

A model judge checks the drafts against six rules the script checks can't count, and
says which of two style notes a draft was written to follow. Its verdicts reach a report
only for the rules where it has been shown to agree with you. It never says which draft
is better.

1. Name the judges in `models.yaml` under `judges:` (`primary` and `second`; the example
   file shows the shape). The primary must be a different family from the primary drafter.
   Rerun `setup_backend.py` (`--no-judges` skips them; `--models` filters drafters only).
2. Judge a run: `judge.py <run>`. A draft written by the primary judge's model goes to
   `second`, so no model judges its own drafts. `--rules` or `--separation` runs one half;
   a rerun resumes, and `--redo` asks again. It writes `judge_<n>.json` beside each draft
   and `judge.json` in the run (the judges' model ids and cost).
3. Calibrate: `calibration.py sheet <run> --out <dir>` draws a sample and writes `sheet.md`
   and `answers.yaml`. Read the drafts and answer each rule yes (the failure is there) or
   no. Each rule needs at least 8 of each once answered; where a rule comes up short, add
   drafts rewritten to contain just that failure and mark them `seeded: true`.
4. `calibration.py tally <dir>/answers.yaml --out calibration.json` prints each rule's
   agreement per judge model. The judge owns a rule at 80% or better on the present cases
   *and* the absent ones. Change the judge model and the calibration no longer applies.
5. `report.py <run> --calibration calibration.json` (also on `--band` and `--compare`)
   adds `judge_<rule>` for the owned rules (share of drafts with the failure; a rise is
   `worse`) and `separation_correct` (a fall is `worse`: the styles got harder to tell
   apart). Unparsed or errored verdicts are never counted.

## What the harness does as a writer would

- **Inputs.** It fills in only the scene, and sends every other input the prompt declares as
  blank, exactly as the app does for a writer who leaves the form alone. The template's own
  defaults then apply (Draft scene: about 1200 words, continuing from the previous scene).
- **The opening message.** The app sends with an empty composer only when the rendered
  prompt ends in a user turn. Draft scene's doesn't, so a writer has to type something to
  start it. The harness types `Draft the scene.`, the same on every run; it is recorded in
  `run.json` and in each draft's meta.

## Reading the report

- **`worse` / `better`** appear only for failures that are failures in any style: named
  emotions, common-list phrases, markdown, a preamble, and `sample_overlap`, the longest run
  of words a draft shares with a voice sample (a draft that lifts the sample scores its
  length).
- **`changed`** marks a style-dependent mechanic (italics, numerals, dashes, contractions,
  adverbs, sentence length) that moved beyond the noise band. Whether the move is right
  depends on the case's style note: that is the judge's call (H2), not the script's.
- **`unmeasured`** marks a move where the baseline showed no variation (a band of 0, after
  taking the wider of the cell's and its group's band): there is nothing to judge it against.
- Everything is per case, model, prompt and brief, never one blended score.

## Files

| File | Role |
|---|---|
| `fixture/book.yaml` | The frozen invented book. Editing it starts a new baseline. |
| `fixture_gen.py` | Builds the five cases' projects (briefs, and Continue lead-ins) through the API. |
| `models.example.yaml` | The model list. |
| `setup_backend.py` | Keys, AI policy, assistants. |
| `run.py` | Draft scene and Continue, per case, model, brief and draft. |
| `checks.py` | Pure script checks (`phrases.yaml` holds the common phrase list, empty until annotated). |
| `report.py` | Per-cell means, the noise band, the comparison. |
| `judge.py` | The model judge: six rule checks and the separation test. |
| `calibration.py` | The writer's worksheet and the tally that says which rules the judge owns. |
| `parity.py` | The mirror-versus-hand-run guard. |
| `lwa_client.py` | The HTTP client and backend discovery. |
