# Measuring prose quality: what counts as better, and who decides

> **Why this document exists.** ADR-0101 decides who owns how the prose reads: the built-in
> prompts, the style notes, the voices. Every slice it plans is a change to prompt or note text,
> and prompt text can't be judged by reading it, because the same edit helps one draft and hurts
> the next. Without a fixed way to measure, each change is judged by feel on whichever scene
> happens to be open, and the built-ins drift toward one writer's taste. This document says what
> success means for that work, how it is measured, and who judges.
>
> It is a working method for developing the app, not an app feature. The harness lives under
> `scripts/benchmark/prose/` and follows that folder's rules (`scripts/benchmark/README.md`): drive
> the real code, generate the runnable fixtures, quote the scope you measured.
>
> Verified against `1cd8761b` (2026-10-24).

## 1. Two kinds of success

The app ships two kinds of thing, and they answer to different judges.

- **A writer's own book**: their style notes, their voices. The writer's taste *is* the spec. For
  *Unbecoming Someone*, Anton judges, and nobody else's preference should move it.
- **The built-ins**: *Prose craft*, *Character voice in prose*, the prose prompts, and the style
  builder. The builder is not a built-in yet (ADR-0101 S2), but it is held to this standard
  because it is meant to become one. These serve every user. Their job is not to write the way any
  one writer likes. It is **to write the way the author using them asked, and only that way**, with
  sound defaults where the author asked nothing. They are judged on fidelity, not on anyone's
  taste.

The two are measured on separate test sets (§3), so tuning one can't quietly tune the other.

## 2. What success means

Every rate below is compared with **the noise band**: the spread between two runs of the unchanged
baseline (§7). A difference inside the band is no difference. Without it, a check run three drafts
at a time flips on chance alone, and "it got worse" or "it got better" means nothing.

**For a writer's own book:**
- In 20 blind pairs on the primary model (§4.4), the writer prefers the new draft in at least 15.
  That threshold is 15 rather than 11 or 12 because 15 of 20 is unlikely by chance (about 2%).
- No failure on the writer's list (§5) is more frequent than the baseline, beyond the noise band.
- No rule that held before breaks.

**For the built-ins:**
- **Styles stay apart.** For each model, the judge identifies which of two style notes produced a
  draft in at least 90% of trials, with the two notes shown in random order (§4.2).
- **The builder captures someone else's style.** For each model, at least 9 of 12 drafts written
  from builder-inferred notes are attributed to the right author among four (§4.3). Chance is 3.
- **The defaults avoid the shared failures.** With no style note, no failure on the common list
  (§5) is more frequent than the baseline, beyond the noise band.
- **No style regresses.** A change that improves one style note's drafts beyond the band and
  worsens another's beyond the band fails.
- **Readers prefer it**, where readers are available (§6), by the same 15-of-20 bar.

**Which models.** The harness names a fixed list:
- a **primary** strong cloud model, which the blind pairs use
- a cheap cloud model
- the local model the writer uses

The script and judge checks run on all three. A model that can't complete a step, such as a local
model truncating a full scene plus its commit, is reported as *out of reach* for that prompt; that
is not a failure of the change. A change that helps only the strongest model is not a success for
the built-ins.

## 3. The test sets

Each set is frozen: a copy taken once, and kept. A run changes prompts or notes, never the briefs.

**The personal set** is a copy of the writer's book **and its whole ancestor chain**, since the
book's *always* style notes may live in the series or author folders above it. It is kept in a
folder the writer names **outside the repository tree**, and so are all its outputs. A run writes
cost records, traces and chat files into the project it drives, which is another reason it is
always a copy and never the live book. It has six to eight scene briefs, chosen to stress
different things:
- two voices in dialogue
- action
- quiet interiority
- a viewpoint character with a strong narrating voice
- a scene with a change marker
- two *Continue* runs from mid-scene

**The built-in set** is committed, so anyone can rerun it. The runnable project is generated under
`tmp/benchmark-fixtures/prose/` from source files under `scripts/benchmark/prose/`. It has:
- **A small invented book**: four scene briefs and two *Continue* runs from mid-scene, three
  characters with narrating and speaking voices, and no ties to any real project. One narration
  setting (close third person, past tense) is used for every style, so the styles differ only in
  what the notes say. The voice samples avoid every mechanic the style notes disagree on, so a
  voice never takes a side on mechanics. A *Continue* run continues a plain lead-in, which sets the
  voice it continues in, so *Continue* results are reported separately and never counted in the
  separation test.
- **Four contrasting style notes** in ADR-0101's shape (Mechanics and Manner):
  - frank and plain
  - lush and ornate
  - clipped and hard-boiled
  - warm and wry

  None of them sets POV or tense. Those stay in the narration fields (ADR-0101 decision 8). A
  fifth case, no style note at all, measures the defaults.
- **The style builder's text**, as ADR-0101 S2 commits it.
- **Public-domain pages** from four authors of roughly the same era, so period diction doesn't
  give the answer away: Stephen Crane, Kate Chopin, Jack London, Edith Wharton. They are used
  only as input to the builder.

**Every run makes three drafts per brief, per style case, per model.** One draft is mostly noise.

## 4. The checks

Each check reports per brief, per style and per model, never as one blended score.

### 4.1 Script checks: exact, free, run every time

They count what can be counted:
- italics in thought
- digits below ten
- em-dash spacing
- the share of dialogue tags that are "said"
- adverbs on tags
- named-emotion words ("felt", "realized", "couldn't help")
- hits from the style note's never-list and, once it exists, the common list
- word count against the target
- an author's name or title appearing in a builder-inferred note, which fails the builder test
  outright (§4.3)
- the longest run of words a draft shares with a voice sample, since a model may lift the
  sample instead of writing in its voice

They measure rule-following and catch regressions; they say nothing about quality. A count
gets a direction (worse when it rises) only when it is a failure in any style: named emotions,
common-list phrases, markdown, a preamble, a lifted sample. The mechanics the style notes
disagree on (italics, numerals, dashes, contractions, adverbs, sentence length) are reported as
*changed* when they move beyond the noise band, never as better or worse: whether a move is
right depends on the note, and judging that is the model judge's job (§4.2).

### 4.2 The model judge: rule-following and attribution

- **One fixed judge model, named in the harness.** It is never used to judge its own drafts. Drafts
  by the judge's own model go to a named second judge.
- **One rule per question.** The judge answers yes or no and quotes the passage that decides it. The
  rules it checks:
  - viewpoint slips
  - time skips
  - a moment explained after it was shown
  - a summing-up ending
  - euphemism in the narration
  - the narration noticing what the viewpoint character wouldn't
- **The separation test.** Given a draft and two style notes, the judge says which note produced it.
  This is attribution against written rules, not a taste call.

Two rules bound it:
- **It never says which draft is better.** Model judges tend to prefer prose that reads like a
  model's, so quality is a human question (§4.4).
- **It is calibrated before its verdicts count.**
  - The writer answers the same questions by hand on a calibration set, built so that every rule
    has at least eight drafts where the failure is present and eight where it isn't.
  - A rule is the judge's only if the judge agrees with the writer on at least 80% of the
    *present* cases and 80% of the *absent* cases. Two rates are used because one overall rate
    would let a judge that always answers "no" pass on a rare failure.
  - A rule that fails stays with the script or with the writer.
  - Changing the judge model voids the calibration.

### 4.3 The builder test

The harness drives the builder as the app does:
- **The first user turn** carries an author's pages and the fixed message "Infer this writing's
  style from these pages and propose the note."
- **The contrast step.** If the builder asks one, the harness answers with the fixed reply "No
  preference; propose the note from the pages."
- **The commit** follows.

This measures what the builder infers from pages. It does not measure the full conversation with
a writer.

The note it commits must not name the author or a work (§4.1). From each of the four inferred notes,
the harness drafts one brief three times. For each draft, the judge is shown the draft and one
unnamed excerpt from each of the four authors, and says which author the draft is closest to.

### 4.4 Blind pairs: the quality judge

- **What a pair is.** The first ~400 words of an old draft and a new draft of the same brief, in
  random order and unlabelled. That is where most failures show, and where reading time is
  affordable.
- **"Old"** means the frozen drafts kept from the baseline, not a fresh run.
- **Which pairs.** 20 are drawn per change, from the primary model only, spread evenly across the
  briefs and style cases.
- **What the reader does.** For each pair they pick the draft they would keep, and may mark lines
  they would cut.
- **How it's tallied.** The harness writes the pairs as a local page and holds the key back; the
  page exports the reader's picks as a file, which the harness tallies against the key.

## 5. The failure list

The list of failures is the real spec for every prose change, and it comes from reading, not
guessing.

1. **Annotate the baseline.** The writer reads the baseline drafts of both sets and marks every
   failure.
2. **Sort the marks into two lists, each with rough frequencies:**
   - **The common list**: failures any reader would call failures, such as an emotion stated
     outright, stock phrasing, a summing-up ending, or purple description. It feeds *Prose craft*,
     the script checks and the default checks.
   - **The writer's list**: failures against this book's own style. It feeds the writer's own
     never-list, and never the built-ins.

## 6. Who judges

- **The writer**, for their own book, always.
- **Readers beyond the writer**, for the built-ins, when available: a small opt-in group (people
  using the app, a writing group, friends), found through a GitHub Discussion or the release notes.
  They only ever see drafts from the invented book, never a writer's manuscript. Recruiting them is
  outreach, and is the maintainer's to decide and do.
- **Until readers exist,** the separation and builder tests (§4.2, §4.3) still keep the built-ins
  off one writer's taste, since they measure fidelity to the style each author asked for. The
  maintainer's own blind pairs on the built-in set count as one reader's.

## 7. How the harness runs

**It drives the backend over HTTP, as the frontend does.**
- **The backend.** The harness runs against a worktree dev backend (`scripts/dev_backend.py`), which
  derives its own port and its own config directory, and finds it through the port file that
  backend publishes in its checkout. It refuses the default port 8787, and so never uses Anton's
  live server, config or projects.
- **One-shot prompts** such as Continue or Shorten: call the generate route with the cursor text,
  as the editor does.
- **Conversation prompts** such as Draft scene or the builder:
  1. create the chat
  2. render the template through the preview route and save the locked record on the chat
  3. send the turn, and save the reply on the chat
  4. run the commit extraction, which proposes the body without writing it
- **Why not in-process.** The backend has no single "run this conversation" entry point: the lock,
  the chat's creation and the turn order live in the frontend (`promptTemplateLock.ts` and the chat
  stores). Calling services in-process would reimplement that logic. Over HTTP, the harness mirrors
  only the *sequence* of calls, and every call runs the real code.
- **The guard on the mirror.** What the harness mirrors is the frontend's half of a conversation,
  and that half ends in the chat record the app saves: the locked system prompt, the opening turns,
  the lore it used, the field contract and the inputs. The backend's half (lore placement on the
  send) is real code on both paths, and the preview mirrors it (ADR-0092). So the harness keeps
  each draft with its chat record as the backend stored it. Once per prompt, and again whenever the
  frontend's sequence for that prompt changes, that record is compared with the record of the same
  brief run by hand in the app (`scripts/benchmark/prose/parity.py`). A difference fails the
  harness, not the change. The backend keeps no log of the exact provider request
  (`record_ai_trace` records commit extractions only), so the chat record is the evidence.

**Setup.**
- The harness reads the provider keys from environment variables and saves them through the
  app's machine-settings route, which keeps them in the OS keyring under the throwaway config
  directory's own namespace. They are never printed or logged.
- It creates one assistant per model in scope and turns AI on for the project.
- Cost is the sum of the costs the routes return. The cost ledger is written by the frontend on
  accept, so the harness doesn't read it.

**A run, in order:**
1. **A/A**: the unchanged baseline, twice, to measure the noise band (§2).
2. **Script checks** on both baseline runs.
3. **Calibration** (§4.2), once per judge model, before any judge verdict counts.
4. **Judge checks** on the baseline.
5. **Annotation** (§5), which produces the common list and the writer's list.

After that, each change is one change: *Prose craft*, *or* a style note, *or* a voice section, never
two. It reruns:
- **A built-in change**: the whole built-in set on all models, script and judge checks, and the blind
  pairs on the primary model. The personal set reruns too.
- **A change to a writer's own note or voice**: the personal set only.

The result is kept or reverted against §2, and recorded with its cost in the PR.

**Cost, estimated.**
- One built-in run is about 180 drafts at about two calls each (turn and commit), plus about a
  thousand single-rule judge calls.
- That is roughly $20–50 on current cloud pricing.
- The local model costs no money but about three hours a run.
- Estimated from prompt sizes, not measured. The harness reports the real figure per run.

## 8. Anti-goals

- **Not an app feature.** No score in the UI and no telemetry.
- **Not the model as quality judge.** It checks rules and attributes styles.
- **Not one writer's taste in the built-ins.** The writer's list never feeds *Prose craft*.
- **Not a writer's manuscript in the repository tree or in front of other readers**, and not a run
  against a live book.
- **Not reimplementing the app's logic in the harness.** It mirrors the frontend's call sequence and
  checks the mirror against the chat record a hand run saves.
- **Not one number,** and not a threshold without the noise band.
- **Not two changes in one run.**

## 9. The journey that defines done (for the harness)

1. **Setup.** The maintainer sets the provider keys in the environment and runs the setup. A
   worktree dev backend comes up on its derived port with its own config directory, and the
   built-in fixture project is generated.
2. **Parity.** The maintainer runs Draft scene on one brief by hand in the app, then the harness's
   parity check. It reports the harness's chat record and the hand run's as matching.
3. **Baseline.** The A/A baseline runs. A dated output folder holds:
   - every draft, with its chat record and the costs the routes returned
   - the script checks per brief, style and model
   - the noise band
4. **Calibration.** The maintainer answers the calibration set. The report says which rules the
   judge may own, and only then adds judge results to the baseline.
5. **Annotation.** The maintainer annotates the baseline; the common list and the writer's list are
   written.
6. **A change.** A *Prose craft* edit is rerun. The report shows each check beside the baseline and
   its noise band, and flags a style whose drafts got harder to tell apart. The pairs page shows 20
   pairs; the maintainer's picks are tallied against the key into the PR's measurement section.
7. **The personal set.** The same commands, pointed at a copy of a writer's book and its chain in a
   folder outside the repository, run the personal set. Nothing from it is written inside the
   repository tree.
