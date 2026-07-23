# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

This file is loaded into **every request of every session**, so it holds rules,
not explanations. The reasoning behind the non-obvious ones lives in
`docs/development/` — read those when a rule looks arbitrary or something is
misbehaving, not by default.

## What this is

A private, **local-first** fiction-writing app. A Python/FastAPI service exposes
a local HTTP API over a **file-based project format**; a Svelte 5 + TipTap
browser UI talks to it at `http://127.0.0.1:8787`. Files on disk are the source
of truth — caches and indexes (`.cache/`) are always rebuildable, and the
frontend never mutates project files directly (all writes go through intentful
backend endpoints: save scene, move node, create todo, …).

## Commands

```powershell
# Backend (FastAPI on :8787, auto-reload) — canonical invocations in .claude/launch.json
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8787 --reload --reload-dir backend
npm run dev --prefix frontend                                    # Vite dev server on :5173

# First-time backend setup
cd backend; python -m venv .venv; .venv\Scripts\python -m pip install -e ".[dev]"

# Gates — run after edits, fix before considering a task done
backend/.venv/Scripts/python.exe -m pytest backend/tests                    # all backend tests
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_ai_chat.py::test_name -q
backend/.venv/Scripts/python.exe -m ruff check backend                     # config: backend/pyproject.toml
npm run check --prefix frontend                                            # svelte-check — must stay clean
npm run build --prefix frontend
```

- After `ruff check --fix`, **re-run** `ruff check` and the tests — an autofix can
  resolve one rule into a new finding.
- Bare `uvicorn` without `--reload` does **not** pick up Python changes; restart it.

## Starting new work

**The primary working tree is Anton's. Claude work happens in a linked worktree
— always.** Start with the **EnterWorktree** tool (this paragraph is what
authorises it). It forks `origin/master`, never local `HEAD`.

This is an invariant, not etiquette — Anton keeps uncommitted WIP in the primary
tree, and both a broad `git add` and `pre-commit`'s stash have destroyed
concurrent work there. → `docs/development/worktrees.md`

- **The one carve-out:** work depending on *unmerged* work forks the
  dependency's branch, explicitly, and says so in the PR. **One work lane** —
  sequence dependent work rather than running it in parallel.
- **Everything lands via a PR.** The `master gates` ruleset requires the three
  checks and blocks direct and force pushes. No fast path for a one-line fix.
- **Check `git branch --show-current` immediately before committing**, not just
  at session start.
- **Stage explicit paths.** Never `git add <dir>` / `-A` / `.`; check
  `git diff --cached --name-only` before every commit.
- **Never link or junction a shared `node_modules`/venv into a worktree** — a
  recursive delete walks the link and guts the primary install (#350).
- Let a worktree's `npm install` happen when a session first needs frontend
  gates, not upfront. Docs-only work never needs it.
- **Clean up when the PR merges**: `ExitWorktree` with `remove`. Stale worktrees
  are not free — each with a `node_modules` adds ~24k files under the repo root.

### Running the app from a worktree — start the servers yourself

**`preview_start` by config *name* runs the PRIMARY tree's code from any
worktree** (#360) — which is Anton's WIP and his live projects. So in a worktree,
start the servers by hand (an approved exception to the "never use Bash for dev
servers" guidance) and open the Browser pane on the URL:

```bash
python scripts/dev_backend.py                              # background it; publishes the port
PORT=5199 npm run dev --prefix frontend -- --mode claude   # background it
```

Then `preview_start {url: "http://127.0.0.1:5199"}` and verify with `read_page`,
`read_network_requests`, and the console.

- **Never pick the backend port by hand** — `dev_backend.py` derives it from this
  checkout's path. Hand-picking silently shares a port on Windows (#364).
- Read the startup line rather than assuming isolation: `dev_backend: verified
  <path> is serving 127.0.0.1:<port>` names the checkout actually being served.
- **To stop a server, kill the process *tree*, and don't trust the PID the OS
  reports** — `taskkill /F /T /PID <reloader pid>`. → `docs/development/worktrees.md`
- A `SessionEnd` hook now stops this worktree's own dev servers automatically
  (#452). It never touches another tree's, so killing one by hand mid-session is
  still yours to do.

## Quality gates

Three machine-enforced layers: an in-session `PostToolUse` hook on every edit,
`pre-commit` on commit, and CI (`.github/workflows/gates.yml`) on every PR — the
only layer that cannot be walked past with `--no-verify`. Full mechanics,
setup, and the exemption ratchet: → `docs/development/quality-gates.md`

- **When a gate goes red, fix the code — never widen the exemption.** The
  ratchet (`scripts/check_exemptions.py`) fails on any new `GRANDFATHERED` entry,
  widened ruff `ignore`, dropped `select` rule, or new skip/xfail. If a new
  exemption is genuinely right, say so explicitly in the PR.
- **Never report "green" without opening the run.** `gh pr checks` can show a
  green table for an earlier commit.
- **File-size guard**: warns ≥1200, **fails ≥1500** lines on `.py/.svelte/.ts`.
- **Style-token guard**: hex/rgb literals and non-token `font-size` in frontend
  style code fail (`docs/design/design-language.md` §5).
- **`MEMORY.md` ratchets** — it is loaded on every request, so it may shrink and
  never grow. If a new memory doesn't fit, merge or retire an old one; keep the
  index to one pointer line per memo and the content in the memo.
- The citation-rot checker is **advisory**, PR-scoped, and **flags but never
  fixes** — repointing a stale line turns visible rot into invisible rot.

**Where do I stop splitting? Match the target shapes, don't guess:**
- a new **endpoint** = thin route in `main.py` → logic in a `services/<area>.py`
  mixin (composed onto `ProjectService` via MRO) → models in `models.py`. No
  business logic in `main.py`.
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

### Node model
Almost everything generalizes to a **Node** with metadata + references. The
class–instance model: `kind` = class, `entry_type` = sub-class, `entry` =
instance. **Read `memory/architecture_class_instance_model.md` before touching
the kind whitelist**, and `memory/strategy_node_model.md` for the shape. Chat is
a Node kind; resist making any new thing "special enough to need its own
subsystem" (`feedback_chat_as_node_validation.md`).

### Backend layout (`backend/app/`)
- `main.py` — the FastAPI app and ~90 HTTP routes (thin; delegates to services).
- `models.py` — Pydantic request/response models (large, central).
- `services/project_service.py` — `ProjectService`: project CRUD, scenes, schema,
  search, structure. Cohesive slices live in mixins under `services/project/`
  (`chats`, `lore`, `prompts`, `assistants`, `node_index`, `tree_structure`),
  composed via MRO. The import path
  `app.services.project_service.ProjectService` stays stable.
- `services/ai/` — provider abstraction. `profiles/` holds per-provider profiles
  (anthropic/openai/openrouter/ollama) + a `registry` and baked-in
  capability/price data; `templates.py` (Jinja2 prompts), `context_expander.py`,
  `sessions.py`, `tokens.py`, `preview.py`.
- `services/migrations.py` — **pre-1.0: do not write migrations or defensive
  reads** for storage-format changes; test projects are recreated
  (`feedback_no_pre_1_0_migrations.md`).

### Frontend layout (`frontend/src/`)
Flat directory of ~36 `.svelte` components plus `.ts` helpers. `App.svelte` is
the large root shell. `api.ts` is the single HTTP client to the backend. Core
reusable widgets: `NodeRow`, `NodeList`, `NodeEditor` (+ body views
`ProseBodyView`/`CodeBodyView`/`ChatBodyView`). **Read
`memory/decisions_ui_widget_taxonomy.md` before adding any list/row/color
treatment**, and the NodeEditor/metadata decision memos before touching those.

## Conventions

- **Vocabulary** (from `AGENTS.md`): `Lore` = the collection, `Entry` (UI) /
  `LoreEntry` (code) = an item, `Scene` = atomic prose file, `Manuscript
  Structure` = act/chapter/scene ordering. **Never** call story info "Codex".
- **No monolithic files**: split before any file passes ~1500 LOC
  (`feedback_no_monolithic_source_files.md`).
- **No compile errors, minimal warnings**: never wave off `svelte-check` issues as
  pre-existing — fix or explicitly flag
  (`feedback_no_compile_errors_minimal_warnings.md`).
- Atomic writes for prose and structure files; keep backend mutations intentful.
- Currency: backend stores USD, API fields use `_usd` suffix; frontend converts
  to EUR for display.
- Pane drag/resize in `App.svelte` deliberately uses document-level
  mousemove/mouseup + direct DOM style updates — do **not** "simplify" without
  re-testing drag in the real browser (see `AGENTS.md`).
- Svelte 5 reactivity has traps — see `memory/feedback_svelte5_reactivity_traps.md`.

## Working in this repo (context hygiene)

Context length is the dominant cost in this repo: measured across recent
sessions, a model step at 500k tokens of context takes ~3.5× one at 50k, and a
single prompt averages ~24 steps. Everything you pull into context is paid for
on every subsequent step of the session.

- **Delegate broad searches.** For "where/how is X done?" spanning several files
  or a monolith, use an `Explore` (or `general-purpose`) subagent — its reading
  never enters your context, only its summary and `file:line` pointers. Launch
  independent searches in parallel.
- **Read directly when you already know the target** file+line, or for a
  single-fact lookup. Don't delegate what's faster to just read.
- **Read narrowly.** `App.svelte` (~4900 LOC) and `project_service.py` (~4500)
  cost thousands of tokens on every later step if read whole. Use
  `offset`/`limit`, or `Grep` for the line first.
- **Subagents return summaries, not editable context.** To edit, pull the
  specific region in with `Read` and edit that.
- **Verify, don't assert.** Prefer running `ruff`/`pytest`/`npm run check` over
  claiming behaviour. A one-line clarifying question beats a wrong 200-line diff.

## Reference material

- `memory/MEMORY.md` — index of persistent design decisions and working-style
  feedback; read the linked memos before touching the areas they name.
- `docs/development/` — worktree and quality-gate mechanics (the *why* behind
  the rules above).
- GitHub Issues are the canonical backlog (`gh issue list`); milestones hold the
  roadmap. Do not invent backlog files.
- `docs/` — deep dives: `metadata-strategy.md`, `ai-model-selection.md`,
  `context-picker.md`, `roleplay.md`, `research-strategy.md`,
  `schema-yaml-howto.md`, `editor-todo-invariants.md`, and `docs/prompts/`.
