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
   a rerun resumes, and `--redo` asks again; a record from a different judge model is
   never resumed. `--workers` (default 4) judges that many drafts at once. It writes
   `judge_<n>.json` beside each draft and `judge.json` in the run (the judges' model ids
   and cost). A band or compare with `--calibration` refuses runs judged by different models.
3. Calibrate, in order:
   1. Name a third model under `seeder:` in `models.yaml` (neither a judge nor a drafter;
      the example file shows one) and rerun `setup_backend.py`.
   2. `calibration_seed.py <run> --out <seeded>` has it rewrite 8 Continue passages per rule
      (`--per-rule`) to contain exactly that one failure, as a run of its own.
   3. `judge.py <seeded>` judges them like any run.
   4. `calibration.py sheet <run> --seeded <seeded> --out <dir>` shuffles a sample of the
      natural drafts and every seeded passage into one list (`answers.yaml`, `sheet.md`).
      The sample is `--scenes` Draft scene drafts (12) and, by default, as many Continue
      drafts as there are seeded passages, so a continuation alone doesn't hint at a planted
      failure. It refuses to overwrite an `answers.yaml` that already holds answers.
   5. `calibration_serve.py <dir>` opens the reading page: answer each rule yes, no or not
      sure. Answers save as you go, so you can stop and resume. The page never shows the
      judge's answers or which passages are seeded. Each answer records the question
      wording it answered; the tally skips answers to a since-reworded question and warns
      of any given before wording was recorded. While the page runs it keeps a
      `<dir>/.serving` marker, which `calibration.py extend` refuses to work past.
4. `calibration.py tally <dir>/answers.yaml --out calibration.json` prints each rule's
   agreement per judge model. The judge owns a rule only if it has at least 8 present and 8
   absent answers at 80% agreement or better on each, agrees on 80% of the seeded present
   ones, and, if you found any natural present ones, on 80% of those too. Not-sure answers
   are never counted. Change the judge model and the calibration no longer applies.
   When a rule's question is reworded, each verdict records the question it answered
   (`question_sha`; verdicts from before count as the old wording). A plain `judge.py`
   rerun re-asks only the reworded rules, a stale verdict counts as missing in the tally and
   the report, and `calibration.json` records the question each rule was tallied against, so
   a reworded question voids that rule's ownership until you retally. `--rules RULE ...` on
   `calibration_seed.py` seeds only those rules (new drafts number after the folder's
   highest). Seeding never reuses a source passage another rule's seed in the same
   `--out` already used, and a second run merges its models into the output's `run.json`. To add to a sheet you have started, `calibration.py extend <dir> --run <run>
   --seeded <seeded> --natural N` appends N more natural Continue drafts and every seeded
   passage not yet on it, numbered after the last id; existing items and answers are
   untouched.
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

## Blind pairs (H4)

A reader's blind preference between a baseline and a changed run (`pairs.py`, #2617). Nothing
calls a backend or a model.

1. `pairs.py make BASELINE_RUN NEW_RUN --out DIR` draws one pair per (style case, brief): the
   first ~400 words, ending at a sentence, of one baseline and one new Draft scene draft of
   the primary model. A cell missing on either side is skipped and printed. It writes
   `DIR/send/pairs.html` (shuffled, A/B unlabelled, nothing of the key in it) and
   `DIR/key.json`, which also holds the excerpts exactly as shown. `--cases frank none lush`
   draws only those styles: 12 pairs instead of 20, a shorter reading, but a higher bar to
   rule out chance (10 of 12 rather than 15 of 20).
2. Send or open `DIR/send/` only; **`key.json` never leaves `DIR`**. It works offline. Every pair
   asks the same question: which would you rather keep as the start of your own draft. Pick
   Keep A or Keep B (there is no "no preference": every pick is a real choice; keys `a`/`b`,
   `]`/`[`, Space for the next unpicked), click a sentence to mark it
   as one you would cut. Progress resumes from the browser's own storage.
3. **Download picks** saves `picks-<page id>-<reader>.json` (**Copy picks** if downloads are blocked).
4. `pairs.py tally DIR/key.json picks.json [picks2.json ...]` (one file per reader: two from
   the same reader are refused) refuses a file from another page and writes `DIR/result.md`:
   new against baseline with a two-sided sign test, per reader and per style case, and the
   cut sentences per side. With several readers each pair casts one vote (the side most
   readers kept; a tie is dropped), since readers judge the same pairs and pooling every pick
   would overstate p.
5. Paste `result.md` into the PR.

## Builder test (H3)

Whether the style builder (`fixture/style-builder.md`, #2623) infers a note that captures an
author's style. For each builder model and each of four authors (`fixture/authors.yaml`:
public-domain Project Gutenberg pages, plus three later held-out excerpts of each) the builder is
given ~1500 words and asked to propose the note; the fixed reply "No preference; propose the note
from the pages." answers any contrast question (at most 3). The judge is then shown one excerpt
and that model's four notes, unlabelled, in an order fixed by a hash of the trial, and says which
note describes the writing.

- **Bar:** per model, 9 of the 12 excerpts matched to the right note (chance is 3). A note that
  names the author or the work (`leak_terms`, whole words, case-insensitive) fails that author
  outright: its three trials never count. A model with a missing note, or a trial not answered,
  is out of reach and counts against the bar.
- **Run:** with a dev backend up, keys set by `setup_backend.py`, and judges in `models.yaml`:
  `builder.py run --out tmp/builder-run` (`--models` names the builder models, default every
  `models:` entry; `--authors KEY ...` for a smoke run, which matches among those authors only and
  is reported as partial). A rerun resumes: a built note and an answered match are kept; delete
  `notes/<model>/<key>.json` to rebuild a note. `builder.py report tmp/builder-run` rewrites
  `result.md`, ready for a PR body.
- **Cost:** about 8 builder conversations and 24 judge calls for two models, roughly $2.
- The builder and the judge run in `builder-<key>` (no style note, the prompt installed through
  the app's prompt routes), under `tmp/benchmark-fixtures/prose/`.
- **Why it doesn't draft from the notes:** drafts written with no note at all were attributed as
  well as drafts from the notes, so drafting measured the brief, not the builder (design doc §4.3).

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
| `calibration_seed.py` | Rewrites passages to contain one planted failure each (the seeder model). |
| `calibration_serve.py` | Local server for the reading page; saves answers to `answers.yaml`. |
| `calibration_page.html` | The reading page (offline, no dependencies). |
| `pairs.py` | Blind pairs: `make` draws the page and key, `tally` reports the readers' picks. |
| `pairs_page.html` | The pairs page template (offline, no dependencies). |
| `builder.py` | The builder test: `run` and `report` (`builder_core.py` holds its pure rules). |
| `parity.py` | The mirror-versus-hand-run guard. |
| `lwa_client.py` | The HTTP client and backend discovery. |
