# `docs/` — documentation index

This folder holds **two kinds of documentation for two different audiences**, and
nothing used to mark which was which. This index is the map: for everything under
`docs/`, it says whether the file is a **user guide** (shipped inside the app) or a
**dev / design** doc (for contributors).

> Rule of thumb: a file listed under **User guides** below is reader-facing product
> copy — write it for a writer *using* the app. Everything else is for contributors
> and never ships.

## User guides — bundled into the in-app guide viewer

These eleven files are the **sources** for the in-app Guides pane. The bundle
`frontend/src/lib/guides.ts` is **generated** from them by `scripts/gen_guides.py`
and held regen-clean by `--check` in pre-commit and CI (the same drift-safe pattern
as the prompt-vocab manifest). **Edit the source `.md` here; never hand-edit the
generated `guides.ts`** — run `python scripts/gen_guides.py` after a change.

Listed in the viewer's display order (Getting started is the default landing guide):

| In-app title | Guide `id` | Source |
| --- | --- | --- |
| Getting started | `getting-started` | [getting-started.md](getting-started.md) |
| Lore | `lore` | [lore.md](lore.md) |
| Custom fields | `custom-fields` | [custom-fields.md](custom-fields.md) |
| Mutations | `mutations` | [mutations.md](mutations.md) |
| Views | `views` | [views.md](views.md) |
| Plotting | `plotting` | [plotting.md](plotting.md) |
| Turning on AI | `ai-setup` | [ai-setup.md](ai-setup.md) |
| Writing prompts | `writing-prompts` | [prompts/guide.md](prompts/guide.md) |
| Context picker | `context-picker` | [context-picker.md](context-picker.md) |
| Roleplay | `roleplay` | [roleplay.md](roleplay.md) |
| Prompt reference | `reference` | [prompts/reference.md](prompts/reference.md) |

The mapping above is owned by `GUIDES` in `scripts/gen_guides.py`. If you add,
remove, or reorder a guide there, update this table to match.

## Dev / design docs — for contributors, not shipped

### Top-level design notes & how-tos

- [project-brief.md](project-brief.md) — what the app is: product vision and scope.
- [frontend-architecture.md](frontend-architecture.md) — frontend structure and the refactoring criteria.
- [metadata-strategy.md](metadata-strategy.md) — the layered metadata schema and the field model.
- [ai-model-selection.md](ai-model-selection.md) — provider profiles and capability-tier model selection.
- [research-strategy.md](research-strategy.md) — the research node kind and its flat storage.
- [editor-todo-invariants.md](editor-todo-invariants.md) — the invariants TODO/editor ownership rests on.
- [schema-yaml-howto.md](schema-yaml-howto.md) — editing `metadata.schema.yaml` by hand (contributor reference).

### [`design/`](design/) — architecture & decision records

The rationale behind the code. Start with the ADRs:

- [`design/adr/`](design/adr/README.md) — the numbered Architecture Decision Records (ADR-0001…), the canonical "why" behind each decision; see its own README index.
- Design notes sit alongside — e.g. [design-language.md](design/design-language.md), [invocation-model.md](design/invocation-model.md), [views-and-filters.md](design/views-and-filters.md) — with `design/mockups/` (HTML mockups) and `design/spikes/` (exploratory write-ups).

### [`development/`](development/) — the contributor rulebook

The rules a change must meet and the mechanics behind them:

- [code-standards.md](development/code-standards.md) — the standards a change must satisfy.
- [quality-gates.md](development/quality-gates.md) — the three enforcement layers and why each exists.
- [worktrees.md](development/worktrees.md) — why the worktree rules are what they are.
- [releasing.md](development/releasing.md) — the runbook for cutting a version.

### [`prompts/`](prompts/) — prompt-authoring internals

**Note:** `prompts/guide.md` and `prompts/reference.md` are the two *bundled user
guides* listed above. Everything else here is contributor-facing:

- [prompts/README.md](prompts/README.md) — overview of the prompts & AI docs.
- [prompts/template-language.md](prompts/template-language.md) — the Jinja template language.
- [prompts/helpers.md](prompts/helpers.md) — the type-aware helpers and filters.
- [prompts/snippets-and-prompts.md](prompts/snippets-and-prompts.md) — how snippets relate to prompts.
- [prompts/chat.md](prompts/chat.md), [prompts/generate.md](prompts/generate.md), [prompts/preview.md](prompts/preview.md) — the per-surface prompt bases.

### [`spikes/`](spikes/) — throwaway experiments

Time-boxed benchmarks and prototypes kept for their findings (e.g. the client-diff
bench). Not part of the product or the build.
