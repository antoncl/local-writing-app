"""The snapshot diff: provenance-tagged runs over two states of a scene.

ADR-0044 §F/§G and Amendment 1, slice 2 of #395. The author parks on a notch and
the same region flips between two states under a tint that does not move; this
produces what the flip flips between.

**Warm = in the scene now, cool = in the snapshot.** An addition is `now`, a
deletion is `was`, and a modification is simply the two adjacent — three cases
that could drift apart reduced to one that cannot. Because the runs carry *all*
the text, one response serves all three view states: Both, Now and Snapshot are
three filters over one payload, not three requests.

**Computed here rather than in the browser, and at a discrete moment.** ADR-0025
defers server-side evaluation until something that cannot see the frontend needs
it, and two things do: the snapshot body lives on disk under `snapshots/` and the
frontend has never loaded it, and capture itself runs on the save path with no
browser in the loop — which is also where an accumulated-change capture trigger
would run if the sprinter case ever shows up (see `scene_snapshots`). A diff that
were only complete after a frontend pass could serve neither.

Amendment 1's contract, which the spike proved sufficient against all eighteen
fixtures:

> Every run is a complete markdown fragment, and is either inline-within-one-block
> or block-spanning — never both.

Three rules produce it:

1. **Blocks are diffed first**, and word granularity applies only where one block
   maps to one block — so no inline run can contain a blank line.
2. **Run boundaries snap out of inline constructs** (`markdown_scan`), an HTML
   comment counting as one, which is what keeps the markers whole.
3. **A block-spanning change is flagged `stacked`** and wrapped around the
   *rendered* output by the frontend, never injected into the source: no inline
   element can wrap two paragraphs.

Rule 2 costs precision — one word changed inside `**very tired**` marks the whole
emphasised phrase — and that is accepted: it is confined to the neighbourhood of
markup, and half-tinting an emphasised phrase reads worse than tinting all of it.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from app.models import DiffRun, FieldDiff, SnapshotDiff
from app.models.snapshots import SnapshotDiffRequest
from app.services.markdown_scan import (
    escapes_container,
    first_line_is_structural,
    protected_intervals,
)

# Blocks are separated by a blank line. The separator is kept as its own chunk
# so the runs still reassemble to the source byte for byte.
BLOCK_SPLIT = re.compile(r"(\n[ \t]*\n)")

# Word granularity the way a diff over prose has to do it: tokens are non-space
# runs and the whitespace between them, so a boundary always falls between
# tokens and reassembling the tokens reproduces the source exactly.
TOKEN = re.compile(r"\S+|\s+")

Interval = tuple[int, int]
Region = tuple[int, int, int, int]  # (was start, was end, now start, now end)

# How many passes `_settle` may take before giving up and stacking the block.
# Each pass only ever grows the changed regions, so a handful is generous — this
# is a guard against a future edit breaking that property, not a tuning knob.
SETTLE_PASSES = 12

# How much two blocks must still share to count as "the same block, rewritten"
# rather than two different blocks that happen to line up positionally. Half is
# a considered default, not a measured optimum: an author reworking a paragraph
# keeps far more than half of it, and two unrelated paragraphs of scene prose
# share only their common words. See `_is_a_rewrite_of` for why this is not the
# length threshold §F rules out.
SAME_BLOCK_RATIO = 0.5

# How far ahead `_align_blocks` looks for the block a block became. Small on
# purpose: splitting or merging a paragraph moves its neighbours by one or two,
# and a wider search starts pairing blocks that merely resemble each other.
ALIGN_LOOKAHEAD = 4


class SnapshotDiffMixin:
    """Composed onto `ProjectService`; resolves `_require_project`,
    `_path_for_node_id`, `_node_id_for_path`, `_read_markdown_with_front_matter`,
    `_snapshots_dir`, `_require_snapshot` and `_snapshot_source_id` via MRO."""

    def diff_snapshot(
        self, scene_id: str, snapshot_id: str, live: SnapshotDiffRequest
    ) -> SnapshotDiff:
        """The runs and the field flip, in one call.

        The live state arrives in the request rather than being read from disk.
        Autosave lags the buffer by up to six seconds, so the file is not
        reliably what the author is looking at — and parking is a *reading*
        gesture, which must not write. `read_scene` would give a state the
        author might never have seen.
        """
        root = self._require_project()
        node_id = self._snapshot_source_id(scene_id)
        record = self._require_snapshot(root, node_id, snapshot_id)
        front_matter, body = self._read_markdown_with_front_matter(
            self._snapshots_dir(root, node_id) / f"{snapshot_id}.md"
        )
        return SnapshotDiff(
            snapshot=record,
            runs=diff_runs(body, live.body),
            fields=_field_diffs(front_matter, live),
            title_was=str(front_matter.get("title") or ""),
            title_now=live.title,
        )


def diff_runs(was: str, now: str) -> list[DiffRun]:
    """Provenance-tagged runs over two markdown bodies, oldest state first."""
    was_blocks = BLOCK_SPLIT.split(was)
    now_blocks = BLOCK_SPLIT.split(now)
    runs: list[DiffRun] = []
    matcher = difflib.SequenceMatcher(None, was_blocks, now_blocks, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            runs.append(DiffRun(kind="equal", text="".join(was_blocks[i1:i2])))
        elif op == "insert":
            runs.append(DiffRun(kind="now", text="".join(now_blocks[j1:j2]), stacked=True))
        elif op == "delete":
            runs.append(DiffRun(kind="was", text="".join(was_blocks[i1:i2]), stacked=True))
        else:
            runs.extend(_align_blocks(was_blocks[i1:i2], now_blocks[j1:j2]))
    return _coalesce(runs)


def _align_blocks(was_blocks: list[str], now_blocks: list[str]) -> list[DiffRun]:
    """Pair the blocks of a changed region by *similarity*, not by position.

    difflib gives the region; it cannot say which block became which, because at
    block level none of them are equal. Position is the obvious answer and it is
    wrong: a paragraph split earlier in the scene shifts every later block by
    one, so "Maren did not run." lines up against "The eleventh was moored…".
    Word-diffing that pair interleaves two unrelated paragraphs into mush which
    still reassembles and still renders well-formed — every oracle passes and
    the author reads nonsense. Stacking it instead is honest but still shows the
    wrong two blocks side by side.

    So each block looks a little way ahead for the block it actually became. A
    block with no counterpart is what it looks like — inserted or deleted — and
    stacks alone. Found by driving the app, which is the only place it shows.
    """
    runs: list[DiffRun] = []
    i = 0
    j = 0
    while i < len(was_blocks) and j < len(now_blocks):
        if _is_a_rewrite_of(was_blocks[i], now_blocks[j]):
            runs.extend(_block_runs(was_blocks[i], now_blocks[j]))
            i, j = i + 1, j + 1
            continue
        # Bounded, because "the block it became" is a local question: an author
        # splits or merges a paragraph, they do not move one to the far end of
        # the scene. An unbounded search would pair across the whole region and
        # produce a worse answer than admitting there is no counterpart.
        ahead_now = _first_match(was_blocks[i], now_blocks, j + 1, j + 1 + ALIGN_LOOKAHEAD)
        ahead_was = _first_match(now_blocks[j], was_blocks, i + 1, i + 1 + ALIGN_LOOKAHEAD)
        if ahead_now is not None and (ahead_was is None or ahead_now - j <= ahead_was - i):
            runs.append(DiffRun(kind="now", text="".join(now_blocks[j:ahead_now]), stacked=True))
            j = ahead_now
        elif ahead_was is not None:
            runs.append(DiffRun(kind="was", text="".join(was_blocks[i:ahead_was]), stacked=True))
            i = ahead_was
        else:
            runs.extend(_stacked_pair(was_blocks[i], now_blocks[j]))
            i, j = i + 1, j + 1
    if i < len(was_blocks):
        runs.append(DiffRun(kind="was", text="".join(was_blocks[i:]), stacked=True))
    if j < len(now_blocks):
        runs.append(DiffRun(kind="now", text="".join(now_blocks[j:]), stacked=True))
    return runs


def _first_match(block: str, candidates: list[str], start: int, stop: int) -> int | None:
    for index in range(start, min(stop, len(candidates))):
        if _is_a_rewrite_of(block, candidates[index]):
            return index
    return None


def _is_a_rewrite_of(was: str, now: str) -> bool:
    """Whether these two blocks are the same block edited, or two different ones.

    **This is not §F's forbidden length threshold.** That rule says a *word
    count* must never decide inline-vs-stacked, because the layout would then
    jitter as the author types. This asks a structural question instead — is
    this the same paragraph, rewritten? — and the answer is stable under
    ordinary editing: adding a clause to a paragraph leaves it overwhelmingly
    itself, while a positional accident pairs two paragraphs sharing almost
    nothing.

    `quick_ratio` first because it is a cheap upper bound: if even the bag of
    words cannot reach the threshold, the real ratio certainly cannot.
    """
    was_tokens = TOKEN.findall(was)
    now_tokens = TOKEN.findall(now)
    if not was_tokens or not now_tokens:
        return False
    matcher = difflib.SequenceMatcher(None, was_tokens, now_tokens, autojunk=False)
    if matcher.quick_ratio() < SAME_BLOCK_RATIO:
        return False
    return matcher.ratio() >= SAME_BLOCK_RATIO


def _block_runs(was: str, now: str) -> list[DiffRun]:
    """Word-level runs within one block, with boundaries snapped out of
    constructs — or the whole block stacked when that cannot be done safely."""
    if was == now:
        return [DiffRun(kind="equal", text=was)]

    was_intervals = protected_intervals(was)
    now_intervals = protected_intervals(now)
    if was_intervals is None or now_intervals is None:
        return _stacked_pair(was, now)

    was_tokens = TOKEN.findall(was)
    now_tokens = TOKEN.findall(now)
    was_offsets = _offsets(was_tokens)
    now_offsets = _offsets(now_tokens)
    matcher = difflib.SequenceMatcher(None, was_tokens, now_tokens, autojunk=False)
    regions: list[Region] = [
        (was_offsets[i1], was_offsets[i2], now_offsets[j1], now_offsets[j2])
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
        if op != "equal"
    ]
    regions = _settle(regions, was, now, was_intervals, now_intervals)
    if regions is None:
        return _stacked_pair(was, now)

    if _needs_stacking(regions, was, now):
        return _stacked_pair(was, now)

    runs: list[DiffRun] = []
    was_cursor = 0
    for was_start, was_end, now_start, now_end in regions:
        if was_start > was_cursor:
            runs.append(DiffRun(kind="equal", text=was[was_cursor:was_start]))
        if was_end > was_start:
            runs.append(DiffRun(kind="was", text=was[was_start:was_end]))
        if now_end > now_start:
            runs.append(DiffRun(kind="now", text=now[now_start:now_end]))
        was_cursor = was_end
    if was_cursor < len(was):
        runs.append(DiffRun(kind="equal", text=was[was_cursor:]))
    runs = [run for run in runs if run.text]

    # The invariant this whole function exists to keep: the runs must still BE
    # the two documents. `_settle` establishes it, so this is a backstop rather
    # than the mechanism — but it is the backstop on losing an author's words,
    # so it fails safe into a coarser rendering rather than trusting the algebra.
    if not _reassembles(runs, was, now):
        return _stacked_pair(was, now)
    return runs


def _reassembles(runs: list[DiffRun], was: str, now: str) -> bool:
    return (
        "".join(run.text for run in runs if run.kind != "now") == was
        and "".join(run.text for run in runs if run.kind != "was") == now
    )


def _stacked_pair(was: str, now: str) -> list[DiffRun]:
    return [
        DiffRun(kind="was", text=was, stacked=True),
        DiffRun(kind="now", text=now, stacked=True),
    ]


def _needs_stacking(regions: list[Region], was: str, now: str) -> bool:
    """Whether this block cannot be wrapped inline at all, and must stack.

    Two ways a structured block defeats an inline wrapper, both found by the
    generated corpus rather than by reasoning:

    - **A change reaching the block's very start.** There is no position before
      a `> ` or `- ` marker to snap back to, so the wrapper would open ahead of
      the marker and the block stops being a blockquote or a list.
    - **A change escaping its container.** A run spanning a newline crosses into
      the next quoted line, list item or table row; a run spanning `|` crosses a
      table cell. Either way the parser tears the wrapper apart —
      `<td><span class="r-was">stone</td>` with a `<span>` that never closes.
    """
    return any(
        (region[0] == 0 and first_line_is_structural(was))
        or (region[2] == 0 and first_line_is_structural(now))
        or escapes_container(was, region[0], region[1])
        or escapes_container(now, region[2], region[3])
        for region in regions
    )


def _offsets(tokens: list[str]) -> list[int]:
    offsets = [0]
    for token in tokens:
        offsets.append(offsets[-1] + len(token))
    return offsets


def _snap(position: int, intervals: list[Interval], *, left: bool) -> int:
    for start, end in intervals:
        if start < position < end:
            return start if left else end
    return position


def _expand_out_of_constructs(
    regions: list[Region], was_intervals: list[Interval], now_intervals: list[Interval]
) -> list[Region]:
    """Grow every changed region until no boundary sits inside a construct.

    Expanding can make two regions touch, so this merges as it goes and repeats
    until nothing moves.
    """
    changed = True
    while changed:
        changed = False
        grown: list[Region] = []
        for region in regions:
            was_start, was_end, now_start, now_end = region
            wider = (
                _snap(was_start, was_intervals, left=True),
                _snap(was_end, was_intervals, left=False),
                _snap(now_start, now_intervals, left=True),
                _snap(now_end, now_intervals, left=False),
            )
            if wider != region:
                changed = True
            if grown and (wider[0] <= grown[-1][1] or wider[2] <= grown[-1][3]):
                previous = grown[-1]
                grown[-1] = (
                    previous[0],
                    max(previous[1], wider[1]),
                    previous[2],
                    max(previous[3], wider[3]),
                )
                changed = True
            else:
                grown.append(wider)
        regions = grown
    return regions


def _settle(
    regions: list[Region],
    was: str,
    now: str,
    was_intervals: list[Interval],
    now_intervals: list[Interval],
) -> list[Region] | None:
    """Snap the regions out of constructs, then make the gaps between them agree.

    **Why the second half exists.** Snapping happens independently on each side,
    because the constructs are each side's own — and a construct that exists on
    only one side (an author bolding a phrase they already wrote, which is the
    *common* edit) grows one boundary and not the other. The text between two
    regions is then no longer the same string on both sides, and an `equal` run
    taken from the `was` side stops reassembling the `now` side. That is losing
    the author's words, quietly, which is the one failure this feature exists to
    prevent — and it is invisible to the eighteen fixtures, which is how the
    spike's algorithm carried it. The generated corpus found it in 37 documents.

    The repair: wherever two gaps disagree, keep only their common prefix as
    shared text and absorb the remainder into the changed region. Regions only
    ever grow, so the loop terminates — in the worst case the whole block becomes
    one was/now pair, which is coarse and correct.

    **And it is bounded anyway.** That termination argument is a proof about code
    that can be edited, and this runs inside an HTTP handler: a wrong one costs a
    hung request rather than a wrong colour. So the loop gives up after
    `SETTLE_PASSES` and returns `None`, which stacks the block — the same safe
    degrade the scanner uses. Losing precision on a pathological block is cheap;
    hanging the backend is not.
    """
    for _ in range(SETTLE_PASSES):
        regions = _expand_out_of_constructs(regions, was_intervals, now_intervals)
        aligned: list[Region] = []
        was_cursor = 0
        now_cursor = 0
        changed = False
        for was_start, was_end, now_start, now_end in regions:
            common = _common_prefix(was[was_cursor:was_start], now[now_cursor:now_start])
            if was_cursor + common != was_start or now_cursor + common != now_start:
                was_start, now_start = was_cursor + common, now_cursor + common
                changed = True
            aligned.append((was_start, was_end, now_start, now_end))
            # BOTH cursors advance. They are the two sides' positions in their
            # own text, and the whole point of this pass is comparing the gap
            # between them — leaving `now_cursor` at zero makes the trailing
            # comparison always unequal and the loop never settles.
            was_cursor, now_cursor = was_end, now_end
        if aligned and was[was_cursor:] != now[now_cursor:]:
            # The trailing gap disagrees for the same reason; keep the common
            # suffix and give the rest to the last region.
            common = _common_suffix(was[was_cursor:], now[now_cursor:])
            first, _, third, _ = aligned[-1]
            aligned[-1] = (first, len(was) - common, third, len(now) - common)
            changed = True
        regions = _merge_touching(aligned)
        if not changed:
            return regions
    return None


def _common_prefix(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def _common_suffix(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[-1 - index] == right[-1 - index]:
        index += 1
    return index


def _merge_touching(regions: list[Region]) -> list[Region]:
    merged: list[Region] = []
    for region in regions:
        if merged and (region[0] <= merged[-1][1] or region[2] <= merged[-1][3]):
            previous = merged[-1]
            merged[-1] = (
                previous[0],
                max(previous[1], region[1]),
                previous[2],
                max(previous[3], region[3]),
            )
        else:
            merged.append(region)
    return merged


def _coalesce(runs: list[DiffRun]) -> list[DiffRun]:
    out: list[DiffRun] = []
    for run in runs:
        if not run.text:
            continue
        if out and out[-1].kind == run.kind and out[-1].stacked == run.stacked:
            out[-1] = out[-1].model_copy(update={"text": out[-1].text + run.text})
        else:
            out.append(run)
    return out


# ----- fields ---------------------------------------------------------------

# Front-matter keys that are not author-visible metadata, so a change in one is
# not something to flip: `id` is identity and never differs, and the rest are
# the file's own bookkeeping.
NON_FIELD_KEYS = frozenset({"id", "title", "schema_version"})


def _field_diffs(front_matter: dict[str, Any], live: SnapshotDiffRequest) -> dict[str, FieldDiff]:
    """Every field whose value differs, both sides carried.

    **No diff is computed on a value.** A field value is atomic — it resolves in
    one blink — so §F has fields flip rather than interleave, and the frontend
    needs only the pair.

    Front matter nests the author's fields under `metadata:` and keeps `status`
    beside it at the top level. The rail renders both as field rows, so the flip
    covers both — reading the top level as if it were the field map is how the
    flip would silently report nothing at all.
    """
    was: dict[str, Any] = {**(front_matter.get("metadata") or {})}
    now: dict[str, Any] = {**live.metadata}
    # Only compare status when the caller actually sent one. Otherwise silence
    # is read as "the author cleared it".
    if live.status is not None:
        was["status"] = front_matter.get("status", "")
        now["status"] = live.status
    keys = (set(was) | set(now)) - NON_FIELD_KEYS
    return {
        key: FieldDiff(was=was.get(key), now=now.get(key))
        for key in sorted(keys)
        if was.get(key) != now.get(key)
    }
