# ADR-0058: A provider is a class, registered once — the call lives on it, not in a branch

**Accepted** 2026-08-15 (Anton). Verified against `9ea49cd2` (2026-08-15).

**The chat/stream *call* for a provider belongs on that provider's class, and a provider is added or removed at a single registration point — not by editing an `if provider_name == …` chain in six places.**

## Context — the abstraction was built for metadata, and the call path drifted off it

An abstract base class for providers exists — `ProviderProfile(ABC)` (`profiles/base.py`), with per-provider subclasses (`AnthropicProfile`, `OpenAIProfile`, `OpenRouterProfile`, `OllamaProfile`) and a registry. But it abstracts **capability/metadata only**: `list_models`, `caching_style`, `count_tokens`, `extract_usage`, `supports_temperature`, `model_for_tier`.

The actual **chat/stream call** never moved onto it. It lives in `providers.py` as free functions selected by hardcoded branches:

- `chat` and `chat_stream` each open with the same five validation guards, then an `if provider_name == "anthropic" / elif "openrouter" / elif "openai"|"ollama"` dispatch to a sibling free function (`_anthropic_chat`, `_openrouter_chat`, `_openai_compatible_chat`, and the `_*_chat_stream` variants).
- `_extract_usage_for_provider` re-dispatches by hand a **third** time — `if provider_name == "anthropic": AnthropicProfile("").extract_usage(…)` — instead of resolving the profile from the registry and calling `.extract_usage()` polymorphically, even though that method is *already on the ABC*.
- `registry.profile_for` is a **fourth** `if provider == …` — the name→instance constructor — sitting under a hardcoded `_KNOWN = {"anthropic", "openai", "openrouter", "ollama"}` name set.

So **adding one provider today means editing every one of these branch sites** (`registry._KNOWN`, `registry.profile_for`, `chat`, `chat_stream`, `_extract_usage_for_provider`, `health_check`) *and* writing the subclass. Removing a provider that a vendor has discontinued means finding and deleting the same scattered branches. That per-provider edit cost is precisely what an abstract base class was meant to remove.

**The original intent was never recorded.** The provider layer's only design artifact — `docs/ai-model-selection.md` — justifies the abstraction by live *model* discovery and gracefully sunsetting deprecated *models*. The argument that drove the ABC — *a provider is a unit you add when a new vendor appears and drop when one goes out of business, and an ABC makes each a per-subclass change* — was made in the architecture phase and written down nowhere (no ADR, no issue, no code comment). This ADR records that intent and closes the gap, so the call path cannot silently drift off the abstraction a second time (cf. ADR-0056: a boundary worth keeping is a gate or a choke point, not a convention).

## Decision

1. **The call lives on the provider class.** `chat(call)` and `chat_stream(call)` become methods on `ProviderProfile`, implemented per subclass (the OpenAI-compatible providers share one base implementation — see §3). `providers.py`'s `chat`/`chat_stream` shrink to: validate the request, resolve the profile from the registry, delegate. The four `if provider_name == …` chains — including `_extract_usage_for_provider`'s — collapse into one polymorphic call each. `extract_usage` stops being re-dispatched: the resolved profile already carries it.

2. **A provider registers once.** Each subclass gains a `from_settings(settings)` constructor (declared on the ABC) that absorbs its own construction difference — Anthropic/OpenAI/OpenRouter take an `api_key`, Ollama takes a `host`. `registry.profile_for` and `_KNOWN` become a single registration table `{name → ProviderProfile subclass}`; `known_provider_names()` and construction both derive from it. Adding a provider = write the subclass + add one registration line; removing = delete both. `capability_profile_for` (the credential-less path) keeps delegating through the same table, so there is still one constructor, not two.

3. **Shared cross-provider logic stays shared, not copy-pasted.** The five validation guards and the OpenAI-compatible request/response body are common to multiple providers; they remain in one place (a base-class method and/or a shared helper the OpenAI-compatible subclasses call), so polymorphism replaces the branching without minting four near-identical method bodies.

## Why — and the rejected alternatives

The load-bearing choice is *what replaces the branches*, and three options were on the table:

- **A parameters-object band-aid** — bundle the ~10 call arguments into a `ChatCall` value object and keep the `if/elif` dispatch. **Rejected.** It was the plan on the table when this drift was noticed, and it only tidies the monolith: it reduces argument counts and makes the branches shorter, entrenching the exact shape the ABC was meant to remove. It would clear the `#76` complexity findings while leaving "add a provider" a six-site edit.

- **The call path only, leaving the registry as-is** — move `chat`/`chat_stream` onto the class but keep `registry.profile_for`/`_KNOWN` as a hand-rolled `if/elif`. **Rejected.** It deletes the *call* branches but leaves the *registration* branch, so adding or removing a provider still means editing the registry by hand. It half-delivers the cheap-add/remove property, which is the whole point.

- **A separate adapter ABC parallel to `ProviderProfile`** — one hierarchy for metadata, a second for the call. **Rejected.** It doubles the per-provider surface (two classes to write and keep in sync per vendor) to preserve a separation that carries no weight: one provider is one thing, and it already holds the credentials the call needs. One class per provider, owning both its metadata and its call, is simpler and is the shape a reader expects.

## Consequences

- **The `#76` `providers.py` complexity findings dissolve into this work.** `chat_stream` (C901=23), `chat` (14), `_anthropic_chat_stream` (16), `_openai_compatible_chat_stream` (11), `health_check` (12), and the PLR0913 argument-count findings are all symptoms of the branching and the threaded-through argument lists. Once dispatch is polymorphic and each method takes its own coherent arguments, the numbers fall out. Those findings are therefore **folded into this reshape and removed from the mechanical `#76` burn-down** — fixing them first would be work on a shape we are about to delete.
- **Provider wire behaviour does not change.** The requests sent to each provider and the parsing of their responses must be **byte-for-byte what they are today** — this is a structural move, not a behavioural one. The existing provider tests are the oracle; a change in what any provider sends or returns is a bug in the reshape, not a feature of it.
- **The metadata ABC is unchanged, only extended.** `list_models`/`caching_style`/`count_tokens`/`extract_usage` keep their contracts; the ABC gains `chat`/`chat_stream`/`from_settings`.

## Forward-looking — user-defined providers (the north star, an explicit non-goal here)

The reason to get the registration point right now is a future one: eventually a user should be able to **bring their own provider**. In a local-first app that most naturally means a **user-registered OpenAI-compatible endpoint** (a name + `base_url` + key + model list), which the existing `_openai_compatible_*` path already largely serves — not user-supplied code.

This ADR does **not** build that. It only keeps the door open *by shape*: the registration point must not assume every provider is a hardcoded Python subclass, so that a config-driven provider can later plug into the same table without reopening the provider layer. Explicit **anti-goals** for this ADR: no user-provider configuration UI, no persistence of user providers, no plugin/arbitrary-code loading, no sandboxing, and no change to provider wire behaviour or to the metadata ABC's existing methods.

## Deferred to implementation (not decided here)

Per the project's habit of not guessing a shape before it is forced (ADR-0005's lesson): the exact request value type (`ChatCall` fields; whether `chat` and `chat_stream` share one request type or the stream form merely adds `thinking_enabled`), the home of the shared OpenAI-compatible body and the validation guards (base method vs mixin vs free helper), and the concrete form a future user-defined provider takes are left to the implementation and its own review.

## Slices

1. **Registration table** — `from_settings` on the ABC + each subclass; `profile_for`/`_KNOWN` become one table. Invisible; existing call path still routes through it.
2. **Usage dedup** — `_extract_usage_for_provider` resolves the profile from the table and calls `.extract_usage()`; the third `if/elif` dies.
3. **Non-stream call** — `chat` onto the class; `providers.chat` thins to validate→resolve→delegate.
4. **Stream call** — `chat_stream` onto the class; `providers.chat_stream` thins the same way; `health_check`'s branch resolves through the table.

Each slice is behaviour-preserving and verified against the provider tests before the next.

---

Citations (symbol · file, at the pin above): `ProviderProfile` · `profiles/base.py`; `profile_for` / `known_provider_names` / `_KNOWN` · `profiles/registry.py`; `chat` / `chat_stream` / `_extract_usage_for_provider` / `health_check` · `providers.py`; design note · `docs/ai-model-selection.md`.

(**Accepted** 2026-08-15, Anton, PR #1046; #76 provider-layer findings fold in; follows 0056; relates the `docs/ai-model-selection.md` design note; verified against `9ea49cd2`.)
