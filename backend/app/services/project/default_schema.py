"""Built-in default metadata schema (#14 backend split).

The minimal schema the app ships before any project/layer
`metadata.schema.yaml` is merged on top (see CLAUDE.md "Layered metadata
schema"). Lives in its own module so the schema slice (project/schema.py)
can import it without an import cycle back into project_service.
"""

from __future__ import annotations

from typing import Any

DEFAULT_METADATA_SCHEMA: dict[str, Any] = {
    "version": 1,
    "entry_types": {
        "manuscript_structure": {
            "name": "Manuscript",
            "kind": "scene",
            "abstract": True,
            "fields": ["number", "summary", "color"],
            "display_template": "{number}. {title}",
            "has_body": False,
        },
        "act": {
            "name": "Act",
            "kind": "scene",
            "parent": "manuscript_structure",
            "fields": [],
        },
        "chapter": {
            "name": "Chapter",
            "kind": "scene",
            "parent": "manuscript_structure",
            "fields": [],
        },
        "scene": {
            "name": "Scene",
            "kind": "scene",
            "parent": "manuscript_structure",
            "fields": ["status", "pov", "characters", "locations", "dynamics", "word_count", "cost"],
            "has_body": True,
            "color": "forest",
        },
        "lore_entry": {
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
        },
        "character": {
            "name": "Character",
            "kind": "lore",
            "parent": "lore_entry",
            "fields": ["character_cost"],
        },
        "place": {
            # Display label is "Location" (matches the `locations` field on
            # scene and the user's mental model); the entry-type id stays
            # "place" so existing project YAML and metadata refs keep
            # resolving — id is a backend identifier, display is UX.
            "name": "Location",
            "kind": "lore",
            "parent": "lore_entry",
            "fields": [],
        },
        "item": {
            "name": "Item",
            "kind": "lore",
            "parent": "lore_entry",
            "fields": [],
        },
        "lore_note": {
            "name": "Note",
            "kind": "lore",
            "parent": "lore_entry",
            "fields": [],
            # Deprecated by the research kind (docs/research-strategy.md
            # slice 5). Kept readable for legacy projects; UI filters this
            # flag so new entries can't be created as `lore_note`.
            "deprecated": True,
        },
        "research": {
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
        "topic": {
            "name": "Topic",
            "kind": "research",
            "parent": "research",
            "fields": [],
            "has_body": False,
        },
        "note": {
            # Research note — prose body + tags. Aliases / related_entries
            # / context_policy are intentionally left off v1 (per the
            # research-strategy decisions); notes participate in AI
            # context via the explicit picker for now.
            "name": "Note",
            "kind": "research",
            "parent": "research",
            "fields": ["tags"],
            "has_body": True,
        },
        "transformation": {
            # Reusable transformation set (#62): a body-less bundle of
            # (field, op, value) rows + a target lore entry-type. Concrete (not
            # abstract) so sets can be created directly; entry_type sub-classing
            # (e.g. shapeshift vs promotion families) stays available but unused.
            "name": "Transformation",
            "kind": "transformation",
            "fields": [],
            "has_body": False,
        },
        "prompt": {
            "name": "Prompt",
            "kind": "prompt",
            "abstract": True,
            "fields": ["preferred_assistant_id", "color"],
            "has_body": True,
            "body_editor": "code",
            "body_language": "jinja2",
            "color": "warm-brown",
        },
        "continuation": {
            "name": "Continuation",
            "kind": "prompt",
            "parent": "prompt",
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
        "roleplay": {
            # Continuation sub-type for two-character roleplay in one scene.
            # `default_body` provides a working starter template and
            # `default_inputs` seeds the `character: context_pick` input
            # the template assumes — together a fresh Roleplay prompt
            # comes ready to invoke via `/roleplay <Name>`. The context
            # strategy is inherited from `continuation`.
            "name": "Roleplay",
            "kind": "prompt",
            "parent": "continuation",
            "fields": [],
            "has_body": True,
            "default_inputs": [
                {
                    "name": "character",
                    "type": "context_pick",
                    "label": "Character",
                    "required": True,
                    "target": {
                        "kinds": ["lore"],
                        "entry_types": {"lore": ["character"]},
                        "multiple": False,
                        "presets": [],
                    },
                },
            ],
            "default_body": (
                "{% set char = entry(input.character) %}\n"
                "{% role \"system\" %}\n"
                "You roleplay one character within an ongoing scene. Stay in "
                "voice, in motive, in the moment. Write that character's NEXT "
                "beat — action, dialogue, or both — and stop. One beat, not a "
                "paragraph of them.\n"
                "{% if char %}\n"
                "\nYou are playing **{{ char.title }}**.\n"
                "{% if char.body %}\n"
                "\n## Character\n"
                "{{ char.body }}\n"
                "{% endif %}\n"
                "{% endif %}\n"
                "{% endrole %}\n"
                "\n"
                "{% role \"user\" %}\n"
                "{% if scene.metadata.dynamics %}\n"
                "## Scene dynamics\n"
                "{{ scene.metadata.dynamics }}\n"
                "\n"
                "{% endif %}\n"
                "{{ relevant_lore(scene) }}\n"
                "{% cache_break %}\n"
                "{% if scenes_before(scene) %}\n"
                "## The story so far\n"
                "{{ scenes_before(scene) }}\n"
                "\n"
                "{% endif %}\n"
                "{% endrole %}\n"
                "\n"
                "{# Per-character thread reconstruction. Spans tagged with the\n"
                "   focus character become assistant turns; spans tagged with\n"
                "   anyone else become user turns prefixed `[Name]:`; untagged\n"
                "   narration is plain user text. First invocation (no markers\n"
                "   yet) sends the whole scene body as one user-narration\n"
                "   message. Must be used OUTSIDE any role block. #}\n"
                "{{ character_thread(scene, input.character) }}\n"
            ),
        },
        "revise": {
            "name": "Revise",
            "kind": "prompt",
            "parent": "prompt",
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
        "general": {
            "name": "General",
            "kind": "prompt",
            "parent": "prompt",
            "fields": [],
            "has_body": True,
            "prompt": {
                "context_strategy": {
                    "output": {"kind": "chat_panel"},
                },
            },
        },
        "snippet": {
            "name": "Snippet",
            "kind": "prompt",
            "parent": "prompt",
            "fields": [],
            "has_body": True,
        },
        "assistant": {
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
                "is_default",
                "color",
            ],
            "has_body": False,
            "color": "graphite",
        },
        "project": {
            "name": "Project",
            "kind": "project",
            "fields": [
                "author",
                "language",
                "genre",
                "narrative_pov",
                "target_word_count",
                "series_number",
                "color",
                "project_cost",
            ],
            "has_body": True,
            "color": "violet",
        },
        "chat_session": {
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
    },
    "fields": {
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
            "picker_config": {"kinds": ["lore"], "entry_types": {"lore": ["character"]}},
        },
        "pov": {
            "name": "POV",
            "type": "entity_ref",
            "picker_config": {"kinds": ["lore"], "entry_types": {"lore": ["character"]}},
        },
        "locations": {
            "name": "Locations",
            "type": "entity_ref_list",
            "picker_config": {"kinds": ["lore"], "entry_types": {"lore": ["place"]}},
        },
        "home_place": {
            "name": "Home Place",
            "type": "entity_ref",
            "picker_config": {"kinds": ["lore"], "entry_types": {"lore": ["place"]}},
        },
        "related_entries": {
            "name": "Related Entries",
            "type": "entity_ref_list",
            "picker_config": {"kinds": ["lore"]},
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
        "is_default": {"name": "Default", "type": "boolean"},
        "preferred_assistant_id": {
            "name": "Preferred assistant",
            "type": "entity_ref",
            "picker_config": {"kinds": ["assistant"]},
        },
        "author": {"name": "Author", "type": "text"},
        "language": {"name": "Language", "type": "text"},
        "genre": {"name": "Genre", "type": "text"},
        "narrative_pov": {"name": "Narrative POV", "type": "text"},
        "target_word_count": {"name": "Target word count", "type": "number"},
        "series_number": {"name": "Series number", "type": "number"},
    },
}
