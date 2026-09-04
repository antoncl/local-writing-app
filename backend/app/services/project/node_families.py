"""Node-family constants (#1806, split out of `references.py`).

Which node kinds the index walks, where their files live, and which layer
contributes which family (`NODE_FAMILIES`, `MACHINE_LAYER_FAMILIES`,
`LIBRARY_LAYER_FAMILIES`, `REFERENCE_BEARING_KINDS`), plus the free-function
form of the per-layer lookup, `families_for_layer`. Pure — no `self`, so
`layers.py`'s `_machine_layer_folder` can import `MACHINE_LAYER_FAMILIES` at
module scope with no import cycle back into `references.py` /
`project_service.py` (it used to import lazily, at call time, for exactly that
reason).

`references.py` re-exports the four constants at module scope, so every
existing import path — `app.services.project.references.NODE_FAMILIES` etc.,
`migrations.py`'s lazy import, `metadata_values.py`'s module-scope import,
`test_plot.py`'s direct import — keeps resolving unchanged. `IndexCollectMixin`
(`index_collect.py`) keeps a one-line `_families_for_layer` method delegating
to `families_for_layer` below, so `layers.py` and `node_index_patch.py`'s
`self._families_for_layer(...)` call sites are untouched.
"""

from __future__ import annotations

from app.services.project.node_index import IndexLayer, NodeFamily

# The Node-shaped kinds the index walks, once per layer of the chain.
NODE_FAMILIES = [
    NodeFamily("manuscript", "scenes", "manuscript:scene"),
    # Research notes walk `research/notes/`. Treated like lore (cross-layer)
    # rather than scenes (book-scoped) — universe- or series-level research
    # notes are a natural use case.
    NodeFamily("research", "research/notes", "research:note"),
    NodeFamily("lore", "lore", "lore:note"),
    NodeFamily("prompt", "prompts", "prompt:base"),
    NodeFamily("assistant", "assistants", "assistant:assistant"),
    # Reusable mutation sets (#62): body-less Node files under `mutation-sets/`.
    # Layered like lore/prompts (a werewolf transform can live at any project
    # level).
    NodeFamily("mutation_set", "mutation-sets", "mutation_set:mutation_set"),
    # Saved views (0.5.0, #35/#78): body-less Node files under `views/`, each
    # carrying a ViewSpec in front matter. Layered like mutation sets — a view
    # can live at any project level.
    NodeFamily("view", "views", "view:view"),
    # Plot planning (ADR-0048): plotlines (and, from S4b, templates + their
    # instances) as flat Node files under `plot/`. Layered — NOT book-scoped
    # like scenes — because S4b ships the diagnostic templates through the
    # ADR-0049 Library, an ancestor layer; book-scoping would exclude them.
    # The plot *board* is a separate per-project singleton (`plot-board.md`),
    # deliberately NOT in this family so an ancestor's board never leaks into
    # the resolved set (one board per open book, ADR-0048 §3).
    NodeFamily("plot", "plot", "plot:plotline"),
    # Chats (ADR-0051 S1): body-less Node files under `chats/`, each carrying
    # the ChatSession payload (messages/journal/inputs/…) in front matter. Root-
    # scoped like scenes (see `_families_for_layer`) — a chat belongs to the open
    # project, an ancestor's chats never resolve into it. Reference-bearing from
    # here on (the `subject` entity_ref arrives in S2); today the type declares
    # only `color`, so it contributes no edges.
    NodeFamily("chat", "chats", "chat:chat_session"),
    # Tags (ADR-0082 slice 1): body-less Node files under `tags/`, front matter
    # only. Layered like lore/prompts — a vocabulary (and its entries) can live
    # at any project level, and the machine layer contributes its own tag
    # entries too (see MACHINE_LAYER_FAMILIES below).
    NodeFamily("tag", "tags", "tag:tag"),
]

# The families the out-of-tree machine layer contributes: assistants, and now
# tags (the assistant-tag vocabulary, ADR-0082). Looked up rather than
# re-spelled as a literal — a second copy of the triple would drift.
MACHINE_LAYER_FAMILIES = [
    family for family in NODE_FAMILIES if family.kind in ("assistant", "tag")
]

# The families the built-in Library ships (ADR-0049). Prompts were the first
# tenant; plot templates are the second (ADR-0048 S4b) — proof the model is
# kind-agnostic, exactly as the design intended: a later kind joins by adding its
# family here and a folder in `builtin_library/`, no new mechanism. Deliberately
# a subset, not "everything a project layer carries": the Library is not a
# project, and scoping it to what actually ships keeps the walk from globbing
# folders that will never exist (the vertical-slice discipline in §4). The
# Library's `plot/` folder ships only `plot:template` nodes, so no plotline or
# board resolves from this layer.
LIBRARY_LAYER_FAMILIES = [family for family in NODE_FAMILIES if family.kind in ("prompt", "plot")]

# Every kind whose files the index extracts reference edges from: the node
# families above, plus the per-layer project node (#334), which lives at the
# layer root rather than in a kind folder and so is collected separately.
# Chats joined the families in ADR-0051 S1 — they are now ordinary Node files,
# so they are reference-bearing like every other kind (contributing no edges
# until the `subject` entity_ref lands in S2).
#
# Derived rather than re-spelled, because the two consumers that must agree
# with edge extraction are destructive-adjacent: `_purge_references_to` rewrites
# the user's files, and `_strip_dangling_references` hides values on read. A
# hand-maintained allow-list drifting from this set is exactly #345 — it said
# `{"scene", "lore"}` while the index had grown six more families, so every
# other kind kept its dangling references forever.
REFERENCE_BEARING_KINDS = frozenset({family.kind for family in NODE_FAMILIES} | {"project"})


def families_for_layer(layer: IndexLayer) -> list[NodeFamily]:
    """Which node families this layer contributes — the per-layer logic the
    index walk used to inline (#329).

    The machine layer is out-of-tree: assistants and tags
    (`MACHINE_LAYER_FAMILIES`, ADR-0082 slice 1). The Library is
    out-of-tree too and ships only its tenant kinds (prompts, ADR-0049).
    Scenes stay book-scoped, so they come from the open project alone.
    """
    if layer.is_machine:
        return MACHINE_LAYER_FAMILIES
    if layer.is_library:
        return LIBRARY_LAYER_FAMILIES
    return [family for family in NODE_FAMILIES if family.kind not in ("manuscript", "chat") or layer.is_root]
