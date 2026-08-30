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

# --- Cost-summary row helpers (#10). The summary reads RAW rows with the same
# tolerant semantics as the other two ledger summers (`_compute_invocation_cost`
# and the per-chat `cost_usd_total`), so a hand-edited row can never make the
# rollup disagree with the per-scene/per-chat figures about which rows count.


def _day_of(record: dict[str, Any]) -> str:
    ts = record.get("ts")
    return ts[:10] if isinstance(ts, str) else ""


def _in_day_range(record: dict[str, Any], since: str | None, until: str | None) -> bool:
    day = _day_of(record)
    return (since is None or day >= since) and (until is None or day <= until)


def _str_field(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    return value if isinstance(value, str) else ""


def _token_field(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key)
    return int(value) if isinstance(value, (int, float)) else 0


def _row_measures(record: dict[str, Any]) -> tuple[int, int, float | None]:
    """A row's (billable input tokens, output tokens, cost-or-None)."""
    usage = record.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    # The three input slots are disjoint (see ChatUsage) — sum for total
    # billable input.
    input_tokens = (
        _token_field(usage, "input_tokens")
        + _token_field(usage, "cached_input_tokens")
        + _token_field(usage, "cache_write_tokens")
    )
    output_tokens = _token_field(usage, "output_tokens")
    raw_cost = record.get("cost_usd")
    cost = float(raw_cost) if isinstance(raw_cost, (int, float)) else None
    return input_tokens, output_tokens, cost


def _cost_rank(bucket: AICostBucket) -> tuple[float, int, str]:
    return (-(bucket.cost_usd or 0.0), -bucket.count, bucket.key)


def _bucket_targets(record: dict[str, Any], label_for: Any) -> list[tuple[str, str, str]]:
    """The (breakdown, key, label) buckets one row lands in."""
    model = _str_field(record, "model")
    targets = [("by_model", model, model or "unknown model")]
    for name, key_field in (
        ("by_chat", "chat_session_id"),
        ("by_scene", "scene_id"),
        ("by_prompt", "prompt_entry_id"),
    ):
        node_id = _str_field(record, key_field)
        if node_id:
            targets.append((name, node_id, label_for(node_id)))
    day = _day_of(record)
    if day:
        targets.append(("by_day", day, day))
    return targets


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
        drift and rows are frozen.

        Iterates the raw rows with the same tolerant reads as the other two
        ledger summers (`_compute_invocation_cost`, the per-chat
        `cost_usd_total`) so all three count the same rows — a hand-edited
        row must not make this total disagree with the per-chat chips. A row
        without a numeric `cost_usd` still counts toward `count` /
        `unpriced_count` and the token totals, but never a cost sum; a scope
        with rows but no priced row reports cost None, not 0.0 (#697).
        """
        since = since or None
        until = until or None
        rows = [
            record
            for record in self._read_ai_invocations_raw()
            if _in_day_range(record, since, until)
        ]

        # One node-index build serves every chat/scene/prompt label lookup,
        # built lazily on the first labelled row so an unlabelled ledger
        # never pays for it.
        index: Any = None

        def label_for(node_id: str) -> str:
            nonlocal index
            if index is None:
                index = self._build_node_index()
            entry = index.by_id.get(node_id)
            return entry.title if entry is not None and entry.title else node_id

        names = ("by_model", "by_chat", "by_scene", "by_prompt", "by_day")
        breakdowns: dict[str, dict[str, AICostBucket]] = {name: {} for name in names}
        totals = AICostSummary(total_cost_usd=None, count=len(rows))

        for record in rows:
            input_tokens, output_tokens, cost = _row_measures(record)
            totals.input_tokens += input_tokens
            totals.output_tokens += output_tokens
            if cost is None:
                totals.unpriced_count += 1
            else:
                totals.total_cost_usd = (totals.total_cost_usd or 0.0) + cost
            for name, key, label in _bucket_targets(record, label_for):
                bucket = breakdowns[name].setdefault(key, AICostBucket(key=key, label=label))
                bucket.count += 1
                bucket.input_tokens += input_tokens
                bucket.output_tokens += output_tokens
                if cost is None:
                    bucket.unpriced_count += 1
                else:
                    bucket.cost_usd = (bucket.cost_usd or 0.0) + cost

        totals.by_model = sorted(breakdowns["by_model"].values(), key=_cost_rank)
        totals.by_chat = sorted(breakdowns["by_chat"].values(), key=_cost_rank)
        totals.by_scene = sorted(breakdowns["by_scene"].values(), key=_cost_rank)
        totals.by_prompt = sorted(breakdowns["by_prompt"].values(), key=_cost_rank)
        totals.by_day = sorted(
            breakdowns["by_day"].values(), key=lambda bucket: bucket.key, reverse=True
        )
        # An empty scope is a known zero; rows with no priced row stay None.
        if totals.total_cost_usd is None and not rows:
            totals.total_cost_usd = 0.0
        return totals
