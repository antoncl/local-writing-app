"""Saved-view slice of ProjectService (0.5.0, epic #35 / #78).

A saved view is a frontmatter-only Node kind (`view`): a ViewSpec (anchor
`kind` + a set-algebra `expr` + `sort` + `group_by`). Storage mirrors mutation
sets — layered Node markdown files under `<project>/views/` with **no prose
body**: the spec lives in front matter (via `_write_node_entry_file`'s
`extra=`). `ProjectService` composes this mixin;
shared IO/index helpers resolve through the MRO (see `mutation_sets.py`).

0.5.0 step 1 lands storage + CRUD. There is no evaluator here — the frontend
consumes a stored spec's membership at runtime.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from app.models_views import (
    CreateViewRequest,
    SaveViewRequest,
    UpdateViewUiRequest,
    ViewGroupByLevel,
    ViewLayout,
    ViewNode,
    ViewNodeList,
    ViewNodeSummary,
    ViewParam,
    ViewSort,
    ViewSpec,
    ViewUiState,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.prompt_disposition import (
    PROMPT_DISPOSITION_REVISE_ENTITIES,
    PROMPT_RUNNABLE_VALUE,
)
from app.view_grammar_generated import (
    FieldPredicate,
    FilterOp,
    NestMatch,
    NestOp,
    ViewExpr,
)

# Well-known id prefix for the per-kind system default view (ADR-0036 §5). The
# frontend addresses `view_default_<kind>` when persisting fold state for a
# pane's default (unselected) view; the node is materialized lazily here on the
# first fold write.
DEFAULT_VIEW_ID_PREFIX = "view_default_"

# The curated builtin EXTRA views a kind ships beside its default (#1682,
# mirroring frontend builtinViews.ts — the specs must stay in lockstep, pinned
# by the builtin-extra-view-specs fixture both suites assert). They share the
# default's lifecycle: synthesized in memory until the first UI-state write
# materializes a read-only system node, so appearance and fold state persist
# for them exactly as for `view_default_<kind>` — every view the app offers is
# a real (or materializable) Node. The registry entry carries its own spec
# builder, so the id roster and the spec dispatch cannot diverge.
BUILTIN_VIEW_ID_PREFIX = "view_builtin_"


def _runnable_prompts_spec(roster: ViewExpr) -> ViewSpec:
    # The prompts launchable as a standalone chat: the backend-stamped computed
    # `runnable` flag (#1684) — Chat disposition AND empty `offer_on`.
    return ViewSpec(
        kind="prompt",
        expr=ViewExpr(
            filter=FilterOp(
                of=roster,
                pred=ViewExpr(field=FieldPredicate(key="runnable", op="overlap", value=[PROMPT_RUNNABLE_VALUE])),
            )
        ),
        sort=ViewSort(by="manual"),
    )


def _openable_chats_spec(roster: ViewExpr) -> ViewSpec:
    # Hides the brainstorm chats: `seed_disposition` (the chat lift's copy of the
    # seeding prompt's disposition) blacklisted on "Revise entities", so plain and
    # freeform ("") chats stay openable.
    return ViewSpec(
        kind="chat",
        expr=ViewExpr(
            filter=FilterOp(
                of=roster,
                pred=ViewExpr(
                    field=FieldPredicate(
                        key="seed_disposition", op="disjoint", value=[PROMPT_DISPOSITION_REVISE_ENTITIES]
                    )
                ),
            )
        ),
        sort=ViewSort(by="manual"),
    )


@dataclass(frozen=True)
class BuiltinExtraView:
    title: str
    kind: str
    build: Callable[[ViewExpr], ViewSpec]


BUILTIN_EXTRA_VIEWS: dict[str, BuiltinExtraView] = {
    "view_builtin_prompt_runnable": BuiltinExtraView("Runnable prompts", "prompt", _runnable_prompts_spec),
    "view_builtin_chat_openable": BuiltinExtraView("Openable chats", "chat", _openable_chats_spec),
}


class ViewsMixin:
    def _iter_view_entries(self) -> Iterator[tuple[Any, dict[str, Any], ViewSpec | None]]:
        """One node-index pass over stored views, yielding (index entry, front
        matter, parsed spec). list_views and the ref-cycle check share it so a
        view's file is read + parsed once per call by a single loop instead of
        two divergent ones (#95). Unreadable views are skipped."""
        for entry in self._build_node_index().by_id.values():
            if entry.kind != "view":
                continue
            try:
                front_matter, _ = self._read_markdown_with_front_matter(entry.path, strict=True)
            except ProjectServiceError:
                continue
            yield entry, front_matter, self._parse_view_spec(front_matter.get("spec"))

    def list_views(self) -> ViewNodeList:
        entries: list[ViewNodeSummary] = []
        for entry, front_matter, spec in self._iter_view_entries():
            entries.append(
                ViewNodeSummary(
                    id=entry.id,
                    title=str(front_matter.get("title") or entry.id),
                    entry_type=self._view_entry_type(front_matter),
                    view_kind=spec.kind if spec else "",
                    spec=spec,
                    ui=self._parse_view_ui(front_matter.get("ui")),
                    system=self._view_system(front_matter),
                    source_layer_id=entry.source_layer_id,
                    source_layer_label=entry.source_layer_label,
                )
            )
        entries.sort(key=lambda entry: (entry.title.lower(), entry.id))
        return ViewNodeList(entries=entries)

    def create_view(self, request: CreateViewRequest) -> ViewNode:
        root = self._require_project()
        self._check_entry_type_kind(request.entry_type, "view")
        view_id = self._new_id("view")
        (root / "views").mkdir(parents=True, exist_ok=True)
        self._write_view_file(
            self._filepath_for_new_node(root / "views", request.title),
            view_id,
            request.title,
            request.entry_type,
            request.spec,
            request.layout,
        )
        return self.read_view(view_id)

    def read_view(self, view_id: str) -> ViewNode:
        index_entry = self._build_node_index().by_id.get(view_id)
        if index_entry is not None and index_entry.kind == "view":
            path = index_entry.path
        else:
            # An app-defined view id — `view_default_<kind>` or a builtin extra
            # (#1682) — has no file until the first UI-state write materializes
            # it (update_view_ui, §5). Return its honest in-memory node with
            # empty fold state (a 200) rather than a 404, so seeding a fresh
            # pane's collapse state never logs a 4xx (#1665). A materialized one
            # has an index_entry and reads its real stored ui above.
            system_node = self._system_view_node(view_id, ViewUiState())
            if system_node is not None:
                return system_node
            path = self._path_for_node_id(view_id, "view")
        front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        spec = self._parse_view_spec(front_matter.get("spec"))
        if spec is None:
            raise ProjectServiceError(f"View {node_id} has no valid spec.", 422)
        return ViewNode(
            id=node_id,
            title=str(front_matter.get("title") or node_id),
            revision=self._revision(path),
            entry_type=self._view_entry_type(front_matter),
            spec=spec,
            layout=self._parse_view_layout(front_matter.get("layout")),
            ui=self._parse_view_ui(front_matter.get("ui")),
            system=self._view_system(front_matter),
            source_layer_id=index_entry.source_layer_id if index_entry else "",
            source_layer_label=index_entry.source_layer_label if index_entry else "",
        )

    def save_view(self, view_id: str, request: SaveViewRequest) -> ViewNode:
        path = self._path_for_node_id(view_id, "view")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        # ADR-0036: a system-provided default view is read-only — spec edits go
        # through Duplicate, not Edit. Fold state still updates via update_view_ui.
        if self._view_system(front_matter):
            raise ProjectServiceError("A system default view cannot be edited; duplicate it first.", 403)
        current_revision = self._revision(path)
        if request.base_revision and request.base_revision != current_revision:
            raise ProjectServiceError("View changed on disk after it was opened.", 409)
        self._check_entry_type_kind(request.entry_type, "view")
        # Preserve fold/ui state — it lives on an independent lifecycle (the
        # lock-free /ui endpoint), so a spec save must not wipe it (ADR-0036).
        self._write_view_file(
            path,
            node_id,
            request.title,
            request.entry_type,
            request.spec,
            request.layout,
            ui=self._parse_view_ui(front_matter.get("ui")),
        )
        self._maybe_rename_node_file(path, request.title)
        return self.read_view(node_id)

    def update_view_ui(self, view_id: str, request: UpdateViewUiRequest) -> ViewNode:
        """Lock-free ui write (ADR-0036): MERGES the provided `ui` fields into the
        stored blob, preserving spec/layout/title/system. It takes no
        base_revision and does not consult the spec revision, so a fold toggle
        never 409s against a concurrent designer save — the two lifecycles are
        independent. An app-defined id with no file yet — `view_default_<kind>`
        or a builtin extra (#1682) — MATERIALIZES the read-only system view
        (§5): the pane's default (unselected) view, and the curated extras
        beside it, are real-on-disk the moment the user first folds or restyles
        one.

        The merge (only fields the request actually set are overwritten) keeps
        `ViewUiState`'s two independent writers from clobbering each other: the
        fold writer sends `collapsed`, the appearance control (ADR-0069) sends
        `appearance`, and neither wipes the other's field on this shared blob."""
        if (
            view_id.startswith((DEFAULT_VIEW_ID_PREFIX, BUILTIN_VIEW_ID_PREFIX))
            and self._build_node_index().by_id.get(view_id) is None
        ):
            return self._materialize_system_view(view_id, request.ui)
        path = self._path_for_node_id(view_id, "view")
        front_matter = self._read_front_matter_only(path, strict=True)
        node_id = self._node_id_for_path(path, front_matter)
        # Merge onto the stored ui so an appearance write preserves `collapsed`
        # and vice-versa. `model_fields_set` is exactly the keys the request JSON
        # carried, so an omitted field is left untouched (ADR-0069).
        existing_ui = self._parse_view_ui(front_matter.get("ui")) or ViewUiState()
        merged_ui = existing_ui.model_copy(
            update={key: getattr(request.ui, key) for key in request.ui.model_fields_set}
        )
        spec = self._parse_view_spec(front_matter.get("spec"))
        title = str(front_matter.get("title") or node_id)
        # SELF-HEAL an app-defined system node (#1682): its spec and title are
        # the APP's, re-derived on every write — only `ui` is user data. Without
        # this, a materialized default/extra freezes whatever spec shipped when
        # the user first folded it, silently diverging from the live definition
        # as releases refine it (the exact staleness the #1692 review flagged
        # for the pre-Amendment-3 materialized prompt default). Runs BEFORE the
        # no-valid-spec guard, so a corrupted system node heals instead of
        # bricking its ui writes.
        if self._view_system(front_matter):
            fresh = self._system_view_node(node_id, merged_ui)
            if fresh is not None:
                spec = fresh.spec
                title = fresh.title
        if spec is None:
            raise ProjectServiceError(f"View {node_id} has no valid spec.", 422)
        self._write_view_file(
            path,
            node_id,
            title,
            self._view_entry_type(front_matter),
            spec,
            self._parse_view_layout(front_matter.get("layout")),
            ui=merged_ui,
            system=self._view_system(front_matter),
        )
        return self.read_view(node_id)

    def delete_view(self, view_id: str) -> ViewNodeList:
        path = self._path_for_node_id(view_id, "view")
        # A system node (a materialized default or builtin extra) is app-owned:
        # deleting it would silently discard the user's persisted appearance and
        # fold state, then re-materialize at shipped defaults on the next write.
        # `save_view` already guards spec edits the same way (#1682).
        front_matter = self._read_front_matter_only(path, strict=True)
        if self._view_system(front_matter):
            raise ProjectServiceError("A system view cannot be deleted; it carries only UI state.", 403)
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        return self.list_views()

    def _system_view_node(self, view_id: str, ui: ViewUiState) -> ViewNode | None:
        """The in-memory node for an APP-DEFINED view id — the per-kind default
        (`view_default_<kind>`) or a curated builtin extra (`view_builtin_*`,
        #1682) — or None when the id is neither. The one dispatch read_view and
        the materializer share, so the two id families can't drift lifecycles."""
        if view_id.startswith(DEFAULT_VIEW_ID_PREFIX):
            return self._default_view_node(view_id, ui)
        if view_id.startswith(BUILTIN_VIEW_ID_PREFIX):
            return self._builtin_extra_view_node(view_id, ui)
        return None

    def _builtin_extra_view_node(self, view_id: str, ui: ViewUiState) -> ViewNode:
        """The in-memory node for a curated builtin extra view (#1682) — the
        `view_default_*` treatment applied to the extras a kind ships beside its
        default ("Runnable prompts", "Openable chats"). `system: true`
        (Duplicate-not-Edit). An unknown `view_builtin_*` id raises 422, so a
        bogus id never becomes a silent 200. A registered kind whose root
        entry_type doesn't resolve (a degenerate schema) falls back to
        `<kind>:base` — MIRRORING the frontend `kindUniverseExpr` fallback, so
        the rendering half and the persisting half fail (or don't) together."""
        registered = BUILTIN_EXTRA_VIEWS.get(view_id)
        if registered is None:
            raise ProjectServiceError(f"No builtin view is defined for id '{view_id}'.", 422)
        root_type = self._kind_root_entry_type(registered.kind) or f"{registered.kind}:base"
        return ViewNode(
            id=view_id,
            title=registered.title,
            revision="",
            entry_type="view:view",
            spec=self._builtin_extra_view_spec(view_id, root_type),
            layout=self._parse_view_layout(None),
            ui=ui,
            system=True,
            source_layer_id="",
            source_layer_label="",
        )

    @staticmethod
    def _builtin_extra_view_spec(view_id: str, root_type: str) -> ViewSpec:
        """The spec of a curated builtin extra (#1682). MUST stay in lockstep
        with the frontend `builtinViews.ts` (which synthesizes the same views
        for the pane switcher) — the golden fixture
        `builtin-extra-view-specs.json` is asserted by both suites, like the
        default-spec fixture. The registry entry carries the builder."""
        registered = BUILTIN_EXTRA_VIEWS.get(view_id)
        if registered is None:
            raise ProjectServiceError(f"No builtin view is defined for id '{view_id}'.", 422)
        return registered.build(ViewExpr(descendants_of=root_type))

    def _default_view_node(self, view_id: str, ui: ViewUiState) -> ViewNode:
        """The kind's honest in-memory default view for a `view_default_<kind>` id
        (ADR-0036 §5) — spec = the kind's default (ADR-0037 §7), no file required.
        Shared by read_view (an unmaterialized default → 200 with empty fold
        state, #1665) and _materialize_system_view (which persists it on the
        first fold). An unknown kind (no kind root) raises 422, so a genuinely
        bogus id never becomes a silent 200. `system: true` (Duplicate-not-Edit)."""
        kind = view_id[len(DEFAULT_VIEW_ID_PREFIX):]
        root_type = self._kind_root_entry_type(kind)
        if not root_type:
            raise ProjectServiceError(f"No default view is defined for kind '{kind}'.", 422)
        return ViewNode(
            id=view_id,
            title="Default",
            revision="",
            entry_type="view:view",
            spec=self._default_view_spec(kind, root_type),
            layout=self._parse_view_layout(None),
            ui=ui,
            system=True,
            source_layer_id="",
            source_layer_label="",
        )

    def _materialize_system_view(self, view_id: str, ui: ViewUiState) -> ViewNode:
        """Persist the read-only system view node for an app-defined id — the
        per-kind default (`view_default_<kind>`, ADR-0036 §5) or a builtin extra
        (`view_builtin_*`, #1682) — the in-memory node written to disk, so it is
        real-on-disk the moment the user first folds or restyles it. `system:
        true` (Duplicate-not-Edit; save_view rejects it); its spec matches the
        frontend synthesis (`defaultView` / `builtinViews`) so a later Duplicate
        starts from the real thing."""
        node = self._system_view_node(view_id, ui)
        if node is None:  # unreachable from update_view_ui's prefix guard
            raise ProjectServiceError(f"View {view_id} does not exist.", 404)
        root = self._require_project()
        (root / "views").mkdir(parents=True, exist_ok=True)
        self._write_view_file(
            self._filepath_for_new_node(root / "views", view_id),
            view_id,
            node.title,
            node.entry_type,
            node.spec,
            ui=ui,
            system=True,
        )
        return self.read_view(view_id)

    def _kind_root_entry_type(self, kind: str) -> str | None:
        """The kind's parentless root entry_type FQN — `<kind>:base` for the
        abstract-rooted kinds (lore/scene/research), or the single concrete type
        for the rest (assistant:assistant, chat:chat_session, …). Mirrors the
        frontend `kindRootEntryTypeId`; `descendants_of` this seeds the whole
        roster for the kind."""
        schema = self.read_metadata_schema()
        for fqn, definition in schema.entry_types.items():
            if definition.kind == kind and not definition.parent:
                return fqn
        return None

    @staticmethod
    def _default_view_spec(kind: str, root_type: str) -> ViewSpec:
        """The per-kind system default spec (ADR-0037 §7). Lore + Prompts group by
        entry_type (alphabetical labels); Assistants by curation state
        (Active/Unlisted) over a tag-parameterized roster; the structural kinds
        (scene/research)
        are a recursive containment Nest over the `parent` relation (roots =
        parentless); every other kind stays the plain whole-kind roster.

        MUST stay in lockstep with the frontend `defaultView` (evaluateView.ts) — the
        materialized default and the pane-synthesized one have to match. The golden
        test in test_views.py::test_default_view_specs_match_frontend guards the drift."""
        roster = ViewExpr(descendants_of=root_type)
        if kind in ("manuscript", "research"):
            return ViewSpec(
                kind=kind,
                expr=ViewExpr(
                    nest=NestOp(
                        # Roots = the roster narrowed to parent-unset, as a first-class
                        # Filter (ADR-0041 §C; #271 retired the bare-predicate-leaf form).
                        parents=ViewExpr(
                            filter=FilterOp(of=roster, pred=ViewExpr(field=FieldPredicate(key="parent", op="unset")))
                        ),
                        children=roster,
                        match=NestMatch(field="parent", direction="child_to_parent", by="ref"),
                        recursive=True,
                    )
                ),
            )
        if kind == "lore":
            return ViewSpec(kind=kind, expr=roster, group_by=[ViewGroupByLevel(field="entry_type", order="label")])
        if kind == "prompt":
            # The prompt shelf groups by DISPOSITION, not leaf entry_type (#951) —
            # what the prompt does to the document (five buckets), rather than one
            # bucket per sub-type. `disposition` is a resolver-stamped computed
            # field (#1684, `prompts.py::_prompt_computed_metadata`), so this spec
            # is honest everywhere, not just in the pane. Shelf order is the
            # field's declared option order, which the evaluator renders by
            # default for option-carrying fields (ADR-0037 Amendment 3) — it
            # replaced the retired frontend lift's rank pre-clustering, and it
            # holds for any persisted or duplicated copy of this spec too.
            return ViewSpec(kind=kind, expr=roster, group_by=[ViewGroupByLevel(field="disposition")])
        if kind == "assistant":
            # #333. Two changes, both consequences of #332 making priority ONE
            # merged sequence:
            #  - group on `listed`, not `source_layer`. Layer was structure only
            #    while layer *was* the ordering; now it would re-cluster the
            #    author's single dragged list by an accident of which folder each
            #    file sits in. Provenance survives as a row annotation.
            #  - born tag-scoped (ADR-0024): `assistant_tags` is the soft scope
            #    that decides which assistants are relevant (ADR-0082 §2 renamed
            #    the field off `tags`, which no built-in binds anymore). The
            #    formal ships UNBOUND, so the predicate is inactive and the pane
            #    opens on the whole roster (ADR-0031 §B) — nothing is decided for
            #    the author, the control is simply already there.
            # `field`-on-assistant_tags rather than the `tagged` leaf: identical
            # OR-over-tags semantics, but it stays designer-authorable and its
            # strip control resolves the real schema `assistant_tags` field, so a
            # duplicate of this view can be edited instead of being a one-way door.
            return ViewSpec(
                kind=kind,
                expr=ViewExpr(
                    filter=FilterOp(
                        of=roster,
                        pred=ViewExpr(field=FieldPredicate(key="assistant_tags", op="overlap", value={"var": "TAG"})),
                    )
                ),
                params=[ViewParam(name="TAG", label="Tag")],
                group_by=[ViewGroupByLevel(field="listed", show_empty=True)],
            )
        return ViewSpec(kind=kind, expr=roster)

    # ----- helpers --------------------------------------------------------

    def _write_view_file(
        self,
        path: Any,
        node_id: str,
        title: str,
        entry_type: str,
        spec: ViewSpec,
        layout: ViewLayout | None = None,
        ui: ViewUiState | None = None,
        system: bool = False,
    ) -> None:
        # exclude_none keeps the on-disk spec compact — a leaf serializes as
        # `{type: lore:character}`, not every unset ViewExpr slot.
        extra: dict[str, Any] = {"spec": spec.model_dump(exclude_none=True)}
        # Only write layout when the designer supplied one — keeps designer-less
        # / programmatic views clean (they fall back to auto-layout on open).
        if layout is not None:
            extra["layout"] = layout.model_dump(exclude_none=True)
        # Fold/ui state (ADR-0036) — only when it carries something: a collapsed
        # set OR a chosen appearance (ADR-0069). An all-empty ui drops cleanly, but
        # an appearance with no collapsed groups (the common case) must still write.
        if ui is not None and (ui.collapsed or ui.appearance):
            extra["ui"] = ui.model_dump(exclude_none=True)
        # `system` marks the read-only default view; only write it when true
        # (default False needs no on-disk footprint).
        if system:
            extra["system"] = True
        self._write_node_entry_file(
            path,
            node_id,
            title,
            entry_type,
            {},
            "",  # body-less: the spec lives in front matter, not a prose body
            extra=extra,
            omit_empty_metadata=True,
        )

    @staticmethod
    def _view_entry_type(front_matter: dict[str, Any]) -> str:
        raw = front_matter.get("entry_type") or "view:view"
        return raw if isinstance(raw, str) else "view:view"

    @staticmethod
    def _parse_view_spec(raw: Any) -> ViewSpec | None:
        from pydantic import ValidationError

        if not isinstance(raw, dict):
            return None
        try:
            return ViewSpec.model_validate(raw)
        except ValidationError:
            return None

    @staticmethod
    def _view_system(front_matter: dict[str, Any]) -> bool:
        return front_matter.get("system") is True

    @staticmethod
    def _parse_view_ui(raw: Any) -> ViewUiState | None:
        """Parse the optional fold/ui blob (ADR-0036). Stored verbatim; a
        malformed one is dropped (fold state is disposable) rather than failing
        the read. None ⇒ no persisted fold state (all groups expanded)."""
        from pydantic import ValidationError

        if not isinstance(raw, dict):
            return None
        try:
            return ViewUiState.model_validate(raw)
        except ValidationError:
            return None

    @staticmethod
    def _parse_view_layout(raw: Any) -> ViewLayout | None:
        """Parse the optional designer layout blob; a malformed one is dropped
        (the designer just auto-lays-out the expr) rather than failing the read."""
        from pydantic import ValidationError

        if not isinstance(raw, dict):
            return None
        try:
            return ViewLayout.model_validate(raw)
        except ValidationError:
            return None

