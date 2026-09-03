"""Chat-session slice of ProjectService (#14 backend split).

Chat sessions are persisted one Node-file-per-chat under `<project>/chats/`
— body-less `.md` nodes carrying the ChatSession payload in front matter
(ADR-0051 S1, the views / mutation-set shape). This mixin owns their CRUD;
`ProjectService` composes it. Shared helpers they call
(`self._require_project`, `self._write_node_entry_file`,
`self._read_markdown_with_front_matter`, `self._delete_node_file`,
`self._utcnow_iso`, `self._new_id`, `self._read_ai_invocations_raw`,
`self.resolve_assistant`, `self.append_ai_invocation`) still live on the
core class and resolve through the MRO at call time.

`_utcnow_iso` deliberately stays in core: a generic timestamp util the
ai_invocations writer also uses (not chat CRUD).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.models import (
    ChangedPick,
    ChatSession,
    ChatSessionJournalEntry,
    ChatSessionList,
    ChatSessionSummary,
    ChatUsage,
    CreateAIInvocationRequest,
    CreateChatSessionRequest,
    SaveChatSessionRequest,
)
from app.services.project.ai_invocations import _add_cost
from app.services.project.errors import ProjectServiceError


class ChatSessionsMixin:
    def _chats_dir(self) -> Path:
        root = self._require_project()
        return root / "chats"

    def _chat_path(self, chat_id: str) -> Path:
        if not re.fullmatch(r"chat_[a-zA-Z0-9_-]+", chat_id):
            raise ProjectServiceError(f"Invalid chat id {chat_id!r}.", 422)
        return self._chats_dir() / f"{chat_id}.md"

    def _subject_scene_id(self, subject: str, root: Path | None = None) -> str:
        """A chat's anchored scene, derived from its `subject` (ADR-0051 S5).

        A scene subject IS the chat's render/journal scene — the old
        `target_scene_id` field folded into `subject`. Returns the subject id
        when it names a scene node (so `{{ scene }}` binds and the #60/#61
        as-of-scene name resolution runs), else "" for a lore/character subject
        or a freeform chat. Uses the node index (kind lookup), not a file read;
        `root` defaults to the current project (tests pass it explicitly).
        """
        if not subject:
            return ""
        entry = self._build_node_index(root).by_id.get(subject)
        return subject if entry is not None and entry.kind == "manuscript" else ""

    def _write_chat_session(self, path: Path, session: ChatSession) -> None:
        """Persist a chat as a Node file (ADR-0051 S2).

        Identity (`id`/`title`/`entry_type`) is the node header. The message
        transcript goes to the node **body** — kept out of front matter so the
        index (`_read_front_matter_only`) and the roster stop at the closing
        delimiter and never parse an unbounded conversation. `subject` (what the
        chat is about) is an `entity_ref`, so it lives in `metadata`, where the
        edge extractor finds it. The remaining session state rides `extra=` into
        front matter, plus a denormalized `message_count` so the roster reads
        the header alone; it is written here atomically with the transcript it
        counts, so it cannot drift.
        """
        dumped = session.model_dump()
        messages = dumped.pop("messages", None) or []
        # `session` is a validated ChatSession, so `subject`/`staged_set` are
        # always `str` here (the sparseness lives on the read side, which guards
        # for it). Both are entity_refs, so they live in `metadata`, where the
        # edge extractor finds them (chat->subject and chat->set). Empty values
        # are omitted so a chat with no staged set is byte-identical to today's.
        subject = dumped.pop("subject", "")
        staged_set = dumped.pop("staged_set", "")
        metadata: dict = {}
        if subject:
            metadata["subject"] = subject
        if staged_set:
            metadata["staged_set"] = staged_set
        extra = {key: value for key, value in dumped.items() if key not in ("id", "title")}
        extra["message_count"] = len(messages)
        body = (
            yaml.safe_dump({"messages": messages}, sort_keys=False, allow_unicode=True)
            if messages
            else ""
        )
        self._write_node_entry_file(
            path,
            session.id,
            session.title,
            "chat:chat_session",
            metadata,
            body,
            extra=extra,
            omit_empty_metadata=True,
        )

    def list_chat_sessions(self) -> ChatSessionList:
        folder = self._chats_dir()
        if not folder.exists():
            return ChatSessionList(sessions=[])
        summaries: list[ChatSessionSummary] = []
        for entry in folder.iterdir():
            if not entry.is_file() or entry.suffix.lower() != ".md":
                continue
            try:
                # Header only — the transcript is in the body (ADR-0051 S2), so
                # the roster never reads an unbounded conversation. `message_count`
                # is denormalized into front matter by `_write_chat_session`.
                data = self._read_front_matter_only(entry, strict=False)
            except Exception:
                continue
            if not data.get("id"):
                continue
            raw_count = data.get("message_count", 0)
            try:
                message_count = int(raw_count)
            except (TypeError, ValueError):
                message_count = 0
            raw_cost = data.get("cost_usd_total", 0.0)
            try:
                cost_usd_total = float(raw_cost) if raw_cost is not None else 0.0
            except (TypeError, ValueError):
                cost_usd_total = 0.0
            # `metadata` is a mapping on every app-written chat; stay total on
            # the shape rather than assuming it, like the `str(...)` reads around
            # it — a non-dict value yields no subject instead of raising here,
            # outside the loop's `_read_front_matter_only` guard.
            metadata = data.get("metadata")
            is_meta = isinstance(metadata, dict)
            subject = str(metadata.get("subject", "") or "") if is_meta else ""
            staged_set = str(metadata.get("staged_set", "") or "") if is_meta else ""
            summaries.append(
                ChatSessionSummary(
                    id=str(data.get("id", "")),
                    title=str(data.get("title", "")) or "Untitled chat",
                    # The node identity type the writer stamps (`chat:chat_session`);
                    # carried through so the roster is a real EvalNode for the
                    # designable Chats view (ADR-0051 S6).
                    entry_type=str(data.get("entry_type", "")),
                    subject=subject,
                    staged_set=staged_set,
                    prompt_entry_id=str(data.get("prompt_entry_id", "") or ""),
                    assistant_id=str(data.get("assistant_id", "") or ""),
                    pinned=bool(data.get("pinned", False)),
                    created_at=str(data.get("created_at", "") or ""),
                    updated_at=str(data.get("updated_at", "") or ""),
                    message_count=message_count,
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
        front, body = self._read_markdown_with_front_matter(path, strict=True)
        # `strict=True` already guarantees a dict-or-raise, so `front` is a map.
        data = dict(front)
        data.pop("message_count", None)  # denormalized roster hint; not a model field
        # `subject`/`staged_set` are stored as entity_refs in `metadata` (so the
        # index extracts the edges); the model carries them top-level. Lift back.
        meta = data.pop("metadata", None)
        if isinstance(meta, dict):
            if meta.get("subject"):
                data["subject"] = str(meta.get("subject") or "")
            if meta.get("staged_set"):
                data["staged_set"] = str(meta.get("staged_set") or "")
        # The transcript lives in the body (ADR-0051 S2), serialized as YAML.
        if body.strip():
            parsed = yaml.safe_load(body)
            if isinstance(parsed, dict):
                data["messages"] = parsed.get("messages") or []
        session = ChatSession.model_validate(data)
        # Phase C2 Slice B: cost_usd_total is now a projection of the
        # unified ai_invocations log. The persisted YAML value is kept
        # for round-trip back-compat but never consulted — sum log rows
        # tagged with this chat_session_id for the live display value.
        #
        # A chat with no priced row — fresh, or one whose turns all ran an
        # unpriced model (those record no positive-cost row) — has an UNKNOWN
        # total, surfaced as None → "—"/hidden, not a fabricated €0.00 (#697).
        total: float | None = None
        for record, cost, _input, _output in self._iter_invocation_rows():
            if str(record.get("chat_session_id") or "") != chat_id:
                continue
            total = _add_cost(total, cost)
        session.cost_usd_total = total
        return session

    def chat_changed_picks(self, chat_id: str) -> list[ChangedPick]:
        """Picked lore entries whose current revision differs from what the AI
        last saw (#1635). Read-only; compares each lore pick's live revision
        against the chat's persisted `seen_revisions`. Never lists an entry the
        AI has not seen yet (not in `seen_revisions`) — that's a pending pick,
        not an edit."""
        chat = self.read_chat_session(chat_id)
        seen = chat.seen_revisions or {}
        # used_node_ids can include scenes/cards — keep only lore entries.
        pick_ids: list[str] = list(
            dict.fromkeys(
                [
                    *chat.used_node_ids,
                    *(i.id for i in chat.context_items if i.kind == "lore" and i.id),
                ]
            )
        )
        out: list[ChangedPick] = []
        for entry_id in pick_ids:
            if entry_id not in seen:
                continue
            try:
                entry = self.read_lore_entry(entry_id)
            except Exception:  # noqa: BLE001
                # A pick that's no longer a readable lore entry — deleted (a
                # stale-cache read raises FileNotFoundError, not
                # ProjectServiceError), retyped to a non-lore kind, or corrupt.
                # The door degrades to journal-only; never 500 a read.
                continue
            current = getattr(entry, "revision", "") or ""
            if current and current != seen[entry_id]:
                out.append(
                    ChangedPick(
                        id=entry_id,
                        title=getattr(entry, "title", "") or "",
                        entry_type=getattr(entry, "entry_type", "") or "",
                    )
                )
        return out

    def create_chat_session(self, request: CreateChatSessionRequest) -> ChatSession:
        self._chats_dir().mkdir(parents=True, exist_ok=True)
        now = self._utcnow_iso()
        session = ChatSession(
            id=self._new_id("chat"),
            title=request.title or "Untitled chat",
            prompt_entry_id=request.prompt_entry_id,
            assistant_id=request.assistant_id,
            system_prompt=request.system_prompt,
            subject=request.subject,
            staged_set=request.staged_set,
            pinned=False,
            created_at=now,
            updated_at=now,
            context_items=[],
            messages=[],
        )
        self._write_chat_session(self._chat_path(session.id), session)
        return session

    def save_chat_session(
        self, chat_id: str, request: SaveChatSessionRequest
    ) -> ChatSession:
        path = self._chat_path(chat_id)
        if not path.exists():
            raise ProjectServiceError(f"Chat {chat_id} does not exist.", 404)
        existing = self.read_chat_session(chat_id)
        self._guard_chat_preset_lock(existing, request)
        next_journal = self._resolved_chat_journal(existing, request)
        self._record_chat_cost_delta(existing, request)
        # The save response must carry the same projection read_chat_session
        # computes — the UI keeps the returned session as its live copy, and a
        # hardcoded 0.0 here zeroed its session-cost display on every save
        # (ADR-0076 decision 6). `existing` was projected from the log above,
        # BEFORE the delta row landed, so adding the accepted delta mirrors the
        # log exactly; None (unknown total, #697) stays None when no priced
        # delta arrives. The log remains the source of truth on read; the
        # persisted snapshot additionally keeps list_chat_sessions' roster
        # cost current, which the hardcoded 0.0 never did.
        next_cost = existing.cost_usd_total
        if request.cost_delta_usd is not None and request.cost_delta_usd > 0:
            next_cost = (next_cost or 0.0) + float(request.cost_delta_usd)
        next_cache_times = self._touched_cache_write_times(existing, request)

        updated = ChatSession(
            id=existing.id,
            title=request.title or existing.title or "Untitled chat",
            prompt_entry_id=request.prompt_entry_id,
            assistant_id=request.assistant_id,
            system_prompt=request.system_prompt,
            # Echoed on every save; fall back to the persisted value so a caller
            # that omits it never silently drops the subject (ADR-0051 S2). A
            # scene subject also carries the render/journal anchor (S5), so this
            # one echo covers both what-it's-about and the as-of scene.
            subject=request.subject or existing.subject,
            # Echoed with the same persisted-value fallback so a per-turn save
            # that omits it never drops the chat's staged set (ADR-0055 S4).
            staged_set=request.staged_set or existing.staged_set,
            # ADR-0057 §2: the lore gate. None from the request = "leave the
            # captured value alone" (general saves), so only the lock-render
            # save (which carries the value from the preview response) sets it;
            # every later per-turn save preserves it.
            lore_enabled=(
                existing.lore_enabled
                if request.lore_enabled is None
                else request.lore_enabled
            ),
            # ADR-0060 §2: the author-selected node ids, preserved like the lore
            # gate. None from the request = "leave the captured value alone"
            # (general saves), so only the lock-render save sets it.
            used_node_ids=(
                existing.used_node_ids
                if request.used_node_ids is None
                else request.used_node_ids
            ),
            # ADR-0060 §5: volatility priors, preserved like `used_node_ids`.
            used_node_hints=(
                existing.used_node_hints
                if request.used_node_hints is None
                else request.used_node_hints
            ),
            # ADR-0067 S2: the field-contract set the lock render registered,
            # preserved like `used_node_ids`. None from the request = "leave the
            # captured value alone" (general saves), so only the lock-render
            # save (which carries it from the preview response) sets it.
            field_contract_stored=(
                existing.field_contract_stored
                if request.field_contract_stored is None
                else request.field_contract_stored
            ),
            pinned=request.pinned,
            created_at=existing.created_at,
            updated_at=self._utcnow_iso(),
            context_items=request.context_items,
            messages=request.messages,
            inputs=request.inputs,
            journal=next_journal,
            cost_usd_total=next_cost,
            cache_write_times=next_cache_times,
            seen_revisions=(
                existing.seen_revisions
                if request.seen_revisions is None
                else request.seen_revisions
            ),
        )
        self._write_chat_session(path, updated)
        return updated

    def _guard_chat_preset_lock(
        self, existing: ChatSession, request: SaveChatSessionRequest
    ) -> None:
        """Once any messages exist, the preset (prompt + assistant + brief) is
        locked. Switching them mid-conversation would invalidate the Anthropic
        cache prefix and force a full re-send. Callers should start a new chat."""
        if not existing.messages:
            return
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

    def _resolved_chat_journal(
        self, existing: ChatSession, request: SaveChatSessionRequest
    ) -> list[ChatSessionJournalEntry]:
        """The journal to persist for this save.

        - request.journal is None → leave the persisted journal alone
          (general saves: rename, message append, draft inputs). This
          is the common case — callers that don't manage the journal
          shouldn't have to forward it.
        - request.journal is a list → "this is the new value", subject
          to the append-only guard. Only the chat-send endpoint sets
          this on purpose.
        """
        if request.journal is None:
            return list(existing.journal)
        prior_ids = [e.entry_id for e in existing.journal]
        incoming_ids = [e.entry_id for e in request.journal]
        if incoming_ids[: len(prior_ids)] != prior_ids:
            raise ProjectServiceError(
                "Chat journal is append-only — cannot drop or reorder "
                "auto-detected context entries.",
                409,
            )
        return list(request.journal)

    def _record_chat_cost_delta(
        self, existing: ChatSession, request: SaveChatSessionRequest
    ) -> None:
        """Phase C2 Slice B: per-turn cost no longer lives on the chat YAML
        — it lands as an ai_invocations row tagged with chat_session_id.
        cost_usd_total re-derives from the unified log on read; the value the
        save path writes/returns is a snapshot of that same projection
        (see save_chat_session), never a second source of truth."""
        if request.cost_delta_usd is None or request.cost_delta_usd <= 0:
            return
        delta = float(request.cost_delta_usd)
        # Provider/model for the telemetry row. The assistant's static
        # config is only a FALLBACK: a tier-configured assistant leaves
        # `ai_model` blank (the concrete model is resolved from the tier at
        # send time), so reading the config alone recorded an empty model
        # and every row bucketed as "unknown model" (#1794). The turn's own
        # provenance — stamped on the assistant message from the stream
        # response (ADR-0076) — is ground truth and wins below; the config
        # still covers older messages that predate per-turn provenance.
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
        # Pick up the last assistant turn's usage + per-turn provenance if
        # the incoming messages carry it. The message's model/provider
        # override the assistant's static config; usage falls back to None.
        last_usage: ChatUsage | None = None
        for message in reversed(request.messages):
            if message.role == "assistant" and message.usage is not None:
                last_usage = message.usage
                if isinstance(message.provider, str) and message.provider:
                    provider = message.provider
                if isinstance(message.model, str) and message.model:
                    model = message.model
                break
        self.append_ai_invocation(
            CreateAIInvocationRequest(
                prompt_entry_id=request.prompt_entry_id,
                prompt_entry_type="chat:chat_session",
                scene_id=self._subject_scene_id(existing.subject),
                chat_session_id=existing.id,
                provider=provider,
                model=model,
                usage=last_usage,
                cost_usd=delta,
            )
        )

    def _touched_cache_write_times(
        self, existing: ChatSession, request: SaveChatSessionRequest
    ) -> dict[str, str]:
        """Existing cache-write timestamps with any slots named in this save
        stamped to now (ADR-0057 cache accounting)."""
        next_cache_times = dict(existing.cache_write_times)
        if request.cache_write_slots:
            now_iso = self._utcnow_iso()
            for slot in request.cache_write_slots:
                if slot:
                    next_cache_times[slot] = now_iso
        return next_cache_times

    def delete_chat_session(self, chat_id: str) -> ChatSessionList:
        path = self._chat_path(chat_id)
        self._delete_node_file(path)  # unlink + un-shadow the memo (#392)
        return self.list_chat_sessions()
