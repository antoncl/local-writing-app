# Prompt language reference

Every variable, helper, filter, and tag you can use in a prompt template, with
what each one gives you back.

Two things are worth knowing up front:

- **A node's type decides its fields.** You read a field with a dot —
  `node.field` — and a field that points at another node resolves to that node,
  so you can keep chaining: `entry(x).home_place.title`. Use `.metadata` when you
  want the whole field map at once.
- **The editor completes what it can.** When an input says what it points at,
  `entry(inputs.character)` completes from that; a literal `entry("honor")`
  completes from the project's nodes. When the type isn't known, completion falls
  back to the basics every node has — `id`, `title`, `body`, `entry_type` —
  rather than guessing.

Everything below is read **as of the prompt's scene**. A prompt with no scene
reads the book's starting values, so `entry(x)` and `original(x)` give the same
thing.

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
| `fields(x)` | The **full** field roster of a node or an `entry_type` FQN — a list of descriptors, each `{id, label, type, options, description, group, proposable}` (plus `items` for list fields). `group` is the field's section label (an applied struct like `GMO`, or a manual header; `None` when ungrouped), so a template can group by it: `{% for f in fields(e) if f.group == "GMO" %}`. `proposable` is advisory; the template chooses what to show. |
| `field_value(entity, field)` | The value of one field on `entity`, by id — the read-back companion to `fields()`. `field` is a bare id or a `fields()` descriptor, so a group loop reads each member's value: `{% for f in fields(e) if f.group == "GMO" %}{{ f.label }}: {{ field_value(e, f) }}{% endfor %}`. `title`/`body` return the node's intrinsics; an `entity_ref` value wraps to a node (so `field_value(e, "patron").title` works). `None` when unresolved. |

If a node's fields are organised into a named group, you can read a member straight off the group: `entry(x).GMO.Goal` reads the `Goal` field of the `GMO` group (`entry(x).GMO.goal` works too). When the group's name has a space, use brackets: `entry(x)["Antagonist GMO"].Goal`. An unknown group or field reads as `None`.
| `type_name(x)` | `str` — a type's human name (from an `entry_type` FQN). |
| `pov(scene)` | The scene's POV character (`lore:character`) or `None`. |
| `is_a(node, entry_type)` | `bool` — kind-of test against the type's `parent:` chain. |
| `use(node, "stable"\|"volatile")` | `""` — adds the node to what the AI sees. It prints nothing where you write it: the app fetches the node and includes it for you, with no duplicates. Hand it a whole picker selection to add every pick at once. The optional `"stable"`/`"volatile"` hint nudges caching and can usually be left off. |
| `use_lore()` | `""` — automatically includes the lore relevant to this scene: entries it links to, and entries named in its summary. Call it to turn that on; leave it out for no automatic lore. |
| `full_outline()` | The manuscript's outline: a nested list of nodes with `.title`, `.summary`, `.children`. |
| `full_text()` | `str` — every scene's prose in reading order. Heavy — the whole-manuscript escape hatch. For one scene, use the prompt's target `scene` (`scene.body`); `use()` selects **lore**, not scene prose. |
| `story_so_far(scene)` | `str` — an XML recap of prior scenes' summaries (scenes **1 → n-1**, reading order). A derived, per-scene-deterministic block: it is emitted (not selected) and caches in the stable prefix. |
| `character_turns(scene, character)` | Reconstructs the scene as **alternating chat turns** for the Roleplay sub-type (focus character → `assistant`, others → `user` prefixed `[Name]:`, narration → plain `user`). Emits its own role boundaries — use it **outside** any `{% role %}` block. |
| `roleplay_beats(scene)` | `str` — the roleplay scene laid out **beat by beat** for a finalize/cleanup prompt: each beat's speaker, its observable text, and (decoded) its private interiority. POV-agnostic; the finalize prompt decides whose interiority survives via `pov(scene)`. A scene with no beat markers returns its body unchanged. |
| `plot_context(as_of=node)` | `str` — the spoiler-gated plot-board recap up to `as_of` (a card/scene). Derived and emitted, like `story_so_far`. |
| `last_words(text, n)` | `str` — the trailing `n` words of a string (pure helper). |

### Field contract

`field_contract` is an object, not a function — one per render. When a prompt
asks the model to **fill in** field values, it lists the fields it promises to
produce, so the app can hold the result to that shape:

| Access | Effect |
| --- | --- |
| `{% do field_contract.store(f) %}` | Register a field the prompt commits to producing. `f` is a `fields()` descriptor, so a group loop stores each member: `{% for f in fields(e) if f.group == "GMO" %}{% do field_contract.store(f) %}{% endfor %}`. |
| `{{ field_contract.render }}` | Render the stored descriptors as the field roster shown to the model. |
| `field_contract.stored` | The registered set, read back by the commit path as the shape to enforce. An empty contract commits nothing. |

## Filters

| Filter | Returns |
| --- | --- |
| `value \| json` | `str` — compact JSON, **insertion-order preserving**, no surprise HTML-escaping. The one JSON spelling (replaces `plain_json` / `tojson`). |

Standard Jinja filters (`join`, `length`, `default`, …) work as usual.

## Tags

| Tag | Effect |
| --- | --- |
| `{% role "system"\|"user"\|"assistant" %}…{% endrole %}` | Marks the wrapped content's message role. An override: un-roled prose is homed to the base type's default role (usually `system`), so a prose-only prompt just works. |
| `{% do … %}` | Evaluates an expression for its side effect and emits nothing (Jinja's `ext.do`) — the construct for the side-effecting helpers: `{% do use(node) %}` records a lore pick, `{% do field_contract.store(f) %}` registers a field. |
| `{% include "Snippet title" %}` | Inlines a `prompt:snippet` node by title (e.g. `Project settings`). |

## Retired

`base(x)` → `original(x)` · `entry_as_of(x, s)` → `entry(x, at=s)` · `effective(x, f, s)` → `entry(x, at=s).f` · `field_catalog` → `fields` · `entry_type_label` → `type_name` · `scenes_before` → `story_so_far` · `character_thread` → `character_turns` · `plain_json` / `tojson` → `\| json` · `input` → `inputs` · `novel` → `project` · `relevant_lore(…, partition=…)` and `{% cache_break %}` → removed (the backend selects and tiers lore; caching is a provider-neutral volatility ordering the author never touches).
