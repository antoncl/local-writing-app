"""Project lifecycle slice of ProjectService (#14 backend split).

Project-as-a-whole operations: scaffold a new project, read + update its
settings, browse the filesystem for the project/base-folder pickers, and
validate / repair the on-disk structure. `ProjectService` composes this mixin.

Nothing here mutates the service's scope any more (#399): a service arrives
bound to an immutable `WorkScope`, so the create/open *entry points* are
`ProjectService.created_at` / `.opened_at`, and what is left here — the
scaffold, the base-folder rebase — writes files under an already-bound root.

Method bodies moved verbatim. Shared tooling resolves through the MRO:
`self._require_project`, `self._read_yaml` / `self._write_yaml`,
`self._write_project_node_file`, `self._write_scene_file`,
`self._filepath_for_new_node`, `self._new_id`, the schema-layer helpers
(`_metadata_schema_base_folder`, `_validate_metadata_schema_definition`,
`read_metadata_schema`), and the validators / todo-anchor repair helpers
`validate_project`/`repair_project` lean on.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

from app.models import (
    AIPolicy,
    AncestorCandidate,
    DirectoryEntry,
    DirectoryListing,
    MetadataSchema,
    ProjectChainLayer,
    ProjectChild,
    ProjectInfo,
    ProjectNode,
    ProjectValidation,
    Scene,
    TodoItem,
    UpdateProjectSettingsRequest,
)
from app.services.migrations import CURRENT_VERSION as PROJECT_SCHEMA_VERSION
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import INHERITS_KEY, MANIFEST_FILENAME, LayerVisitor
from app.services.project.node_index import IndexLayer
from app.services.project.tree_configs import (
    MANUSCRIPT_TREE_CONFIG,
    RESEARCH_TREE_CONFIG,
)
from app.services.tree_structure import TreeStructureService


class _AIPolicyResolver(LayerVisitor):
    """Keeps the innermost layer's stated policy (#312).

    The walk runs outermost first, so "last statement seen" *is* "nearest
    explicit statement wins" — no comparison, no rank arithmetic, and no second
    notion of which end of the chain is near. A layer that states nothing leaves
    the answer alone; a chain where nobody states anything leaves the `off` it
    starts with, which is the fail-closed floor rather than a permissive
    default.

    A bespoke visitor rather than `collect_layers` + a comprehension because
    there is real per-layer work here (a manifest read); the reader is injected
    so the visitor stays a pure fold over the chain and the file access stays on
    the service — see `LayerCollector` for the other legitimate shape.
    """

    def __init__(self, stated: Callable[[Path], AIPolicy | None]) -> None:
        self._stated = stated
        self.policy: AIPolicy = "off"

    def visit_layer(self, layer: IndexLayer) -> None:
        stated = self._stated(layer.folder)
        if stated is not None:
            self.policy = stated


class ProjectLifecycleMixin:
    def _scaffold_new_project(self, title: str, inherits: list[str] | None = None) -> None:
        """Write a new project's files under this service's already-bound root.

        Creation used to resolve the root and then point the service at it, which
        made "which project is this service on?" an outcome of the call rather
        than an input to it (#399). The root now arrives with the service, so
        this only writes files; `ProjectService.created_at` is the entry point.

        No longer takes a base folder (#429): the bound is the machine root, so
        creating a project cannot set it. Passing one per create is what made
        every project record its own parent and every chain one hop long.

        The declaration is resolved **before the first mkdir** (#425). An
        explicit `inherits` naming a non-ancestor is a 422, and refusing it
        after the folder exists would leave a half-scaffolded project on disk
        for a request that never should have started writing.
        """
        root = self._require_project()
        declaration = self._declaration_for_new_project(root, inherits)
        root.parent.mkdir(parents=True, exist_ok=True)
        root.mkdir(parents=True, exist_ok=True)
        for folder in ["scenes", "lore", "prompts", ".cache"]:
            (root / folder).mkdir(exist_ok=True)
        (root / "research" / "notes").mkdir(parents=True, exist_ok=True)

        # Project node singleton — book metadata, blurb, etc. live here. It is
        # written BEFORE project.yaml: open_project gates on the manifest, so
        # a throw between the two must not leave a folder that opens forever
        # and 404s on its project node forever. This order fails the other way,
        # which is the recoverable one.
        self._write_project_node_file(root / "project.md", self._new_project_node(title))
        self._write_yaml(root / "project.yaml", self._new_project_manifest(title, declaration))
        self._write_yaml(root / "metadata.schema.yaml", self._empty_metadata_schema())
        self._write_yaml(root / "tags.yaml", {"tags": []})
        initial_scene = Scene(
            id=self._new_id("scene"),
            title="Untitled Scene",
            body="",
            revision="",
            status="draft",
            entry_type="scene:scene",
            metadata={},
        )
        self._write_scene_file(self._filepath_for_new_node(root / "scenes", initial_scene.title), initial_scene)
        # Seed the manuscript tree with one scene leaf so a fresh project
        # opens to something instead of an empty outline.
        TreeStructureService(root, MANUSCRIPT_TREE_CONFIG).initialize(
            leaf_node={
                "id": self._new_id("node"),
                "type": "scene:scene",
                "title": initial_scene.title,
                "scene_id": initial_scene.id,
                "children": [],
            },
        )
        # Research tree starts empty — no seeded topic or note. The
        # research pane / kind ships in a later slice; this just ensures
        # the file exists so validate_project doesn't flag it as missing.
        TreeStructureService(root, RESEARCH_TREE_CONFIG).initialize()
        self._write_yaml(root / "todo.yaml", {"items": []})

    def _declaration_for_new_project(self, root: Path, requested: list[str] | None) -> list[str]:
        """The `inherits` entries a project being created should start with (#425).

        **The default is every ancestor project**, not the nearest one. Under
        the non-transitive semantics that shipped (#309 / ADR-0039 Amendment 1,
        and #428 closed as YAGNI) only an explicit list produces a full chain,
        so nearest-only would leave `Universe › Series › Book` unreachable
        without a second gesture nobody knows to make — which is the defect
        this fixes. "Every ancestor project" is the shape the folder layout the
        author just chose already implies.

        Non-project ancestors are skipped rather than declared-and-warned:
        they carry no manifest, so they contribute nothing, and a default that
        seeds a warning is a default that is wrong.

        Both paths go through `_validated_declaration`, so there is one writer
        of the stored (project-relative) form, and an explicitly requested
        non-ancestor is refused here exactly as it is on a settings save.

        `ancestor_projects` rather than the declared walk, deliberately (#460):
        a project being created has no declaration to read, and reading for one
        anyway meant parsing the `project.yaml` the scaffold is about to
        overwrite — which turned a stale malformed file in the target folder
        into a 422 on create.
        """
        entries = requested if requested is not None else [
            str(folder) for folder in self.ancestor_projects(root)
        ]
        return self._validated_declaration(entries, root)

    def _new_project_manifest(self, title: str, inherits: list[str]) -> dict[str, Any]:
        """The manifest a fresh project starts with.

        No `projects_base_folder` (#429): the walk's bound is the machine root,
        so a project does not carry one. Writing it per project is what made
        every chain one hop long — the wizard passed the folder it had just
        built the project inside, so the bound was always the parent.

        `inherits` is written even when empty (#425). Absent and `[]` mean the
        same thing to the reader, so this costs nothing and makes the key
        present in every manifest the app writes — which is where a hand-editor
        looks for it, and the one place the flat case is otherwise invisible.

        **No `ai` block** (#312). It used to seed `policy: "off"` explicitly,
        which was harmless while the policy was read from one manifest and fatal
        the moment it resolves over the chain: every layer would state `off` at
        birth, so "this layer has no opinion" would not exist on disk and a book
        set to `cloud-allowed` under a universe still carrying its birth default
        could never be distinguished from one deliberately switched off. Absent
        now means *no opinion*, and a chain that states nothing anywhere still
        resolves to `off` — see `_resolved_ai_policy`. The default is unchanged;
        what changed is that it is no longer written down as a decision nobody
        made.
        """
        return {
            "title": title,
            "version": 1,
            "schema_version": PROJECT_SCHEMA_VERSION,
            INHERITS_KEY: inherits,
            "settings": {
                "theme": "system",
            },
            "manuscript_structure": {
                "container_types": [
                    {"type": "scene:act", "label": "Act"},
                    {"type": "scene:chapter", "label": "Chapter"},
                ]
            },
        }

    def _empty_metadata_schema(self) -> dict[str, Any]:
        return {"version": 1, "entry_types": {}, "fields": {}, "groups": {}}

    def _project_title(self, root: Path) -> str | None:
        """This project's title, from the manifest — the only place it lives.

        It used to be cached on the service and refreshed by whoever wrote it
        (`save_project_node`), which made it a second mutable field to keep in
        step with the scope (#399). `save_project_node` already syncs
        project.yaml, so reading it is both simpler and one fewer thing that can
        disagree with disk.
        """
        manifest = self._read_yaml(root / MANIFEST_FILENAME)
        title = manifest.get("title")
        return title.strip() if isinstance(title, str) and title.strip() else None

    def current_project(self) -> ProjectInfo:
        root = self._require_project()
        base_folder = self._metadata_schema_base_folder(root)
        return ProjectInfo(
            title=self._project_title(root) or root.name,
            root_path=str(root),
            # The machine root (#429), reported as `None` when none is set
            # rather than falling back to `root.parent`. That fallback was a
            # lie the moment the bound stopped being per project: the walk
            # returns no candidates without a root, so claiming the parent was
            # the bound described a chain that does not exist.
            projects_base_folder=str(base_folder) if base_folder else None,
            ai_policy=self._resolved_ai_policy(root),
            ancestors=self._ancestor_candidates_for_api(root),
            chain=self._project_chain_for_api(root),
            children=self._project_children(root),
        )

    def _project_chain_for_api(self, root: Path) -> list[ProjectChainLayer]:
        """The resolved chain, straight off the walker (#432).

        Deliberately `collect_layers` rather than a filter over the
        enumeration this method sits next to. The chain's membership rule
        (`declared and is_project, plus root`) and its naming rule (manifest
        title, else the "Base Folder" case, else the folder name) both live in
        `layers.py`, and re-applying either here would recreate exactly the
        duplication this exists to delete —
        `decisions_walker_visitor_uniformity`: every hierarchy walk goes
        through the walker, even a one-line one; optimise inside it, never
        bypass it.

        The machine layer is excluded (`include_machine` defaults False): it
        contributes assistants, carries no `metadata.schema.yaml`, and is not
        a project anyone can navigate to. `read_metadata_schema_layers` makes
        the same choice, which is why the two views agree by construction.
        """
        return [
            ProjectChainLayer(
                id=layer.id,
                label=layer.label,
                path=str(layer.folder),
                is_root=layer.is_root,
            )
            for layer in self.collect_layers(root)
        ]

    def ai_policy(self) -> AIPolicy:
        """Just the permission, without building the whole `ProjectInfo` (#433).

        Resolved over the layer chain since #312, so this is no longer a single
        manifest read — but it is still bounded by the chain, where
        `current_project()` scales with the whole shelf (every child project,
        every ancestor title). The saving #433 bought is smaller and still real;
        the read-count test below pins what it is now.

        `current_project()` is the app's most I/O-heavy read: the root manifest
        several times over, a stat of every folder between the base and the
        project, one open + `yaml.safe_load` per project ancestor for its title
        (#311), and an `iterdir()` plus a manifest parse per child project
        (#310). Measured on a three-level chain with three child projects, that
        is **11 file reads to answer "is AI on?"**; it grows with the depth of
        the chain and the number of books beside the one that is open, on paths
        that may be a network or OneDrive mount.

        ⚠ **Two of the five AI routes still pay it anyway.** `ai_generate`
        (`routers/ai.py:650`) and `ai_generate_stream` (`:898`) call
        `build_preview` *before* they reach here, and `build_preview` binds the
        whole `ProjectInfo` into the template context as `project` / `novel`
        (`services/ai/preview.py:180`). Narrowing that changes what a template
        can reach, which is #317's question, so it is deliberately not done
        here — but it means the saving lands on `ai_health`, `ai_chat` and
        `ai_chat_stream`, and those two routes pay one extra manifest read
        until the preview context is settled.

        The value itself is normalised by `_stated_ai_policy`, not here, so
        `current_project()` gets the same guarantee — see that method.

        `_require_project()` still raises when no project is open, deliberately:
        callers turn that into `"off"` too, and a silent `"off"` from here would
        be indistinguishable from a project that chose it.
        """
        return self._resolved_ai_policy(self._require_project())

    def _ancestor_candidates_for_api(self, root: Path) -> list[AncestorCandidate]:
        """The enumeration, outermost first — every ancestor folder, flagged.

        Not the declared subset: #311's switcher filters this down, while
        #318's wizard needs the *un*declared rows in order to offer them, and a
        non-project folder must be visible and marked rather than absent (an
        unexplained gap in the list reads as a defect, and its presence is a
        quiet warning that a folder up there is not what the author assumed).
        """
        return [
            AncestorCandidate(
                path=str(folder),
                name=folder.name,
                is_project=is_project,
                inherited=inherited,
                title=self._readable_project_title(folder) if is_project else None,
            )
            for folder, is_project, inherited in self.declared_ancestor_candidates(root)
        ]

    def _readable_project_title(self, folder: Path) -> str | None:
        """Another project's title, or None when its manifest cannot be read.

        A title is decoration on someone else's folder; the open project must not
        become unopenable because of it. Reading it *unguarded* is what made a
        malformed `project.yaml` two levels up return 422 from `GET /project` and
        `POST /project/open` — for a project whose own files are fine, and for an
        ancestor it may not even have declared. Worse, the five AI routes catch
        `ProjectServiceError` and fall back to `policy="off"`, so the same broken
        file silently turned AI off with nothing naming the cause.

        This is the same judgement `_project_children` already makes one method
        down, where `iterdir()` is wrapped because it reaches outside the project.
        This read reaches further out, so it needs the guard more, not less.
        `OSError` covers the Windows cases that motivated it: a manifest locked
        mid-write by another instance, an ACL-restricted shelf, an offline
        network or OneDrive path. `UnicodeDecodeError` covers a manifest saved as
        cp1252 by a hand editor — `_read_yaml` opens as utf-8 and only catches
        `yaml.YAMLError`.

        None here means "no title to show", which the breadcrumb already renders
        by falling back to the folder name. The folder still reports
        `is_project`, so nothing about the enumeration is falsified.

        This used to carry a warning that the same hole was still open one
        level down — `_layer_label_for_folder` read a declared ancestor's
        manifest unguarded during the layer walk, so a malformed one broke
        `_build_node_index` and `validate_project`, the very report that should
        have named it (#430). **That is closed**: the label now comes through
        this method, so there is one guarded cross-project title read rather
        than a guarded one and an unguarded one. `POST /project/validate`
        returns 200 and lists the problem, pinned by
        `test_a_malformed_ancestor_manifest_leaves_the_validation_report_readable`.

        What forced it was #432 putting `collect_layers` on `current_project()`:
        the unguarded read moved onto `POST /project/open`, so a broken manifest
        two levels up stopped the project below it opening at all. #430 stays
        open for the rest of its body — `validate_project` still builds the node
        index outside the `try` that would turn any *other* cause into a
        reported error.
        """
        try:
            return self._project_title(folder)
        except (ProjectServiceError, OSError, UnicodeDecodeError):
            return None

    def _project_children(self, root: Path) -> list[ProjectChild]:
        """Project folders directly inside this one, alphabetically.

        Direct children only — visibility is ancestor-only (ADR-0039), so a
        level shows its own children and never the whole shelf. Non-project
        subfolders are omitted here, unlike ancestors: a child roster is a list
        of places you can open, and `scenes/` is not one.
        """
        children: list[ProjectChild] = []
        try:
            entries = sorted(root.iterdir(), key=lambda path: path.name.lower())
        except OSError:
            return []
        for folder in entries:
            if not folder.is_dir() or not (folder / MANIFEST_FILENAME).exists():
                continue
            children.append(
                ProjectChild(
                    path=str(folder),
                    name=folder.name,
                    # Guarded for the same reason as the ancestor side, and by
                    # the same helper: a child's manifest is another folder's
                    # file, and an unreadable one must not 422 the open project.
                    # This read was unguarded (#310), so a malformed manifest in
                    # any direct subfolder took out `current_project()` — the
                    # exact mirror of the ancestor case, found by review of the
                    # ancestor fix. Reusing the helper also retires the second
                    # copy of the title-or-folder-name rule.
                    title=self._readable_project_title(folder) or folder.name,
                )
            )
        return children

    def update_project_settings(self, request: UpdateProjectSettingsRequest) -> ProjectInfo:
        root = self._require_project()
        manifest = self._read_yaml(root / "project.yaml")
        settings = manifest.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        ai_settings = settings.get("ai")
        if not isinstance(ai_settings, dict):
            ai_settings = {}
        # Partial update: a field left unset is left unchanged.
        if request.ai_policy is not None:
            ai_settings["policy"] = request.ai_policy
        if request.inherits is not None:
            # Validated against the machine root (#429). There is no pending
            # bound to pass any more: widening is a machine-settings change, so
            # it cannot arrive in the same request as a declaration — and it no
            # longer needs to, because widening it widens it for every project
            # at once rather than for this one.
            manifest[INHERITS_KEY] = self._validated_declaration(request.inherits, root)
        if ai_settings:
            settings["ai"] = ai_settings
        manifest["settings"] = settings
        self._write_yaml(root / "project.yaml", manifest)
        return self.current_project()

    def _validated_declaration(self, declared: list[str], root: Path) -> list[str]:
        """Turn a requested declaration into manifest entries, or refuse (#309).

        Refuses here rather than dropping-with-a-warning at read time, because
        the two cases are different: a **write** naming a non-ancestor is a
        caller error we can reject before it reaches disk, while a *stored*
        entry that stopped being an ancestor (a folder moved out from under it)
        is a state the reader must survive. Same rule, different obligation.

        Stored relative to the project so that moving or renaming the folder
        above it does not invalidate every book beneath.

        Took a pending `base` until #429, so that a settings update widening
        `projects_base_folder` and declaring a newly-eligible ancestor could be
        one request — the wizard's gesture. The bound is machine-level now, so
        widening is not part of any project's save and there is no pending
        value to validate against.
        """
        candidates = set(self.ancestor_projects(root))
        entries: list[str] = []
        for raw in declared:
            folder = Path(raw).expanduser()
            if not folder.is_absolute():
                folder = root / folder
            folder = folder.resolve()
            if folder not in candidates:
                raise ProjectServiceError(
                    f"{folder} is not an ancestor project within the base folder.", 422
                )
            entries.append(os.path.relpath(folder, root).replace("\\", "/"))
        return entries

    def _resolved_ai_policy(self, root: Path) -> AIPolicy:
        """The permission in force here, resolved over the layer chain (#312).

        **Nearest explicit statement wins, and a chain that states nothing is
        `off`.** An ancestor's policy is a *default* for everything beneath it,
        not a lock: a universe set to `cloud-allowed` lets its books use the
        model without each one saying so, and a book that says `off` is off
        regardless. Anton's call, recorded on #312 — "B, but overrideable".

        The rejected alternative was plain most-restrictive along the chain. It
        reads like `decisions_ai_permission_fails_closed`, but it fails closed
        on the *wrong* question: fail-closed is about a permission we cannot
        read, and an ancestor that deliberately says `off` is one we read
        perfectly well. Most-restrictive would also have made the feature
        unusable, because every project the app has ever created seeded
        `policy: "off"` into its own manifest, so every ancestor would have
        pinned every descendant off forever. `_new_project_manifest` no longer
        writes that block — which is what makes "no opinion" expressible at all.

        Fail-closed keeps the two places it belongs: an unreadable or
        unrecognised *value* is `off` (see `_stated_ai_policy`), and a chain
        with no statement anywhere resolves to `off` here rather than to some
        permissive default.

        Through `visit_layers`, not a private walk — the chain's membership rule
        is the declaration's, and a permission resolved over a second, slightly
        different notion of the chain is exactly the bug #432 records for the
        frontend's re-derivation (`decisions_walker_visitor_uniformity`).

        ⚠ Cost: one manifest read per chain layer, on top of the walk's own (the
        label rule reads each ancestor's manifest for its title). Both
        `current_project()` and `ai_policy()` pay it per call, and `ai_policy()`
        is on five AI routes. That is the same waste #466 records for
        `current_project()`'s double walk, one consumer further on; the fix is a
        memo over the walk, which belongs with #392/#466 and not here.
        """
        resolver = _AIPolicyResolver(self._stated_ai_policy)
        self.visit_layers(resolver, root)
        return resolver.policy

    def _stated_ai_policy(self, folder: Path) -> AIPolicy | None:
        """What one layer's manifest *says*, or `None` when it says nothing.

        Absent block, or a block without a `policy` key, is **no opinion** — the
        distinction the whole resolution rests on. It is deliberately not the
        same as `off`: nearest-explicit-wins can only mean anything if a layer
        can decline to have a view.

        Anything outside `AIPolicy` becomes `"off"`, including an explicit
        `policy: null` and a non-string — a stated-but-unreadable permission is
        one we do not have (`decisions_ai_permission_fails_closed`), and it is
        still a *statement*, so it also stops the search rather than deferring
        to an ancestor. The membership set is derived from the type rather than
        restated, so adding a policy to `AIPolicy` cannot silently start reading
        as "off" here.

        A manifest that cannot be read at all is `off` for the same reason,
        which is also what keeps a malformed ancestor from raising out of a
        walk driven by every AI route — the guard `_readable_project_title` and
        `_layer_label_for_folder` already apply to the title beside it (#430).
        A nearer layer still overrides it, so an unreadable *ancestor* cannot
        turn a book's own `cloud-allowed` off.

        This normalisation used to live in `_read_ai_settings`, which returned
        the whole `settings.ai` block; nothing ever read another key out of it.
        Guarding only the caller that noticed is what once let the two readers
        disagree: `ai_policy()` fell closed on a hand-edited
        `policy: cloud_allowed` while `current_project()` passed the raw string
        into `ProjectInfo`'s `AIPolicy` Literal, raising a Pydantic
        `ValidationError` that `translate_errors` does not catch. That escaped
        as a 500 from `GET /api/project` **and** `POST /api/project/open`, where
        it precedes `current_scope.set(...)` — so one mistyped character made
        the project unopenable, with an error naming nothing.
        """
        try:
            manifest = self._read_yaml(folder / MANIFEST_FILENAME)
        except Exception:
            return "off"
        settings = manifest.get("settings")
        if not isinstance(settings, dict):
            return None
        ai = settings.get("ai")
        if not isinstance(ai, dict) or "policy" not in ai:
            return None
        policy = ai["policy"]
        return policy if policy in get_args(AIPolicy) else "off"

    def list_directories(self, path: Path | None = None) -> DirectoryListing:
        target = (path or self._default_directory_picker_path()).expanduser().resolve()
        if not target.exists():
            raise ProjectServiceError("That folder does not exist.", 404)
        if not target.is_dir():
            raise ProjectServiceError("That path is not a folder.", 400)

        directories: list[DirectoryEntry] = []
        try:
            children = sorted(
                (child for child in target.iterdir() if child.is_dir()),
                key=lambda child: child.name.lower(),
            )
        except PermissionError as exc:
            raise ProjectServiceError("This folder cannot be opened.", 403) from exc

        for child in children:
            directories.append(DirectoryEntry(name=child.name, path=str(child)))

        parent = target.parent if target.parent != target else None
        return DirectoryListing(
            path=str(target),
            parent_path=str(parent) if parent else None,
            directories=directories,
        )

    def _default_directory_picker_path(self) -> Path:
        documents = Path.home() / "Documents"
        if documents.exists() and documents.is_dir():
            return documents
        return Path.home()

    def validate_project(self) -> ProjectValidation:
        root = self._require_project()
        warnings: list[str] = []
        errors: list[str] = []
        metadata_schema: MetadataSchema | None = None
        node_index = self._build_node_index(root)
        warnings.extend(node_index.warnings)
        errors.extend(node_index.errors)

        for required in [
            "project.yaml",
            # The project node singleton. Nothing back-fills it since #343
            # retired the v3 migration, so if it goes missing this report is
            # how it surfaces; repair_project recreates it.
            "project.md",
            "manuscript.structure.yaml",
            "research.structure.yaml",
            "todo.yaml",
        ]:
            if not (root / required).exists():
                errors.append(f"Missing {required}.")

        try:
            metadata_schema = self.read_metadata_schema()
            warnings.extend(self._metadata_schema_layer_warnings(root))
            # A declared ancestor that is no longer one — a folder moved, or a
            # typo. Dropped by the walk; surfaced here so it is not silent (#309).
            warnings.extend(self.declared_ancestor_warnings(root))
            errors.extend(self._validate_metadata_schema_definition(metadata_schema))
        except (ProjectServiceError, ValueError) as exc:
            errors.append(f"Invalid metadata schema: {exc}")

        scene_ids = {entry.id for entry in node_index.by_id.values() if entry.kind == "scene"}
        referenced = TreeStructureService.collect_leaf_ids(self.read_structure().root)

        for scene_id in sorted(referenced - scene_ids):
            errors.append(f"Structure references missing scene {scene_id}.")
        for scene_id in sorted(scene_ids - referenced):
            warnings.append(f"Scene {scene_id} is not in the manuscript structure.")
        for entry in sorted((entry for entry in node_index.by_id.values() if entry.kind == "scene"), key=lambda item: item.id):
            scene_id = entry.id
            path = entry.path
            try:
                front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
                entry_type = front_matter.get("entry_type", "scene:scene")
                if entry_type is not None and not isinstance(entry_type, str):
                    errors.append(f"Scene {scene_id} has invalid entry_type; it must be text.")
                    entry_type = "scene:scene"
                metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                status = str(front_matter.get("status") or "draft")
                if metadata_schema:
                    errors.extend(self._validate_scene_metadata(scene_id, str(entry_type or "scene:scene"), status, metadata, metadata_schema, node_index))
                    # Mutation-value issues are advisory (never block a save), so
                    # they surface as warnings, not errors.
                    warnings.extend(self._validate_scene_mutations(scene_id, body, metadata_schema, node_index))
            except ProjectServiceError as exc:
                errors.append(exc.message)

        for entry in sorted((entry for entry in node_index.by_id.values() if entry.kind == "lore"), key=lambda item: item.id):
            entry_id = entry.id
            path = entry.path
            try:
                front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
                entry_type = front_matter.get("entry_type", "lore:lore_note")
                if entry_type is not None and not isinstance(entry_type, str):
                    errors.append(f"Lore Entry {entry_id} has invalid entry_type; it must be text.")
                    entry_type = "lore:lore_note"
                metadata = self._normalise_metadata(front_matter.get("metadata"), path)
                if metadata_schema:
                    errors.extend(self._validate_lore_entry_metadata(entry_id, str(entry_type or "lore:lore_note"), metadata, metadata_schema, node_index))
            except ProjectServiceError as exc:
                errors.append(exc.message)

        todos = self.read_todos()
        todo_anchor_refs = {
            (item.scene_id, item.anchor_id)
            for item in todos.items
            if item.scene_id and item.anchor_id
        }
        anchors_by_scene = self._read_scene_todo_anchors(scene_ids)
        anchor_counts_by_scene = self._read_scene_todo_anchor_counts(scene_ids)

        for item in todos.items:
            label = f"TODO {item.id}"
            if item.scene_id and item.scene_id not in scene_ids:
                errors.append(f"{label} references missing scene {item.scene_id}.")
            if item.anchor_id and not item.scene_id:
                errors.append(f"{label} has anchor {item.anchor_id} but no scene.")
            if item.scene_id and item.anchor_id and item.anchor_id not in anchors_by_scene.get(item.scene_id, set()):
                errors.append(f"{label} references missing anchor {item.anchor_id} in scene {item.scene_id}.")

        for scene_id, anchors in anchors_by_scene.items():
            for anchor_id in sorted(anchors):
                if (scene_id, anchor_id) not in todo_anchor_refs:
                    warnings.append(f"Scene {scene_id} contains orphan TODO anchor {anchor_id}.")

        for scene_id, anchor_counts in anchor_counts_by_scene.items():
            for anchor_id, count in sorted(anchor_counts.items()):
                if count > 1:
                    errors.append(f"Scene {scene_id} contains duplicate TODO anchor {anchor_id}.")

        return ProjectValidation(
            valid=not errors,
            warnings=warnings,
            errors=errors,
            migrations_applied=list(self.last_migrations),
        )

    def _new_project_node(self, title: str) -> ProjectNode:
        return ProjectNode(
            id=self._new_id("project"),
            title=title,
            body="",
            entry_type="project:project",
            metadata={},
        )

    def _restore_project_node_file(self, root: Path) -> None:
        """Recreate project.md if it went missing.

        A read refuses rather than synthesize (#343), because an id invented on
        a read reaches no file. Repair is where inventing one is honest: it
        mints and persists, so every later read agrees. The title comes from
        project.yaml, which is all a fresh project node carries anyway.
        """
        path = root / "project.md"
        if path.exists():
            return
        manifest = self._read_yaml(root / "project.yaml") if (root / "project.yaml").exists() else {}
        title = str(manifest.get("title") or "Untitled Project")
        self._write_project_node_file(path, self._new_project_node(title))

    def repair_project(self) -> ProjectValidation:
        root = self._require_project()
        self._restore_project_node_file(root)
        node_index = self._build_node_index(root)
        scene_ids = {entry.id for entry in node_index.by_id.values() if entry.kind == "scene"}
        anchors_by_scene = self._read_scene_todo_anchors(scene_ids)
        todos = self.read_todos()

        kept_items: list[TodoItem] = []
        valid_anchor_refs: set[tuple[str, str]] = set()
        for item in todos.items:
            if item.scene_id and item.scene_id not in scene_ids:
                continue
            if item.anchor_id and not item.scene_id:
                continue
            if item.scene_id and item.anchor_id:
                if item.anchor_id not in anchors_by_scene.get(item.scene_id, set()):
                    continue
                valid_anchor_refs.add((item.scene_id, item.anchor_id))
            kept_items.append(item)

        if len(kept_items) != len(todos.items):
            todos.items = kept_items
            self._write_yaml(root / "todo.yaml", todos.model_dump())

        for scene_id, anchors in anchors_by_scene.items():
            orphan_anchor_ids = {
                anchor_id
                for anchor_id in anchors
                if (scene_id, anchor_id) not in valid_anchor_refs
            }
            if orphan_anchor_ids:
                self._remove_scene_anchor_comments(scene_id, orphan_anchor_ids)
            self._remove_duplicate_scene_anchor_comments(scene_id)

        return self.validate_project()
