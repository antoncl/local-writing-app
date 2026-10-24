# Measuring prose quality: what counts as better, and who decides

> **Why this document exists.** ADR-0101 decides who owns how the prose reads — the built-in
> prompts, the style notes, the voices. Every slice it plans is a change to prompt or note text,
> and prompt text can't be judged by reading it: the same edit helps one draft and hurts the
> next. Without a fixed way to measure, each change is judged by feel on whichever scene happens
> to be open, and the built-ins drift toward one writer's taste. This document says what success
> means for that work, how it is measured, and who judges.
>
> It is a working method for developing the app, not an app feature. The harness lives under
> `scripts/benchmark/prose/` and follows that folder's rules (`scripts/benchmark/README.md`):
> drive the real code, generate the runnable fixtures under `tmp/benchmark-fixtures/`, quote the
> scope you measured.

## 1. Two kinds of success

The app ships two kinds of thing, and they answer to different judges.

- **A writer's own book** — their style notes, their voices. The writer's taste *is* the spec.
  For *Unbecoming Someone*, Anton judges, and nobody else's preference should move it.
- **The built-ins** — *Prose craft*, *Character voice in prose*, the style builder. They ship to
  every user. Their job is not to write the way any one writer likes; it is **to write the way
  the author using them asked, and only that way**, with sound defaults where the author asked
  nothing. They are judged on fidelity, not on anyone's taste.

The two are measured on separate test sets (§3), so tuning one can't quietly tune the other.

## 2. What success means

A change succeeds when every line for its tier holds, on every model in scope (§7).

**For a writer's own book:**
- The writer prefers the new drafts in a clear majority of blind comparisons — at least 7 of 10
  pairs.
- Every failure on the failure list (§5) is as rare or rarer, per 1,000 words.
- No rule that held before breaks.

**For the built-ins:**
- **Styles stay apart.** Given a draft and two style notes, a judge picks the note that produced
  it at least 9 times in 10 (§4.2). Drafts that can't be told apart mean the prompt flattens
  every style into the model's own.
- **The builder captures someone else's style.** A draft written from a note the builder inferred
  from an author's pages is assigned to that author, not another, in at least 3 of 4 authors
  (§4.3).
- **The defaults avoid the shared failures.** With no style note at all, every failure on the
  common list (§5) is as rare or rarer than at baseline.
- **No style regresses.** A change that improves one style note's drafts and degrades another's
  fails.
- **Readers prefer it**, where readers are available (§6): a majority of blind comparisons.

## 3. The test sets

Both are frozen: a run changes prompts or notes, never the briefs.

**The personal set** — a frozen copy of the writer's book, kept locally and never committed or
shown to anyone else. Six to eight scene briefs chosen to stress different things:
- two voices in dialogue
- action
- quiet interiority
- a viewpoint character with a strong narrating voice
- a scene with a change marker
- two *Continue* runs from mid-scene

**The built-in set** — committed, so anyone can rerun it. It has three parts:
- **A small invented book.** Four scene briefs and three characters with narrating and speaking
  voices, written for the test, with no ties to any real project. Its source files are committed
  under `scripts/benchmark/prose/`; the runnable project is generated from them.
- **Four contrasting style notes**, each written to ADR-0101's shape (Mechanics and Manner):
  - a frank close third person
  - a lush, distant omniscient narrator
  - a clipped first-person present-tense thriller voice
  - a warm, wry comic voice
  The fourth case is no style note at all, which measures the defaults.
- **Public-domain pages** from four authors with distinct styles: Austen, Conan Doyle, Stephen
  Crane, Kate Chopin. These are used only as input to the builder.

**Every run makes three drafts per brief per model.** One draft is mostly noise; a comparison
needs the spread.

## 4. The checks

Cheapest first. Each check reports per brief, per style and per model, never as one blended
score.

### 4.1 Script checks — exact, free, run every time

These count what can be counted:
- italics in thought
- digits below ten
- em-dash spacing
- the share of dialogue tags that are "said"
- adverbs on tags
- named-emotion words ("felt", "realized", "couldn't help")
- hits from the style note's never-list and from the common list
- word count against the target

They measure rule-following and catch regressions; they say nothing about quality.

### 4.2 The model judge — rule-following and style separation

A model, not the one that drafted, answers **yes/no questions, one rule per question, each
answer with the quoted passage that decides it**. It covers:
- viewpoint slips
- time skips
- a moment explained after it was shown
- a summing-up ending
- euphemism in the narration
- the narration noticing what the viewpoint character wouldn't

It also runs the separation test: given a draft and two style notes, which note produced it?

Two rules bound it:
- **It never judges quality.** Model judges tend to prefer prose that reads like a model's;
  "which draft is better" is a human question (§6).
- **It earns trust before it is used.** On about twenty drafts, the writer answers the same
  questions by hand. The judge is used only where it agrees with the writer on at least 85% of
  verdicts; a rule where it disagrees more stays with the script or with the writer.

### 4.3 The builder test

The harness runs the style builder on each public-domain author's pages: one turn with the pages
and a request to infer the style, then the commit. It then drafts one brief from each inferred
note. The judge is shown the draft and two authors' original pages, and says which author the
draft is closer to.

The automated run skips the builder's contrast step ("which of these two is closer?"), since
that needs a writer's answer, so this measures what the builder infers from pages, not the whole
conversation.

### 4.4 Blind comparison — the quality judge

Pairs of drafts from the same brief, one old and one new, in random order and unlabelled. Only
**the first ~400 words** of each draft are shown, since that is where most failures show and
where reading time is affordable. For each pair the reader picks the one they would keep, and may
mark lines they would cut. The harness writes the pairs as a local page and holds the key back.
The reader's picks are saved to a file the harness then tallies against the key.

## 5. The failure list

The list of failures is the real spec for every prose change, and it comes from reading, not
guessing.

1. **Baseline.** Run today's prompts and notes on both sets.
2. **Annotate.** The writer reads the personal set and marks every failure; the built-in set is
   annotated the same way.
3. **Sort.** The marks become two lists, each with rough frequencies:
   - **the common list** — failures any reader would call failures: an emotion stated outright,
     stock phrasing, a summing-up ending, purple description
   - **the writer's list** — failures against this book's own style

   The common list feeds *Prose craft* and the default checks. The writer's list feeds the
   writer's own never-list, and never the built-ins.

## 6. Who judges

- **The writer**, for their own book, always.
- **Readers beyond the writer**, for the built-ins, when available: a small opt-in group (people
  using the app, a writing group, friends), found through a GitHub Discussion or the release
  notes. They only ever see drafts from the built-in set — the invented book — never a writer's
  manuscript. Recruiting them is outreach and is the maintainer's to decide and do.
- **Until readers exist**, the built-ins are still kept off one writer's taste by the
  separation and builder tests (§4.2, §4.3), which measure fidelity to the style each author
  asked for. The maintainer's own blind comparisons on the built-in set count as one reader's.

## 7. How a change is run

1. **Change one thing.** *Prose craft*, *or* a style note, *or* a voice section — never two at
   once, so a result can be attributed.
2. **Rerun the affected set**: the personal set for the writer's own notes and voices; the
   built-in set, and the personal set too, for any built-in.
3. **Read the report**: script and judge results beside the baseline, then the blind pairs.
4. **Keep or revert** against §2. Record the result and its cost in the PR.

**Models in scope** are a fixed list, named in the harness: at least one strong cloud model, one
cheap cloud model, and the local model the writer uses. A change that helps only the strongest
model is not a success for the built-ins.

## 8. Anti-goals

- **Not an app feature.** No score in the UI and no telemetry. The harness is a development tool.
- **Not the model as quality judge.** It checks rules and tells styles apart, nothing more.
- **Not one writer's taste in the built-ins.** The writer's list never feeds *Prose craft*.
- **Not a writer's manuscript in the repo or in front of other readers.**
- **Not one number.** A blended score hides the regression that §2 forbids.
- **Not two changes in one run.**

## 9. The journey that defines done (for the harness)

1. The maintainer runs the baseline on the built-in set. A dated output folder holds every draft
   with the request that produced it, a report of the script and judge checks per brief, style
   and model, and a page of blind 400-word pairs with the key held aside.
2. The maintainer runs the judge-calibration step, answers the twenty drafts' questions, and the
   report says which rules the judge may own.
3. A *Prose craft* edit is rerun. The report shows each check beside the baseline, and flags a
   style whose drafts got harder to tell apart.
4. The maintainer picks in the pairs page; the harness tallies the picks against the key, and the
   result fills the PR's measurement section.
5. The same commands, pointed at a local copy of a writer's book, run the personal set; nothing
   from it is written inside the repo.
