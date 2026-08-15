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
near-cap file while you worked. `frontend/src/lib/types.ts` is the chronic
offender — a flat wire-types module every feature touches. When CI's file-size
check fails but your local one passes: `git fetch`, merge `origin/master`,
re-count, and **split for real margin** — don't shave one line and re-land at the
cap, or master will push it over again before the next merge. The cheap split:
move a self-contained block to a sibling module and re-export it
(`export type { … } from "./…"`) so the original stays the single import surface.

The guard warns at ≥1200 lines and fails at ≥1500 (`.py`/`.svelte`/`.ts`).

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

## No pre-1.0 migrations

During the 0.x line, a change that alters the on-disk YAML shape (field rename,
wrapper removal, new required key, changed parse grammar) implements **only the
new shape**. Don't add a `field_a or field_b` fallback in the reader, don't add a
step to `services/migrations.py`, and don't bump `project_schema_version`.

**Why.** Paying migration complexity on every pre-1.0 change isn't worth it while
the format is still moving; test projects are disposable and get recreated when a
format change breaks them. The migration commitment begins at **1.0.0** — the
first version that owes a stable storage contract. From 1.0.0 onward, write
proper migrations for any further change. (The long-term migration design is a
separate concern that activates then.)

**Two obligations that come with the policy:**

- **Warn before shipping a breaking change.** Any 0.x change that renames or
  removes a required key, adds a required key with no in-code default, changes an
  on-disk `*.yaml` shape, or changes how an existing field is parsed will make old
  projects fail or silently lose data on next load. Say so plainly when finalizing
  the change — which files/structures are affected and what breaks — so the author
  can plan a test-project reset. If a *live* (non-test) project would lose data,
  the warning isn't enough: pause and confirm before shipping. "Test projects are
  disposable" is not "data loss is acceptable."
- **Machine-level data is not recreated with a project.** Recreating a test
  project only resets data inside the project folder. Assistants and `config.yaml`
  live under `%APPDATA%/local-writing-app/` (machine-level, shared across every
  project) and have no recreate trigger short of deleting that folder. A breaking
  re-key that touches a machine-level shape leaves stale files silently
  mis-rendering, and a fresh project won't fix them — either normalize on read for
  those paths specifically, or tell the user to clear the machine-level folder.
