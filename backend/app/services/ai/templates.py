"""Prompt template engine.

Templates are Jinja2 with one custom block-level directive:

- `{% role "system" %}…{% endrole %}` — marks the message role for the wrapped
  content. An override for multi-turn / mixed-role prompts (ADR-0060 §4): text
  outside any role block is homed to the base type's `default_role` (passed to
  `render_template`), not discarded, so a prose-only prompt just works.

`{% cache_break %}` is **retired** (ADR-0060 §5): the author no longer places cache
breakpoints. Caching is a provider-neutral volatility ordering the send path
produces and each provider adapter maps to its own primitive; author prose that
should cache already rides the stable system prefix automatically.

The renderer returns a `RenderedTemplate` with:
- `messages: list[RenderedMessage]` — role-tagged message structures
- `warnings: list[str]` — author errors that don't break rendering

Sandboxing uses `jinja2.sandbox.SandboxedEnvironment` with `StrictUndefined`,
so typos in variable names raise rather than render empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jinja2 import StrictUndefined, nodes
from jinja2.ext import Extension
from jinja2.sandbox import SandboxedEnvironment

ROLE_START = "\x00ROLE_START:"
ROLE_END = "\x00ROLE_END\x00"
ROLE_START_SEP = "\x00"

VALID_ROLES = {"system", "user", "assistant"}


@dataclass
class ContentBlock:
    text: str


@dataclass
class RenderedMessage:
    role: str
    blocks: list[ContentBlock]

    @property
    def text(self) -> str:
        return "".join(block.text for block in self.blocks)


@dataclass
class RenderedTemplate:
    messages: list[RenderedMessage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # ADR-0057 §2: whether the lore gate (`use_lore()` / `use()`) executed during
    # this render — the execution-derived lore gate. Set by `build_preview` from
    # the env's invocation slot; the preview route surfaces it as `lore_enabled`.
    lore_invoked: bool = False
    # ADR-0060 §2: node ids the template selected via `use(node)`, in insertion
    # order, deduped. Set by `build_preview` from the env's `used_nodes` slot;
    # persisted on the chat (`ChatSession.used_node_ids`) and unioned into the send
    # path's one lore selector. Empty when the template selected no nodes.
    used_node_ids: list[str] = field(default_factory=list)
    # ADR-0060 §5: per-node volatility priors from `use(node, "stable"|"volatile")`,
    # keyed by id. Carried beside `used_node_ids`, persisted on the chat, and read by
    # the send path's `_tier_lore_ids` as a revision-bounded placement bias. Empty
    # when no node carried a hint.
    used_node_hints: dict[str, str] = field(default_factory=dict)
    # ADR-0060 §6: the send-path lore the model will receive, split into the two
    # tiers, computed cold (a fresh throwaway session) by `build_preview` so the
    # cache-aware preview can surface it — templates no longer emit lore. Empty when
    # the prompt is not lore-enabled or selects nothing.
    send_lore_stable: str = ""
    send_lore_volatile: str = ""
    # ADR-0067 S2: the field descriptors registered via `{% do
    # field_contract.store(f) %}` during this render, in insertion order. Set by
    # `build_preview` from `env.field_contract.stored`; persisted on the chat
    # (`ChatSession.field_contract_stored`) beside `used_node_ids` so the commit
    # reads the SAME set back instead of re-rendering a separate extractor.
    field_contract_stored: list[dict[str, Any]] = field(default_factory=list)


class RoleExtension(Extension):
    """`{% role "system" %}…{% endrole %}` — wrap body with role markers."""

    tags = {"role"}

    def parse(self, parser):  # type: ignore[override]
        lineno = next(parser.stream).lineno
        role_arg = parser.parse_expression()
        body = parser.parse_statements(("name:endrole",), drop_needle=True)
        call = self.call_method("_wrap_role", [role_arg])
        return nodes.CallBlock(call, [], [], body).set_lineno(lineno)

    def _wrap_role(self, role: str, caller) -> str:  # type: ignore[no-untyped-def]
        body = caller()
        return f"{ROLE_START}{role}{ROLE_START_SEP}{body}{ROLE_END}"


def create_environment() -> SandboxedEnvironment:
    """Create a sandboxed Jinja2 env with the prompt extensions installed.

    `{% role %}` and `{% do %}` are the installed statement tags. `{% do %}`
    (Jinja's `ext.do`, ADR-0060 Am.1) evaluates an expression purely for its side
    effect and emits nothing — the correct construct for the side-effecting helpers
    (`{% do use(node) %}` records a lore pick; `{% do field_contract.store(f) %}`
    registers a field, ADR-0067). Without it the author's `{% do … %}` raises an
    `unknown tag 'do'` syntax error against the check.
    """
    return SandboxedEnvironment(
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        extensions=[RoleExtension, "jinja2.ext.do"],
        undefined=StrictUndefined,
    )


def render_template(
    source: str,
    context: dict[str, Any] | None = None,
    *,
    env: SandboxedEnvironment | None = None,
    default_role: str | None = None,
) -> RenderedTemplate:
    """Render a template source into structured role-tagged messages.

    Raises Jinja's TemplateError subclasses for syntax errors and undefined
    variables. Author-mistake warnings (e.g. unknown role names) are collected on
    `RenderedTemplate.warnings` rather than raised.

    `default_role` (ADR-0060 §4) is the prompt base type's default envelope: text
    outside any `{% role %}` block is emitted as a message of that role, in
    document order, instead of being discarded. `None` (the caller declared no
    default) keeps the legacy behaviour — loose text is ignored with a warning.
    """
    env = env or create_environment()
    template = env.from_string(source)
    raw = template.render(**(context or {}))
    return _parse_marker_stream(raw, default_role=default_role)


def _parse_marker_stream(raw: str, default_role: str | None = None) -> RenderedTemplate:
    result = RenderedTemplate()
    cursor = 0
    length = len(raw)

    while cursor < length:
        role_start_idx = raw.find(ROLE_START, cursor)
        if role_start_idx == -1:
            _home_loose_text(raw[cursor:], result, default_role)
            break

        if role_start_idx > cursor:
            _home_loose_text(raw[cursor:role_start_idx], result, default_role)

        sep_idx = raw.find(ROLE_START_SEP, role_start_idx + len(ROLE_START))
        if sep_idx == -1:
            result.warnings.append("Malformed role marker; rendering aborted.")
            break
        role_name = raw[role_start_idx + len(ROLE_START):sep_idx]

        body_start = sep_idx + len(ROLE_START_SEP)
        end_idx = _find_matching_role_end(raw, body_start)
        if end_idx == -1:
            result.warnings.append(
                f"Role block '{role_name}' missing end marker; rendering aborted."
            )
            break

        body = raw[body_start:end_idx]
        cursor = end_idx + len(ROLE_END)

        if role_name not in VALID_ROLES:
            result.warnings.append(
                f"Unknown role '{role_name}'. Valid roles: {sorted(VALID_ROLES)}."
            )

        if ROLE_START in body:
            # Nested role blocks aren't a coherent construct here. Drop the
            # outer wrapper, but still extract any messages the inner roles
            # produce so the author sees most of their intent.
            result.warnings.append(
                f"Nested role block inside '{role_name}' is not supported; "
                "outer role discarded, inner roles preserved."
            )
            inner = _parse_marker_stream(body)
            result.messages.extend(inner.messages)
            result.warnings.extend(inner.warnings)
            continue

        if body:
            result.messages.append(
                RenderedMessage(role=role_name, blocks=[ContentBlock(text=body)])
            )

    return result


def _find_matching_role_end(raw: str, start: int) -> int:
    """Return the index of the ROLE_END that closes the role opened just before
    `start`, skipping over any nested ROLE_START/ROLE_END pairs. Returns -1 if
    unmatched.
    """
    depth = 1
    cursor = start
    while True:
        next_start = raw.find(ROLE_START, cursor)
        next_end = raw.find(ROLE_END, cursor)
        if next_end == -1:
            return -1
        if next_start != -1 and next_start < next_end:
            depth += 1
            cursor = next_start + len(ROLE_START)
            continue
        depth -= 1
        if depth == 0:
            return next_end
        cursor = next_end + len(ROLE_END)


def _home_loose_text(
    segment: str, result: RenderedTemplate, default_role: str | None
) -> None:
    """Home un-roled text (ADR-0060 §4).

    Text outside any `{% role %}` block lands in a message of the base type's
    `default_role`, in document order, instead of being discarded. When no
    default is declared (`default_role is None`) the legacy behaviour stands: the
    text is ignored with a warning.
    """
    if not segment.strip():
        return
    if default_role is not None:
        result.messages.append(
            RenderedMessage(role=default_role, blocks=[ContentBlock(text=segment)])
        )
        return
    excerpt = segment.strip().splitlines()[0][:60]
    result.warnings.append(
        f"Text outside any role block is ignored: '{excerpt}…'"
        if len(excerpt) >= 60
        else f"Text outside any role block is ignored: '{excerpt}'"
    )


