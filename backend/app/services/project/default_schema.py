"""Built-in default metadata schema (#14 backend split).

The minimal schema the app ships before any project/layer
`metadata.schema.yaml` is merged on top (see CLAUDE.md "Layered metadata
schema"). Lives in its own module so the schema slice (project/schema.py)
can import it without an import cycle back into project_service.

Entry-type identity is the kind-qualified FQN `kind:key` (#77): the dict
key here, the `parent` reference, and the value stored in a node's
`entry_type` front matter all use that form (e.g. `lore:character`). The
bare `name` is the display label; the `kind` field mirrors the key prefix.
"""

from __future__ import annotations

from typing import Any

# The prompt disposition vocabulary (#951/#1684) — one module owns the shelf
# labels AND the handler keys the computation reads; the `disposition`/`runnable`
# field defs below reference the labels so declared option order IS shelf order.
from app.services.project.prompt_disposition import (
    PROMPT_DISPOSITIONS,
    PROMPT_RUNNABLE_VALUE,
)

# Intrinsic fields (#116): the identity triple stored in every node's
# top-level front matter (not in `metadata`). The schema resolver injects
# these keys into every entry_type's resolved `fields` list, in this order
# (title leads; id trails since it's hidden by default). Value is read from
# the node property of the same name. Kept here so the resolver and any
# consumer share one source of truth.
INTRINSIC_FIELD_KEYS: tuple[str, ...] = ("title", "entry_type", "id")

# Every `computed` function the app knows, split by WHO may declare one.
#
# Authorable — a user can point a schema field at these from the field editor,
# so `save_metadata_field` validates against this tuple and nothing else.
#
# Built-in — supplied by a resolver rather than by `_computed_entry_metadata`'s
# body-walking dispatch, and meaningless on an arbitrary entry type: `references`
# is inverted at view-eval time on the frontend, and the assistant pair is
# stamped by the layer traversal (#332/#333). Offering them in the field editor
# would let a user declare "assistant curation" on a lore type and get a field
# that is silently always empty.
#
# One place, because there were three and they already disagreed: this tuple,
# the dispatch in `computed_metadata.py`, and the frontend field editor's own
# union — which still omits `cost` (tracked separately, not fixed here).
AUTHORABLE_COMPUTED_FUNCTIONS: tuple[str, ...] = ("word_count", "counter", "cost")
BUILTIN_COMPUTED_FUNCTIONS: tuple[str, ...] = (
    "references",
    "assistant_listed",
    "assistant_position",
    "path",
    "prompt_disposition",
    "prompt_runnable",
)
COMPUTED_FUNCTIONS: tuple[str, ...] = AUTHORABLE_COMPUTED_FUNCTIONS + BUILTIN_COMPUTED_FUNCTIONS

# `context_strategy.output.handler` (ADR-0065) is the registry key that selects
# which OutputHandler runs a prompt's result — `inline` (stream a suggestion into
# the prose editor), `extract_to_node` (a brainstorm chat whose commit becomes a
# reviewable node patch), or `finalize_scene` (a scene action, not an
# editor-surface prompt — ADR-0070 S3's roleplay finalize/cleanup projection,
# invoked from its own modal, never the slash menu). This replaces the old
# `output.kind` disposition enum: `kind` named WHERE the output landed and
# everything else (source, review, activation) was derived from it; the handler
# now OWNS that behaviour, and the key just names which one.
#
# An empty/unset `handler` is legitimate — a prompt with no output handler stays in
# the conversation (the `general` and `snippet` bases). A brainstorm is not a
# special kind but `extract_to_node` + a `commit` capability (`PromptCommit`); the
# built-in brainstorm prompts below are `extract_to_node` with a `commit` block.
#
# None of this — `handler`, the inline `destination` (`cursor`/`selection`), or
# `commit.review` (`visual_diff`/`replace`) — is validated at rest: the backend
# parses `context_strategy.output` and `model_dump`s it straight through
# (`validate_prompt_output` was deleted, #1425). The handler vocabulary is
# closed and mirrored on both sides — `OUTPUT_HANDLER_KEYS` in
# editor-core/outputHandlers.ts (invocation) and `PROMPT_OUTPUT_HANDLER_KEYS`
# in services/project/prompt_disposition.py (the `disposition` computed field,
# #1684), pinned together by spec/prompt-disposition-labels.json — and both
# fail closed on an unknown value: such a prompt resolves to no surface / the
# Snippets shelf, so it simply isn't invocable, not a save-time rejection.

DEFAULT_METADATA_SCHEMA: dict[str, Any] = {
    "version": 1,
    "entry_types": {
        "manuscript:base": {
            "name": "Manuscript",
            "kind": "manuscript",
            "abstract": True,
            "fields": ["number", "summary", "color"],
            # Number POSTFIX (#1144 follow-up): the counter is reorder-live, so it
            # trails the title ("Act 1", "Chapter 3") rather than prefixing it. New
            # nodes are auto-named WITHOUT a baked-in number (see nextAutoName), so
            # the live number is the single source — no "1. Act 1" doubling, no
            # stale number after a drag.
            "display_template": "{title} {number}",
            "has_body": False,
        },
        "manuscript:act": {
            "name": "Act",
            "icon": "stack-2",
            "kind": "manuscript",
            "parent": "manuscript:base",
            # Narration (pov_mode / pov / tense) is authorable at every structure
            # level so it can be overridden here and cascade to the scenes below
            # (ADR-0079).
            "fields": ["pov_mode", "pov", "tense"],
        },
        "manuscript:chapter": {
            "name": "Chapter",
            "icon": "book",
            "kind": "manuscript",
            "parent": "manuscript:base",
            "fields": ["pov_mode", "pov", "tense"],
        },
        "manuscript:scene": {
            "name": "Scene",
            "icon": "feather",
            "kind": "manuscript",
            "parent": "manuscript:base",
            "fields": [
                "status",
                # Narration cascade fields kept adjacent, mode first — pov_mode
                # gates whether pov applies (ADR-0079); matches act/chapter ordering.
                "pov_mode",
                "pov",
                "tense",
                "characters",
                "location",
                "tags",
                "dynamics",
                "word_count",
                "cost",
            ],
            "has_body": True,
            "color": "forest",
        },
        "lore:base": {
            # Abstract base for every lore kind — carries the fields every
            # entry shares (aliases for matching, tags for filtering,
            # related_entries for cross-links, color for per-entry tint,
            # context_policy for how the implicit / explicit context layers
            # treat the entry).
            "name": "Entry",
            "kind": "lore",
            "abstract": True,
            "fields": ["aliases", "tags", "related_entries", "color", "context_policy"],
            "color": "slate-blue",
            # Lore entries call their title a "Name" (#116). Expressed as a
            # per-type label override on the intrinsic `title` field rather
            # than a hardcoded per-kind label in the editor — inherited by
            # every lore kind, and users can further relabel per type.
            "field_overrides": {"title": {"label": "Name"}},
        },
        "lore:character": {
            "name": "Character",
            "icon": "user",
            "kind": "lore",
            "parent": "lore:base",
            "fields": ["role", "pronouns", "home_place", "character_cost"],
        },
        "lore:location": {
            # Local key aligned to its "Location" display (#85); the old key
            # was `place`, a documented key/display mismatch scar removed in
            # the pre-1.0 FQN cleanup. Matches the `location` field on scene.
            "name": "Location",
            "icon": "map-pin",
            "kind": "lore",
            "parent": "lore:base",
            "fields": ["location_type", "region"],
        },
        "lore:item": {
            "name": "Item",
            "kind": "lore",
            "parent": "lore:base",
            "fields": [],
        },
        "lore:note": {
            # The generic in-world lore entry: a typeless note (a loose canon
            # fact, a concept, a faction blurb) and the default lore entry_type.
            # Distinct from the `research` kind — that is the author's
            # out-of-world reference *tree* (docs/research-strategy.md); a note
            # lives in the flat Lore collection and joins lore references + AI
            # context. Reinstated after an overeager research-era deprecation (#963).
            "name": "Note",
            "icon": "notebook",
            "kind": "lore",
            "parent": "lore:base",
            "fields": [],
        },
        "research:base": {
            # Abstract parent for the research-kind tree. Mirrors
            # `manuscript_structure` for the manuscript tree: not
            # instantiated directly, used as the shared parent so the
            # picker/matcher can group by kind and entry_type inheritance
            # works the same way.
            "name": "Research",
            "kind": "research",
            "abstract": True,
            "fields": [],
            "has_body": False,
        },
        "research:topic": {
            "name": "Topic",
            "icon": "folder",
            "kind": "research",
            "parent": "research:base",
            "fields": [],
            "has_body": False,
            # A research topic is a tree container (folder-like grouping node),
            # not something that opens in a NodeEditor.
            "opens_in": "tree_container",
        },
        "research:note": {
            # Research note — prose body + tags. Aliases / related_entries
            # / context_policy are intentionally left off v1 (per the
            # research-strategy decisions); notes participate in AI
            # context via the explicit picker for now.
            "name": "Note",
            "icon": "notebook",
            "kind": "research",
            "parent": "research:base",
            "fields": ["tags"],
            "has_body": True,
        },
        "mutation_set:mutation_set": {
            # Reusable mutation set (#62): a body-less bundle of
            # (field, op, value) rows + a target lore entry-type. Concrete (not
            # abstract) so sets can be created directly; entry_type sub-classing
            # (e.g. shapeshift vs promotion families) stays available but unused.
            "name": "Mutation set",
            "icon": "arrows-shuffle",
            "kind": "mutation_set",
            # ADR-0055 §3: `target_entity` is the OPTIONAL entity pin. Declaring
            # it as a schema `entity_ref` (stored in `metadata`, not the top-level
            # front-matter that carries `target_entry_type`/`rows`) is what earns
            # the set→subject edge and reference-integrity for free — the same
            # deal `subject` gets on chat:chat_session. Unset ⇒ reusable template.
            "fields": ["target_entity"],
            "has_body": False,
            # Mutation sets are authored/applied through a dialog, not a
            # NodeEditor.
            "opens_in": "dialog",
        },
        "plot:base": {
            # Abstract root for the `plot` kind, mirroring lore:base / prompt:base
            # (#724). Every multi-type kind needs one: `kindRootEntryTypeId` /
            # `defaultView(kind)` resolve the whole-kind roster as
            # `descendants_of:<kind>:base`, so without a single abstract root the
            # plot types are unrelated parentless siblings and the default view
            # collapses to just the first one — which left the Plot templates pane
            # empty. Carries no shared fields (plotline/template/board share none).
            "name": "Plot",
            "kind": "plot",
            "abstract": True,
            "fields": [],
        },
        "plot:thread": {
            # Abstract beat-holder base (ADR-0080 §1): the contract a plotline and a
            # character arc SHARE — a colour (`color`, hoisted here per Amendment
            # 1 §1 so both subtypes tint), an instantiated beat roster
            # (`instance_beats`) plus the template-lineage snapshot
            # (`source_template_*`). Never instantiated (like plot:base). Its two
            # concrete children are plot:plotline (external events; can be a
            # card's primary thread) and plot:character_arc (a character's
            # internal change; + character binding; never primary, §4). What they
            # share lives HERE, not in one inheriting from the other, so an arc
            # reuses the beat machinery without being an `is_a` plotline
            # (ADR-0080 §1/§4). `has_body` here so both children inherit the
            # prose description body.
            "name": "Thread",
            "kind": "plot",
            "abstract": True,
            "parent": "plot:base",
            "fields": [
                "color",
                "instance_beats",
                "source_template_id",
                "source_template_name",
                "source_ai_guidance",
                "source_diagnostic_questions",
                "source_weak_spots",
            ],
            "has_body": True,
        },
        "plot:plotline": {
            # A story thread — and, per ADR-0053, an instance of a plot template:
            # one node kind, no separate "arc". The intrinsic title is its name;
            # `color` (inherited from the shared `plot:thread` base, Amendment 1
            # §1) tints its chips + the cards it is primary on; the prose body is
            # its description. The beat roster (`instance_beats`) and
            # template-lineage snapshot (`source_template_*`) are also inherited
            # from `plot:thread` (ADR-0080 §1) — this type adds only `genre`.
            # Cards reference one as their primary plotline and fulfil its beats
            # (card `beat_links`). An ordinary flat Node under `plot/`, layered
            # like lore.
            "name": "Plotline",
            "icon": "route",
            "kind": "plot",
            "parent": "plot:thread",
            "fields": [
                "genre",
            ],
            "has_body": True,
            "color": "plum",
        },
        "plot:character_arc": {
            # A character arc (ADR-0080): the plotline's SIBLING under the shared
            # plot:thread beat-holder base — NOT an `is_a` plotline. It binds the
            # `character` (§2) whose internal change it tracks; that binding is what
            # makes a thread an arc rather than a subplot. Its beats (inherited
            # `instance_beats`) are change-beats — states of the character, realised
            # through the plot's events; a card links one to mean "this card CAUSES
            # this change" (§3). Never a card's primary/colour thread (§4: the card
            # `plotline` ref targets plot:plotline exactly, so an arc is excluded by
            # type). Its own glyph (seedling — growth/becoming) so the writer meets
            # it as a distinct object. `instance_beats` + `source_template_*` +
            # `has_body` + `color` are inherited from plot:thread (Amendment 1 §1:
            # an arc's colour default resolves to the bound character's, on the
            # frontend, when unset here — still overridable per arc); it adds
            # only `character`.
            "name": "Character arc",
            "icon": "seedling",
            "kind": "plot",
            "parent": "plot:thread",
            "fields": [
                "character",
            ],
        },
        "plot:card": {
            # A unit of story function (ADR-0048 §1): "this happens, and it does
            # this job for the story." The synopsis is the prose body; `plotline`
            # points at its primary thread; `scene` is an optional attachment
            # (0..1 scene per card, 0..n cards per scene — no uniqueness the other
            # way). Claims (§4) are deferred: the closed beat roster they validate
            # against only exists once templates are instantiated (a later slice),
            # so per §4 ("widen when a workflow demands it, not before") the card
            # carries no claims field yet — it is added when a workflow first
            # exercises it, or by a writer as a schema extension. A flat Node under
            # `plot/`, layered like the plotline it references.
            "name": "Card",
            "icon": "cards",
            "kind": "plot",
            "parent": "plot:base",
            "fields": ["plotline", "scene", "page_status", "beat_links", "causal_links", "follow_ups"],
            "has_body": True,
        },
        "plot:template": {
            # A diagnostic story-structure lens (ADR-0048 S4b), shipped read-only
            # by the built-in Library (ADR-0049) or cloned into a project to adapt.
            # `genre` and the `beats` roster are metadata fields (#1744, #736) —
            # visible + editable via MetadataPanel like any field; the prose guide
            # is the body. The remaining template-level attributes (family,
            # ai_use_guidance, …) still ride in the `template:` front-matter block.
            "name": "Plot template",
            "icon": "layout-grid",
            "kind": "plot",
            "parent": "plot:base",
            "fields": ["genre", "beats"],
            "has_body": True,
        },
        "plot:board": {
            # The plot board — a per-project layout singleton (ADR-0048 §3).
            # Presentation only (card positions, per-column ordering, collapsed
            # groups, viewport); it owns no story data. Addressed by path like
            # the project node (file `plot-board.md`), never listed or created
            # as an ordinary instance. Declared here so its entry_type resolves;
            # it carries no schema metadata fields — the layout is an opaque
            # payload on the node, not user metadata.
            "name": "Board",
            "icon": "layout-board",
            "kind": "plot",
            "parent": "plot:base",
            "fields": [],
            "has_body": False,
            # The plot board opens as its own canvas surface, not a NodeEditor.
            "opens_in": "board",
        },
        "prompt:base": {
            "name": "Prompt",
            "kind": "prompt",
            "abstract": True,
            "fields": ["preferred_assistant_id", "assistant_tags", "color", "disposition", "runnable"],
            "has_body": True,
            "body_editor": "code",
            "body_language": "jinja2",
            "color": "warm-brown",
        },
        "prompt:general": {
            "name": "General",
            "icon": "prompt",
            "kind": "prompt",
            "parent": "prompt:base",
            "fields": [],
            "has_body": True,
        },
        "prompt:snippet": {
            "name": "Snippet",
            "icon": "quote",
            "kind": "prompt",
            "parent": "prompt:base",
            "fields": [],
            "has_body": True,
        },
        "assistant:assistant": {
            "name": "Assistant",
            "icon": "sparkles",
            "kind": "assistant",
            "fields": [
                "ai_provider",
                "ai_capability_tier",
                "ai_model",
                "ai_temperature",
                "ai_max_tokens",
                "ai_thinking",
                "summary",
                "assistant_tags",
                "color",
                "listed",
                "position",
            ],
            "has_body": False,
            "color": "graphite",
        },
        "project:project": {
            "name": "Project",
            "icon": "book-2",
            "kind": "project",
            # `color` leads: it is the level/inheritance cue the app reads
            # elsewhere (the `--star` axis, level pills), and field order is the
            # display order everywhere — including the create-wizard review step,
            # whose fixed 560px frame pushed a trailing `color` below the fold
            # (#560). Placed at the top as if a user had dragged it up, rather
            # than special-casing the review pane's presentation order.
            "fields": [
                "color",
                "author",
                "language",
                "spelling",
                # Book-level narration default: mode + the viewpoint character,
                # both cascade down the manuscript (ADR-0079 Amendment 2). A
                # single-POV novel sets pov once here; scenes inherit by absence.
                "pov_mode",
                "pov",
                "tense",
                "measurement_system",
                "target_word_count",
                "series_number",
                "path",
                "project_cost",
            ],
            "has_body": True,
            "color": "violet",
        },
        "chat:chat_session": {
            # Chat-as-node base type. Concrete (not abstract) because chats are
            # instantiated directly via the chats pane. Storage is a Node file at
            # <project>/chats/<id>.md: the ChatSession session state (prompt
            # binding, assistant, system brief, journal) lives in front matter,
            # and the message transcript lives in the node *body* (ADR-0051 S2) —
            # kept out of front matter so the index never parses it. `subject` is
            # a live entity_ref (what the chat is about); `color` is the per-node
            # tint. Neither is written by any editor today, but declaring
            # `subject` is what makes the chat→subject edge extract.
            "name": "Chat",
            "icon": "message-circle",
            "kind": "chat",
            # `staged_set` (ADR-0055 S4): the mutation set a committing brainstorm
            # OWNS — a second entity_ref, into the mutation_set kind, earning the
            # chat->set edge exactly as `subject` earns chat->subject.
            "fields": ["subject", "staged_set", "color"],
            "has_body": False,
            "body_shape": "chat",
            "color": "graphite",
        },
        "view:view": {
            # Saved view (0.5.0, #35/#78): a frontmatter-only node carrying a
            # ViewSpec (kind + set-algebra expr + sort). Concrete so views are
            # created directly; body-less (the spec lives in front matter, not a
            # prose body). No schema fields in v1 — the view designer edits the
            # spec, not metadata. See ADR-0021.
            "name": "View",
            "icon": "eye",
            "kind": "view",
            "fields": [],
            "has_body": False,
            # Routes the NodeEditor to the Svelte Flow view designer body
            # (0.5.0 step 3, #80) instead of the inert none-shape.
            "body_shape": "view",
        },
        "tag:base": {
            # Abstract root for the `tag` kind (ADR-0082 slice 1): a label. A
            # vocabulary is a concrete sub-type (tag:tag, tag:assistant_tag, or
            # a user-authored one like tag:motifs); a tag is an entry of it, and
            # a field that holds tags is a reference list into the vocabulary.
            "name": "Tag",
            "kind": "tag",
            "abstract": True,
            "fields": ["color"],
            "has_body": False,
            "description": (
                "A label. Tags are nodes: a vocabulary is a tag type, a tag is "
                "an entry of it, and a field that holds tags is a reference "
                "list into the vocabulary (ADR-0082)."
            ),
        },
        "tag:tag": {
            # The general-purpose vocabulary (0082 slice 1). Concrete so tags
            # are created directly from the picker; body-less like a view.
            "name": "Tag",
            "icon": "tag",
            "kind": "tag",
            "parent": "tag:base",
            "fields": [],
            "has_body": False,
            "description": "General tags for grouping and filtering. Never shown to the reader.",
            # A tag is minted from a picker, not authored through the
            # Conversations panel — kept out of the Offer-on picker's "editor"
            # host set the same way mutation_set is (review fix).
            "opens_in": "dialog",
        },
        "tag:assistant_tag": {
            # The assistant vocabulary (ADR-0082 slice 1): matches prompts to
            # assistants. Lives at the machine layer, alongside assistants
            # themselves (MACHINE_LAYER_FAMILIES, references.py).
            "name": "Assistant tag",
            "icon": "tag",
            "kind": "tag",
            "parent": "tag:base",
            "fields": [],
            "has_body": False,
            "description": "Tags that match prompts to assistants.",
            "opens_in": "dialog",
        },
    },
    "groups": {
        "plot_beat": {
            # ADR-0048 S7 Slice 1 (#736): a plot template's beat roster is a real
            # ordered structured-list field (`beats`), not an opaque `template:`
            # payload — so beats render + edit through the standard MetadataPanel
            # widget like any other field. This is the first built-in item_group;
            # its members are the beat's shape: a short title, the story function
            # it asserts, optional authoring guidance, whether the beat is a
            # required part of the structure, and a stable `id` the card->beat
            # links of Slice 3 point at (preserved verbatim from the roster so
            # that slice needs no re-migration).
            "name": "Plot beat",
            "members": [
                {"key": "title", "name": "Title", "type": "text"},
                {"key": "function", "name": "Function", "type": "long_text"},
                {"key": "guidance", "name": "Guidance", "type": "long_text"},
                {"key": "required", "name": "Required", "type": "boolean", "default": True},
                {"key": "id", "name": "ID", "type": "text"},
            ],
        },
        "plot_instance_beat": {
            # A specialized beat on a template instance (ADR-0048 S7 Slice 2, #776).
            # The `plot_beat` shape plus one member: `specifics`, where the generic
            # requirement becomes concrete to this book. The generic title /
            # function / guidance ride along (snapshot-copied at instantiate) so the
            # writer specializes *against* the requirement instead of losing it; the
            # stable `id` carries the beat's identity for the card->beat links of a
            # later slice. Kept distinct from `plot_beat` (rather than adding
            # `specifics` there) so a template's read-only beats never sprout an
            # empty book-specialization slot they can't use.
            "name": "Plot instance beat",
            # Instantiation machinery, not an author-facing shape (#1003).
            "system": True,
            "members": [
                {"key": "title", "name": "Title", "type": "text"},
                {"key": "function", "name": "Function", "type": "long_text"},
                {"key": "guidance", "name": "Guidance", "type": "long_text"},
                {"key": "specifics", "name": "Specifics", "type": "long_text"},
                {"key": "required", "name": "Required", "type": "boolean", "default": True},
                {"key": "id", "name": "ID", "type": "text"},
            ],
        },
        "plot_beat_link": {
            # A card->beat link (ADR-0048 S7 Slice 3b; ADR-0053): the card names
            # which beat of which plotline it fulfils. Consumed nested as the
            # `beat_links` list field's item shape, so a card carries a LIST of these
            # (multiple beats, across multiple plotlines, per card). Both members are
            # plain `text`, NOT `entity_ref`: v1 keeps refs out of item shapes (the
            # top-level ref-healers walk only top-level values), so `plotline` holds
            # the plotline node id as text and plot.py heals these by hand on card
            # save + read — dropping a link whose plotline is gone or whose `beat_id`
            # has left that plotline's roster. The `plotline` member holds a
            # `plot:thread` holder id — a plotline OR a character arc (ADR-0080
            # §3); the key name is retained for zero-migration though it may hold
            # an arc.
            "name": "Beat link",
            # Card→beat wiring, not an author-facing shape (#1003).
            "system": True,
            "members": [
                {"key": "plotline", "name": "Plotline", "type": "text"},
                {"key": "beat_id", "name": "Beat", "type": "text"},
            ],
        },
        "plot_causal_link": {
            # An authored card->card causal edge (ADR-0048 S7 Slice 6b): "this card
            # leads to that card". The single member `target` holds the destination
            # card's node id as plain `text` (v1 bars refs from item shapes, same as
            # `plot_beat_link`), so plot.py heals these by hand on card save + read —
            # dropping a link whose target card is gone, points at the card itself, or
            # duplicates another. v1 is UNTYPED: one directed edge, no label; a `type`
            # member is a later slice, added when a workflow first demands it.
            "name": "Causal link",
            # Card→card wiring, not an author-facing shape (#1003).
            "system": True,
            "members": [
                {"key": "target", "name": "Target", "type": "text"},
            ],
        },
    },
    "fields": {
        # Intrinsic identity triple (#116). Every node carries `id`, `title`,
        # and `entry_type` in top-level front matter — not in `metadata`.
        # Declaring them as fields (marked `intrinsic`) surfaces them in the
        # field-inheritance hierarchy so Views can filter/sort by title/type
        # and the schema editor can rename/hide them per layer. Value is read
        # from the node property keyed by the field id, never from metadata.
        # The resolver injects these into every entry_type's field list, so
        # they need no membership entry on individual types.
        "title": {"name": "Title", "type": "text", "intrinsic": True},
        "entry_type": {"name": "Type", "type": "text", "intrinsic": True},
        # `id` is machine identity — hidden by default so it doesn't clutter
        # the rail / picker; unhide per type in the schema editor to filter by it.
        "id": {"name": "ID", "type": "text", "intrinsic": True, "hidden": True},
        # `body` is the conditional intrinsic (ADR-0059 §A/§B): the node's
        # top-level markdown body given a field definition so it carries a label
        # and — decisively — a description that tells the commit model what the
        # body is FOR. Value lives on `node.body` (never `metadata.body`); the
        # resolver injects this key into the field membership of `has_body` types
        # only (unlike the always-injected identity triple), and the description
        # below drives the extraction contract's body clause in place of the old
        # hardcoded "complete markdown body" prose that invited the field dump.
        "body": {
            "name": "Body",
            "type": "long_text",
            "intrinsic": True,
            "ai_proposable": True,
            "description": (
                "Free-form prose for what the structured fields do not capture — "
                "the entry's narrative, notes, or main text. Do NOT restate values "
                "that already live in the fields (aliases, tags, appearance, etc.); "
                "the body is for what has no field of its own."
            ),
        },
        "status": {
            "name": "Status",
            "description": (
                "Where this entry is in your workflow — draft, revised, or "
                "complete. Organizational only; it does not change the prose."
            ),
            "type": "select",
            # Colored options demonstrate the ColoredSelect path. Authors
            # can recolor or rename via the Detail Field editor; storage
            # is the SelectOption object shape — bare strings still parse
            # via the back-compat validator on MetadataFieldDefinition.
            "options": [
                {"value": "draft", "color": "stone"},
                {"value": "revised", "color": "amber"},
                {"value": "complete", "color": "moss"},
            ],
            # New scenes open at the start of the workflow rather than blank.
            "default": "draft",
        },
        "summary": {
            "name": "Summary",
            "description": (
                "A one- or two-sentence gist of this entry — what it is at a "
                "glance. Used as a compact stand-in for the full body in lists and "
                "AI context."
            ),
            "type": "long_text",
        },
        "beats": {
            # The plot-template beat roster (ADR-0048 S7 Slice 1, #736). An ordered
            # structured-list field whose items take the `plot_beat` group shape;
            # `plot:template` is its consumer. Replaces the opaque `template.plot_points`
            # payload so beats are visible + editable through the field system (goal 7).
            "name": "Plot beats",
            "type": "list",
            "item_group": "plot_beat",
        },
        "instance_beats": {
            # A plotline's beat roster (ADR-0048 S7 Slice 2, #776; ADR-0053 §1). The
            # `beats` field's sibling, bound to `plot_instance_beat` (which adds the
            # per-beat `specifics` member); `plot:plotline` is its consumer. A separate
            # field, not a reuse of the template's `beats`, because a field binds to
            # exactly one item_group and a plotline's beats carry the extra `specifics`
            # member (a read-only template beat has no book-specialization slot). Named
            # distinctly from the template's `beats` ("Plot beats") so the two are
            # tellable apart in the field catalog.
            "name": "Specialized beats",
            "type": "list",
            "item_group": "plot_instance_beat",
        },
        "genre": {
            # Genre/premise, authored on a `plot:template` and seeded onto each
            # `plot:plotline` at instantiate (#1728, #1744). On the template it is
            # the writer's own metadata field — editable in the panel like any node
            # field, not a hidden spec attribute; on a plotline it is freely
            # editable and independent of the book's genre (a thriller book's
            # romance subplot carries its own). Free text (not an enum) so a
            # genre-neutral structure can explain its breadth; long_text because a
            # premise runs past a single line. Fed to the AI via read_plot_context
            # so a plotline brainstorm knows what it is writing. Visible (not
            # hidden): author-facing, unlike the source_* lineage snapshots.
            "name": "Genre",
            "type": "long_text",
        },
        "source_template_id": {
            # Lineage snapshot (ADR-0048 S7 Slice 2, #776; ADR-0053): the stable id of
            # the template a `plot:plotline` was instantiated from, captured at
            # instantiate. Empty for an ad-hoc plotline. Hidden so it doesn't clutter
            # the panel; unhide per type to filter/group plotlines by their source in a
            # View. A plain text snapshot, not a live `entity_ref` — the lineage must
            # survive the source template being edited, renamed, or deleted, which a
            # healing ref would not.
            "name": "Source template id",
            "type": "text",
            "hidden": True,
        },
        "source_template_name": {
            # The display name of the source template, snapshotted at instantiate so
            # the plotline can show "The Hero's Journey" without re-resolving a
            # (possibly inherited or since-deleted) template. Empty for an ad-hoc
            # plotline. Hidden, like `source_template_id`.
            "name": "Source template",
            "type": "text",
            "hidden": True,
        },
        "source_ai_guidance": {
            # Guidance snapshot (ADR-0053; ADR-0048 S7 item 7): the source template's
            # `ai_use_guidance` — how to use this structure as a diagnostic lens —
            # copied onto the plotline at instantiate so `read_plot_context` feeds the
            # AI the structural intent, not just per-beat one-liners. A snapshot (not a
            # live read of the source template) for the same reason the beats are: the
            # writer can specialize the beats, so guidance read live would describe the
            # ORIGINAL structure while the plotline shows a diverged one. Empty for an
            # ad-hoc plotline. Hidden, like the lineage fields.
            "name": "Structure guidance",
            "type": "text",
            "hidden": True,
        },
        "source_diagnostic_questions": {
            # Guidance snapshot (ADR-0053): the source template's
            # `global_diagnostic_questions` — the questions to ask of the draft against
            # this structure — captured at instantiate beside `source_ai_guidance`. A
            # flat text `list` (`item_type` scalar sugar, like `follow_ups`). Empty for
            # an ad-hoc plotline. Hidden, like the lineage fields.
            "name": "Diagnostic questions",
            "type": "list",
            "item_type": "text",
            "hidden": True,
        },
        "source_weak_spots": {
            # Guidance snapshot (ADR-0048 S7 item 7, #948): the source template's
            # `common_weak_spots` — the structure's characteristic failure modes, the
            # things the diagnostic checks the draft against — captured at instantiate
            # beside the other guidance snapshots. A flat text `list` (`item_type`
            # scalar, like `source_diagnostic_questions`). Empty for an ad-hoc plotline.
            # Hidden, like the lineage fields.
            "name": "Common weak spots",
            "type": "list",
            "item_type": "text",
            "hidden": True,
        },
        "dynamics": {
            # Scene-current per-character beats for the roleplay use case.
            # The roleplay template reads this verbatim; both characters
            # see all beats so the AI plays them as one continuous scene.
            "name": "Dynamics",
            "description": (
                "Scene-current beats for the characters in this scene — how each is "
                "behaving and what's driving them right now. Read verbatim by the "
                "roleplay AI as direction; present-tense, not backstory."
            ),
            "type": "long_text",
        },
        "aliases": {
            "name": "Aliases",
            "description": (
                "Other names this entry goes by (nicknames, titles, epithets). "
                "Used to auto-detect mentions of it in your prose and pull it into "
                "AI context."
            ),
            "type": "multi_select",
        },
        "tags": {
            # ADR-0082 §2: an ordinary entity_ref_list into the general tag
            # vocabulary (kind `tag`, entry type `tag:tag`), not the retired
            # `tags` value type. `create_missing` lets a typed name that
            # resolves to nothing mint a new tag node at the save's write layer.
            "name": "Tags",
            "description": (
                "Labels for grouping and filtering entries. For your own "
                "organization and Views; never shown to the reader."
            ),
            "type": "entity_ref_list",
            "picker_config": {"sources": [{"kind": "tag", "expr": {"type": "tag:tag"}}], "create_missing": True},
        },
        "context_policy": {
            # How the AI-context layers treat this entry. Values:
            #   - "always":      pulled into every implicit-mode render
            #   - "auto":        textual alias match (current default)
            #   - "manual_only": skipped by the matcher; explicit picker only
            #   - "never":       hidden from picker and matcher
            # Default "auto" preserves the pre-policy behavior — existing
            # entries that omit the field keep their current treatment.
            "name": "Context policy",
            "description": (
                "Controls when this entry is fed to the AI as context: 'always' "
                "(every request), 'auto' (when its name or an alias is mentioned — "
                "the default), 'manual_only' (only when you pick it), or 'never' "
                "(excluded everywhere)."
            ),
            "type": "select",
            "options": [
                {"value": "always", "label": "Always include"},
                {"value": "auto", "label": "Automatic (alias match)"},
                {"value": "manual_only", "label": "Manual only"},
                {"value": "never", "label": "Never include"},
            ],
            # A required select: "none" is meaningless for an entry's context
            # policy, so it declares a default. The default is the terminal
            # fallback applied at *evaluation* (`_entry_context_policy`), never
            # written to disk — front matter stays sparse, and an absent field
            # resolves to "auto" (#1421). The default's presence is what makes the
            # editor drop the "(none)" pick and reject a blank save.
            "default": "auto",
            # Author-owned cost/visibility knob (ADR-0057): a commit must never
            # set it (ADR-0059 §F). The one built-in field this ADR flips.
            "ai_proposable": False,
        },
        "color": {
            # Instance-level color override (palette swatch id). Resolves
            # to a stripe color on NodeRows + the manuscript tree, and
            # ultimately to chip / dot color in the context picker. When
            # unset, the entry-type's `color` (or its parent's) wins; see
            # resolveColor in frontend/src/colors.ts. Built-in field so
            # every entry kind can opt in to per-entry tinting without
            # the user having to add a schema field.
            "name": "Color",
            "description": (
                "A palette swatch name for tinting this entry in lists and the "
                "manuscript tree (e.g. 'moss', 'amber', 'slate') — not a hex code, "
                "and not a description of a color."
            ),
            "type": "color",
        },
        "characters": {
            "name": "Characters",
            "description": (
                "The characters who appear in this scene — references to existing "
                "character entries, not free text."
            ),
            "type": "entity_ref_list",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:character"}}]},
        },
        "pov": {
            "name": "POV",
            "description": (
                "The point-of-view character the narration follows — a reference "
                "to one existing character entry. Cascades down the manuscript "
                "(book / act / chapter / scene) unless a level below overrides it."
            ),
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:character"}}]},
        },
        "character": {
            # The character a `plot:character_arc` is about (ADR-0080 §2): the arc's
            # defining reference — "whose change is this?". A single live `entity_ref`
            # into the lore character kind, mirroring `pov`. A plotline has NO such
            # field. Not hard-required at save in this slice — ADR §Open defers the
            # binding timing/UX (bound at instantiate vs after), so an arc may be
            # briefly unbound; the "an arc names its character" invariant lands with
            # that later UX work, not as a save-time check here.
            "name": "Character",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:character"}}]},
        },
        "location": {
            "name": "Location",
            "description": (
                "Where this scene takes place — a reference to an existing "
                "location entry."
            ),
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:location"}}]},
        },
        "role": {
            "name": "Role",
            "description": (
                "This character's role in the story — the protagonist, the "
                "antagonist, a supporting player, or a minor walk-on."
            ),
            "type": "select",
            "options": ["protagonist", "antagonist", "supporting", "minor"],
        },
        "pronouns": {
            "name": "Pronouns",
            "description": (
                "The pronouns this character goes by. A starter set — add your own "
                "options per project for anyone these don't fit."
            ),
            "type": "select",
            "options": ["He/Him", "She/Her", "They/Them"],
        },
        "home_place": {
            # Adopted by lore:character (#1316): where the character is from.
            "name": "Home Place",
            "description": (
                "Where this character is from or based — a reference to an "
                "existing location entry."
            ),
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:location"}}]},
        },
        "location_type": {
            "name": "Location type",
            "description": (
                "What kind of place this is — a settlement, a single building, a "
                "wider region, or a landmark."
            ),
            "type": "select",
            "options": ["settlement", "building", "region", "landmark"],
        },
        "region": {
            "name": "Region",
            "description": (
                "The larger place that contains this one — a reference to another "
                "location entry (e.g. the city a building sits in)."
            ),
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:location"}}]},
        },
        "related_entries": {
            "name": "Related Entries",
            "description": (
                "Other lore entries connected to this one (people, places, "
                "factions, objects) — references to existing entries, for cross-"
                "linking and AI context."
            ),
            "type": "entity_ref_list",
            "picker_config": {"sources": [{"kind": "lore"}]},
        },
        "subject": {
            # ADR-0051 S2: what a chat is *about* — the node it was opened
            # against (a lore entry, character, or scene). A live `entity_ref`,
            # so the index extracts a chat→subject edge and the subject surfaces
            # its conversations through the ordinary backlink machinery, with no
            # chat-specific traversal. Kind-neutral: the picker offers lore
            # entries and scenes (character = lore:character).
            "name": "Subject",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "lore"}, {"kind": "manuscript"}]},
        },
        "staged_set": {
            # ADR-0055 S4: the mutation set a chat OWNS — the staged, position-
            # free change a committing brainstorm is shaping (its work-product).
            # A live `entity_ref` into the mutation_set kind, mirroring `subject`:
            # it lives in `metadata`, so the index extracts a chat->set edge (the
            # set surfaces the chats refining it) and deleting the set purges the
            # chat's pin. Singular — a chat owns one mutation set; a distinct
            # set is a new chat with its own context. Empty for impersonate /
            # freeform chats. On send the set's rows are seeded into the AI context
            # so a resumed conversation continues refining the same set.
            # (Field id kept as `staged_set`; only the label reads "Mutation set".)
            "name": "Mutation set",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "mutation_set"}]},
        },
        "target_entity": {
            # ADR-0055 §3: the OPTIONAL entity a mutation set is pinned to — the
            # character this mutation set is *about*. Unset ⇒ the reusable,
            # type-scoped template of #62 (entity bound at apply time); set ⇒ an
            # entity-pinned one-off, offered only for its own entity and stamping
            # it on apply. A live `entity_ref` so it rides the same kind-neutral
            # edge machinery as `subject`: the pinned entity lists its staged
            # changes through the reverse index, and deleting it purges the pin.
            "name": "Pinned to",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "lore"}]},
        },
        "plotline": {
            # A single reference to a `plot:plotline` thread. A shared catalog
            # field (any type can reuse it); its current consumer is the card
            # (ADR-0048 §1), which points at its one primary plotline — the
            # plotline's color tints the card on the board (S7). Single ref, not
            # a list; secondary-thread modelling waits for a workflow.
            "name": "Plotline",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "plot", "expr": {"type": "plot:plotline"}}]},
        },
        "scene": {
            # A single optional reference to a scene. A shared catalog field; its
            # current consumer is the card's scene attachment (ADR-0048 §1): the
            # scene that realizes the card, or unset for backstory / not-yet-
            # written material (0..1 scene per card; the reverse is unconstrained).
            # When the referenced scene is deleted the ref is cleared — blanked on
            # the referrer, whether by the delete's reference purge (same project)
            # or read-side healing (an ancestor delete). The ADR's "visible dangle"
            # on the board is a later, board-layer concern, not this strip.
            "name": "Scene",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "manuscript", "expr": {"type": "manuscript:scene"}}]},
        },
        "page_status": {
            # A card's page status (ADR-0048 S7 Slice 3b): whether its story beat is
            # realized in prose. `on_page` is DERIVED — a card with a `scene` link is
            # on the page, so plot.py forces it on card save + read and clears a stale
            # `on_page` when the scene is removed. Absent (the sparse default) reads as
            # `unwritten` — a placeholder to promote; `off_page` is the writer's
            # deliberate "this happens off-screen, no scene ever" (diagnostics must not
            # nag it toward a scene). So a writer only authors off_page vs unwritten;
            # on_page is the app's business, driven by the scene attachment.
            "name": "Page status",
            "type": "select",
            "options": [
                {"value": "unwritten", "color": "stone"},
                {"value": "off_page", "color": "graphite"},
                {"value": "on_page", "color": "moss"},
            ],
        },
        "beat_links": {
            # A card's beat links (ADR-0048 S7 Slice 3b; ADR-0053): the beats this card
            # fulfils, each a `plot_beat_link` (a plotline id + a beat id within that
            # plotline's roster). An ordered `list` so one card can serve several beats,
            # across several plotlines. Its consumer is `plot:card`. Integrity is
            # plot-local: the item shape is plain text (v1 bars refs from item shapes),
            # so plot.py heals dangling links on card save + read, not the top-level
            # reference machinery. Hidden by default, like the lineage id fields
            # (`source_template_id` / `source_template_name`): the members are raw ids
            # meant for the board's link editor (a later slice), not hand-entry in the
            # generic panel.
            "name": "Beat links",
            "type": "list",
            "item_group": "plot_beat_link",
            "hidden": True,
        },
        "causal_links": {
            # A card's authored causal edges (ADR-0048 S7 Slice 6b): the cards this
            # card *leads to*, each a `plot_causal_link` (a target card node id). An
            # ordered `list` so one card can lead to several. Its consumer is
            # `plot:card`. Integrity is plot-local: the item shape is plain text (v1
            # bars refs from item shapes), so plot.py heals dangling / self / duplicate
            # links on card save + read, not the top-level reference machinery. Hidden
            # by default, like `beat_links`: the members are raw ids meant for the
            # board's "Leads to…" link editor, not hand-entry in the generic panel.
            "name": "Causal links",
            "type": "list",
            "item_group": "plot_causal_link",
            "hidden": True,
        },
        "follow_ups": {
            # A light per-card follow-up list (ADR-0048 S8c): loose "still to do on
            # this card" notes — the dissolved remains of the quarry's claims/evidence
            # apparatus (migration principle 2), NOT the scene-scoped todo subsystem.
            # A flat text `list` (the `item_type` sugar → a plain scalar sequence,
            # stored like multi_select): deleting an item IS the "done" gesture, so
            # there is no per-item done flag. Unlike the raw-id link lists above it is
            # visible + hand-editable in the generic panel, and (being a plain,
            # non-hidden `list`) proposable — so the plot-card brainstorm (S8b) can
            # add follow-ups through the same entry-patch it already commits.
            "name": "Follow-ups",
            "description": (
                "Loose 'still to do on this card' notes. Each item is one short "
                "reminder; delete an item when it's done."
            ),
            "type": "list",
            "item_type": "text",
        },
        "word_count": {
            "name": "Word Count",
            "type": "computed",
            "computed": {"source": "body", "function": "word_count"},
        },
        "number": {
            "name": "Number",
            "type": "computed",
            "computed": {"function": "counter", "scope": "siblings"},
        },
        "cost": {
            # Per-scene sum of cost_usd across ai_invocations whose
            # scene_id matches. Sibling fields character_cost / project_cost
            # do the same for lore characters and the project node.
            "name": "AI cost",
            "type": "computed",
            "computed": {"function": "cost", "scope": "scene"},
        },
        "character_cost": {
            # All-time AI cost attributed to this character across every
            # scene — sum of cost_usd where ai_invocations.character_id ==
            # this lore entry's id.
            "name": "AI cost",
            "type": "computed",
            "computed": {"function": "cost", "scope": "character"},
        },
        "project_cost": {
            # Whole-project AI cost — sum of cost_usd across every row in
            # ai_invocations.yaml regardless of scene/character attribution.
            "name": "AI cost",
            "type": "computed",
            "computed": {"function": "cost", "scope": "project"},
        },
        "path": {
            # The project folder's absolute filesystem path. Read-only, and
            # NOT body-derived: its resolver is `read_project_node`, which has
            # the root Path in hand — hence a BUILTIN function, not an
            # authorable one. Rehomed here off the retiring Project pane's
            # identity block (#417 slice 3).
            "name": "Path",
            "type": "computed",
            "computed": {"function": "path"},
        },
        "references": {
            # Any-field backlinks — the built-in node-set computed field
            # (#184, ADR-0029 §G / ADR-0031 §G). Unlike word_count/cost it has
            # NO stored/materialized value: it is resolved at VIEW-EVAL time on
            # the frontend by inverting the forward reference adjacency into a
            # reverse index (views-and-filters.md §14.4), so there is no
            # `computed_metadata` branch for it — the loose function dispatch in
            # computed_metadata.py simply skips the unknown `references` function.
            # `computed.value_type` DECLARES the output payload (node-set) so the
            # view designer can type its `field_of` handles (ADR-0031 §D/§G; the
            # one aspect ADR-0029 left implicit). A catalog field like any other:
            # added/removed per type, reorderable, hideable/relabelable via
            # field_overrides — but NOT seeded into any default type membership
            # (surfacing it as a rail backlinks widget is #15 / Phase 2c), and
            # its definition is built-in (not user-editable, like the other
            # computed fields). `field_of(set, references)` → the referrers.
            "name": "References",
            "type": "computed",
            "computed": {"function": "references", "value_type": "node_set"},
        },
        "listed": {
            # An assistant's CURATION state (#332/#333) — is it in the author's
            # roster, or merely available? Computed, not stored: the value is
            # the layer traversal's answer (`.order.yaml` merged across layers),
            # so it has no place in an assistant's front matter and must not be
            # editable — hand-editing it would assert a curation the ordering
            # files contradict on the next read.
            #
            # `computed.value_type` declares the payload the way `references`
            # does, so surfaces can type it without re-deriving: a `select`, and
            # therefore groupable (the #333 default groups on it) while the
            # field itself stays read-only. This is the shape #232 wants for
            # `source_layer` too — a resolver-stamped field rather than a magic
            # string special-cased in every consumer.
            "name": "Curation",
            "type": "computed",
            "options": [
                {"value": "listed", "label": "Active"},
                {"value": "unlisted", "label": "Unlisted"},
            ],
            "computed": {"function": "assistant_listed", "value_type": "select"},
        },
        "position": {
            # Index in the merged priority sequence, or unset when the assistant
            # is unlisted — an assistant nobody has ordered has no priority to
            # report, and the unlisted tail's order is a fallback rather than an
            # expressed one. Computed for the same reason as `listed`.
            "name": "Priority",
            "type": "computed",
            "computed": {"function": "assistant_position", "value_type": "number"},
        },
        "ai_provider": {
            "name": "Subscription",
            "description": (
                "Which AI subscription this assistant runs on. Its API "
                "credentials and endpoint come from your machine settings, and "
                "the choice scopes which models are available below."
            ),
            "type": "select",
            "options": ["anthropic", "openai", "openrouter", "ollama"],
        },
        "ai_capability_tier": {
            "name": "Capability tier",
            "description": (
                "Pick a tier — Fast, Balanced, Premium, Reasoning or Local — and "
                "the app resolves it to a concrete model for the provider (the "
                "cheapest that fits). Leave it unset to bind an exact model under "
                "Advanced instead."
            ),
            "type": "select",
            "options": ["", "fast", "balanced", "premium", "reasoning", "local"],
        },
        "ai_model": {
            "name": "Model",
            "description": (
                "The exact model this assistant runs. Set automatically from the "
                "capability tier, or pick a specific one under Advanced (which "
                "switches the tier to Custom)."
            ),
            "type": "text",
        },
        "ai_temperature": {
            "name": "Temperature",
            "description": (
                "Sampling temperature: higher is more varied and inventive, lower "
                "more focused and repeatable. Leave blank to use the model's "
                "default."
            ),
            "type": "number",
        },
        "ai_max_tokens": {
            "name": "Max output tokens",
            "description": (
                "Upper bound on the length of a single response, in tokens. Leave "
                "blank to use the model's default."
            ),
            "type": "number",
        },
        "ai_thinking": {
            "name": "Show thinking",
            "description": (
                "For models that support it, surface the model's reasoning "
                "alongside its answer."
            ),
            "type": "boolean",
        },
        "preferred_assistant_id": {
            "name": "Preferred assistant",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "assistant"}]},
        },
        # A prompt's soft assistant scope (ADR-0024): the picker surfaces
        # assistants carrying any of these tags first, and the dynamic default
        # is the topmost matching one. ADR-0082 §2: an entity_ref_list into the
        # assistant-tag vocabulary (kind `tag`, entry type `tag:assistant_tag`),
        # shared with `assistant:assistant`'s own (renamed) field of the same id
        # — one field definition, one vocabulary, referenced by both kinds.
        "assistant_tags": {
            "name": "Preferred assistant tags",
            "type": "entity_ref_list",
            "picker_config": {
                "sources": [{"kind": "tag", "expr": {"type": "tag:assistant_tag"}}],
                "create_missing": True,
            },
        },
        # A prompt's DISPOSITION and standalone-runnability (#951/#1433/#1684),
        # derived at read from the entry's own `context_strategy.output` —
        # rationale, mapping, and the shelf-order/option-order contract live in
        # prompt_disposition.py. Same `select` value_type shape as `listed`:
        # groupable/filterable while staying read-only.
        "disposition": {
            "name": "Disposition",
            "type": "computed",
            "options": [{"value": label, "label": label} for label in PROMPT_DISPOSITIONS],
            "computed": {"function": "prompt_disposition", "value_type": "select"},
        },
        "runnable": {
            "name": "Runnable",
            "type": "computed",
            "options": [{"value": PROMPT_RUNNABLE_VALUE, "label": "Runnable"}],
            "computed": {"function": "prompt_runnable", "value_type": "select"},
        },
        "author": {"name": "Author", "type": "text"},
        # #317: the built-in project-node vocabulary. These are `select`s rather
        # than free text so the model gets a constrained, resolvable value (a
        # world's units/tense/spelling instead of a US default the author had no
        # way to state), and — because `project` is a kind — every roster below
        # is user-extensible through a schema layer, so the built-ins only have to
        # be a sensible, opinionated start. `narrative_pov`/`genre` were text;
        # `genre` is dropped (a keyword can't carry it — a future Lore treatment),
        # `narrative_pov` becomes the richer `pov_mode` roster. All friendly-
        # labelled: a select never shows a raw key.
        "language": {
            "name": "Language",
            "type": "select",
            "options": [
                {"value": "en", "label": "English"},
                {"value": "es", "label": "Spanish"},
                {"value": "fr", "label": "French"},
                {"value": "de", "label": "German"},
                {"value": "it", "label": "Italian"},
                {"value": "pt", "label": "Portuguese"},
                {"value": "nl", "label": "Dutch"},
                {"value": "sv", "label": "Swedish"},
                {"value": "da", "label": "Danish"},
                {"value": "ja", "label": "Japanese"},
                {"value": "zh", "label": "Chinese"},
            ],
        },
        # A sub-choice of `language` (§6): the wizard filters these by the chosen
        # language, but the schema field itself carries the full roster — the
        # dependent narrowing is a UI concern, not a storage one.
        "spelling": {
            "name": "Spelling",
            "type": "select",
            "options": [
                {"value": "en_GB", "label": "British English"},
                {"value": "en_US", "label": "American English"},
                {"value": "en_AU", "label": "Australian English"},
                {"value": "en_CA", "label": "Canadian English"},
            ],
        },
        "pov_mode": {
            "name": "Narrative POV",
            "type": "select",
            "options": [
                {"value": "first", "label": "First person"},
                {"value": "second", "label": "Second person"},
                {"value": "third_limited", "label": "Third person — limited"},
                {"value": "third_close", "label": "Third person — close"},
                {"value": "third_omniscient", "label": "Third person — omniscient"},
                {"value": "third_objective", "label": "Third person — objective"},
                {"value": "multiple_alternating", "label": "Multiple / alternating"},
            ],
        },
        "tense": {
            "name": "Tense",
            "type": "select",
            "options": [
                {"value": "past", "label": "Past"},
                {"value": "present", "label": "Present"},
            ],
        },
        # Imperial and US customary agree on length (a foot is a foot) but differ
        # on volume and weight, so they are distinct options; `in_world` is for a
        # secondary-world setting that should name no Earth system at all (#317).
        "measurement_system": {
            "name": "Measurement system",
            "type": "select",
            "options": [
                {"value": "metric", "label": "Metric"},
                {"value": "us_customary", "label": "US customary"},
                {"value": "imperial", "label": "Imperial"},
                {"value": "in_world", "label": "In-world"},
            ],
        },
        "target_word_count": {"name": "Target word count", "type": "number"},
        "series_number": {"name": "Series number", "type": "number"},
    },
}
