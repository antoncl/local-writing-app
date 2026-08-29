"""Abstract `ProviderProfile` + the dataclasses every concrete profile
returns. See [docs/ai-model-selection.md](../../../../../docs/ai-model-selection.md)
for the rationale and the conversation that fed it.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from app.services.machine_settings import MachineSettings

log = logging.getLogger(__name__)


class CapabilityTier(str, Enum):
    """High-level model picker: what the user picks before names.

    Cloud providers expose FAST/BALANCED/PREMIUM/REASONING; Ollama is
    LOCAL-only (no auto-rank within local since everything is free).
    """

    FAST = "fast"
    BALANCED = "balanced"
    PREMIUM = "premium"
    REASONING = "reasoning"
    LOCAL = "local"


class Capability(str, Enum):
    """Per-model flags. Drives Advanced disclosure surfacing later."""

    VISION = "vision"
    TOOLS = "tools"
    THINKING = "thinking"
    CACHING = "caching"
    # Opt-out, unlike the others: almost every model accepts a `temperature`,
    # so this flag is present by default and *absent* only for the families
    # below. The picker keys the read-only Temperature field on its absence
    # (#1554).
    TEMPERATURE = "temperature"


CachingStyle = Literal["none", "auto", "explicit"]
"""How the dispatch layer should mark cacheable content for a given model.

- `none`: provider does not cache; no markup
- `auto`: provider caches transparently (most OpenRouter routes, OpenAI direct)
- `explicit`: wrap stable content with `cache_control: ephemeral` (Anthropic
  direct, Anthropic/Alibaba/Gemini via OpenRouter)
"""


def family_from_id(model_id: str) -> str:
    """The catalogue family a model groups under (ADR-0073 S3) — a slim,
    presentation-neutral facet derived from the id, no curation table.

    Slash-namespaced ids (OpenRouter `qwen/qwen-2.5-72b`, `anthropic/claude-…`)
    group by the vendor prefix; a native id groups by its leading alphabetic
    run before the first digit or separator (`claude-3-5-sonnet` → `claude`,
    `gpt-4o` → `gpt`, `o3` → `o`). Lower-cased so `Qwen/…` and `qwen/…` land in
    one bucket.
    """

    ident = model_id.strip().lower()
    if "/" in ident:
        return ident.split("/", 1)[0]
    match = re.match(r"[a-z]+", ident)
    return match.group(0) if match else ident


# Model families whose API rejects a `temperature` parameter — sampling was
# removed on the newest Anthropic families (Opus 4.7/4.8/5, Sonnet 5, Fable 5,
# Mythos 5). This lives here, provider-neutral, because the *same* model is
# reachable through more than one provider: OpenRouter serves it as
# `anthropic/claude-opus-4-8`. `family_supports_temperature` strips any leading
# `provider/` route segment before matching, so the rule catches the model on
# every route, not just the native Anthropic id (#1554). Anthropic 4.6 and older
# (incl. Haiku 4.5) still accept temperature and are deliberately absent.
NO_TEMPERATURE_FAMILIES: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)


def family_supports_temperature(model_id: str) -> bool:
    """Whether `model_id`'s family accepts a `temperature` parameter.

    False only for `NO_TEMPERATURE_FAMILIES`. The id is matched with any leading
    `provider/` route segment stripped (`anthropic/claude-opus-4-8` → checked as
    `claude-opus-4-8`) so an OpenRouter/other route to a no-sampling model is
    caught the same as the native id. Variant suffixes (`:free`, `:beta`) ride
    along after the family prefix and still match via `startswith`.
    """
    base = model_id.split("/", 1)[-1]
    return not any(base.startswith(p) for p in NO_TEMPERATURE_FAMILIES)


@dataclass
class ModelDescriptor:
    """One row in a provider's catalogue. Fields that are unknown at
    discovery time (e.g. pricing for providers that don't publish it) stay
    None; v1 tolerates this and falls back to bake-in data.
    """

    id: str
    display_name: str
    provider: str
    context_window: int
    tier: CapabilityTier
    capabilities: set[Capability] = field(default_factory=set)
    deprecated: bool = False
    sunset_date: date | None = None
    successor: str | None = None
    cost_in_per_mtok: float | None = None
    cost_out_per_mtok: float | None = None
    cache_read_multiplier: float | None = None
    # ADR-0073 S4: False marks a model surfaced from LIVE discovery that has no
    # hand-audited baked-in entry — an Anthropic/OpenAI model newer than the
    # audit file, shown with a derived tier and its raw id as the name so Refresh
    # stops hiding it. Baked-in rows (and the live-primary OpenRouter/Ollama
    # catalogues, which have no audit list to be absent from) stay True. The
    # picker badges the False ones "new".
    verified: bool = True
    # The provider's own signal on whether this model accepts a `temperature`
    # parameter. Default True; OpenRouter sets it from the route's published
    # `supported_parameters`. Combined with the family rule by
    # `accepts_temperature` — never read this raw for the effective answer.
    supports_temperature: bool = True
    # The model's published max OUTPUT tokens — distinct from `context_window`
    # (the input budget). Used to clamp a request's `max_tokens` down so we never
    # ask a model for more than it allows (Anthropic/OpenAI 400 otherwise, #1591).
    # None = unknown (live-only OpenRouter routes, Ollama, un-audited models); the
    # resolver then keeps the configured default, safe for providers that clamp
    # server-side (OpenRouter) or don't error (Ollama).
    max_output_tokens: int | None = None

    @property
    def family(self) -> str:
        """The catalogue family (id-derived) the picker groups by."""

        return family_from_id(self.id)

    @property
    def accepts_temperature(self) -> bool:
        """Effective temperature support: the provider's own signal AND the
        family rule. The no-sampling families reject `temperature` on every
        route (incl. OpenRouter's `anthropic/…` ids), so the family rule
        overrides a provider that still lists the parameter. Drives the wire
        `temperature` capability and the picker's read-only field (#1554).
        """

        return self.supports_temperature and family_supports_temperature(self.id)

    @property
    def free(self) -> bool:
        """A genuinely-free model — input priced at exactly 0 (OpenRouter
        `:free` routes, kept since #1386). Unknown pricing (`None`, e.g. a
        provider that doesn't publish it, or local Ollama) is NOT free."""

        return self.cost_in_per_mtok == 0.0


@dataclass
class UsageMetrics:
    """Normalized per-call token counts. Each provider parses its own
    response shape into this; `compute_cost` consumes it alongside a
    `ModelDescriptor` to produce USD.

    `input_tokens` is non-cached input billed at full rate.
    `cached_input_tokens` are input tokens served from cache (discounted
    by `cache_read_multiplier`). `cache_write_tokens` are input tokens
    written to the cache this call (a small premium on Anthropic; 0
    elsewhere). The three slots are disjoint — sum them for total input.
    """

    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    # Subset of `cache_write_tokens` written at the 1-hour TTL (Anthropic prices
    # these at ~2x input vs ~1.25x for 5-minute). 0 when the provider doesn't
    # report a per-TTL breakdown, in which case every write bills at the 5m rate
    # (the prior, understating behaviour). Never exceeds `cache_write_tokens`.
    cache_write_tokens_1h: int = 0
    output_tokens: int = 0


# Anthropic cache-write premiums over the base input rate: a 5-minute-TTL write
# is ~1.25x, a 1-hour-TTL write ~2x. A chat writes the stable system prefix at
# 1h and the volatile journal at 5m, so billing every write at 1.25x understates
# any turn that (re)writes the 1h prefix (#814). `cache_write_tokens_1h` carries
# the 1h portion; the remainder is billed at the 5m rate.
_CACHE_WRITE_MULTIPLIER = 1.25
_CACHE_WRITE_MULTIPLIER_1H = 2.0


def compute_cost(usage: UsageMetrics, descriptor: ModelDescriptor) -> float | None:
    """USD cost for one call, computed from descriptor pricing.

    Returns None when the descriptor carries no pricing at all — both
    input and output rates unknown (a local Ollama model, or a
    live-discovered model whose provider doesn't publish prices). None
    means "cost unknown" and surfaces as "—"; it is deliberately
    distinct from a real 0.0, which a genuinely zero-priced model (one
    with an explicit 0.0 rate) still produces. Fabricating 0.0 for an
    unpriced call would render as "€0.00" — a confident zero the display
    contract reserves for a truly free call (#697).

    Caller should freeze the returned value into their accumulator —
    recomputing later would drift when the model's listed price changes.
    """

    if descriptor.cost_in_per_mtok is None and descriptor.cost_out_per_mtok is None:
        return None
    cost_in = (descriptor.cost_in_per_mtok or 0.0) / 1_000_000
    cost_out = (descriptor.cost_out_per_mtok or 0.0) / 1_000_000
    cache_read_mult = (
        descriptor.cache_read_multiplier
        if descriptor.cache_read_multiplier is not None
        else 1.0
    )
    # Cache writes split by TTL: the 1h portion at the higher premium, the rest
    # (5m) at the lower one. `cache_write_tokens_1h` is 0 when the provider gives
    # no per-TTL breakdown, so this reduces to the all-5m rate (#814).
    cache_write_5m = max(usage.cache_write_tokens - usage.cache_write_tokens_1h, 0)
    return (
        usage.input_tokens * cost_in
        + usage.cached_input_tokens * cost_in * cache_read_mult
        + cache_write_5m * cost_in * _CACHE_WRITE_MULTIPLIER
        + usage.cache_write_tokens_1h * cost_in * _CACHE_WRITE_MULTIPLIER_1H
        + usage.output_tokens * cost_out
    )


_TIKTOKEN_ENCODER = None
_TIKTOKEN_TRIED = False


def _tiktoken_encoder():
    global _TIKTOKEN_ENCODER, _TIKTOKEN_TRIED
    if _TIKTOKEN_TRIED:
        return _TIKTOKEN_ENCODER
    _TIKTOKEN_TRIED = True
    try:
        import tiktoken
    except ImportError:
        log.warning("tiktoken unavailable; token counts use char/4 approximation")
        return None
    _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
    return _TIKTOKEN_ENCODER


def default_token_count(text: str) -> int:
    """Universal fallback token estimator — cl100k_base via tiktoken,
    or character/4 when tiktoken isn't installed. Providers without a
    native tokenizer call this from their `count_tokens`.
    """

    if not text:
        return 0
    encoder = _tiktoken_encoder()
    if encoder is None:
        return max(1, len(text) // 4)
    return len(encoder.encode(text))


class ProviderError(RuntimeError):
    """An expected, user-facing failure from a provider's call path — a
    missing SDK package, an unconfigured or mispasted key. The dispatch
    layer catches it and turns it into an error result, not a 500.

    ``detail`` carries developer-facing diagnostics (e.g. the empty-stream dump,
    #1601) that must NOT be shown to the user: the dispatch layer copies it onto
    the ``StreamError`` so the stream layer can record it to ``errors.log``, while
    the message alone reaches the UI. The message itself stays user-facing.
    """

    def __init__(self, *args: object, detail: str | None = None) -> None:
        super().__init__(*args)
        self.detail = detail


@dataclass
class ChatCall:
    """One completion request, provider-agnostic — what to say, not who to
    say it to. Credentials and endpoint live on the resolved profile.

    `system_blocks` is the multi-block form: a volatility-ordered (stable-first)
    list of `{"text": str, "tier": "stable"|"volatile"|None}` blocks (ADR-0060 §5).
    It carries only the volatility tier — never a provider's ttl/breakpoint
    vocabulary; each adapter maps the tier to its own caching primitive. When set it
    overrides `system_prompt` for providers that honor it (Anthropic; OpenRouter on
    explicit-cache routes); others collapse it to a string.
    """

    model: str
    system_prompt: str
    messages: list[dict[str, str]]
    max_tokens: int
    temperature: float | None = None
    system_blocks: list[dict] | None = None
    session_id: str | None = None
    # Streaming only: ask the provider for extended thinking when it supports
    # it (Anthropic). Ignored by `chat` and by providers without a thinking
    # mode.
    thinking_enabled: bool = False


@dataclass
class ChatOutcome:
    """What a provider's `chat` returns: the assistant text, the provider's
    stop/finish reason, and the raw SDK response (which the dispatch layer
    hands to `extract_usage`).
    """

    content: str
    stop_reason: str | None
    raw: Any


@dataclass
class StreamDelta:
    """A chunk of assistant text from a streaming call."""

    text: str


@dataclass
class StreamThinking:
    """A chunk of provider reasoning/thinking from a streaming call."""

    text: str


@dataclass
class StreamFinal:
    """The terminator a provider's `chat_stream` yields last, carrying what
    the dispatch layer needs to build its public `StreamDone`: the stop
    reason and (when the provider reported it) the token usage.
    """

    stop_reason: str | None
    usage: UsageMetrics | None = None


class ThinkTagSplitter:
    """Stream-safe splitter that reroutes <think>…</think> regions as thinking.

    Many local models (DeepSeek-R1, QwQ, Ollama) emit reasoning inline as
    `<think>…</think>` tags inside the content stream. This splitter consumes
    chunks of text and yields StreamDelta for normal content, StreamThinking
    for content inside tags, and holds back enough trailing characters that
    a tag split across chunk boundaries is still recognized.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, text: str) -> Iterator[StreamDelta | StreamThinking]:
        self._buf += text
        # The two states are mirror images — inside a think block we scan for
        # the closing tag and emit thinking; outside we scan for the opening
        # tag and emit content. `_scan` runs one such pass; a found delimiter
        # flips the state and we loop, otherwise the buffer is held for the
        # next chunk and we stop.
        while self._buf:
            if self._in_think:
                found = yield from self._scan(self._CLOSE, StreamThinking)
            else:
                found = yield from self._scan(self._OPEN, StreamDelta)
            if not found:
                return
            self._in_think = not self._in_think

    def _scan(
        self, delim: str, event_cls: type[StreamDelta | StreamThinking]
    ) -> Iterator[StreamDelta | StreamThinking]:
        """Consume the buffer up to `delim`, emitting `event_cls` for the text.

        Returns True (via `return`) when the delimiter was found and stripped —
        the caller flips state and loops. Returns False when it wasn't: emit
        everything except a possible partial delimiter at the tail, hold that
        back for the next chunk, and stop.
        """
        idx = self._buf.find(delim)
        if idx == -1:
            hold = len(delim) - 1
            if len(self._buf) > hold:
                out = self._buf[:-hold] if hold else self._buf
                if out:
                    yield event_cls(text=out)
                self._buf = self._buf[-hold:] if hold else ""
            return False
        if idx > 0:
            yield event_cls(text=self._buf[:idx])
        self._buf = self._buf[idx + len(delim):]
        return True

    def flush(self) -> Iterator[StreamDelta | StreamThinking]:
        if not self._buf:
            return
        if self._in_think:
            yield StreamThinking(text=self._buf)
        else:
            yield StreamDelta(text=self._buf)
        self._buf = ""


class ProviderProfile(ABC):
    """One per provider. Concrete implementations live in sibling modules
    (anthropic.py, openai.py, openrouter.py, ollama.py)."""

    name: str
    display_name: str

    # Key signatures this provider recognizes as its own, e.g. ("sk-ant-",).
    # Empty = no key (Ollama). The dispatch layer scans providers by these
    # to spot a key pasted into the wrong provider's field — each provider
    # declares only its own; specificity (longest prefix) resolves overlap.
    key_prefixes: tuple[str, ...] = ()

    # ADR-0073 S4: does this provider's live catalogue authoritatively list every
    # model the account can reach? When True, `list_models` surfaces live models
    # with no baked-in audit entry (marked unverified) instead of dropping them,
    # so Refresh is honest. All four current providers set True; the flag exists
    # so a future provider with an unreliable/partial live listing can opt out
    # (stay baked-in-only) without a special case in the merge.
    live_catalog: bool = False

    def configured_key(self) -> str:
        """The API key this profile holds, or '' when it needs none. The
        dispatch layer reads it to guard against a blank or mispasted key
        before delegating the call. Overridden by providers that carry one.
        """
        return ""

    @classmethod
    @abstractmethod
    def from_settings(cls, settings: MachineSettings) -> ProviderProfile:
        """Construct a live profile from machine settings, reading this
        provider's own credential slot (api key or host).

        This is the single constructor the registry calls: adding a
        provider means writing this classmethod on the subclass and adding
        one line to the registration table, not editing a dispatch chain.
        """

    @abstractmethod
    async def list_models(self, *, force_refresh: bool = False) -> list[ModelDescriptor]:
        """Return the provider's model catalogue. Implementations should
        prefer live discovery and fall back to bake-in data on failure.

        `force_refresh=True` bypasses any in-memory cache the implementation
        keeps; disk-cache invalidation lives in `profile_cache.py`.
        """

    @abstractmethod
    def caching_style(self, model_id: str) -> CachingStyle:
        """Tell the dispatch layer how to mark cacheable content for this
        model. See `CachingStyle` for the contract."""

    @abstractmethod
    def count_tokens(self, text: str, model_id: str) -> int:
        """Estimate tokens for `text` under `model_id`. Pre-send only —
        actuals come back via `extract_usage` on the response.

        Doesn't have to be exact; powers the cost-estimate panel.
        Providers without a native tokenizer should call
        `default_token_count` for a tiktoken-cl100k_base fallback.
        """

    @abstractmethod
    def extract_usage(self, raw_response: Any, model_id: str) -> UsageMetrics:
        """Parse the provider's response object into normalized usage.

        Each provider knows the shape of its own SDK response. Missing
        fields default to 0 — never raise on a malformed `usage` block.
        """

    @abstractmethod
    def chat(self, call: ChatCall) -> ChatOutcome:
        """Run one non-streaming completion against this provider.

        Credentials and endpoint come from the instance (built via
        `from_settings`); the request is `call`. Raise `ProviderError` for
        an expected failure — a missing SDK package, a key problem — which
        the dispatch layer catches. Streaming is `chat_stream`, added in a
        later slice.
        """

    @abstractmethod
    def health_ping(self, model: str) -> None:
        """Make the cheapest call that proves the endpoint + credentials
        work — a 1-token completion against `model`. Returns nothing on
        success; raises `ProviderError` (or lets the SDK's error surface)
        on failure, which the dispatch layer turns into a health result.
        """

    @abstractmethod
    def chat_stream(
        self, call: ChatCall
    ) -> Iterator[StreamDelta | StreamThinking | StreamFinal]:
        """Stream a completion: yield `StreamDelta`/`StreamThinking` chunks as
        they arrive, then exactly one `StreamFinal` carrying the stop reason
        and usage. Credentials/endpoint come from the instance; the request is
        `call` (with `call.thinking_enabled` honored where supported). Raise
        `ProviderError` for an expected failure; the dispatch layer wraps the
        events into its public StreamDone/StreamError.
        """

    def supports_temperature(self, model_id: str) -> bool:
        """Whether the model accepts a `temperature` parameter on the
        request. Delegates to the provider-neutral family rule, so the
        no-sampling families are rejected on every provider (a `claude-opus-5`
        reached through OpenRouter as `anthropic/claude-opus-5` is caught the
        same as the native id). Call sites omit `temperature` from the request
        kwargs when this returns False.
        """
        return family_supports_temperature(model_id)

    def requires_temperature(self, model_id: str) -> bool:
        """Whether the model's API rejects requests that omit `temperature`.
        Default False — most APIs supply a sensible server-side default
        when the parameter is absent. Override only for models that 400
        on missing temp. Save-time validation refuses assistants without
        an explicit temperature when this returns True for their model.
        """
        return False

    def model_for_tier(
        self, tier: CapabilityTier, models: list[ModelDescriptor]
    ) -> str | None:
        """Default tier resolver: cheapest non-deprecated model in tier.

        Tie-break: highest `context_window`, then descriptor list order.
        Subclasses can override (e.g. Ollama returns None — no auto-rank
        for local models; the picker shows the explicit list).
        """

        candidates = [
            m
            for m in models
            if m.tier == tier and not m.deprecated
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda m: (
                m.cost_in_per_mtok if m.cost_in_per_mtok is not None else float("inf"),
                -m.context_window,
            )
        )
        return candidates[0].id
