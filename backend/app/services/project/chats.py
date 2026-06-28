"""Chat-session slice of ProjectService (#14 backend split).

Chat sessions are persisted one-YAML-per-chat under `<project>/chats/`.
This mixin owns their CRUD; `ProjectService` composes it. Method bodies
moved verbatim from project_service.py — shared helpers they call
(`self._require_project`, `self._read_yaml`, `self._write_yaml`,
`self._utcnow_iso`, `self._new_id`, `self._read_ai_invocations_raw`,
`self.resolve_assistant`, `self.append_ai_invocation`) still live on the
core class and resolve through the MRO at call time.

`compute_project_cost` and `_utcnow_iso` deliberately stay in core: the
former is a cost-reporting surface over the unified ai_invocations log
(not chat CRUD), and the latter is a generic timestamp util the
ai_invocations writer also uses.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models import (
    ChatSession,
    ChatSessionList,
    ChatSessionSummary,
    ChatUsage,
    CreateAIInvocationRequest,
    CreateChatSessionRequest,
    SaveChatSessionRequest,
)
from app.services.project.errors import ProjectServiceError


class ChatSessionsMixin:
    def _chats_dir(self) -> Path:
        root = self._require_project()
        return root / "chats"

    def _chat_path(self, chat_id: str) -> Path:
        if not re.fullmatch(r"chat_[a-zA-Z0-9_-]+", chat_id):
            raise ProjectServiceError(f"Invalid chat id {chat_id!r}.", 422)
        return self._chats_dir() / f"{chat_id}.yaml"

    def list_chat_sessions(self) -> ChatSessionList:
        folder = self._chats_dir()
        if not folder.exists():
            return ChatSessionList(sessions=[])
        summaries: list[ChatSessionSummary] = []
        for entry in folder.iterdir():
            if not entry.is_file() or entry.suffix.lower() != ".yaml":
                continue
            try:
                data = self._read_yaml(entry)
            except Exception:
                continue
            if not isinstance(data, dict) or not data.get("id"):
                continue
            messages = data.get("messages") or []
            raw_cost = data.get("cost_usd_total", 0.0)
            try:
                cost_usd_total = float(raw_cost) if raw_cost is not None else 0.0
            except (TypeError, ValueError):
                cost_usd_total = 0.0
            summaries.append(
                ChatSessionSummary(
                    id=str(data.get("id", "")),
                    title=str(data.get("title", "")) or "Untitled chat",
                    prompt_entry_id=str(data.get("prompt_entry_id", "") or ""),
                    assistant_id=str(data.get("assistant_id", "") or ""),
                    pinned=bool(data.get("pinned", False)),
                    created_at=str(data.get("created_at", "") or ""),
                    updated_at=str(data.get("updated_at", "") or ""),
                    message_count=len(messages) if isinstance(messages, list) else 0,
                    cost_usd_total=cost_usd_total,
                )
            )
        # Pinned first, then most-recently-updated first.
        pinned = sorted(
            (s for s in summaries if s.pinned),
            key=lambda s: s.updated_at, reverse=True,
        )
        unpinned = sorted(
            (s for s in summaries if not s.pinned),
            key=lambda s: s.updated_at, reverse=True,
        )
        return ChatSessionList(sessions=pinned + unpinned)

    def read_chat_session(self, chat_id: str) -> ChatSession:
        path = self._chat_path(chat_id)
        if not path.exists():
            raise ProjectServiceError(f"Chat {chat_id} does not exist.", 404)
        data = self._read_yaml(path)
        if not isinstance(data, dict):
            raise ProjectServiceError(f"Chat {chat_id} is malformed.", 500)
        session = ChatSession.model_validate(data)
        # Phase C2 Slice B: cost_usd_total is now a projection of the
        # unified ai_invocations log. The persisted YAML value is kept
        # for round-trip back-compat but never consulted — sum log rows
        # tagged with this chat_session_id for the live display value.
        log_total = 0.0
        for record in self._read_ai_invocations_raw():
            if str(record.get("chat_session_id") or "") != chat_id:
                continue
            cost = record.get("cost_usd")
            if isinstance(cost, (int, float)):
                log_total += float(cost)
        session.cost_usd_total = log_total
        return session

    def create_chat_session(self, request: CreateChatSessionRequest) -> ChatSession:
        self._chats_dir().mkdir(parents=True, exist_ok=True)
        now = self._utcnow_iso()
        session = ChatSession(
            id=self._new_id("chat"),
            title=request.title or "Untitled chat",
            prompt_entry_id=request.prompt_entry_id,
            assistant_id=request.assistant_id,
            system_prompt=request.system_prompt,
            target_scene_id=request.target_scene_id,
            pinned=False,
            created_at=now,
            updated_at=now,
            context_items=[],
            messages=[],
        )
        self._write_yaml(self._chat_path(session.id), session.model_dump())
        return session

    def save_chat_session(
        self, chat_id: str, request: SaveChatSessionRequest
    ) -> ChatSession:
        path = self._chat_path(chat_id)
        if not path.exists():
            raise ProjectServiceError(f"Chat {chat_id} does not exist.", 404)
        existing = self.read_chat_session(chat_id)
        # Once any messages exist, the preset (prompt + assistant + brief) is
        # locked. Switching them mid-conversation would invalidate the Anthropic
        # cache prefix and force a full re-send. Callers should start a new chat.
        if existing.messages:
            if request.prompt_entry_id != existing.prompt_entry_id:
                raise ProjectServiceError(
                    "Cannot change prompt of a chat that already has messages. "
                    "Start a new chat with this prompt instead.",
                    409,
                )
            if request.assistant_id != existing.assistant_id:
                raise ProjectServiceError(
                    "Cannot change assistant of a chat that already has messages. "
                    "Start a new chat with this assistant instead.",
                    409,
                )
            if request.system_prompt != existing.system_prompt:
                raise ProjectServiceError(
                    "Cannot change brief of a chat that already has messages. "
                    "Start a new chat to use a different brief.",
                    409,
                )
        # Journal handling:
        # - request.journal is None → leave the persisted journal alone
        #   (general saves: rename, message append, draft inputs). This
        #   is the common case — callers that don't manage the journal
        #   shouldn't have to forward it.
        # - request.journal is a list → "this is the new value", subject
        #   to the append-only guard. Only the chat-send endpoint sets
        #   this on purpose.
        if request.journal is None:
            next_journal = list(existing.journal)
        else:
            prior_ids = [e.entry_id for e in existing.journal]
            incoming_ids = [e.entry_id for e in request.journal]
            if incoming_ids[: len(prior_ids)] != prior_ids:
                raise ProjectServiceError(
                    "Chat journal is append-only — cannot drop or reorder "
                    "auto-detected context entries.",
                    409,
                )
            next_journal = list(request.journal)
        # Phase C2 Slice B: per-turn cost no longer lives on the chat YAML
        # — it lands as an ai_invocations row tagged with chat_session_id.
        # cost_usd_total stays at 0 (kept on the model for back-compat
        # round-trips); compute_project_cost reads the unified log.
        if request.cost_delta_usd is not None and request.cost_delta_usd > 0:
            delta = float(request.cost_delta_usd)
            # Try to resolve provider/model via the chat's assistant for
            # richer telemetry rows. Empty when the assistant lookup
            # fails — the cost still attributes correctly via chat_session_id.
            provider = ""
            model = ""
            try:
                assistant = self.resolve_assistant(request.assistant_id) if request.assistant_id else None
                if assistant is not None:
                    raw_provider = assistant.metadata.get("ai_provider")
                    raw_model = assistant.metadata.get("ai_model")
                    if isinstance(raw_provider, str):
                        provider = raw_provider
                    if isinstance(raw_model, str):
                        model = raw_model
            except Exception:
                pass
            # Pick up the last assistant turn's usage telemetry if the
            # incoming messages carry it. Falls back to None when absent.
            last_usage: ChatUsage | None = None
            for message in reversed(request.messages):
                if message.role == "assistant" and message.usage is not None:
                    last_usage = message.usage
                    break
            self.append_ai_invocation(
                CreateAIInvocationRequest(
                    prompt_entry_id=request.prompt_entry_id,
                    prompt_entry_type="chat",
                    scene_id=existing.target_scene_id,
                    chat_session_id=existing.id,
                    provider=provider,
                    model=model,
                    usage=last_usage,
                    cost_usd=delta,
                )
            )
        next_cost = 0.0
        next_cache_times = dict(existing.cache_write_times)
        if request.cache_write_slots:
            now_iso = self._utcnow_iso()
            for slot in request.cache_write_slots:
                if slot:
                    next_cache_times[slot] = now_iso

        updated = ChatSession(
            id=existing.id,
            title=request.title or existing.title or "Untitled chat",
            prompt_entry_id=request.prompt_entry_id,
            assistant_id=request.assistant_id,
            system_prompt=request.system_prompt,
            # target_scene_id only matters before first-send (the render
            # binding); callers echo the loaded value so it survives
            # per-turn saves. Fall back to the persisted value when a
            # caller omits it, so it's never silently dropped.
            target_scene_id=request.target_scene_id or existing.target_scene_id,
            pinned=request.pinned,
            created_at=existing.created_at,
            updated_at=self._utcnow_iso(),
            context_items=request.context_items,
            messages=request.messages,
            inputs=request.inputs,
            journal=next_journal,
            cost_usd_total=next_cost,
            cache_write_times=next_cache_times,
        )
        self._write_yaml(path, updated.model_dump())
        return updated

    def delete_chat_session(self, chat_id: str) -> ChatSessionList:
        path = self._chat_path(chat_id)
        if path.exists():
            path.unlink()
        return self.list_chat_sessions()
