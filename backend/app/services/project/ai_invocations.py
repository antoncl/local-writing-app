"""AI-invocation telemetry slice of ProjectService (#14 backend split).

An append-only log at `<project>/ai_invocations.yaml`: each accepted
continuation/roleplay generation pushes one record (model, tokens, cost,
scene_id, character_id, chat_session_id). The `cost` computed field and the
project-cost breakdown both project from this log. Not a Node kind yet —
promote when the audit-log UI lands (GH #9/#10). This mixin owns the log IO and
the cost rollup; `ProjectService` composes it.

Method bodies moved verbatim from project_service.py. Shared helpers they call
(`self._require_project`, `self._read_yaml`, `self._write_yaml`,
`self._new_id`, `self._utcnow_iso`, and `self._chats_dir` from
`ChatSessionsMixin`) live elsewhere on the composed class and resolve through
the MRO at call time. `_utcnow_iso` and `_write_node_entry_file` stay in core:
both are generic/shared writers used by other slices too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.models import (
    AIInvocation,
    AIInvocationList,
    CreateAIInvocationRequest,
)


class AiInvocationsMixin:
    def compute_project_cost(self) -> dict:
        """Sum cost_usd across `ai_invocations.yaml` and group by
        chat_session_id. Rows without a chat_session_id (continuation /
        roleplay accepts) fold into a synthetic "_other" bucket so the
        total still matches the log total. Returns:
            {"total_usd": float,
             "chats": [{"id": str, "title": str, "cost_usd": float}, ...]}
        Sorted by cost descending. Phase C2 Slice B replaces the prior
        per-chat cost_usd_total iteration.
        """
        per_chat: dict[str, float] = {}
        other_cost = 0.0
        total = 0.0
        for record in self._read_ai_invocations_raw():
            cost = record.get("cost_usd")
            if not isinstance(cost, (int, float)):
                continue
            total += float(cost)
            chat_id = str(record.get("chat_session_id") or "")
            if chat_id:
                per_chat[chat_id] = per_chat.get(chat_id, 0.0) + float(cost)
            else:
                other_cost += float(cost)
        # Resolve titles via the chat YAMLs so the response carries
        # human-readable labels. Chats whose YAML is gone (e.g. deleted
        # but historical log rows remain) keep a stub title.
        chat_titles: dict[str, str] = {}
        folder = self._chats_dir()
        if folder.exists():
            for entry in folder.iterdir():
                if not entry.is_file() or entry.suffix.lower() != ".yaml":
                    continue
                try:
                    data = self._read_yaml(entry)
                except Exception:
                    continue
                if isinstance(data, dict) and data.get("id"):
                    chat_titles[str(data["id"])] = str(data.get("title") or "Untitled chat")
        rows: list[dict] = []
        for chat_id, cost in per_chat.items():
            rows.append({
                "id": chat_id,
                "title": chat_titles.get(chat_id, "(deleted chat)"),
                "cost_usd": cost,
            })
        if other_cost > 0:
            rows.append({
                "id": "_other",
                "title": "Continuation & Roleplay accepts",
                "cost_usd": other_cost,
            })
        rows.sort(key=lambda r: r["cost_usd"], reverse=True)
        return {"total_usd": total, "chats": rows}

    def _ai_invocations_path(self) -> Path:
        root = self._require_project()
        return root / "ai_invocations.yaml"

    def _read_ai_invocations_raw(self) -> list[dict[str, Any]]:
        path = self._ai_invocations_path()
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if isinstance(data, list):
            return [record for record in data if isinstance(record, dict)]
        if isinstance(data, dict):
            items = data.get("invocations", [])
            if isinstance(items, list):
                return [record for record in items if isinstance(record, dict)]
        return []

    def list_ai_invocations(
        self,
        *,
        scene_id: str | None = None,
        character_id: str | None = None,
        chat_session_id: str | None = None,
    ) -> AIInvocationList:
        raw = self._read_ai_invocations_raw()
        invocations: list[AIInvocation] = []
        for record in raw:
            try:
                invocation = AIInvocation.model_validate(record)
            except Exception:
                continue
            if scene_id is not None and invocation.scene_id != scene_id:
                continue
            if character_id is not None and invocation.character_id != character_id:
                continue
            if chat_session_id is not None and invocation.chat_session_id != chat_session_id:
                continue
            invocations.append(invocation)
        return AIInvocationList(invocations=invocations)

    def append_ai_invocation(
        self, request: CreateAIInvocationRequest
    ) -> AIInvocation:
        self._require_project()
        raw = self._read_ai_invocations_raw()
        invocation = AIInvocation(
            id=self._new_id("inv"),
            ts=self._utcnow_iso(),
            prompt_entry_id=request.prompt_entry_id,
            prompt_entry_type=request.prompt_entry_type,
            scene_id=request.scene_id,
            character_id=request.character_id,
            chat_session_id=request.chat_session_id,
            provider=request.provider,
            model=request.model,
            usage=request.usage,
            cost_usd=request.cost_usd,
        )
        raw.append(invocation.model_dump())
        self._write_yaml(self._ai_invocations_path(), {"invocations": raw})
        return invocation
