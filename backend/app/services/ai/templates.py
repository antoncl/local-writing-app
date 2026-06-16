"""Prompt template engine.

Templates are Jinja2 with two custom block-level directives:

- `{% role "system" %}…{% endrole %}` — marks the message role for the wrapped
  content. Only text inside role blocks is sent to the model.
- `{% cache_break %}` — emits a cache-control marker. Inside a role block it
  splits the content into multiple blocks; the block before the marker carries
  `cache_break_after=True`. Outside any role it is a warning.

The renderer returns a `RenderedTemplate` with:
- `messages: list[RenderedMessage]` — role-tagged message structures
- `warnings: list[str]` — author errors that don't break rendering

Sandboxing uses `jinja2.sandbox.SandboxedEnvironment` with `StrictUndefined`,
so typos in variable names raise rather than render empty.

Helpers (callable functions like `relevant_lore`, `text_before`) are registered
into the environment by `register_helpers()`; that lands in M2.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jinja2 import StrictUndefined, nodes
from jinja2.ext import Extension
from jinja2.sandbox import SandboxedEnvironment

ROLE_START = "\x00ROLE_START:"
ROLE_END = "\x00ROLE_END\x00"
CACHE_BREAK_MARKER = "\x00CACHE_BREAK\x00"
ROLE_START_SEP = "\x00"

VALID_ROLES = {"system", "user", "assistant"}


@dataclass
class ContentBlock:
    text: str
    cache_break_after: bool = False


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


class CacheBreakExtension(Extension):
    """`{% cache_break %}` — standalone marker, no body."""

    tags = {"cache_break"}

    def parse(self, parser):  # type: ignore[override]
        lineno = next(parser.stream).lineno
        return nodes.Output(
            [nodes.MarkSafe(nodes.Const(CACHE_BREAK_MARKER))]
        ).set_lineno(lineno)


def create_environment() -> SandboxedEnvironment:
    """Create a sandboxed Jinja2 env with the prompt extensions installed."""
    return SandboxedEnvironment(
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        extensions=[RoleExtension, CacheBreakExtension],
        undefined=StrictUndefined,
    )


def render_template(
    source: str,
    context: dict[str, Any] | None = None,
    *,
    env: SandboxedEnvironment | None = None,
) -> RenderedTemplate:
    """Render a template source into structured role-tagged messages.

    Raises Jinja's TemplateError subclasses for syntax errors and undefined
    variables. Author-mistake warnings (text outside roles, cache_break outside
    role, unknown role names) are collected on `RenderedTemplate.warnings`
    rather than raised.
    """
    env = env or create_environment()
    template = env.from_string(source)
    raw = template.render(**(context or {}))
    return _parse_marker_stream(raw)


def _parse_marker_stream(raw: str) -> RenderedTemplate:
    result = RenderedTemplate()
    cursor = 0
    length = len(raw)

    while cursor < length:
        role_start_idx = raw.find(ROLE_START, cursor)
        if role_start_idx == -1:
            _check_trailing_text(raw[cursor:], result)
            break

        if role_start_idx > cursor:
            _check_trailing_text(raw[cursor:role_start_idx], result)

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

        blocks = _split_on_cache_breaks(body)
        if blocks:
            result.messages.append(RenderedMessage(role=role_name, blocks=blocks))

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


def _check_trailing_text(segment: str, result: RenderedTemplate) -> None:
    cache_break_count = segment.count(CACHE_BREAK_MARKER)
    if cache_break_count:
        result.warnings.append(
            f"`cache_break` outside a role block has no effect "
            f"({cache_break_count} occurrence{'s' if cache_break_count > 1 else ''})."
        )
        segment = segment.replace(CACHE_BREAK_MARKER, "")
    if segment.strip():
        excerpt = segment.strip().splitlines()[0][:60]
        result.warnings.append(
            f"Text outside any role block is ignored: '{excerpt}…'"
            if len(excerpt) >= 60
            else f"Text outside any role block is ignored: '{excerpt}'"
        )


def _split_on_cache_breaks(body: str) -> list[ContentBlock]:
    if CACHE_BREAK_MARKER not in body:
        return [ContentBlock(text=body)] if body else []

    parts = body.split(CACHE_BREAK_MARKER)
    # Each split point is a cache breakpoint AFTER the preceding chunk.
    blocks: list[ContentBlock] = []
    for index, chunk in enumerate(parts):
        is_last = index == len(parts) - 1
        # A trailing cache_break leaves an empty last chunk; treat as
        # "cache after the previous content block".
        if is_last and chunk == "":
            if blocks:
                blocks[-1] = ContentBlock(
                    text=blocks[-1].text, cache_break_after=True
                )
            continue
        blocks.append(
            ContentBlock(text=chunk, cache_break_after=not is_last)
        )
    return [block for block in blocks if block.text or block.cache_break_after]


