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

from pathlib import Path
from typing import Any, NamedTuple

import yaml

from app.models import (
    CardEntry,
    CardList,
    CardSummary,
    CreateCardRequest,
    CreatePlotlineRequest,
    PlotBoard,
    PlotlineEntry,
    PlotlineList,
    PlotlineSummary,
    PlotTemplate,
    PlotTemplateList,
    PlotTemplateSpec,
    PlotTemplateSummary,
    SaveCardRequest,
    SavePlotBoardRequest,
    SavePlotlineRequest,
    SavePlotTemplateRequest,
)
from app.services.markdown_validation import validate_scene_markdown
from app.services.project.errors import ProjectServiceError

PLOT_BOARD_FILENAME = "plot-board.md"
PLOT_TEMPLATE_ENTRY_TYPE = "plot:template"


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
            )
        )

    def read_plotline(self, entry_id: str) -> PlotlineEntry:
        read = self._read_plot_folder_node(entry_id, expected_entry_type="plot:plotline", noun="plotline")
        return PlotlineEntry(
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

    def save_plotline(self, entry_id: str, request: SavePlotlineRequest) -> PlotlineEntry:
        return self.read_plotline(
            self._save_plot_folder_node(entry_id, request, expected_entry_type="plot:plotline", noun="plotline")
        )

    def delete_plotline(self, entry_id: str) -> PlotlineList:
        self._delete_plot_folder_node(entry_id, expected_entry_type="plot:plotline", noun="plotline")
        return self.list_plotlines()

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

    def _require_plot_family_winner(self, entry_id: str, winner, family_root: str, *, noun: str) -> None:
        # The delete guard: refuse to unlink a resolved node of a different
        # family through this endpoint (a plotline id on the cards delete path
        # would otherwise destroy the plotline and return the card list).
        if winner is not None and winner.kind == "plot" and family_root not in self.entry_type_ancestry(
            winner.entry_type
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
        self, *, title: str, requested_entry_type: str, default_entry_type: str, noun: str
    ) -> str:
        root = self._require_project()
        entry_type = requested_entry_type or default_entry_type
        schema = self.read_metadata_schema()
        # The requested type must be in this family (rejects board/template/the
        # sibling family), subsuming the old board-only guard.
        self._require_plot_family(entry_type, default_entry_type, noun=noun, schema=schema)
        initial_metadata = self._initial_metadata_from_defaults(entry_type, schema)
        metadata_errors = self._validate_entry_metadata(
            label=f"{noun.capitalize()} new",
            entry_type=entry_type,
            expected_kind="plot",
            metadata=initial_metadata,
            schema=schema,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
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

    def _delete_plot_folder_node(self, entry_id: str, *, expected_entry_type: str, noun: str) -> None:
        # Root captured before the unlink so the purge rewrites the project this
        # delete belongs to even if another request opens a different one (#381).
        root = self._require_project()
        winner = self._build_node_index().by_id.get(entry_id)
        self._reject_inherited_book_local(entry_id, winner, root, noun=noun)
        # Refuse to delete a node of a different family through this endpoint.
        self._require_plot_family_winner(entry_id, winner, expected_entry_type, noun=noun)
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
            )
        )

    def read_card(self, entry_id: str) -> CardEntry:
        read = self._read_plot_folder_node(entry_id, expected_entry_type="plot:card", noun="card")
        return CardEntry(
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

    def save_card(self, entry_id: str, request: SaveCardRequest) -> CardEntry:
        return self.read_card(
            self._save_plot_folder_node(entry_id, request, expected_entry_type="plot:card", noun="card")
        )

    def delete_card(self, entry_id: str) -> CardList:
        self._delete_plot_folder_node(entry_id, expected_entry_type="plot:card", noun="card")
        return self.list_cards()

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
            entries.append(
                PlotTemplateSummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    body=body,
                    entry_type=PLOT_TEMPLATE_ENTRY_TYPE,
                    template=template,
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
