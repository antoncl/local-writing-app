# ADR-0082: A tags field is a `multi_select` over a named, writer-grown vocabulary

- **Status:** Draft — awaiting review
- **Date:** 2026-09-03
- **Issue:** #1778
- **Relates to:** ADR-0081 (references at any depth), ADR-0078 (promotion), ADR-0045 (scope is
  the unit of work), ADR-0042 / #339 (authoring level, layered tags), ADR-0071 (migration
  ladder), ADR-0074 (context-pick selectors), ADR-0024 / #88 (assistant tags), #698 (list
  fields)

> **Verified against `d4fbdd59` (2026-09-03).** Citations name the symbol first; the line is a
> convenience and is what rots.

## Problem

`tags` is one of the thirteen field types a schema author can pick
(`MetadataFieldDefinition.type`, `backend/app/models/schema.py:37`). ADR-0081 made it descend
into groups alongside `entity_ref` and `entity_ref_list`, and that work exposed a question the
type had been avoiding: **what does a user-defined field of type `tags` mean?**

Read the code and the answer is that `tags` is a *reference* type wearing a *value* type's
clothes. A plain `list` of `text` has no vocabulary — every value is a private string. A
`multi_select` has a vocabulary the schema author declares up front. `tags` sits between them,
and everything that treats it differently from `list` treats it as a reference into a shared
vocabulary:

- it rides the one metadata-reference traversal with the ref types
  (`REF_FIELD_TYPES`, `backend/app/services/project/metadata_refs.py:40`);
- on a lore or scene save it is canonicalised against a registry and unknown names are minted
  into it (`_canonicalise_metadata_tags`, `backend/app/services/project/metadata_values.py:109`,
  called from `save_lore_entry` and `save_scene`);
- the registry is a per-layer file, union-merged down the inheritance chain with first-seen
  casing and nearest-wins colour (`_TagRegistryMerger`, `backend/app/services/project/tags.py:45`);
- it has rename and merge that rewrite documents (`merge_tags`, `tags.py:488`), a governance
  pane, per-option scope and colour.

None of that belongs to a value type. The one thing `tags` adds over `multi_select` is *who is
allowed to add an option*: the schema author in advance, or any writer at the point of use.

**The tell is that the `tags` type resolves against different vocabularies depending on where
the field sits.** The built-in schema has *one* `tags` field definition
(`default_schema.py:750`), listed on `manuscript:scene`, `lore:base`, `research:note` **and**
`assistant:assistant`. On the first three it resolves against the project chain's `tags.yaml`.
On an assistant it resolves against a machine-global `assistant-tags.yaml` with its own
registry, overview and merge endpoint (`AssistantTagsMixin`,
`backend/app/services/project/assistant_tags.py`), as does `assistant_tags` on prompts
(`default_schema.py:1187`). The type declares nothing about which vocabulary applies; **the
field key and the node kind decide, by convention in the code** — the module says so itself:
*"the field id is what disambiguates the two stores, not the type"* (`_ASSISTANT_TAG_FIELD`,
`assistant_tags.py:44`). The two stores do not even agree on behaviour: project tags are
canonicalised for casing on save, assistant tags are registered case-sensitively and add-only
(`register_assistant_tags`, `backend/app/services/machine_settings.py:453`), and a research
note's tags are neither canonicalised nor registered.

So a user who adds a third `tags` field gets undefined semantics: it silently joins the project
vocabulary and its kind-scope, indistinguishable from the built-in one. That is why the type
"doesn't make sense" in the picker. It is not that tags are wrong as a field — it is that the
type has no target.

The second thing the assistant case shows is what a vocabulary is *for* beyond filtering. The
prompt→assistant selection is a **join**: assistants whose tags overlap the prompt's
`assistant_tags` come first (`assistantScopeTags` / `assistantTagsOf`,
`frontend/src/lib/chat/assistantScope.ts`). Two fields on two kinds share one vocabulary, and
sharing is what makes the join meaningful. A vocabulary therefore needs a **name**, so that
more than one field can bind to it. Today that binding exists only for the one pair the code
hardwires.

## Decision

A tags field is a **`multi_select` whose vocabulary is named and may be extended by writers.**
The `tags` type is retired. `multi_select` gains two orthogonal properties, and the two
registries become two named vocabularies in one per-layer store.

### 1 — Two field properties, not a type

`MetadataFieldDefinition` gains, for `multi_select` only:

- **`vocabulary: <name>`** — the field draws its options from the named vocabulary in the
  layered store (§2) instead of its inline `options`. A field has inline options *or* a
  vocabulary, never both; inline options are the anonymous, closed, single-field case and stay
  exactly as they are.
- **`extensible: true`** — writers may add an option to the field's vocabulary by naming one
  that does not exist. Default `false`.

They are orthogonal on purpose, and the four combinations are all real:

| | inline options | `vocabulary` |
|---|---|---|
| closed | today's `multi_select` | a curated series-level vocabulary a book's field picks from but may not extend |
| `extensible` | *not allowed* — see below | today's `tags` |

`extensible` without `vocabulary` is rejected. Added options need a home, and the only home an
inline-options field has is the author-owned schema file. A writer's scene save must not edit
the schema — that boundary (author declares, writer fills) is the reason the tag registry has
always been a file beside the schema and not inside it. The check is a soft schema-shape error
in `_field_shape_errors` (`backend/app/services/project/schema_definition_validation.py:76`),
alongside the item-shape rules, not a model validator — for the same reason those are not.

A closed vocabulary is **enforced**: a value not in the vocabulary (current or former name, §4)
is rejected on save with a 422, as `_validate_select_value` (`metadata_values.py:334`) rejects
an unknown `select` value. Whether an inline closed `multi_select` should validate its values
the same way — today `_validate_str_list_value` (`metadata_values.py:352`) accepts any string —
is a pre-existing gap this ADR does not decide.

`extensible` is a permission, not a mode: it changes who may *add* to the option set and
nothing about how the field is displayed, filtered, grouped or searched. A field bound to a
vocabulary behaves as `multi_select` does everywhere `multi_select` already works — filtering,
ADR-0037 grouping in option order, the `overlap` predicate, lore-mutation
`COLLECTION_FIELD_TYPES` (`lore_mutations.py:102`) — because it *is* one. That is the payoff of
choosing `multi_select` over a cousin of it: the type-dispatch sites for `tags` in both runtimes
(a grep for the type comparison finds more than twenty, from `FieldValueEditor.svelte` and
`schemaTypeHelpers.ts` to `promotion.py` and `fieldIcons.ts`) collapse to "is this a
`multi_select`, and does it bind a vocabulary".

**The same two properties go on `GroupMember`** (`schema.py:274`), and `member_as_field`
(`metadata_refs.py:63`) carries them, so a vocabulary-bound member of an item group renders and
canonicalises like a top-level field — the ADR-0081 uniformity, kept. And on
`PromptInputDefinition`: the `tags` prompt-input type (`PromptInputType`, `models/base.py:59`),
which today renders with a hard-coded assistant origin (`PromptInputField.svelte:220`), retires
the same way — a prompt input of type `multi_select` names its vocabulary.

**The built-in bindings.** A field id is one definition across every kind that lists it, so
`tags` cannot mean the project vocabulary on a scene and the assistant vocabulary on an
assistant. The assistant's field is **renamed `assistant_tags`** — the only reason one key
ever meant two things is that the type carried the vocabulary implicitly by kind:

```yaml
tags:           {type: multi_select, vocabulary: tags,           extensible: true}   # scene, lore, research
assistant_tags: {type: multi_select, vocabulary: assistant_tags, extensible: true}   # prompt AND assistant
```

Everything keyed on an assistant's `tags` follows the rename: `_ASSISTANT_TAG_FIELD` and the
registration call in `save_assistant_entry` (`assistants.py:514`), `assistantTagsOf`
(`assistantScope.ts:23`), the shipped assistant view's `key="tags"` predicate
(`views.py:463`, `evaluateView.ts:271`), and the `tagged:` selector leaf when it is applied to
`kind:assistant` (`selector_eval.py`, which reads the `tags` *key*). On project kinds `tagged:`
is unchanged: sugar over the built-in `tags` field.

### 2 — One layered vocabulary store

A vocabulary is **named into existence by the first field that binds it.** There is no
declaration step and no owning layer: its options live in `vocabularies.yaml` at whichever
layers have added or curated them, and the merged view is the union down the chain.

```yaml
# <layer>/vocabularies.yaml
tags:
  - {value: coastal, color: sea-green, scope: {kinds: [lore]}}
  - {value: mirrors, formerly: [mirror]}
motifs:
  - {value: doubling}
```

The record shape is `SelectOption` (`backend/app/models/base.py:8`) — `value`, optional
`label`, optional `color` — plus two optional keys: `scope` (a `NodePickerConfig`, carried over
from `ScopedTag` unchanged) and `formerly` (§4). This is the same shape inline options use.

Merge semantics are the existing tag registry's, generalised by one level of keying
(vocabulary name → option value): options **union** across layers, first-seen casing wins,
nearest asserting layer wins colour, scope unions. The rationale in `_TagRegistryMerger`
stands verbatim — a book's typo must not restyle the world's vocabulary — and the
`up_to_layer_id` truncation (#339: the vocabulary visible at an authoring level L is the union
base → L) carries over.

**The resolved schema carries the vocabulary.** The schema resolver stamps the merged
vocabulary's options — with `formerly` — onto the resolved field's `options`, and the resolved
field keeps its `vocabulary` name. The inline-xor-vocabulary rule is a rule about the *stored*
definition; on the wire there is one shape, and the consumers that already read
`field.options` — ADR-0037 grouping (`groupBy.ts`), the `overlap` evaluator
(`evaluateView.ts:1090`), `ColoredSelect` — get vocabulary fields for free with no second
store threaded through `evaluateView`. The editor chooses `TagPicker` by the presence of
`vocabulary`, not by `options.length` (`FieldValueEditor.svelte:220` today), and `TagPicker`'s
`origin: "project" | "assistant"` prop becomes the vocabulary name.

**The machine layer joins the vocabulary walk.** Assistants live in machine settings, outside
the project chain, so the `assistant_tags` vocabulary lives in a machine-level
`vocabularies.yaml` and the chain a vocabulary is merged over is *machine → declared
ancestors → open project*. The layer walk already yields the machine layer behind an
`include_machine` flag (`collect_layers`, `layers.py:157`); schema layering excludes it and
vocabulary layering includes it. Two consequences the tag reader does not have today:
the reader needs a **no-project path** (an assistant is editable with no project open, so the
machine vocabulary must resolve from the machine layer alone; `read_known_tags` calls
`_require_project`, `tags.py:98`), and the machine layer, which exists only when
`<machine>/assistants/` does, is **created on first write** to it. That is what folds the
second registry, its overview and its merge endpoint into the first.

**Per-option scope stays, and stays optional.** A vocabulary bound on several kinds needs it:
`coastal`, added on a location, must not be suggested on a chat. The picker uses scope only to
rank suggestions, exactly as `TagPicker` does now ("known-but-out-of-scope is still known"),
and auto-broaden on use is unchanged. A vocabulary bound to one field on one kind never
accumulates a scope worth reading, and nothing forces it to.

### 3 — An added option lands at the layer that owns the saved node

A writer's newly-typed option is registered in the `vocabularies.yaml` of **the layer that
owns the node being saved**: the open project for a project node (ADR-0045 makes it the write
target), the machine layer for a machine-roster assistant. The picker adds at save time and
cannot ask for a layer. Moving an option to an ancestor is a deliberate act through the
governance surface, not a side effect of use.

ADR-0078 §3's promotion rule for tags carries over to any vocabulary-bound field: an option
known at the destination travels with the node, an option not known there stays behind as an
origin override, for the reason ADR-0078 gives — registering it at the destination would push a
book-local label into a shared space. A curated series-level `motifs` vocabulary makes that
argument stronger, not weaker. `_partition_tags` (`promotion.py:135`) becomes the partition
for "a `multi_select` bound to a vocabulary", and `known_at_dest` (`promotion.py:222`) is read
per vocabulary and includes former names. One sharpening: ADR-0081 treats a *nested* option
unknown at the destination as cosmetic, because an extensible vocabulary re-registers it there.
For a **closed** vocabulary nothing may register at the destination, so a nested unknown
option blocks the promotion exactly as a nested origin-local ref does.

### 4 — Rename and merge record a fact; they do not reach across layers

Today a rename rewrites documents, and is therefore bounded by what the open scope may write:
`_reject_sources_above_this_layer` (`tags.py:426`) refuses to rename a tag an ancestor asserts,
because rewriting the ancestor's documents would cross the ADR-0045 scope boundary, and a
series project cannot see a book's scenes to rewrite them at all. The module calls the
resulting stale strings "the rule, not a stopgap". This ADR replaces that rule with one that
needs no bound.

**A rename records the old value on the option** as `formerly: [old]`, in the owning layer's
`vocabularies.yaml`. A merge is the same record — the merged-away option's value becomes a
former name of the survivor, and the merged-away record is dropped. **Resolution honours
former names:** the merged vocabulary maps a former name to its option for the picker (a chip
shows the current name), for view filtering and grouping (a node still carrying `mirror`
buckets under `mirrors`), and for the save-time canonicaliser's known-map, which today keys by
current name only (`_canonicalise_tag_list`, `metadata_values.py:148`). Stored values are
rewritten **lazily**, by that canonicaliser — the next save of a node carrying a former name
writes the current one. The same-layer document rewrite the merge does today
(`_rename_tag_in_documents`, `tags.py:450`) is kept as an immediate convenience for the
documents the open scope owns, but it is no longer what makes the rename *correct*.

Consequences of that inversion:

- No write ever crosses a scope boundary, so the ancestor guard is unnecessary and goes. A
  series-level rename is honoured in every book the moment the book re-reads the merged
  vocabulary, without the series ever touching a book's files.
- Rename authority follows ownership: an option is renamed at the layer that asserts it. A
  descendant may not rename an ancestor's option, as now — but the *reason* is no longer "we
  cannot rewrite the files", it is that the record belongs to the ancestor.
- The tempting simplification — "only the picker needs to know about former names" — is
  wrong, and the ADR says so in advance: a view filter on the new name must find an untouched
  scene carrying the old one, or the rename appears to have lost nodes. The resolver treats a
  former name as equal to the current one; the picker merely displays the current one. Because
  the resolved field's `options` carry `formerly` (§2), the frontend evaluator has what it
  needs without a round-trip.

Inline-option renames (a schema author editing a closed `multi_select`'s options) keep the
eager rewrite they have (`_apply_option_value_changes`,
`backend/app/services/project/schema.py:877`). Whether they should adopt the `formerly` record
too is not decided here.

### 5 — The traversal's discriminator becomes "binds a vocabulary"

ADR-0081's one traversal selects occurrences by `field.type in REF_FIELD_TYPES`
(`iter_ref_occurrences` / `rewrite_ref_occurrences`, `metadata_refs.py:102`). The tag-shaped
passes — canonicalise, rename, promotion partition — now select **a `multi_select` with
`vocabulary` set**; the traversal's selection becomes a predicate over the field rather than a
type tuple. The ref passes (index, purge, heal, title) keep selecting by ref type and are
untouched. `LIST_ITEM_GROUP_MEMBER_TYPES` (`schema.py:30`, TS mirror `types.ts:521`) replaces
`tags` with `multi_select`: the comment barring `multi_select` from groups says "no item
affordances", but a `tags` member already has every affordance a group member needs and is
the same widget, and the bar is a name check in both places it is enforced
(`shapeableGroups`, `_list_field_schema_errors`). Not doing this would silently lose the
nested-tags capability ADR-0081 just shipped.

A `list` with the `select` item sugar does **not** take the two properties. An ordered list
legitimately repeats values (`_apply_option_value_changes` says so and preserves them); a
vocabulary-bound value is a set and canonicalising it de-duplicates. The two shapes are not the
same thing, and the traversal yields no occurrence for a scalar-sugar list anyway
(`ref_members`, `metadata_refs.py:74`).

### 6 — Migration (ADR-0071)

This is a storage-shape change after 0.9.5, so it ships with a migration, in three parts.

**Per layer (schema version 8 → 9):** `<layer>/tags.yaml` → `<layer>/vocabularies.yaml` under
key `tags` (records carried verbatim: `name`→`value`, `scope`, `color`); any user-authored
`metadata.schema.yaml` field with `type: tags` → `type: multi_select, vocabulary: tags,
extensible: true`. Built-in fields are code and move with the code. `migrate_project`
(`backend/app/services/migrations.py:295`) runs for the project being opened; an ancestor is
its own project and migrates when *it* is opened. Between those two moments the book's merged
vocabulary would silently lose the series' tags. So **opening a project applies the pending
root steps to every layer of its declared chain**, stamping each. The alternative — a reader
that dispatches on the layer's version — is a permanent fork in every layered reader, this one
and the next. This extends ADR-0071's per-project ladder to the chain and is called out in
the PR.

**Machine, once:** `assistant-tags.yaml` → machine `vocabularies.yaml` under key
`assistant_tags`, and the `tags` → `assistant_tags` key rename in machine-roster assistant
front matter (§1). The ladder has no machine seam — a `RootMigration` takes a project root — so
this is a machine-level step, versioned in machine config and run at app start, idempotent.
It is the one document rewrite this ADR makes, and it touches no project file.

**Scaffold:** a new project gets `vocabularies.yaml` where `create_project` writes `tags.yaml`
today (`lifecycle.py:211`).

There is no per-project `DocumentMigration`: a node's list of strings stays a list of strings.

## Scope

**In:**
- the two properties on field, group member and prompt input; their validation; the TS mirror;
- the layered `vocabularies.yaml` store with the machine layer in its walk and a no-project
  read path, replacing both registries and both merge endpoints with one set keyed by
  vocabulary name;
- the resolved-schema stamping of vocabulary options;
- `formerly`-based rename/merge, resolver support in picker, views and canonicaliser, lazy
  rewrite on save, removal of the ancestor guard;
- the traversal discriminator change and the group-member list change;
- the assistant field rename and its consumers;
- the schema pane: a `multi_select` field offers "options inline" or "from vocabulary ‹name›",
  with `extensible` alongside the latter; the name is a picker over names the merged store
  knows plus free text for a new one;
- the governance pane generalised by vocabulary name (the assistant-tag pane becomes the
  `assistant_tags` vocabulary in the same pane);
- the three-part migration.

**Out, and why:**
- **A `tag` node kind.** A label is a name with a colour. The moment an author wants to *write
  about* a motif — give it a body, have scenes reference it — it is a `lore:` entry type with an
  `entity_ref_list`, which already exists. Drawing that line here is what keeps a vocabulary
  option from accreting metadata until it is a second node system.
- **A description on a vocabulary option.** No surface asks for one; adding it would be
  reserving a mechanism for a render surface that does not exist.
- **The AI-context join.** A hand-built view `lore where motifs overlap field_of($scene,
  motifs)` is expressible in the view grammar today, but the AI-path selector evaluator
  supports only the flat-membership subset and raises on `field_of`/`var`
  (`selector_eval.py`, module docstring). Making a join view a context selector is a separate
  decision and this ADR does not sketch its shape.
- **The properties on `select`-sugar lists** (§5).
- **Validating inline closed `multi_select` values** (§1) and **unifying inline-option rename
  with `formerly`** (§4).

## Alternatives considered

- **Hide `tags` from the type picker and keep the type.** Fixes the UX symptom and leaves the
  two-vocabularies convention, the type-dispatch in twenty-odd consumers and the ancestor guard
  all in place. A defence, not an invariant.
- **Fold `tags` into `list`.** Throws away the vocabulary, which is the whole point of tags.
- **Tags as a Node kind** (a `tag` kind with flat storage; a tags field = `entity_ref_list`
  filtered to it). Same semantics as this ADR with a heavier carrier: it needs flat storage for
  a kind, case-insensitive title resolution as a kind-specific rule, create-on-miss as a ref
  picker mode, and it invites the label/entity line to blur. The uses tags actually have —
  filter, group, join — are all `multi_select` uses.
- **Keep two registries and add a third property naming the store.** Names the special case
  instead of removing it; a user vocabulary would be a third special case.
- **Per-kind field binding instead of renaming the assistant field** (let `field_overrides`
  carry `vocabulary`, so `tags` binds differently on `assistant:assistant`). Overrides carry
  `label` and `hidden` — presentation. Making one of them change what a field *means* per kind
  is a new override dimension invented for one built-in, and it would leave the very ambiguity
  this ADR exists to remove: the same key meaning two things.
- **Rename in place with cross-layer rewrites** (the current rule, extended). Violates the
  ADR-0045 scope bound and cannot reach descendants a parent project does not index; the
  current guard exists precisely because this is not possible.
- **One property instead of two** (`vocabulary` implies `extensible`). Loses the closed-but-
  shared case in §1's table, which is the curated series vocabulary — the case where a series
  author most wants the boundary.
- **A version-dispatching reader instead of migrating the chain** (§6).

## Consequences

- One vocabulary mechanism where there were two, and it is user-authorable: a user can build
  the prompt→assistant join for their own purposes with nothing the built-ins don't use.
- Research-note and assistant saves gain the canonicalisation lore and scene saves have; the
  case-sensitive add-only assistant registration goes.
- Every `tags`-typed dispatch in both runtimes becomes a `multi_select` path with a vocabulary
  check; `TagPicker` becomes the widget for a vocabulary-bound `multi_select` rather than a
  type's widget.
- `formerly` means a stored value can lag its option's current name indefinitely in an
  untouched node. That is by design and is the cost of never writing across a scope boundary;
  §4 places the burden on the resolver so the lag is invisible.
- ADR-0071's ladder gains a chain-wide application and a machine-level step (§6).
- `docs/metadata-strategy.md`'s type paragraph and `docs/schema-yaml-howto.md` need the new
  properties; `docs/prompts/reference.md` is unaffected (tag values reach templates as lists,
  as now).
- `schema_version` 8 → 9.

## Acceptance

The user journey that defines done, in the public vocabulary:

1. The author opens the schema pane on scenes, adds `Motifs`, type `multi_select`, picks "from
   vocabulary", types `motifs`, ticks `extensible`. They add the same on `lore:theme`, picking
   `motifs` from the names the pane now offers.
2. In a scene they type `mirrors` into Motifs; it shows as pending, saves, and is registered in
   the open project's `vocabularies.yaml` under `motifs`. On a lore entry, `mir` autocompletes
   to `mirrors`. The general tag cloud does not contain `mirrors`.
3. A view over scenes grouped by Motifs buckets by option; a filter `motifs overlap [mirrors]`
   finds the scene; a plot board grouped by Motifs lanes it.
4. In the vocabulary pane they merge `mirror` into `mirrors`. The lore entry that carried
   `mirror` and has not been re-saved still appears under `mirrors` in the view and shows the
   chip `mirrors` in its editor; its next save writes `mirrors`.
5. In a series-level project the author renames `doubling` to `doubles`. Opening a book under
   it, a scene carrying `doubling` shows and filters as `doubles`, and the book's files were not
   touched.
6. A book's `Motifs` is redeclared closed (`extensible` off) against the series vocabulary;
   typing a new word into it on a book scene is refused on save, and the series' options still
   autocomplete.
7. The prompt editor's "Preferred assistant tags" and the assistant editor's (renamed) tags
   behave as before: the chat's assistant picker orders by overlap, and the assistant-tag
   governance pane is the `assistant_tags` entry in the vocabulary pane. With no project open,
   editing an assistant's tags still autocompletes and registers.
8. A project at schema version 8 under a series also at 8 opens; both layers migrate and stamp;
   its tags, tag colours, tag scopes, inherited series tags and assistant tags are all where
   they were.

**Not:** a tag kind, a body or description on an option, an AI-context join view, or a
per-vocabulary settings surface beyond what the tag governance pane already has.

## To verify / build at implementation

- The machine-layer writes: `layer_by_id` defaults to `include_machine=False`
  (`layers.py:335`), so governance endpoints addressing the machine layer need the flag, and
  the first write must create `<machine>/assistants/` for the layer to exist.
- Whether the search index's raw-value walk (`_iter_metadata_search_values`, `search.py:220`)
  should resolve `formerly` or whether matching what is stored is acceptable.
- `TagPicker`'s governance adapter selection by vocabulary name, and whether the assistant
  adapter's "add-only" behaviour was a property of the machine vocabulary or of the pane.
- The `up_to_layer_id` write-target gap noted in `save_lore_entry` (`lore.py:271`: the
  canonicaliser reads as of L but writes to the resolution root) is pre-existing and carries
  over; it is not widened by this ADR, but the vocabulary writer inherits it.
- The exact set of `tags` type-dispatch sites — match field *types*, not field keys; `tags`
  the *key* on the built-in project field stays.
- How ADR-0071's runner is extended to the declared chain (§6), and that an ancestor opened
  later as its own project finds itself already at 9.
