# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A private, **local-first** fiction-writing app. A Python/FastAPI service exposes
a local HTTP API over a **file-based project format**; a Svelte 5 + TipTap
browser UI talks to it at `http://127.0.0.1:8787`. Files on disk are the source
of truth — caches and indexes (`.cache/`) are always rebuildable, and the
frontend never mutates project files directly (all writes go through intentful
backend endpoints: save scene, move node, create todo, …).

## Commands

Run both processes from the repo root. The canonical dev invocations live in
`.claude/launch.json`:

```powershell
# Backend (FastAPI on :8787, auto-reload)
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8787 --reload --reload-dir backend

# Frontend (Vite dev server on :5173)
npm run dev --prefix frontend
```

First-time backend setup:
```powershell
cd backend; python -m venv .venv; .venv\Scripts\python -m pip install -e .
```

Tests, lint, type-checking, build:
```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests           # all backend tests
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_ai_chat.py::test_name -q   # single test
backend/.venv/Scripts/python.exe -m ruff check backend           # backend lint (config in pyproject.toml)
backend/.venv/Scripts/python.exe -m ruff check backend --fix     # apply safe autofixes
npm run check --prefix frontend     # svelte-check — must stay clean (no errors, minimal warnings)
npm run build --prefix frontend
```

**Verification gates** (run after edits, fix before considering a task done):
backend = `ruff check backend` + `pytest backend/tests`; frontend = `npm run check`.
Ruff config lives in `backend/pyproject.toml` (`[tool.ruff]`); install it with
`pip install -e ".[dev]"`. Note: ruff's autofix can resolve one rule into a new
finding (e.g. collapsing an `if` then tripping a "combine branches" rule) — always
re-run `ruff check` and the tests after `--fix`, don't assume one pass is clean.

Note: bare `uvicorn` without `--reload` does **not** pick up Python changes —
restart it after editing backend code.

## Starting new work

**The primary working tree is Anton's. Claude work happens in a linked
worktree — always.** Start with the **EnterWorktree** tool (this paragraph is
what authorises it); it creates a worktree under `.claude/worktrees/` and moves
the session into it. `worktree.baseRef` is pinned so the branch forks
**`origin/master`**, never local `HEAD`.

This is an invariant, not etiquette. It is what three separate rules used to
ask you to remember, and it retires all three:

- Anton keeps uncommitted WIP in the primary tree. A broad `git add` has swept
  it into a commit before, and `pre-commit`'s stash — a patch file under
  `~/.cache/pre-commit`, *not* a git stash, so `git stash list` looks empty —
  reverts the tree repo-wide while it runs. In a separate directory, neither
  can reach his files.
- HEAD used to drift mid-session: another session merges a PR, its branch is
  deleted, and the shared tree silently lands on `master`. A private worktree
  has a private HEAD.
- `origin/master` as the base is now the harness's job, not yours. Reading a
  floating `HEAD` is what produced the wrong-branch commit this policy came from.

**The one carve-out:** work that genuinely depends on *unmerged* work forks the
dependency's branch, explicitly, and says so in the PR. Forking `master` for a
dependent slice is what got #312 rolled back. Prefer not to be in that position
at all — **one work lane** still stands; sequence dependent work rather than
running it in parallel.

Mechanics:

- **Everything lands via a PR.** The `master gates` ruleset requires the three
  checks, requires a PR, and blocks direct pushes and force-pushes to `master`.
  There is no fast path for a one-line fix, by design.
- **Check the branch immediately before committing**, not just at session
  start — `git branch --show-current`. Cheap, and it catches the case above.
- **A worktree gets its own `node_modules`** (`scripts/npm_run.py` runs a real
  `npm install`). That costs minutes and disk, so let it happen when a session
  first needs frontend gates, not upfront — docs-only work never needs it.
  **Never link or junction a shared `node_modules`/venv into a worktree**; see
  the gates section for why that is destructive.
- **Clean up when the PR merges**: `ExitWorktree` with `remove`. It refuses
  while uncommitted changes or unmerged commits remain, which is the behaviour
  you want.
- A worktree is a **fresh checkout**, so gitignored files do not come along. If
  some future local file must be present in every worktree, list it in a
  `.worktreeinclude` at the repo root (`.gitignore` syntax; only gitignored
  matches are copied) rather than copying it by hand.

### Running the app from a worktree — start the servers yourself

**`preview_start` by config name resolves `.claude/launch.json` from the
PRIMARY tree, so it runs the primary tree's code no matter which worktree the
session is in** (#360, verified: a fresh start from a worktree watched
`<primary>/backend`, wrote no port file, and used a config the worktree had
rewritten). That is the same defect as #352 — a verification path exercising
the wrong tree — and it is worse than for the gates, because the primary tree
holds Anton's WIP *and his live projects*. A worktree session that believes it
is driving an isolated backend would be driving his.

**So in a worktree, start the dev servers yourself and point the Browser pane
at the URL.** This is a deliberate, Anton-approved exception to the general
"never use Bash to run dev servers" guidance, which predates worktree
isolation:

```bash
# backend first — it publishes the port the frontend reads
python scripts/dev_backend.py                    # background it
PORT=5199 npm run dev --prefix frontend -- --mode claude   # background it
```

Then `preview_start {url: "http://127.0.0.1:5199"}` — the `url` form opens a
browser tab without starting a server — and verify with `read_page`,
`read_network_requests`, and the console as usual.

**Don't pick the backend port by hand.** `dev_backend.py` derives it from *this
checkout's path* (8800–8899), which separates sibling worktrees; `PORT` still
overrides, and is the escape hatch if two checkouts ever hash to the same slot
(1-in-100, and it now fails loudly rather than silently). Hand-picking is how
#364 happened: every worktree defaulted to `8788`, and on Windows
`uvicorn --reload` binds with `SO_REUSEADDR` — which Windows reads as "share
this address" when both sides set it, as every `--reload` server does. The
second start then **succeeds silently**, receives nothing, and the first tree's
server answers every request. The launcher now refuses an occupied port up
front, and after startup makes the server prove it is the one just started (a
per-launch nonce over `/__dev_backend_provenance`, served by
`scripts/dev_backend_app.py`). It publishes `tmp/dev-backend-port` only once
that passes, so the frontend inherits the guarantee — `--mode claude` hard-fails
on a missing port file rather than showing another tree's data.

Read the startup line rather than assuming isolation: `dev_backend: verified
<path> is serving 127.0.0.1:<port>` names the checkout actually being served.

**Stopping them: kill the process tree, not the process — and don't trust the
PID the OS gives you.** `uvicorn --reload` spawns a `multiprocessing` child that
survives its parent and keeps holding the port. Worse, `netstat -ano` and
`Get-NetTCPConnection` both report the socket against the *reloader* that
created it, which by then is usually **dead** — so you kill that PID, it
"succeeds", and the port keeps serving. This is exactly how #364's "I killed
every listener on the port" step produced a false negative and sent the
diagnosis after the import system instead. Ask the server who it is
(`curl 127.0.0.1:<port>/__dev_backend_provenance` returns the real pid), or find
the live child:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*multiprocessing*' } |
  Select-Object ProcessId,ParentProcessId
taskkill /F /T /PID <the reloader pid>   # /T is the part that matters
```

## Automated quality gates

The standards below are **machine-enforced** — they no longer depend on
remembering to run a command (a rule that lives only in prose drifts under
context pressure; that is how `App.svelte` reached ~4900 lines). Three layers,
weakest → strongest:

1. **In-session** — a Claude Code `PostToolUse` hook
   (`.claude/hooks/check_edited_file.py`, wired in `.claude/settings.json`) runs
   the file-size guard + the style-token guard + `ruff` on **every file you
   edit** and feeds any violation straight back into context. Fix it before
   declaring the task done.
2. **Git hooks** (`.pre-commit-config.yaml`) — *commit only*, and fast: `ruff`
   (blocking) + advisory complexity + the file-size and style-token guards on
   staged files. **There is deliberately no push stage** — the slow whole-project
   gates moved to CI (#352). `ruff` covers `backend/`,
   `scripts/` **and** `.claude/hooks/` — the gate machinery is held to the rules
   it enforces (#352); the root `.ruff.toml` extends `backend/pyproject.toml` so
   files outside `backend/` don't fall back to ruff's weaker defaults.
   One-time setup per clone:
   `backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"`, then
   `backend/.venv/Scripts/pre-commit install` — **not** `… -t pre-push`; if an
   old clone has one, `pre-commit uninstall -t pre-push` removes it.

3. **CI** (`.github/workflows/gates.yml`, #352) — the same gates on a **clean
   checkout**, on every PR and every push to master. It is the only layer that
   cannot be walked past with `--no-verify`, and the only one immune to the
   local hazards below (a worktree importing the primary tree's code; a
   concurrent session writing into the shared tree mid-run). It runs the two
   guards **repo-wide**, not just over staged files. Three jobs: `backend` and
   `frontend` on Linux, plus `backend-windows` — this is a Windows-first app and
   the bugs that bite are platform ones (junctions, cp1252, path separators,
   CRLF). The repo is public, so runner minutes are free; optimise for signal,
   not cost.
   **The checks are REQUIRED** — the `master gates` ruleset blocks merging a red
   PR, blocks direct pushes to master, and blocks force-push/deletion. Still:
   **never report "green" without opening the run.**

The **exemption ratchet** (`scripts/check_exemptions.py`, CI, PRs only) is the
guard on the guards: every escape hatch may shrink, never grow. It compares this
branch against the PR base and fails on a new `GRANDFATHERED` entry, a widened
ruff `ignore` or `per-file-ignores`, a rule dropped from `select`, or a newly
skipped/xfailed test. **When a gate goes red, fix the code — do not widen the
exemption.** If a new exemption is genuinely right, say so explicitly in the PR
rather than letting it ride along in a diff; once it lands, the base moves and
the ratchet re-arms. Run it locally with
`python scripts/check_exemptions.py --base origin/master`.

The **citation-rot checker** (`scripts/check_citations.py`,
`.github/workflows/citation-rot.yml`, #397) is the one **advisory** gate, and
deliberately not part of `gates.yml`: a PR must not go red because an unrelated
issue got stale. It verifies `path:line` claims in issue bodies, ADRs and docs
against the code, anchoring each on the symbol the prose names next to it —
which is what catches the dangerous shape, a line number that is still valid
and now lands on unrelated code. **It runs on PRs only**, commenting about the
files that diff touches — rot is caught by the person creating it, while the
context is still in their head. A weekly repo-wide run once edited a standing
tracking issue (#407); that was retired in 2026-07 because a permanently-open
issue restating rot is a log, not a fix. **It flags, it never
fixes**: repointing a stale line number yields a citation that resolves cleanly
and still does not support the sentence, which turns visible rot into invisible
rot. The repo-wide sweep still exists in the script — run it by hand before a
release, and note that `python scripts/check_citations.py --memory-dir <memory>`
is the only run that can see the memory files, since CI cannot.

**In a linked git worktree** the gates must test *that* worktree's code.
`scripts/venv_run.py` borrows the primary worktree's *interpreter* but forces
this checkout's `backend/` onto `PYTHONPATH` (#352 — otherwise the editable
install silently imports the primary tree's `app`), and `scripts/npm_run.py`
runs a real `npm install` in the worktree. **Never link or junction a shared
`node_modules`/venv into a worktree**: a recursive delete — `git worktree
remove -f` among them — walks through the link and guts the primary install
(#350, and `memory/feedback_never_junction_shared_venv.md`).

The **file-size guard** (`scripts/check_file_size.py`) is the enforced half of
"no monolithic files": warns ≥1200, **fails ≥1500** lines on `.py/.svelte/.ts`.
Files knowingly over the cap are listed in that script's `GRANDFATHERED` set
(currently `test_metadata_validation.py`) — split them when you next work there,
then delete the entry. The **style-token guard**
(`scripts/check_style_tokens.py`) is the enforced half of the design language
(`docs/design/design-language.md` §5): hex/rgb color literals and non-token
`font-size` in frontend style code fail, with its own shrink-to-zero
`GRANDFATHERED` set (#129) — sanctioned exceptions are in the script's
docstring. The manual gates still apply when iterating
(`ruff check backend` + `pytest backend/tests`; `npm run check`).

**Where do I stop splitting? Match the target shapes, don't guess:**
- a new **endpoint** = a thin route in `main.py` → logic in a `services/<area>.py`
  mixin (composed onto `ProjectService` via MRO) → request/response models in
  `models.py`. No business logic in `main.py`.
- a new **pane / list UI** = compose `NodeList` + `NodeRow` with a scoped
  `<style>`; domain state lives in a `lib/stores/*.svelte.ts` rune controller,
  not the component. A bespoke list that won't reduce to those widgets is the
  smell to question, not to hand-roll.

## Architecture

### Project format (on disk)
A project is a folder: `project.yaml`, `manuscript.structure.yaml`,
`metadata.schema.yaml`, and `scenes/ lore/ prompts/ todo.yaml .cache/`. Scenes
are Markdown with YAML front matter; the front-matter `id` is canonical identity
(filenames are not). The manuscript tree (acts/chapters/scenes ordering) lives in
`manuscript.structure.yaml`, separate from prose.

### Layered metadata schema
The app ships a minimal built-in schema, then **merges every
`metadata.schema.yaml` from the ancestor projects the open project *declares*
(`inherits:`) down to itself**, with nearer folders overriding farther ancestors.
This lets users model world/series/book levels purely by folder depth — the app
does not hardcode those concepts. A `metadata.schema.yaml` is only created at a
layer when a definition is saved there.

Two rules bound that walk, and both were once a per-project manifest key:
- **Where it stops** is the *machine* root — `default_projects_folder` in
  machine settings, one folder for every project (#429). A project outside it,
  or a machine with none set, is a chain of length one.
- **What it includes** is the project's own `inherits:` declaration (#309).
  Absent means it inherits nothing; the declaration can only *select* from the
  folders between the machine root and the project, never extend past them.

### Node model (read `memory/strategy_node_model.md` and `architecture_class_instance_model.md`)
Almost everything generalizes to a **Node** with metadata + references. The
class–instance model: `kind` = class, `entry_type` = sub-class, `entry` =
instance. **Read `architecture_class_instance_model.md` before touching the kind
whitelist.** Chat is a Node kind; resist making any new thing "special enough to
need its own subsystem" (see `feedback_chat_as_node_validation.md`).

### Backend layout (`backend/app/`)
- `main.py` — the FastAPI app and ~90 HTTP routes (thin; delegates to services).
- `models.py` — Pydantic request/response models (large, central).
- `services/project_service.py` — `ProjectService`, the core class for project
  CRUD, scenes, schema, search, structure. Being decomposed (issue #14): cohesive
  slices move into mixins under `services/project/` (`chats`, `lore`, `prompts`,
  `assistants`, plus `node_index`, `tree_structure`), composed via MRO. The import
  path `app.services.project_service.ProjectService` stays stable.
- `services/ai/` — provider abstraction. `profiles/` holds per-provider profiles
  (anthropic/openai/openrouter/ollama) + a `registry` and baked-in capability/price
  data; `templates.py` (Jinja2 prompts), `context_expander.py`, `sessions.py`,
  `tokens.py`, `preview.py`.
- `services/migrations.py` — schema versioning. **Pre-1.0: do not write
  migrations or defensive reads** for storage-format changes; test projects are
  recreated (`feedback_no_pre_1_0_migrations.md`).

### Frontend layout (`frontend/src/`)
Flat directory of ~36 `.svelte` components plus `.ts` helpers. `App.svelte` is the
large root shell (being decomposed alongside #14). `api.ts` is the single HTTP
client to the backend. Core reusable widgets: `NodeRow`, `NodeList`, `NodeEditor`
(+ body views `ProseBodyView`/`CodeBodyView`/`ChatBodyView`). **Read
`memory/decisions_ui_widget_taxonomy.md` before adding any list/row/color
treatment**, and the NodeEditor/metadata decision memos before touching those.

## Conventions

- **Vocabulary** (from `AGENTS.md`): `Lore` = the collection, `Entry` (UI) /
  `LoreEntry` (code) = an item, `Scene` = atomic prose file, `Manuscript
  Structure` = act/chapter/scene ordering. **Never** call story info "Codex".
- **No monolithic files**: split before any file passes ~1500 LOC
  (`feedback_no_monolithic_source_files.md`).
- **No compile errors, minimal warnings**: never wave off `svelte-check` issues as
  pre-existing — fix or explicitly flag (`feedback_no_compile_errors_minimal_warnings.md`).
- Atomic writes for prose and structure files; keep backend mutations intentful.
- Currency: backend stores USD, API fields use `_usd` suffix; frontend converts
  to EUR for display.
- Pane drag/resize in `App.svelte` deliberately uses document-level
  mousemove/mouseup + direct DOM style updates — do **not** "simplify" without
  re-testing drag in the real browser (see `AGENTS.md`).
- Svelte 5 reactivity has traps — see `memory/feedback_svelte5_reactivity_traps.md`.

## Working in this repo (context hygiene)

This codebase has large files (`App.svelte` ~4900 LOC, `project_service.py`
~4500 LOC). Reading one whole to answer a narrow question floods context, so:

- **Delegate broad searches.** For "where/how is X done?" that spans several files
  or means scanning a monolith, use an `Explore` (or `general-purpose`) subagent —
  it reads excerpts and returns a summary + `file:line` pointers, not raw dumps.
  Launch independent searches in parallel.
- **Read directly when you already know the target** file+line, or for a
  single-fact lookup. Don't delegate what's faster to just read.
- **Subagents return summaries, not editable context.** To actually edit, pull the
  specific function/region into context with `Read` (use `offset`/`limit` on the
  big files) and edit that — don't try to edit from a subagent's summary alone.
- **Verify, don't assert.** Prefer running `ruff`/`pytest`/`npm run check` to
  confirm behavior over claiming it (this session's ruff pass caught two regressions
  that looked fine on paper). A one-line clarifying question beats a wrong 200-line diff.

## Reference material

- `memory/MEMORY.md` — index of persistent design decisions and working-style
  feedback; read the linked memos before touching the areas they name.
- GitHub Issues are the canonical backlog (`gh issue list`); milestones hold the
  roadmap. Do not invent backlog files.
- `docs/` — deep dives: `metadata-strategy.md`, `ai-model-selection.md`,
  `context-picker.md`, `roleplay.md`, `research-strategy.md`,
  `schema-yaml-howto.md`, `editor-todo-invariants.md`, and `docs/prompts/`.
