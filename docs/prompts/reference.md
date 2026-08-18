# Prompt language reference — the typed surface

This is the **completion contract** for the prompt template language (ADR-0060 §8):
every variable, helper, filter, and tag, with its declared return type or shape.
The language guarantees it is completable so the editor's code-completion has a
stable target — even though the completion UI itself is delivered separately.

Two rules make it typeable:

- **A node's `entry_type` determines its fields.** Field access is uniform
  attribute access (`node.field`) resolved through the metadata schema; an
  `entity_ref` field resolves to its target `entry_type`, so completion chains
  (`entry(x).home_place.title`). `.metadata` is the explicit whole-map escape.
- **Dynamic arguments infer their type from declarations.** `entry(inputs.character)`
  completes from the input's declared target `kinds`/`entry_types`; a literal
  `entry("honor")` from the node index. An untyped or unconstrained argument
  degrades gracefully to the intrinsics (`id`, `title`, `body`, `entry_type`) —
  never a wrong guess.

Everything below is resolved **as of the prompt's one scene** (ADR-0012); a
scene-less prompt reads book-start values, so `entry(x) == original(x)` there.

## Variables

| Name | Type / shape |
| --- | --- |
| `scene` | The prompt's scene node (`manuscript:scene`) or `None`. `scene.title`, `scene.body`, `scene.<field>` (e.g. `scene.pov`, `scene.summary`); entity-ref fields auto-resolve to nodes. |
| `project` | The project node. `project.<field>` reads an authored project field (e.g. `project.spelling`); `project.metadata` is the whole map; intrinsics (`title`, `root_path`) win a name collision. |
| `inputs` | The prompt's declared inputs, by name. `inputs.<name>` — a `context_pick` resolves to a `list` of nodes (or use `entry(inputs.pick)` for the first); a `text`/`select` to a string; a number to a number. |
| `selection` | `str` — the selected prose (revise/inline dispositions), else `""`. |
| `text_before` / `text_after` | `str` — body markdown around the cursor; `""` when not dispatched from an editor. |
| `date` | Today's date; `date.year`, `date.month`, `date.day`, and `str(date)`. |

## Helpers

| Call | Returns |
| --- | --- |
| `entry(x, at=scene, position=n)` | A node resolved as of the prompt's scene (or the explicit `at=` scene; `at=None` forces book-start; `position=` is a within-scene cursor). `entry_type` inferred from `x`. Accepts an id, a node, or a `context_pick` value (first pick). |
| `original(x)` | The same node at **book-start**, ignoring every mutation. |
| `fields(x)` | The **full** field roster of a node or an `entry_type` FQN — a list of descriptors, each `{id, label, type, options, description, proposable}` (plus `items` for list fields). `proposable` is advisory; the template chooses what to show. |
| `type_name(x)` | `str` — a type's human name (from an `entry_type` FQN). |
| `pov(scene)` | The scene's POV character (`lore:character`) or `None`. |
| `is_a(node, entry_type)` | `bool` — kind-of test against the type's `parent:` chain. |
| `use(node, "stable"\|"volatile")` | `""` — **selects** the node into context; the backend places, dedups, tiers, and caches it (the template emits nothing). The optional hint is an advisory cache-tier prior, bounded by per-revision correctness. |
| `use_lore()` | `""` — enables the scene's implicit lore (the gate); the backend selects and places it. |
| `full_outline()` | The manuscript's outline: a nested list of nodes with `.title`, `.summary`, `.children`. |
| `full_text()` | `str` — every scene's prose in reading order. Heavy — the whole-manuscript escape hatch. For one scene, use the prompt's target `scene` (`scene.body`); `use()` selects **lore**, not scene prose. |
| `story_so_far(scene)` | `str` — an XML recap of prior scenes' summaries (scenes **1 → n-1**, reading order). A derived, per-scene-deterministic block: it is emitted (not selected) and caches in the stable prefix. |
| `character_turns(scene, character)` | Reconstructs the scene as **alternating chat turns** for the Roleplay sub-type (focus character → `assistant`, others → `user` prefixed `[Name]:`, narration → plain `user`). Emits its own role boundaries — use it **outside** any `{% role %}` block. |
| `plot_context(as_of=node)` | `str` — the spoiler-gated plot-board recap up to `as_of` (a card/scene). Derived and emitted, like `story_so_far`. |
| `last_words(text, n)` | `str` — the trailing `n` words of a string (pure helper). |

## Filters

| Filter | Returns |
| --- | --- |
| `value \| json` | `str` — compact JSON, **insertion-order preserving**, no surprise HTML-escaping. The one JSON spelling (replaces `plain_json` / `tojson`). |

Standard Jinja filters (`join`, `length`, `default`, …) work as usual.

## Tags

| Tag | Effect |
| --- | --- |
| `{% role "system"\|"user"\|"assistant" %}…{% endrole %}` | Marks the wrapped content's message role. An override: un-roled prose is homed to the base type's default role (usually `system`), so a prose-only prompt just works. |
| `{% include "snippet-id" %}` | Inlines a `prompt:snippet` node by id (e.g. `builtin-project-settings`). |

## Retired

`base(x)` → `original(x)` · `entry_as_of(x, s)` → `entry(x, at=s)` · `effective(x, f, s)` → `entry(x, at=s).f` · `field_catalog` → `fields` · `entry_type_label` → `type_name` · `scenes_before` → `story_so_far` · `character_thread` → `character_turns` · `plain_json` / `tojson` → `\| json` · `input` → `inputs` · `novel` → `project` · `relevant_lore(…, partition=…)` and `{% cache_break %}` → removed (the backend selects and tiers lore; caching is a provider-neutral volatility ordering the author never touches).
