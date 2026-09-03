"""Tag node models (ADR-0082 slice 1).

A tag is a body-less node of kind `tag`, minted from a picker rather than
authored in an editor (§1). This module mirrors the `view`/`assistant` node
read + create/save shapes (`models_views.ViewNode`, `models/entries.py`
`AssistantEntry`) — slice 1 registers the kind on the read + create path only;
merge, rename-propagation and the `tags` field-type retirement are later
slices.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TagEntry(BaseModel):
    id: str
    title: str
    entry_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    # `""`, not `None` — the roster's `revision` was `undefined` on the wire,
    # so `saveTagEntry` sent no `base_revision` and the 409 staleness guard
    # never fired (review fix). Mirrors `AssistantEntry`.
    revision: str = ""
    # Layer provenance, as `ViewNode`/`AssistantEntry` carry it.
    source_layer_id: str = ""
    source_layer_label: str = ""


class TagEntryList(BaseModel):
    tags: list[TagEntry] = Field(default_factory=list)


class CreateTagEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "tag:tag"
    color: str | None = None
    # Where the new tag's file lands (same semantics as
    # CreateAssistantEntryRequest.layer_id):
    #   None → the open project when one is open, else the machine dir.
    #   ""   → the machine config dir explicitly.
    #   else → that layer by id.
    layer_id: str | None = None


class SaveTagEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    # No default (review fix): for a tag the entry type IS the vocabulary, so a
    # PUT that omits it must 422 rather than silently retype e.g. an assistant
    # tag as a general one.
    entry_type: str
    # Only `color` is meaningful today; the shape stays a dict so a future
    # field (e.g. `merged_into`, §5) needs no request-model change.
    metadata: dict[str, Any] = Field(default_factory=dict)
    base_revision: str | None = None
