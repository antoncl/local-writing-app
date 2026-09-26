"""ADR-0096 §2: the save mints identity, for every kind.

Generalizes `_ensure_beat_identity` / `_mint_beat_id` (formerly `plot.py`,
ADR-0048 S7 Slice 3a, #779): for every list field whose group DECLARES
identity (`item_identity`, stamped by the resolver per ADR-0096 §1), give
each item lacking a value — or repeating an earlier item's — a fresh opaque
id. An item that already carries a unique id keeps it, so an edit never
changes it; a within-list collision (e.g. copy-pasting an item along with its
id) is re-salted until it lands outside the ids already claimed.

Auto-fill only — nothing here rejects. A blank item still saves and simply
gains an id, matching the sparse-spec principle.

Mint format: the two built-in plot groups (`plot_beat`, `plot_instance_beat`)
keep EXACTLY today's `beat_` + `sha256(title+salt)[:12]` (salt = a fresh
`uuid4().hex` per attempt) — nothing about their stored ids changes. Any
other group's ids use the `item_` prefix and salt the group's TITLE member
(ADR-0096 §1's vocabulary: its first `text` member other than the identity
member; `""` if there is none) instead of a hardcoded `title` key.

Called from every OWNED save path, after metadata normalisation and before
validation/write (§2 lists them); never on an override save (a list cannot be
overridden at all, so minting there would manufacture the very difference
that makes the save fail) and never inside `_validate_entry_metadata` (which
also runs on read)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from app.models.schema import MetadataSchema
from app.services.project.metadata_refs import title_member

# The two built-in groups whose ids must stay byte-for-byte what
# `_ensure_beat_identity` minted before this generalization (#779, #2260's
# trace reads them as beat ids). Every other group is "any other group" per
# ADR-0096 §2.
_BEAT_GROUP_IDS = frozenset({"plot_beat", "plot_instance_beat"})


def _mint_item_id(prefix: str, salt_text: str, taken: set[str]) -> str:
    """`<prefix><sha256(salt_text+salt)[:12]>`, salt = `uuid4().hex`. The salt
    text is folded into the hash but the per-mint salt alone guarantees
    uniqueness; the result is opaque, not a legible slug. Re-salted until it
    lands outside `taken`, so a fresh mint never re-introduces a collision."""
    while True:
        salt = uuid.uuid4().hex
        candidate = prefix + hashlib.sha256(f"{salt_text}{salt}".encode()).hexdigest()[:12]
        if candidate not in taken:
            return candidate


def ensure_list_item_identity(
    metadata: dict[str, Any], entry_type: str, schema: MetadataSchema
) -> dict[str, list[str]]:
    """Mint identity in place on `metadata`'s list fields for `entry_type`,
    for every field whose resolved item shape is a non-scalar group that
    declares identity. Returns `{field_id: [ids minted THIS call]}` (#2260),
    so a save-side trace can report which items got a fresh id vs. kept an
    existing one — mirroring `_ensure_beat_identity`'s `minted` return.
    Callers that don't trace simply ignore/discard it.

    `metadata` is mutated in place (each item dict updated with its id) and
    also returned as `metadata`'s own list values, matching the mutate-and-
    return convention `_ensure_beat_identity` used."""
    minted: dict[str, list[str]] = {}
    definition = schema.entry_types.get(entry_type)
    if definition is None:
        return minted
    for field_id in definition.fields:
        field = schema.fields.get(field_id)
        if field is None or field.type != "list" or field.item_scalar or not field.item_identity:
            continue
        items = metadata.get(field_id)
        if not isinstance(items, list):
            continue
        identity_key = field.item_identity
        prefix = "beat_" if field.item_group in _BEAT_GROUP_IDS else "item_"
        title_key = title_member(field) or ""
        seen: set[str] = set()
        field_minted: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue  # a non-dict item 422s in validation; leave it be
            value = item.get(identity_key)
            if isinstance(value, str) and value and value not in seen:
                seen.add(value)
                continue
            salt_value = item.get(title_key) if title_key else None
            salt_text = salt_value if isinstance(salt_value, str) else ""
            new_id = _mint_item_id(prefix, salt_text, seen)
            item[identity_key] = new_id
            seen.add(new_id)
            field_minted.append(new_id)
        if field_minted:
            minted[field_id] = field_minted
    return minted
