"""Unified node-ops slice of ProjectService (#14 backend split).

Kind-polymorphic entrypoints (`lookup_node_kind`, `read_node`, `save_node`,
`delete_node`) that resolve a node's kind via the index and dispatch to the
per-kind reader/saver/deleter. The unified HTTP endpoints use these so a
caller can address any node by id without knowing its kind ahead of time;
the per-kind endpoints + methods are untouched. This mixin owns the
dispatchers; `ProjectService` composes it.

Method bodies moved verbatim. Everything they call resolves through the MRO:
`self._require_project`, `self._build_node_index` (ReferencesMixin), and the
per-kind `read_*`/`save_*`/`delete_*` methods on their respective slices.
"""

from __future__ import annotations

from app.models import (
    AssistantEntry,
    ChatSession,
    LoreEntry,
    PromptEntry,
    SaveAssistantEntryRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    SaveSceneRequest,
    Scene,
)
from app.models_views import SaveViewRequest, ViewNode
from app.services.project.errors import ProjectServiceError


class NodeOpsMixin:
    # kind → (matching request type, saver method name). `save_node`
    # dispatches through this table instead of an if/elif ladder that pairs a
    # kind test with an isinstance guard per kind (#76). Order and outcomes are
    # unchanged: an unknown kind is a 422, a request whose type does not match
    # the resolved kind is the same 422, and each kind calls the same saver.
    _SAVE_NODE_DISPATCH: dict[str, tuple[type, str]] = {
        "manuscript": (SaveSceneRequest, "save_scene"),
        "lore": (SaveLoreEntryRequest, "save_lore_entry"),
        "prompt": (SavePromptEntryRequest, "save_prompt_entry"),
        "assistant": (SaveAssistantEntryRequest, "save_assistant_entry"),
        "chat": (SaveChatSessionRequest, "save_chat_session"),
        "view": (SaveViewRequest, "save_view"),
    }

    def lookup_node_kind(self, node_id: str) -> str | None:
        """Cheap kind lookup that doesn't read the node file. Returns None
        if the id isn't indexed. Used by the unified HTTP endpoints to
        pick the right per-kind request validator before parsing PUT
        bodies (Phase 3c)."""
        self._require_project()
        entry = self._build_node_index().by_id.get(node_id)
        return entry.kind if entry else None

    def read_node(
        self, node_id: str
    ) -> Scene | LoreEntry | PromptEntry | AssistantEntry | ChatSession | ViewNode:
        """Unified node-read entrypoint.

        Resolves the kind via the node index and dispatches to the
        kind-specific reader. Backend half of the chat-as-node refactor
        (decisions-node-editor-modularization, Phase 3b-ii) — internal
        callers can now look up any node by id without knowing its kind
        ahead of time. Per-kind endpoints (`/api/scenes/{id}`,
        `/api/chats/{id}`, etc.) are untouched and still work the same.

        Project nodes (the singleton `project.md`) are NOT routed here —
        they're addressed via `read_project_node()` with no id.
        """
        self._require_project()
        index = self._build_node_index()
        entry = index.by_id.get(node_id)
        if entry is None:
            raise ProjectServiceError(f"Node {node_id} does not exist.", 404)
        if entry.kind == "manuscript":
            return self.read_scene(node_id)
        if entry.kind == "lore":
            return self.read_lore_entry(node_id)
        if entry.kind == "prompt":
            return self.read_prompt_entry(node_id)
        if entry.kind == "assistant":
            return self.read_assistant_entry(node_id)
        if entry.kind == "chat":
            return self.read_chat_session(node_id)
        if entry.kind == "view":
            return self.read_view(node_id)
        raise ProjectServiceError(
            f"Unsupported node kind {entry.kind!r} for node {node_id}.", 422
        )

    def save_node(
        self,
        node_id: str,
        request: SaveSceneRequest
        | SaveLoreEntryRequest
        | SavePromptEntryRequest
        | SaveAssistantEntryRequest
        | SaveChatSessionRequest
        | SaveViewRequest,
    ) -> Scene | LoreEntry | PromptEntry | AssistantEntry | ChatSession | ViewNode:
        """Unified node-save entrypoint (Phase 3b-iii).

        Resolves the kind via the node index and dispatches to the
        kind-specific saver. The caller passes the request type
        matching the node's kind; mismatch is a 422. Per-kind
        endpoints + savers are untouched and still work the same.
        """
        self._require_project()
        index = self._build_node_index()
        entry = index.by_id.get(node_id)
        if entry is None:
            raise ProjectServiceError(f"Node {node_id} does not exist.", 404)

        dispatch = self._SAVE_NODE_DISPATCH.get(entry.kind)
        if dispatch is None:
            raise ProjectServiceError(
                f"Unsupported node kind {entry.kind!r} for node {node_id}.", 422
            )
        request_type, saver_name = dispatch
        if not isinstance(request, request_type):
            raise ProjectServiceError(
                f"Request type {type(request).__name__} does not match "
                f"node {node_id} kind {entry.kind!r}.",
                422,
            )
        return getattr(self, saver_name)(node_id, request)

    def delete_node(self, node_id: str) -> None:
        """Unified node-delete entrypoint (Phase 3b-iii).

        Resolves the kind via the node index and dispatches to the
        kind-specific deleter. Returns None — callers fetch the
        kind-specific list separately to refresh their UI. Per-kind
        delete endpoints + deleters are untouched.
        """
        self._require_project()
        index = self._build_node_index()
        entry = index.by_id.get(node_id)
        if entry is None:
            raise ProjectServiceError(f"Node {node_id} does not exist.", 404)
        if entry.kind == "manuscript":
            self.delete_scene(node_id)
            return
        if entry.kind == "lore":
            self.delete_lore_entry(node_id)
            return
        if entry.kind == "prompt":
            self.delete_prompt_entry(node_id)
            return
        if entry.kind == "assistant":
            self.delete_assistant_entry(node_id)
            return
        if entry.kind == "chat":
            self.delete_chat_session(node_id)
            return
        if entry.kind == "view":
            self.delete_view(node_id)
            return
        raise ProjectServiceError(
            f"Unsupported node kind {entry.kind!r} for node {node_id}.", 422
        )
