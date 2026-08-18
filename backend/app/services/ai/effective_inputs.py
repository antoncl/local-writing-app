"""Resolve a prompt's EFFECTIVE inputs (ADR-0061).

A prompt declares its `inputs` on its front matter and references them in its
Jinja body as `{{ input.<name> }}`. A **snippet** (a `prompt:snippet`) is a
prompt with no invocation contract, pulled into another prompt's body by name
with `{% include "<name>" %}`. Today inclusion carries only the *text*, so the
snippet's input contract leaks upward: the including prompt must re-declare the
snippet's inputs by hand, or the strict-undefined render fails.

This module is the single resolver that makes a snippet carry its fields. A
prompt's **effective** inputs are its own declared `inputs` plus, recursively,
the `inputs` of every snippet it includes with a *literal* `{% include %}` tag.
It is a static function of the body's source — the input form must exist before
the template runs, so the set is gathered from the AST, never from executing the
body (ADR §2). One resolver, read by every surface (ADR §4); cycle and
recursion-depth guards live here.

The core (`resolve_effective_inputs`) is pure — it takes a `resolve_snippet`
callback rather than a `ProjectService`, so it unit-tests without a project.
`list_prompt_entries` builds the callback over the prompt entries it already
loaded (see `PromptEntriesMixin`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from jinja2 import nodes
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from app.models import PromptInputDefinition
from app.services.ai.templates import create_environment

# A backstop against a pathologically deep (but acyclic) include chain. Cycles
# are caught precisely by the on-path guard below; this only bounds depth so a
# hand-authored chain of hundreds of snippets can't exhaust the stack at gather
# time. Well above any realistic nesting.
_MAX_INCLUDE_DEPTH = 16


@dataclass(frozen=True)
class SnippetSource:
    """The pieces of a resolved `prompt:snippet` the resolver needs: `id` keys
    the cycle/dedup guards, `body` is recursed for its own includes, and
    `inputs` are the fields it contributes."""

    id: str
    body: str
    inputs: tuple[PromptInputDefinition, ...]


@dataclass(frozen=True)
class InputTypeConflict:
    """A same-name / different-type collision across included snippets (ADR §3).

    Nearer-wins cannot quietly absorb a *type* clash — a silent pick would let a
    change to one snippet break a prompt that includes both — so it is surfaced,
    never resolved. `types` are the distinct types seen for `name`, in encounter
    order; the first still wins in `EffectiveInputs.inputs` so a form renders.
    S2 surfaces this in the preview and editor; S1 detects and unit-tests it.
    """

    name: str
    types: tuple[str, ...]


@dataclass(frozen=True)
class EffectiveInputs:
    inputs: list[PromptInputDefinition]
    conflicts: list[InputTypeConflict]
    # Which snippet contributed each INHERITED input: name → source snippet id
    # (ADR-0061 §3, S3b). Keyed by every snippet-contributed name; a name the
    # outer prompt declares itself is absent (it is own, not inherited). The
    # nearer snippet wins the tag, like the definition it carries. The editor's
    # two-tier Inputs list reads this to render "inherited, from <snippet>"; the
    # id → title lookup is the reader's (the frontend holds the prompt roster).
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass
class _GatherState:
    """Mutable accumulator for the include-tree walk (phase 1). Threaded through
    the module-level `_visit`/`_offer` rather than closed over, so each stays a
    small, independently-tested function."""

    resolve_snippet: Callable[[str], SnippetSource | None]
    parse_env: SandboxedEnvironment
    max_depth: int
    gathered: dict[str, PromptInputDefinition] = field(default_factory=dict)
    # name → id of the snippet that first (nearest) contributed it (S3b).
    provenance: dict[str, str] = field(default_factory=dict)
    conflict_types: dict[str, list[str]] = field(default_factory=dict)
    on_path: set[str] = field(default_factory=set)  # ids on the current DFS path
    done: set[str] = field(default_factory=set)  # fully-visited ids (diamond skip)


def resolve_effective_inputs(
    body: str,
    own_inputs: Sequence[PromptInputDefinition],
    resolve_snippet: Callable[[str], SnippetSource | None],
    *,
    env: SandboxedEnvironment | None = None,
    max_depth: int = _MAX_INCLUDE_DEPTH,
) -> EffectiveInputs:
    """Compute the effective inputs of a prompt with `body` and `own_inputs`.

    `resolve_snippet(name)` maps an include name to its `SnippetSource` (or None
    when no such snippet exists — a dangling include contributes nothing, exactly
    as it renders to a `TemplateNotFound` later). `env` is an optional shared
    parse environment; callers resolving many prompts pass one so the sandboxed
    env is built once.
    """
    state = _GatherState(
        resolve_snippet=resolve_snippet,
        parse_env=env or create_environment(),
        max_depth=max_depth,
    )
    for name in literal_include_names(body, state.parse_env):
        child = resolve_snippet(name)
        if child is not None:
            _visit(state, child, 1)

    inputs = _overlay_own_inputs(own_inputs, state.gathered)
    conflicts = [InputTypeConflict(name=n, types=tuple(t)) for n, t in state.conflict_types.items()]
    # Only names the outer does NOT declare itself are inherited — the rest are
    # own (an override), so drop their provenance so the editor tiers them as own.
    own_names = {inp.name for inp in own_inputs}
    provenance = {name: source for name, source in state.provenance.items() if name not in own_names}
    return EffectiveInputs(inputs=inputs, conflicts=conflicts, provenance=provenance)


def _visit(state: _GatherState, snippet: SnippetSource, depth: int) -> None:
    """Pre-order DFS over an included snippet's inputs then its own includes, so
    a nearer definition wins over a farther one (nearer-wins, extended down the
    include depth). The on-path set catches cycles precisely; the done set skips
    re-walking a diamond; `max_depth` bounds a pathological acyclic chain."""
    if depth > state.max_depth or snippet.id in state.on_path or snippet.id in state.done:
        return
    state.on_path.add(snippet.id)
    try:
        for inp in snippet.inputs:
            _offer(state, inp, snippet.id)
        for name in literal_include_names(snippet.body, state.parse_env):
            child = state.resolve_snippet(name)
            if child is not None:
                _visit(state, child, depth + 1)
    finally:
        state.on_path.discard(snippet.id)
        state.done.add(snippet.id)


def _offer(state: _GatherState, inp: PromptInputDefinition, source_id: str) -> None:
    """Record the first-seen definition of each name; note a same-name /
    different-type clash across snippets as a conflict (the first still wins so a
    form renders). `source_id` is the snippet contributing this definition — kept
    for the first-seen (nearest) one, so the provenance tag names the snippet
    whose definition actually wins (S3b)."""
    existing = state.gathered.get(inp.name)
    if existing is None:
        state.gathered[inp.name] = inp
        state.provenance[inp.name] = source_id
        return
    if existing.type != inp.type:
        seen = state.conflict_types.setdefault(inp.name, [existing.type])
        if inp.type not in seen:
            seen.append(inp.type)


def _overlay_own_inputs(
    own_inputs: Sequence[PromptInputDefinition],
    gathered: dict[str, PromptInputDefinition],
) -> list[PromptInputDefinition]:
    """Overlay the outer prompt's own inputs onto the gathered snippet inputs. A
    name the outer declares AND a snippet contributes is owned by the snippet for
    existence + type; the outer overrides only default / label / hidden (ADR §3).
    The outer does NOT redefine the type even when it declares a different one —
    retyping an inherited input is a named anti-goal (deferred). Own-only names
    are the outer's outright. Own inputs come first, then the purely-inherited
    ones in gather order — the two-tier shape the editor will render in S3."""
    result: list[PromptInputDefinition] = []
    own_names: set[str] = set()
    for own in own_inputs:
        own_names.add(own.name)
        inherited = gathered.get(own.name)
        if inherited is None:
            result.append(own)
        else:
            result.append(
                inherited.model_copy(
                    update={"default": own.default, "label": own.label, "hidden": own.hidden}
                )
            )
    result.extend(inp for name, inp in gathered.items() if name not in own_names)
    return result


def literal_include_names(source: str, env: SandboxedEnvironment) -> list[str]:
    """The literal template names of every `{% include %}` in `source`, in
    document order. A dynamically-named include (`{% include input.x %}`) yields
    nothing — its name isn't knowable statically, so it can't contribute fields
    (ADR §2). A `{% include ["a", "b"] %}` list contributes each literal member.

    A body that fails to parse (malformed mid-edit) contributes no includes
    rather than raising — the render path surfaces the real syntax error later;
    gathering must degrade, matching `_parse_prompt_inputs`'s leniency.
    """
    # An include tag always spells the word "include"; without it there is
    # nothing to find, so skip building the AST for the common include-free body.
    if "include" not in source:
        return []
    try:
        ast = env.parse(source)
    except TemplateError:
        return []
    names: list[str] = []
    for node in ast.find_all(nodes.Include):
        template = node.template
        if isinstance(template, nodes.Const):
            if isinstance(template.value, str):
                names.append(template.value)
        elif isinstance(template, nodes.List):
            for item in template.items:
                if isinstance(item, nodes.Const) and isinstance(item.value, str):
                    names.append(item.value)
    return names
