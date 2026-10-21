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

### The review-before-push gate — a `PreToolUse` hook

`scripts/review_gate.py hook`, wired as a `PreToolUse` hook on `Bash|PowerShell`,
blocks `git push` and `gh pr create` from a Claude session until a code review
is recorded for the commit being pushed. The rule it enforces: run the
adversarial `/code-review` over the final diff **before the first push**, so the
fixes ride the same CI run. CI takes ~17 minutes, and as prose the rule kept
being skipped — push first, review after, pay for a second run (most recently
#2605).

The workflow:

1. `/code-review` over the branch's diff; fix the findings; **commit** the fixes.
2. `python scripts/review_gate.py mark` — records `HEAD` in
   `<git-dir>/claude-reviewed-sha`. The git dir is per-worktree, so each
   worktree has its own record and nothing is committed. `mark` refuses while
   the worktree has uncommitted or untracked changes: the recorded commit must
   contain the fixes, including a new test file nobody `git add`ed.
3. Push / open the PR.

What the hook accepts: the recorded SHA is `HEAD`, or `HEAD` descends from it
through merge commits and `origin/master`'s own commits only — bringing the
branch up to date with master is not new work and needs no re-review. Any other
new commit (a late fix, a rebase, an amend) re-blocks until `mark` runs again.
A command that both moves `HEAD` (commit, merge, pull, rebase, reset,
checkout, switch, …) and pushes — `git commit … && git push` — is blocked
outright: the hook runs before the commit, so it could only vouch for the old
`HEAD`. The review covers `HEAD` only, so a refspec naming another branch, or
`--all` / `--mirror` / `--branches`, is blocked too.

The command is judged per segment (split at `;`, `&&`, `||`, `|`, `&` and
newlines, outside quotes), so a `-d` or `-C` belonging to another command in
the chain cannot vouch for the push.

Always allowed: `--dry-run`, and branch deletion (`--delete`, `-d`,
`:branch`) — the post-merge cleanup publishes no code.

**The escape is visible on purpose.** For a docs-only or emergency push, end the
command with a comment carrying a reason:

```bash
git push -u origin my-branch  # review-gate: skip docs-only change
```

It is a comment in both bash and PowerShell, so it changes nothing about the
command, and it sits in the transcript where it can be questioned. It counts
only as the command's trailing, unquoted comment — the same text inside a
quoted PR body does nothing — and a bare `# review-gate: skip` with no reason
is still blocked.

Limits, accepted: the gate checks for a *recorded* review, not a good one —
`mark` is the model's own attestation. It defends against forgetting, which is
the failure that kept happening. A conflict resolution inside a merge commit is
not re-reviewed. `cd elsewhere && git push` is judged by the session's cwd
(`git -C <dir> push` is resolved correctly). The hook spawns a Python process
on every shell call — tens of milliseconds, against a 17-minute CI run it
saves. Like any hook, it is not active in
the session that adds it — `settings.json` loads at session start.

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
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.lock
backend/.venv/Scripts/python.exe -m pip install -e backend --no-deps
backend/.venv/Scripts/pre-commit install
```

Deps install from `backend/requirements.lock`, never a fresh resolve — same
versions on every machine, in CI, and in the release freeze (#1393). To move
them, edit `backend/pyproject.toml` and run `python scripts/relock_backend.py`.

**Not** `… -t pre-push`. If an old clone has one, `pre-commit uninstall -t pre-push`
removes it.

## 3. CI — the only layer that cannot be walked past

`.github/workflows/gates.yml` (#352) runs the same gates on a **clean checkout**,
on every PR and every push to master. It is the only layer immune to `--no-verify`
and to the local hazards below (a worktree importing the primary tree's code; a
concurrent session writing into the shared tree mid-run). It runs the two guards
**repo-wide**, not just over staged files.

Four required jobs: `backend` and `frontend` on Linux, `backend-windows`, and
`e2e` (the Playwright smoke over the built bundle, #1352). This is a
Windows-first app and the bugs that bite are platform ones (junctions, cp1252,
path separators, CRLF) — but a Windows-only gate hides POSIX bugs, so both run.
The repo is public, so runner minutes are free; optimise for signal, not cost.

The checks are **required**: the `master gates` ruleset blocks merging a red PR,
blocks direct pushes to master, and blocks force-push and deletion. It also
requires the PR branch to be **up to date with master** (strict status checks,
on since 2026-10-02). Without it, a PR's checks test the branch as it forked, not
the merge result: on 2026-10-01 two PRs that each passed (#2389, #2391) merged
into a red master, because git's textual merge attached one PR's
`field_overrides` block to the other's new entry type. The cost is a rebase or
"Update branch" plus a CI rerun whenever master moved under an open PR — which
is why a PR only pays for the jobs its files can affect (next section). Still:
**never report "green" without opening the run.** `gh pr checks` can report a
full green table for an *earlier* commit — filter runs by `head_sha` and check
per-job status.

### Path-aware jobs — a PR pays only for what it can break

A first `changes` job pipes the PR's changed files (its merge commit against the
base tip, renames counted as delete + add) through
`scripts/ci_changed_areas.py`, which names the areas they can affect. Each heavy
job skips an untouched area. **A job skipped by its `if` reports as passed**, so
the four required checks always report and never sit pending. A push to master
and a manual run gate everything.

| Changed path | backend pytest (Linux + Windows) | frontend | e2e |
|---|---|---|---|
| `backend/app/builtin_library/` (built-in prompts), `backend/tests/` | ✓ | | |
| rest of `backend/` (incl. `pyproject.toml`, `requirements.lock`) | ✓ | | ✓ |
| `docs/` | ✓ | | |
| `frontend/` | | ✓ | ✓ |
| `frontend/src/lib/views/__fixtures__/`, `viewGrammar.generated.ts`, `diffRuns.fixtures.json` (fixtures pytest reads or regenerates) | ✓ | ✓ | ✓ |
| `gates.yml`, `scripts/`, `.claude/`, `spec/`, `.ruff.toml`, `.pre-commit-config.yaml`, `.gitattributes` | ✓ | ✓ | ✓ |
| other `.github/workflows/`, the PR template, `packaging/`, `site/`, root `*.md`, `LICENSE`, `.gitignore` | | | |
| **anything not listed** | ✓ | ✓ | ✓ |

The `backend` job's ruff, guard, drift and ratchet steps are cheap and
repo-wide, so they run on every PR. When its full pytest step skips, it still
runs `test_gate_invariants.py` and `test_ci_changed_areas.py` (seconds): they
check the gate machinery against the whole tracked tree, so a file added by
any PR can turn them red.

The mapping is **fail-open**, and that is the invariant to keep when editing it:
a wrong guess may cost a slower run, never a skipped job that should have gone
red. So an unmapped path runs everything; an empty diff runs everything; and the
consumers test `!= 'false'` rather than `== 'true'`, so a failed `changes` job
leaves empty outputs and every heavy job runs (`!cancelled()` keeps them going
past it). `test_ci_changed_areas.py` pins the rules and fails when a tracked
path matches no rule, so a new top-level folder gets mapped on purpose. **When a
test starts reading a file outside its area** (a backend test opening a
frontend fixture, say), add that path to the rules — otherwise a change to it
skips the test that reads it.

## The exemption ratchet — the guard on the guards

`scripts/check_exemptions.py` (CI, PRs only). Every escape hatch may shrink,
never grow. It compares the branch against the PR base and fails on a widened
ruff `ignore` or `per-file-ignores`, a rule dropped from `select`, a newly
skipped/xfailed test, or a grown `GENERATED_ROOTS` build-output skip list. (The
per-file `GRANDFATHERED` escape hatches the guards once carried were removed in
#1681 — a guard violation now always fails, with no per-file exemption to grow.)

**When a gate goes red, fix the code — do not widen the exemption.** If a new
exemption is genuinely right, say so explicitly in the PR rather than letting it
ride along in a diff; once it lands, the base moves and the ratchet re-arms.

```bash
python scripts/check_exemptions.py --base origin/master
```

## Gates inside a linked worktree

The gates must test *that* worktree's code.

- `scripts/venv_run.py` borrows the primary worktree's *interpreter* but forces
  this checkout's `backend/` onto `PYTHONPATH` (#352 — otherwise the editable
  install silently imports the primary tree's `app`).
- `scripts/npm_run.py` runs a real `npm install` in the worktree.
- **Never link or junction a shared `node_modules`/venv into a worktree**: a
  recursive delete — `git worktree remove -f` among them — walks through the link
  and guts the primary install (#350).

## The memory-index ratchet

`scripts/check_memory_index.py`, run from the `PostToolUse` hook when the edited
file sits beside a `MEMORY.md` — so ordinary edits pay nothing for it.

`MEMORY.md` is loaded into every request of every session, which means its size
is paid on every model step (~24 per user prompt when this was measured). It has
no natural shrinking force: every session may add a memory, none removes one.
That is the same shape as the exemption ratchet, and it gets the same treatment
— a high-water mark that only ever moves down.

Four rules, three of them ratchets against the counts at the time the guard
landed rather than absolutes:

- **size** — `MAX_BYTES`; merge or retire a memory rather than raising it.
- **inline content** — non-pointer lines. The index is meant to be pointers, one
  line per memory, with content in the memo files; prose that accumulates here
  is paid on every step instead of being read on demand.
- **hook length** — a pointer over `MAX_POINTER_CHARS` has started summarising
  the memo instead of pointing at it.
- **dangling pointers** — a pointer to a missing memo. This one is a correctness
  bug, so it carries no ratchet and is always reported.

The ratchets exist because the first three rules are *already violated today*.
An absolute rule would fire on every memory write until a consolidation pass
lands, and a guard that fires every time is one that gets tuned out. Ratcheting
keeps it silent until something gets worse. **After a consolidation pass, lower
all three constants to whatever the trimmed file measures** — that is the step
that converts a one-off cleanup into a floor.

Pinned by `test_gate_invariants.py`, including that a finding survives being
reported to a cp1252 console: an earlier version raised `UnicodeEncodeError`
while echoing an emoji from the index back, which turned the guard into a crash
at exactly the moment it had something to say.

## The two content guards

- **File-size guard** (`scripts/check_file_size.py`) — the enforced half of "no
  monolithic files": warns ≥1200, **fails ≥1500** lines on `.py/.svelte/.ts`. A
  file over the cap must be split — there's no per-file exemption (the empty
  `GRANDFATHERED` escape hatch was removed in #1681; every source file is under
  the cap, #76).
- **Style-token guard** (`scripts/check_style_tokens.py`) — the enforced half of
  the design language (`docs/design/design-language.md` §5): hex/rgb color
  literals and non-token `font-size` in frontend style code fail — no per-file
  exemption (#1681). Sanctioned exceptions are listed in the script's docstring;
  build outputs are skipped via the ratcheted `GENERATED_ROOTS` list.
