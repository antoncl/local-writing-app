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

#329 was a refactor: the scattered walks collapse into one, and what each did
per layer becomes a visitor. Two behaviour changes have landed in
`_metadata_schema_base_folder` since, each a one-line edit in one place because
of that collapse — #337 / ADR-0039 Amendment 2 stipulated the root rather than
inferring it from a stray `metadata.schema.yaml`, and **#429 moved the bound off
the project onto the machine**: one root per machine, so every project under it
necessarily agrees about where the chain stops. See that method's docstring.

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
# The per-layer manifest: a folder carrying one IS a project, and its `inherits`
# key is the declaration. It no longer says where the walk *stops* — that bound
# is the machine root since #429, one folder for every project, so a manifest is
# an input to a layer's content and to whether the folder counts as a layer at
# all, but not to the extent of the chain.
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

    def ancestor_candidates(self, root: Path) -> list[tuple[Path, bool]]:
        """Every folder between the machine root and `root`, outermost first,
        as `(folder, is_project)` (#309).

        The candidate set is the **filesystem walk**, which is finite and
        cycle-free by construction — ADR-0039 Amendment 1 rejected a
        user-editable `parent:` link precisely because that can form a loop.
        The declaration only ever *selects* from this list; it can never extend
        it, so a project cannot name its way outside the machine root.

        Non-project folders are reported too, marked `is_project=False`. They
        can never be inherited (there is no `project.yaml` to layer), but
        omitting them from the enumeration would leave a hole in the wizard's
        list that reads as a defect rather than as information.

        **This is the walk alone, and it parses nothing** (#460). It used to
        carry a third `inherited` flag, which three of its five consumers threw
        away — and that flag was the only reason the walk read a manifest, so
        it was also the only thing in the walk that could fail. On the create
        path (#425) that turned a `project.yaml` the scaffold was about to
        overwrite into a 422. The declaration is an overlay now:
        `declared_ancestor_candidates` puts it back for the two consumers that
        want it, and `ancestor_projects` answers the narrower question the rest
        were really asking.

        An optional `with_declaration=` flag was rejected. It must either
        change the tuple's arity — two methods wearing one name — or fill
        `inherited=False` when not requested, and `_project_layer_folders`
        filters on exactly that field: a caller passing the wrong flag would
        get a silently **flat chain** rather than an error, because "nobody
        asked" and "not declared" would be the same value.

        Took a pending `base` override until #429, so that a settings update
        widening `projects_base_folder` and declaring a newly-eligible ancestor
        could be validated as one request. With the bound on the machine tier
        there is no per-project value to be mid-write: widening happens once,
        in machine settings, and every project sees it at once.

        A project outside the machine root yields `[]` — the bound is absent
        from its parent chain, so there is nothing between them. That is the
        length-one chain a stray project gets.
        """
        root = root.resolve()
        base_folder = self._metadata_schema_base_folder(root)
        chain = [root, *root.parents]
        if base_folder is None or base_folder not in chain:
            return []
        ancestors = list(reversed(chain[: chain.index(base_folder) + 1]))[:-1]
        return [(folder, (folder / MANIFEST_FILENAME).exists()) for folder in ancestors]

    def declared_ancestor_candidates(self, root: Path) -> list[tuple[Path, bool, bool]]:
        """The walk with the declaration on it, as `(folder, is_project,
        inherited)` (#460).

        The one place the enumeration and `root`'s own `inherits:` are joined,
        and therefore the one place the walk reads a manifest. Two consumers
        need it: the layer chain (`_project_layer_folders`) and the wizard's
        row states (`_ancestor_candidates_for_api`). Everything else wants
        either the bare walk or `ancestor_projects`.
        """
        declared = self._declared_ancestors(root.resolve())
        return [
            (folder, is_project, folder in declared)
            for folder, is_project in self.ancestor_candidates(root)
        ]

    def ancestor_projects(self, root: Path) -> list[Path]:
        """The ancestor folders that are projects, outermost first (#460).

        The question four call sites were open-coding as a filter over the
        walk — validation, the create default, the warning report, and the
        layer chain. One name so that a change to what counts as a project
        (#441's enforcement, #430's malformed manifests) lands in one place
        rather than in whichever three of the four someone remembers.
        """
        return [folder for folder, is_project in self.ancestor_candidates(root) if is_project]

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
        candidates = {folder for folder, _ in self.ancestor_candidates(root)}
        projects = set(self.ancestor_projects(root))
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
            for folder, is_project, inherited in self.declared_ancestor_candidates(root)
            if is_project and inherited
        ] + [root]

    def _metadata_schema_base_folder(self, root: Path) -> Path | None:
        """Where the walk stops — the outer bound of the layer chain.

        **The machine root, and nothing else** (#429). One folder per machine,
        so every project under it necessarily agrees about where the chain
        stops. The root is stipulated, never inferred from a file's presence
        (#337 / ADR-0039 Amendment 2) — that part is unchanged; what moved is
        *who owns the value*.

        It used to be each project's own `settings.projects_base_folder`. Two
        things were wrong with that. It is machine information wearing a file's
        clothes: an absolute path duplicated into every manifest, surviving
        neither a move, nor another machine, nor a different drive letter. And
        because the create wizard built each project directly under the folder
        it passed as the bound, the stored value was always the project's own
        parent — so no two levels of one shelf agreed, and a chain enumerated
        exactly one hop from whichever end it was opened. `Universe › Series ›
        Book` was unreachable.

        `root` is still taken because the *caller's* question is "where does
        this project's walk stop", and a project outside the root has no walk
        at all: `ancestor_candidates` finds the bound absent from its parent
        chain and returns nothing, leaving a chain of length one. Keeping the
        parameter also means the signature does not change if the bound ever
        becomes per-something-else again.

        `None` when no root is configured — no bound, so a project's chain is
        itself alone.
        """
        from app.services import machine_settings as ms_service

        return ms_service.projects_root()

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
