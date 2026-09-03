# ADR-0082: A tag is a node, and a tags field is a reference list into a vocabulary

- Status: **Accepted** — 2026-09-03, Anton, PR #1779.
- **Issue:** #1778
- **Relates to:** ADR-0081 (references at any depth), ADR-0078 (promotion), ADR-0045 (scope is
  the unit of work), ADR-0042 / #339 (authoring level, layered tags), ADR-0071 (migration
  ladder), ADR-0074 (context-pick selectors), ADR-0029 (intrinsic fields, type colour),
  ADR-0024 / #88 (assistant tags), the class–instance model (`docs/metadata-strategy.md`)

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

None of that belongs to a value type. But it is not quite a reference either, and the gap is
**identity**. A reference stores a machine-minted id; the target's title can change freely and
nothing propagates (that is why ADR-0081 could call refs "already uniform, so free"). A tag
stores its *name*, so the name is the identity, and every rename becomes a rewrite problem: the
project-tag merge may only rewrite documents the open scope owns
(`_reject_sources_above_this_layer`, `tags.py:426`), so a tag renamed at a series is stale in
every book until each book is opened and re-saved, and the module calls those stale strings
"the rule, not a stopgap". The repo already settled this for nodes: **ids are machine-minted,
never hand-rolled** — hand-rolled ids caused the project-inheritance bugs (#1716–#1719). A tag
whose name is its id is a hand-rolled id.

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
`assistant_tags.py:49`). The two stores do not even agree on behaviour: project tags are
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

**A tag is a node.** A vocabulary is an entry type of a new `tag` kind, a tag is an entry of
that type, and a tags field is an `entity_ref_list` filtered to that entry type, with one new
picker affordance: create the entry when the typed name resolves to nothing. The `tags` field
type, both tag registries and the tag-specific rename machinery are retired, and the two merge
endpoints become one merge on tag nodes (§5); every other tag lifecycle is the reference
lifecycle ADR-0081 already made uniform.

### 1 — The `tag` kind, and why it is a kind

The kind whitelist is deliberately short: a new kind must be justified by a genuinely different
storage shape or routing surface, not a user-visible affordance
(`docs/metadata-strategy.md` § Invariants). `tag` qualifies on both:

- **Storage.** A tag is a body-less, title-only node that is minted from a picker rather than
  authored in an editor, lives at the machine layer as well as in projects (the assistant
  vocabulary), and is expected in the hundreds. No existing kind has that profile; making it a
  `lore:` sub-type would drag every tag into implicit-context detection, alias matching and the
  Lore pane.
- **Routing.** A tag's instance list is a governance surface (usage counts, merge, colour), not
  a document list, and its "editor" is a picker.

In class–instance terms (`docs/metadata-strategy.md` § Class–instance model):

| OO concept | Tags |
|---|---|
| class | kind `tag` |
| abstract base | `tag:base` — fields `color` (the `color` type, `schema.py:296`) and `merged_into` (§5); `has_body: false` |
| sub-class | **a vocabulary**: `tag:tag` (general), `tag:assistant_tag` (built-in), `tag:motifs` (user-authored) |
| instance | a tag: `tags/coastal.md`, front matter `id`, `kind`, `entry_type`, `title`, `metadata`; no body |

A user authors a vocabulary exactly as they author a lore sub-type: in the Custom Data pane,
scoped to kind `tag`.

Storage follows the app's one shape. Every indexed kind is **one Markdown file per node with
front matter** — views, mutation sets and chats are already body-less nodes carrying their
payload in front matter (`NODE_FAMILIES`, `backend/app/services/project/references.py:77`). The
file is named by title slug like a lore entry or a scene (`_filepath_for_new_node`,
`project_service.py:553`); the id is minted by `_new_id("tag")` (`project_service.py:647`).
`tag` is a `NodeFamily` row with folder `tags/`; for project layers `_families_for_layer`
(`references.py:840`) falls through to `NODE_FAMILIES`, so the index walk, purge, heal and
title passes see project tag files with no new collector. The machine layer is filtered to
assistants by a derived predicate (`MACHINE_LAYER_FAMILIES`, `references.py:113`, deliberately
not a literal), which widens to `tag` so the layer contributes `tag:assistant_tag` entries
beside its assistants. The built-in Library (`LIBRARY_LAYER_FAMILIES`, `references.py:124`,
prompt and plot) is unchanged: it ships no tags. A many-per-file YAML collection was rejected
(§ Alternatives).

**What registering a kind costs** — the full surface, which `research` touched only in part
(it has no save-dispatch or upsert-whitelist row): the `NODE_FAMILIES` row and the
`MACHINE_LAYER_FAMILIES` predicate above; `tag` in the entry-type upsert whitelist
(`services/project/schema.py:287`); rows in the three kind ladders — `_SAVE_NODE_DISPATCH`,
`read_node`, `delete_node` (`node_ops.py:42`, `:60`, `:172`) and `_SAVE_NODE_REQUEST_BY_KIND`
(`routers/entries.py:179`) — since there is no generic create and each kind has its own POST;
a `create_tag_entry` behind `POST /api/tags` that the picker calls; `tag` among the promotable
kinds (the promotion routers and `_fold_override_edges`, `overrides.py:179`, fold only
`lore`/`prompt` today), because
lifting a tag to an ancestor *is* promotion; and the frontend registrations (`SchemaKind`,
`schemaTypeHelpers.ts:88`; `SCHEMA_KIND_META`, `:103`; `DocumentKind` / `EditableDocument`,
`types.ts:153`). `NodeEditor` opens a tag through `has_body: false` like a view.

**Layering is node layering.** A tag lives at exactly one layer, the one it was written to, and
shadows by id like any node. The registry's union-across-layers merge (`_TagRegistryMerger`)
existed only because the same *name* asserted at two layers had to be one tag; with ids, a book
that uses a series tag stores the series tag's id and asserts nothing.

### 2 — A tags field is an `entity_ref_list` that may create its target

The field is an ordinary `entity_ref_list` whose `picker_config` names the vocabulary:

```yaml
motifs:
  name: Motifs
  type: entity_ref_list
  picker_config:
    sources: [{kind: tag, entry_types: [motifs]}]
    create_missing: true
```

`create_missing` is a new **mechanic** on `NodePickerConfig` (`backend/app/models_views.py:223`),
beside `presets`, `multiple` and `allow_target_marking`. When the typed name resolves to no tag
in the picker's source, the picker offers to create one — the gesture `TagRosterPopover`
already has ("Create ‹x›", `TagRosterPopover.svelte:70`), now on the reference picker, which
has no create path today (`NodePicker.svelte`). It is permitted only when the source names
exactly **one concrete entry type**, so the minted entry has an unambiguous type; a source
spanning several vocabularies is a closed picker.

**Resolution before creation.** The name is matched **case-insensitively** against the titles of
tags in the source across the merged chain, so typing `coastal` on a book scene finds the
series' `Coastal` and references it rather than minting a duplicate. The candidates endpoint
already returns id + title per picker config (`/api/references/candidates`,
`routers/entries.py:278`); the fold is the picker's. That is the one rule the kind adds to
title resolution: `resolve_snippet_name` (`snippet_loader.py:46`) is exact and case-sensitive
because prompt includes are code; a tag is a word. A same-title tag at two layers is therefore
only created deliberately, or by two sibling books before a series tag exists — in which case
they remain distinct tags until merged (§5). Nothing folds them silently.

**Where the entry is created: the layer the saved node is being written to.** For a node saved
at the open project that is the open project (ADR-0045); when the authoring-level dropdown
(#339 / ADR-0042, `up_to_layer_id`) directs a save to an ancestor L, the tag is created at L
too — a node at L must not reference a tag that exists only below it, which is the ADR-0078 §4
dangling-edge case. For a machine-roster assistant it is the machine layer, and that path must
work **with no project open**: `_require_project` (`project_service.py:385`) 409s there today
and only the assistant paths avoid it (`assistants.py:442`), so tag creation gets the same
machine-only path, with `layer_by_id(include_machine=True)` (`layers.py:335`). The picker does
not offer a layer of its own: a save has exactly one write target (ADR-0045), the tag is a
side effect of that save, and a second layer choice inside a chip picker would let a node
reference a tag *below* its own layer — the dangling case above. Lifting a tag to an ancestor
is a deliberate act: ADR-0078 promotion of the tag node.

**Closed vocabularies need nothing.** A field without `create_missing` is a closed pick over
the vocabulary — the curated series-level case — and is enforced the way every ref is: the id
must resolve (`_validate_entity_ref_list_value`, `metadata_values.py:359`).

**The built-in bindings.** A field id is one definition across every kind that lists it, so
`tags` cannot point at `tag:tag` on a scene and at `tag:assistant_tag` on an assistant. The
assistant's field is renamed `assistant_tags`, matching the prompt's:

```yaml
tags:           {type: entity_ref_list, picker_config: {sources: [{kind: tag, entry_types: [tag]}],           create_missing: true}}  # scene, lore, research
assistant_tags: {type: entity_ref_list, picker_config: {sources: [{kind: tag, entry_types: [assistant_tag]}], create_missing: true}}  # prompt AND assistant
```

Consumers keyed on an assistant's `tags` follow the rename: `_ASSISTANT_TAG_FIELD` and the
registration in `save_assistant_entry` (`assistants.py:514`), `assistantTagsOf`
(`assistantScope.ts:23`), the shipped assistant view's `key="tags"` predicate
(`views.py:463`, `evaluateView.ts:271`). The `tags` prompt-input type (`PromptInputType`,
`models/base.py:59`), rendered today with a hard-coded assistant origin
(`tagOrigin="assistant"`, `components/widgets/PromptInputField.svelte:220`), retires: a prompt
input that picks tags is a
node-pick input whose `target` names the vocabulary, which prompt inputs already carry
(`PromptInputDefinition.target`, `schema.py:188`).

Group members are covered without a word: `GroupMember` already admits `entity_ref_list`
(`LIST_ITEM_GROUP_MEMBER_TYPES`, `schema.py:30`), and `tags` simply leaves that set.

### 3 — What is free, because it is the reference lifecycle

This is the reason to take the id path. Each of these is a tag-specific pass today and an
existing ref pass tomorrow:

| Today (tags) | Tomorrow (refs) |
|---|---|
| `_canonicalise_metadata_tags` casing + registry write on save | nothing — an id has no casing; §2 resolves before creation |
| `merge_tags` / `_rename_tag_in_documents` rewriting names | **rename = edit the tag node's title.** No propagation, no aliases. |
| no index edge for a tags occurrence (`_reference_edges_for_entry`, `references.py:1206`) | a backlink edge per reference, field-qualified (`ReferenceEdge`) |
| tag usage counts re-derived per registry (`_count_document_tags`) | `edges_by_dst` / the `references` computed node-set field (`default_schema.py:1072`, `backlinks.ts`) |
| a deleted tag survives as a string forever | `_purge_metadata_refs` (`metadata_values.py:705`) scrubs the owned scope; `_strip_dangling_references` (`:653`) heals the rest on read |
| raw strings reach search | `_resolve_reference_titles` (`search.py:252`) — search by tag title keeps working |
| `{{ scene.tags }}` is `list[str]` passed through un-wrapped (`entry_ref.py:325`) | `list[EntryRef]`; `str(ref)` is the title (`EntryRef.__str__`, `entry_ref.py:201`), `.id` / `.metadata.color` reachable; equality is by id (`:207`) |
| `_partition_tags` on promotion (`promotion.py:135`) | `_partition_entity_ref_list` (`promotion.py:116`): a ref to an origin-local tag stays behind as an override, a nested one blocks (ADR-0081). ADR-0078's stated intent — don't push a book-local label into a shared space — is preserved by the same rule refs already obey. |
| per-tag colour store (`UpdateTagColorRequest`) | the tag node's `color` field, with ADR-0029 type-level colour as the vocabulary default (`color` / `own_color`, `schema.py:385`) |
| per-tag **scope** (a `NodePickerConfig`) with auto-broaden on use | **dropped as stored data.** Scope only ever ranked picker suggestions; that ranking is now read off backlinks — the kinds of the nodes referencing the tag — which is what auto-broaden approximated. |
| `overlap` filtering by tag name | `evalField` already tokenises a ref list to a set (`evaluateView.ts:1077`) |
| the Tags governance pane | **the `tag` kind's instance list**: a `NodeList` of tag rows grouped by vocabulary, usage count from backlinks, merge and colour as row actions — the app reduces to `NodeRow` or `NodeEditor`, and this pane was the exception |

Two things are *not* free and are decided here:

- **Titles across kinds in the frontend.** `segmentForField` buckets an `entity_ref_list` by
  the referenced node's title (`groupBy.ts:88`) — but through `ctx.nodeById`, which is the
  view's *own roster* (`evaluateView.ts:325`). A scene view grouped by Motifs would show raw
  ids. The frontend keeps a **tag roster store** (the successor of `knownTagsStore`,
  `stores/tags.ts`, now a node list of kind `tag` across the merged chain), and the evaluator,
  `FieldValue` chips and the picker resolve tag ids through it. That store is also where
  `merged_into` (§5) is followed on the frontend.
- **Colour on the chip.** The reference picker already resolves a target node's own
  `metadata.color` onto its chips and selector members (`buildInstanceColorMap`,
  `frontend/src/lib/utils/pickerStripes.ts:47`, #1528). `FieldValue` and `NodeRow` do not: they
  colour only `tags` and `color` fields, from the name-keyed tag map (`FieldValue.svelte:167`,
  `NodeRow.svelte:91`). A tag chip in those two surfaces resolves through the same helper the
  picker uses.

### 4 — `tagged:` means "references this tag", by id

The `tagged:` selector leaf matches a tag **name**, exactly and case-sensitively, against the
built-in `tags` key in both evaluators (`selector_node_tags`, `selector_eval.py:54`; `nodeTags`,
`evaluateView.ts:1044`), and the picker emits it by name (`NodePicker.svelte:398`). A selector
by name breaks under rename, which is the bug this ADR exists to remove. So `tagged:` takes a
**tag id**, and its meaning is schema-free: **a node is tagged with T if any of its metadata
references T** — a backlink edge from the node to T exists. That covers user vocabularies
(`motifs`) without the evaluator knowing field keys, and it is the same graph the usage counts
read. The picker emits the id; the ADR-0074 parity contract stands, and the corpus
(`spec/selector-eval-corpus.json`) is rewritten with ids — its by-name cases lose their
subject and retire, including "tagged matches a comma-string tags value" and "tagged is
case-sensitive". The `TAG`
parameter of the built-in roster view (`views.py:463`) is an `overlap` over an
`entity_ref_list`, which the evaluator already handles; its strip control (`taggedField`,
`viewParams.ts:55`, which synthesises a `type: "tags"` field) becomes a picker over kind `tag`.
The selector-kind `"tag"` on `NodePickerRef.kind` (`types.ts:840`) keeps its meaning — "the
nodes tagged with this tag" — and its persisted id scheme `tag:${kind}:${name}`
(`NodePicker.svelte:407`) is replaced, both because it carries a name and because it collides
with the `tag:` FQN prefix of the new kind.

### 5 — Merge is a redirect, not a rewrite

Rename needs nothing (§3). Merge — `mirror` into `mirrors` — is the one operation that cannot
be a pure title edit, because references to `mirror`'s id exist in files the open scope may not
write (a book's scenes, when merging at the series). So:

- Within the owned scope, references to `mirror` are rewritten to `mirrors` through the one
  traversal (`rewrite_ref_occurrences`), as the merge does today.
- `mirror` is not deleted. Its `merged_into` field (an `entity_ref` on `tag:base`, to another
  tag) is set to `mirrors`, and it leaves every picker and roster.
- **The redirect resolves at one choke point: the node index.** The index entry of a merged tag
  carries `merged_into`; id→entry lookup canonicalises through it, and edge building rewrites
  the edge's destination to the survivor, so backlinks, usage counts and `tagged:` land on
  `mirrors` with no consumer doing anything. An edge from the `merged_into` field is a
  *redirect*, not a reference: the index keeps it apart from backlink edges, so it counts
  toward no usage total and `tagged: mirrors` (§4) never matches the tag node `mirror` itself.
  The frontend follows the same field in the tag roster store (§3). A merged
  tag is therefore never *dangling* — the heal pass does not strip it — and the chain cannot
  collide, because ids are unique.
- **Lazy rewrite rides save-time ref validation.** There is no "ref pass on save" to hook; what
  every kind's save already does is validate each ref value through the one traversal
  (`_validate_entity_ref_list_value`). That validation rewrites a merged id to its survivor
  while it is there, so a book scene writes `mirrors`' id on its next save.
- **Deleting a survivor cascades to its redirects.** `_purge_references_to`
  (`metadata_values.py:793`) would otherwise scrub `merged_into` on every merged tag and
  resurrect them into pickers. A redirect without a survivor is meaningless, so it is deleted
  with it — the chat-subject cascade (`_chats_with_subject_in`, `:777`: "a deleted subject
  takes its chats with it") is the precedent. References to the deleted tags
  then heal as dangling, which is ordinary deletion.
- A merged tag with no remaining backlinks in the open scope may be deleted by the governance
  surface; the ADR does not delete it automatically, because the open scope cannot see a sibling
  book's references.

Deleting a tag outright is ordinary node deletion: purge in the owned scope, heal-on-read
elsewhere. That is lossy by design and is why merge exists.

### 6 — Migration (ADR-0071)

This is a storage-shape change after 0.9.5 and, unlike the reference-type changes before it, it
rewrites node documents: every `tags: [name, …]` becomes `tags: [tag_…, …]`. Three parts, and
one new step type.

**A chain-aware step type.** `RootMigration.fn` takes a bare root (`MigrationFn`,
`migrations.py:80`) and the `DocumentMigration` sub-ladder is context-free (`migrate_document`,
`migrations.py:252`); this step needs the name→id map accumulated from the ancestors already
migrated and from the machine layer. So the ladder gains a `ChainMigration` whose function
receives the root and a context the runner builds outermost-first.

**Per layer, outermost first (schema version 8 → 9),** one `ChainMigration`:

1. read `<layer>/tags.yaml`; mint one `tag:tag` node per record in `<layer>/tags/` (title =
   name, `color` carried), extending the inherited name→id map. The map is keyed
   **case-insensitively**, as the registry was (`_TagRegistryMerger` keys by `name.lower()`):
   a name already mapped by an ancestor in any casing mints nothing and keeps the ancestor's
   casing — the union collapses to the ancestor's node, as the union merge did, and the §2
   resolution rule holds for migrated data too.
2. walk the layer's node documents, **including `overrides/*.md`** (ADR-0071 §3; ADR-0078 parks
   a stayed-behind tag there) and rewrite each `tags` / `assistant_tags` value through the map
   (prompts' `assistant_tags` through the machine map). A name in a document but in no
   registry is minted at this layer first.
3. rewrite `tagged:` leaves in saved views and in chats' persisted context picks
   (`save_chat_session`, `chats.py:350`), including their selector `id`/`title`, and the
   `field.key: "tags"` /
   `TAG`-param bindings in on-disk copies of the shipped assistant view (`views.py:463`); a
   name that resolves to nothing is dropped and logged.
4. any user-authored `metadata.schema.yaml` field with `type: tags` becomes the
   `entity_ref_list` shape in §2 bound to `tag:tag`; any prompt `inputs[].type: "tags"` becomes
   the node-pick input shape.

`_run_migrations` (`backend/app/services/project/migration_runner.py:28`, reached from
`migrate_project`, `migrations.py:295`) runs for the project being opened and rewrites only the
open layer's files (`:67`); an ancestor migrates only when *it* is opened. Step 2 in a book
needs step 1 in its series, and — sharper — removing `tags` from the type `Literal` makes an
unmigrated ancestor's `metadata.schema.yaml` fail validation on merge. So **opening a project
runs the full ladder on every layer of its declared chain, outermost first**, each through its
own `ProjectService(WorkScope(root=layer))._run_migrations()` with its own `backup_project`
(the ADR-0071 backup rule holds per layer), skipping a declared folder that has no
`project.yaml`. ADR-0071 §5 deferred migrate-ancestors-on-open; this ADR decides it, and the
runner change is called out in the PR. A version-dispatching reader was rejected
(§ Alternatives).

**Machine, once, before any project step.** `assistant-tags.yaml` → `tag:assistant_tag` nodes
in `<machine>/tags/`; machine-roster assistants' `tags` → `assistant_tags: [ids]`. The ladder
has no machine seam — a root step takes a project root — so this is a machine-level step keyed
on the `version` field `MachineSettings` already carries (`machine_settings.py:107`,
`version: int = 1`), bumped for it, run in the app lifespan, idempotent.

**Scaffold.** `create_project` writes a `tags/` folder where it writes `tags.yaml` today
(`lifecycle.py:211`).

## Scope

**In:**
- the `tag` kind and everything §1 lists under registration cost; `tag:base` with `color` and
  `merged_into`; built-in `tag:tag` and `tag:assistant_tag`;
- `create_missing` on `NodePickerConfig`, its single-concrete-type rule, case-insensitive title
  resolution for kind `tag` in the picker, creation at the written-to layer including the
  machine-only path;
- retirement of the `tags` field type and the `tags` prompt-input type; the assistant field
  rename and its consumers; `tags` leaving `REF_FIELD_TYPES`, `LIST_ITEM_GROUP_MEMBER_TYPES`,
  `COLLECTION_FIELD_TYPES` (`lore_mutations.py:102`), the hard-coded `field_id == "tags"` in
  `research.py:358`, and the TS mirrors;
- `tagged:` by id as "references this tag" in both evaluators and the picker, the rewritten
  parity corpus, the `TAG` strip control, the replaced selector id scheme;
- **one merge operation on tag nodes** (owned-scope rewrite + `merged_into`), replacing
  `merge_tags` and `merge_assistant_tags`; `merged_into` in the index choke point, the
  save-time rewrite, the survivor-delete cascade; the tag roster store; the governance pane as
  the tag kind's instance list; tag-chip colour in `FieldValue`/`NodeRow` via the picker's
  helper;
- the retirement of `TagsMixin`'s registry, `AssistantTagsMixin`, `_canonicalise_metadata_tags`,
  `_partition_tags`, the tag-scope endpoints and stores, `KnownTags` / `AssistantTag`
  (`models/annotations.py`);
- the `ChainMigration` step type, the chain-wide runner, the machine step, the scaffold.

**Out, and why:**
- **A body on a tag.** `tag:base` declares no body. If an author wants to write about a motif,
  `lore:` is where in-world things with prose live; nothing here prevents a `lore:motif` entry
  type from coexisting with a `tag:motifs` vocabulary.
- **The AI-context join** (lore that shares a motif with the current scene, pulled into
  context automatically). The view grammar can express such a view today, but the AI-path
  selector evaluator supports only the flat-membership subset and raises on the relational
  operators (`selector_eval.py`, module docstring). Making a join view a context selector is a
  separate decision.
- **Automatic deletion of a merged tag** (§5).

## Alternatives considered

- **Identity by name with `formerly` aliases** (the first draft of this ADR: retire the type,
  give `multi_select` `vocabulary` + `extensible` properties, record renames as aliases on the
  option). It has three holes a rename at a parent layer exposes: a child option whose value
  equals a parent's former name collides and folds; the same value asserted at two layers
  diverges when one renames; and every consumer that reads raw values — Jinja, search, exports
  — must resolve aliases or shows stale names, a rule with no enforcement point. Each hole is
  the name being the identity. Ids remove all three and make rename a non-event.
- **Hide `tags` from the type picker and keep the type.** Fixes the UX symptom and leaves the
  two-vocabularies convention, the type dispatch in twenty-odd consumers and the rewrite-bounded
  rename in place. A defence, not an invariant.
- **Fold `tags` into `list`.** Throws away the vocabulary, which is the whole point of tags.
- **A `lore:` sub-type instead of a kind.** Drags tags into implicit-context detection, alias
  matching and the Lore pane, and cannot live at the machine layer. The kind-whitelist test
  (storage shape, routing surface) is met; a sub-type fails it in the other direction.
- **Many tags per file** (`tags.yaml` holding id-bearing records, surfaced as nodes). The
  collector is thirty lines; the cost is everything that assumes an id resolves to its own file
  — save, delete, snapshot and diff, export, backup, and ADR-0078 promotion, which *moves the
  file*. Each would need a tag-only implementation moving records between YAML files: a second
  lifecycle for one kind, the special subsystem the chat-as-node lesson warns against. One file
  per tag is what the other body-less kinds already do, and § Consequences measures the cost.
- **Keep the union-merge registry beside the nodes** (a tag asserted at several layers). The
  union existed to reconcile names; ids need no reconciling. A book that wants a series tag
  references it.
- **`tagged:` by name, resolved at evaluation.** Breaks on the first rename; the same defect
  the ADR removes from the field. **`tagged:` scanning only the built-in `tags` key** was also
  rejected: a user vocabulary is a first-class tag, and the backlink graph already knows every
  reference without the evaluator learning field keys.
- **Merge by deletion** (delete the merged-away tag and let heal strip it). Loses the tag from
  every file the open scope cannot rewrite — a book's scenes on a series merge. The redirect
  costs one field on `tag:base`. **Refusing to delete a survivor** while redirects point at it
  was the alternative to the cascade; a redirect with no survivor has no meaning, so the
  cascade is the honest shape.
- **A version-dispatching reader instead of migrating the chain** (§6). A permanent fork in
  every layered reader, this one and the next.

## Consequences

- One reference mechanism where there were two tag registries and a third, half-built one for
  research notes. Rename is free and total. The user-authorable join (prompt→assistant) is
  available to any pair of fields on any kinds.
- **Front matter stores ids, not words:** `tags: [tag_9f3a…]`. Reference lists already look
  like this; it is the one place the files get less readable, and the title is one hop away.
- **One file per tag is a proportionate number of files, and the I/O is lighter than today's.**
  A vocabulary of 20–200 tags sits beside 50–150 scenes and 50–300 lore entries; a tag file is
  seven lines, named by its title, so `tags/` reads as the vocabulary list. Measured on Windows
  (2026-09-03, 500 tag files, plain front-matter parse): all 500 read in 77 ms cold / 67 ms
  warm, 0.13 ms per file, 1.9 ms to rename one. That read happens once at index build, where
  every other kind is already read the same way. On the hot path the design is *strictly
  lighter*: tagging a scene writes the scene and **no tag file** (the id goes into the scene),
  whereas today every lore and scene save reads every layer's `tags.yaml` and may write it
  back; a rename writes one file where today it rewrites every carrying document in scope. Tag
  files are app-owned like `lore/` — nothing hand-edits them — and git sees one stable file
  per tag rather than a registry that changes on unrelated saves.
- **Jinja templates that treat `scene.tags` as strings change meaning**: `{{ scene.tags |
  join(", ") }}` still renders titles via `str()`, but `"coastal" in scene.tags` no longer holds
  (`EntryRef.__eq__` is by id). No built-in prompt touches `tags`; the `tags` input type is
  documented in `docs/prompts/snippets-and-prompts.md:111`, which changes with it.
- The Tags pane becomes a `NodeList`; `TagPicker` becomes the reference picker with
  `create_missing`; the tag-colour maps keyed by lowercased name (`FieldValue.svelte`,
  `NodeRow.svelte`) go.
- ADR-0071's ladder gains a step type, a chain-wide application and a machine-level step (§6).
  The migration is the largest since 0.9.5 and rewrites every node that carries a tag; the
  per-layer backup is what makes that acceptable.
- `docs/metadata-strategy.md`'s kind table and type paragraph, and `docs/schema-yaml-howto.md`,
  gain the `tag` kind; `schema_version` 8 → 9.

## Acceptance

The user journey that defines done, in the public vocabulary:

1. The author opens the Custom Data pane, kind `tag`, and adds a sub-type `Motifs`. On scenes
   they add a field `Motifs`, type `entity_ref_list`, source kind `tag` / `Motifs`, and tick
   "create when missing". They add the same field on `lore:theme`.
2. In a scene they type `mirrors` into Motifs; the picker offers "Create ‹mirrors›", and saving
   writes `tags/mirrors.md` in the open project and the id into the scene. On a lore entry,
   `mir` autocompletes to `mirrors`. The general Tags group does not show it; the Motifs group
   in the tag pane does, with a usage count of two.
3. A view over scenes grouped by Motifs buckets under `mirrors` with an openable header; a
   filter `motifs overlap [mirrors]` finds the scene; a plot board grouped by Motifs lanes it;
   a context pick of the tag `mirrors` selects both the scene and the lore entry.
4. In a series-level project the author renames the tag `doubling` to `doubles` in its editor.
   Opening a book under it, a scene carrying that tag shows, filters and groups as `doubles`.
   No file in the book changed.
5. In the tag pane they merge `mirror` into `mirrors`. A lore entry that carried `mirror` and
   has not been re-saved shows the chip `mirrors`, filters as `mirrors`, counts toward
   `mirrors`' usage, and writes `mirrors`' id on its next save. `mirror` is gone from every
   picker. Deleting `mirrors` later removes `mirror`'s redirect with it.
6. A book's `Motifs` field is redeclared without "create when missing"; typing a new word into
   it on a book scene offers nothing, while the series' motifs still autocomplete — and typing
   `Coastal` on a book scene references the series' `coastal` rather than creating a second.
   Saving a lore entry with the authoring level set to the series creates its new tag at the
   series.
7. The prompt editor's "Preferred assistant tags" and the assistant editor's (renamed) tags
   behave as before: the chat's assistant picker orders by overlap, and the assistant vocabulary
   is the `Assistant tags` group in the tag pane. With no project open, tagging an assistant
   still autocompletes and creates, at the machine layer.
8. A project at schema version 8 under a series also at 8 opens; both layers run the full
   ladder outermost first, each backed up, and stamp; every scene, lore entry, research note,
   prompt, assistant and override carries ids whose titles are the names it had; colours are
   where they were; a saved view with a `tagged:` leaf and a chat with a tag pick still select
   the same nodes.

**Not:** a body on a tag, an AI-context join view, or automatic deletion of merged tags.

## To verify / build at implementation

- `_partition_entity_ref_list` returns `None` (field dropped) when every target is hidden where
  `_partition_tags` returned `[]`; confirm the override shape ADR-0078 §4 expects.
- The lore-block renderer's treatment of ref members vs flat lists (`_resolve_list_refs`,
  `lore_block.py:324`; `_scalar_text`, `:369`) — a tags value moves from the second branch to
  the first.
- `NodeIndexEntry` carries no metadata today; `merged_into` becomes an index field, which bumps
  the index snapshot (`node_index_snapshot.py`).
- The machine layer exists only once `<machine>/assistants/` does (`_machine_layer_folder`,
  `layers.py:422`); creating the first machine tag must create the layer.
- The `changed-picks` reconciliation (`chat_changed_picks`, `routers/entries.py:151`) against
  migrated selector ids.
- Which frontend surfaces build a roster for the `"tag"` selector kind today
  (`buildSelectorRoster`, `NodePicker.svelte:332`) and now read the tag roster store.
