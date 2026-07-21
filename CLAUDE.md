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
   guards **repo-wide**, not just over staged files. Private repo, so minutes
   are billed: `ubuntu-latest` only, two parallel jobs, superseded runs
   cancelled — keep it that way.

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
`metadata.schema.yaml` from `settings.projects_base_folder` down to the open
project folder**, with nearer folders overriding farther ancestors. This lets
users model world/series/book levels purely by folder depth — the app does not
hardcode those concepts. A `metadata.schema.yaml` is only created at a layer when
a definition is saved there.

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
