"""Put a scene's mutation pills back after a finalize rewrite (#2435).

The finalize prompt shows the model each pill as a `⟦<id>⟧` marker
(`anchors_as_markers`); the model carries the markers through its prose. This
pure function maps them back to the ORIGINAL anchor/close comments, and appends
any pill the rewrite didn't place, so a finalize never loses one.
"""

from __future__ import annotations

import re

from app.services.project.mutation_anchors import pill_comments

# The editor's `MUTATION_MARKER_PATTERN` (`mutationMarkers.ts`) shape, backticks
# included (a model sometimes code-quotes a marker), but any id: legacy-derived
# anchor ids don't carry the minted `mut_` prefix, and an unmatched marker would
# be left in the prose. Only a KNOWN id or an unknown `mut_` id is consumed.
_MARKER = re.compile(r"`?⟦([A-Za-z0-9_-]+)⟧`?")


def place_pills(old_body: str, new_body: str) -> tuple[str, list[str]]:
    """`(body, unplaced_ids)`: `new_body` with each known marker replaced by its
    original comment (first occurrence only; a duplicate or unknown marker is
    removed), then every pill of `old_body` the model didn't place appended as a
    final paragraph in its old order. `unplaced_ids` names those appended pills."""
    originals = dict(pill_comments(old_body))
    placed: set[str] = set()

    def restore(match: re.Match[str]) -> str:
        pill_id = match.group(1)
        if pill_id not in originals:
            return "" if pill_id.startswith("mut_") else match.group(0)
        if pill_id in placed:
            return ""
        placed.add(pill_id)
        return originals[pill_id]

    body = _MARKER.sub(restore, new_body)
    unplaced = [pill_id for pill_id in originals if pill_id not in placed]
    if unplaced:
        tail = "\n".join(originals[pill_id] for pill_id in unplaced)
        body = f"{body.rstrip()}\n\n{tail}\n"
    return body, unplaced
