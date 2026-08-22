# Releasing — how we cut a version

This is the runbook for shipping any release, `vX.Y.Z`. It is version-agnostic:
follow it unchanged for every release. Where a concrete number appears it is an
example, not scope.

Releasing is **manual and deliberate** — there is no release automation, and CI
(`.github/workflows/gates.yml`) does not tag or publish. That is a choice, not a
gap: a release is a judgement call (is the milestone really done? do the notes
tell the right story?), and the steps below are the checklist that keeps the
judgement consistent, not a pipeline to hand it to.

The convention, in one line: **one milestone ↔ one annotated tag ↔ one published
GitHub Release.** Every past inconsistency (a milestone with no tag, a tag with
no Release) is a break in that chain — don't add another.

## 1. Entry gate — is it release time?

All of these before anything else:

- **The release milestone is at zero open issues.** The GitHub milestone named
  for the version (`0.9.0`, `1.0.0`, …) is the ledger — drive it to zero, don't
  eyeball it.
- **Gates are green on `master` at the real head SHA.** Open the actual CI run
  for the commit you will tag — `gh pr checks` can show a green table for an
  earlier SHA (see `reference_gh_checks_can_report_a_stale_sha` in memory). A
  green *table* is not a green *run*.
- **The exemption ratchet is clean** — no new grandfathered entries, widened
  ignores, or added skips snuck in (`scripts/check_exemptions.py`).
- **Pre-release backlog sweep.** Walk the *open* issues (`gh issue list --state
  open`) and triage each: genuine work in scope for this release, or a deferral.
  Move deferrals to a later milestone (`0.9.5`, `Post-1.0`) **explicitly**, so the
  backlog reflects a decision rather than neglect. A hardening release weights
  this toward paying debt down; a feature release toward not shipping known
  regressions — same step, same discipline. This is also where you decide what
  the release *is*: the milestone's contents are its scope.

## 2. Bump the version

Two package literals own the version and move together:

- `backend/pyproject.toml` → `[project].version` (backend source of truth).
- `frontend/package.json` → `version` (frontend source of truth); then
  regenerate the lockfile so it doesn't lag:

  ```
  npm install --prefix frontend
  ```

`backend/app/main.py` does **not** carry a copy — its `FastAPI(version=…)` is
derived from the installed package metadata, and `scripts/check_version_sync.py`
(pre-commit + CI) holds the two literals equal. So a bump is a two-file edit, and
a half-done bump fails the gate rather than shipping mismatched halves.

**Do NOT touch when bumping:**

- The `tiktoken` (or any dependency) pin in `pyproject.toml` — a dependency
  version can coincidentally equal the app version. Never blind find-and-replace
  the semver string.
- The data-format counters — `migrations.CURRENT_VERSION`, and the snapshot /
  witness / workspace-layout `*_VERSION` constants. Those version *on-disk
  formats*, not the release, and move only when a format actually changes.

## 3. Smoke test before tagging

Build the shipping artifact and run it once — nothing else forces the thing you
are about to tag to have actually started:

```
npm run build --prefix frontend
```

Boot the backend, open the app, confirm it comes up clean. A green CI build is
necessary, not sufficient; a release you never launched is a release you never
tested.

## 4. Merge → tag → publish (order matters)

1. **Merge** the version-bump PR to `master`. Gates run on the push.
2. **Tag the release-merge commit.** An *annotated* tag, `v`-prefixed, and keep
   the `v` in the annotation text too (past annotations sometimes dropped it):

   ```
   git tag -a vX.Y.Z -m "vX.Y.Z — <headline>" <merge-commit-sha>
   git push origin vX.Y.Z
   ```

   The tag names the exact commit that carries the bumped version — never a
   commit ahead of or behind it.
3. **Publish a GitHub Release** on that tag — every time, no exceptions. The body
   is the release notes (next section).

## 5. Release notes

Notes are compiled per release from what closed since the previous tag. Recipe:

- Open with a stat line — e.g. *"N issues closed, M PRs since vPREV."*

  ```
  gh pr list --state merged --search "merged:>=<date-of-vPREV>" --limit 500
  gh issue list --state closed --milestone "X.Y.Z"
  ```

- Group the notable changes into thematic sections (features, fixes, internals),
  most user-facing first. Reference issues/PRs by number.
- Note-worthy vs. internal-only is a judgement call: user-visible behaviour and
  fixes belong in the notes; pure chore/CI churn generally does not. When in
  doubt, a reader deciding whether to upgrade is the audience — write for them.

## 6. Post-release housekeeping

- **Close the milestone.**
- **Ensure the next milestones exist** so incoming work has a home.
- **Move anything that didn't land forward** to a real milestone — an unfinished
  issue is rescheduled, never silently dropped.

---

*The related mechanics live next door: `quality-gates.md` (the checks the entry
gate leans on), `worktrees.md` (how the bump PR is prepared), `code-standards.md`
(what a change must meet). This file owns only the release sequence.*
