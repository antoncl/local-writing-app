"""Built-in entry-type definitions for the default metadata schema.

Extracted from ``default_schema.py`` to keep that module under the
file-size cap. Pure data — ``DEFAULT_METADATA_SCHEMA`` composes this as
its ``entry_types``.
"""

from __future__ import annotations

from typing import Any

DEFAULT_ENTRY_TYPES: dict[str, Any] = {
    "manuscript:base": {
        "name": "Manuscript",
        "kind": "manuscript",
        "abstract": True,
        "fields": ["number", "summary", "color", "conversations", "references"],
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
        # Amendment 1 (ADR-0089, #2099): a scene reads brief→draft — the
        # long_text sections (Summary, Dynamics) come before the prose body,
        # the reverse of a lore entry. `body` is a conditional intrinsic
        # spliced right after `title` by default (see
        # `_build_entry_type_membership`), so without an explicit order it
        # would land ahead of Summary/Dynamics. `display_order` is additive
        # (named ids lead, in sequence; unnamed members trail in resolved
        # order), so the whole leading sequence is named explicitly here —
        # the identity triple, then the compact fields in their existing
        # order, then the two long_text sections, then body last. Any
        # unnamed member (none today) would trail after body.
        "display_order": [
            "title",
            "entry_type",
            "id",
            "number",
            "color",
            "status",
            "pov_mode",
            "pov",
            "tense",
            "characters",
            "location",
            "tags",
            "word_count",
            "cost",
            "summary",
            "dynamics",
            "body",
        ],
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
        "fields": [
            "aliases",
            "tags",
            "related_entries",
            "color",
            "context_policy",
            "conversations",
            "mutation_sets",
            "review_items",
            "references",
        ],
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
        "fields": ["conversations", "references"],
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
        "fields": ["conversations", "references"],
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
        "fields": [
            "preferred_assistant_id",
            "assistant_tags",
            "color",
            "disposition",
            "runnable",
            "conversations",
            "references",
        ],
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
            "ai_lore_budget_tokens",
            "ai_lore_expansion",
            "ai_history_budget_tokens",
            "ai_price_in_usd_per_mtok",
            "ai_price_out_usd_per_mtok",
            "summary",
            "assistant_tags",
            "color",
            "listed",
            "position",
            "conversations",
            "references",
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
            "conversations",
            "references",
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
        "fields": ["subject", "staged_set", "color", "conversations", "references"],
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
        "fields": ["color", "merged_into"],
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
}
