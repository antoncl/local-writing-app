"""Template helpers — functions registered into the Jinja2 sandbox.

Two kinds of helpers:

- **Pure helpers** (`last_words`) need no project state and are always available.
- **Project-bound helpers** (`pov`, `story_so_far`, `entry`) need to look up
  nodes, walk the reference graph, or read prior scenes. They are registered by
  `register_helpers(env, project_service)` against a specific project.

Helpers return either strings (which render directly via `{{ helper(...) }}`)
or dicts (which support both attribute-style and key-style access in Jinja).
Pydantic node objects are never returned directly — templates should not
depend on the Pydantic API surface.

Sandbox notes:
- Sandboxed attribute access already blocks dunders. Returning dicts means
  templates can safely use `{{ pov(scene).title }}` or `{{ pov(scene)['title'] }}`.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from jinja2 import pass_context
from jinja2.sandbox import SandboxedEnvironment

from app.services.ai.entry_patch import (
    is_proposable_field,
)
from app.services.ai.entry_ref import EntryRef
from app.services.ai.field_contract import FieldContract
from app.services.ai.plot_prompt_context import render_plot_context
from app.services.ai.sessions import AISession
from app.services.error_log import append_error_line

if TYPE_CHECKING:
    from app.services.project_service import ProjectService

# Sentinel distinguishing "the `at=` anchor was omitted" (use the prompt's
# ambient scene) from "at=None passed explicitly" (book-start). See the `entry()`
# global in `register_helpers` (ADR-0060 §3).
_UNSET = object()

# Per-entry context policy. Default "auto" preserves the pre-policy
# alias-match behavior for every entry that omits the field.
#   - "always":      pulled into every implicit-mode render
#   - "auto":        textual alias match (current default)
#   - "manual_only": skipped by the matcher; explicit picker only
#   - "never":       hidden from picker and matcher
VALID_CONTEXT_POLICIES = {"always", "auto", "manual_only", "never"}
DEFAULT_CONTEXT_POLICY = "auto"


def _entry_context_policy(summary: Any) -> str:
    """Read the entry's context_policy metadata, clamped to a known value."""
    policy = _get_field(summary, "context_policy")
    if isinstance(policy, str) and policy in VALID_CONTEXT_POLICIES:
        return policy
    return DEFAULT_CONTEXT_POLICY

# Word splitter — same shape as project_service.WORD_PATTERN. Splitting on
# whitespace is a fine approximation for `last_words`.
_WS = re.compile(r"\s+")


# ----- Pure helpers --------------------------------------------------------


def last_words(text: Any, n: Any) -> str:
    """Return the trailing `n` words of `text`.

    - Empty / None text → "".
    - `n <= 0` → "".
    - If text has ≤ n words, the whole text is returned with its original
      whitespace preserved.
    """
    if text is None:
        return ""
    text_str = str(text)
    try:
        n_int = int(n)
    except (TypeError, ValueError):
        return ""
    if n_int <= 0 or not text_str.strip():
        return ""
    words = _WS.split(text_str.strip())
    if len(words) <= n_int:
        return text_str
    return " ".join(words[-n_int:])


def _coerce_entry_ref(
    project: ProjectService, schema: Any, value: Any
) -> EntryRef | None:
    """Helper backing the `entry()` Jinja global.

    Accepts a string id, an EntryRef (returns it unchanged), an object with
    an `.id` attribute, a context_pick value (list of {id, kind, ...} refs
    or its JSON-string form — first picked ref wins), or None.
    """
    if value is None or value == "":
        return None
    if isinstance(value, EntryRef):
        return value
    if isinstance(value, str):
        return _coerce_str_entry_ref(project, schema, value)
    if isinstance(value, list):
        if not value:
            return None
        return _coerce_entry_ref(project, schema, value[0])
    if isinstance(value, dict):
        inner_id = value.get("id")
        if isinstance(inner_id, str) and inner_id:
            return EntryRef(project, schema, inner_id)
        return None
    inner = getattr(value, "id", None)
    if isinstance(inner, str) and inner:
        return EntryRef(project, schema, inner)
    return None


def _use_values(value: Any) -> list[Any]:
    """Split a `use()` argument into the individual nodes it selects.

    A single pick (an id, EntryRef, or dict) is one node — `[value]`. A
    multi-select `context_pick` reaches the template as a **list** (the bind
    layer coerces it to `list[EntryRef]`, ADR-0060 §2), so `use(inputs.picks)`
    selects EVERY pick — the natural spelling of Journey A's explicit
    `{% for p in inputs.picks %}{{ use(p) }}{% endfor %}` loop, not just the
    first. A raw `[...]`-shaped JSON string (an un-coerced picker value) is
    unwrapped to its elements, mirroring `_coerce_entry_ref`'s own string
    handling; a non-list JSON string, or unparseable text, stays one value.

    Unlike `entry()` (which resolves a single node and takes `[0]` of a list on
    purpose), `use()` records — so a list must not silently collapse to its head.
    """
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, list):
                return parsed
    return [value]


def _record_use(
    project: ProjectService,
    schema: Any,
    value: Any,
    hint: Any,
    used_nodes_slot: list[str],
    used_hints_slot: dict[str, str],
) -> None:
    """Record a `use(node[, hint])` call into the per-render slots (ADR-0060 §2/§5):
    each resolved id into `used_nodes_slot` (deduped, insertion-ordered), and a valid
    volatility `hint` into `used_hints_slot` keyed by id (last hint wins). A
    multi-select `context_pick` list selects every pick (each element recorded),
    with the hint applied to all; a value that doesn't resolve, or an invalid hint,
    is a no-op. Module-level so the `use` closure in `register_helpers` stays
    trivial."""
    for item in _use_values(value):
        ref = _coerce_entry_ref(project, schema, item)
        if ref is None or not ref.id:
            continue
        if ref.id not in used_nodes_slot:
            used_nodes_slot.append(ref.id)
        if hint in ("stable", "volatile"):
            used_hints_slot[ref.id] = hint


def _coerce_str_entry_ref(
    project: ProjectService, schema: Any, value: str
) -> EntryRef | None:
    """Coerce a string arg to an EntryRef. A `context_pick` input serializes as
    a JSON list, so a `[...]`-shaped string is unwrapped to its first picked
    ref's id; a bare id string becomes an EntryRef directly.
    """
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            parsed = json.loads(stripped)
        except (ValueError, TypeError):
            return None
        return _coerce_entry_ref(project, schema, parsed)
    return EntryRef(project, schema, value)


def _coerce_entry_ref_as_of(
    project: ProjectService,
    schema: Any,
    value: Any,
    scene: Any,
    position: int | None = None,
    index: Any = None,
) -> EntryRef | None:
    """Resolve an entry **as of** a scene — the engine behind `entry(x)` /
    `entry(x, at=scene)` (ADR-0060 §3, was ADR-0055 §1's `entry_as_of`). The
    returned EntryRef's fields are overlaid with their effective value at
    `scene` (title/body and any mutated metadata field); unmutated fields keep
    their book-start value, read uniformly by attribute (`entry(x, at=s).rank`).

    `scene` accepts any form a `context_pick` / entity input carries — a bare
    scene id (the launch seed), the picker's JSON list (the writer's choice), a
    dict/EntryRef — resolved through `_coerce_entry_ref` like `entry()`'s own arg.

    Degrades to a plain book-start read (exactly `original(x)`) when there is no
    anchor — no/empty scene, a scene outside the manuscript, a non-lore or
    unmutated entry — so a subject-anchored prompt with no anchor set behaves as
    before.

    `position` is the optional within-scene cursor (`effective_state`'s
    `position`; default `END_OF_SCENE`, every marker in the scene live) — the
    `effective()` capability preserved on this path per ADR-0060 §3.
    """
    ref = _coerce_entry_ref(project, schema, value)
    if ref is None:
        return None
    scene_ref = _coerce_entry_ref(project, schema, scene)
    if scene_ref is None:
        return ref
    scene_id = scene_ref.id
    base = _safe_read_node(project, ref.id)
    if base is None:
        return ref
    try:
        overrides = project.effective_state(ref.id, scene_id, position, index)
    except Exception:
        overrides = {}
    # Read base once: hand it to the EntryRef as `loaded=` even with no overrides,
    # so a non-mutated subject (the common case) isn't re-read on attribute access.
    updates = _effective_overlay_updates(project, schema, base, overrides) if overrides else {}
    loaded = base.model_copy(update=updates) if updates else base
    return EntryRef(project, schema, ref.id, loaded=loaded)


def _effective_overlay_updates(
    project: ProjectService, schema: Any, base: Any, overrides: dict[str, Any]
) -> dict[str, Any]:
    """The `model_copy(update=...)` payload that overlays `effective_state`
    output onto a base lore entry: intrinsic title/body land on the entry,
    every other mutated field on a copy of `metadata` (scalars coerced to the
    field's native type, collections handed through as the list they resolve to)."""
    updates: dict[str, Any] = {}
    metadata = dict(getattr(base, "metadata", {}) or {})
    metadata_changed = False
    for field, raw in overrides.items():
        if field in ("title", "body"):
            updates[field] = raw if isinstance(raw, str) else str(raw)
        else:
            metadata[field] = _coerce_effective_value(project, schema, field, raw)
            metadata_changed = True
    if metadata_changed:
        updates["metadata"] = metadata
    return updates


def _coerce_effective_value(project: ProjectService, schema: Any, field: str, raw: Any) -> Any:
    """Coerce one `effective_state` value to its field's native type: a collection
    already resolves to the list to hand back as-is (ADR-0009); a scalar marker is
    a string that `_coerce_mutation_value` turns back into a number/bool/etc. so an
    as-of value matches a book-start value. Used by the `entry(x, at=…)` overlay."""
    if isinstance(raw, list):
        return raw
    field_def = getattr(schema, "fields", {}).get(field) if schema is not None else None
    field_type = getattr(field_def, "type", "") if field_def is not None else ""
    return project._coerce_mutation_value(raw, field_type)


def _fields(project: ProjectService, schema: Any, value: Any) -> list[dict[str, Any]]:
    """Backing the `fields()` Jinja global (ADR-0060 §3, was `field_catalog`).

    Returns the **full** field roster of a lore type as `{id, label, type,
    options, description, group, proposable}` descriptors, in the type's display
    order.
    Nothing is hidden and nothing is enforced: `proposable` is an **advisory**
    flag (structurally `false` for computed / reference / hidden fields) that the
    template reads and decides on — `{% for f in fields(x) if f.proposable %}` is
    the author's choice, not a gate (`author_vs_runtime_authority`: trust the
    designer). ``value`` may be an *entry* (revise mode — its resolved type is
    used) or an *entry_type FQN string* (create mode, §6.4 — no entry exists yet,
    so the type to draft is named directly). Empty when the type can't be
    resolved — the template degrades to a body-only instruction.
    """
    if schema is None:
        return []
    # A string may be an entry_type FQN (create mode) or an entry id (revise).
    # They share no namespace — a type is a key of schema.entry_types, an id is
    # not — so a string naming a known type is the type; anything else resolves
    # as an entry.
    if isinstance(value, str) and schema.entry_types.get(value) is not None:
        entry_type: str | None = value
    else:
        ref = _coerce_entry_ref(project, schema, value)
        entry_type = ref.entry_type if ref is not None else None
    definition = schema.entry_types.get(entry_type) if entry_type else None
    if definition is None:
        return []
    # `body` IS a proposable field (ADR-0059 §A), so it appears here — that is
    # what lets the brainstorm create seed list it with its description. Callers
    # that route body via the top-level "body" key instead of the fields object
    # (the extraction contract's loop; the revise-mode long_text value displays,
    # which already show `e.body` separately) filter it out with `f.id != "body"`.
    catalog: list[dict[str, Any]] = []
    for field_id in definition.fields:
        field = schema.fields.get(field_id)
        # `options` is always present (empty when the field has none) so the
        # create template can test `f.options` without hitting StrictUndefined.
        # For `list` fields the top-level options are SUPPRESSED: the select
        # sugar stores its choices on the field, but "one of: …" at field
        # level reads as a constraint on the field's own (non-array) value —
        # the choices belong to the item descriptor below.
        # Resolve the field's per-type label (#1009): a `field_overrides[id].label`
        # on the resolved type wins over the shared field def's name — the same
        # resolution the rail UI (`effectiveFieldLabel`) uses, so the model sees a
        # field by the name the author sees (e.g. `title` = "Name" on lore,
        # "Title" on scene) instead of always the global "Title".
        override = definition.field_overrides.get(field_id)
        descriptor: dict[str, Any] = {
            "id": field_id,
            "label": override.label if override and override.label else field.name,
            "type": field.type,
            "options": [opt.value for opt in field.options] if field.options and field.type != "list" else [],
            # Author help text (#1004): what the field is FOR, so the model
            # proposes on-target values. Always present (None when unset) so the
            # template can test `f.description` without hitting StrictUndefined.
            "description": field.description,
            # The field's section label (#784), so a template can reason about
            # fields BY their group — `{% for f in fields(e) if f.group == "GMO" %}`
            # renders an applied struct (Goal/Motivation/Obstacle) as one block.
            # It is the same `group` an L2 group application stamps on its members
            # and a manual section header uses; None when ungrouped. Always present
            # so the template can test `f.group` without hitting StrictUndefined.
            "group": field.group,
            # Advisory (ADR-0060 §3): whether it makes sense to ask the AI to
            # compute a value — `false` for computed / reference / hidden fields.
            # The template decides what to do with it; the roster is never
            # pre-filtered on it (retires the old `is_proposable_field` gate).
            "proposable": is_proposable_field(field_id, field),
        }
        # List fields (#698): describe the item shape so the model emits
        # legal items — flat scalars for item_type sugar, member-keyed maps
        # for a group shape. `items` mirrors the top-level descriptor shape
        # per member; templates test `f['items']` the way they test options.
        if field.type == "list" and field.item_members:
            # The resolver's tie-break verdict, never the raw declaration —
            # a cross-layer both-keys conflict would otherwise make this
            # describe a record list as a flat scalar array.
            descriptor["item_scalar"] = bool(field.item_scalar)
            descriptor["items"] = [
                {
                    "key": member.key,
                    "label": member.name or member.key,
                    "type": member.type,
                    "options": [opt.value for opt in member.options] if member.options else [],
                }
                for member in field.item_members
            ]
        catalog.append(descriptor)
    return catalog


def _field_value(project: ProjectService, schema: Any, entity: Any, field: Any) -> Any:
    """Backing the `field_value(entity, field)` Jinja global (#784).

    The value of one field on `entity`, addressed by id — the dynamic-access
    companion to `fields()`. `fields(e)` yields descriptors (`id`, `label`,
    `type`, `group`, …); `field_value(e, f)` reads the value for a descriptor OR
    a bare id, so a template can iterate a group and render each member's value
    without reaching through a `.metadata` map::

        {% for f in fields(e) if f.group == "GMO" %}
        {{ f.label }}: {{ field_value(e, f) }}
        {% endfor %}

    `title` / `body` are the node's intrinsic top-level values; every other id is
    a field on the node. An `entity_ref` value wraps to an `EntryRef` (the same
    resolution `e.<field>` gives), so `field_value(e, "patron").title` works.
    Returns None when the entity or the field id can't be resolved.
    """
    ref = _coerce_entry_ref(project, schema, entity)
    if ref is None:
        return None
    field_id = field.get("id") if isinstance(field, dict) else str(field)
    if not field_id:
        return None
    if field_id == "title":
        return ref.title
    if field_id == "body":
        return ref.body
    return ref.metadata.get(field_id)


def _type_name(schema: Any, entry_type: Any) -> str:
    """The human name of an entry_type FQN for a prompt instruction (ADR-0060 §7,
    was `entry_type_label`; ADR-0046 §6.4 create mode: "draft a new
    {{ type_name(inputs.entry_type) }}"). Falls back to the FQN's last segment,
    then the FQN itself, so a template never renders an empty noun."""
    fqn = entry_type if isinstance(entry_type, str) else ""
    if schema is not None and fqn:
        definition = schema.entry_types.get(fqn)
        if definition is not None and getattr(definition, "name", ""):
            return definition.name
    return fqn.rsplit(":", 1)[-1] if fqn else "entry"


# ----- Project-bound helpers ----------------------------------------------


def _plot_context(project: ProjectService, as_of: Any) -> str:
    """Render the spoiler-gated plot-board context for a prompt (ADR-0048 S8b).

    `as_of` is a card or scene node id (a plot-card brainstorm passes the card's
    own id, so the model sees the board up to and including that card's reveal
    position). A non-id / unknown anchor gates nothing (the whole board). Degrades
    to "" rather than raising, so a context helper never breaks the render — but
    the failure is recorded to the project error log (#386) instead of vanishing,
    so a silently-empty plot context is diagnosable rather than a mystery."""
    try:
        anchor = as_of if isinstance(as_of, str) and as_of else None
        return render_plot_context(project.read_plot_context(anchor))
    except Exception as exc:
        root = project.root_path  # None when no project is open; append_error_line never raises
        if root is not None:
            append_error_line(
                root,
                origin="backend",
                message=f"plot_context helper failed: {exc}",
                context="plot_context",
                level="warning",
            )
        return ""


def register_helpers(
    env: SandboxedEnvironment,
    project: ProjectService,
    session: AISession | None = None,
    journal: list[Any] | None = None,
) -> None:
    """Bind project-aware helpers to the given env. Idempotent.

    `session` and `journal` are accepted for API compatibility. They once fed
    the emitting `relevant_lore()` Jinja global, which ADR-0060 §2 retired (a
    template that emits lore double-includes it — ADR-0060 Context §3). The one
    lore selector — the internal `_relevant_lore` — now runs only on the send
    path (`chat.py::_lore_cache_blocks`), which threads its own session/journal
    directly; no Jinja global reads them here anymore.
    """
    try:
        schema = project.read_metadata_schema()
    except Exception:
        schema = None

    # Lazily built at most once per env, then shared by every mutation-aware
    # helper (`effective`, `relevant_lore`) so a template that resolves N entries
    # or scrubs many fields walks the manuscript once, not once per call — the
    # AI hot path (§3.3, ADR-0006). Templates that touch no mutations never build
    # it. Envs are per-render, so there's no cross-render staleness.
    _mutations_index_slot: list[Any] = []

    def _mutations_index() -> Any:
        if not _mutations_index_slot:
            try:
                _mutations_index_slot.append(project.build_mutations_index())
            except Exception:
                _mutations_index_slot.append(None)
        return _mutations_index_slot[0]

    # ADR-0057 §2: the execution-derived lore gate. `use_lore()` / `use()` record
    # that they ran into this per-render slot; the caller (build_preview) reads it
    # back after render to persist the chat's `lore_enabled`. The flag tracks
    # *invocation*, not a non-empty result — a lore-using prompt in a project
    # with no lore yet is still lore-enabled, so lore added later flows in. A
    # mutable slot (not a bare bool) so the nested helper flips it through the
    # closure; envs are per-render, so it never leaks across renders.
    lore_invoked_slot: list[bool] = [False]
    env.lore_invoked = lore_invoked_slot  # type: ignore[attr-defined]

    # ADR-0060 §2: the author-selection channel. `use(node)` records the resolved
    # node id into this per-render slot (deduped, insertion-ordered); `build_preview`
    # reads it back after render onto `RenderedTemplate.used_node_ids`, whence it is
    # persisted on the chat and unioned into the send path's one lore selector — the
    # SAME dedupped set `relevant_lore` owns, never a rival matcher (ADR-0057
    # anti-goal). A mutable list (not a bare local) so the nested helper appends
    # through the closure; envs are per-render, so it never leaks across renders.
    used_nodes_slot: list[str] = []
    env.used_nodes = used_nodes_slot  # type: ignore[attr-defined]

    # ADR-0060 §5: the optional volatility hint on `use(node, "stable"|"volatile")`,
    # keyed by resolved id. Carried beside `used_nodes` (not folded into it, so the
    # selector's id union is untouched) onto `RenderedTemplate.used_node_hints`,
    # persisted on the chat, and read by `_tier_lore_ids` as a revision-bounded
    # placement prior. Only valid hints land here; a node named twice keeps its
    # last hint.
    used_hints_slot: dict[str, str] = {}
    env.used_hints = used_hints_slot  # type: ignore[attr-defined]

    # ADR-0067 S1: the field contract accumulator. A prompt registers the fields
    # it commits to producing via `{% do field_contract.store(f) %}` and renders
    # their descriptor list with `{{ field_contract.render }}`; the commit path
    # reads `.stored` back as the shape to enforce (S2). One instance per render,
    # exposed as a global (for the template) and as an env attribute (for the
    # read-back) — the same per-render lifetime as `used_nodes` above.
    field_contract = FieldContract()
    env.field_contract = field_contract  # type: ignore[attr-defined]
    env.globals["field_contract"] = field_contract

    env.globals["last_words"] = last_words
    env.globals["pov"] = lambda scene: _pov(project, schema, scene)
    env.globals["story_so_far"] = lambda scene: _story_so_far(project, scene)

    # ADR-0057 §2 + docs/design/context-caching.md §4: the gate-only declaration.
    # A chat prompt that lets the backend place lore (the normal case) calls
    # `use_lore()` — it flips the lore-invoked gate but emits nothing, because the
    # send path selects, dedups, and places the lore itself, tiered stable/volatile
    # per the revision baseline. Emitting lore from the template instead bakes it
    # into the (frozen, sometimes uncached) prompt and double-counts against the
    # send-path block (ADR-0060 Context §3) — which is why the emitting
    # `relevant_lore()` global is retired; only the internal `_relevant_lore`
    # function survives, on the send path (chat.py).
    def _use_lore() -> str:
        lore_invoked_slot[0] = True
        return ""

    env.globals["use_lore"] = _use_lore

    # ADR-0060 §2/§5: `use(node)` / `use(node, "stable"|"volatile")` — "also include
    # *this* node in context." Coerces its argument to an EntryRef like `entry()`
    # (an id, an EntryRef, or a dict) and records the resolved id — but where a
    # multi-select `context_pick` is a LIST, it records EVERY pick (not `entry()`'s
    # first-wins), so `use(inputs.picks)` selects them all; `_use_values` owns the
    # split. Flips the lore gate (using a node means the chat is lore-enabled). The
    # optional second arg is an advisory volatility PRIOR (ADR-0060 §5): it biases
    # which tier the node starts in but never overrides the per-revision correctness
    # check (a "stable"-hinted node that changed still re-writes). Emits nothing —
    # the backend places and caches it — so it also composes inside a loop:
    # `{% for p in inputs.picks %}{{ use(p, "volatile") }}{% endfor %}`.
    def _use(value: Any, hint: Any = None) -> str:
        lore_invoked_slot[0] = True
        _record_use(project, schema, value, hint, used_nodes_slot, used_hints_slot)
        return ""

    env.globals["use"] = _use
    # ADR-0060 §3: one scene-anchored constructor. `entry(x)` resolves x **as of
    # the prompt's ambient `scene`** (the single ADR-0012 anchor) when there is
    # one, book-start when there is not — the common "this node as it is here"
    # default. `entry(x, at=s)` names an explicit anchor (a different scene, or a
    # picked scene); an explicit `at=None` forces book-start; `position=` is the
    # optional within-scene cursor. `@pass_context` hands the helper the render
    # context so it can read the ambient `scene` the template was invoked with —
    # the scene-less path skips building the mutations index it never needs.
    @pass_context
    def _entry(ctx: Any, value: Any, at: Any = _UNSET, position: int | None = None) -> Any:
        scene = ctx.get("scene") if at is _UNSET else at
        if scene is None or scene == "":
            return _coerce_entry_ref(project, schema, value)
        return _coerce_entry_ref_as_of(
            project, schema, value, scene, position, index=_mutations_index()
        )

    env.globals["entry"] = _entry
    # ADR-0060 §3: the one clearly-named book-start read, ignoring every mutation.
    env.globals["original"] = lambda value: _coerce_entry_ref(project, schema, value)
    env.globals["fields"] = lambda value: _fields(project, schema, value)
    env.globals["field_value"] = lambda entity, field: _field_value(project, schema, entity, field)
    env.globals["type_name"] = lambda value: _type_name(schema, value)
    env.globals["full_outline"] = lambda: _full_outline(project)
    env.globals["full_text"] = lambda: _full_text(project)
    env.globals["character_turns"] = (
        lambda scene, character: _character_turns(project, schema, scene, character)
    )
    env.globals["roleplay_beats"] = lambda scene: _roleplay_beats(project, scene)
    env.globals["is_a"] = lambda node, entry_type: _is_a(project, schema, node, entry_type)
    # The spoiler-gated plot-board context (ADR-0048 S8b) — a plot-card brainstorm
    # renders `{{ plot_context(as_of=e.id) }}` so the model reasons over the board
    # up to and including the card's reveal position, no future scenes leaked.
    env.globals["plot_context"] = lambda as_of=None: _plot_context(project, as_of)
    # ADR-0060 §7: the one JSON filter for values quoted to the model (#698),
    # `{{ value | json }}`. Jinja's built-in `| tojson` is htmlsafe_json_dumps: it
    # escapes ' & < > to \uXXXX and sorts keys — the model imitates both (escapes
    # persist into adopted values, and the member order contradicts the catalog).
    # This one preserves insertion order and emits readable text. Replaces the old
    # `plain_json()` global and `tojson`; there is one spelling now.
    env.filters["json"] = lambda value: json.dumps(value, ensure_ascii=False)


def create_environment_for_project(
    project: ProjectService,
    session: AISession | None = None,
    journal: list[Any] | None = None,
) -> SandboxedEnvironment:
    """Convenience: env with extensions and project helpers registered."""
    from app.services.ai.snippet_loader import PromptSnippetLoader
    from app.services.ai.templates import create_environment

    env = create_environment()
    # Without a loader, Jinja raises on any `{% include %}`; this resolves an
    # include name to a `prompt:snippet` entry so snippets can be reused (#771).
    env.loader = PromptSnippetLoader(project)
    register_helpers(env, project, session, journal)
    return env


# ----- Internal: data access -----------------------------------------------


def _is_a(project: ProjectService, schema: Any, node: Any, entry_type_fqn: Any) -> bool:
    """`is_a(node, "lore:character")` → true when the node's entry_type equals or
    descends from the given FQN via the schema `parent:` chain (ADR-0026).

    Inheritance-aware, unlike `entry.entry_type == "..."`: a `lore:deity` that
    inherits `lore:character` satisfies `is_a(entry, "lore:character")`. Falls
    back to exact match when the schema is unavailable. Templates use it to branch
    prompt logic on a type family."""
    if not isinstance(entry_type_fqn, str) or not entry_type_fqn:
        return False
    node_type = _get_field(node, "entry_type")
    if not isinstance(node_type, str) or not node_type:
        return False
    if schema is None:
        return node_type == entry_type_fqn
    return entry_type_fqn in project.entry_type_ancestry(node_type, schema=schema)


def _get_field(node: Any, key: str) -> Any:
    """Read `key` from a node's metadata, or from the node itself as fallback."""
    if node is None:
        return None
    metadata = _attr_or_item(node, "metadata")
    if isinstance(metadata, dict) and key in metadata:
        return metadata[key]
    return _attr_or_item(node, key)


def _attr_or_item(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, EntryRef):
        # Drill to the underlying Pydantic model so helpers see the raw
        # metadata dict and raw field values — EntryRef's attribute view
        # wraps entity_ref fields as EntryRefs, which breaks helpers like
        # pov() that need the raw lore id back. .id is preserved even when
        # the underlying load fails.
        loaded = obj._load()
        if loaded is None:
            return obj.id if key == "id" else None
        return getattr(loaded, key, None)
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _is_lore_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("lore_")


def _is_scene_id(value: Any) -> bool:
    return isinstance(value, str) and (
        value.startswith("scene_") or value.startswith("node_")
    )


def _collect_lore_refs_from_metadata(metadata: Any) -> set[str]:
    """Walk a metadata dict looking for lore IDs in entity_ref / list values."""
    found: set[str] = set()
    if not isinstance(metadata, dict):
        return found
    for value in metadata.values():
        if _is_lore_id(value):
            found.add(value)
        elif isinstance(value, list):
            for item in value:
                if _is_lore_id(item):
                    found.add(item)
    return found


def _safe_read_node(project: ProjectService, node_id: str) -> Any:
    """Best-effort read of any node by id (lore, scene, plot card, …).

    `use()` accepts any Node (ADR-0060 §2), so the lore-context renderer must be
    able to load whatever it was handed — not lore alone. Dispatches through the
    kind-resolving `read_node`; a missing or unreadable id yields None, and the
    caller skips it, exactly as the lore-only reader did before."""
    try:
        return project.read_node(node_id)
    except Exception:
        return None


def _scene_id_of(scene: Any) -> str | None:
    """The scene id from whatever a template passed as `scene` — a plain id
    string, a Scene/dict, or an EntryRef."""
    if isinstance(scene, str):
        return scene or None
    return _attr_or_item(scene, "id")


# ----- `pov(scene)` --------------------------------------------------------


def _pov(
    project: ProjectService, schema: Any, scene: Any
) -> EntryRef | None:
    """Return an EntryRef for the scene's POV character, or None.

    Looks for a `pov` field on the scene's metadata. If it's an entity_ref
    (a lore id), wraps it as an EntryRef so `pov(scene).title` /
    `pov(scene).aliases` work. If the field is a free-form string (no lore
    id), returns None — templates that need to display free-form text can
    read `scene.metadata.pov` directly.
    """
    raw = _get_field(scene, "pov")
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
        if not raw:
            return None
    if not _is_lore_id(raw):
        return None
    return EntryRef(project, schema, raw)


# ----- `story_so_far(scene)` ----------------------------------------------


def _story_so_far(project: ProjectService, scene: Any) -> str:
    """XML listing of summaries for all scenes before `scene` in manuscript order.

    Walks the manuscript structure depth-first, collecting scene summaries up
    to (but not including) the current scene. Wraps each as
    `<scene title="...">summary</scene>` inside a `<story_so_far>` block.
    Scope is the whole project; once nested-project support lands the scope
    will be the current book.
    """
    target_id = _attr_or_item(scene, "id")
    if not target_id:
        return ""
    try:
        structure = project.read_structure()
    except Exception:
        return ""

    chunks: list[str] = []
    _walk_collect(structure.root, target_id, project, chunks)
    if not chunks:
        return ""
    return "<story_so_far>\n" + "\n\n".join(chunks) + "\n</story_so_far>"


def _walk_collect(
    node: Any, target_id: str, project: ProjectService, chunks: list[str]
) -> bool:
    """Append `<scene>` entries for scene nodes preceding `target_id`.

    Returns True once `target_id` has been encountered (so the caller stops
    descending into later siblings).
    """
    node_scene_id = _attr_or_item(node, "scene_id")
    if node_scene_id and node_scene_id == target_id:
        return True
    if node_scene_id:
        full = None
        try:
            full = project.read_scene(node_scene_id)
        except Exception:
            full = None
        if full is not None:
            summary = _get_field(full, "summary")
            title = _attr_or_item(full, "title") or ""
            if isinstance(summary, str) and summary.strip():
                chunks.append(
                    f"<scene title={quoteattr(str(title))}>\n"
                    f"{xml_escape(summary.strip())}\n"
                    f"</scene>"
                )
    for child in _attr_or_item(node, "children") or []:
        if _walk_collect(child, target_id, project, chunks):
            return True
    return False


_XML_TAG_FALLBACK = "lore_entry"


def _xml_safe_tag(name: Any) -> str:
    """Coerce a node entry_type into a valid XML element name."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(name).strip())
    if not cleaned or not cleaned[0].isalpha() and cleaned[0] != "_":
        return _XML_TAG_FALLBACK
    return cleaned


# ----- `full_outline()` and `full_text()` ---------------------------------


class _OutlineNode(dict):
    """Plain dict carrying outline data, but with attribute access for Jinja.

    Templates can write `{{ node.title }}` and `{% for c in node.children %}`,
    matching the look of EntryRef without dragging EntryRef's lazy load along
    for what is essentially structural data.
    """

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.get(name)


def _full_outline(project: ProjectService) -> list[_OutlineNode]:
    """Manuscript outline as a list of nested nodes.

    Each node carries `title`, `summary`, `entry_type`, `scene_id`, and
    `children` (recursive). Walks the manuscript structure in document
    order. Containers (acts, chapters) carry their own title; the summary
    comes from the linked scene's metadata when present.
    """
    try:
        structure = project.read_structure()
    except Exception:
        return []
    return [_build_outline_node(child, project) for child in structure.root.children]


def _build_outline_node(node: Any, project: ProjectService) -> _OutlineNode:
    scene_id = _attr_or_item(node, "scene_id")
    title = _attr_or_item(node, "title") or ""
    summary = ""
    if scene_id:
        try:
            scene = project.read_scene(scene_id)
        except Exception:
            scene = None
        if scene is not None:
            raw_summary = _get_field(scene, "summary")
            if isinstance(raw_summary, str):
                summary = raw_summary.strip()
            if not title:
                title = _attr_or_item(scene, "title") or ""
    return _OutlineNode(
        title=str(title),
        summary=summary,
        entry_type=str(_attr_or_item(node, "type") or ""),
        scene_id=scene_id,
        children=[
            _build_outline_node(child, project)
            for child in (_attr_or_item(node, "children") or [])
        ],
    )


class _SceneText(dict):
    """Plain dict + attribute access. Same shape rationale as `_OutlineNode`."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.get(name)


def _full_text(project: ProjectService) -> list[_SceneText]:
    """Every scene's prose in manuscript order.

    Each item has `title`, `body`, `scene_id`, and `entry_type`. Skips
    structural containers that have no scene_id, since their body would be
    empty by design (containers carry only metadata).
    """
    try:
        structure = project.read_structure()
    except Exception:
        return []
    out: list[_SceneText] = []
    _collect_scene_text(structure.root, project, out)
    return out


def _collect_scene_text(
    node: Any, project: ProjectService, sink: list[_SceneText]
) -> None:
    scene_id = _attr_or_item(node, "scene_id")
    if scene_id:
        try:
            scene = project.read_scene(scene_id)
        except Exception:
            scene = None
        if scene is not None:
            sink.append(
                _SceneText(
                    title=str(_attr_or_item(scene, "title") or ""),
                    body=str(_attr_or_item(scene, "body") or ""),
                    scene_id=scene_id,
                    entry_type=str(_attr_or_item(scene, "entry_type") or ""),
                )
            )
    for child in _attr_or_item(node, "children") or []:
        _collect_scene_text(child, project, sink)


# ----- Character-thread reconstruction --------------------------------------

# Matches the comment-marker pair the frontend writes when accepting a
# roleplay continuation (see frontend/src/lib/utils/markdown.ts). The wrapper
# is preserved across save/reload as plain markdown; we re-discover it here to
# split the body into per-character segments at send time.
#
# A beat may also carry its character's PRIVATE interiority (ADR-0070) as an
# optional `;internal=<url-encoded>` field on the opening marker — hidden inner
# state bound to the beat. It is included only on the FOCUS character's own
# turns and stripped from every other character's (see `_thread_parts`).
CHARACTER_SPAN_PATTERN = re.compile(
    r"<!--\s*character:id=([A-Za-z0-9_-]+)(?:;internal=(\S*))?\s*-->"
    r"([\s\S]*?)<!--\s*/character\s*-->",
)

# The delimiter separating a beat's external prose from its interiority in the
# generation stream and in a replayed focus turn. ADR-0070: keep in lockstep
# with `INTERIORITY_MARKER` in frontend/src/lib/editor-core/interiority.ts and
# the literal in backend/app/builtin_library/prompts/roleplay.md.
INTERIORITY_MARKER = "[[interiority]]"


def _split_body_by_character_markers(
    body: str,
) -> list[tuple[str | None, str, str]]:
    """Return [(character_id | None, text, internal), …] for the body.

    Text outside any character marker becomes a (None, text, "") segment.
    Text inside `<!-- character:id=X -->…<!-- /character -->` becomes
    (X, text, internal), where `internal` is the decoded interiority payload
    from the optional `;internal=` field ("" when absent). Empty text segments
    are dropped.
    """
    if not body:
        return []
    segments: list[tuple[str | None, str, str]] = []
    cursor = 0
    for match in CHARACTER_SPAN_PATTERN.finditer(body):
        before = body[cursor:match.start()]
        if before:
            segments.append((None, before, ""))
        char_id = match.group(1)
        internal = unquote(match.group(2)) if match.group(2) else ""
        text = match.group(3)
        if text:
            segments.append((char_id, text, internal))
        cursor = match.end()
    tail = body[cursor:]
    if tail:
        segments.append((None, tail, ""))
    return segments


def _character_turns(
    project: ProjectService,
    schema: Any,
    scene: Any,
    character_input: Any,
) -> str:
    """Build a per-character chat thread from the scene's body markers.

    Must be used OUTSIDE any `{% role %}` block — emits its own
    role-tagged content using the same ROLE_START/ROLE_END markers
    the {% role %} extension produces, so the renderer's marker
    parser folds the output back into multiple alternating messages.

    Spans tagged with the FOCUS character (whoever `character_input`
    resolves to) become `assistant` messages. Spans tagged with any
    OTHER character become `user` messages prefixed `[Name]: `.
    Untagged narration is `user` with no prefix. No markers anywhere
    → first invocation; the whole body is one user-narration message.

    If the last message in the thread would be assistant (scene
    ended on the focus character's own turn), a short user nudge is
    appended so the chat API has a turn to respond to.
    """
    from app.services.ai.templates import ROLE_START

    focus_ref = _coerce_entry_ref(project, schema, character_input)
    focus_id = focus_ref.id if focus_ref else None
    body = _scene_body_text(scene)
    segments = _split_body_by_character_markers(body)

    # First invocation: no markers anywhere, the whole body is one
    # user-narration message. Empty body → nothing to emit.
    if not any(seg[0] for seg in segments):
        if body.strip():
            return _role_block("user", body)
        return ""

    # Resolve all character lore ids to titles for the [Name]: prefix.
    other_ids = {seg[0] for seg in segments if seg[0] and seg[0] != focus_id}
    titles = _character_titles(project, other_ids)

    parts = _thread_parts(segments, focus_id, titles)

    # Chat APIs need to end on a user turn so the model knows whose turn it is.
    # If the scene ended on the focus character's own span, append a synthetic
    # user nudge naming them.
    if parts and parts[-1].startswith(f"{ROLE_START}assistant"):
        focus_title = focus_ref.title if focus_ref else ""
        nudge = f"Continue as {focus_title}." if focus_title else "Continue."
        parts.append(_role_block("user", nudge))

    return "".join(parts)


def _role_block(role: str, text: str) -> str:
    """One role-tagged span using the same ROLE_START/ROLE_END markers the
    {% role %} extension emits, so the renderer's marker parser folds it back
    into a message.
    """
    from app.services.ai.templates import ROLE_END, ROLE_START, ROLE_START_SEP
    return f"{ROLE_START}{role}{ROLE_START_SEP}{text}{ROLE_END}"


def _scene_body_text(scene: Any) -> str:
    """The scene's body text — whether `scene` is an object with a `.body` str
    or a dict carrying `"body"`. Anything else yields empty.
    """
    if scene is None:
        return ""
    attr = getattr(scene, "body", None)
    if isinstance(attr, str):
        return attr
    if isinstance(scene, dict):
        value = scene.get("body")
        if isinstance(value, str):
            return value
    return ""


def _character_titles(project: ProjectService, other_ids: set[str]) -> dict[str, str]:
    """Map each non-focus character lore id to its title (falling back to the
    id) for the `[Name]: ` prefix on that character's user turns.
    """
    titles: dict[str, str] = {}
    for cid in other_ids:
        loaded = _safe_read_node(project, cid)
        title = getattr(loaded, "title", None) if loaded else None
        titles[cid] = str(title) if title else cid
    return titles


def _thread_parts(
    segments: list[Any], focus_id: str | None, titles: dict[str, str]
) -> list[str]:
    """Turn character-tagged body segments into alternating role blocks: the
    focus character's spans become `assistant`, other characters' become `user`
    prefixed `[Name]: `, untagged narration is plain `user`. Consecutive
    same-role segments coalesce into one turn.

    Interiority (ADR-0070) is per-character private: the focus character's own
    interiority is folded back into their `assistant` turns (in the same
    `[[interiority]]`-delimited shape the model produces, so the replayed
    conversation is self-consistent), while every OTHER character's interiority
    is dropped from their `[Name]: ` turns — no cross-character leak.
    """
    parts: list[str] = []
    current_role: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, current_role
        if buffer and current_role:
            joined = "".join(buffer).strip()
            if joined:
                parts.append(_role_block(current_role, joined))
        buffer = []

    for char_id, text, internal in segments:
        if char_id and char_id == focus_id:
            role = "assistant"
            content = _with_interiority(text, internal)
        elif char_id:
            # Another character's beat — interiority stripped (privacy).
            role = "user"
            content = f"[{titles.get(char_id, char_id)}]: {text}"
        else:
            role = "user"
            content = text

        if role != current_role:
            flush()
            current_role = role
        buffer.append(content)
    flush()
    return parts


def _with_interiority(text: str, internal: str) -> str:
    """Fold a focus beat's interiority back onto its external prose in the same
    `[[interiority]]`-delimited shape the model emits, so a replayed focus turn
    matches how the beat was generated. No interiority → the external prose
    unchanged.

    The trailing blank line matters when a character has two consecutive beats:
    the buffer joins coalesced spans directly, so without it one beat's
    interiority would run into the next beat's prose. It is stripped off the
    turn as a whole by `flush`, so a lone beat is unaffected.
    """
    if not internal.strip():
        return text
    return f"{text}\n\n{INTERIORITY_MARKER}\n\n{internal}\n\n"


def _roleplay_beats(project: ProjectService, scene: Any) -> str:
    """Lay out a roleplay scene's beats for a finalize/cleanup prompt (ADR-0070
    S3): each beat's speaker, its observable text, and — decoded — its private
    interiority, so the finalize prompt can project the scene to one character's
    POV (keeping that character's interiority as narration, cutting the rest).

    Unlike `character_turns`, this is POV-agnostic and not a chat thread: it emits
    one readable block naming every character's beats and interiority, and the
    finalize prompt decides whose interiority survives via `pov(scene)`. A scene
    with no markers (not roleplayed) returns its body unchanged.
    """
    body = _scene_body_text(scene)
    segments = _split_body_by_character_markers(body)
    if not any(seg[0] for seg in segments):
        return body
    ids = {seg[0] for seg in segments if seg[0]}
    titles = _character_titles(project, ids)
    lines: list[str] = []
    for char_id, text, internal in segments:
        text = text.strip()
        if not char_id:
            if text:
                lines.append(f"[Narration] {text}")
            continue
        name = titles.get(char_id, char_id)
        if text:
            lines.append(f"[{name}] {text}")
        internal = internal.strip()
        if internal:
            lines.append(f"[{name} — interiority] {internal}")
    return "\n\n".join(lines)
