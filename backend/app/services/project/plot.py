"""Plot-planning slice of ProjectService (ADR-0048 S4a).

Two node types under the new `plot` kind:

- **Plotlines** (`plot:plotline`, ADR-0048 §2) — flat Node markdown files under
  `<project>/plot/`, layered like lore. Ordinary CRUD; the write funnel
  (`_atomic_write` → `_maintain_index_after_write`) keeps the node-index memo
  coherent, so a created plotline is immediately resolvable by id and
  reference-bearing for free. S4a keeps editing **book-local**: an *inherited*
  plotline's write-routing (fork / override, the ADR-0039/0042 machinery lore
  carries) is deferred until a use case needs it — plot planning is per-book.

- **The board** (`plot:board`, ADR-0048 §3) — a per-project layout singleton at
  `<project>/plot-board.md`, addressed by path like the project node, **not** a
  member of the `plot/` family folder. Because `plot` is a layered kind, a
  folder-globbed board would let an ancestor's board leak into the resolved set;
  a directly-addressed per-project file makes "one board per open book"
  structural. It is presentation-only (an opaque `layout` payload the canvas in
  S7 populates) and created on first open.

Shared tooling resolves through the MRO (`_require_project`,
`_build_node_index`, `_read_markdown_with_front_matter`, `_read_front_matter_only`,
`_normalise_metadata`, `read_metadata_schema`, `_initial_metadata_from_defaults`,
`_validate_entry_metadata`, `_new_id`, `_filepath_for_new_node`,
`_path_for_node_id`, `_node_id_for_path`, `_front_matter_id`, `_revision`,
`_strip_unknown_metadata_fields`, `_strip_dangling_references`,
`_computed_entry_metadata`, `_maybe_rename_node_file`, `_delete_node_file`,
`_purge_references_to`, `_atomic_write`).
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from app.models import (
    CardEntry,
    CardList,
    CardSummary,
    CreateCardRequest,
    CreatePlotlineRequest,
    CreatePlotTemplateRequest,
    CreateSceneRequest,
    PlotBoard,
    PlotBoardBeat,
    PlotBoardCard,
    PlotBoardContainer,
    PlotBoardPlotline,
    PlotBoardPlotlineBeat,
    PlotBoardProjection,
    PlotlineEntry,
    PlotlineList,
    PlotlineSummary,
    PlotTemplate,
    PlotTemplateList,
    PlotTemplateSpec,
    PlotTemplateSummary,
    RealizeCardRequest,
    SaveCardRequest,
    SavePlotBoardRequest,
    SavePlotlineRequest,
    SavePlotTemplateRequest,
    StructureNode,
)
from app.services.markdown_validation import validate_scene_markdown
from app.services.project.errors import ProjectServiceError

PLOT_BOARD_FILENAME = "plot-board.md"
PLOT_TEMPLATE_ENTRY_TYPE = "plot:template"
# A plotline is a plot-template instance (ADR-0053 §1): one node kind carrying the
# beat roster + colour + lineage. The former `plot:template_instance` / "arc" kind
# is retired into this one.
PLOT_PLOTLINE_ENTRY_TYPE = "plot:plotline"
# The `plot_beat` members carried verbatim into a plotline's `plot_instance_beat`
# when a template is instantiated (ADR-0048 S7 Slice 2, #776). `specifics` is left
# for the writer, so it is not in this snapshot set.
_INSTANCE_BEAT_SNAPSHOT_KEYS = ("title", "function", "guidance", "required", "id")
# The metadata list-fields whose items are beats carrying a stable `id` member
# (ADR-0048 S7 Slice 3a, #779). Every write of one of these mints an id for any
# beat that lacks one and re-salts a within-list collision, so a card→beat link
# (Slice 3b) always has a stable, list-unique target to point at. `beats` is the
# template's roster; `instance_beats` is a plotline's (ADR-0053).
_BEAT_LIST_FIELDS = ("beats", "instance_beats")
PLOT_CARD_ENTRY_TYPE = "plot:card"
# Card-only metadata fields (ADR-0048 S7 Slice 3b). `beat_links` is the list of
# card→beat links — each a *(plotline node id, beat id)* text pair, healed
# plot-locally because v1 bars refs from list-item shapes. `page_status` is the
# on/off-page vs unwritten marker, with `on_page` derived from the scene link.
_BEAT_LINK_FIELD = "beat_links"
# The authored card→card causal edges (ADR-0048 S7 Slice 6b) — each a single
# `target` card node id as text, healed plot-locally (drop dangling / self /
# duplicate) for the same v1-bars-refs-from-item-shapes reason as `beat_links`.
_CAUSAL_LINK_FIELD = "causal_links"
_PAGE_STATUS_FIELD = "page_status"


class _PlotNodeRead(NamedTuple):
    """The healed pieces of a resolved `plot/` node, shared by every reader
    (plotline, card, template) so the read → heal → validate core lives once."""

    node_id: str
    entry_type: str
    title: str
    body: str
    metadata: dict[str, Any]
    revision: str
    schema: Any
    front_matter: dict[str, Any]
    index_entry: Any


class PlotMixin:
    # ----- Shared plot/ folder-node CRUD (plotlines, cards) ---------------
    #
    # Plotlines and cards are the same shape — book-local layered `plot/` Nodes
    # with schema-driven metadata + a prose body — so their list/create/read/
    # save/delete live here once, parametrized by (entry_type, model, noun), and
    # each public method is a thin typed wrapper. Templates are a Library tenant
    # with their own write contract (read-only-in-place, clone, a `template:`
    # block), so they share only the read core (`_read_plot_folder_node`), not
    # the writes. Every `plot/` node is addressed by a `plot_` id in one folder,
    # so the endpoint is the only discriminator between the families — the
    # `is_a` family guard below is what stops one endpoint from creating,
    # reading, retyping, or deleting another family's node.

    def _require_plot_family(
        self, entry_type: str, family_root: str, *, noun: str, node_id: str | None = None, schema: Any = None
    ) -> None:
        # The type must be `family_root` or a sub-type of it (via the `parent:`
        # chain), never a sibling family — a board, a template, or a plotline vs
        # a card. `node_id` set means we resolved an on-disk node of the wrong
        # family through this endpoint (404, as read_plot_template has always
        # done); unset means a bad requested `entry_type` on create/save (422).
        # This subsumes the old board-only reject: a board is not `is_a` a card.
        if family_root not in self.entry_type_ancestry(entry_type, schema=schema):
            if node_id is not None:
                raise ProjectServiceError(f"Node {node_id} is not a {noun}.", 404)
            raise ProjectServiceError(
                f"{entry_type} is not a {noun} type; it cannot be created or saved through the {noun} path.",
                422,
            )

    def _require_plot_family_winner(
        self, entry_id: str, winner, family_root: str, *, noun: str, schema: Any = None
    ) -> None:
        # The delete guard: refuse to unlink a resolved node of a different
        # family through this endpoint (a plotline id on the cards delete path
        # would otherwise destroy the plotline and return the card list).
        if winner is not None and winner.kind == "plot" and family_root not in self.entry_type_ancestry(
            winner.entry_type, schema=schema
        ):
            raise ProjectServiceError(f"Node {entry_id} is not a {noun}.", 404)

    def _plot_node_path(self, entry_id: str, winner, *, noun: str) -> Path:
        # The on-disk path for a plot/ node addressed by id: the resolved winner
        # when indexed, else the conventional-name file (a node written but not
        # yet indexed). A truly-absent node 404s with the right noun rather than
        # the shared resolver's fixed "Plotline" label (S5a review).
        if winner is not None and winner.kind == "plot":
            return winner.path
        path = self._require_project() / "plot" / f"{entry_id}.md"
        if not path.exists():
            raise ProjectServiceError(f"{noun.capitalize()} {entry_id} does not exist.", 404)
        return path

    def _list_plot_folder_nodes(self, *, entry_type: str, summary_cls):
        # Exact entry_type, not kind: the `plot` kind also carries the board and
        # the Library's templates, none of which belong in this list. A sub-type
        # would need is-a filtering, but S5a ships none.
        index = self._build_node_index()
        entries = []
        for entry in index.by_id.values():
            if entry.entry_type != entry_type:
                continue
            try:
                front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            metadata = self._normalise_metadata(front_matter.get("metadata"), entry.path)
            entries.append(
                summary_cls(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    body=body,
                    entry_type=entry_type,
                    metadata=metadata,
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda summary: (summary.title.lower(), summary.id))
        return entries

    def _create_plot_folder_node(
        self,
        *,
        title: str,
        requested_entry_type: str,
        default_entry_type: str,
        noun: str,
        seed_metadata: dict[str, Any] | None = None,
        node_id: str | None = None,
    ) -> str:
        root = self._require_project()
        entry_type = requested_entry_type or default_entry_type
        schema = self.read_metadata_schema()
        # The requested type must be in this family (rejects board/template/the
        # sibling family), subsuming the old board-only guard.
        self._require_plot_family(entry_type, default_entry_type, noun=noun, schema=schema)
        initial_metadata = self._initial_metadata_from_defaults(entry_type, schema)
        # `seed_metadata` lets a caller (instantiate) hand a new node its starting
        # field values — the snapshotted beat roster + lineage — over the defaults.
        # Normalised + validated exactly like a save's metadata, so a bad seed 422s
        # rather than reaching disk.
        if seed_metadata:
            initial_metadata = self._normalise_metadata({**initial_metadata, **seed_metadata}, root / "plot")
            initial_metadata = self._ensure_beat_identity(initial_metadata)
        metadata_errors = self._validate_entry_metadata(
            label=f"{noun.capitalize()} new",
            entry_type=entry_type,
            expected_kind="plot",
            metadata=initial_metadata,
            schema=schema,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        # A supplied id restores a node under its original identity (ADR-0053
        # §7 undo). Collision-rejected against the whole node index, so a
        # restore can never clobber a live node — only reoccupy the id its own
        # delete freed. Empty/None mints fresh, the normal create.
        if node_id:
            if node_id in self._build_node_index().by_id:
                raise ProjectServiceError(f"{noun.capitalize()} id {node_id} already exists.", 409)
            new_id = node_id
        else:
            new_id = self._new_id("plot")
        self._write_node_entry_file(
            self._filepath_for_new_node(root / "plot", title),
            new_id,
            title,
            entry_type,
            initial_metadata,
            "",
        )
        return new_id

    def _read_plot_folder_node(self, entry_id: str, *, expected_entry_type: str, noun: str) -> _PlotNodeRead:
        # The read → heal → validate core shared by read_plotline / read_card /
        # read_plot_template. Enforces the node is-a `expected_entry_type` (a
        # plotline id on the cards endpoint 404s rather than reading back as a
        # card), then runs the #345 read-side healing (drop retired fields +
        # dangling references) before validating.
        index = self._build_node_index()
        index_entry = index.by_id.get(entry_id)
        path = self._plot_node_path(entry_id, index_entry, noun=noun)
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or expected_entry_type
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(
                f"{noun.capitalize()} {node_id} has invalid entry_type; it must be text.", 422
            )
        schema = self.read_metadata_schema()
        self._require_plot_family(raw_entry_type, expected_entry_type, noun=noun, node_id=node_id, schema=schema)
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        metadata = self._strip_unknown_metadata_fields(metadata, raw_entry_type, schema)
        metadata = self._strip_dangling_references(metadata, schema, index)
        if raw_entry_type == PLOT_CARD_ENTRY_TYPE:
            metadata = self._normalise_card_metadata(metadata, index, node_id)
        metadata_errors = self._validate_entry_metadata(
            label=f"{noun.capitalize()} {node_id}",
            entry_type=raw_entry_type,
            expected_kind="plot",
            metadata=metadata,
            schema=schema,
            node_index=index,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        return _PlotNodeRead(
            node_id=node_id,
            entry_type=raw_entry_type,
            title=str(front_matter.get("title") or node_id),
            body=body,
            metadata=metadata,
            revision=self._revision(path),
            schema=schema,
            front_matter=front_matter,
            index_entry=index_entry,
        )

    def _build_plot_folder_entry(self, read: _PlotNodeRead, entry_cls):
        # The one Entry-construction mapping shared by every plain plot-folder
        # reader (plotline, card, template instance): identity + healed metadata +
        # computed fields + layer provenance. Only the model class differs, so the
        # three readers pass it in rather than repeating the 10-field mapping.
        # (Templates read differently — they add the `template:` spec + Library
        # provenance — so they build their model directly, not through here.)
        return entry_cls(
            id=read.node_id,
            title=read.title,
            body=read.body,
            revision=read.revision,
            entry_type=read.entry_type,
            metadata=read.metadata,
            computed_metadata=self._computed_entry_metadata(
                read.body, node_id=read.node_id, entry_type=read.entry_type, schema=read.schema
            ),
            source_layer_id=read.index_entry.source_layer_id if read.index_entry else "",
            source_layer_label=read.index_entry.source_layer_label if read.index_entry else "",
        )

    def _save_plot_folder_node(self, entry_id: str, request, *, expected_entry_type: str, noun: str) -> str:
        root = self._require_project()
        schema = self.read_metadata_schema()
        # The requested type must be in this family (never save a card as a template).
        self._require_plot_family(request.entry_type, expected_entry_type, noun=noun, schema=schema)
        index = self._build_node_index()
        winner = index.by_id.get(entry_id)
        # Book-local write: refuse to touch an inherited winner (its fork/override
        # routing is deferred) — writing winner.path would rewrite ancestor canon.
        self._reject_inherited_book_local(entry_id, winner, root, noun=noun)
        path = self._plot_node_path(entry_id, winner, noun=noun)
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        # The node on disk must actually be this family — never retype across
        # families (a plotline id on the cards endpoint would otherwise be
        # rewritten as a card, dropping its own fields).
        self._require_plot_family(
            front_matter.get("entry_type") or expected_entry_type,
            expected_entry_type,
            noun=noun,
            node_id=node_id,
            schema=schema,
        )
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError(f"{noun.capitalize()} changed on disk after it was opened.", 409)
        markdown_errors = validate_scene_markdown(request.body)
        if markdown_errors:
            raise ProjectServiceError(" ".join(markdown_errors), 422)
        metadata = self._normalise_metadata(request.metadata, path)
        metadata = self._ensure_beat_identity(metadata)
        # Gate on the concrete type being written (like the read path's
        # `raw_entry_type`), not the endpoint constant `expected_entry_type` — so
        # save and read agree in every case. plot:card is a leaf here (the module
        # lists cards by exact type), so both consistently skip any subtype.
        if request.entry_type == PLOT_CARD_ENTRY_TYPE:
            metadata = self._normalise_card_metadata(metadata, index, node_id)
        metadata_errors = self._validate_entry_metadata(
            label=f"{noun.capitalize()} {node_id}",
            entry_type=request.entry_type,
            expected_kind="plot",
            metadata=metadata,
            schema=schema,
            node_index=index,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        self._write_node_entry_file(path, node_id, request.title, request.entry_type, metadata, request.body)
        self._maybe_rename_node_file(path, request.title)
        return node_id

    def _ensure_beat_identity(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Give every beat a stable, list-unique `id` (ADR-0048 S7 Slice 3a, #779).

        A card→beat link (Slice 3b) is the composite *(instance node id, beat id)*,
        so a beat's id only needs to be unique **within its own list** — the node
        half already disambiguates the instance, and `instantiate` keeps copying a
        template beat's id into the instance (provenance). Each id is minted with a
        fresh per-beat salt (`_mint_beat_id`); the salt — not the title — is what
        makes it unique, so even two beats with identical titles diverge, and the id
        is opaque hex rather than a legible slug. It is minted once and then
        persisted: a beat that already carries a non-colliding id keeps it, so
        renaming a beat never changes its id and 3b's links survive the edit. A
        within-list collision (copy-pasting a beat carries its id along) is re-salted.

        Auto-fill only — nothing here rejects. A blank beat still saves and simply
        gains an id, matching the sparse-spec principle: an incomplete beat must
        never block a write.
        """
        for field in _BEAT_LIST_FIELDS:
            beats = metadata.get(field)
            if not isinstance(beats, list):
                continue
            seen: set[str] = set()
            for beat in beats:
                if not isinstance(beat, dict):
                    continue  # a non-dict item 422s in validation; leave it be
                beat_id = beat.get("id")
                if isinstance(beat_id, str) and beat_id and beat_id not in seen:
                    seen.add(beat_id)
                    continue
                beat["id"] = self._mint_beat_id(beat.get("title"), seen)
                seen.add(beat["id"])
        return metadata

    @staticmethod
    def _mint_beat_id(title: object, taken: set[str]) -> str:
        """`beat_<sha256(title+salt)[:12]>`, salt = `uuid4().hex`. The title is folded
        into the hash but the per-mint salt alone guarantees uniqueness; the result is
        opaque, not a legible slug. Re-salted until it lands outside `taken`, so a
        fresh mint never re-introduces a collision."""
        name = title if isinstance(title, str) else ""
        while True:
            salt = uuid.uuid4().hex
            candidate = "beat_" + hashlib.sha256(f"{name}{salt}".encode()).hexdigest()[:12]
            if candidate not in taken:
                return candidate

    def _normalise_card_metadata(
        self, metadata: dict[str, Any], index: Any, card_id: str
    ) -> dict[str, Any]:
        """Card-only metadata normalization (ADR-0048 S7 Slice 3b/6b).

        Runs on every card save AND read — the same two-path symmetry the `scene`
        ref already has (purge-on-delete + heal-on-read). Heals the card→beat links
        and the authored card→card causal links (drops any that no longer resolve),
        then derives `page_status` from the scene attachment. `plot:card` is the only
        plot node carrying these fields, so the save/read callers gate this to cards;
        `card_id` is the healing card's own node id, needed to drop a self-link.
        """
        self._heal_beat_links(metadata, index)
        self._heal_causal_links(metadata, index, card_id)
        self._derive_card_page_status(metadata)
        return metadata

    @staticmethod
    def _iter_valid_beat_link_pairs(links: Any) -> Iterator[tuple[str, str]]:
        """Yield each well-formed, unique *(plotline id, beat id)* pair from a stored
        `beat_links` value (ADR-0048 S7 3b/5b; ADR-0053), skipping non-dict items,
        incomplete pairs (a blank half points nowhere), and duplicate pairs (a card
        fulfils a beat once). The shared front half of `_heal_beat_links` (which then
        filters by live roster) and `_resolve_card_beats` (which resolves titles) — one
        place decides what a valid link *is*, so the two can't drift on it."""
        if not isinstance(links, list):
            return
        seen: set[tuple[str, str]] = set()
        for link in links:
            if not isinstance(link, dict):
                continue
            plotline_id = link.get("plotline")
            beat_id = link.get("beat_id")
            if not (isinstance(plotline_id, str) and plotline_id and isinstance(beat_id, str) and beat_id):
                continue
            key = (plotline_id, beat_id)
            if key in seen:
                continue
            seen.add(key)
            yield key

    def _heal_beat_links(self, metadata: dict[str, Any], index: Any) -> None:
        """Keep only card→beat links that still resolve (ADR-0048 S7 Slice 3b; ADR-0053).

        A `beat_links` item is a *(plotline node id, beat id)* pair stored as plain
        text — v1 keeps refs out of list-item shapes, so the top-level reference
        purge/heal never reaches these. This is that healing, plot-local: a link
        survives only if its `plotline` is a live `plot:plotline` **and** its `beat_id`
        is in that plotline's current roster. A link to a deleted plotline, or to a
        beat since removed from the roster, is dropped — the board can only draw links
        that mean something. Well-formedness + dedup are the shared
        `_iter_valid_beat_link_pairs`; this adds the roster filter and re-emits each
        surviving pair as a canonical `{plotline, beat_id}` dict. When nothing survives
        the key is removed, so an all-dangling list heals to sparse rather than `[]`.
        """
        links = metadata.get(_BEAT_LINK_FIELD)
        if not isinstance(links, list):
            return
        rosters: dict[str, set[str] | None] = {}
        healed: list[Any] = []
        for plotline_id, beat_id in self._iter_valid_beat_link_pairs(links):
            if plotline_id not in rosters:
                rosters[plotline_id] = self._plotline_beat_ids(plotline_id, index)
            roster = rosters[plotline_id]
            if roster is None or beat_id not in roster:
                continue  # plotline gone / not a plotline / beat left the roster
            healed.append({"plotline": plotline_id, "beat_id": beat_id})
        if healed:
            metadata[_BEAT_LINK_FIELD] = healed
        else:
            metadata.pop(_BEAT_LINK_FIELD, None)

    def _plotline_beat_ids(self, plotline_id: str, index: Any) -> set[str] | None:
        """The beat ids in a `plot:plotline`'s roster, or None when the id is not a live
        plotline. Reads just the front matter (the lightest node read); the plotline's
        own writes guarantee its beats are id-healed."""
        entry = index.by_id.get(plotline_id)
        if entry is None or entry.entry_type != PLOT_PLOTLINE_ENTRY_TYPE:
            return None
        front_matter = self._read_front_matter_only(entry.path, strict=True)
        metadata = self._normalise_metadata(front_matter.get("metadata"), entry.path)
        beats = metadata.get("instance_beats")
        if not isinstance(beats, list):
            return set()
        return {
            beat["id"]
            for beat in beats
            if isinstance(beat, dict) and isinstance(beat.get("id"), str) and beat["id"]
        }

    @staticmethod
    def _iter_valid_causal_targets(links: Any) -> Iterator[str]:
        """Yield each well-formed, unique `target` card id from a stored `causal_links`
        value (ADR-0048 S7 Slice 6b), skipping non-dict items, a blank target (points
        nowhere), and duplicate targets (a card leads to another once). The shared front
        half of `_heal_causal_links` (which then filters to live, non-self cards) and
        `_resolve_card_causal` (which surfaces the ids in the projection) — one place
        decides what a valid link *is*, so the two can't drift on it."""
        if not isinstance(links, list):
            return
        seen: set[str] = set()
        for link in links:
            if not isinstance(link, dict):
                continue
            target = link.get("target")
            if not (isinstance(target, str) and target):
                continue
            if target in seen:
                continue
            seen.add(target)
            yield target

    def _heal_causal_links(self, metadata: dict[str, Any], index: Any, card_id: str) -> None:
        """Keep only authored causal links that still resolve (ADR-0048 S7 Slice 6b).

        A `causal_links` item is a single `target` card node id stored as plain text —
        v1 keeps refs out of list-item shapes, so the top-level reference purge/heal
        never reaches these. This is that healing, plot-local: a link survives only if
        its `target` is a live `plot:card` **and** is not the healing card itself (a
        card does not lead to itself). A link to a deleted card, a non-card node, or a
        self-reference is dropped — the board can only draw edges that mean something.
        Well-formedness + dedup are the shared `_iter_valid_causal_targets`; this adds
        the live-card + non-self filter and re-emits each survivor as a canonical
        `{target}` dict. When nothing survives the key is removed, so an all-dangling
        list heals to sparse rather than `[]`.
        """
        links = metadata.get(_CAUSAL_LINK_FIELD)
        if not isinstance(links, list):
            return
        healed: list[Any] = []
        for target in self._iter_valid_causal_targets(links):
            if target == card_id:
                continue  # a card does not lead to itself
            entry = index.by_id.get(target)
            if entry is None or entry.entry_type != PLOT_CARD_ENTRY_TYPE:
                continue  # target card gone / not a card
            healed.append({"target": target})
        if healed:
            metadata[_CAUSAL_LINK_FIELD] = healed
        else:
            metadata.pop(_CAUSAL_LINK_FIELD, None)

    @staticmethod
    def _page_status_from_scene(scene: Any) -> str | None:
        """The DERIVED half of `page_status` (ADR-0048 S7 3b/5b): a scene attachment IS
        `on_page`, overriding any stored value; without a scene nothing is derived (the
        authored off_page / unwritten stands). The one rule the save/read healer
        (`_derive_card_page_status`) and the board projection (`_board_page_status`)
        both read — so "what makes a card on_page" is defined once and can't drift."""
        return "on_page" if isinstance(scene, str) and scene else None

    def _derive_card_page_status(self, metadata: dict[str, Any]) -> None:
        """`page_status` is authored only as off_page vs unwritten; on_page is derived
        (ADR-0048 S7 Slice 3b). A card with a `scene` attachment IS on the page → force
        `on_page`; when the scene is gone a stale `on_page` is cleared back to blank
        (which reads as `unwritten`). An authored off_page / unwritten is left as-is,
        and blank + no scene stays blank — sparse, and reads as unwritten."""
        derived = self._page_status_from_scene(metadata.get("scene"))
        if derived is not None:
            metadata[_PAGE_STATUS_FIELD] = derived
        elif metadata.get(_PAGE_STATUS_FIELD) == "on_page":
            metadata.pop(_PAGE_STATUS_FIELD, None)

    def _delete_plot_folder_node(self, entry_id: str, *, expected_entry_type: str, noun: str) -> None:
        # Root captured before the unlink so the purge rewrites the project this
        # delete belongs to even if another request opens a different one (#381).
        root = self._require_project()
        winner = self._build_node_index().by_id.get(entry_id)
        self._reject_inherited_book_local(entry_id, winner, root, noun=noun)
        # Refuse to delete a node of a different family through this endpoint.
        self._require_plot_family_winner(
            entry_id, winner, expected_entry_type, noun=noun, schema=self.read_metadata_schema()
        )
        path = self._plot_node_path(entry_id, winner, noun=noun)
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        self._purge_references_to({entry_id}, root)

    def _reject_inherited_book_local(self, entry_id: str, winner, root: Path, *, noun: str) -> None:
        # Same owned/inherited predicate every Library tenant reads
        # (`_node_is_owned_here`), but a *different* contract: a plotline or card is
        # a book-local editable node whose inherited-fork routing is merely deferred,
        # not a read-only Library node — so the message names the node and its
        # deferred-fork reason. Shared by plotlines and cards (S5a): both are
        # per-book plot-planning nodes with the same "no inherited write yet" rule.
        if winner is not None and winner.kind == "plot" and not self._node_is_owned_here(winner, root):
            raise ProjectServiceError(
                f"{noun.capitalize()} {entry_id} is inherited from "
                f"{winner.source_layer_label or 'an ancestor'}; editing or deleting an inherited "
                f"{noun} is not supported yet (fork / override deferred). Plot planning is "
                f"per-book — work with a {noun} created in this project.",
                409,
            )

    # ----- Plotlines (plot:plotline) -------------------------------------

    def list_plotlines(self) -> PlotlineList:
        return PlotlineList(
            entries=self._list_plot_folder_nodes(entry_type="plot:plotline", summary_cls=PlotlineSummary)
        )

    def create_plotline(self, request: CreatePlotlineRequest) -> PlotlineEntry:
        return self.read_plotline(
            self._create_plot_folder_node(
                title=request.title,
                requested_entry_type=request.entry_type,
                default_entry_type="plot:plotline",
                noun="plotline",
                node_id=request.id or None,
            )
        )

    def read_plotline(self, entry_id: str) -> PlotlineEntry:
        return self._build_plot_folder_entry(
            self._read_plot_folder_node(entry_id, expected_entry_type="plot:plotline", noun="plotline"),
            PlotlineEntry,
        )

    def save_plotline(self, entry_id: str, request: SavePlotlineRequest) -> PlotlineEntry:
        return self.read_plotline(
            self._save_plot_folder_node(entry_id, request, expected_entry_type="plot:plotline", noun="plotline")
        )

    def delete_plotline(self, entry_id: str) -> PlotlineList:
        self._delete_plot_folder_node(entry_id, expected_entry_type="plot:plotline", noun="plotline")
        return self.list_plotlines()

    # ----- Cards (plot:card) ---------------------------------------------
    #
    # A card (ADR-0048 §1) is a unit of story function: a synopsis (the body), a
    # primary `plotline` reference, and an optional `scene` reference. It is the
    # plotline's structural twin — a book-local flat Node under `plot/` — so it
    # shares the parametrized `_*_plot_folder_node` CRUD above, differing only in
    # (model, entry_type, noun); its fields ride through `metadata`. Claims (§4)
    # are deferred — see the `plot:card` schema comment (default_schema.py) for why.

    def list_cards(self) -> CardList:
        return CardList(entries=self._list_plot_folder_nodes(entry_type="plot:card", summary_cls=CardSummary))

    def create_card(self, request: CreateCardRequest) -> CardEntry:
        return self.read_card(
            self._create_plot_folder_node(
                title=request.title,
                requested_entry_type=request.entry_type,
                default_entry_type="plot:card",
                noun="card",
                node_id=request.id or None,
            )
        )

    def read_card(self, entry_id: str) -> CardEntry:
        return self._build_plot_folder_entry(
            self._read_plot_folder_node(entry_id, expected_entry_type="plot:card", noun="card"),
            CardEntry,
        )

    def save_card(self, entry_id: str, request: SaveCardRequest) -> CardEntry:
        return self.read_card(
            self._save_plot_folder_node(entry_id, request, expected_entry_type="plot:card", noun="card")
        )

    def delete_card(self, entry_id: str) -> CardList:
        self._delete_plot_folder_node(entry_id, expected_entry_type="plot:card", noun="card")
        return self.list_cards()

    # ----- Card operations: realize, attach, seed (ADR-0048 §1) -----------
    #
    # *attach* — binding a card to an existing scene — is not its own operation:
    # it is a `save_card` that sets the `scene` entity_ref, which the board's
    # picker will drive (S7). `_set_card_scene` below is that write, reused by
    # both realize and seed so the ref is always schema-validated (the scene
    # must exist) through the one save path. *realize* creates the scene first;
    # *seed-from-manuscript* is the bulk inverse — a card for every scene.

    def _set_card_scene(self, card: CardEntry, scene_id: str) -> CardEntry:
        # Attach = write the card's `scene` ref through the normal save path, so
        # the ref is schema-validated and the index / reference graph stay
        # coherent. Attachment lives only on the card (scenes never grow planning
        # fields — ADR binding decisions), so this is the whole of "attach".
        metadata = {**card.metadata, "scene": scene_id}
        return self.save_card(
            card.id,
            SaveCardRequest(
                title=card.title,
                body=card.body,
                entry_type=card.entry_type,
                metadata=metadata,
                base_revision=card.revision,
            ),
        )

    def realize_card(self, entry_id: str, request: RealizeCardRequest) -> CardEntry:
        """Create a scene from a card and attach it (ADR-0048 §1, *realize*).

        A planned card becomes a real, empty scene slotted into the manuscript
        (titled after the card; placement via `parent_id`, else the first
        container — create_scene's fallback), linked back through the card's
        `scene` ref. The synopsis stays on the card as the plan; the new scene
        holds the prose the writer has yet to write. 0..1 scene per card, so a
        card that already has one 409s rather than orphaning the first scene.
        """
        root = self._require_project()
        card = self.read_card(entry_id)
        if card.metadata.get("scene"):
            raise ProjectServiceError(
                f"Card {entry_id} already has a scene attached; detach it before realizing another.",
                409,
            )
        # Refuse a non-writable (inherited) card BEFORE minting the scene: realize
        # has a side effect (create_scene), and save_card's book-local write guard
        # would otherwise fire only after the scene exists — leaving an orphan
        # scene behind on a 409. Run the same guard up front, on the resolved winner.
        self._reject_inherited_book_local(
            entry_id, self._build_node_index().by_id.get(entry_id), root, noun="card"
        )
        scene = self.create_scene(CreateSceneRequest(title=card.title, parent_id=request.parent_id))
        return self._set_card_scene(card, scene.id)

    def seed_cards_from_manuscript(self) -> CardList:
        """Create one attached card per manuscript scene that has none (ADR-0048 §1/§S5).

        An explicit, re-runnable bulk action: walk the manuscript in reading
        order and mint a `plot:card` for every scene not already referenced by a
        card, attaching each to its scene (title from the scene; plotline left
        for the writer). Idempotent — a second run adds nothing, because a scene
        already carded is skipped (0..n cards per scene, but seed adds at most
        the one it is responsible for).
        """
        carded_scene_ids = {
            card.metadata["scene"]
            for card in self.list_cards().entries
            if card.metadata.get("scene")
        }
        for scene_id, title in self._manuscript_scene_nodes():
            if scene_id in carded_scene_ids:
                continue
            card = self.create_card(CreateCardRequest(title=title))
            self._set_card_scene(card, scene_id)
            carded_scene_ids.add(scene_id)
        return self.list_cards()

    def _manuscript_scene_nodes(self) -> list[tuple[str, str]]:
        # (scene_id, title) for every leaf *scene*, in manuscript reading order —
        # the source list seed-from-manuscript mints cards from. Only true leaves
        # count: containers (acts/chapters) also carry a backing `scene_id`, so
        # the filter is `_is_leaf_node` (type == scene:scene), not merely
        # "has a scene_id". Title is the manuscript node's title (what the writer
        # sees in the tree), which create_scene seeds and rename keeps in step.
        ordered: list[tuple[str, str]] = []

        def walk(node) -> None:
            if self._is_leaf_node(node) and node.scene_id:
                ordered.append((node.scene_id, node.title))
            for child in node.children:
                walk(child)

        walk(self.read_structure().root)
        return ordered

    # ----- Template instantiation (a plotline IS an instance, ADR-0053) ----
    #
    # A plotline is a plot-template instance (ADR-0053 §1): there is no separate
    # "instance" kind. A plain / ad-hoc plotline is just `create_plotline` with no
    # beats (the empty case); `instantiate_plot_template` is the one bespoke op —
    # it mints a plotline seeded with a snapshot of the template's beat roster.

    def instantiate_plot_template(self, template_id: str) -> PlotlineEntry:
        """Apply a template to this book (ADR-0048 §3; ADR-0053 §2): snapshot its
        beats into a new, book-local `plot:plotline` the writer then specializes.

        The template stays pristine (it may be an inherited, read-only Library
        node); the plotline is a book-local editable copy. The beat roster is
        *copied*, not linked — a plotline must stand alone (an ad-hoc one has no
        template at all), and snapshotting is what lets the writer diverge from the
        generic beats freely. `source_template_id` / `source_template_name` record
        the lineage, so the plotline can still name the structure it was rolled from
        after it diverges or the source template is gone.
        """
        source = self.read_plot_template(template_id)
        # read_plot_template validated the beats field, so every item is a member
        # map (a non-dict item would have 422'd on read) — no shape guard needed here.
        source_beats = source.metadata.get("beats") or []
        instance_beats = [
            {key: beat[key] for key in _INSTANCE_BEAT_SNAPSHOT_KEYS if key in beat}
            for beat in source_beats
        ]
        new_id = self._create_plot_folder_node(
            title=source.title,
            requested_entry_type="",
            default_entry_type=PLOT_PLOTLINE_ENTRY_TYPE,
            noun="plotline",
            seed_metadata={
                "instance_beats": instance_beats,
                "source_template_id": source.id,
                "source_template_name": source.title,
            },
        )
        return self.read_plotline(new_id)

    # ----- The board (plot:board) — a per-project layout singleton --------

    def _plot_board_path(self) -> Path:
        return self._require_project() / PLOT_BOARD_FILENAME

    def read_plot_board(self) -> PlotBoard:
        """Open the board, creating it on first open (ADR-0048 §3).

        Unlike the project node (project.md always exists from create_project),
        the board is minted lazily the first time it is opened, so an absent
        file is created here rather than 404'd. It lives outside the `plot/`
        family folder and is not in the node index — one board per open book.
        """
        path = self._plot_board_path()
        if not path.exists():
            self._write_plot_board_file(path, PlotBoard(id=self._new_id("plot"), layout={}))
        front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "plot:board"
        entry_type = raw_entry_type if isinstance(raw_entry_type, str) else "plot:board"
        raw_layout = front_matter.get("layout")
        layout = raw_layout if isinstance(raw_layout, dict) else {}
        return PlotBoard(
            id=node_id,
            title=str(front_matter.get("title") or "Board"),
            revision=self._revision(path),
            entry_type=entry_type,
            layout=layout,
        )

    def save_plot_board(self, request: SavePlotBoardRequest) -> PlotBoard:
        path = self._plot_board_path()
        exists = path.exists()
        current_revision = self._revision(path) if exists else ""
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Plot board changed on disk after it was opened.", 409)
        # Identity rides the file, not the request — a save never re-mints an id
        # the file already carries; an absent (or id-less) file is minted here,
        # the same repair contract as the project node.
        node_id = (self._front_matter_id(path) if exists else None) or self._new_id("plot")
        board = PlotBoard(id=node_id, revision=current_revision, layout=request.layout)
        self._write_plot_board_file(path, board)
        return self.read_plot_board()

    def _write_plot_board_file(self, path: Path, board: PlotBoard) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": board.id,
                "title": board.title,
                "entry_type": board.entry_type,
                "layout": board.layout,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        self._atomic_write(path, f"---\n{front_matter}\n---\n")

    def read_plot_board_projection(self) -> PlotBoardProjection:
        """The board's render model in one read (ADR-0048 S7a + Slice 4; ADR-0053):
        the plotlines with their beat rosters, the manuscript containers a card lays
        out inside, the cards with their plotline/scene refs + resolved container, and
        the board's opaque layout. Read-only and computed — card + plotline + structure
        + board data only, never the read-only Library templates.

        Card refs need no dangling-resolution here: deleting a scene or a plotline
        purges the referencing cards (delete_scene / delete_plotline →
        `_purge_references_to`), so a stored ref is always either live or already
        blanked to "" — the same invariant the unset case relies on. A plain
        `or None` is the whole of "resolve a ref"; a gone scene projects as an
        unattached card (ADR §S5), never a dangling pointer.

        The structure is walked exactly once (`_board_container_map`) and joined
        onto the cards in memory, so the projection adds no per-card structure I/O.
        """
        board = self.read_plot_board()
        plotline_entries = self.list_plotlines().entries
        card_entries = self.list_cards().entries
        # One pass over every card's beat links yields two things with no extra I/O:
        # the per-(plotline, beat) USE-COUNT a plotline node shows (0 = a gap the
        # structure exposes; ADR-0053 §6 / S5a), and the set of plotlines some card
        # links. A plotline lands in `use_counts` iff a card links a beat of it, so its
        # keys ARE the referenced set the badge catalog resolves from.
        use_counts: dict[str, Counter[str]] = {}
        for card in card_entries:
            for plotline_id, beat_id in self._iter_valid_beat_link_pairs(card.metadata.get(_BEAT_LINK_FIELD)):
                use_counts.setdefault(plotline_id, Counter())[beat_id] += 1
        plotlines = [
            PlotBoardPlotline(
                id=line.id,
                title=line.title,
                color=line.metadata.get("color") or None,
                beats=self._plotline_board_beats(line.metadata, use_counts.get(line.id)),
            )
            for line in plotline_entries
        ]
        containers, scene_to_container, scene_to_order = self._board_container_map()
        # Resolve card→beat badges against the live plotlines once per projection
        # (Slice 5b; ADR-0053): the stored links carry only ids, so this catalog turns
        # each into a titled badge with a map lookup instead of a read per link. Built
        # from the plotlines already listed above — no second front-matter read — and
        # limited to the plotlines some card links (the use_counts keys).
        beat_catalog = self._plotline_beat_catalog(plotline_entries, set(use_counts))
        # The live card ids, so authored causal links resolve to real edge endpoints
        # (Slice 6b) — the display side of `_heal_causal_links`, symmetric with the
        # beat catalog above.
        card_ids = {card.id for card in card_entries}
        cards: list[PlotBoardCard] = []
        used_containers: set[str] = set()
        for card in card_entries:
            scene = card.metadata.get("scene") or None
            container = scene_to_container.get(scene) if scene else None
            # Mark the card's container and every ancestor used, so a nesting box
            # (a "part" between act and chapter) is projected even with no direct card.
            cursor = container
            while cursor is not None and cursor not in used_containers:
                used_containers.add(cursor)
                cursor = containers[cursor].parent
            cards.append(
                PlotBoardCard(
                    id=card.id,
                    title=card.title,
                    synopsis=card.body,
                    plotline=card.metadata.get("plotline") or None,
                    scene=scene,
                    container=container,
                    page_status=self._board_page_status(card.metadata, scene),
                    beats=self._resolve_card_beats(card.metadata, beat_catalog),
                    sequence=scene_to_order.get(scene) if scene else None,
                    causal_links=self._resolve_card_causal(card.metadata, card_ids, card.id),
                )
            )
        # Reading order (containers is already ordered), used-only — an empty
        # container is not a board concern.
        board_containers = [c for cid, c in containers.items() if cid in used_containers]
        return PlotBoardProjection(
            board_id=board.id,
            board_revision=board.revision,
            layout=board.layout,
            plotlines=plotlines,
            containers=board_containers,
            cards=cards,
        )

    def _board_container_map(
        self,
    ) -> tuple[dict[str, PlotBoardContainer], dict[str, str], dict[str, int]]:
        """Walk the manuscript once → (containers-by-id in reading order,
        scene_id → innermost-container-id, scene_id → reading-order rank).

        A *container* is a non-leaf structure node other than the root — an act, a
        chapter, whatever container types the project declares (`_is_leaf_node`
        draws the leaf/container line, the same test seed-from-manuscript uses). A
        card lays out inside its scene's INNERMOST container (the scene's immediate
        parent); the board nests that box inside its ancestors via `parent`. A scene
        directly under the root has no container (it maps to nothing here), so its
        card is homeless — same as a scene-less card.

        `scene_to_order` ranks EVERY carded leaf scene by manuscript reading order
        (0-based, in pre-order) — including a scene directly under the root, which
        is homeless (no container) yet still holds a reveal-order position (ADR-0048
        S7 Slice 6). The board's manuscript-order edge layer chains cards by this
        rank, and the beat-sequence layer orders a beat's cards by it.

        `containers` is insertion-ordered by a pre-order walk, i.e. manuscript
        reading order, which the board relies on to lay acts/chapters out in order.
        """
        containers: dict[str, PlotBoardContainer] = {}
        scene_to_container: dict[str, str] = {}
        scene_to_order: dict[str, int] = {}

        def walk(node: StructureNode, parent_container: str | None) -> None:
            for child in node.children:
                if self._is_leaf_node(child):
                    if child.scene_id:
                        # Rank by encounter order (pre-order == reading order); a
                        # scene under the root is homeless but still ranked.
                        scene_to_order[child.scene_id] = len(scene_to_order)
                        if parent_container is not None:
                            scene_to_container[child.scene_id] = parent_container
                else:
                    if child.id not in containers:
                        containers[child.id] = PlotBoardContainer(
                            id=child.id, title=child.title, parent=parent_container
                        )
                    walk(child, child.id)

        walk(self.read_structure().root, None)
        return containers, scene_to_container, scene_to_order

    def _board_page_status(self, metadata: dict[str, Any], scene: str | None) -> str | None:
        """The card's page status as the board shows it (ADR-0048 S7 Slice 5b):
        `on_page` when a scene is attached (the shared `_page_status_from_scene` rule,
        overriding any stored value), else the authored `off_page` / `unwritten`, else
        None — the sparse default, which reads as unwritten. Derived from the CURRENT
        scene, so a stale stored `on_page` on a since-detached card (the card list
        skips read-side healing) never reaches the board. The valid-value filter is a
        read-time defense (write-time schema validation is what strips a bad value)."""
        derived = self._page_status_from_scene(scene)
        if derived is not None:
            return derived
        stored = metadata.get(_PAGE_STATUS_FIELD)
        return stored if stored in ("off_page", "unwritten") else None

    @staticmethod
    def _iter_roster_beats(metadata: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield each well-formed beat dict — one carrying a non-empty string `id` —
        from a plotline's `instance_beats` roster, in stored order (ADR-0053). One
        place decides what a valid roster beat is, so the board-node roster, the
        card-badge catalog, and the AI context can't drift on it. A plotline's own
        writes id-heal the roster, so a beat lacking an id is a belt-and-braces skip."""
        raw = metadata.get("instance_beats")
        if not isinstance(raw, list):
            return
        for beat in raw:
            if isinstance(beat, dict) and isinstance(beat.get("id"), str) and beat["id"]:
                yield beat

    def _plotline_board_beats(
        self, metadata: dict[str, Any], use_counts: Mapping[str, int] | None = None
    ) -> list[PlotBoardPlotlineBeat]:
        """A plotline's beat roster as the board node renders it (ADR-0053 §3): each
        beat's stable id + title, in stored order, with its `use_count` (how many cards
        fulfil it; ADR-0053 §6 / S5a). `use_counts` maps this plotline's beat ids to
        their counts — a beat absent from it (nothing links it) is a 0."""
        counts = use_counts or {}
        return [
            PlotBoardPlotlineBeat(
                beat_id=beat["id"],
                title=str(beat.get("title") or ""),
                use_count=counts.get(beat["id"], 0),
            )
            for beat in self._iter_roster_beats(metadata)
        ]

    def _plotline_beat_catalog(
        self, plotline_entries: list[PlotlineSummary], referenced: set[str]
    ) -> dict[str, tuple[str, str | None, dict[str, str]]]:
        """`plotline_id -> (plotline title, plotline colour, {beat_id: beat title})` for
        each `referenced` plotline (ADR-0048 S7 Slice 5b; ADR-0053), so a card's beat
        badges resolve by map lookup rather than a read per link. Built from the
        plotline summaries the projection already listed — no second front-matter read;
        an unreadable plotline never enters that list, so its links drop, matching
        `_heal_beat_links`. The colour lets the board tint a card's badges by plotline."""
        catalog: dict[str, tuple[str, str | None, dict[str, str]]] = {}
        for entry in plotline_entries:
            if entry.id not in referenced:
                continue
            titles = {beat["id"]: str(beat.get("title") or "") for beat in self._iter_roster_beats(entry.metadata)}
            catalog[entry.id] = (entry.title, entry.metadata.get("color") or None, titles)
        return catalog

    def _resolve_card_beats(
        self, metadata: dict[str, Any], catalog: dict[str, tuple[str, str | None, dict[str, str]]]
    ) -> list[PlotBoardBeat]:
        """Resolve a card's stored `beat_links` (id pairs) into board badges (ADR-0048
        S7 Slice 5b; ADR-0053), dropping any link whose plotline or beat is gone (the
        display side of `_heal_beat_links`). Well-formedness + dedup are the shared
        `_iter_valid_beat_link_pairs`; this adds the catalog lookup + title resolution.
        Badge order follows the stored list, so it is stable across reads and the
        writer's arrangement holds."""
        resolved: list[PlotBoardBeat] = []
        for plotline_id, beat_id in self._iter_valid_beat_link_pairs(metadata.get(_BEAT_LINK_FIELD)):
            entry = catalog.get(plotline_id)
            if entry is None:
                continue  # plotline gone / not referenced → drop (display-side heal)
            plotline_title, plotline_color, beat_titles = entry
            title = beat_titles.get(beat_id)
            if title is None:
                continue  # beat left the roster → drop
            resolved.append(
                PlotBoardBeat(
                    plotline_id=plotline_id,
                    plotline_title=plotline_title,
                    plotline_color=plotline_color,
                    beat_id=beat_id,
                    title=title,
                )
            )
        return resolved

    def _resolve_card_causal(
        self, metadata: dict[str, Any], card_ids: set[str], self_id: str
    ) -> list[str]:
        """Resolve a card's stored `causal_links` into the target card ids the board
        draws edges to (ADR-0048 S7 Slice 6b), dropping any target that is gone, is a
        self-reference, or isn't a live card (the display side of `_heal_causal_links`).
        Well-formedness + dedup are the shared `_iter_valid_causal_targets`; this adds
        the live-card + non-self filter. Order follows the stored list, so it is stable
        across reads."""
        return [
            target
            for target in self._iter_valid_causal_targets(metadata.get(_CAUSAL_LINK_FIELD))
            if target != self_id and target in card_ids
        ]

    # ----- Templates (plot:template) — an ADR-0049 Library tenant ---------
    #
    # A diagnostic story-structure lens. Its beat roster + guidance live in a
    # `template:` front-matter block (an opaque payload like the board's
    # `layout`), the prose guide is the body. The built-in Library ships the
    # 14 defaults as read-only ancestor nodes; a writer clones one into this
    # project (a new id, editable) to adapt it. Read-only-in-place and clone are
    # the shared Library-tenant surface (`_node_is_owned_here` /
    # `_reject_inherited_library_write`); this mixin adds only the per-kind
    # read/write of the `template:` block. Owned templates ARE `plot/` family
    # nodes, so they index and reference-purge like plotlines.

    def list_plot_templates(self) -> PlotTemplateList:
        root = self._require_project()
        index = self._build_node_index()
        entries: list[PlotTemplateSummary] = []
        for entry in index.by_id.values():
            if entry.entry_type != PLOT_TEMPLATE_ENTRY_TYPE:
                continue
            try:
                front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
                template = self._parse_plot_template_spec(front_matter.get("template"), entry.id)
            except ProjectServiceError:
                # A file that will not read or whose `template:` block is corrupt is
                # skipped from the list (the single-entry read still 422s), exactly
                # as list_prompt_entries / list_plotlines skip unreadable entries.
                continue
            raw_metadata = front_matter.get("metadata")
            roster = raw_metadata.get("beats") if isinstance(raw_metadata, dict) else None
            entries.append(
                PlotTemplateSummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    body=body,
                    entry_type=PLOT_TEMPLATE_ENTRY_TYPE,
                    template=template,
                    beat_count=len(roster) if isinstance(roster, list) else 0,
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                    is_library=entry.is_library,
                    editable=self._node_is_owned_here(entry, root),
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return PlotTemplateList(entries=entries)

    def read_plot_template(self, entry_id: str) -> PlotTemplate:
        # Shares the read core (resolve + is_a guard + #345 healing + validate);
        # a plotline/card is not a template, so the shared `_require_plot_family`
        # 404s it (was the bespoke exact-type check here). Templates add only the
        # `template:` spec block and the Library provenance the core does not carry.
        root = self._require_project()
        read = self._read_plot_folder_node(entry_id, expected_entry_type=PLOT_TEMPLATE_ENTRY_TYPE, noun="plot template")
        return PlotTemplate(
            id=read.node_id,
            title=read.title,
            body=read.body,
            revision=read.revision,
            entry_type=PLOT_TEMPLATE_ENTRY_TYPE,
            template=self._parse_plot_template_spec(read.front_matter.get("template"), read.node_id),
            metadata=read.metadata,
            computed_metadata=self._computed_entry_metadata(
                read.body, node_id=read.node_id, entry_type=PLOT_TEMPLATE_ENTRY_TYPE, schema=read.schema
            ),
            source_layer_id=read.index_entry.source_layer_id if read.index_entry else "",
            source_layer_label=read.index_entry.source_layer_label if read.index_entry else "",
            is_library=read.index_entry.is_library if read.index_entry else False,
            # Fail-closed truth the UI read-only lock reads (#689): an inherited
            # winner is not owned → read-only. No index winner means a just-written
            # owned clone, editable. Mirrors `_reject_inherited_library_write`.
            editable=self._node_is_owned_here(read.index_entry, root) if read.index_entry else True,
        )

    def create_plot_template(self, request: CreatePlotTemplateRequest) -> PlotTemplate:
        """Blank-create an owned `plot:template` in this project — the non-fork entry
        point (#918). Mints a new id and writes a minimal spec with an empty beat
        roster; the writer names it and authors beats in the editor. The owned twin of
        fork_plot_template (which copies a Library / ancestor original). Owned + editable
        from birth, so it saves and deletes like any clone."""
        root = self._require_project()
        title = request.title.strip() or "New template"
        new_id = self._new_id("plot")
        spec = PlotTemplateSpec(display_name=title)
        path = self._filepath_for_new_node(root / "plot", title)
        self._write_plot_template_file(path, new_id, title, spec, body="")
        return self.read_plot_template(new_id)

    def fork_plot_template(self, entry_id: str) -> PlotTemplate:
        """Clone an inherited template into this project as an editable copy
        (ADR-0049 §5, generalized from prompts in ADR-0048 S4b).

        Mints a **new id** and leaves the Library / ancestor original in place —
        the same "duplicate the default to adapt it" gesture prompts use, so
        clone and per-project hide stay orthogonal. A template this project
        already owns is directly editable, so there is nothing to clone.
        """
        root = self._require_project()
        winner = self._build_node_index().by_id.get(entry_id)
        if winner is None or winner.entry_type != PLOT_TEMPLATE_ENTRY_TYPE:
            raise ProjectServiceError(f"Plot template {entry_id} not found.", 404)
        if self._node_is_owned_here(winner, root):
            raise ProjectServiceError(
                f"Plot template {entry_id} is owned by this project and is directly "
                "editable; there is nothing to clone.",
                409,
            )
        source = self.read_plot_template(entry_id)
        new_id = self._new_id("plot")
        path = self._filepath_for_new_node(root / "plot", source.title)
        self._write_plot_template_file(path, new_id, source.title, source.template, source.body, source.metadata)
        return self.read_plot_template(new_id)

    def save_plot_template(self, entry_id: str, request: SavePlotTemplateRequest) -> PlotTemplate:
        # Inherited (Library / ancestor) templates are read-only in place — the
        # structural 409, shared with prompts. Scope the reject to `plot:template`
        # (the `plot` kind also carries plotlines, which reject separately). Owned
        # clones save freely.
        self._reject_inherited_library_write(entry_id, entry_type=PLOT_TEMPLATE_ENTRY_TYPE, noun="plot template")
        index = self._build_node_index()
        path = self._path_for_node_id(entry_id, "plot")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        if (front_matter.get("entry_type") or "") != PLOT_TEMPLATE_ENTRY_TYPE:
            raise ProjectServiceError(f"Node {node_id} is not a plot template.", 404)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Plot template changed on disk after it was opened.", 409)
        markdown_errors = validate_scene_markdown(request.body)
        if markdown_errors:
            raise ProjectServiceError(" ".join(markdown_errors), 422)
        # Validate metadata against the schema before persisting it (S4c finding #1),
        # the same contract as save_plotline — the read path heals it, so the write
        # path must carry it rather than silently dropping author-added fields.
        schema = self.read_metadata_schema()
        metadata = self._normalise_metadata(request.metadata, path)
        metadata = self._ensure_beat_identity(metadata)
        metadata_errors = self._validate_entry_metadata(
            label=f"Plot template {node_id}",
            entry_type=PLOT_TEMPLATE_ENTRY_TYPE,
            expected_kind="plot",
            metadata=metadata,
            schema=schema,
            node_index=index,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        self._write_plot_template_file(path, node_id, request.title, request.template, request.body, metadata)
        self._maybe_rename_node_file(path, request.title)
        return self.read_plot_template(node_id)

    def delete_plot_template(self, entry_id: str) -> PlotTemplateList:
        root = self._require_project()
        self._reject_inherited_library_write(entry_id, entry_type=PLOT_TEMPLATE_ENTRY_TYPE, noun="plot template")
        winner = self._build_node_index().by_id.get(entry_id)
        if winner is None or winner.entry_type != PLOT_TEMPLATE_ENTRY_TYPE:
            raise ProjectServiceError(f"Plot template {entry_id} not found.", 404)
        path = self._path_for_node_id(entry_id, "plot")
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        self._purge_references_to({entry_id}, root)
        return self.list_plot_templates()

    def _parse_plot_template_spec(self, raw: object, node_id: str) -> PlotTemplateSpec:
        from pydantic import ValidationError

        # Absent block → an empty spec (a minimal template is legal). But a block
        # that is *present and malformed* is corruption, whether it is a non-mapping
        # or a mapping that fails validation — 422 both, not a silent blank spec.
        if raw is None:
            return PlotTemplateSpec()
        if not isinstance(raw, dict):
            raise ProjectServiceError(
                f"Plot template {node_id} has an invalid `template` block: it must be a mapping.", 422
            )
        try:
            return PlotTemplateSpec.model_validate(raw)
        except ValidationError as exc:
            raise ProjectServiceError(f"Plot template {node_id} has an invalid `template` block: {exc}.", 422) from exc

    def _write_plot_template_file(
        self,
        path: Path,
        node_id: str,
        title: str,
        spec: PlotTemplateSpec,
        body: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        front_matter_data: dict[str, Any] = {
            "id": node_id,
            "title": title,
            "entry_type": PLOT_TEMPLATE_ENTRY_TYPE,
            "template": spec.model_dump(mode="json"),
        }
        # Only emit a `metadata:` block when there is something to store — an empty
        # dict is noise, matching the omit-empty behaviour of _write_node_entry_file.
        if metadata:
            front_matter_data["metadata"] = metadata
        front_matter = yaml.safe_dump(
            front_matter_data,
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body_text = f"{body.rstrip()}\n" if body and body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body_text}")
