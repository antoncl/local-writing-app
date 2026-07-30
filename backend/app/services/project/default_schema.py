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
        "plot:template": {
            # A diagnostic story-structure lens (ADR-0048 S4b), shipped read-only
            # by the built-in Library (ADR-0049) or cloned into a project to adapt.
            # Its beat roster + guidance live in a `template:` front-matter block
            # (an opaque payload, like the board's `layout`), the prose guide is
            # the body — so it carries no schema metadata fields. Declared here so
            # its entry_type resolves.
            "name": "Plot template",
            "kind": "plot",
            "parent": "plot:base",
            "fields": [],
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
                "project_cost",
            ],
            "has_body": True,
            "color": "violet",
        },
        "chat:chat_session": {
            # Chat-as-node base type (Phase 3 of the NodeEditor
            # modularization). Concrete (not abstract) because chats are
            # instantiated directly via the chats pane — Phase 3a only
            # registers the type here; ChatSession storage at
            # <project>/chats/<id>.yaml stays the source of truth until
            # Phase 3b migrates it onto the Node CRUD path. The fields
            # users edit on a chat (prompt binding, assistant, system
            # brief, message history, journal) live on the ChatSession
            # Python model, not the metadata schema — none are declared
            # here. body_shape="chat" wires the future ChatBodyView once
            # Phase 4 ships.
            "name": "Chat",
            "kind": "chat",
            "fields": ["color"],
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
