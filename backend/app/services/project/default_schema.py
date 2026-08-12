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
)
COMPUTED_FUNCTIONS: tuple[str, ...] = AUTHORABLE_COMPUTED_FUNCTIONS + BUILTIN_COMPUTED_FUNCTIONS

DEFAULT_METADATA_SCHEMA: dict[str, Any] = {
    "version": 1,
    "entry_types": {
        "scene:base": {
            "name": "Manuscript",
            "kind": "scene",
            "abstract": True,
            "fields": ["number", "summary", "color"],
            "display_template": "{number}. {title}",
            "has_body": False,
        },
        "scene:act": {
            "name": "Act",
            "kind": "scene",
            "parent": "scene:base",
            "fields": [],
        },
        "scene:chapter": {
            "name": "Chapter",
            "kind": "scene",
            "parent": "scene:base",
            "fields": [],
        },
        "scene:scene": {
            "name": "Scene",
            "kind": "scene",
            "parent": "scene:base",
            "fields": ["status", "pov", "characters", "locations", "dynamics", "word_count", "cost"],
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
            "kind": "lore",
            "parent": "lore:base",
            "fields": ["character_cost"],
        },
        "lore:location": {
            # Local key aligned to its "Location" display (#85); the old key
            # was `place`, a documented key/display mismatch scar removed in
            # the pre-1.0 FQN cleanup. Matches the `locations` field on scene.
            "name": "Location",
            "kind": "lore",
            "parent": "lore:base",
            "fields": [],
        },
        "lore:item": {
            "name": "Item",
            "kind": "lore",
            "parent": "lore:base",
            "fields": [],
        },
        "lore:lore_note": {
            "name": "Note",
            "kind": "lore",
            "parent": "lore:base",
            "fields": [],
            # Deprecated by the research kind (docs/research-strategy.md
            # slice 5). Kept readable for legacy projects; UI filters this
            # flag so new entries can't be created as `lore:lore_note`.
            "deprecated": True,
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
            "kind": "research",
            "parent": "research:base",
            "fields": [],
            "has_body": False,
        },
        "research:note": {
            # Research note — prose body + tags. Aliases / related_entries
            # / context_policy are intentionally left off v1 (per the
            # research-strategy decisions); notes participate in AI
            # context via the explicit picker for now.
            "name": "Note",
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
            "kind": "mutation_set",
            "fields": [],
            "has_body": False,
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
        "plot:plotline": {
            # A story thread the writer creates at will (ADR-0048 §2). The
            # intrinsic title is its name; `color` tints its chips and card
            # tints on the board; the prose body is its description. Cards
            # reference one as their primary plotline (S5). An ordinary flat
            # Node under `plot/`, layered like lore.
            "name": "Plotline",
            "kind": "plot",
            "parent": "plot:base",
            "fields": ["color"],
            "has_body": True,
            "color": "plum",
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
            "kind": "plot",
            "parent": "plot:base",
            "fields": ["plotline", "scene", "page_status", "beat_links", "causal_links", "follow_ups"],
            "has_body": True,
        },
        "plot:template": {
            # A diagnostic story-structure lens (ADR-0048 S4b), shipped read-only
            # by the built-in Library (ADR-0049) or cloned into a project to adapt.
            # The beat roster is the `beats` ordered-list field (S7 Slice 1, #736) —
            # visible + editable via MetadataPanel like any field; the prose guide
            # is the body. Template-level attributes (family, ai_use_guidance, …)
            # still ride in the `template:` front-matter block for now.
            "name": "Plot template",
            "kind": "plot",
            "parent": "plot:base",
            "fields": ["beats"],
            "has_body": True,
        },
        "plot:template_instance": {
            # The book-local, specialized copy of a template's beat roster
            # (ADR-0048 §3, S7 Slice 2, #776). A template is generic ("the lovers
            # have an argument"); the instance is where the writer makes that
            # concrete to *this* book ("…about her hiding the debt"), and where an
            # ad-hoc plot with no template behind it lives. The plotline's / card's
            # third structural twin — a book-local flat Node under `plot/`, layered,
            # freely editable (never a read-only Library node like the template it
            # was cloned from). `instance_beats` holds the specialized roster; the
            # generic beat is snapshot-copied in at instantiate so the instance is
            # self-contained (an ad-hoc instance has no template to fall back to).
            # `source_template_id` / `source_template_name` are the lineage
            # snapshot — "which of the 14 arcs is this?" — captured at instantiate
            # and durable even after the beats diverge or the source template is
            # gone (a live ref would heal-to-blank, which for lineage is exactly
            # wrong); both hidden, both empty for an ad-hoc instance.
            "name": "Plot instance",
            "kind": "plot",
            "parent": "plot:base",
            "fields": ["instance_beats", "source_template_id", "source_template_name"],
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
            "kind": "plot",
            "parent": "plot:base",
            "fields": [],
            "has_body": False,
        },
        "prompt:base": {
            "name": "Prompt",
            "kind": "prompt",
            "abstract": True,
            "fields": ["preferred_assistant_id", "assistant_tags", "color"],
            "has_body": True,
            "body_editor": "code",
            "body_language": "jinja2",
            "color": "warm-brown",
        },
        "prompt:continuation": {
            "name": "Continuation",
            "kind": "prompt",
            "parent": "prompt:base",
            "fields": [],
            "has_body": True,
            "prompt": {
                "context_strategy": {
                    "target": {"required": True, "kind": "scene"},
                    "scan_surface": ["_text_before"],
                    "output": {"kind": "append_to_body", "review": "visual_diff"},
                },
            },
        },
        "prompt:roleplay": {
            # Continuation sub-type for two-character roleplay in one scene.
            # The shipped prompt body lives in the built-in Library
            # (`builtin-roleplay`), not a `default_body` here — the Library is
            # its home now that a real node stores it (ADR-0049 §7). Clone that
            # node to get an editable copy. `default_inputs` still declares the
            # `character: context_pick` input the template assumes. The context
            # strategy is inherited from `continuation`.
            "name": "Roleplay",
            "kind": "prompt",
            "parent": "prompt:continuation",
            "fields": [],
            "has_body": True,
            "default_inputs": [
                {
                    "name": "character",
                    "type": "context_pick",
                    "label": "Character",
                    "required": True,
                    "target": {
                        "sources": [{"kind": "lore", "expr": {"type": "lore:character"}}],
                        "multiple": False,
                        "presets": [],
                    },
                },
            ],
        },
        "prompt:revise": {
            # Abstract base for the two revise flavours. Split symmetrically
            # (ADR-0046 §5): sub-typing the lore case (`revise:entry`) while
            # leaving the scene case bare would leave the taxonomy lopsided, and
            # the TipTap editor filters its prompts by type — both flavours must
            # sit at the same depth. The concrete children carry the disposition;
            # the two `output.kind`s differ (replace_selection vs entry_patch),
            # so there is nothing shared to hoist onto the base.
            "name": "Revise",
            "kind": "prompt",
            "parent": "prompt:base",
            "abstract": True,
            "fields": [],
            "has_body": True,
        },
        "prompt:revise:scene": {
            # Today's in-editor scene revise, unchanged — an author selects prose
            # and the result replaces the selection behind the aiSuggestion mark.
            "name": "Revise scene",
            "kind": "prompt",
            "parent": "prompt:revise",
            "fields": [],
            "has_body": True,
            "prompt": {
                "context_strategy": {
                    "target": {"required": True, "kind": "scene"},
                    "scan_surface": ["_text_before", "_selection", "_text_after"],
                    "output": {"kind": "replace_selection", "review": "visual_diff"},
                },
            },
        },
        "prompt:revise:entry": {
            # The lore brainstorm (ADR-0046 §5/§6.3/§6.4), a pre-rolled prompt
            # like `roleplay`: an ideation *chat* that, on a commit turn, returns
            # a JSON `entry_patch`. It has TWO modes, chosen by how it was
            # launched, not by a separate prompt (ADR-0046 §6.4 — one vehicle):
            #   • REVISE — an existing entry rides in the `entry` input; the
            #     commit is the entry's revised body plus any changed proposable
            #     fields — long-text and structured alike (#653) — reviewed as a
            #     proposed-vs-current flip (slices 3a/3b).
            #   • CREATE — no `entry`; a target `entry_type` (hidden, launch-set)
            #     names the kind to draft from scratch; the commit is a whole new
            #     entry (title + fields + body), reviewed whole (no flip) and
            #     created via `POST /api/lore` + `PUT` (§6.4).
            # `output.kind = entry_patch` routes invocation to a chat and the
            # committed patch to review, not the scene aiSuggestion streaming
            # mark. The patch is validated server-side (`validate_ai_entry_patch`
            # / `validate_ai_entry_draft`) before review — the safety guarantee is
            # validate-on-return, not constrained decoding. The entry rides in as
            # an `entry` input loaded with `entry(input.entry)` — exactly how
            # roleplay pulls its character — because `{{ scene }}` resolves scenes
            # only (`read_scene`), never a lore entry. No `context_strategy.target`
            # for the same reason. `field_catalog(e)` (revise) / `field_catalog(
            # input.entry_type)` (create) lists the proposable fields so the
            # instruction names real field ids.
            "name": "Revise entry",
            "kind": "prompt",
            "parent": "prompt:revise",
            "fields": [],
            "has_body": True,
            "default_inputs": [
                {
                    # Optional (§6.4): present ⇒ revise it, absent ⇒ create mode.
                    "name": "entry",
                    "type": "context_pick",
                    "label": "Entry",
                    "required": False,
                    "target": {
                        "sources": [{"kind": "lore", "expr": {"type": "lore:base"}}],
                        "multiple": False,
                        "presets": [],
                    },
                },
                {
                    # The kind to draft in create mode — launch-set, not authored
                    # in the strip (`hidden`), so it reaches `input.entry_type`
                    # without cluttering the inputs strip.
                    "name": "entry_type",
                    "type": "text",
                    "label": "Entry type",
                    "required": False,
                    "hidden": True,
                },
            ],
            "prompt": {
                "context_strategy": {
                    "output": {"kind": "entry_patch", "review": "visual_diff"},
                },
            },
        },
        "prompt:revise:plot_card": {
            # The plot-card brainstorm (ADR-0048 S8b): an ideation chat that, on a
            # commit turn, returns a JSON `entry_patch` for the card — the SAME loop
            # as `revise:entry`, on a `plot:card` instead of a lore entry (the loop
            # is entry_type-keyed, not lore-shaped; ADR-0048 §5). It differs from
            # `revise:entry` in two ways: it is REVISE-ONLY (a card is created on the
            # board first, so there is no create-from-scratch mode — the `entry`
            # input is required), and its body drops in the spoiler-gated
            # `plot_context(as_of=e.id)` block so the model reasons over the whole
            # board (arcs' beat rosters + the other cards' synopses) while patching
            # this one card. `output.kind = entry_patch` routes it through the chat +
            # patch-review commit, validated server-side before review.
            "name": "Revise plot card",
            "kind": "prompt",
            "parent": "prompt:revise",
            "fields": [],
            "has_body": True,
            "default_inputs": [
                {
                    "name": "entry",
                    "type": "context_pick",
                    "label": "Card",
                    "required": True,
                    "target": {
                        "sources": [{"kind": "plot", "expr": {"type": "plot:card"}}],
                        "multiple": False,
                        "presets": [],
                    },
                },
            ],
            "prompt": {
                "context_strategy": {
                    "output": {"kind": "entry_patch", "review": "visual_diff"},
                },
            },
        },
        "prompt:general": {
            "name": "General",
            "kind": "prompt",
            "parent": "prompt:base",
            "fields": [],
            "has_body": True,
            "prompt": {
                "context_strategy": {
                    "output": {"kind": "chat_panel"},
                },
            },
        },
        "prompt:snippet": {
            "name": "Snippet",
            "kind": "prompt",
            "parent": "prompt:base",
            "fields": [],
            "has_body": True,
        },
        "assistant:assistant": {
            "name": "Assistant",
            "kind": "assistant",
            "fields": [
                "ai_provider",
                "ai_capability_tier",
                "ai_model",
                "ai_temperature",
                "ai_max_tokens",
                "ai_thinking",
                "summary",
                "tags",
                "color",
                "listed",
                "position",
            ],
            "has_body": False,
            "color": "graphite",
        },
        "project:project": {
            "name": "Project",
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
                "pov_mode",
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
            "kind": "chat",
            "fields": ["subject", "color"],
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
            "kind": "view",
            "fields": [],
            "has_body": False,
            # Routes the NodeEditor to the Svelte Flow view designer body
            # (0.5.0 step 3, #80) instead of the inert none-shape.
            "body_shape": "view",
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
            # A card->beat link (ADR-0048 S7 Slice 3b): the card names which beat of
            # which template instance it fulfils. Consumed nested as the `beat_links`
            # list field's item shape, so a card carries a LIST of these (multiple
            # beats per card). Both members are plain `text`, NOT `entity_ref`: v1
            # keeps refs out of item shapes (the top-level ref-healers walk only
            # top-level values), so `instance` holds the instance node id as text and
            # plot.py heals these by hand on card save + read — dropping a link whose
            # instance is gone or whose `beat_id` has left that instance's roster.
            "name": "Beat link",
            "members": [
                {"key": "instance", "name": "Instance", "type": "text"},
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
        "status": {
            "name": "Status",
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
        },
        "summary": {"name": "Summary", "type": "long_text"},
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
            # A template instance's specialized beat roster (ADR-0048 S7 Slice 2,
            # #776). The `beats` field's sibling, bound to `plot_instance_beat`
            # (which adds the per-beat `specifics` member); `plot:template_instance`
            # is its consumer. A separate field, not a reuse of `beats`, because a
            # field binds to exactly one item_group and the instance's beats carry
            # the extra member. Named distinctly from the template's `beats`
            # ("Plot beats") so the two are tellable apart in the field catalog.
            "name": "Specialized beats",
            "type": "list",
            "item_group": "plot_instance_beat",
        },
        "source_template_id": {
            # Lineage snapshot (ADR-0048 S7 Slice 2, #776): the stable id of the
            # template a `plot:template_instance` was instantiated from, captured at
            # instantiate. Empty for an ad-hoc instance. Hidden so it doesn't
            # clutter the panel; unhide per type to filter/group instances by their
            # source in a View. A plain text snapshot, not a live `entity_ref` — the
            # lineage must survive the source template being edited, renamed, or
            # deleted, which a healing ref would not.
            "name": "Source template id",
            "type": "text",
            "hidden": True,
        },
        "source_template_name": {
            # The display name of the source template, snapshotted at instantiate so
            # the instance can show "Mythic Quest Arc" without re-resolving a
            # (possibly inherited or since-deleted) template. Empty for an ad-hoc
            # instance. Hidden, like `source_template_id`.
            "name": "Source template",
            "type": "text",
            "hidden": True,
        },
        "dynamics": {
            # Scene-current per-character beats for the roleplay use case.
            # The roleplay template reads this verbatim; both characters
            # see all beats so the AI plays them as one continuous scene.
            "name": "Dynamics",
            "type": "long_text",
        },
        "aliases": {"name": "Aliases", "type": "multi_select"},
        "tags": {"name": "Tags", "type": "tags"},
        "context_policy": {
            # How the AI-context layers treat this entry. Values:
            #   - "always":      pulled into every implicit-mode render
            #   - "auto":        textual alias match (current default)
            #   - "manual_only": skipped by the matcher; explicit picker only
            #   - "never":       hidden from picker and matcher
            # Default "auto" preserves the pre-policy behavior — existing
            # entries that omit the field keep their current treatment.
            "name": "Context policy",
            "type": "select",
            "options": ["always", "auto", "manual_only", "never"],
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
            "type": "color",
        },
        "characters": {
            "name": "Characters",
            "type": "entity_ref_list",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:character"}}]},
        },
        "pov": {
            "name": "POV",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:character"}}]},
        },
        "locations": {
            "name": "Locations",
            "type": "entity_ref_list",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:location"}}]},
        },
        "home_place": {
            "name": "Home Place",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "lore", "expr": {"type": "lore:location"}}]},
        },
        "related_entries": {
            "name": "Related Entries",
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
            "picker_config": {"sources": [{"kind": "lore"}, {"kind": "scene"}]},
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
            "picker_config": {"sources": [{"kind": "scene", "expr": {"type": "scene:scene"}}]},
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
            # A card's beat links (ADR-0048 S7 Slice 3b): the beats this card fulfils,
            # each a `plot_beat_link` (a template-instance id + a beat id within that
            # instance's roster). An ordered `list` so one card can serve several beats.
            # Its consumer is `plot:card`. Integrity is plot-local: the item shape is
            # plain text (v1 bars refs from item shapes), so plot.py heals dangling
            # links on card save + read, not the top-level reference machinery.
            # Hidden by default, like the lineage id fields (`source_template_id` /
            # `source_template_name`): the members are raw ids meant for the board's
            # link editor (a later slice), not hand-entry in the generic panel.
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
            "type": "select",
            "options": ["anthropic", "openai", "openrouter", "ollama"],
        },
        "ai_capability_tier": {
            "name": "Capability tier",
            "type": "select",
            "options": ["", "fast", "balanced", "premium", "reasoning", "local"],
        },
        "ai_model": {"name": "Model", "type": "text"},
        "ai_temperature": {"name": "Temperature", "type": "number"},
        "ai_max_tokens": {"name": "Max output tokens", "type": "number"},
        "ai_thinking": {"name": "Show thinking", "type": "boolean"},
        "preferred_assistant_id": {
            "name": "Preferred assistant",
            "type": "entity_ref",
            "picker_config": {"sources": [{"kind": "assistant"}]},
        },
        # A prompt's soft assistant scope (ADR-0024): the picker surfaces
        # assistants carrying any of these tags first, and the dynamic default
        # is the topmost matching one. A degenerate `tagged:` source over
        # kind:assistant, expressed with the existing tags widget/infra.
        "assistant_tags": {"name": "Preferred assistant tags", "type": "tags"},
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
