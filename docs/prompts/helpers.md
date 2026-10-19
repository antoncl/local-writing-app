# Helpers — implementation notes

How the functions a prompt can call are built and registered. **What each helper
does** — its arguments, what it returns, examples, caveats — is documented once, for
authors, in [reference.md](reference.md#helpers). This page doesn't repeat it.

## Registration

Every helper is a global on the per-render sandboxed environment, installed by:

```python
register_helpers(env, project, session=None, journal=None) -> None   # services/ai/helpers.py
```

`session` and `journal` are accepted for compatibility only. They fed the retired
emitting `relevant_lore()` global. The send path's lore selector now gets them
directly (`services/ai/chat.py`). Render paths call
`create_environment_for_project()`, which builds the environment, installs the
snippet loader and calls `register_helpers()` (see
[template-language.md](template-language.md#the-environment)).

Helpers come in three shapes:

- **Pure** — `last_words`, `prose`: plain functions, no project state.
- **Project-bound** — most helpers (`entry`, `pov`, `story_so_far`, `full_outline`,
  …): closures over the `ProjectService` and the merged metadata schema, bound when
  the environment is built.
- **Stateful** — `use`, `auto_lore`, `no_lore`, `lore_as_of`, `field_contract`:
  each records what the template did in a **per-render slot on the environment** (the `use()` picks, the
  `auto_lore()` flag, the stored field contract, …). `build_preview` reads those
  slots back onto the `RenderedTemplate` after the render. Environments are built
  per render, so this state never leaks from one render to the next.

The mutation index that as-of reads need is built lazily — at most once per
environment, shared by every helper that resolves an entry — so a template that
reads no entries never builds it.

## Resolution: as of the prompt's scene

Every read is resolved **as of the prompt's scene** (ADR-0012): `entry(x)`,
`scene.pov.rank` and the placed lore all see the values in effect at the end of that
scene. `entry(x, at=…)` moves the anchor, `original(x)` reads book-start, and a
scene-less prompt reads book-start throughout. The author-facing account, with the
timeline diagram, is [reference.md § As of this scene](reference.md#as-of-this-scene).

## `EntryRef`

`entry()`, `original()`, `pov()` and every resolved reference field return an
`EntryRef` (`services/ai/entry_ref.py`) — a lazy wrapper that reads the node only
when a template touches something other than its id:

- `.id` / `.raw_id` never load. `.found` says whether the id resolves.
- `.title` falls back to the id when the node is missing; `str(ref)` is the title,
  so `{{ ref }}` prints a name.
- `.body` is the story text, with the app's markers removed.
- `.metadata.<field>` and the shortcut `.<field>` read a field. A reference field
  resolves to a child `EntryRef` (or a list of them). A **group label** resolves to
  a view over that group's fields (`entry.GMO.Goal`). Subscript mirrors attribute
  access, for labels that aren't identifiers (`entry["Antagonist GMO"]`).
- Ids are canonicalised on load, so a reference to a merged tag reads as the tag
  that survived (ADR-0082 §5).
- Each reference hop increases a depth counter. Past **6 hops**
  (`_ENTRY_REF_MAX_DEPTH`) a ref stops loading and reads as its bare id — a ceiling
  for runaway cycles. The editor's completion mirrors it
  (`MAX_REF_HOPS` in `frontend/src/lib/promptCompletion.ts`).

## Adding a helper

1. **Write the logic in its own module** under `services/ai/`. `helpers.py` is near
   the 1500-line cap and should only register (ADR-0098, ADR-0099).
2. **Register it in `helpers.py`** with a literal `env.globals["name"] = …` (or
   `env.filters[...]`). The vocabulary gate (`scripts/check_prompt_vocab_docs.py`)
   finds the registered names by parsing that file, so a registration elsewhere is
   invisible to it.
3. **Test it** in `backend/tests/test_ai_helpers*.py`.
4. **Document it in [reference.md](reference.md)**: a row in the right *At a glance*
   table under `## Helpers`, plus an *In detail* entry. The gate fails until the
   documented names match the registered ones. Renaming or retiring a name adds a
   row to *Retired names*.
5. **Regenerate the bundled artifacts** —
   `python scripts/gen_prompt_vocab.py` (the editor's completion manifest) and
   `python scripts/gen_guides.py` (the in-app guides). pre-commit checks both are
   current.
6. If a built-in prompt should use it, update the built-in. Built-ins are worked
   examples in the public vocabulary.

## Implementation reference

- Registration: [`backend/app/services/ai/helpers.py`](../../backend/app/services/ai/helpers.py) — `register_helpers`, `create_environment_for_project`
- `EntryRef`: [`backend/app/services/ai/entry_ref.py`](../../backend/app/services/ai/entry_ref.py)
- Tests: `backend/tests/test_ai_helpers.py`, `test_ai_helpers_as_of.py`, `test_prompt_vocab.py`
