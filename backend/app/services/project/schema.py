"""Metadata-schema slice of ProjectService (#14 backend split).

The layered metadata schema: read/merge the built-in DEFAULT_METADATA_SCHEMA
with every `metadata.schema.yaml` from the projects base folder down to the
open project, resolve inheritance, and expose definition CRUD for entry-types,
groups, and fields (per-layer writes). This mixin owns that subsystem;
`ProjectService` composes it.

Method bodies moved verbatim. Shared helpers they call live elsewhere on the
composed class and resolve through the MRO: `self._require_project`,
`self._read_yaml` / `self._write_yaml`, `self._read_markdown_with_front_matter`
/ `self._write_markdown_with_front_matter`, `self._node_id_for_path`,
`self._entry_markdown_paths` and `self._is_relative_to` (both kept in core:
the former is shared with the tags slice, the latter with project-open
validation). The instance-value validation helpers (`_validate_*_metadata`,
`_strip_unknown_metadata_fields`) also stay in core — they are the
metadata-value subsystem, not schema-definition CRUD.
"""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.models import (
    LIST_ITEM_SCALAR_TYPES,
    DeleteMetadataEntryTypeRequest,
    DeleteMetadataFieldRequest,
    EntryTypeDefinition,
    MetadataDefinitionSource,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataSchemaLayer,
    MetadataSchemaLayers,
    MetadataSchemaOverview,
    MoveMetadataFieldRequest,
    RenameMetadataFieldRequest,
    SetFieldOrderRequest,
    SetFieldOverrideRequest,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project import schema_cache
from app.services.project.default_schema import (
    AUTHORABLE_COMPUTED_FUNCTIONS,
    DEFAULT_METADATA_SCHEMA,
    INTRINSIC_FIELD_KEYS,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import SCHEMA_FILENAME
from app.services.project.node_index import IndexLayer
from app.services.project.schema_validation import validate_prompt_output

# Entry-type identity is the kind-qualified FQN `kind:key` (#77). The key may nest
# (`kind:seg:seg…`, e.g. `prompt:revise:scene`) — the extra colons are a pure naming
# separator with no tie to the `parent:` chain (#600). The kind is always the first
# segment (group 1); each segment starts with a letter, then letters/digits/underscores.
_ENTRY_TYPE_FQN_RE = re.compile(r"([a-z][a-z0-9_]*):([A-Za-z][A-Za-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)*)")


def _entry_type_ancestry(
    entry_types: dict[str, EntryTypeDefinition], entry_type_id: str
) -> list[str]:
    """Walk the `parent:` chain of an entry_type FQN: the type itself, then each
    ancestor, nearest first. Unknown ids resolve to just themselves. Cycle-safe
    (schema CRUD already rejects self-parent, but a `seen` guard keeps this total).

    The single canonical answer to "is X a kind-of Y" — the backend `is_a` Jinja
    helper resolves membership against this chain, and the frontend view
    `descendants_of` leaf walks the same `parent:` links in the schema payload
    (ADR-0026). Built once here, not duplicated per consumer."""
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = entry_type_id
    while isinstance(current, str) and current not in seen:
        chain.append(current)
        seen.add(current)
        definition = entry_types.get(current)
        current = definition.parent if definition is not None else None
    return chain


def _schema_layer_from(layer: IndexLayer) -> MetadataSchemaLayer:
    """The API-facing twin of `IndexLayer`.

    Used to run its own `enumerate` over the chain, re-deriving id and label
    with the same rules the index build used; now it reads them off the walk.
    """
    schema_path = layer.folder / SCHEMA_FILENAME
    return MetadataSchemaLayer(
        id=layer.id,
        label=layer.label,
        folder_path=str(layer.folder),
        schema_path=str(schema_path),
        exists=schema_path.exists(),
    )


class MetadataSchemaMixin:
    def read_metadata_schema(
        self, root: Path | None = None, *, up_to_layer_id: str | None = None
    ) -> MetadataSchema:
        """The merged schema for `root`, defaulting to the open project.

        `root` is explicit for callers that must not straddle a concurrent
        `open_project` (#381): `ProjectService` is a process-global singleton
        whose `root_path` mutates in place, so an operation that resolves the
        project more than once can read one project's schema against another's
        files.

        `up_to_layer_id` resolves the schema **as of** authoring layer L
        (ADR-0042 §3, #393): the merge stops at L, so a field a more-local
        layer defines is absent — the roster can only shrink as L rises towards
        the base, never offer a field the target layer cannot store. `None`,
        the default, merges the whole chain to the open project, which is what
        every resolution-scope read wants and gets unchanged; only the write
        path passes L, via `_schema_as_authored`.

        **The result is a shared, cached instance (#394) — treat it as
        read-only.** The resolved-definitions cache returns the same object to
        every caller of a given chain, so mutating it (or a nested `entry_types`
        / `fields` member) corrupts it for all of them. `MetadataSchema` is
        frozen against top-level reassignment; the nested collections rely on
        this contract. To change definitions, write a layer (the schema-CRUD
        methods), which reads YAML directly and never mutates this result.
        """
        root = root or self._require_project()
        paths = self._metadata_schema_layer_paths(root, up_to_layer_id=up_to_layer_id)
        # The resolved-definitions cache (#394) — one door, so the index build,
        # the as-of-L authoring reads, and every endpoint here share one merged
        # artefact rather than each re-parsing the chain. `paths` is the chain
        # identity (already truncated for as-of-L); the cache stamps it with the
        # layer fingerprints + `build_identity()` and folds only on a miss.
        return schema_cache.resolved_schema(paths, self._build_metadata_schema)

    def _build_metadata_schema(
        self, paths: list[Path], fingerprints: list[schema_cache.Fingerprint]
    ) -> MetadataSchema:
        """Fold the chain into a validated schema — the cache's rebuild path.

        Runs only on a merged-cache miss. Each existing layer's parse is served
        from the per-layer atom cache (no YAML re-parse for an unchanged file),
        and copied on loan: `_merge_metadata_schema_layer` aliases layer values
        into its output (`schema.py` `_merge_metadata_schema_section`), so the
        shared atom must not reach the mutating fold uncopied — this preserves
        the fresh-dict-per-build semantics the pre-cache code had for free.
        """
        data = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path, fp in zip(paths, fingerprints, strict=True):
            if fp is None:  # no schema file at this layer — a stored value, not a miss
                continue
            layer_data = schema_cache.layer_parse(path, fp, self._read_metadata_schema_layer)
            self._merge_metadata_schema_layer(data, deepcopy(layer_data))
        data = self._resolve_metadata_schema_inheritance(data)
        return MetadataSchema.model_validate(data)

    def _schema_as_authored(
        self, root: Path | None = None, *, authoring_layer: Path | None = None
    ) -> MetadataSchema:
        """The schema a write in this unit must validate against (#393).

        ADR-0042 binds a write to an authoring layer L; the field roster it may
        use is the schema resolved base → L, never the fuller resolution-scope
        schema. Validating a write against a chain deeper than its own target
        would accept a field the target layer cannot store, and fail only
        later, when a sibling book reads it (ADR-0045 §4).

        L is supplied one of two ways. `#314`'s lore save passes `authoring_layer`
        explicitly — the save *is* ADR-0042's edit unit, so L rides its request
        body (the rail picker's write target) rather than an ambient header.
        Absent that, it falls back to the immutable `WorkScope`
        (`scope.authoring_layer`), which defaults to the resolution scope — so a
        unit with no rail picker behind it resolves the whole chain, exactly as
        before.
        """
        layer = authoring_layer if authoring_layer is not None else self._scope_authoring_layer()
        up_to_layer_id = (
            self._metadata_schema_layer_id(layer.resolve()) if layer is not None else None
        )
        # `root` (defaulted inside `read_metadata_schema`) is the resolution
        # scope; `up_to_layer_id` truncates it to L.
        return self.read_metadata_schema(root, up_to_layer_id=up_to_layer_id)

    def _scope_authoring_layer(self) -> Path | None:
        scope = self.scope
        return scope.authoring_layer if scope is not None else None

    def entry_type_ancestry(
        self,
        entry_type_id: str,
        *,
        schema: MetadataSchema | None = None,
    ) -> list[str]:
        """The inheritance chain of an entry_type FQN (self first, then ancestors
        via `parent:`). Pass `schema` to reuse an already-read schema on a hot
        path (the AI template render); otherwise it reads the effective schema.
        The shared ancestry primitive behind the `is_a` helper (ADR-0026)."""
        if schema is None:
            schema = self.read_metadata_schema()
        return _entry_type_ancestry(schema.entry_types, entry_type_id)

    def read_metadata_schema_layers(self) -> MetadataSchemaLayers:
        root = self._require_project()
        return MetadataSchemaLayers(
            layers=[_schema_layer_from(layer) for layer in self.collect_layers(root)]
        )

    def read_metadata_schema_overview(self) -> MetadataSchemaOverview:
        root = self._require_project()
        data = deepcopy(DEFAULT_METADATA_SCHEMA)
        built_in_source = MetadataDefinitionSource(
            layer_id="built_in",
            layer_label="Built-in",
            built_in=True,
        )
        entry_type_sources = dict.fromkeys(data.get("entry_types", {}), built_in_source)
        field_sources = dict.fromkeys(data.get("fields", {}), built_in_source)
        layers = self.read_metadata_schema_layers().layers
        layers_by_path = {Path(layer.schema_path): layer for layer in layers}

        for path in self._metadata_schema_layer_paths(root):
            if not path.exists():
                continue
            layer_data = self._read_metadata_schema_layer(path)
            self._merge_metadata_schema_layer(data, layer_data)
            layer = layers_by_path.get(path)
            if not layer:
                continue
            source = MetadataDefinitionSource(
                layer_id=layer.id,
                layer_label=layer.label,
                schema_path=layer.schema_path,
            )
            layer_entry_types = layer_data.get("entry_types") if isinstance(layer_data.get("entry_types"), dict) else {}
            for entry_type_id, layer_type_data in layer_entry_types.items():
                if self._layer_overrides_entry_type(layer_type_data):
                    entry_type_sources[entry_type_id] = source
                else:
                    entry_type_sources.setdefault(entry_type_id, source)
            for field_id in self._schema_section_keys(layer_data, "fields"):
                field_sources[field_id] = source

        data = self._resolve_metadata_schema_inheritance(data)
        return MetadataSchemaOverview(
            effective_schema=MetadataSchema.model_validate(data),
            layers=layers,
            entry_type_sources=entry_type_sources,
            field_sources=field_sources,
        )

    def upsert_metadata_entry_type(self, request: UpsertMetadataEntryTypeRequest) -> MetadataSchema:
        root = self._require_project()
        layer_path = self._metadata_schema_layer_path_for_id(root, request.layer_id)
        if layer_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        entry_type_id = request.entry_type_id.strip()
        if request.entry_type.kind not in {
            "scene", "lore", "prompt", "assistant", "project", "chat", "mutation_set", "view", "plot"
        }:
            raise ProjectServiceError(
                "Node type kind must be scene, lore, prompt, assistant, project, chat, mutation_set, view, or plot.",
                422,
            )
        # Entry-type identity is the kind-qualified FQN `kind:key` (#77): that
        # FQN is the dict key, the stored id, and the value written into a
        # node's `entry_type` front matter. Accept either the full FQN or a
        # bare local key (qualified here with the declared kind) so callers may
        # send either; the local part is the stable machine handle.
        fqn = entry_type_id if ":" in entry_type_id else f"{request.entry_type.kind}:{entry_type_id}"
        match = _ENTRY_TYPE_FQN_RE.fullmatch(fqn)
        if not match:
            raise ProjectServiceError(
                "Node type ID must be `kind:key` (the key may nest as `kind:key:subkey`), where each "
                "segment starts with a letter and contains only letters, numbers, and underscores.",
                422,
            )
        if match.group(1) != request.entry_type.kind:
            raise ProjectServiceError(
                f"Node type id kind prefix '{match.group(1)}' must match the node kind '{request.entry_type.kind}'.",
                422,
            )
        entry_type_id = fqn
        if request.entry_type.prompt is not None and request.entry_type.kind != "prompt":
            raise ProjectServiceError("Prompt configuration is only valid on prompt node types.", 422)
        if request.entry_type.parent == entry_type_id:
            raise ProjectServiceError("Node type cannot inherit from itself.", 422)

        schema = self.read_metadata_schema()
        if not request.allow_existing and entry_type_id in schema.entry_types:
            raise ProjectServiceError(f"Node type {entry_type_id} already exists.", 422)

        overview = self.read_metadata_schema_overview()
        source = overview.entry_type_sources.get(entry_type_id)
        # ADR-0029 §A: a layer may EXTEND/OVERLAY a built-in type — the guard is
        # narrowed from a blanket wall to blocking only DECLARATION rewrites.
        # A built-in write persists overlay-safe data (fields it extends, color,
        # body/display settings, group applications, field overrides); the
        # shipped `name`/`kind`/`parent`/`abstract` declaration is stripped
        # before write (below), so the built-in can never be forked.
        entry_type_built_in = bool(source and source.built_in)

        layer_data = self._read_yaml(layer_path) if layer_path.exists() else self._empty_metadata_schema()
        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            entry_types = {}

        existing_entry_type = entry_types.get(entry_type_id)
        existing_fields = existing_entry_type.get("fields") if isinstance(existing_entry_type, dict) else None
        fields = existing_fields if isinstance(existing_fields, list) else request.entry_type.fields
        # Preserve existing group applications when the caller (e.g. the type
        # editor's Save Type) doesn't carry them — they're managed via the
        # dedicated set_entry_type_group_applications path, like `fields`.
        existing_applications = (
            existing_entry_type.get("group_applications") if isinstance(existing_entry_type, dict) else None
        )
        # Persist ONLY the fields the caller actually set — `model_dump(exclude_unset=True)`.
        # Pydantic defaults like `body_editor="wysiwyg"` would otherwise leak onto disk and
        # override the inherited values from a parent type (e.g. a `prompt` sub-type would
        # end up with body_editor=wysiwyg pinned in the layer file, masking the parent's
        # code/jinja2). Inheritance fills in absent fields on read.
        entry_type_data = request.entry_type.model_dump(exclude_unset=True, exclude_none=True)
        entry_type_data.pop("own_fields", None)
        entry_type_data["name"] = request.entry_type.name.strip() or entry_type_id
        entry_type_data["kind"] = request.entry_type.kind
        entry_type_data["abstract"] = bool(request.entry_type.abstract)
        entry_type_data["fields"] = fields
        if isinstance(existing_applications, list) and "group_applications" not in entry_type_data:
            entry_type_data["group_applications"] = deepcopy(existing_applications)
        if not request.entry_type.parent:
            entry_type_data.pop("parent", None)
        if request.entry_type.prompt is None and isinstance(existing_entry_type, dict):
            existing_prompt = existing_entry_type.get("prompt")
            if isinstance(existing_prompt, dict):
                entry_type_data["prompt"] = deepcopy(existing_prompt)
        if entry_type_built_in:
            # Overlay-only for a built-in (ADR-0029 §A): never persist the
            # shipped declaration — `name`/`kind`/`parent`/`abstract` stay
            # inherited from the built-in. Membership keeps only the fields
            # that EXTEND the built-in, so inherited/intrinsic keys aren't
            # pinned literally into the layer (the resolver re-injects them).
            for declaration_key in ("name", "kind", "parent", "abstract"):
                entry_type_data.pop(declaration_key, None)
            builtin_members = set(schema.entry_types[entry_type_id].fields)
            entry_type_data["fields"] = [
                field for field in entry_type_data.get("fields", []) if field not in builtin_members
            ]
        # Don't leave a source-flipping stub for a built-in: if the overlay
        # carries nothing but an empty membership, drop the entry rather than
        # writing `<type>: {}` (which would report the built-in as
        # layer-sourced) — same reasoning as `set_metadata_field_override`.
        if entry_type_built_in and not entry_type_data.get("fields") and not (
            set(entry_type_data) - {"fields"}
        ):
            entry_types.pop(entry_type_id, None)
        else:
            entry_types[entry_type_id] = entry_type_data
        layer_data["entry_types"] = entry_types

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == layer_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        schema_errors = self._validate_metadata_schema_definition(
            MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
        )
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(layer_path, layer_data)
        return self.read_metadata_schema()

    def delete_metadata_entry_type(self, request: DeleteMetadataEntryTypeRequest) -> MetadataSchema:
        root = self._require_project()
        entry_type_id = request.entry_type_id.strip()
        schema = self.read_metadata_schema()
        if entry_type_id not in schema.entry_types:
            raise ProjectServiceError(f"Unknown node type {entry_type_id}.", 404)
        if self._entry_type_in_use(root, entry_type_id):
            raise ProjectServiceError(f"Node type {entry_type_id} is used by project documents.", 422)

        overview = self.read_metadata_schema_overview()
        source = overview.entry_type_sources.get(entry_type_id)
        if source is None:
            raise ProjectServiceError(f"Unknown node type {entry_type_id}.", 404)
        if source.built_in:
            raise ProjectServiceError("System node types cannot be deleted.", 422)
        source_path = self._metadata_schema_layer_path_for_id(root, source.layer_id)
        if source_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        layer_data = self._read_yaml(source_path) if source_path.exists() else self._empty_metadata_schema()
        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict) or entry_type_id not in entry_types:
            raise ProjectServiceError(f"Node type {entry_type_id} is not defined in its source layer.", 422)
        entry_types.pop(entry_type_id)
        layer_data["entry_types"] = entry_types

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == source_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        schema_errors = self._validate_metadata_schema_definition(
            MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
        )
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(source_path, layer_data)
        return self.read_metadata_schema()

    def _validate_candidate_schema(self, root: Path, layer_path: Path, layer_data: dict[str, Any]) -> None:
        """Merge all layers (substituting `layer_data` for `layer_path`),
        resolve, validate, and raise on any errors. Shared by the schema
        write paths."""
        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == layer_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        schema_errors = self._validate_metadata_schema_definition(
            MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
        )
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

    # Reusable-group CRUD (upsert/delete/applications) lives in
    # `schema_groups.MetadataSchemaGroupsMixin` — split out at the size gate
    # (#698); same MRO composition, same helpers.

    def set_entry_type_field_order(self, request: SetFieldOrderRequest) -> MetadataSchema:
        root = self._require_project()
        layer_path = self._metadata_schema_layer_path_for_id(root, request.layer_id)
        if layer_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)
        entry_type_id = request.entry_type_id.strip()
        schema = self.read_metadata_schema()
        definition = schema.entry_types.get(entry_type_id)
        if definition is None:
            raise ProjectServiceError(f"Unknown node type {entry_type_id}.", 404)
        # No built-in guard (ADR-0029 §A): display order is a pure per-layer
        # overlay that never rewrites the built-in declaration — same reasoning
        # as `set_metadata_field_override`.
        # Display order references the type's resolved membership (own +
        # inherited + generated). It may be a subset — listed fields lead in this
        # sequence, the rest trail in resolved order (#89) — but every id must be
        # a real member and there are no duplicates.
        members = set(definition.fields)
        if len(set(request.field_order)) != len(request.field_order) or any(
            fid not in members for fid in request.field_order
        ):
            raise ProjectServiceError("Field order must reference the type's fields without duplicates.", 422)
        layer_data = self._read_yaml(layer_path) if layer_path.exists() else self._empty_metadata_schema()
        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            entry_types = {}
        entry_type_data = entry_types.get(entry_type_id)
        if not isinstance(entry_type_data, dict):
            # A type whose fields are all inherited has no own definition at this
            # layer; still allow storing a local display-order override.
            entry_type_data = {}
        # Membership is untouched (parent ∪ own_fields); this is a pure ordering
        # overlay, so inherited fields become locally reorderable (#89).
        entry_type_data["display_order"] = list(request.field_order)
        entry_types[entry_type_id] = entry_type_data
        layer_data["entry_types"] = entry_types
        self._validate_candidate_schema(root, layer_path, layer_data)
        self._write_yaml(layer_path, layer_data)
        return self.read_metadata_schema()

    def set_metadata_field_override(self, request: SetFieldOverrideRequest) -> MetadataSchema:
        """Set / clear a per-type field presentation override (#116): relabel or
        hide a field this type carries (own or inherited) without touching the
        shared field def. Pure-presentation overlay on the layer, parallel to
        `display_order`; the request is the field's COMPLETE desired overlay at
        this layer (empty aspects clear, an empty overlay drops the entry).
        `hidden: false` is meaningful — it un-hides a field the def hides by
        default (e.g. `id`)."""
        root = self._require_project()
        layer_path = self._metadata_schema_layer_path_for_id(root, request.layer_id)
        if layer_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)
        entry_type_id = request.entry_type_id.strip()
        schema = self.read_metadata_schema()
        definition = schema.entry_types.get(entry_type_id)
        if definition is None:
            raise ProjectServiceError(f"Unknown node type {entry_type_id}.", 404)
        # No built-in guard here (unlike type-definition CRUD): a field override
        # is a pure presentation overlay written to the user's layer and never
        # mutates the built-in type. Relabelling / hiding a field on a built-in
        # type (e.g. `title` → "Name" on lore:character) is the core use case.
        field_key = request.field_key.strip()
        if field_key not in set(definition.fields):
            raise ProjectServiceError(
                f"Field {field_key} is not defined for entry_type {entry_type_id}.", 422
            )
        label = request.label.strip() if isinstance(request.label, str) else None
        overlay: dict[str, Any] = {}
        if label:
            overlay["label"] = label
        if request.hidden is not None:
            overlay["hidden"] = bool(request.hidden)

        layer_data = self._read_yaml(layer_path) if layer_path.exists() else self._empty_metadata_schema()
        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            entry_types = {}
        entry_type_data = entry_types.get(entry_type_id)
        if not isinstance(entry_type_data, dict):
            entry_type_data = {}
        overrides = entry_type_data.get("field_overrides")
        if not isinstance(overrides, dict):
            overrides = {}
        if overlay:
            overrides[field_key] = overlay
        else:
            overrides.pop(field_key, None)
        if overrides:
            entry_type_data["field_overrides"] = overrides
        else:
            entry_type_data.pop("field_overrides", None)
        # Don't leave an orphaned empty stub: clearing the last override on a
        # type that has no other local definition would otherwise write
        # `<type>: {}` to the layer — cruft that also flips a built-in type's
        # source to this layer (making it look user-defined). Drop the entry.
        if entry_type_data:
            entry_types[entry_type_id] = entry_type_data
        else:
            entry_types.pop(entry_type_id, None)
        layer_data["entry_types"] = entry_types
        self._validate_candidate_schema(root, layer_path, layer_data)
        self._write_yaml(layer_path, layer_data)
        return self.read_metadata_schema()

    def upsert_metadata_field(self, request: UpsertMetadataFieldRequest) -> MetadataSchema:
        root = self._require_project()
        layer_path = self._metadata_schema_layer_path_for_id(root, request.layer_id)
        if layer_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        field_id = request.field_id.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", field_id):
            raise ProjectServiceError("Metadata field ID must start with a letter and contain only letters, numbers, and underscores.", 422)
        if request.field.type == "computed":
            spec = request.field.computed or {}
            function = spec.get("function")
            # Deliberately the AUTHORABLE subset, not every known function: the
            # built-in ones are resolver-supplied and meaningless on a type the
            # resolver never visits, so offering them here would mint fields
            # that are silently always empty.
            if function not in AUTHORABLE_COMPUTED_FUNCTIONS:
                raise ProjectServiceError(
                    "Computed fields must use a supported function "
                    f"({', '.join(AUTHORABLE_COMPUTED_FUNCTIONS)}).",
                    422,
                )
            if function == "counter" and spec.get("scope", "siblings") not in ("siblings", "manuscript"):
                raise ProjectServiceError(
                    "Counter scope must be 'siblings' or 'manuscript'.",
                    422,
                )

        if request.field.type == "list" and request.field.item_group:
            # #698 × ADR-0045: the item shape must be visible AT OR ABOVE the
            # target layer. Validating against the full merged chain would
            # accept a group defined in a deeper sibling-invisible layer —
            # every sibling project inheriting this layer would then resolve
            # the field with no shape and 422 on all saves.
            visible_groups = self._read_metadata_schema_through_path(root, layer_path).groups
            if request.field.item_group not in visible_groups:
                raise ProjectServiceError(
                    f"Group {request.field.item_group} is not defined at or above this layer; "
                    "define the group there first, or author the field in the layer that owns it.",
                    422,
                )

        existing_field = self.read_metadata_schema().fields.get(field_id)
        if existing_field is not None and not request.allow_existing:
            raise ProjectServiceError(f"Metadata field {field_id} already exists.", 422)
        layer_data = self._read_yaml(layer_path) if layer_path.exists() else self._empty_metadata_schema()
        fields = layer_data.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        fields[field_id] = request.field.model_dump(
            exclude_none=True, exclude={"category", "group_origin", "item_members", "item_scalar"}
        )
        layer_data["fields"] = fields

        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            entry_types = {}
        entry_type_data = entry_types.get(request.entry_type)
        if not isinstance(entry_type_data, dict):
            effective_entry_type = self._read_metadata_schema_through_path(root, layer_path).entry_types.get(request.entry_type)
            if effective_entry_type is not None:
                entry_type_data = {"fields": []}
            else:
                entry_type_data = {
                    "name": request.entry_type,
                    "kind": "scene",
                    "fields": [],
                }
        fields_list = entry_type_data.get("fields")
        if not isinstance(fields_list, list):
            fields_list = []
        if field_id not in fields_list:
            fields_list.append(field_id)
        entry_type_data["fields"] = fields_list
        entry_types[request.entry_type] = entry_type_data
        layer_data["entry_types"] = entry_types

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == layer_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        schema = MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
        schema_errors = self._validate_metadata_schema_definition(schema)
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(layer_path, layer_data)
        if existing_field is not None:
            self._apply_option_value_changes(
                root, field_id, existing_field, request.field, request.option_migration
            )
        return self.read_metadata_schema()

    def move_metadata_field(self, request: MoveMetadataFieldRequest) -> MetadataSchema:
        root = self._require_project()
        target_path = self._metadata_schema_layer_path_for_id(root, request.target_layer_id)
        if target_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        field_id = request.field_id.strip()
        schema = self.read_metadata_schema()
        field = schema.fields.get(field_id)
        if field is None:
            raise ProjectServiceError(f"Unknown metadata field {field_id}.", 404)

        overview = self.read_metadata_schema_overview()
        source = overview.field_sources.get(field_id)
        if source is None:
            raise ProjectServiceError(f"Unknown metadata field {field_id}.", 404)
        if source.built_in:
            raise ProjectServiceError("System metadata fields cannot be moved.", 422)

        source_path = self._metadata_schema_layer_path_for_id(root, source.layer_id)
        if source_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)
        if source_path == target_path:
            return schema

        if field.type == "list" and field.item_group:
            # Same at-or-above rule as upsert (#698 × ADR-0045): the candidate
            # validation below merges the WHOLE chain, so it cannot see that a
            # move above the group's layer strands every sibling project.
            visible_groups = self._read_metadata_schema_through_path(root, target_path).groups
            if field.item_group not in visible_groups:
                raise ProjectServiceError(
                    f"Group {field.item_group} is not defined at or above the target layer; "
                    "move the group first, or keep the field in the layer that can see it.",
                    422,
                )

        source_data = self._read_yaml(source_path) if source_path.exists() else self._empty_metadata_schema()
        target_data = self._read_yaml(target_path) if target_path.exists() else self._empty_metadata_schema()
        self._remove_metadata_field_from_layer(source_data, field_id, request.entry_type)
        self._add_metadata_field_to_layer(root, target_path, target_data, field_id, field, request.entry_type)

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == source_path:
                self._merge_metadata_schema_layer(candidate, source_data)
            elif path == target_path:
                self._merge_metadata_schema_layer(candidate, target_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        moved_schema = MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
        schema_errors = self._validate_metadata_schema_definition(moved_schema)
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(source_path, source_data)
        self._write_yaml(target_path, target_data)
        return self.read_metadata_schema()

    def rename_metadata_field(self, request: RenameMetadataFieldRequest) -> MetadataSchema:
        root = self._require_project()
        old_field_id = request.old_field_id.strip()
        new_field_id = request.new_field_id.strip()
        if old_field_id == new_field_id:
            return self.read_metadata_schema()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", new_field_id):
            raise ProjectServiceError("Metadata field ID must start with a letter and contain only letters, numbers, and underscores.", 422)

        schema = self.read_metadata_schema()
        if old_field_id not in schema.fields:
            raise ProjectServiceError(f"Unknown metadata field {old_field_id}.", 404)
        if new_field_id in schema.fields:
            raise ProjectServiceError(f"Metadata field {new_field_id} already exists.", 422)

        overview = self.read_metadata_schema_overview()
        source = overview.field_sources.get(old_field_id)
        if source is None:
            raise ProjectServiceError(f"Unknown metadata field {old_field_id}.", 404)
        if source.built_in:
            raise ProjectServiceError("System metadata fields cannot be renamed.", 422)
        source_path = self._metadata_schema_layer_path_for_id(root, source.layer_id)
        if source_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        layer_data = self._read_yaml(source_path) if source_path.exists() else self._empty_metadata_schema()
        fields = layer_data.get("fields")
        if not isinstance(fields, dict) or old_field_id not in fields:
            raise ProjectServiceError(f"Metadata field {old_field_id} is not defined in its source layer.", 422)
        fields[new_field_id] = fields.pop(old_field_id)
        self._replace_metadata_field_reference_in_layer(layer_data, old_field_id, new_field_id, request.entry_type)

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == source_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        renamed_schema = MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
        schema_errors = self._validate_metadata_schema_definition(renamed_schema)
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(source_path, layer_data)
        self._rename_entry_metadata_key(root, old_field_id, new_field_id)
        return self.read_metadata_schema()

    def delete_metadata_field(self, request: DeleteMetadataFieldRequest) -> MetadataSchema:
        root = self._require_project()
        field_id = request.field_id.strip()
        schema = self.read_metadata_schema()
        if field_id not in schema.fields:
            raise ProjectServiceError(f"Unknown metadata field {field_id}.", 404)

        overview = self.read_metadata_schema_overview()
        source = overview.field_sources.get(field_id)
        if source is None:
            raise ProjectServiceError(f"Unknown metadata field {field_id}.", 404)
        if source.built_in:
            raise ProjectServiceError("System metadata fields cannot be deleted.", 422)
        source_path = self._metadata_schema_layer_path_for_id(root, source.layer_id)
        if source_path is None:
            raise ProjectServiceError("Unknown metadata schema layer.", 404)

        layer_data = self._read_yaml(source_path) if source_path.exists() else self._empty_metadata_schema()
        self._remove_metadata_field_from_layer(layer_data, field_id, request.entry_type)

        candidate = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path == source_path:
                self._merge_metadata_schema_layer(candidate, layer_data)
            elif path.exists():
                self._merge_metadata_schema_layer(candidate, self._read_metadata_schema_layer(path))
        deleted_schema = MetadataSchema.model_validate(self._resolve_metadata_schema_inheritance(candidate))
        schema_errors = self._validate_metadata_schema_definition(deleted_schema)
        if schema_errors:
            raise ProjectServiceError(" ".join(schema_errors), 422)

        self._write_yaml(source_path, layer_data)
        self._remove_entry_metadata_key(root, field_id)
        return self.read_metadata_schema()

    def _add_metadata_field_to_layer(
        self,
        root: Path,
        layer_path: Path,
        layer_data: dict[str, Any],
        field_id: str,
        field: MetadataFieldDefinition,
        entry_type: str,
    ) -> None:
        fields = layer_data.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        # `field` may come from the RESOLVED schema (move path), which carries
        # resolver-stamped derived keys — never persist those into a layer.
        fields[field_id] = field.model_dump(
            exclude_none=True, exclude={"category", "group_origin", "item_members", "item_scalar"}
        )
        layer_data["fields"] = fields

        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            entry_types = {}
        entry_type_data = entry_types.get(entry_type)
        if not isinstance(entry_type_data, dict):
            effective_entry_type = self._read_metadata_schema_through_path(root, layer_path).entry_types.get(entry_type)
            entry_type_data = {
                "name": effective_entry_type.name if effective_entry_type else entry_type,
                "kind": effective_entry_type.kind if effective_entry_type else "scene",
                "fields": [],
            }
        fields_list = entry_type_data.get("fields")
        if not isinstance(fields_list, list):
            fields_list = []
        if field_id not in fields_list:
            fields_list.append(field_id)
        entry_type_data["fields"] = fields_list
        entry_types[entry_type] = entry_type_data
        layer_data["entry_types"] = entry_types

    def _remove_metadata_field_from_layer(self, layer_data: dict[str, Any], field_id: str, entry_type: str) -> None:
        fields = layer_data.get("fields")
        if isinstance(fields, dict):
            fields.pop(field_id, None)
            layer_data["fields"] = fields

        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            return
        candidate_entry_types = [entry_type] if entry_type in entry_types else list(entry_types)
        for entry_type_id in candidate_entry_types:
            entry_type_data = entry_types.get(entry_type_id)
            if not isinstance(entry_type_data, dict):
                continue
            fields_list = entry_type_data.get("fields")
            if isinstance(fields_list, list):
                entry_type_data["fields"] = [candidate for candidate in fields_list if candidate != field_id]

    def _replace_metadata_field_reference_in_layer(
        self,
        layer_data: dict[str, Any],
        old_field_id: str,
        new_field_id: str,
        entry_type: str,
    ) -> None:
        entry_types = layer_data.get("entry_types")
        if not isinstance(entry_types, dict):
            return
        candidate_entry_types = [entry_type] if entry_type in entry_types else list(entry_types)
        for entry_type_id in candidate_entry_types:
            entry_type_data = entry_types.get(entry_type_id)
            if not isinstance(entry_type_data, dict):
                continue
            fields_list = entry_type_data.get("fields")
            if not isinstance(fields_list, list):
                continue
            replaced: list[Any] = []
            for candidate in fields_list:
                next_field_id = new_field_id if candidate == old_field_id else candidate
                if next_field_id not in replaced:
                    replaced.append(next_field_id)
            entry_type_data["fields"] = replaced

    def _entry_type_in_use(self, root: Path, entry_type_id: str) -> bool:
        for path in self._entry_markdown_paths(root):
            front_matter, _ = self._read_markdown_with_front_matter(path, strict=True)
            if front_matter.get("entry_type") == entry_type_id:
                return True
        return False

    def _rename_entry_metadata_key(self, root: Path, old_field_id: str, new_field_id: str) -> None:
        for path in self._entry_markdown_paths(root):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict) or old_field_id not in metadata:
                continue
            if new_field_id not in metadata:
                metadata[new_field_id] = metadata[old_field_id]
            metadata.pop(old_field_id, None)
            front_matter["metadata"] = metadata
            self._write_markdown_with_front_matter(path, front_matter, body)

    def _remove_entry_metadata_key(self, root: Path, field_id: str) -> None:
        for path in self._entry_markdown_paths(root):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict) or field_id not in metadata:
                continue
            metadata.pop(field_id, None)
            front_matter["metadata"] = metadata
            self._write_markdown_with_front_matter(path, front_matter, body)

    def _apply_option_value_changes(
        self,
        root: Path,
        field_id: str,
        old_field: MetadataFieldDefinition,
        new_field: MetadataFieldDefinition,
        rename_map: dict[str, str] | None,
    ) -> None:
        """Propagate select/multi_select option edits into stored entry data.

        Applies an explicit, reorder-safe `rename_map` (old value → new value,
        keyed by the option's original value) and then clears any value that is
        no longer one of the field's options. select → invalid value cleared;
        multi_select → invalid items dropped. A `list` field with the `select`
        item sugar (#698) stores the same flat scalar sequence multi_select
        does and reads its choices from the field's own options, so it
        migrates through the identical list branch. Skips `tags` (freeform;
        tag renames flow through merge_tags, not the option list).
        """

        def carries_options(field: MetadataFieldDefinition) -> bool:
            # For a list field the sugar carries the options — but only when
            # the sugar is actually the shape (a resolvable item_group wins a
            # cross-layer tie, and then the options are dead weight).
            return field.type in ("select", "multi_select") or (
                field.type == "list" and field.item_type == "select" and not field.item_group
            )

        if not carries_options(old_field) or not carries_options(new_field):
            return
        rename = {k: v for k, v in (rename_map or {}).items() if k != v}
        valid = {option.value for option in new_field.options}
        if not rename and not valid and not old_field.options:
            return

        # multi_select is a SET, so its migration de-duplicates; an ordered
        # list legitimately repeats values (that is the point of an ordered
        # log), so its items must survive the rewrite verbatim-in-order.
        ordered = old_field.type == "list"
        for path in self._entry_markdown_paths(root):
            front_matter, body = self._read_markdown_with_front_matter(path, strict=True)
            metadata = front_matter.get("metadata")
            if not isinstance(metadata, dict) or field_id not in metadata:
                continue
            value = metadata[field_id]
            next_value = self._clean_option_value(value, rename, valid, ordered=ordered)
            if next_value == value:
                continue
            metadata[field_id] = next_value
            front_matter["metadata"] = metadata
            self._write_markdown_with_front_matter(path, front_matter, body)

    def _clean_option_value(
        self, value: Any, rename: dict[str, str], valid: set[str], *, ordered: bool = False
    ) -> Any:
        if isinstance(value, list):
            out: list[Any] = []
            seen: set[str] = set()
            for item in value:
                if not isinstance(item, str):
                    out.append(item)
                    continue
                mapped = rename.get(item, item)
                if mapped not in valid or (not ordered and mapped in seen):
                    continue
                seen.add(mapped)
                out.append(mapped)
            return out
        if isinstance(value, str):
            mapped = rename.get(value, value)
            return mapped if mapped in valid else ""
        return value

    # The layer walk itself — `_project_layer_folders`, `_metadata_schema_layer_paths`,
    # `_layer_label_for_folder`, `_metadata_schema_layer_id` and
    # `_metadata_schema_base_folder` — moved to `layers.py` in #329, so there is
    # one traversal every consumer visits. They resolve through the MRO, so the
    # call sites below are unchanged.

    def _metadata_schema_layer_path_for_id(self, root: Path, layer_id: str) -> Path | None:
        """The schema file for a layer id, or None when the id is unknown.

        Reverses the id through the walk (`layer_by_id` → `LayerFinder`) rather
        than re-hashing `path.parent` per candidate, which was the last surviving
        "derive the layer identity yourself" site (#329).
        """
        layer = self.layer_by_id(root, layer_id)
        return None if layer is None else layer.folder / SCHEMA_FILENAME

    def build_prospective_metadata_schema(self, layers: list[IndexLayer]) -> MetadataSchema:
        """The merged schema for an explicit, not-yet-created chain (#318 slice 4).

        `read_metadata_schema` derives its layers by walking the open project's
        declaration; the wizard's review pane has only the ticked ancestors and a
        root folder that does not exist yet (`prospective_layers`). The merge is a
        pure function of the ordered layer folders, so it reuses the exact fold
        `_build_metadata_schema` uses — default base, nearer-wins per layer,
        inheritance resolved last. The root layer contributes nothing (its
        `metadata.schema.yaml` is not written until create), which the
        `path.exists()` guard handles: a prospective leaf simply adds no schema,
        the correct answer.
        """
        data = deepcopy(DEFAULT_METADATA_SCHEMA)
        for layer in layers:
            path = layer.folder / SCHEMA_FILENAME
            if path.exists():
                self._merge_metadata_schema_layer(data, self._read_metadata_schema_layer(path))
        data = self._resolve_metadata_schema_inheritance(data)
        return MetadataSchema.model_validate(data)

    def _read_metadata_schema_through_path(self, root: Path, target_path: Path) -> MetadataSchema:
        data = deepcopy(DEFAULT_METADATA_SCHEMA)
        for path in self._metadata_schema_layer_paths(root):
            if path.exists():
                self._merge_metadata_schema_layer(data, self._read_metadata_schema_layer(path))
            if path == target_path:
                break
        data = self._resolve_metadata_schema_inheritance(data)
        return MetadataSchema.model_validate(data)

    def _metadata_schema_layer_warnings(self, root: Path) -> list[str]:
        """Why this project's chain is only itself, when it is (#429).

        Both cases name the *machine* root now, because that is where the bound
        lives and where the author has to go to change it. Naming
        `settings.projects_base_folder` sent them to a per-project key that no
        longer decides anything.
        """
        warnings: list[str] = []
        base_folder = self._metadata_schema_base_folder(root)
        if base_folder is None:
            warnings.append(
                "No projects folder is set for this machine, so this project inherits nothing; "
                "using its own metadata schema only. Set it in Settings."
            )
        elif not self._is_relative_to(root, base_folder):
            warnings.append(
                f"This project is outside the machine's projects folder ({base_folder}), so it "
                "inherits nothing; using its own metadata schema only."
            )
        return warnings


    def _read_metadata_schema_layer(self, path: Path) -> dict[str, Any]:
        try:
            return self._read_yaml(path)
        except ProjectServiceError as exc:
            raise ProjectServiceError(f"{path}: {exc.message}", exc.status_code) from exc

    def _merge_metadata_schema_layer(self, base: dict[str, Any], layer: dict[str, Any]) -> None:
        base["version"] = layer.get("version", base.get("version", 1))
        if "entry_types" in layer:
            base["entry_types"] = self._merge_metadata_entry_types(
                base.get("entry_types", {}),
                layer.get("entry_types"),
            )
        if "fields" in layer:
            base["fields"] = self._merge_metadata_schema_section(
                base.get("fields", {}),
                layer.get("fields"),
            )
        if "groups" in layer:
            base["groups"] = self._merge_metadata_schema_section(
                base.get("groups", {}),
                layer.get("groups"),
            )

    def _resolve_metadata_schema_inheritance(self, data: dict[str, Any]) -> dict[str, Any]:
        resolved_data = deepcopy(data)
        entry_types = resolved_data.get("entry_types")
        if not isinstance(entry_types, dict):
            return resolved_data

        resolved: dict[str, Any] = {}
        resolving: set[str] = set()
        # L2 groups: generated field definitions accumulated while expanding
        # each entry type's group_applications. Merged into `fields` after
        # resolution (declared fields win on key collision).
        groups = resolved_data.get("groups")
        if not isinstance(groups, dict):
            groups = {}
        generated_fields: dict[str, Any] = {}

        def expand_group_applications(raw_entry_type: dict[str, Any], target_fields: list[Any]) -> None:
            applications = raw_entry_type.get("group_applications")
            if not isinstance(applications, list):
                return
            for application in applications:
                if not isinstance(application, dict):
                    continue
                group_id = application.get("group_id")
                group = groups.get(group_id) if isinstance(group_id, str) else None
                if not isinstance(group, dict):
                    continue
                label = str(application.get("label", "")).strip()
                prefix = str(application.get("key_prefix", "")).strip()
                group_name = str(group.get("name", "")).strip()
                section = f"{label} {group_name}".strip() if label else group_name
                members = group.get("members")
                if not isinstance(members, list):
                    continue
                for member in members:
                    if not isinstance(member, dict):
                        continue
                    member_key = str(member.get("key", "")).strip()
                    if not member_key:
                        continue
                    generated_key = f"{prefix}{member_key}"
                    generated_fields[generated_key] = {
                        "name": member.get("name") or member_key,
                        "type": member.get("type", "text"),
                        "icon": member.get("icon"),
                        "options": deepcopy(member.get("options", [])),
                        "picker_config": deepcopy(member.get("picker_config")),
                        "default": deepcopy(member.get("default")),
                        "group": section or None,
                        "group_origin": group_id,
                    }
                    if generated_key not in target_fields:
                        target_fields.append(generated_key)

        def resolve_entry_type(entry_type_id: str) -> Any:
            if entry_type_id in resolved:
                return resolved[entry_type_id]
            raw_entry_type = entry_types.get(entry_type_id)
            if not isinstance(raw_entry_type, dict):
                resolved[entry_type_id] = raw_entry_type
                return raw_entry_type
            if entry_type_id in resolving:
                resolved[entry_type_id] = deepcopy(raw_entry_type)
                return resolved[entry_type_id]

            resolving.add(entry_type_id)
            parent_id = raw_entry_type.get("parent")
            inherited_fields: list[Any] = []
            if isinstance(parent_id, str) and parent_id in entry_types:
                parent_entry_type = resolve_entry_type(parent_id)
                if isinstance(parent_entry_type, dict):
                    inherited_fields = parent_entry_type.get("fields", [])

            next_entry_type = deepcopy(raw_entry_type)
            local_fields = raw_entry_type.get("fields", [])
            next_entry_type["own_fields"] = deepcopy(local_fields) if isinstance(local_fields, list) else []
            # `own_color` mirrors `own_fields` — captures the value as
            # declared on this type before parent inheritance overwrites
            # the effective `color`. The editor uses this to distinguish
            # "set on this type" from "inherited".
            next_entry_type["own_color"] = raw_entry_type.get("color")
            next_entry_type["fields"] = self._merge_metadata_field_lists(
                inherited_fields,
                local_fields,
            )
            # L2: append generated fields from this type's group applications
            # (after own/inherited so they trail the hand-authored fields).
            expand_group_applications(raw_entry_type, next_entry_type["fields"])
            # Intrinsic identity fields (#116): every node carries id/title/
            # entry_type in top-level front matter, so inject them into every
            # type's membership (leading, before display_order can reorder).
            # Unconditional + deduped: intrinsic fields can never be dropped by
            # a type omitting them, and inheriting a parent that already has
            # them doesn't double-count. Injected here (not via each type's
            # `fields`) keeps them out of `own_fields`, so the editor renders
            # them as built-in rather than type-owned.
            existing_fields = next_entry_type["fields"]
            intrinsic_to_add = [k for k in INTRINSIC_FIELD_KEYS if k not in existing_fields]
            next_entry_type["fields"] = intrinsic_to_add + existing_fields
            # Display order (#89): membership is inheritance-resolved above; a
            # per-type `display_order` then reorders the whole resolved list
            # (inherited fields included) without touching membership. Additive
            # and stable — unknown ids are ignored, members absent from the order
            # trail in their resolved position.
            next_entry_type["fields"] = self._apply_display_order(
                next_entry_type["fields"], raw_entry_type.get("display_order")
            )
            if isinstance(parent_id, str) and parent_id in entry_types:
                parent_definition = resolved.get(parent_id)
                if isinstance(parent_definition, dict):
                    for inheritable in ("display_template", "has_body", "body_editor", "body_language", "body_shape", "default_body", "default_inputs", "color"):
                        if inheritable not in next_entry_type and inheritable in parent_definition:
                            next_entry_type[inheritable] = parent_definition[inheritable]
                    parent_prompt = parent_definition.get("prompt")
                    if isinstance(parent_prompt, dict):
                        child_prompt = next_entry_type.get("prompt") if isinstance(next_entry_type.get("prompt"), dict) else {}
                        merged_prompt = {**deepcopy(parent_prompt), **deepcopy(child_prompt)}
                        next_entry_type["prompt"] = merged_prompt
            # Field presentation overrides (#116): inherit the parent's, then
            # layer this type's on top per aspect (child wins). Parallel to
            # display_order — pure presentation, membership untouched. A child
            # that only sets `hidden` keeps the parent's `label`, and vice versa.
            parent_overrides: dict[str, Any] = {}
            if isinstance(parent_id, str) and parent_id in entry_types:
                parent_definition = resolved.get(parent_id)
                if isinstance(parent_definition, dict) and isinstance(parent_definition.get("field_overrides"), dict):
                    parent_overrides = parent_definition["field_overrides"]
            own_overrides = next_entry_type.get("field_overrides")
            if not isinstance(own_overrides, dict):
                own_overrides = {}
            # Own (pre-merge) overrides, mirroring `own_fields`/`own_color`
            # (ADR-0029 §I). The override editor reads/writes this so editing
            # one aspect doesn't freeze the inherited other aspect into the
            # child layer.
            next_entry_type["own_field_overrides"] = deepcopy(own_overrides)
            merged_overrides: dict[str, dict[str, Any]] = {
                key: dict(value) for key, value in parent_overrides.items() if isinstance(value, dict)
            }
            for key, value in own_overrides.items():
                if not isinstance(value, dict):
                    continue
                combined = dict(merged_overrides.get(key, {}))
                for aspect in ("label", "hidden"):
                    if value.get(aspect) is not None:
                        combined[aspect] = value[aspect]
                merged_overrides[key] = combined
            next_entry_type["field_overrides"] = merged_overrides
            resolving.remove(entry_type_id)
            resolved[entry_type_id] = next_entry_type
            return next_entry_type

        for entry_type_id in list(entry_types):
            entry_types[entry_type_id] = resolve_entry_type(str(entry_type_id))

        # Merge generated group fields into the schema's field registry.
        # Declared fields win on a key collision (don't clobber an authored
        # field that happens to match a generated prefix+member key).
        if generated_fields:
            schema_fields = resolved_data.get("fields")
            if not isinstance(schema_fields, dict):
                schema_fields = {}
            for generated_key, generated_def in generated_fields.items():
                schema_fields.setdefault(generated_key, generated_def)
            resolved_data["fields"] = schema_fields

        # Authorship category (ADR-0029 §D): stamp `category` on every resolved
        # field def as the single source of truth so no surface re-derives it
        # from scattered booleans. Derived, never stored — `intrinsic` iff the
        # key is in the canonical set, `computed` iff `type == "computed"`,
        # else `stored`. INTRINSIC_FIELD_KEYS stays canonical here.
        schema_fields = resolved_data.get("fields")
        if isinstance(schema_fields, dict):
            for field_key, field_def in schema_fields.items():
                if not isinstance(field_def, dict):
                    continue
                if field_key in INTRINSIC_FIELD_KEYS:
                    field_def["category"] = "intrinsic"
                elif field_def.get("type") == "computed":
                    field_def["category"] = "computed"
                else:
                    field_def["category"] = "stored"
                # item_members / item_scalar are DERIVED: purge any persisted
                # or authored copy unconditionally, then re-stamp for list
                # fields. A stale copy would otherwise survive group
                # deletion/rename (validating values against a shape that no
                # longer exists), and a hand-authored one would bypass the
                # member-type ban.
                field_def.pop("item_members", None)
                field_def.pop("item_scalar", None)
                if field_def.get("type") == "list":
                    self._stamp_list_item_members(field_key, field_def, groups)
        return resolved_data

    @staticmethod
    def _stamp_list_item_members(
        field_key: str, field_def: dict[str, Any], groups: dict[str, Any]
    ) -> None:
        """Stamp the resolved item shape on a list field (#698, ADR-0048 §6).

        Derived like `category`, never persisted: `item_members` is the named
        group's members, or the `item_type` sugar normalized to a one-member
        shape (key "value", options seeded from the field's own `options`);
        `item_scalar` records WHICH shape won, and is the only discriminator
        downstream consumers may read — never the raw declaration keys, which
        a cross-layer merge can leave in conflict. Tie-break: a RESOLVABLE
        item_group wins; an unknown group falls back to the sugar so the
        field stays serviceable (integrity reports the conflict either way).
        A field with neither (or an unknown group and no sugar) stays
        unstamped; integrity reports it."""

        group_id = field_def.get("item_group")
        group = groups.get(group_id) if isinstance(group_id, str) and group_id else None
        members = group.get("members") if isinstance(group, dict) else None
        if isinstance(members, list):
            field_def["item_members"] = deepcopy(members)
            field_def["item_scalar"] = False
            return
        item_type = field_def.get("item_type")
        if isinstance(item_type, str) and item_type:
            field_def["item_members"] = [
                {
                    "key": "value",
                    "name": field_def.get("name") or field_key,
                    "type": item_type,
                    "options": deepcopy(field_def.get("options", [])),
                }
            ]
            field_def["item_scalar"] = True

    def _merge_metadata_entry_types(self, base: Any, layer: Any) -> Any:
        if not isinstance(base, dict):
            base = {}
        if not isinstance(layer, dict):
            return layer

        merged = deepcopy(base)
        for entry_type_id, layer_entry_type in layer.items():
            base_entry_type = merged.get(entry_type_id)
            if not isinstance(base_entry_type, dict) or not isinstance(layer_entry_type, dict):
                merged[entry_type_id] = deepcopy(layer_entry_type)
                continue

            next_entry_type = self._merge_metadata_schema_section(base_entry_type, layer_entry_type)
            if isinstance(base_entry_type.get("fields"), list) or isinstance(layer_entry_type.get("fields"), list):
                next_entry_type["fields"] = self._merge_metadata_field_lists(
                    base_entry_type.get("fields", []),
                    layer_entry_type.get("fields", []),
                )
            merged[entry_type_id] = next_entry_type
        return merged

    def _merge_metadata_field_lists(self, base: Any, layer: Any) -> list[Any]:
        fields: list[Any] = []
        if isinstance(base, list):
            fields.extend(deepcopy(base))
        if isinstance(layer, list):
            for field_id in layer:
                if field_id not in fields:
                    fields.append(deepcopy(field_id))
        return fields

    @staticmethod
    def _apply_display_order(fields: list[str], order: Any) -> list[str]:
        """Reorder a resolved membership list by a per-type `display_order` (#89):
        ids named in `order` (that are actually members) lead, in that sequence;
        the rest trail in their resolved order. Stable and robust to drift — a
        stale id in `order` is skipped; a new member absent from `order` keeps its
        place after the ordered ones."""
        if not isinstance(order, list):
            return fields
        members = set(fields)
        seen: set[str] = set()
        ordered: list[str] = []
        for field_id in order:
            if isinstance(field_id, str) and field_id in members and field_id not in seen:
                ordered.append(field_id)
                seen.add(field_id)
        for field_id in fields:
            if field_id not in seen:
                ordered.append(field_id)
                seen.add(field_id)
        return ordered

    def _merge_metadata_schema_section(self, base: Any, layer: Any) -> Any:
        if not isinstance(base, dict):
            base = {}
        if not isinstance(layer, dict):
            return layer

        merged = deepcopy(base)
        for key, value in layer.items():
            key = str(key)
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged

    def _layer_overrides_entry_type(self, layer_type_data: Any) -> bool:
        if not isinstance(layer_type_data, dict):
            return False
        return any(key in layer_type_data for key in ("name", "kind", "parent", "abstract"))

    def _schema_section_keys(self, data: dict[str, Any], section: str) -> list[str]:
        value = data.get(section)
        if not isinstance(value, dict):
            return []
        return [str(key) for key in value]

    def _validate_metadata_schema_definition(self, schema: MetadataSchema) -> list[str]:
        errors: list[str] = []
        for entry_type_id, entry_type in schema.entry_types.items():
            # Identity is the kind-qualified FQN `kind:key` (#77): the dict key
            # must be `<kind>:<local>` and its prefix must match the type's own
            # `kind`. This is the backstop that keeps a hand-edited layer from
            # reintroducing a bare (ambiguous) key or crossing a key into the
            # wrong kind.
            fqn_match = _ENTRY_TYPE_FQN_RE.fullmatch(entry_type_id)
            if not fqn_match:
                errors.append(f"Metadata entry_type key {entry_type_id!r} must be kind-qualified as `kind:key`.")
            elif fqn_match.group(1) != entry_type.kind:
                errors.append(
                    f"Metadata entry_type {entry_type_id} has kind prefix '{fqn_match.group(1)}' "
                    f"but declares kind '{entry_type.kind}'."
                )
            if entry_type.parent and entry_type.parent not in schema.entry_types:
                errors.append(f"Metadata entry_type {entry_type_id} references unknown parent {entry_type.parent}.")
            if entry_type.parent and entry_type.parent in schema.entry_types:
                parent_entry_type = schema.entry_types[entry_type.parent]
                if parent_entry_type.kind != entry_type.kind:
                    errors.append(f"Metadata entry_type {entry_type_id} parent {entry_type.parent} has a different kind.")
            seen: set[str] = set()
            parent_id = entry_type.parent
            while parent_id:
                if parent_id in seen or parent_id == entry_type_id:
                    errors.append(f"Metadata entry_type {entry_type_id} has a circular parent chain.")
                    break
                seen.add(parent_id)
                parent_id = schema.entry_types.get(parent_id).parent if parent_id in schema.entry_types else None

        for entry_type_id, entry_type in schema.entry_types.items():
            for field_id in entry_type.fields:
                if field_id not in schema.fields:
                    errors.append(f"Metadata entry_type {entry_type_id} references unknown field {field_id}.")

        for entry_type_id, entry_type in schema.entry_types.items():
            for application in entry_type.group_applications:
                if application.group_id not in schema.groups:
                    errors.append(
                        f"Metadata entry_type {entry_type_id} applies unknown group {application.group_id}."
                    )

        for entry_type_id, entry_type in schema.entry_types.items():
            if entry_type.prompt is None:
                continue
            if entry_type.kind != "prompt":
                errors.append(f"Entry type {entry_type_id} has prompt configuration but kind is {entry_type.kind}.")
                continue
            seen_inputs: set[str] = set()
            for input_def in entry_type.prompt.inputs:
                if input_def.name in seen_inputs:
                    errors.append(f"Entry type {entry_type_id} has duplicate prompt input '{input_def.name}'.")
                seen_inputs.add(input_def.name)
                if input_def.type == "select" and not input_def.options:
                    errors.append(f"Entry type {entry_type_id} input '{input_def.name}' is type select but has no options.")
            # ADR-0054 §1/§2 + #954: the prompt's `output` — its disposition `kind`,
            # optional `commit` (chat_panel only), and optional `on_accept` mark-stamp
            # (inline only). Soft-validated in `schema_validation` (co-located with the
            # closed vocabularies), which keeps this file under the size cap.
            strategy = entry_type.prompt.context_strategy
            errors.extend(validate_prompt_output(entry_type_id, strategy.output if strategy else None))

        for field_id, field in schema.fields.items():
            if field.type == "computed":
                if not field.computed:
                    errors.append(f"Computed metadata field {field_id} must define computed settings.")
                continue
            if field.computed:
                errors.append(f"Metadata field {field_id} has computed settings but is not type computed.")
            if field.type == "list":
                errors.extend(self._list_field_schema_errors(field_id, field, schema))
            elif field.item_group is not None or field.item_type is not None:
                errors.append(f"Metadata field {field_id} has item shape settings but is not type list.")
        return errors

    @staticmethod
    def _list_field_schema_errors(field_id: str, field: MetadataFieldDefinition, schema: MetadataSchema) -> list[str]:
        """Shape rules for a list field (#698, ADR-0048 §6) — SOFT errors, not
        model validators: layers merge field defs by key union, so an
        ancestor's item_group and a child's item_type can legitimately meet in
        one merged def, and a raising validator would make the merged schema
        unreadable (500 on every read). The resolver's tie-break (a resolvable
        item_group wins, else the item_type sugar) keeps reads serviceable;
        these report the states the author should fix."""

        errors: list[str] = []
        if field.item_group is None and field.item_type is None:
            errors.append(f"List metadata field {field_id} declares neither item_group nor item_type.")
        elif field.item_group is not None and field.item_type is not None:
            errors.append(
                f"List metadata field {field_id} declares both item_group and item_type; "
                "remove one of them from the layer that added it (the resolved schema uses the group while it exists)."
            )
        if field.item_group is not None:
            group = schema.groups.get(field.item_group)
            if group is None:
                errors.append(f"List metadata field {field_id} references unknown group {field.item_group}.")
            else:
                # Members must stay inside the one scalar catalog
                # (LIST_ITEM_SCALAR_TYPES) — the POSITIVE form of the item_type
                # Literal, so the two cannot drift. Reference-typed members are
                # out because the read-side healers only walk top-level values
                # (a nested ref they cannot heal or purge is a silent
                # mis-link); date and multi_select carry no item affordances.
                for member in group.members:
                    if member.type not in LIST_ITEM_SCALAR_TYPES:
                        errors.append(
                            f"List metadata field {field_id} item shape {field.item_group} has "
                            f"member {member.key} of type {member.type}, which list items do not support."
                        )
        return errors
