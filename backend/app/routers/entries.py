"""View, assistant, chat, unified-node, todo, reference, and search routes (#170 main.py split)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.models import (
    AssistantEntry,
    AssistantEntryList,
    BacklinksResponse,
    ChatSession,
    ChatSessionList,
    CreateAssistantEntryRequest,
    CreateChatSessionRequest,
    CreateTodoRequest,
    EmbeddedTodoList,
    ReferenceCandidatesResponse,
    ReferenceGraphResponse,
    ReferenceResolveRequest,
    ReferenceResolveResponse,
    ReorderAssistantsRequest,
    SaveAssistantEntryRequest,
    SaveChatSessionRequest,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    SaveSceneRequest,
    SearchRequest,
    SearchResponse,
    TodoDocument,
    UpdateTodoRequest,
)
from app.models_views import (
    CreateViewRequest,
    SaveViewRequest,
    ViewNode,
    ViewNodeList,
)
from app.routers.ai import _validate_assistant_temperature
from app.runtime import service, translate_errors

router = APIRouter()


@router.get("/api/views", response_model=ViewNodeList)
def list_views() -> ViewNodeList:
    """Saved views (0.5.0, #35/#78) — frontmatter-only `view` nodes."""
    with translate_errors():
        return service.list_views()


@router.post("/api/views", response_model=ViewNode)
def create_view(request: CreateViewRequest) -> ViewNode:
    with translate_errors():
        return service.create_view(request)


@router.get("/api/views/{view_id}", response_model=ViewNode)
def get_view(view_id: str) -> ViewNode:
    with translate_errors():
        return service.read_view(view_id)


@router.put("/api/views/{view_id}", response_model=ViewNode)
def save_view(view_id: str, request: SaveViewRequest) -> ViewNode:
    with translate_errors():
        return service.save_view(view_id, request)


@router.delete("/api/views/{view_id}", response_model=ViewNodeList)
def delete_view(view_id: str) -> ViewNodeList:
    with translate_errors():
        return service.delete_view(view_id)


@router.get("/api/assistants", response_model=AssistantEntryList)
def list_assistant_entries() -> AssistantEntryList:
    with translate_errors():
        return service.list_assistant_entries()


@router.post("/api/assistants", response_model=AssistantEntry)
def create_assistant_entry(request: CreateAssistantEntryRequest) -> AssistantEntry:
    with translate_errors():
        return service.create_assistant_entry(request)


@router.get("/api/assistants/{entry_id}", response_model=AssistantEntry)
def get_assistant_entry(entry_id: str) -> AssistantEntry:
    with translate_errors():
        return service.read_assistant_entry(entry_id)


@router.put("/api/assistants/{entry_id}", response_model=AssistantEntry)
def save_assistant_entry(entry_id: str, request: SaveAssistantEntryRequest) -> AssistantEntry:
    err = _validate_assistant_temperature(request.metadata)
    if err:
        raise HTTPException(status_code=400, detail=err)
    with translate_errors():
        return service.save_assistant_entry(entry_id, request)


@router.delete("/api/assistants/{entry_id}", response_model=AssistantEntryList)
def delete_assistant_entry(entry_id: str) -> AssistantEntryList:
    with translate_errors():
        return service.delete_assistant_entry(entry_id)


@router.post("/api/assistants/order", response_model=AssistantEntryList)
def reorder_assistant_entries(request: ReorderAssistantsRequest) -> AssistantEntryList:
    with translate_errors():
        return service.reorder_assistant_entries(request)


# --- Persistent chat sessions (Phase 3) ---


@router.get("/api/chats", response_model=ChatSessionList)
def list_chat_sessions() -> ChatSessionList:
    with translate_errors():
        return service.list_chat_sessions()


@router.post("/api/chats", response_model=ChatSession)
def create_chat_session(request: CreateChatSessionRequest) -> ChatSession:
    with translate_errors():
        return service.create_chat_session(request)


@router.get("/api/chats/{chat_id}", response_model=ChatSession)
def get_chat_session(chat_id: str) -> ChatSession:
    with translate_errors():
        return service.read_chat_session(chat_id)


@router.put("/api/chats/{chat_id}", response_model=ChatSession)
def save_chat_session(chat_id: str, request: SaveChatSessionRequest) -> ChatSession:
    with translate_errors():
        return service.save_chat_session(chat_id, request)


@router.delete("/api/chats/{chat_id}", response_model=ChatSessionList)
def delete_chat_session(chat_id: str) -> ChatSessionList:
    with translate_errors():
        return service.delete_chat_session(chat_id)


# --- Unified node endpoints (Phase 3c) ---
#
# Thin HTTP shim over the unified service-layer dispatchers
# (read_node / save_node / delete_node). The per-kind endpoints
# (`/api/scenes/{id}`, `/api/chats/{id}`, etc.) keep working — these
# are an additional path that lets callers operate on any node by id
# without knowing its kind. The PUT validator picks the right
# Pydantic save-request model based on the indexed kind.


_SAVE_NODE_REQUEST_BY_KIND: dict[str, type] = {
    "scene": SaveSceneRequest,
    "lore": SaveLoreEntryRequest,
    "prompt": SavePromptEntryRequest,
    "assistant": SaveAssistantEntryRequest,
    "chat": SaveChatSessionRequest,
}


@router.get("/api/nodes/{node_id}")
def get_node(node_id: str):
    """Dispatches by kind via the node index. Returns the kind-specific
    Pydantic model — Scene | LoreEntry | PromptEntry | AssistantEntry |
    ChatSession. No response_model declared because FastAPI can't pick
    a single model for a heterogeneous union; the underlying readers
    each emit their canonical shape."""
    with translate_errors():
        return service.read_node(node_id)


@router.put("/api/nodes/{node_id}")
async def put_node(node_id: str, request: Request):
    """Unified save. Looks up the node's kind first so we can validate
    the JSON body against the right per-kind save-request model, then
    forwards to the matching saver. Wrong-shape requests come back as
    a Pydantic 422 just like the per-kind endpoints."""
    kind = service.lookup_node_kind(node_id)
    if kind is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} does not exist.")
    request_model = _SAVE_NODE_REQUEST_BY_KIND.get(kind)
    if request_model is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported node kind {kind!r} for node {node_id}.",
        )
    raw = await request.json()
    try:
        parsed = request_model.model_validate(raw)
    except Exception as exc:
        # Bubble Pydantic validation as a 422 with the message — matches
        # FastAPI's default behavior for typed request bodies.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Assistant requests carry the small temperature-range check the
    # per-kind endpoint runs; mirror it here so the unified path
    # rejects out-of-range temperatures the same way.
    if kind == "assistant":
        err = _validate_assistant_temperature(parsed.metadata)
        if err:
            raise HTTPException(status_code=400, detail=err)
    with translate_errors():
        return service.save_node(node_id, parsed)


@router.delete("/api/nodes/{node_id}", status_code=204)
def delete_node(node_id: str):
    """Unified delete. Returns 204 No Content — callers refresh their
    own kind-specific list separately."""
    with translate_errors():
        service.delete_node(node_id)


@router.get("/api/todos", response_model=TodoDocument)
def get_todos() -> TodoDocument:
    with translate_errors():
        return service.read_todos()


@router.get("/api/todos/embedded", response_model=EmbeddedTodoList)
def get_embedded_todos() -> EmbeddedTodoList:
    """The rebuildable index of in-prose embedded todos across all scenes."""
    with translate_errors():
        return service.read_embedded_todos()


@router.post("/api/todos", response_model=TodoDocument)
def create_todo(request: CreateTodoRequest) -> TodoDocument:
    with translate_errors():
        return service.create_todo(request)


@router.patch("/api/todos/{todo_id}", response_model=TodoDocument)
def update_todo(todo_id: str, request: UpdateTodoRequest) -> TodoDocument:
    with translate_errors():
        return service.update_todo(todo_id, request)


@router.delete("/api/todos/{todo_id}", response_model=TodoDocument)
def delete_todo(todo_id: str) -> TodoDocument:
    with translate_errors():
        return service.delete_todo(todo_id)


@router.post("/api/references/resolve", response_model=ReferenceResolveResponse)
def resolve_references(request: ReferenceResolveRequest) -> ReferenceResolveResponse:
    with translate_errors():
        return service.resolve_references(request.ids)


@router.get("/api/references/candidates", response_model=ReferenceCandidatesResponse)
def list_reference_candidates(
    kind: str | None = Query(default=None),
    entry_type: str | None = Query(default=None),
    exclude_id: str | None = Query(default=None),
) -> ReferenceCandidatesResponse:
    with translate_errors():
        return service.list_reference_candidates(kind=kind, entry_type=entry_type, exclude_id=exclude_id)


@router.get("/api/references/backlinks", response_model=BacklinksResponse)
def list_backlinks(id: str = Query()) -> BacklinksResponse:
    with translate_errors():
        return service.list_backlinks(id)


@router.get("/api/references/graph", response_model=ReferenceGraphResponse)
def reference_graph() -> ReferenceGraphResponse:
    with translate_errors():
        return service.reference_graph()


@router.post("/api/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    with translate_errors():
        return service.search(request)


