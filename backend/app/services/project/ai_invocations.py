"""AI-invocation telemetry slice of ProjectService (#14 backend split).

An append-only log at `<project>/ai_invocations.yaml`: each accepted
continuation/roleplay generation pushes one record (model, tokens, cost,
scene_id, character_id, chat_session_id). The `cost` / `character_cost` /
`project_cost` computed fields project from this log via the computed-metadata
resolver. Not a Node kind yet — promote when the audit-log UI lands (GH #9/#10).
This mixin owns the log IO; `ProjectService` composes it.

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
    AICostBucket,
    AICostSummary,
    AIInvocation,
    AIInvocationList,
    CreateAIInvocationRequest,
)


class AiInvocationsMixin:
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

    def ai_cost_summary(
        self, *, since: str | None = None, until: str | None = None
    ) -> AICostSummary:
        """Aggregate the ledger into project-wide totals plus by-model /
        by-chat / by-scene / by-prompt / by-day buckets (#10). `since` /
        `until` are inclusive `YYYY-MM-DD` day bounds compared against each
        row's UTC timestamp day; empty strings behave like unset. Sums
        stored `cost_usd` verbatim — never re-prices, since catalogue prices
        drift and rows are frozen. A row with `cost_usd is None` still
        counts toward `count` / `unpriced_count` and its token totals, but
        never a cost sum — unknown stays distinct from 0.0 (#697).
        """
        since = since or None
        until = until or None
        rows = [
            invocation
            for invocation in self.list_ai_invocations().invocations
            if (since is None or invocation.ts[:10] >= since)
            and (until is None or invocation.ts[:10] <= until)
        ]

        # One node-index build serves every chat/scene/prompt label lookup,
        # and only runs at all if some row actually needs one.
        needs_index = any(
            invocation.chat_session_id or invocation.scene_id or invocation.prompt_entry_id
            for invocation in rows
        )
        index = self._build_node_index() if needs_index else None

        def label_for(node_id: str) -> str:
            entry = index.by_id.get(node_id) if index is not None else None
            return entry.title if entry is not None and entry.title else node_id

        by_model: dict[str, dict[str, Any]] = {}
        by_chat: dict[str, dict[str, Any]] = {}
        by_scene: dict[str, dict[str, Any]] = {}
        by_prompt: dict[str, dict[str, Any]] = {}
        by_day: dict[str, dict[str, Any]] = {}
        totals = {"cost_usd": 0.0, "unpriced_count": 0, "input_tokens": 0, "output_tokens": 0}

        def bump(
            buckets: dict[str, dict[str, Any]],
            key: str,
            label: str,
            *,
            priced: bool,
            cost: float,
            input_tokens: int,
            output_tokens: int,
        ) -> None:
            bucket = buckets.setdefault(
                key,
                {
                    "key": key,
                    "label": label,
                    "cost_usd": 0.0,
                    "count": 0,
                    "unpriced_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )
            bucket["count"] += 1
            bucket["input_tokens"] += input_tokens
            bucket["output_tokens"] += output_tokens
            if priced:
                bucket["cost_usd"] += cost
            else:
                bucket["unpriced_count"] += 1

        for invocation in rows:
            usage = invocation.usage
            # The three input slots are disjoint (see ChatUsage) — sum for
            # total billable input.
            input_tokens = (
                usage.input_tokens + usage.cached_input_tokens + usage.cache_write_tokens
                if usage is not None
                else 0
            )
            output_tokens = usage.output_tokens if usage is not None else 0
            priced = invocation.cost_usd is not None
            cost = invocation.cost_usd or 0.0

            totals["input_tokens"] += input_tokens
            totals["output_tokens"] += output_tokens
            if priced:
                totals["cost_usd"] += cost
            else:
                totals["unpriced_count"] += 1

            bump(
                by_model,
                invocation.model,
                invocation.model or "unknown model",
                priced=priced,
                cost=cost,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            if invocation.chat_session_id:
                bump(
                    by_chat,
                    invocation.chat_session_id,
                    label_for(invocation.chat_session_id),
                    priced=priced,
                    cost=cost,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            if invocation.scene_id:
                bump(
                    by_scene,
                    invocation.scene_id,
                    label_for(invocation.scene_id),
                    priced=priced,
                    cost=cost,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            if invocation.prompt_entry_id:
                bump(
                    by_prompt,
                    invocation.prompt_entry_id,
                    label_for(invocation.prompt_entry_id),
                    priced=priced,
                    cost=cost,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            day = invocation.ts[:10]
            bump(
                by_day,
                day,
                day,
                priced=priced,
                cost=cost,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        def ranked(buckets: dict[str, dict[str, Any]]) -> list[AICostBucket]:
            ordered = sorted(
                buckets.values(), key=lambda b: (-b["cost_usd"], -b["count"], b["key"])
            )
            return [AICostBucket(**b) for b in ordered]

        by_day_ranked = [
            AICostBucket(**b) for b in sorted(by_day.values(), key=lambda b: b["key"], reverse=True)
        ]

        return AICostSummary(
            total_cost_usd=totals["cost_usd"],
            count=len(rows),
            unpriced_count=totals["unpriced_count"],
            input_tokens=totals["input_tokens"],
            output_tokens=totals["output_tokens"],
            by_model=ranked(by_model),
            by_chat=ranked(by_chat),
            by_scene=ranked(by_scene),
            by_prompt=ranked(by_prompt),
            by_day=by_day_ranked,
        )
