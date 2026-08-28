"""Preview + generation dispatch.

Preview (`build_preview`) renders a template against a target scene and
returns structured messages. It does NOT call a model. M2.4.

Generation (`build_chat_payload` + caller) converts the rendered template
into the chat-API shape (system_prompt + alternating user/assistant
messages). The actual chat call lives in the route handler, which has
access to settings and policy. M4.0.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date as _date_cls
from typing import TYPE_CHECKING, Any, NoReturn

from jinja2 import TemplateError, TemplateSyntaxError, UndefinedError

from app.models import PreviewCacheBlock
from app.services.ai import tokens as ai_tokens
from app.services.ai.call_resolver import resolve_call_params
from app.services.ai.entry_ref import ProjectInfoRef
from app.services.ai.helpers import (
    EntryRef,
    _coerce_entry_ref,
    create_environment_for_project,
)
from app.services.ai.profiles.registry import profile_for
from app.services.ai.sessions import AISession, default_registry
from app.services.ai.templates import RenderedTemplate, render_template
from app.services.tree_structure import TreeStructureService

if TYPE_CHECKING:
    from app.services.ai.profiles import ModelDescriptor
    from app.services.machine_settings import MachineSettings


def _find_marked_target_scene_id(inputs: dict[str, Any]) -> str | None:
    """Scan context_pick input values for a scene ref marked as ★ target.

    The picker UI flags a single picked scene per input with `target: true`;
    if any input carries such a ref, the marked scene becomes the template's
    `scene` binding (overriding any caller-supplied target_scene_id). Returns
    the first match; the picker enforces at most one per input, but if two
    inputs each mark a scene, the first by iteration order wins.

    Frontend serializes context_pick values as JSON strings (see
    PromptInputField.svelte). Accept either a string or an already-decoded
    list so backend tests can pass plain Python structures.
    """
    for value in inputs.values():
        if isinstance(value, str):
            stripped = value.strip()
            if not (stripped.startswith("[") and stripped.endswith("]")):
                continue
            try:
                value = json.loads(stripped)
            except (ValueError, TypeError):
                continue
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            if item.get("target") and item.get("kind") == "manuscript":
                scene_id = item.get("id")
                if isinstance(scene_id, str) and scene_id:
                    return scene_id
    return None


def _coerce_inputs(project_service, schema: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    """ADR-0060 §2: coerce `context_pick` input values to `list[EntryRef]` at the
    bind layer, so the template author never learns the picks arrived as JSON on
    the wire (no `fromjson` filter — rejected alternative). A picker value is a
    JSON-encoded string of `[{id, kind, title, target?}, ...]`; parse it and wrap
    each item into an EntryRef (reusing the same coercion `entry()`/`use()` use).
    Non-picker values (plain strings, numbers, bools) pass through unchanged, so
    `entry(inputs.x)` still works for a single pick (it takes `[0]`)."""
    return {
        name: _coerce_input_value(project_service, schema, value)
        for name, value in inputs.items()
    }


def _coerce_input_value(project_service, schema: Any, value: Any) -> Any:
    """One input value, coerced: a JSON-list string of picked refs becomes a
    `list[EntryRef]`; anything else is returned untouched.

    The coercion keys on the *picker shape*, not merely a `[...]`-looking string:
    a `context_pick` always serializes as a JSON list of dicts (`{id, kind, …}`).
    A plain `text`/`long_text` input whose value happens to look like a JSON array
    of scalars (`["a","b"]`, `[1,2,3]`) is left as the author's string — otherwise
    it would silently become an empty `list[EntryRef]` and break `{{ inputs.x }}`."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return value
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return value
    if not isinstance(parsed, list):
        return value
    # Only a context_pick is a list of dicts; a scalar list is a plain value.
    if not all(isinstance(item, dict) for item in parsed):
        return value
    expanded = _expand_container_picks(project_service, parsed)
    refs: list[EntryRef] = []
    for item in expanded:
        ref = _coerce_entry_ref(project_service, schema, item)
        if ref is not None:
            refs.append(ref)
    return refs


def _expand_container_picks(
    project_service, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Replace a manuscript **container** pick (the manuscript root, an act, or a
    chapter) with its ordered descendant scene picks — ADR-0074 slice 4. A picked
    container stores one live ref; it materializes to its *current* scenes at
    render time, so a scene added to the container later is included without
    re-picking. Leaf scene picks, non-manuscript picks, and unresolved ids pass
    through untouched.

    The container test is structural, not a trust of the ref's `entry_type`: a
    manuscript-kind pick whose id resolves (via the structure tree) to a node
    carrying no `scene_id` is a container. Containers are not in the node index
    (they are structure-YAML nodes, not node files), so this resolves through
    `read_structure()` — the EntryRef/`read_scene` path cannot see them.

    No dedup: overlapping picks (a container and its own descendant scene) can't
    arise in normal use — the picker's absorb rule is the invariant that
    prevents them — so a straight expansion stays honest rather than masking a
    frontend bug.

    `read_structure()` is not free (it scans every scene's front matter), and
    the preview pane re-renders on a debounce while editing, so the common case
    — a prompt that picks only scenes — must not pay it. The `entry_type` tag is
    a *cheap gate*, not the expansion authority: a scene ref is tagged
    `manuscript:scene`, so anything manuscript-kind that isn't lets the load
    through, where the structural test (below) decides. A container ref always
    carries an act/chapter/root type, never `manuscript:scene`, so it is never
    gated out."""
    if not any(_might_be_container(item) for item in items):
        return items
    document = project_service.read_structure()
    out: list[dict[str, Any]] = []
    for item in items:
        container = _container_node_for_pick(document, item)
        if container is None:
            out.append(item)
            continue
        for scene_id in TreeStructureService.collect_descendant_scene_ids_ordered(container):
            out.append({"id": scene_id, "kind": "manuscript"})
    return out


def _is_manuscript_pick(item: dict[str, Any]) -> bool:
    return item.get("kind") == "manuscript" and bool(item.get("id"))


def _might_be_container(item: dict[str, Any]) -> bool:
    """A cheap gate for the structure load: a manuscript pick that is not
    explicitly tagged a scene might be a container. See `_expand_container_picks`
    — this only decides whether to look; `_container_node_for_pick` decides what
    is actually a container."""
    return _is_manuscript_pick(item) and item.get("entry_type") != "manuscript:scene"


def _container_node_for_pick(document, item: dict[str, Any]):
    """The container `StructureNode` a pick refers to, or None when the pick is
    not a manuscript container (a scene leaf, a non-manuscript pick, or an
    unresolved id — all left for the normal EntryRef coercion)."""
    if not _is_manuscript_pick(item):
        return None
    node = TreeStructureService.find_node(document, str(item["id"]))
    if node is None or node.scene_id:
        return None
    return node


class _DateProxy:
    """Exposes the current date as `date.today`, `date.iso`, and bare {{ date }}.

    Avoids confusion with Python's `date.today()` callable: `{{ date.today }}` returns
    the ISO string for today, not a method object.
    """

    def __init__(self, today: _date_cls) -> None:
        self._today = today

    @property
    def today(self) -> str:
        return self._today.isoformat()

    @property
    def iso(self) -> str:
        return self._today.isoformat()

    def __str__(self) -> str:
        return self._today.isoformat()


class PreviewError(Exception):
    """Raised when the template can't be rendered (syntax, undefined var, etc.).

    `line` and `col` are populated when the underlying Jinja2 error carries
    location info — surfacing them lets the editor pin a gutter marker on
    the offending line in the inline preview.

    `kind` is a coarse classification consumed by /api/ai/preview to populate
    `AIPreviewResponse.error.kind`; the frontend uses it (with `undefined_name`)
    to render a friendly message without re-parsing `message`.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 422,
        *,
        line: int | None = None,
        col: int | None = None,
        kind: str = "other",
        undefined_name: str | None = None,
        undefined_namespace: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.line = line
        self.col = col
        self.kind = kind
        self.undefined_name = undefined_name
        self.undefined_namespace = undefined_namespace


# UndefinedError messages from Jinja2 look like:
#   "'dict object' has no attribute 'character'"
#   "'ProjectInfo object' has no attribute 'language'"
#   "'character' is undefined"
_UNDEFINED_ATTR_RE = re.compile(r"'([^']+)' has no attribute '([^']+)'")
_UNDEFINED_NAME_RE = re.compile(r"'([^']+)' is undefined")


def _extract_undefined_ref(message: str) -> tuple[str | None, str | None]:
    """Return ``(undefined_name, object_type)`` from a Jinja UndefinedError.

    ``object_type`` is set only for an *attribute miss* (``'X object' has no
    attribute 'y'`` → ``('y', 'X')``); a bare undefined name (``'y' is
    undefined``) returns ``('y', None)``. The object type lets the caller tell a
    namespace attribute miss (``project.language``) apart from an undeclared
    input, which the leaf name alone cannot.
    """
    m = _UNDEFINED_ATTR_RE.search(message)
    if m:
        return m.group(2), m.group(1).removesuffix(" object")
    m = _UNDEFINED_NAME_RE.search(message)
    if m:
        return m.group(1), None
    return None, None


def _namespace_for_object_type(context: dict[str, Any], obj_type: str | None) -> str | None:
    """Reverse-map a Jinja object type name to its render-context namespace.

    Derived from the live ``context`` (not hardcoded), first key wins for aliased
    values. Since ADR-0060 §3 the ``scene`` / ``project`` namespaces are
    metadata-fallback wrappers (``EntryRef`` / ``ProjectInfoRef``) whose
    ``node.<field>`` access returns ``None`` for an absent key rather than raising
    an attribute miss — so they no longer reach this map; it still serves any
    plain namespace object (e.g. ``date``). ``inputs`` is deliberately excluded:
    undeclared/empty inputs keep their own dedicated messaging, which keys on the
    leaf name, not the namespace.
    """
    if not obj_type:
        return None
    # Jinja's object_type_repr qualifies app classes with their module
    # ("app.models.project.ProjectInfo object") but leaves builtins bare
    # ("dict object"); compare on the trailing class-name segment either way.
    short = obj_type.rsplit(".", 1)[-1]
    for key, value in context.items():
        if key == "inputs":
            continue
        if value is not None and type(value).__name__ == short:
            return key
    return None


@dataclass
class PreviewRequest:
    """The inputs to one preview render — everything except the project service.
    Bundled so the dispatch boundary takes one object instead of ten parallel
    args: the render inputs are a data clump; `project_service` is the dependency
    that stays a separate parameter.
    """

    template_source: str
    target_scene_id: str
    session_id: str | None
    inputs: dict[str, Any]
    text_before: str
    text_after: str
    commit: bool
    selection: str = ""
    resolution_scene_id: str = ""
    subject: str = ""


def build_preview(
    project_service, request: PreviewRequest
) -> tuple[RenderedTemplate, str | None]:
    """Render the template and return (output, session_id_used).

    `session_id_used` is None when no session was bound (caller did not supply
    one), so the response surface can report 'no caching' to the user.
    """
    template_source = request.template_source
    target_scene_id = request.target_scene_id
    session_id = request.session_id
    inputs = request.inputs
    text_before = request.text_before
    text_after = request.text_after
    commit = request.commit
    selection = request.selection
    resolution_scene_id = request.resolution_scene_id
    subject = request.subject

    # Mutation resolution scene, in precedence order (ADR-0012): an explicit
    # `scene_ref` input (the frontend resolves the input value into
    # `resolution_scene_id`) wins, then a scene marked ★ in a context_pick
    # input, then the caller's implicit target_scene_id, then — for a bound chat
    # — its `subject` when that subject is a scene (ADR-0051 S5: the old
    # target_scene_id field folded into subject; the index kind lookup is cheap).
    subject_scene_id = project_service._subject_scene_id(subject) if subject else ""
    effective_scene_id = (
        resolution_scene_id
        or _find_marked_target_scene_id(inputs)
        or target_scene_id
        or subject_scene_id
    )

    if effective_scene_id:
        try:
            scene = project_service.read_scene(effective_scene_id)
        except Exception as exc:  # noqa: BLE001
            raise PreviewError(
                f"Target scene not found: {exc}",
                404,
                kind="scene_not_found",
            ) from exc
    else:
        # Chat-routed prompts may not target a specific scene. Templates that
        # reference `scene` will see None and can guard with `{% if scene %}`.
        scene = None

    session: AISession | None = None
    if session_id:
        session = default_registry.get_or_create(session_id)
        # Each preview render is its own "what was pulled in this call" snapshot;
        # clear touched so we don't carry over IDs from a previous render.
        session.touched = {}

    env = create_environment_for_project(project_service, session=session)

    try:
        project_info = project_service.current_project()
    except Exception:  # noqa: BLE001
        project_info = None

    try:
        schema = project_service.read_metadata_schema()
    except Exception:  # noqa: BLE001
        schema = None

    # ADR-0060 §4 Amendment 2: the fixed default role envelope for un-roled prose —
    # a prompt type carries no behavior config, so this is always `system`.
    default_role = "system"

    # Wrap the loaded scene as an EntryRef so templates can write
    # `scene.pov.title` instead of `scene.metadata.pov.title`. The wrapper
    # pre-fills `loaded=` so .title / .body don't trigger a re-read,
    # and helpers reach the raw payload via _attr_or_item's EntryRef path.
    if scene is not None:
        scene = EntryRef(project_service, schema, scene.id, loaded=scene)

    # ADR-0060 §3: wrap the project node so a template reads `project.<field>`
    # off its authored metadata, `.metadata` kept as the whole-map escape.
    project_ref = (
        ProjectInfoRef(project_info, project=project_service, schema=schema)
        if project_info is not None
        else None
    )

    context = {
        "scene": scene,
        "project": project_ref,
        # ADR-0060 §7: `inputs` (plural — "the inputs, named"). Values are coerced
        # at this bind layer so a `context_pick` reaches the template as a
        # `list[EntryRef]`, not the raw JSON string it travels as on the wire.
        "inputs": _coerce_inputs(project_service, schema, inputs),
        "text_before": text_before,
        "text_after": text_after,
        "selection": selection,
        "date": _DateProxy(_date_cls.today()),
    }

    try:
        rendered = render_template(
            template_source, context=context, env=env, default_role=default_role
        )
    except TemplateError as exc:
        _raise_preview_error_from_template(exc, context)

    if session is not None and commit:
        session.commit()

    # ADR-0057 §2: carry the execution-derived lore gate off the env (set by the
    # `use_lore()` / `use()` helpers) onto the rendered result, so the preview
    # route can surface it and the chat can persist `lore_enabled`. The default
    # `[False]` covers an env that never registered the helpers.
    rendered.lore_invoked = bool(getattr(env, "lore_invoked", [False])[0])
    # ADR-0060 §2: carry the author-selected node ids off the env (set by `use()`)
    # onto the rendered result, so the chat can persist `used_node_ids` and the
    # send path unions them into its one lore selector.
    rendered.used_node_ids = list(getattr(env, "used_nodes", []) or [])
    # ADR-0060 §5: carry the per-node volatility priors (set by `use(node, hint)`)
    # so the chat can persist `used_node_hints` and the send path's tiering reads them.
    rendered.used_node_hints = dict(getattr(env, "used_hints", {}) or {})
    # ADR-0067 S2: carry the registered field-contract set off the env (set by
    # `{% do field_contract.store(f) %}`) onto the rendered result, so the chat
    # can persist `field_contract_stored` and the commit reads it back instead
    # of re-rendering a separate extractor.
    rendered.field_contract_stored = list(getattr(getattr(env, "field_contract", None), "stored", None) or [])
    # ADR-0060 §6: compute the send-path lore the model will receive so the
    # cache-aware preview can surface it (templates no longer emit lore). Only for a
    # lore-enabled prompt; `scene` is the same as-of anchor the send path resolves.
    if rendered.lore_invoked:
        rendered.send_lore_stable, rendered.send_lore_volatile = _preview_lore_tiers(
            project_service, scene, rendered.used_node_ids, rendered.used_node_hints
        )

    return rendered, session_id


def _preview_lore_tiers(
    project_service,
    scene: Any,
    used_node_ids: list[str],
    used_node_hints: dict[str, str],
) -> tuple[str, str]:
    """The send-path lore the model will receive, split into (stable, volatile) XML
    for the cache-aware preview (ADR-0060 §6). Mirrors the send path's selection +
    tiering (`_relevant_lore_ids` + `_tier_lore_ids`) but against a FRESH throwaway
    `AISession` — the cold turn-1 view (unhinted lore volatile; `use(node,
    "stable")` stable) — and never commits, so it cannot touch a live chat's cache
    baseline. Both tiers resolve as-of `scene`, like the send path.

    The journal is an EMPTY list, not `None` (#1477). A `None` journal drops the
    selector into its static body-hop (`_textual_one_hop` over entry BODIES), which
    the send never does from scene-derived roots — the send's depth-1 is
    conversation-driven (expand_context over the message). The scene `summary`
    scan, by contrast, now runs on BOTH paths (it moved to the selector's common
    path), so the preview and the send agree on it. Passing `[]` takes the same
    journal branch the send takes, with the turn-1 conversation (empty, nothing
    typed yet), so the preview shows exactly the message-independent floor a first
    send starts from — scene refs + `always` policy + the scene summary + `use()`
    picks + one structural hop — and never invents body-hop entries the wire won't
    carry. The author's own message then adds to that at send, which is new input
    the preview couldn't know."""
    from app.services.ai.helpers import (
        _relevant_lore_ids,
        _tier_lore_ids,
    )
    from app.services.ai.lore_block import _format_lore_block
    from app.services.ai.sessions import AISession

    ids = _relevant_lore_ids(
        project_service, scene, "implicit", [], list(used_node_ids or [])
    )
    if not ids:
        return "", ""
    stable_ids, volatile_ids = _tier_lore_ids(
        project_service, ids, AISession(id="preview"), dict(used_node_hints or {})
    )
    index = project_service.build_mutations_index() if scene is not None else None
    stable_xml = _format_lore_block(project_service, stable_ids, scene, index=index)
    volatile_xml = _format_lore_block(project_service, volatile_ids, scene, index=index)
    return stable_xml, volatile_xml


def _raise_preview_error_from_template(
    exc: TemplateError, context: dict[str, Any]
) -> NoReturn:
    """Translate a Jinja `TemplateError` into a `PreviewError` (HTTP 422),
    carrying the line, a `kind` tag, and — for an attribute miss on a real
    namespace object (`project.language`) — the namespace, so the frontend can
    say 'wrong path' instead of 'no input named language'.
    """
    # `lineno` is set for TemplateSyntaxError and most subclasses; for
    # UndefinedError it's typically missing. Surface what we have. Jinja2
    # doesn't expose column info on TemplateError; col stays None.
    line = getattr(exc, "lineno", None)
    undefined_namespace = None
    if isinstance(exc, UndefinedError):
        kind = "undefined"
        undefined_name, obj_type = _extract_undefined_ref(exc.message or "")
        undefined_namespace = _namespace_for_object_type(context, obj_type)
    elif isinstance(exc, TemplateSyntaxError):
        kind = "syntax"
        undefined_name = None
    else:
        kind = "other"
        undefined_name = None
    raise PreviewError(
        f"{type(exc).__name__}: {exc.message}",
        422,
        line=int(line) if isinstance(line, int) else None,
        kind=kind,
        undefined_name=undefined_name,
        undefined_namespace=undefined_namespace,
    ) from exc


def build_chat_payload(rendered: RenderedTemplate) -> tuple[str, list[dict[str, str]]]:
    """Convert a RenderedTemplate into a chat-API payload.

    System messages are concatenated into a single system_prompt string.
    User and assistant messages pass through in order, with two safety
    transforms: whitespace-only messages are dropped (an empty conditional
    in the template shouldn't emit a no-op turn), and consecutive
    same-role messages are coalesced (Anthropic rejects user/user or
    assistant/assistant pairs outright; this also keeps OpenAI happy).
    Other roles are ignored — warnings on the rendered template already
    flag them.

    Returns: (system_prompt, messages)
    """
    system_parts: list[str] = []
    chat_messages: list[dict[str, str]] = []
    for msg in rendered.messages:
        text = "".join(block.text for block in msg.blocks)
        if msg.role == "system":
            if text.strip():
                system_parts.append(text)
        elif msg.role in ("user", "assistant"):
            if not text.strip():
                continue
            if chat_messages and chat_messages[-1]["role"] == msg.role:
                chat_messages[-1]["content"] = chat_messages[-1]["content"].rstrip() + "\n\n" + text.lstrip()
            else:
                chat_messages.append({"role": msg.role, "content": text})
    system_prompt = "\n\n".join(system_parts)
    return system_prompt, chat_messages


@dataclass
class PreviewEstimate:
    """The token/cost estimate surfaced alongside a preview render (V2)."""

    provider: str | None
    model: str | None
    caching_style: str | None
    estimated_tokens: int
    cache_blocks: list[PreviewCacheBlock]
    # `estimated_cost_usd` is the SETTLED input cost — a repeat send with a warm
    # cache (stable prefix priced as cache reads); `estimated_first_cost_usd` is
    # the FIRST send (stable prefix priced as cache writes). Equal when the model
    # doesn't cache (#1052). Both None when pricing is unknown.
    estimated_cost_usd: float | None
    estimated_first_cost_usd: float | None


def _preview_send_blocks(
    rendered: RenderedTemplate, count: Any
) -> list[PreviewCacheBlock]:
    """The send-path composition the model will receive (ADR-0060 §6): the stable
    system prefix, the tier-tagged lore the backend will place (visible again now
    that templates no longer emit it), then the uncached conversation turns.
    `count(text)` returns the token count for a block."""
    blocks: list[PreviewCacheBlock] = []

    def add(label: str, role: str, text: str, tier: str | None) -> None:
        if text.strip():
            blocks.append(
                PreviewCacheBlock(
                    label=label, role=role, tokens=count(text), tier=tier, text=text
                )
            )

    system_text = "\n\n".join(
        m.text for m in rendered.messages if m.role == "system" and m.text.strip()
    )
    add("system", "system", system_text, "stable")
    add("stable lore", "system", rendered.send_lore_stable, "stable")
    add("volatile lore", "system", rendered.send_lore_volatile, "volatile")
    for message in rendered.messages:
        if message.role != "system":
            add(message.role, message.role, message.text, None)
    return blocks


async def estimate_preview_tokens_and_cost(
    project_service,
    rendered: RenderedTemplate,
    *,
    assistant_id: str | None,
    settings: MachineSettings,
) -> PreviewEstimate:
    """Estimate tokens + input cost for a rendered preview (V2).

    When an assistant is named, resolve its provider/model to pick the caching
    style and price the input; without one, tokens are still counted (the
    tokenizer choice is provider-agnostic in v1) but cost/caching stay unknown.

    `cache_blocks` is the send-path composition the model will receive (ADR-0060
    §6): the stable system prefix, the tier-tagged lore the backend will place
    (visible again now that templates no longer emit it), then the uncached
    conversation turns. `estimated_tokens` sums them, so it now includes the lore
    the older flattened-template count missed.
    """
    provider: str | None = None
    model: str | None = None
    caching_style: str | None = None
    descriptor: ModelDescriptor | None = None
    if assistant_id is not None:
        resolved = resolve_call_params(
            project_service,
            settings,
            assistant_id=assistant_id,
            provider_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        provider = resolved.provider or None
        model = resolved.model or None
        if provider:
            try:
                profile = profile_for(provider, settings)
                caching_style = profile.caching_style(model or "")
            except ValueError:
                caching_style = None
        if provider and model:
            descriptor = await ai_tokens.descriptor_for(
                provider=provider, model=model, settings=settings
            )

    counter_provider = provider or "anthropic"  # tokenizer choice is identical across providers in v1

    def _count(text: str) -> int:
        return ai_tokens.count_tokens(
            text, provider=counter_provider, model=model or "", settings=settings
        )

    cache_blocks = _preview_send_blocks(rendered, _count)
    estimated_tokens = sum(b.tokens for b in cache_blocks)
    # Cache-aware cost (#1052): the stable prefix (system + stable lore) is the
    # cacheable part; volatile lore and the conversation turns are never cached.
    # Price the prefix as cache reads (settled) vs writes (first send) when the
    # model caches. `descriptor` present with a zero rate still yields 0.0, not
    # None — the UI shows "€0.0000" rather than "—" (a known-free call, #697).
    stable_tokens = sum(b.tokens for b in cache_blocks if b.tier == "stable")
    other_tokens = estimated_tokens - stable_tokens
    caches = caching_style in ("auto", "explicit")
    estimated_cost_usd, estimated_first_cost_usd = ai_tokens.estimate_send_cost(
        stable_tokens, other_tokens, descriptor, caches
    )

    return PreviewEstimate(
        provider=provider,
        model=model,
        caching_style=caching_style,
        estimated_tokens=estimated_tokens,
        cache_blocks=cache_blocks,
        estimated_cost_usd=estimated_cost_usd,
        estimated_first_cost_usd=estimated_first_cost_usd,
    )
