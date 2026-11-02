"""Proofreading slice of ProjectService (ADR-0102 §4–§7, slice 2).

What the writer tells the proofreading lens to accept, kept in two optional
files. Absent means empty: no migration and no `CURRENT_VERSION` bump, because
nothing that exists changes shape (ADR-0102 §6).

- `proofreading.yaml`, at any layer — a project folder of the chain, the
  machine config dir, or the read-only built-in Library (which ships the
  fiction default). Holds `words`, `rules` and `dialect`. Words are the union of
  every layer's; rules and dialect merge outermost to nearest, nearer winning,
  the way `metadata.schema.yaml` does.
- `proofreading.ignored.yaml`, in a project folder: ignore-here context hashes
  by node id, saved in the project the node lives in.

The layers come from the one walk (`collect_layers`, `layers.py`) with the
Library and the machine included. The machine dir is a target before it holds
anything — the first word ever added at machine level needs somewhere to go —
so it is added to the list when the walk does not yield it yet.

Shared helpers it calls (`self._require_project`, `self.collect_layers`,
`self._metadata_schema_layer_id`, `self._build_node_index`,
`self._read_yaml`, `self._write_yaml`) live elsewhere on the composed class and
resolve through the MRO.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models import (
    ProofreadingDialectRequest,
    ProofreadingIgnoreRequest,
    ProofreadingLayer,
    ProofreadingRuleRequest,
    ProofreadingSetup,
    ProofreadingWordRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import (
    PROOFREADING_FILENAME,
    PROOFREADING_IGNORED_FILENAME,
)
from app.services.project.node_index import IndexLayer

DIALECTS = ("american", "british", "australian", "canadian", "indian")
_MAX_HASH = 2**64 - 1


def _words_of(data: dict[str, Any]) -> list[str]:
    raw = data.get("words")
    if not isinstance(raw, list):
        return []
    return [w.strip() for w in raw if isinstance(w, str) and w.strip()]


def _rules_of(data: dict[str, Any]) -> dict[str, bool]:
    raw = data.get("rules")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, bool)}


def _ignored_of(data: dict[str, Any]) -> dict[str, list[str]]:
    raw = data.get("ignored")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for node_id, hashes in raw.items():
        if isinstance(hashes, list):
            kept = [str(h) for h in hashes if str(h).isdigit()]
            if kept:
                out[str(node_id)] = kept
    return out


def _clean_word(word: str) -> str:
    cleaned = word.strip()
    # One dictionary entry is one word: the engine tokenizes on whitespace, so
    # an entry with a space in it could never match anything.
    if not cleaned or any(ch.isspace() for ch in cleaned):
        raise ProjectServiceError("A dictionary entry is a single word, without spaces.", 422)
    return cleaned


class ProofreadingMixin:
    # ---------- layers ----------

    def _proofreading_layers(self, root: Path) -> list[IndexLayer]:
        """Library, machine, then the project chain, outermost first."""
        from app.services import machine_settings as ms_service

        layers = self.collect_layers(root, include_machine=True, include_library=True)
        if not any(layer.is_machine for layer in layers):
            machine_dir = ms_service.assistants_dir().parent.resolve()
            machine = IndexLayer(
                folder=machine_dir,
                id=self._metadata_schema_layer_id(machine_dir),
                label="Machine",
                rank=0,
                is_machine=True,
            )
            at = 1 if layers and layers[0].is_library else 0
            layers.insert(at, machine)
        return layers

    def _proofreading_write_layer(self, root: Path, layer_id: str) -> IndexLayer:
        layer = next((x for x in self._proofreading_layers(root) if x.id == layer_id), None)
        if layer is None:
            raise ProjectServiceError(f"Unknown layer id {layer_id}.", 404)
        if layer.is_library:
            raise ProjectServiceError(
                "The built-in Library's proofreading defaults are read-only; set it on this machine or a project instead.",
                409,
            )
        return layer

    # ---------- read ----------

    def read_proofreading(self) -> ProofreadingSetup:
        root = self._require_project()
        layers = self._proofreading_layers(root)
        word_layers: dict[str, list[str]] = {}
        rules: dict[str, bool] = {}
        rule_layers: dict[str, str] = {}
        dialect = "american"
        ignored: dict[str, list[str]] = {}
        for layer in layers:
            data = self._read_yaml(layer.folder / PROOFREADING_FILENAME)
            for word in _words_of(data):
                word_layers.setdefault(word, []).append(layer.id)
            for rule, enabled in _rules_of(data).items():
                rules[rule] = enabled
                rule_layers[rule] = layer.id
            if data.get("dialect") in DIALECTS:
                dialect = data["dialect"]
            if not (layer.is_library or layer.is_machine):
                for node_id, hashes in _ignored_of(self._read_yaml(layer.folder / PROOFREADING_IGNORED_FILENAME)).items():
                    merged = ignored.setdefault(node_id, [])
                    merged.extend(h for h in hashes if h not in merged)
        return ProofreadingSetup(
            words=sorted(word_layers),
            word_layers=word_layers,
            rules=rules,
            rule_layers=rule_layers,
            dialect=dialect,
            layers=[
                ProofreadingLayer(
                    id=layer.id,
                    label=layer.label,
                    is_machine=layer.is_machine,
                    is_library=layer.is_library,
                    is_root=layer.is_root,
                )
                for layer in layers
            ],
            ignored=ignored,
        )

    # ---------- writes ----------

    def _update_proofreading_file(self, layer: IndexLayer, change) -> None:
        path = layer.folder / PROOFREADING_FILENAME
        data = self._read_yaml(path)
        change(data)
        self._write_yaml(path, data)

    def add_proofreading_word(self, request: ProofreadingWordRequest) -> ProofreadingSetup:
        root = self._require_project()
        layer = self._proofreading_write_layer(root, request.layer_id)
        word = _clean_word(request.word)

        def change(data: dict[str, Any]) -> None:
            data["words"] = sorted({*_words_of(data), word})

        self._update_proofreading_file(layer, change)
        return self.read_proofreading()

    def remove_proofreading_word(self, request: ProofreadingWordRequest) -> ProofreadingSetup:
        root = self._require_project()
        layer = self._proofreading_write_layer(root, request.layer_id)
        word = request.word.strip()

        def change(data: dict[str, Any]) -> None:
            remaining = [w for w in _words_of(data) if w != word]
            if remaining:
                data["words"] = remaining
            else:
                data.pop("words", None)

        self._update_proofreading_file(layer, change)
        return self.read_proofreading()

    def set_proofreading_rule(self, request: ProofreadingRuleRequest) -> ProofreadingSetup:
        root = self._require_project()
        layer = self._proofreading_write_layer(root, request.layer_id)

        def change(data: dict[str, Any]) -> None:
            # Keep every other key as written, unknown rule names included: a
            # rule this Harper version lacks may return in the next (§5).
            rules = dict(data["rules"]) if isinstance(data.get("rules"), dict) else {}
            if request.enabled is None:
                rules.pop(request.rule, None)
            else:
                rules[request.rule] = request.enabled
            if rules:
                data["rules"] = dict(sorted(rules.items()))
            else:
                data.pop("rules", None)

        self._update_proofreading_file(layer, change)
        return self.read_proofreading()

    def set_proofreading_dialect(self, request: ProofreadingDialectRequest) -> ProofreadingSetup:
        root = self._require_project()
        layer = self._proofreading_write_layer(root, request.layer_id)

        def change(data: dict[str, Any]) -> None:
            if request.dialect is None:
                data.pop("dialect", None)
            else:
                data["dialect"] = request.dialect

        self._update_proofreading_file(layer, change)
        return self.read_proofreading()

    def ignore_proofreading_spot(self, request: ProofreadingIgnoreRequest) -> ProofreadingSetup:
        root = self._require_project()
        if any(int(h) > _MAX_HASH for h in request.hashes):
            raise ProjectServiceError("An ignore-here hash is an unsigned 64-bit number.", 422)
        index = self._build_node_index(root)
        entry = index.by_id.get(request.node_id)
        if entry is None:
            raise ProjectServiceError(f"Unknown node {request.node_id}.", 404)
        # Saved in the project the node lives in (§4), so it holds wherever the
        # node is opened.
        layers = {x.id: x for x in self._proofreading_layers(root)}
        layer = layers.get(entry.source_layer_id) if entry.source_layer_id else None
        if layer is not None and (layer.is_library or layer.is_machine):
            raise ProjectServiceError("Only a node in a project can have an ignore-here.", 409)
        folder = layer.folder if layer is not None else root
        path = folder / PROOFREADING_IGNORED_FILENAME
        ignored = _ignored_of(self._read_yaml(path))
        hashes = ignored.setdefault(request.node_id, [])
        hashes.extend(h for h in dict.fromkeys(request.hashes) if h not in hashes)
        # A deleted node's hashes go with the next write here, instead of a
        # hook on every delete path (§6).
        ignored = {node_id: h for node_id, h in ignored.items() if node_id in index.by_id}
        self._write_yaml(path, {"ignored": ignored})
        return self.read_proofreading()
