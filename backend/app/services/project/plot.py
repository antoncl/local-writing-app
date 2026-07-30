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
    SavePlotBoardRequest,
    SavePlotlineRequest,
)
from app.services.markdown_validation import validate_scene_markdown
from app.services.project.errors import ProjectServiceError

PLOT_BOARD_FILENAME = "plot-board.md"


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
        self._write_plotline_file(self._filepath_for_new_node(root / "plot", request.title), entry)
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
        index = self._build_node_index()
        winner = index.by_id.get(entry_id)
        # S4a writes book-local. An inherited winner (an ancestor's plotline) is
        # out of scope — its fork/override routing is deferred (see module note).
        # Saving one here writes a book-local copy carrying the same id, which is
        # acceptable for the per-book planning surface plotlines serve.
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
        self._write_plotline_file(path, entry)
        self._maybe_rename_node_file(path, request.title)
        return self.read_plotline(node_id)

    def delete_plotline(self, entry_id: str) -> PlotlineList:
        # Root captured before the unlink so the purge rewrites the project this
        # delete belongs to even if another request opens a different one (#381).
        root = self._require_project()
        path = self._path_for_node_id(entry_id, "plot")
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        self._purge_references_to({entry_id}, root)
        return self.list_plotlines()

    def _write_plotline_file(self, path: Path, entry: PlotlineEntry) -> None:
        front_matter = yaml.safe_dump(
            {
                "id": entry.id,
                "title": entry.title,
                "entry_type": entry.entry_type,
                "metadata": entry.metadata,
            },
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = entry.body.rstrip() + "\n" if entry.body.strip() else ""
        self._atomic_write(path, f"---\n{front_matter}\n---\n\n{body}")

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
