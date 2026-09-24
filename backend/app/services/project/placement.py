"""Sibling order for the trees: a number between the neighbours (ADR-0094 §2).

A node in the manuscript or research tree carries its placement on its own
file — `parent` (the container's id; absent = the top of the tree) and `rank`
(a number; siblings ascend by it). This module is the pure half: reading a
rank, ordering a sibling group, and planning the writes a placement needs. The
service half (`TreeNodesMixin`) turns a plan into file writes.

The one invariant a plan keeps: **every intermediate state of its writes is in
the right order**, so a crash part-way through leaves the tree correct. That is
why a renumber assigns fresh ranks *above* the group's current highest, writes
the last sibling first, and covers the node being placed too — leaving the
mover out is exactly what breaks it (A=1, B=1, C=2; move C between A and B;
renumbering only A and B above 2 passes through A, C, B).
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

# The two front-matter keys placement lives in (ADR-0094 §1).
PARENT_KEY = "parent"
RANK_KEY = "rank"
PLACEMENT_KEYS = (PARENT_KEY, RANK_KEY)

# The node kinds that have a tree, and so carry placement.
TREE_KINDS = frozenset({"manuscript", "research"})

# A value between two neighbours that would need more decimal places than this
# makes the placement renumber instead (ADR-0094 §2). A readability limit, set
# far inside what the arithmetic can represent.
MAX_RANK_DECIMALS = 6


_PLACEMENT_LINE = re.compile(rb"^(?:parent|rank)[ \t]*:")
_PLACEMENT_LINE_TEXT = re.compile(r"^(?:parent|rank)[ \t]*:")
_ENTRY_TYPE_LINE = re.compile(r"^entry_type[ \t]*:")


def _front_matter_span(lines: list[str]) -> int | None:
    """Index of the closing `---` line when `lines` open with a front-matter
    block, else None. Delimiters are `---` alone at column 0, as the writers
    emit and the readers split on."""
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            return index
    return None


def content_without_placement(data: bytes) -> bytes:
    """A node file's bytes with its top-level `parent:` / `rank:` lines removed —
    what the save revision hashes (ADR-0094 §6), so a move or a renumber of its
    siblings never turns an open pane's next save into a conflict."""
    lines = data.splitlines(keepends=True)
    if not lines or lines[0].rstrip(b"\r\n") != b"---":
        return data
    kept = [lines[0]]
    for index in range(1, len(lines)):
        line = lines[index]
        if line.rstrip(b"\r\n") == b"---":
            kept.extend(lines[index:])
            return b"".join(kept)
        if not _PLACEMENT_LINE.match(line):
            kept.append(line)
    return data


def placement_lines(parent: object, rank: object, newline: str = "\n") -> list[str]:
    """The front-matter lines for a placement: `parent` when set, then `rank`
    when set. Values are dumped by YAML itself, so a hand-written oddity still
    round-trips as valid YAML."""
    lines: list[str] = []
    if parent is not None:
        lines.append(yaml.safe_dump({PARENT_KEY: parent}, allow_unicode=True).strip() + newline)
    if rank is not None:
        value = rank_to_yaml(rank) if isinstance(rank, Decimal) else rank
        lines.append(yaml.safe_dump({RANK_KEY: value}).strip() + newline)
    return lines


def set_placement_in_text(text: str, parent: object, rank: object) -> str:
    """`text` with its placement lines replaced — every other byte kept.

    The old `parent:` / `rank:` lines go and the new ones are inserted right
    after `entry_type:` (or at the end of the block when there is none), in the
    file's own line ending. Editing lines rather than re-dumping the mapping is
    what keeps a move to the one line it changes: a re-dump would restyle other
    keys, and the blank line the scene writer puts after the block would go too.
    `text` must be the file decoded as-is (no newline translation) — the caller
    writes the result back as bytes."""
    lines = text.splitlines(keepends=True)
    close = _front_matter_span(lines)
    if close is None:
        raise ValueError("a tree node's file must open with a front-matter block")
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    block = [line for line in lines[1:close] if not _PLACEMENT_LINE_TEXT.match(line)]
    insert_at = next(
        (index + 1 for index, line in enumerate(block) if _ENTRY_TYPE_LINE.match(line)),
        len(block),
    )
    block[insert_at:insert_at] = placement_lines(parent, rank, newline)
    return "".join([lines[0], *block, *lines[close:]])


def parse_rank(value: object) -> float | None:
    """A rank as read from front matter, or None when it is not a usable number.

    A YAML boolean is an `int` subclass in Python and a quoted "3" is a string;
    neither is a rank — both read as missing, so the missing-rank rule (sort
    last) covers them rather than a hand edit surprising the order."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def parse_parent(value: object) -> str | None:
    """A parent id as read from front matter, or None for the top of the tree."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def rank_sort_key(node_id: str, rank: float | None) -> tuple[bool, float, str]:
    """Siblings ascend by rank; ties by id; a missing rank after every ranked
    sibling, ties by id (ADR-0094 §2)."""
    return (rank is None, rank if rank is not None else 0.0, node_id)


def rank_to_yaml(rank: Decimal) -> int | float:
    """The value written to front matter: an int when integral, else the float
    whose shortest repr is the decimal itself (at most `MAX_RANK_DECIMALS`
    places, so the float round-trips it exactly for display)."""
    if rank == rank.to_integral_value():
        return int(rank)
    return float(rank)


def _as_decimal(rank: float) -> Decimal:
    # repr() is the shortest string that round-trips the float, so 2.3 is
    # Decimal("2.3"), not the binary expansion.
    return Decimal(repr(rank))


def rank_between(lower: float, upper: float) -> Decimal | None:
    """The shortest decimal strictly between `lower` and `upper`, nearest the
    midpoint, rounding half up; None when none fits in `MAX_RANK_DECIMALS`
    places (or the neighbours are not in ascending order).

    Between 2 and 3 it is 2.5; between 2 and 2.5 it is 2.3; then 2.2, 2.1, 2.05.
    If any value with *d* decimals lies strictly between the neighbours, the
    one nearest the midpoint does too, so rounding the midpoint at increasing
    *d* finds the shortest."""
    low, high = _as_decimal(lower), _as_decimal(upper)
    if low >= high:
        return None
    midpoint = (low + high) / 2
    for places in range(MAX_RANK_DECIMALS + 1):
        candidate = midpoint.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if low < candidate < high:
            return candidate
    return None


@dataclass(frozen=True)
class Sibling:
    """One member of a sibling group, as the group currently reads."""

    id: str
    rank: float | None


def _new_rank(others: Sequence[Sibling], position: int) -> Decimal | None:
    """The rank for a node inserted at `position` among `others` (the group
    without it), or None when the neighbours leave no room."""
    lower = others[position - 1] if position > 0 else None
    upper = others[position] if position < len(others) else None
    if (lower is not None and lower.rank is None) or (upper is not None and upper.rank is None):
        return None
    if lower is None and upper is None:
        return Decimal(1)
    if lower is None:
        assert upper is not None and upper.rank is not None
        return _as_decimal(upper.rank) - 1
    assert lower.rank is not None
    if upper is None:
        return _as_decimal(lower.rank) + 1
    assert upper.rank is not None
    return rank_between(lower.rank, upper.rank)


def plan_placement(group: Sequence[Sibling], node_id: str, position: int) -> list[tuple[str, Decimal]]:
    """The rank writes that put `node_id` at `position` in `group`, in order.

    `group` is the target sibling group as it currently reads, in order; it
    includes `node_id` when the node already sits in it (a reorder). `position`
    counts with the node removed from its old place — the index the frontend
    sends for a drop. Returns `(id, rank)` pairs to write in the order given;
    empty when the node already sits there.

    When no rank fits (§2), the whole group as it stands — mover included — is
    renumbered upward from above its highest rank, last member first, and the
    node is then placed among the renumbered ranks."""
    others = [sibling for sibling in group if sibling.id != node_id]
    position = max(0, min(position, len(others)))
    current = next((sibling for sibling in group if sibling.id == node_id), None)
    if (
        current is not None
        and current.rank is not None
        and [sibling.id for sibling in group].index(node_id) == position
    ):
        # Already there: the group without the mover, with the mover put back
        # at `position`, is the group as it reads. A node with no rank is not
        # "there" — it only sorts last by default — so it is always written.
        return []

    rank = _new_rank(others, position)
    if rank is not None:
        return [(node_id, rank)]

    writes: list[tuple[str, Decimal]] = []
    ranked = [_as_decimal(sibling.rank) for sibling in group if sibling.rank is not None]
    base = max(ranked).to_integral_value(rounding=ROUND_FLOOR) if ranked else Decimal(0)
    renumbered: dict[str, float] = {}
    for offset in range(len(group) - 1, -1, -1):
        new = base + 1 + offset
        writes.append((group[offset].id, new))
        renumbered[group[offset].id] = float(new)
    others = [Sibling(sibling.id, renumbered[sibling.id]) for sibling in others]
    rank = _new_rank(others, position)
    # Integers one apart always leave room (a midpoint at one decimal), and
    # an empty group places at 1; a None here would be a bug in this module.
    assert rank is not None
    if renumbered.get(node_id) != float(rank):
        writes.append((node_id, rank))
    return writes


# ---- placement writes are not saves (ADR-0094 §6) --------------------------
#
# The session-boundary snapshot rule (`maybe_capture_session_boundary`) reads a
# node file's modification time as "the last save". A placement write bumps it
# without an author touching the node, so a drag would suppress the next
# session's snapshot. Each placement write therefore records the mtime it
# produced beside the authored mtime it replaced; the boundary reads the
# authored one while the file still carries the placement write's mtime. The
# record is in memory: after a restart the boundary reads the plain mtime again,
# which fails safe (a missed snapshot, never a spurious one).

_placement_writes: dict[str, tuple[int, int]] = {}
_placement_writes_lock = threading.Lock()


def note_placement_write(path: Path, before_ns: int, after_ns: int) -> None:
    """Record that a placement write moved `path`'s mtime from `before_ns` to
    `after_ns`. A second placement write keeps the first one's authored time."""
    key = str(path.resolve())
    with _placement_writes_lock:
        previous = _placement_writes.get(key)
        authored = previous[1] if previous is not None and previous[0] == before_ns else before_ns
        _placement_writes[key] = (after_ns, authored)


def last_authored_mtime_ns(path: Path) -> int:
    """`path`'s mtime, unless the last write to it was a placement write — then
    the mtime it had before placement writes began."""
    current = path.stat().st_mtime_ns
    with _placement_writes_lock:
        record = _placement_writes.get(str(path.resolve()))
    if record is not None and record[0] == current:
        return record[1]
    return current
