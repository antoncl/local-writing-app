"""The one layer walk (#329 / ADR-0039 Amendment 2).

Every consumer that needs "the folders this project inherits from, outermost
first" visits **this** traversal. Before #329 there were six derivations of the
same chain — the walk, the thing deciding where it stops, the schema-path map,
the node-index build (constructing `IndexLayer` inline with rank implied by
`enumerate`), the assistant roster (layer folder from an entry's path, rank from
index insertion order) and the machine layer special-cased at two more sites.
A change to *how far* the walk goes was therefore six edits, and they drifted:
`assistants.py` inferred rank from dict insertion order, so an incremental index
patch (#307) would silently reorder the roster.

The walk yields `IndexLayer` objects stamped with everything a consumer used to
re-derive: `folder`, `id`, `label`, an **explicit `rank`**, and the `is_root` /
`is_machine` flags. Per-layer logic lives in the visitor, not in a private copy
of the traversal.

**Behaviour is preserved exactly**, including the base-folder widening in
`_metadata_schema_base_folder` (see its docstring). #329 is a refactor: the
scattered walks collapse into one, and what each did per layer becomes a
visitor. ADR-0039 Amendment 2 also stipulates the root rather than inferring it
from a stray `metadata.schema.yaml` — that is a **behaviour** change and lands
separately (#337), which is now a one-line edit in one place because of this.

Ordering contract, relied on by consumers:

* The machine layer, when present, comes **first** (rank 0) — i.e. it is the
  outermost layer, the one every project inherits from.
* Project layers follow, **outermost ancestor → open project**, so a descendant
  entry overwrites an ancestor's on an id collision.
* `rank` is dense over the yielded sequence and only ever compared, never used
  as an index into anything.

⚠ The walk order above is unchanged since #329, but what *depends* on it moved.
Until #332 the assistant roster used `rank` as its leading sort term, so
machine-first meant the Machine bucket sat on top of the roster (ADR-0037 §7 /
#224). #332 merges every layer's `.order.yaml` into one sequence instead, folding
outermost → innermost — so the same machine-first walk now puts the machine layer
at the **bottom** of the roster, which is what most-local-wins requires. No
consumer should read "first in the walk" as "first in a user-facing list" again.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.services.project.node_index import IndexLayer

# The metadata-schema file each project layer may carry. Not applicable to the
# machine layer, which is out-of-tree and contributes assistants only.
SCHEMA_FILENAME = "metadata.schema.yaml"
# The per-layer manifest. Its `settings.projects_base_folder` is what the walk
# consults to decide where it stops, so it is an input to the *shape* of the
# chain and not only to a layer's content.
MANIFEST_FILENAME = "project.yaml"
# The manifest key holding the declaration: which enumerated ancestors this
# project inherits from (#309 / ADR-0039 Amendment 1). Absent means none.
INHERITS_KEY = "inherits"


@lru_cache(maxsize=1024)
def _layer_id_for_folder(folder: Path) -> str:
    """A layer's stable id: sha256 of its resolved path, first 16 hex chars.

    Memoised because `Path.resolve()` is a filesystem syscall (~0.16 ms on
    Windows) and this is called once per layer per walk, on paths that barely
    change within a session. Caching here rather than letting hot callers skip
    the walk keeps the optimisation *inside* the abstraction, so every consumer
    gets it. Keyed on the argument, so a rename produces a new key rather than
    a stale hit.

    ⚠ **The cache is safe only because layer ids are never persisted.** They are
    derived, compared against ids from this same function within one process,
    and reversed to a folder via the *walk* (`layer_by_id`), never via the id
    itself — so even a stale entry stays self-consistent. Nothing writes a layer
    id to disk today (`.order.yaml` holds entry ids). **#334 is where that could
    change** — it owns layer-qualified identity and explicit rank, the shape
    #306's snapshot serializes. If a layer id ever lands on disk, revisit this:
    a path-hash id survives neither a moved project folder nor a re-resolved
    symlink, cache or no cache.
    """
    return hashlib.sha256(str(folder.resolve()).encode("utf-8")).hexdigest()[:16]


class LayerVisitor(Protocol):
    """Visits each layer in walk order. Implementations carry whatever per-layer
    logic used to live inside a bespoke traversal.

    **Every consumer of the chain is a visitor** — including the ones whose body
    would reduce to a one-line comprehension. Uniformity is the point: the walk's
    definition changes mid-development (#309 declares inheritance, #318's wizard
    authors it, #337 stipulates the root), and a consumer that iterates the
    sequence itself is a second place to find when it does. The number of sites
    needing a walk only grows, so non-uniformity compounds while the few
    microseconds saved never do.
    """

    def visit_layer(self, layer: IndexLayer) -> None: ...


# Concrete visitors subclass the Protocol explicitly. It buys no static check —
# there is no mypy in the gates, and `from __future__ import annotations` makes
# the annotation a string that is never evaluated — but it makes every visitor
# greppable from one name, which is the point of insisting they all be visitors.


class LayerCollector(LayerVisitor):
    """The visitor that accumulates the sequence, in order.

    A consumer with no real per-layer logic does not need a bespoke visitor and
    does not need to iterate the walk itself: it visits with this and iterates
    the result. That is still one traversal, still visitor-mediated, and reads
    like the comprehension it replaces. The extra pass is a constant factor over
    a sequence bounded by chain depth — O(2N) is O(N), and the per-layer work is
    memoised anyway.

    So there are two legitimate shapes, and neither is a compromise:
    bespoke visitor when there is per-layer work (`_NodeIndexBuilder`),
    `collect_layers` + a comprehension when there is not.
    """

    def __init__(self) -> None:
        self.layers: list[IndexLayer] = []

    def visit_layer(self, layer: IndexLayer) -> None:
        self.layers.append(layer)


class LayerWalkMixin:
    def visit_layers(
        self,
        visitor: LayerVisitor,
        root: Path,
        *,
        include_machine: bool = False,
    ) -> None:
        """Drive `visitor` over the layer chain, outermost first, root last.

        **The** entry point. `include_machine` prepends the machine config dir
        as an ordinary out-of-tree layer (`is_machine=True`) when it actually
        holds an `assistants/` folder — the condition the old
        `_collect_machine_layer_assistants` early-returned on. Schema layering
        must not see it, so it is opt-in rather than default.
        """
        for layer in self._layer_sequence(root, include_machine=include_machine):
            visitor.visit_layer(layer)

    def _layer_sequence(self, root: Path, *, include_machine: bool) -> list[IndexLayer]:
        """Build the chain. Private: consumers visit, they do not iterate.

        `root` is canonicalised **once, here**, because everything below
        compares against it. `_project_layer_folders` yields resolved folders
        (see its docstring on #356), so `folder == root` against an unresolved
        argument is false for *every* layer — no layer is marked `is_root`, and
        `_families_for_layer` then drops scenes and chats from the index
        silently. Same normal-form defect as #356, one comparison further on.
        """
        root = root.resolve()
        layers: list[IndexLayer] = []
        if include_machine:
            machine_layer = self.machine_layer(rank=len(layers))
            if machine_layer is not None:
                layers.append(machine_layer)
        # `chain_index` is the position within the *project* chain, which is what
        # the label rule keys on ("Base Folder" is the outermost project layer).
        # It is deliberately not the same number as `rank`, which spans the whole
        # yielded sequence including the machine layer.
        for chain_index, folder in enumerate(self._project_layer_folders(root)):
            layers.append(
                IndexLayer(
                    folder=folder,
                    id=self._metadata_schema_layer_id(folder),
                    label=self._layer_label_for_folder(root, folder, chain_index),
                    rank=len(layers),
                    is_root=folder == root,
                )
            )
        return layers

    def collect_layers(self, root: Path, *, include_machine: bool = False) -> list[IndexLayer]:
        """The whole sequence, via `LayerCollector`. For callers that really do
        want every layer at once."""
        collector = LayerCollector()
        self.visit_layers(collector, root, include_machine=include_machine)
        return collector.layers

    def layer_by_id(self, root: Path, layer_id: str, *, include_machine: bool = False) -> IndexLayer | None:
        """Reverse a `source_layer_id` back to its layer, or None when unknown."""
        return next(
            (
                layer
                for layer in self.collect_layers(root, include_machine=include_machine)
                if layer.id == layer_id
            ),
            None,
        )

    def machine_layer(self, *, rank: int = 0) -> IndexLayer | None:
        """The machine layer as an `IndexLayer`, or None when it has no
        `assistants/` folder.

        One constructor, so the walk and the two callers that need the machine
        layer *without* a project chain (the index's no-project path and the
        roster's) cannot drift apart on its id, label or flags — which is the
        exact duplication #329 exists to remove.
        """
        folder = self._machine_layer_folder()
        if folder is None:
            return None
        return IndexLayer(
            folder=folder,
            id=self._metadata_schema_layer_id(folder),
            label="Machine",
            rank=rank,
            is_machine=True,
        )

    def _machine_layer_folder(self) -> Path | None:
        """The machine config dir, when it carries an `assistants/` folder.

        Imported lazily: `machine_settings` reaches back into service-level
        config and importing it at module scope closes an import cycle.
        """
        from app.services import machine_settings as ms_service

        machine_dir = ms_service.assistants_dir().parent
        if not (machine_dir / "assistants").exists():
            return None
        return machine_dir

    def ancestor_candidates(self, root: Path, *, base: Path | None = None) -> list[tuple[Path, bool, bool]]:
        """Every folder between the configured base and `root`, outermost first,
        as `(folder, is_project, inherited)` (#309).

        The candidate set is the **filesystem walk**, which is finite and
        cycle-free by construction — ADR-0039 Amendment 1 rejected a
        user-editable `parent:` link precisely because that can form a loop.
        The declaration only ever *selects* from this list; it can never extend
        it, so a project cannot name its way out of the configured base folder.

        Non-project folders are reported too, marked `is_project=False`. They
        can never be inherited (there is no `project.yaml` to layer), but
        omitting them from the enumeration would leave a hole in the wizard's
        list that reads as a defect rather than as information.

        `base` overrides the stored bound with one that is **about to be
        written**. A settings update that widens `projects_base_folder` and
        declares a newly-eligible ancestor in the same request would otherwise
        validate the declaration against the *old* bound and reject it — which
        is exactly the shape #318's wizard submits (pick a shelf, tick the
        levels, save once). It is a pending-value parameter, not an opt-out:
        omitting it reads the manifest, which is right for every other caller.
        """
        root = root.resolve()
        base_folder = base.resolve() if base is not None else self._metadata_schema_base_folder(root)
        chain = [root, *root.parents]
        if base_folder is None or base_folder not in chain:
            return []
        declared = self._declared_ancestors(root)
        ancestors = list(reversed(chain[: chain.index(base_folder) + 1]))[:-1]
        return [
            (folder, (folder / MANIFEST_FILENAME).exists(), folder in declared)
            for folder in ancestors
        ]

    def _declared_ancestors(self, root: Path) -> set[Path]:
        """The folders `root`'s manifest says it inherits from, resolved.

        **An absent key means "inherits nothing"** — not "inherits everything",
        which would be inference wearing a declaration's clothes: folder
        placement would still decide, and the key would only ever let you opt
        out. It also means an author who has declared nothing gets a flat
        project rather than a hierarchy they never asked for and cannot see.

        Paths are stored **relative to the project**, so moving or renaming a
        shelf does not invalidate every book beneath it. Entries that do not
        resolve to an actual ancestor are dropped by `_project_layer_folders`,
        which is where the warning belongs — this is a read, not a validator.
        """
        manifest = self._read_yaml(root / MANIFEST_FILENAME)
        declared = manifest.get(INHERITS_KEY)
        if not isinstance(declared, list):
            return set()
        resolved: set[Path] = set()
        for entry in declared:
            if not isinstance(entry, str) or not entry.strip():
                continue
            candidate = Path(entry.strip())
            if not candidate.is_absolute():
                candidate = root / candidate
            try:
                resolved.add(candidate.resolve())
            except OSError:
                continue
        return resolved

    def declared_ancestor_warnings(self, root: Path) -> list[str]:
        """One warning per declared entry that is not an ancestor (#309).

        Dropped rather than honoured: the enumeration is the filesystem walk,
        and an entry outside it is either a typo or a folder that has since
        moved. Honouring it would let the manifest extend the chain past the
        configured base — the property the walk exists to guarantee.

        **Two ways a declaration can fail, and both must be said out loud.**
        The first is an entry that is not an ancestor at all. The second is an
        ancestor that carries no `project.yaml`: it is a legitimate row in the
        enumeration, so the first check passes it, and it still contributes
        nothing — the author ticked something and got silence. A folder that
        was a project and stopped being one (a manifest deleted, a folder
        restored without it) lands here, which is precisely when a silent drop
        is least affordable.
        """
        root = root.resolve()
        candidates = {folder for folder, _, _ in self.ancestor_candidates(root)}
        projects = {folder for folder, is_project, _ in self.ancestor_candidates(root) if is_project}
        declared = self._declared_ancestors(root)
        return [
            f"Project declares inheritance from {folder}, which is not an ancestor "
            f"within the base folder. It was ignored."
            for folder in sorted(declared - candidates)
        ] + [
            f"Project declares inheritance from {folder}, which is not a project "
            f"(no {MANIFEST_FILENAME}). It contributes nothing."
            for folder in sorted((declared & candidates) - projects)
        ]

    def _project_layer_folders(self, root: Path) -> list[Path]:
        """Project folders from outermost ancestor to current root, inclusive.

        **The declared subset, plus the open project** (#309). The project is
        always in its own chain and is never subject to the declaration —
        "inherit from myself" is not a choice anyone should have to make.

        Gaps are legal by construction: the declaration is a set membership
        test per candidate, so declaring a grandparent without its parent is a
        recorded choice rather than an error. Nothing here reads an *ancestor's*
        declaration — each project's own list is the complete answer for itself,
        which is what keeps the chain a property of the file you are editing.

        One normal form, and finite by construction (#356). The previous version
        checked `_is_relative_to` — which resolves *both* operands — and then
        walked an **unresolved** `current` comparing it against a **resolved**
        `base_folder`. Where `.resolve()` changes the string (a junction or
        symlink above the project, a mapped or substituted drive, an 8.3 short
        path) the guard passed, the equality could never hold, and the walk ran
        to the drive root — where `Path("C:/").parent` is itself. It never
        terminated. A `break` on that fixpoint would only hide the real defect,
        which is comparing two normal forms in one traversal.
        """
        root = root.resolve()
        return [
            folder
            for folder, is_project, inherited in self.ancestor_candidates(root)
            if is_project and inherited
        ] + [root]

    def _metadata_schema_base_folder(self, root: Path) -> Path | None:
        """Where the walk stops — the outer bound of the layer chain.

        **The configured `projects_base_folder`, and nothing else** (#337 /
        ADR-0039 Amendment 2: the root is stipulated, never inferred from a
        file's presence).

        Until #337 this widened: when the configured value equalled
        `root.parent` — which the project chooser writes on *every* create, so
        it was the normal path, not an edge case — it was discarded in favour of
        the **outermost** ancestor anywhere up `root.parents` that happened to
        contain a `metadata.schema.yaml`. A stray schema file in a grandparent
        therefore set the extent of schema layering, the node index *and* the
        assistant roster, with no declaration and nothing on screen naming it.
        Under #312 it would have decided which ancestors contribute AI policy,
        which turns a surprise into a permission surprise.

        The widening was also, accidentally, the only thing giving a
        UI-created project a chain deeper than two layers. That is why this
        lands **with** the declaration (#309) and not before it: enumeration
        now stops where the user said it does, and inheritance is what the
        project declares within that bound.
        """
        manifest = self._read_yaml(root / MANIFEST_FILENAME)
        settings = manifest.get("settings")
        if not isinstance(settings, dict):
            return None
        base_folder = settings.get("projects_base_folder")
        if not isinstance(base_folder, str) or not base_folder.strip():
            return None
        return Path(base_folder).expanduser().resolve()

    def _metadata_schema_layer_id(self, folder: Path) -> str:
        return _layer_id_for_folder(folder)

    def _layer_label_for_folder(self, root: Path, folder: Path, layer_index: int) -> str:
        """A layer's name follows the *project*, not its position (#309).

        The old rule labelled position 0 "Base Folder", which was true while
        the walk always started at the configured base. Under a declared chain
        the outermost layer is normally a real project — and with gaps legal it
        may be a grandparent — so a positional rule mislabels it. This is
        user-visible in the schema-layers overview and in every shadow warning.

        A layer that carries a manifest gets that manifest's title; "Base
        Folder" survives only for a folder that genuinely is the configured
        base and is not itself a project.
        """
        if folder == root:
            return self._project_title(root) or root.name
        manifest = self._read_yaml(folder / MANIFEST_FILENAME)
        title = manifest.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        if layer_index == 0 and folder == self._metadata_schema_base_folder(root):
            return "Base Folder"
        return folder.name

    def _metadata_schema_layer_paths(self, root: Path) -> list[Path]:
        """Schema-file candidates, base → root — as a visitor like everything
        else, even though the body is one line.

        This called `_project_layer_folders` directly for a while, to dodge the
        `Path.resolve()` each layer id costs (`read_metadata_schema` is hot and
        discards the ids). That was premature optimisation buying microseconds
        at the price of a second place to change the walk. The cost is now paid
        once, memoised in `_layer_id_for_folder`.
        """
        return [layer.folder / SCHEMA_FILENAME for layer in self.collect_layers(root)]
