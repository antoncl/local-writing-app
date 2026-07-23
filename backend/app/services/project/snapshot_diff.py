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
from pathlib import Path
from typing import Any

from app.models import DiffRun, FieldDiff, SnapshotDiff
from app.models.snapshots import SnapshotDiffRequest
from app.services.markdown_scan import (
    escapes_container,
    first_line_is_structural,
    is_code_block,
    protected_intervals,
)

# Blocks are separated by a blank line. The separator is kept as its own chunk
# so the runs still reassemble to the source byte for byte.
#
# **`\r?\n` on both ends**, because this is a Windows-first app and a CRLF scene
# file is ordinary. Matching only `\n[ \t]*\n` made a whole CRLF document ONE
# block, so inline runs came to contain blank lines and a wrapper opened in one
# paragraph and closed in the next — rule 1 broken by the most common line
# ending we ship against.
#
# **And the separator is greedy over a RUN of blank lines.** Stopping at two
# newlines left the third heading the next chunk, so deleting one blank line of
# three emitted an inline run of a bare newline at line start — which marked
# reads as a raw-HTML block, swallowing the paragraph after it.
BLOCK_SPLIT = re.compile(r"(\r?\n(?:[ \t]*\r?\n)+)")

# Word granularity the way a diff over prose has to do it: tokens are non-space
# runs and the whitespace between them, so a boundary always falls between
# tokens and reassembling the tokens reproduces the source exactly.
TOKEN = re.compile(r"\S+|\s+")

def _is_whitespace(token: str) -> bool:
    """difflib's `isjunk`: an element that may not anchor a match.

    Whitespace is junk in the literal sense difflib means. A single space
    matches every other single space, so letting it anchor does two kinds of
    harm: it is the dominant term in the O(n·m) search that made a long
    paragraph take minutes, and it inflates `SequenceMatcher.ratio()` to ~0.5
    for ANY two prose blocks — which put `SAME_BLOCK_RATIO` on the noise floor
    and let `_align_blocks` word-diff two unrelated paragraphs into mush.

    Marking it junk fixes both at once and leaves the runs themselves unchanged:
    measured on real prose the changed regions are identical, while two
    unrelated paragraphs fall from 0.500 to 0.167.

    Not `autojunk=True`, which is far faster but ruins the diff: it junks any
    element appearing in >1% of the sequence, so in repetitive prose every
    common word stops anchoring and a two-word edit reports the whole remaining
    paragraph as changed.
    """
    return token.isspace()


Interval = tuple[int, int]
Region = tuple[int, int, int, int]  # (was start, was end, now start, now end)

# How many passes `_settle` may take before giving up and stacking the block.
# Each pass only ever grows the changed regions, so a handful is generous — this
# is a guard against a future edit breaking that property, not a tuning knob.
SETTLE_PASSES = 12

# Above this many tokens on either side, a block is diffed as a whole rather
# than word by word.
#
# `difflib`'s matcher is superlinear, and marking whitespace junk lowers the
# constant without changing that: with every third word edited, 600 tokens cost
# 0.12s, 2400 cost 0.88s, and it keeps climbing. This runs inside a synchronous
# route on a *reading* gesture, so an unbounded cost is a hung pane with nothing
# on screen explaining why — the same class of harm as a wrong render, which is
# why the bound is structural rather than a hope about input size.
#
# 2000 tokens is roughly a thousand-word paragraph: far beyond anything in
# fiction prose, and ~0.5s at the very worst. Past it the block stacks, which is
# the degrade this module already uses everywhere it cannot proceed safely.
MAX_WORD_DIFF_TOKENS = 2000

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
        was = self._snapshot_state(front_matter, node_id, self._snapshots_dir(root, node_id))
        return SnapshotDiff(
            snapshot=record,
            runs=diff_runs(body, live.body),
            fields=_field_diffs(was, live),
            title_was=was["title"],
            title_now=live.title,
        )

    def _snapshot_state(
        self, front_matter: dict[str, Any], node_id: str, path: Path
    ) -> dict[str, Any]:
        """The snapshot's title, status and metadata, normalised the way
        `read_scene` normalises the live side.

        **The two sides have to come off the same pipeline or the comparison is
        a lie.** The live values reach us through `read_scene`, which supplies
        defaults and heals the metadata; reading the snapshot's front matter raw
        made every one of those steps look like an authored change:

        - `status` absent means `"draft"` live but read as `""` here, so a scene
          that never set a status reported one changing on *every* park;
        - `title` absent falls back to the node id everywhere else, and to `""`
          here, so the title flipped on every park and the read-only title input
          rendered empty;
        - a reference to a deleted node is blanked live but kept in the byte
          copy, giving a phantom flip the author cannot reconcile;
        - an unquoted date parses to `datetime.date` here and arrives as a
          string live, painting a flip whose two sides render identically.

        **Validation deliberately does not run.** A snapshot is a historical
        record and may not satisfy today's schema; refusing to read it would
        make the compare view fail exactly when it is most wanted.
        """
        schema = self.read_metadata_schema()
        entry_type = str(front_matter.get("entry_type") or "scene:scene")
        metadata = self._normalise_metadata(front_matter.get("metadata"), path)
        metadata = self._strip_unknown_metadata_fields(metadata, entry_type, schema)
        metadata = self._strip_dangling_references(metadata, schema, self._build_node_index())
        return {
            "title": str(front_matter.get("title") or node_id),
            "status": str(front_matter.get("status") or "draft"),
            "metadata": metadata,
        }


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


def _too_large_to_diff(*blocks: str) -> bool:
    """Whether a block pair is past the point where word-level diffing is safe.

    Checked before **every** token-level matcher, which is the part that has to
    be got right: the first attempt put this only in `_block_runs`, and
    `_is_a_rewrite_of` runs `ratio()` over the same token lists *before*
    `_block_runs` is ever reached — so the guard never fired and a 4000-word
    paragraph still took 95 seconds. The hang had simply moved.
    """
    return any(len(TOKEN.findall(block)) > MAX_WORD_DIFF_TOKENS for block in blocks)


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
    # Too big to compare cheaply, so it is not a rewrite as far as this asks —
    # the caller stacks it, which is what an oversized block gets anyway.
    if max(len(was_tokens), len(now_tokens)) > MAX_WORD_DIFF_TOKENS:
        return False
    matcher = difflib.SequenceMatcher(_is_whitespace, was_tokens, now_tokens, autojunk=False)
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
    if _too_large_to_diff(was, now):
        return _stacked_pair(was, now)
    # Code never gets a word-level diff: a wrapper inside a fence is content,
    # so the reader would see the markup itself.
    if is_code_block(was) or is_code_block(now):
        return _stacked_pair(was, now)
    was_offsets = _offsets(was_tokens)
    now_offsets = _offsets(now_tokens)
    matcher = difflib.SequenceMatcher(_is_whitespace, was_tokens, now_tokens, autojunk=False)
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


def _field_diffs(was_state: dict[str, Any], live: SnapshotDiffRequest) -> dict[str, FieldDiff]:
    """Every field whose value differs, both sides carried.

    **No diff is computed on a value.** A field value is atomic — it resolves in
    one blink — so §F has fields flip rather than interleave, and the frontend
    needs only the pair.

    Both sides arrive already normalised — the snapshot's through
    `_snapshot_state`, the live one through `read_scene` — so what is left here
    is only the comparison. `status` is carried beside the field map because
    that is where the scene file keeps it, while the rail renders it as one
    field row among the others.
    """
    was: dict[str, Any] = {**was_state["metadata"]}
    now: dict[str, Any] = {**live.metadata}
    # Only compare status when the caller actually sent one. Otherwise silence
    # is read as "the author cleared it".
    if live.status is not None:
        was["status"] = was_state["status"]
        now["status"] = live.status
    keys = (set(was) | set(now)) - NON_FIELD_KEYS
    return {
        key: FieldDiff(was=was.get(key), now=now.get(key))
        for key in sorted(keys)
        if not _same_value(was.get(key), now.get(key))
    }


def _same_value(was: Any, now: Any) -> bool:
    """Whether two field values are the same *as the rail renders them*.

    A missing key and an empty one are the same absence to a reader — the row
    reads "(none)" either way — so reporting a flip between them shows the
    author two identical-looking values and no way to reconcile them. They
    arrive different for ordinary reasons: healing a reference to a deleted node
    blanks it to `""` rather than removing it, and a scene saved before a field
    existed simply has no key.

    `0` and `False` are values, not absences, so the check is explicit about
    the empty containers rather than leaning on truthiness.
    """
    empty = (None, "", [], {})
    was_blank = any(was is candidate or was == candidate for candidate in empty)
    now_blank = any(now is candidate or now == candidate for candidate in empty)
    if was_blank or now_blank:
        return was_blank and now_blank
    return bool(was == now)
