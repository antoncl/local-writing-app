"""AI-invocation telemetry slice of ProjectService (#14 backend split).

An append-only log at `<project>/ai_invocations.csv`: each accepted
continuation/roleplay generation pushes one record (model, tokens, cost,
scene_id, character_id, chat_session_id). The `cost` / `character_cost` /
`project_cost` computed fields project from this log via the computed-metadata
resolver. Not a Node kind yet — promote when the audit-log UI lands (GH #9/#10).
This mixin owns the log IO; `ProjectService` composes it.

The ledger is a plain append-only CSV, following the logging-system precedent
(#1801): each new row is an O(1) line append (`open(…, "a")`), not a
read-modify-rewrite of the whole file. On disk the record is flat — the nested
`usage` object hoists to four fixed `usage_*` columns — and an empty cell means
None (an unpriced row has an empty `cost_usd`; a row with no usage captured has
all four `usage_*` cells empty, distinct from a captured zero). Readers key by
the header names, so a later column stays additive. The one-time move off the
old `{invocations: [...]}` YAML list is migration v9 (ADR-0071 ladder).

Shared helpers the methods call (`self._require_project`, `self._new_id`,
`self._utcnow_iso`, and `self._chats_dir` from `ChatSessionsMixin`) live
elsewhere on the composed class and resolve through the MRO at call time.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

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


def _add_cost(acc: float | None, cost: float | None) -> float | None:
    """Fold one row's cost into a running total under the shared "unknown
    until a priced row" policy (#697): a scope stays None until its first
    priced row, then accumulates. The per-chat `cost_usd_total`, the summary
    grand total, and each summary bucket all reduce with this, so they agree
    on when a total is known rather than re-expressing the rule three ways
    (#1708)."""
    if cost is None:
        return acc
    return (acc or 0.0) + cost


def _cost_rank(bucket: AICostBucket) -> tuple[float, int, str]:
    return (-(bucket.cost_usd or 0.0), -bucket.count, bucket.key)


def _bucket_targets(
    record: dict[str, Any], resolve_node: Any
) -> list[tuple[str, str, str, bool]]:
    """The (breakdown, key, label, openable) buckets one row lands in.
    `openable` is True only for a node-keyed bucket whose id resolves to a
    live node; the non-node breakdowns (model, day) are never openable."""
    model = _str_field(record, "model")
    targets = [("by_model", model, model or "unknown model", False)]
    for name, key_field in (
        ("by_chat", "chat_session_id"),
        ("by_scene", "scene_id"),
        ("by_prompt", "prompt_entry_id"),
    ):
        node_id = _str_field(record, key_field)
        if node_id:
            label, openable = resolve_node(node_id)
            targets.append((name, node_id, label, openable))
    day = _day_of(record)
    if day:
        targets.append(("by_day", day, day, False))
    return targets


# --- CSV ledger serialization (#1801). The on-disk row is flat: the nine
# string fields, `cost_usd`, then the four `usage_*` columns hoisted out of the
# nested usage object. In memory a record keeps the nested `usage` shape the
# rest of the slice (and `AIInvocation`) expects, so the CSV format is confined
# to the reader/writer here and the v9 migration — no consumer sees it. These
# are module-public because migration v9 reuses the exact same column order and
# flattening (one contract, authored once).

_INVOCATION_STR_COLUMNS = (
    "id",
    "ts",
    "prompt_entry_id",
    "prompt_entry_type",
    "scene_id",
    "character_id",
    "chat_session_id",
    "provider",
    "model",
)
_INVOCATION_USAGE_COLUMNS = (
    "usage_input_tokens",
    "usage_cached_input_tokens",
    "usage_cache_write_tokens",
    "usage_output_tokens",
)
INVOCATION_CSV_COLUMNS = (
    *_INVOCATION_STR_COLUMNS,
    "cost_usd",
    *_INVOCATION_USAGE_COLUMNS,
)


def _num_cell(value: Any) -> str:
    """A numeric cell: empty for None / non-numeric (the "unknown" sentinel),
    else the plain number (`repr` keeps an int an int and a float a float, so a
    token count round-trips as `4200`, not `4200.0`)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    return repr(value)


def _cell_to_float(cell: Any) -> float | None:
    """An empty numeric cell reads back as None (unknown), not 0.0. A garbage
    cell degrades to None (unpriced) rather than dropping the row — the same
    way the old YAML reader let a non-numeric `cost_usd` fall through to
    unpriced (the established "junk degrades to defaults" tolerance)."""
    text = (cell or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _cells_to_usage(row: Mapping[str, Any]) -> dict[str, int] | None:
    """Rebuild the nested usage dict from the four `usage_*` cells. All-empty =
    no usage captured (None); otherwise an empty or garbage cell within a
    captured group degrades to the ChatUsage default 0."""
    cells = {
        column.removeprefix("usage_"): (row.get(column) or "").strip()
        for column in _INVOCATION_USAGE_COLUMNS
    }
    if not any(cells.values()):
        return None
    return {key: _cell_to_int(text) for key, text in cells.items()}


def _cell_to_int(text: str) -> int:
    try:
        return int(text) if text else 0
    except ValueError:
        return 0


def invocation_record_to_csv_row(record: Mapping[str, Any]) -> dict[str, str]:
    """Flatten one in-memory record (the nested shape `AIInvocation.model_dump`
    produces) to a CSV cell dict keyed by `INVOCATION_CSV_COLUMNS`."""
    row = {
        column: (value if isinstance(value := record.get(column), str) else "")
        for column in _INVOCATION_STR_COLUMNS
    }
    row["cost_usd"] = _num_cell(record.get("cost_usd"))
    usage = record.get("usage")
    if isinstance(usage, Mapping):
        # A captured usage block: a missing subkey degrades to the ChatUsage
        # default 0, so the group is never mistaken for "no usage" on readback.
        for column in _INVOCATION_USAGE_COLUMNS:
            token = usage.get(column.removeprefix("usage_"))
            row[column] = _num_cell(token) if isinstance(token, (int, float)) else "0"
    else:
        # No usage captured: all four cells stay empty (the None sentinel).
        for column in _INVOCATION_USAGE_COLUMNS:
            row[column] = ""
    return row


def csv_row_to_invocation_record(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Rebuild the nested in-memory record from one `csv.DictReader` row, the
    inverse of `invocation_record_to_csv_row`. Returns None only for a
    structurally-truncated line — the sole drop reason. Every bad *value*
    degrades to its default (the old YAML reader's "junk counts, degraded"
    tolerance), so a hand-edited row still lands in the same rollups as the
    computed cost fields."""
    # A short row — fewer fields than the header — has None for the missing
    # trailing columns; a crash mid-append is the only thing that writes one.
    if any(value is None for key, value in row.items() if key is not None):
        return None
    record: dict[str, Any] = {
        column: (row.get(column) or "") for column in _INVOCATION_STR_COLUMNS
    }
    record["cost_usd"] = _cell_to_float(row.get("cost_usd"))
    usage = _cells_to_usage(row)
    if usage is not None:
        record["usage"] = usage
    return record


class AiInvocationsMixin:
    def _ai_invocations_path(self) -> Path:
        root = self._require_project()
        return root / "ai_invocations.csv"

    def _read_ai_invocations_raw(self) -> list[dict[str, Any]]:
        path = self._ai_invocations_path()
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            records = [csv_row_to_invocation_record(row) for row in csv.DictReader(handle)]
        return [record for record in records if record is not None]

    def _iter_invocation_rows(
        self, *, since: str | None = None, until: str | None = None
    ) -> Iterator[tuple[dict[str, Any], float | None, int, int]]:
        """The single tolerant scan of the ledger every summer routes
        through (#1708): yields `(record, cost_or_None, input_tokens,
        output_tokens)` per row, optionally restricted to an inclusive
        `YYYY-MM-DD` day range. Centralising "which rows count, and how a row
        is priced" here keeps the per-scene / per-chat / summary figures from
        drifting apart on a future edit — a hand-edited row can never make one
        summer disagree with another about a row."""
        for record in self._read_ai_invocations_raw():
            if not _in_day_range(record, since, until):
                continue
            input_tokens, output_tokens, cost = _row_measures(record)
            yield record, cost, input_tokens, output_tokens

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
        # Append one line — no read-modify-rewrite of the whole ledger. A crash
        # here loses at most this partial last line, which the reader skips
        # (#1801). The header is written only when the file is new/empty.
        path = self._ai_invocations_path()
        needs_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=INVOCATION_CSV_COLUMNS)
            if needs_header:
                writer.writeheader()
            writer.writerow(invocation_record_to_csv_row(invocation.model_dump()))
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

        # One node-index build serves every chat/scene/prompt label lookup,
        # built lazily on the first labelled row so an unlabelled ledger
        # never pays for it.
        index: Any = None

        def resolve_node(node_id: str) -> tuple[str, bool]:
            """(label, openable) for a node-keyed bucket. `openable` is True
            when the id still resolves to a live indexed node — a deleted /
            never-a-node id is inert (the frontend labels it "(deleted …)").
            A live but title-less node stays openable, falling back to its id
            as the label."""
            nonlocal index
            if index is None:
                index = self._build_node_index()
            entry = index.by_id.get(node_id)
            if entry is None:
                return node_id, False
            return (entry.title or node_id), True

        names = ("by_model", "by_chat", "by_scene", "by_prompt", "by_day")
        breakdowns: dict[str, dict[str, AICostBucket]] = {name: {} for name in names}
        totals = AICostSummary(total_cost_usd=None, count=0)

        for record, cost, input_tokens, output_tokens in self._iter_invocation_rows(
            since=since, until=until
        ):
            totals.count += 1
            totals.input_tokens += input_tokens
            totals.output_tokens += output_tokens
            if cost is None:
                totals.unpriced_count += 1
            totals.total_cost_usd = _add_cost(totals.total_cost_usd, cost)
            for name, key, label, openable in _bucket_targets(record, resolve_node):
                bucket = breakdowns[name].setdefault(
                    key, AICostBucket(key=key, label=label, openable=openable)
                )
                bucket.count += 1
                bucket.input_tokens += input_tokens
                bucket.output_tokens += output_tokens
                if cost is None:
                    bucket.unpriced_count += 1
                bucket.cost_usd = _add_cost(bucket.cost_usd, cost)

        totals.by_model = sorted(breakdowns["by_model"].values(), key=_cost_rank)
        totals.by_chat = sorted(breakdowns["by_chat"].values(), key=_cost_rank)
        totals.by_scene = sorted(breakdowns["by_scene"].values(), key=_cost_rank)
        totals.by_prompt = sorted(breakdowns["by_prompt"].values(), key=_cost_rank)
        totals.by_day = sorted(
            breakdowns["by_day"].values(), key=lambda bucket: bucket.key, reverse=True
        )
        # An empty scope is a known zero; rows with no priced row stay None.
        if totals.total_cost_usd is None and totals.count == 0:
            totals.total_cost_usd = 0.0
        return totals
