"""The kind-agnostic Library-tenant surface (ADR-0049, generalized in ADR-0048 S4b).

The built-in Library (ADR-0049) resolves app-owned nodes as a read-only ancestor
layer. Prompts were its first tenant; plot templates are the second. The two
tenants share one truth — *does the open project own this winner, or is it
inherited?* — expressed once here so consumers cannot drift to opposite polarity:
`fork_*` clones only what is NOT owned; the read-only reject refuses to write what
is NOT owned; the `editable` read-model flag is True only when it IS owned.

Composed onto `ProjectService`; the per-kind mixins (`PromptEntriesMixin`,
`PlotMixin`) call these through the MRO. `_metadata_schema_layer_id` lives on the
core class and resolves at call time.

Book-scoped kinds that merely *defer* fork/override (plotlines) reuse the
`_node_is_owned_here` predicate but keep their own reject message — "not supported
yet" is a different contract from "read-only Library node". lore.py / overrides.py
still compute the same owned/inherited split for their own fork-to-here semantics;
folding those on is a deliberate future step (they shadow the id in place rather
than clone), out of scope here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.project.errors import ProjectServiceError

if TYPE_CHECKING:
    from pathlib import Path

    from app.services.project.node_index import NodeIndexEntry


class LibraryTenantMixin:
    def _node_is_owned_here(self, winner: NodeIndexEntry, root: Path) -> bool:
        """Whether the open project OWNS this node winner, vs inheriting it from
        the built-in Library or an ancestor project.

        The single predicate for the owned/inherited split across Library tenants.
        Fail-closed by construction: an inherited winner is not owned, so it is
        read-only and its `editable` flag is False.
        """
        return winner.source_layer_id == self._metadata_schema_layer_id(root)

    def _reject_inherited_library_write(self, entry_id: str, *, kind: str, noun: str) -> None:
        """Refuse a write to a Library / ancestor node this project does not own.

        The structural "never a write target" guarantee at the actual boundary
        (ADR-0049 §3): the save/delete is refused here, not merely hidden in the
        UI, so overwriting or deleting a shipped app node is unconstructable
        rather than validated. A no-op when there is no index winner (a just-
        created, not-yet-indexed node is owned) or the winner is a different kind.
        The only path to a change is to clone the node into this project.
        """
        root = self._require_project()
        winner = self._build_node_index().by_id.get(entry_id)
        if winner is None or winner.kind != kind:
            return
        if not self._node_is_owned_here(winner, root):
            label = winner.source_layer_label or "an ancestor"
            raise ProjectServiceError(f"This {noun} is inherited from {label} and is read-only here.", 409)
