# Quality gates — the three layers, and why each exists

CLAUDE.md says what to run and what never to do. This file says how the
machinery works and what it is defending against. Read it before changing
`.pre-commit-config.yaml`, `.claude/settings.json`, `.github/workflows/`, or
anything under `scripts/`.

The standards are **machine-enforced** rather than remembered. A rule that lives
only in prose drifts under context pressure — that is how `App.svelte` reached
~4900 lines. Three layers, weakest → strongest.

## 1. In-session — the `PostToolUse` hook

`.claude/hooks/check_edited_file.py`, wired in `.claude/settings.json`, runs the
file-size guard, the style-token guard, and `ruff` on **every file you edit**,
and feeds any violation straight back into the model's context.

Because it is on the session's hot path, both its wall-clock and its *output
size* matter: the hook's stdout is injected into context on every single edit.
It therefore runs **one** ruff process (blocking rules and the advisory
complexity rules requested together via `--extend-select`, then partitioned by
rule code on the way out), emits one line per finding rather than ruff's
default six-line source snippet, and caps its total output. An earlier version
ran ruff twice — the second pass with `--no-cache`, which both doubled the
process spawns and discarded the cache the first pass had just warmed.

## 2. Git hooks — commit only, and fast

`.pre-commit-config.yaml`: `ruff` (blocking) + advisory complexity + the
file-size and style-token guards, on staged files.

**There is deliberately no push stage** — the slow whole-project gates moved to
CI (#352). `ruff` covers `backend/`, `scripts/` **and** `.claude/hooks/`: the
gate machinery is held to the rules it enforces (#352). The root `.ruff.toml`
extends `backend/pyproject.toml` so files outside `backend/` don't fall back to
ruff's weaker defaults.

One-time setup per clone:

```powershell
backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"
backend/.venv/Scripts/pre-commit install
```

**Not** `… -t pre-push`. If an old clone has one, `pre-commit uninstall -t pre-push`
removes it.

## 3. CI — the only layer that cannot be walked past

`.github/workflows/gates.yml` (#352) runs the same gates on a **clean checkout**,
on every PR and every push to master. It is the only layer immune to `--no-verify`
and to the local hazards below (a worktree importing the primary tree's code; a
concurrent session writing into the shared tree mid-run). It runs the two guards
**repo-wide**, not just over staged files.

Three jobs: `backend` and `frontend` on Linux, plus `backend-windows`. This is a
Windows-first app and the bugs that bite are platform ones (junctions, cp1252,
path separators, CRLF) — but a Windows-only gate hides POSIX bugs, so both run.
The repo is public, so runner minutes are free; optimise for signal, not cost.

The checks are **required**: the `master gates` ruleset blocks merging a red PR,
blocks direct pushes to master, and blocks force-push and deletion. Still:
**never report "green" without opening the run.** `gh pr checks` can report a
full green table for an *earlier* commit — filter runs by `head_sha` and check
per-job status.

## The exemption ratchet — the guard on the guards

`scripts/check_exemptions.py` (CI, PRs only). Every escape hatch may shrink,
never grow. It compares the branch against the PR base and fails on a new
`GRANDFATHERED` entry, a widened ruff `ignore` or `per-file-ignores`, a rule
dropped from `select`, or a newly skipped/xfailed test.

**When a gate goes red, fix the code — do not widen the exemption.** If a new
exemption is genuinely right, say so explicitly in the PR rather than letting it
ride along in a diff; once it lands, the base moves and the ratchet re-arms.

```bash
python scripts/check_exemptions.py --base origin/master
```

## The citation-rot checker — advisory by design

`scripts/check_citations.py`, `.github/workflows/citation-rot.yml` (#397). It
verifies `path:line` claims in issue bodies, ADRs and docs against the code,
anchoring each on the symbol the prose names next to it — which is what catches
the dangerous shape: a line number that is still *valid* and now lands on
unrelated code.

It is deliberately **not** part of `gates.yml`, because a PR must not go red
because an unrelated issue got stale. It runs on PRs only, commenting about the
files that diff touches, so rot is caught by the person creating it while the
context is still in their head. A weekly repo-wide run once edited a standing
tracking issue (#407); that was retired in 2026-07 because a permanently-open
issue restating rot is a log, not a fix.

**It flags, it never fixes.** Repointing a stale line number yields a citation
that resolves cleanly and still does not support the sentence — which turns
visible rot into invisible rot.

The repo-wide sweep still exists in the script: run it by hand before a release.
`python scripts/check_citations.py --memory-dir <memory>` is the only run that
can see the memory files, since CI cannot.

## Gates inside a linked worktree

The gates must test *that* worktree's code.

- `scripts/venv_run.py` borrows the primary worktree's *interpreter* but forces
  this checkout's `backend/` onto `PYTHONPATH` (#352 — otherwise the editable
  install silently imports the primary tree's `app`).
- `scripts/npm_run.py` runs a real `npm install` in the worktree.
- **Never link or junction a shared `node_modules`/venv into a worktree**: a
  recursive delete — `git worktree remove -f` among them — walks through the link
  and guts the primary install (#350).

## The two content guards

- **File-size guard** (`scripts/check_file_size.py`) — the enforced half of "no
  monolithic files": warns ≥1200, **fails ≥1500** lines on `.py/.svelte/.ts`.
  Files knowingly over the cap live in that script's `GRANDFATHERED` set
  (currently `test_metadata_validation.py`) — split them when you next work
  there, then delete the entry.
- **Style-token guard** (`scripts/check_style_tokens.py`) — the enforced half of
  the design language (`docs/design/design-language.md` §5): hex/rgb color
  literals and non-token `font-size` in frontend style code fail. Its own
  shrink-to-zero `GRANDFATHERED` set (#129); sanctioned exceptions are listed in
  the script's docstring.
