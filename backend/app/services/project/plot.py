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

import yaml

from app.models import (
    CreatePlotlineRequest,
    PlotBoard,
    PlotlineEntry,
    PlotlineList,
    PlotlineSummary,
    PlotTemplate,
    PlotTemplateList,
    PlotTemplateSpec,
    PlotTemplateSummary,
    SavePlotBoardRequest,
    SavePlotlineRequest,
    SavePlotTemplateRequest,
)
from app.services.markdown_validation import validate_scene_markdown
from app.services.project.errors import ProjectServiceError

PLOT_BOARD_FILENAME = "plot-board.md"
PLOT_TEMPLATE_ENTRY_TYPE = "plot:template"


class PlotMixin:
    # ----- Plotlines (plot:plotline) -------------------------------------

    def list_plotlines(self) -> PlotlineList:
        index = self._build_node_index()
        entries: list[PlotlineSummary] = []
        for entry in index.by_id.values():
            # Exact entry_type, not kind: the `plot` kind also carries the board
            # and (from S4b) the Library's templates, none of which belong in
            # the plotline list. A plotline sub-type would need is-a filtering,
            # but S4a ships none.
            if entry.entry_type != "plot:plotline":
                continue
            try:
                front_matter, body = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            metadata = self._normalise_metadata(front_matter.get("metadata"), entry.path)
            entries.append(
                PlotlineSummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    body=body,
                    entry_type="plot:plotline",
                    metadata=metadata,
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return PlotlineList(entries=entries)

    def create_plotline(self, request: CreatePlotlineRequest) -> PlotlineEntry:
        root = self._require_project()
        entry_type = request.entry_type or "plot:plotline"
        self._reject_non_plotline_type(entry_type)
        schema = self.read_metadata_schema()
        initial_metadata = self._initial_metadata_from_defaults(entry_type, schema)
        metadata_errors = self._validate_entry_metadata(
            label="Plotline new",
            entry_type=entry_type,
            expected_kind="plot",
            metadata=initial_metadata,
            schema=schema,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)

        entry = PlotlineEntry(
            id=self._new_id("plot"),
            title=request.title,
            body="",
            revision="",
            entry_type=entry_type,
            metadata=initial_metadata,
        )
        self._write_node_entry_file(
            self._filepath_for_new_node(root / "plot", request.title),
            entry.id,
            entry.title,
            entry.entry_type,
            entry.metadata,
            entry.body,
        )
        return self.read_plotline(entry.id)

    def read_plotline(self, entry_id: str) -> PlotlineEntry:
        index = self._build_node_index()
        index_entry = index.by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "plot":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "plot")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        raw_entry_type = front_matter.get("entry_type") or "plot:plotline"
        if not isinstance(raw_entry_type, str):
            raise ProjectServiceError(f"Plotline {node_id} has invalid entry_type; it must be text.", 422)
        entry_type = raw_entry_type
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        schema = self.read_metadata_schema()
        # Same read-side healing every node kind gets (#345): drop fields a schema
        # change retired and references whose target was deleted, before validating.
        metadata = self._strip_unknown_metadata_fields(metadata, entry_type, schema)
        metadata = self._strip_dangling_references(metadata, schema, index)
        metadata_errors = self._validate_entry_metadata(
            label=f"Plotline {node_id}",
            entry_type=entry_type,
            expected_kind="plot",
            metadata=metadata,
            schema=schema,
            node_index=index,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        return PlotlineEntry(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            body=body,
            revision=self._revision(path),
            entry_type=entry_type,
            metadata=metadata,
            computed_metadata=self._computed_entry_metadata(
                body, node_id=node_id, entry_type=entry_type, schema=schema
            ),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_plotline(self, entry_id: str, request: SavePlotlineRequest) -> PlotlineEntry:
        root = self._require_project()
        self._reject_non_plotline_type(request.entry_type)
        index = self._build_node_index()
        winner = index.by_id.get(entry_id)
        # S4a writes book-local, and refuses to touch an inherited winner: without
        # fork/override routing (deferred), writing to `winner.path` would rewrite
        # ancestor canon for every downstream book. Plot planning is per-book.
        self._reject_inherited_plotline(entry_id, winner, root)
        path = winner.path if (winner is not None and winner.kind == "plot") else self._path_for_node_id(entry_id, "plot")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("Plotline changed on disk after it was opened.", 409)
        markdown_errors = validate_scene_markdown(request.body)
        if markdown_errors:
            raise ProjectServiceError(" ".join(markdown_errors), 422)
        schema = self.read_metadata_schema()
        metadata = self._normalise_metadata(request.metadata, path)
        metadata_errors = self._validate_entry_metadata(
            label=f"Plotline {node_id}",
            entry_type=request.entry_type,
            expected_kind="plot",
            metadata=metadata,
            schema=schema,
            node_index=index,
        )
        if metadata_errors:
            raise ProjectServiceError(" ".join(metadata_errors), 422)
        entry = PlotlineEntry(
            id=node_id,
            title=request.title,
            body=request.body,
            revision=current_revision,
            entry_type=request.entry_type,
            metadata=metadata,
        )
        self._write_node_entry_file(path, entry.id, entry.title, entry.entry_type, entry.metadata, entry.body)
        self._maybe_rename_node_file(path, request.title)
        return self.read_plotline(node_id)

    def delete_plotline(self, entry_id: str) -> PlotlineList:
        # Root captured before the unlink so the purge rewrites the project this
        # delete belongs to even if another request opens a different one (#381).
        root = self._require_project()
        winner = self._build_node_index().by_id.get(entry_id)
        # Same guard as save: deleting an inherited plotline resolves to the
        # ancestor's file — refuse rather than destroy canon for other books.
        self._reject_inherited_plotline(entry_id, winner, root)
        path = self._path_for_node_id(entry_id, "plot")
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        self._purge_references_to({entry_id}, root)
        return self.list_plotlines()

    def _reject_non_plotline_type(self, entry_type: str) -> None:
        # The board is a per-project singleton at plot-board.md, never a folder
        # node — refuse to write one into plot/, where it would be folder-globbed
        # into the node index (the board-is-not-indexed invariant, ADR-0048 §3).
        # `entry_type` is a free str on the request models, so this is reachable.
        # Templates (S4b) get their own Library write path; other plotline
        # sub-types are fine.
        if entry_type == "plot:board":
            raise ProjectServiceError(
                "plot:board is a per-project singleton (plot-board.md), not a plotline; "
                "it cannot be created or saved through the plotline path.",
                422,
            )

    def _reject_inherited_plotline(self, entry_id: str, winner, root: Path) -> None:
        # Same owned/inherited predicate every Library tenant reads
        # (`_node_is_owned_here`), but a *different* contract: a plotline is a
        # book-local editable node whose inherited-fork routing is merely deferred,
        # not a read-only Library node — so the message differs.
        if winner is not None and winner.kind == "plot" and not self._node_is_owned_here(winner, root):
            raise ProjectServiceError(
                f"Plotline {entry_id} is inherited from {winner.source_layer_label or 'an ancestor'}; "
                "editing or deleting an inherited plotline is not supported yet (fork / override "
                "deferred). Plot planning is per-book — work with a plotline created in this project.",
                409,
            )

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
        root = self._require_project()
        index = self._build_node_index()
        index_entry = index.by_id.get(entry_id)
        if index_entry is not None and index_entry.kind == "plot":
            path = index_entry.path
        else:
            path = self._path_for_node_id(entry_id, "plot")
        front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        if (front_matter.get("entry_type") or "") != PLOT_TEMPLATE_ENTRY_TYPE:
            # A plotline (same `plot` kind, same folder) is not a template — refuse
            # rather than hand back a shapeless spec.
            raise ProjectServiceError(f"Node {node_id} is not a plot template.", 404)
        return PlotTemplate(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            body=body,
            revision=self._revision(path),
            entry_type=PLOT_TEMPLATE_ENTRY_TYPE,
            template=self._parse_plot_template_spec(front_matter.get("template"), node_id),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
            is_library=index_entry.is_library if index_entry else False,
            # Fail-closed truth the UI read-only lock reads (#689): an inherited
            # winner is not owned → read-only. No index winner means a just-written
            # owned clone, editable. Mirrors `_reject_inherited_library_write`.
            editable=self._node_is_owned_here(index_entry, root) if index_entry else True,
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
        self._write_plot_template_file(path, new_id, source.title, source.template, source.body)
        return self.read_plot_template(new_id)

    def save_plot_template(self, entry_id: str, request: SavePlotTemplateRequest) -> PlotTemplate:
        # Inherited (Library / ancestor) templates are read-only in place — the
        # structural 409, shared with prompts. Scope the reject to `plot:template`
        # (the `plot` kind also carries plotlines, which reject separately). Owned
        # clones save freely.
        self._reject_inherited_library_write(entry_id, entry_type=PLOT_TEMPLATE_ENTRY_TYPE, noun="plot template")
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
        self._write_plot_template_file(path, node_id, request.title, request.template, request.body)
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
        self, path: Path, node_id: str, title: str, spec: PlotTemplateSpec, body: str
    ) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": node_id,
                "title": title,
                "entry_type": PLOT_TEMPLATE_ENTRY_TYPE,
                "template": spec.model_dump(mode="json"),
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body_text = f"{body.rstrip()}\n" if body and body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body_text}")
