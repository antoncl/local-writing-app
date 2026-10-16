# Code standards

The rules a change is expected to meet before it lands. These are conventions,
not just style preferences — several are machine-enforced by the quality gates
(→ [`quality-gates.md`](quality-gates.md)). This document is the *why*; the gates
are the *how*.

## No monolithic source files

Split a file before it becomes a multi-thousand-line monolith. When a single
`.py`, `.svelte`, or `.ts` file has grown past ~1500 LOC and is *still*
accumulating new top-level functions, state, or markup, treat that as a stop
sign and extract — don't wait for a "natural" 5000-line extraction point.

**Why.** Two ~5400-line files (`App.svelte`, `project_service.py`) once ate
context on every edit, forced a search just to locate the change site, and
needed a multi-commit refactor (#14) to undo. Moving thousands of lines without
intermediate verification is itself risky — it puts the app one mistake away
from broken. Smaller files mean cheaper reading, cleaner diffs, and less
bisecting when something breaks.

**In practice.**

- **Default to a new file** when adding a new pane, dialog, service, or cohesive
  feature. A new file at 200 LOC is fine; a 200-LOC addition to a 4000-LOC file
  is not.
- **Watch the file you're editing.** If a feature has added a few hundred LOC and
  the file is already over ~1500, surface the split before continuing rather than
  shipping it larger.
- **Extraction pattern.** The parent owns long-lived state and side-effects; the
  extracted component takes draft state via `bind:` props and emits events for
  actions. Shared constants migrate to a domain util module.
- **The existing monoliths get split incrementally** — each slice a separate,
  bisectable commit, never a one-shot rewrite.

**The file-size guard fails on the merge with master, not your branch alone.**
A branch locally under the cap can still fail CI when master advanced a shared
near-cap file while you worked. `frontend/src/lib/types.ts` was the chronic
offender — a flat wire-types module every feature touched — until #1859 split
it into sibling `<domain>Types.ts` modules behind a re-export barrel; a new
wire type now goes in its domain's module, never in the barrel. When CI's
file-size check fails but your local one passes: `git fetch`, merge
`origin/master`, re-count, and **split for real margin** — don't shave one line
and re-land at the cap, or master will push it over again before the next
merge. The cheap split: move a self-contained block to a sibling module and
re-export it (`export * from "./…"` or `export type { … } from "./…"`) so the
original stays the single import surface.

The guard warns at ≥1200 lines and fails at ≥1500 (`.py`/`.svelte`/`.ts`).

## Keep methods short and parameter lists small

The per-file rule has a per-function twin: keep individual methods short and their
parameter lists small. Ruff flags both — argument count (`PLR0913`) and
per-function complexity (`C901`, `PLR0912`, `PLR0915`). These run as an advisory
hook, so treat them as a **smell to remove, not an obstacle to route around**.

**Why.** A long method or a long parameter list is a signal that the function is
doing too much. Many parameters mean many internal branches, and a method with
many flows becomes virtually **untestable** — the number of input permutations
explodes combinatorially, so no realistic test suite covers them. Short,
single-purpose functions are the opposite: few flows, each one easy to exercise
in isolation.

**Decompose — never disguise the count.** When a function trips the argument or
complexity limit, split its responsibilities into smaller, independently-testable
helpers. Do **not** pack the parameters into a struct or object purely to get
under the linter's count: that hides the number from the tool while leaving the
god-function — and its untestable permutation explosion — fully intact. Bundling
unrelated parameters to silence the metric is *parameter stuffing*, and it is
forbidden.

**The line is cohesion, not grouping.** A value object is legitimate when the
parameters it carries genuinely describe *one thing* — `{x, y, width, height}` is
a rectangle, and this repo's Pydantic `*Request` models bundle a real request.
Those model a concept and reduce what the function juggles. The test for which one
you're doing: does the struct name a thing that already wanted to exist, or is it
a grab-bag invented only because the linter complained? The first is real
modelling; the second is evasion.

The same applies to waving a complexity finding off as "pre-existing debt." That
notes the smell instead of removing it. If a genuinely cohesive value object
isn't the honest fix, the function is doing too much and must be split.

## No compile errors, minimal warnings

A clean typecheck and build is the baseline. Never leave compile errors in place,
and avoid warnings unless they genuinely cannot be avoided.

When a check (`svelte-check`, `tsc`, the build) reports errors or warnings — even
ones that predate your change — do not dismiss them as "pre-existing" or "out of
scope." Investigate and fix, or explicitly flag them for a fix (a tracked
tech-debt issue). A growing pile of tolerated errors erodes the signal a clean
check gives, and misconfigured tooling that hides errors is itself a bug worth
fixing.

`npm run check` (svelte-check) must stay clean. Do not bury standing errors in a
"these are pre-existing" aside — call them out and propose a fix or a tech-debt
issue.

## Storage changes owe a migration

Since 0.9.5 the project format is a stable contract: a change that alters the
on-disk shape (field rename, wrapper removal, new required key, changed parse
grammar) ships **with a migration** in `services/migrations.py` and a
`CURRENT_VERSION` bump. Pick the step shape that fits — `RootMigration` (one
project folder), `DocumentMigration` (one document at a time), or
`ChainMigration` (needs the inherited chain) — per ADR-0071. Don't paper over an
old shape with a `field_a or field_b` fallback in the reader instead: the
migration is the one place the old shape is known.

**Why.** Writers' projects are real data, and 1.0 promises they survive
upgrades. A migration converts each project once, backs it up first
(`.migration-backups/`), and leaves every reader free of legacy branches.
(Through 0.9.0 the rule was the opposite — implement only the new shape, recreate
test projects — because the format was still moving. That ended at 0.9.5.)

**Two obligations that come with it:**

- **Pause before risking real data.** If a change could lose data a migration
  can't faithfully carry over, say so plainly when finalizing it — which
  files/structures are affected and what is lost — and confirm before shipping.
- **Machine-level data is not migrated with a project.** Assistants and
  `config.yaml` live under `%APPDATA%/local-writing-app/` (machine-level, shared
  across every project); project migrations never touch them. A re-key that
  touches a machine-level shape needs its own handling — normalize on read for
  those paths specifically, or migrate them separately.
