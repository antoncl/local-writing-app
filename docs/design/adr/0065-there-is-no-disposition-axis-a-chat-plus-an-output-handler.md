# ADR-0065: There is no disposition axis — a chat plus an optional output-handler

- Status: **Accepted** — 2026-08-17 (Anton). Approved over the prompt/field-system design session.
- Issue: #1109 · Pre-1.0 (no release milestone)
- **Supersedes** ADR-0054's central decision — the output **disposition axis** (`output.kind` as a closed set of peer values + `commit` as a separate capability on `chat_panel`). **Subsumes** ADR-0063 (commit-to-a-target = the `extract_to_node` handler).
- Follows: ADR-0058 (a provider is a class, registered once — the call on the class, not a branch — the pattern this reuses), ADR-0056 (self-enforcing: registered choke points + uniformity so a cold session copies a sibling), ADR-0050 (the caretaker "knows only commands" — the core-knows-only-the-contract precedent), ADR-0054 (the disposition/commit model this collapses)
- Composes with: ADR-0061/0062 (the extractor is a prompt), ADR-0059 (`ai_proposable` gating on the node write)
- **Verified against `f0c20603` (2026-08-17). Interface derived from a scan of the real handlers (see §Grounding).**

## Amendment 1 (2026-08-19) — the collapse is *config on `general`*, S3 is unbuilt, and the no-helper verdict is retracted

Review of the implementation surfaced that this ADR's central slice was never built and that two of its calls were wrong. This amendment corrects them; where it touches how the output is *authored*, it is refined in **ADR-0067** (the prompt-output model + the `field_contract` Jinja accumulator), which this ADR now composes with.

**1. S3 was never implemented.** #1127 retired the `output.kind`→handler-key *dispatch*, but `default_schema.py` still ships `prompt:continuation / roleplay / revise / revise:scene / revise:entry / revise:scene_summary`, and the built-in Library prompts still carry those `entry_type`s. The two authored kinds `{general, snippet}` (§1) are **not yet the only concrete prompt types**. Finishing S3 — collapsing the built-ins to `{general, snippet}` — is the outstanding work.

**2. The behaviour is *config on `general`*, not a per-type declaration.** §1 is right that continuation / revise / roleplay / brainstorm are all `general`; what §1–§3 underspecify is *where the choice lives*. It is a **per-prompt config area** on a `general` prompt, with these independent axes:
   - **`method`** — where the output goes, from the closed backend-owned set: `append` (stream at cursor) · `inline` (replace selection) · `roleplay` (append + character mark) · `node` (extract → write a node's fields) · `none` (stays in the chat). This corrects §3's over-collapse of `append`+`inline` into one handler with a hidden destination sub-choice: they are **distinct authored methods**, because an author picks "append at cursor" vs "replace selection," not "inline, destination=cursor."
   - **`diff`** — a boolean, only meaningful for `node`: show a field-by-field diff to review, vs. preview-and-accept. Off for "regenerate the summary," on for a large multi-field revise. This replaces the create-vs-update-vs-replace distinction, which does **not** need to be a method axis — it falls out of `diff` × the target below.
   - **`headless`** — a boolean, orthogonal to `method`: run as a single pass with no conversation (vs. open a chat). The ADR's `activation` conflated this; it is its own axis.
   - **target type** (for `node`) — **authored on the prompt**, per ADR-0063 S1's `commit.target`. A brainstorm prompt is type-specific (a "brainstorm a location" prompt renders `fields("lore:location")` and can only produce a location); the caller supplies only the *instance* to update (the launch subject, of that type), never the type. *(**Superseded by ADR-0067 Amendment 1**: the target type is `inputs.entry_type`, a required input the caller seeds — not an output-config `commit.target`.)*

**3. `prompt:extractor` is withdrawn, and there is no separate extractor prompt at all.** ADR-0063 S2 (#1174) introduced a `prompt:extractor` entry_type — this **re-created the very sub-type proliferation this ADR collapses, and is withdrawn.** More than that: the field contract is authored *inline* in each node-writing `general` prompt via the `field_contract` accumulator (ADR-0067), so there is no separate default-extractor prompt to type or maintain. A single-pass (no-conversation) extraction is just a `general` prompt with `headless = true`. #1174 is re-based onto ADR-0067, not merged as-is.

**4. The "which fields" scope leaves the type for the Jinja.** With only `{general, snippet}`, `output.commit.fields` has no per-behaviour type to hang off. So the field scope moves into the **extractor's Jinja** (this is ADR-0063 S3, "commit.fields retires into the authorable Jinja") — which means **the two-type collapse and 0063 S3 are coupled: you cannot finish this ADR's S3 without doing 0063's.** See ADR-0067.

**5. The §Grounding "NO new Jinja helper is required" verdict is retracted.** Once the field contract is authored inline and read back as data at commit (ADR-0063 S3 / ADR-0067), the template layer needs real support for "the fields this prompt outputs" — the `field_contract` accumulator (`store` / `render`) plus enabling `{% do %}` — not the hand-inlined `{% for f in fields(...) %}` loop `DEFAULT_EXTRACTION_TEMPLATE` carries today. Specified in **ADR-0067**.

**6. The built-ins are application deliverables.** The shipped built-in Library prompts are part of the app "on par with a config file"; finishing S3 re-authors them to `{general, snippet}` + config **completely and correctly**, not half-typed.

Unchanged: the handler *set* stays closed and backend-owned (§Anti-goals) — the config only *selects* from it; `commit` / `on_accept` stay handler-local; `snippet` is the **include** (see the ADR-0061 amendment: includes are role-less).

## Amendment 2 (2026-08-26) — no prompt behavior lives on the type; `PromptEntryTypeExtras` is removed

Dogfooding surfaced that the type/class still carries prompt *behavior* config — the coupling this ADR exists to remove. §1 ("continuation/revise/… are all `general`, differing only by handler") is right; the implementation kept a per-type bundle, `PromptEntryTypeExtras`, that re-admits behavior on the class. This amendment removes it in full. (Citations pinned to `master@c0ec4e90`; symbol/path names are the durable references.)

**1. The principle, flat.** A prompt *type* carries only **identity and structure** — name, parent, fields, body editor, color, assistant binding. It never carries *what a prompt does*. All per-prompt behavior lives on the **instance** (its body — `{% role %}`, includes — and its `context_strategy`); any universal convention is a **fixed engine rule**. The test is not "is it render-resolved" but "can it vary without minting a new sub-type" — anything on the type can only vary by adding a type, which is the proliferation this ADR kills.

**2. `PromptEntryTypeExtras` is removed entirely**, field by field:
- `context_strategy` (`.target`, `.output`) — behavior config, already owned per-instance. The create-time seed (`create_prompt_entry`) retires; a new `general` starts with no `context_strategy` = a plain conversation. `.target` was an orphan with no runtime consumer.
- `model_class` — never wired; model/tier is the **assistant's** (`ai_model` / `ai_capability_tier`, resolved in `call_resolver`), reached from a prompt via `preferred_assistant_id`.
- `provider_policy` — never wired; off/local-only/cloud-allowed is the **machine→project `AIPolicy`** chain (`providers.py`), not per-type.
- `system_prompt` — never wired; the system prompt is the rendered template's system-role text (ADR-0060 §4).
- `inputs` — the type-level copy is unused; the live input seed is the separate top-level `default_inputs`.
- `default_role` — removed; loose-prose homing becomes a constant (ADR-0060 §4 Amendment 2).

None of `model_class` / `provider_policy` / `context_strategy.target` / `system_prompt` was ever introduced by an ADR — they are stranded fields from the pre-ADR M5.2a "Add Prompts pane and Prompt Type editor" (`a8909529`), superseded by the assistant, the policy chain, and the template. Removal deletes scaffolding, not capability.

**3. The "Prompt defaults" UI is removed** (`SchemaTypeEditor.svelte`) — it authored exactly this bundle, letting a user set values that changed nothing at runtime, a control that lies.

Anti-goals: no per-instance `default_role` (the `{% role %}` override already covers it); no configurable loose-prose homing (it is fixed); the type never regains a behavior field — a genuine *seed* need is its own decision (ADR-0049 §7), not a revived bundle.

Consequences: the bundle, its create-seed, and its type-level `.output` validation retire; a new `general` persists no `context_strategy` (invocability is the entry_type, per `entries.py`); shipped Library prompts are unaffected (they carry their own instance config). **No migration:** pre-1.0 with zero users, there is no persisted user data to carry forward and the app-owned built-in schema is simply re-authored — removal is forward-compatible on read regardless (Pydantic drops the retired keys).

## Context

ADR-0054 modelled a prompt's output as **two** things: a **disposition** (`output.kind` ∈ `append_to_body` · `replace_selection` · `chat_panel`) and an optional **commit** capability on `chat_panel`; the four concrete bases (continuation / revise / general / snippet) each bundle one. That framing treats the disposition as an axis of independent choices.

A scan of the real behaviors (§Grounding) shows it isn't. `output.kind` is a **discriminator from which everything else falls out**, and its values come in a few **fixed, correlated bundles**:

- `append_to_body` and `replace_selection` are the *same* behaviour — an inline generation streamed behind the `aiSuggestion` mark — differing only in *where* inline (cursor vs selection).
- `chat_panel` + `commit` is a second, unrelated behaviour — a conversation, then a fresh extractor pass over the transcript → a validated node patch → a diff review.
- `chat_panel` alone is *no* output behaviour — the result stays in the chat (general / impersonate).
- `source`, `review`, and `activation` are **not independently chosen** — each is derived from `output.kind`. (`scan_surface` is declared, edited, and tested, but **dead**: no dispatch reads it; the frontend derives what to gather from `output.kind`.)

So every derived prompt is really: **a chat, plus (optionally) one bundle that takes the output somewhere.** continuation / revise / roleplay are the *inline* bundle with per-prompt config; brainstorm is the *extract-to-node* bundle; impersonate is the *null* bundle.

## Decision

**There is no disposition axis. There is a chat, and an optional output-handler.**

### 1. Two prompt kinds

The concrete prompt bases collapse to **`{general, snippet}`**. `snippet` = non-AI reusable text, included by name into another prompt's body via `{% import %}` (no output handler; not invoked). `general` = a chat. continuation / revise / roleplay / impersonate / brainstorm are all `general`, differing only by which output handler (if any) they declare.

### 2. An output handler is a registered class implementing a minimal interface

Each output behaviour is an `OutputHandler` — **a class registered once** (the ADR-0058 provider pattern), implementing a contract derived from the real handlers, not invented:

**Declarative** (the fixed, correlated bundle — a handler *is* a coherent bundle):
- `key` — the discriminator that replaces `output.kind`: `inline` · `extract_to_node`.
- `source` — what it reads: `scan(_text_before, _selection, _text_after)` (inline) | `transcript` (extract). **This becomes a live property that drives gathering** — retiring the dead `scan_surface` declaration.
- `review` — `inline_mark` | `patch_diff`.
- `activation` — `inline` (slash / selection toolbar) | `conversation` (＋New).

**Behavioral** (the two methods the core calls polymorphically):
- `produce(run) -> Produced` — **identity** for `inline` (the streamed generation *is* the output); the **extractor second pass** (ADR-0063) for `extract_to_node`.
- `apply(produced, run)` — stream at cursor / replace the selection (inline); write the node's fields after the diff (extract).

The core loop knows **only** the interface: run the chat; if a handler is declared, `produce` → present its `review` → on accept `apply`. Branch-free — exactly ADR-0050's "the caretaker knows only commands" and ADR-0058's "the call lives on the class, not a branch."

### 3. The closed handler set (today), each a coherent bundle

- **`inline`** — `source` = scan tokens, `produce` = identity, `apply` = stream at a **destination** (`cursor | selection`), `review` = `inline_mark`, `activation` = `inline`. Covers continuation (append at cursor) *and* revise:scene (replace selection): the destination is a **sub-choice**, not two handlers. Roleplay = this handler **+ the `on_accept` mark** capability.
- **`extract_to_node`** — `source` = transcript, `produce` = the extractor prompt (ADR-0063), `apply` = validated node write, `review` = `patch_diff`, `activation` = `conversation`. Carries the **`commit`** capability (target + review mode + fields).
- **none** — no handler; the output stays in the chat (general / impersonate).

### 4. Capabilities stay per-handler, never in the base

`commit{review, fields}` is unique to `extract_to_node`; `on_accept{mark, from_input}` is unique to `inline` — both validator-gated to their handler. Neither enters the base interface. The minimality rule: **the base earns a method only when ≥2 handlers need it** — `commit` and `on_accept` don't, so they stay handler-local.

### 5. A new output = a new registered handler

A genuinely new output behaviour (a todo, a plot card, a new scene) is a **new class implementing the interface + one registration line** — ADR-0058's "subclass + one line" — not a new base, not a config combo, not a core branch.

## Why / rejected alternatives

**Keep ADR-0054's disposition axis (`output.kind` enum + `commit` capability).** Superseded. The scan shows `output.kind` is a discriminator, not an axis of independent choices — its values are correlated bundles, and `source`/`review`/`activation` derive from it (with `scan_surface` dead). Modelling correlated bundles as a flat enum forces every consumer to branch on the value and re-derive the rest; a closed set of handler *classes* that own their bundle is the honest shape.

**One configurable output-stage object (`source × transform × destination × review` as independent knobs).** Rejected — the parameters are *correlated*, not orthogonal; an object with independent knobs admits a large space of invalid combinations (transcript-source → replace-selection). Discrete handler classes encode only the valid bundles.

**Keep the four concrete bases.** Rejected — post-inputs-on-the-instance (ADR-0054's own finding) they carry nothing a handler doesn't; they are `general` + a handler in disguise.

**Arbitrary / author-defined handlers.** Rejected here — the handler set is **closed and backend-owned** (as ADR-0054's disposition set already was); a new output is deliberate code (a class), not free config. (A non-node handler is deferred with a trigger.)

## Anti-goals

- **Not a god-object.** Discrete handler classes, not one parameterised struct.
- **Not arbitrary handler dispatch.** Closed, backend-owned registry; a new handler is a real class + registration.
- **The base interface stays minimal.** `commit` / `on_accept` are per-handler; the base is `produce` + `apply` + the declarative bundle.
- **No new Jinja support** (§Grounding). The interface is served entirely by existing helpers and injected context.
- **No pre-1.0 migration** — the built-in prompts are re-authored to `general` + a declared handler; test projects recreated.

## Grounding — the scan, and the Jinja verdict

The interface above was **derived from a scan** of the six real behaviors, not designed top-down. This is that scan — the map an implementer needs, since it names what each handler must cover and where the behaviour lives today. (Symbols are the durable anchors; line numbers are a convenience under the pin.)

| Behaviour (today's `output.kind`) | source | transform | destination | review | activation | where it lives today |
|---|---|---|---|---|---|---|
| **continuation** (`append_to_body`) | `_text_before` | identity | scene body **at the cursor** | `aiSuggestion` mark | slash / toolbar | gather + stream in `runPromptEntryWithInputs` / `#renderStreamingSuggestion` (`frontend/src/lib/editor-core/aiSuggestion.svelte.ts`, append branch ~363-369, ~148-182); mark `proseMarks.ts` (`aiSuggestion` ~12-34); route `POST /api/ai/generate/stream` (`backend/app/routers/ai.py:438`) |
| **revise:scene** (`replace_selection`) | `_text_before`+`_selection`+`_text_after` | identity | **the selection** | `aiSuggestion` mark | selection toolbar | gather ~341-362, delete-then-stream `ensureStreamingStarted` ~395-410 (same file); same route |
| **revise:entry** (`chat_panel` + `commit`) | **transcript** | **extractor** (2nd pass) | **a node's fields** | patch diff (`commit.review`) | conversation ＋New | `run_entry_patch_extraction` + `DEFAULT_EXTRACTION_TEMPLATE` / `render_extraction_contract` (`backend/app/services/ai/extraction.py` ~71-150, ~214); validate `validate_ai_entry_patch_for_type`; route `POST /api/ai/entry-patch/{id}/extract` (`ai.py:602-613`) |
| **general / impersonate** (`chat_panel`) | — | — | **none** (stays in the chat) | none | conversation ＋New | `runPromptEntryWithInputs` chat_panel branch → `onOpenChat` (`aiSuggestion.svelte.ts:322-327`) |
| **roleplay** (`continuation` + `on_accept`) | `_text_before` | identity | body at cursor | `aiSuggestion` mark **+ a character mark on accept** | slash / toolbar | as continuation, **plus** `promptOnAccept` (`frontend/src/lib/editor-core/promptResolution.ts:283-292`) → `createCharacterMark` (`proseMarks.ts:48-77`) → markdown-comment round-trip (`markdown.ts:35`), read back by `character_thread()` (`backend/app/services/ai/helpers.py:1248-1299`) |
| **snippet** | — | — | — | — | not invoked | text-included by name via `{% import %}`, `PromptSnippetLoader` (`backend/app/services/ai/snippet_loader.py:20-60`); no `context_strategy` block |

Two structural facts the implementer must know:

- **`output.kind` is the discriminator that everything else is derived from today.** The five rows above are selected by `output.kind` (`backend/app/models/schema.py:222`); destination, review, and activation all follow from it. Dispatch is scattered — the frontend branches on it in `runPromptEntryWithInputs` (`aiSuggestion.svelte.ts:322-369`) to decide inline-vs-chat and *what to gather*; the backend splits by route (`/generate/stream` vs `/entry-patch/{id}/extract`). **S2/S3 replace those branches with `handler = registry[key]; handler.produce(...); handler.apply(...)`.**
- **`scan_surface` is declared but dead.** It is stored (`schema.py:229`), edited (`SchemaTypeEditor.svelte` ~187, ~350), and tested — but **no dispatch reads it**; the frontend derives what to gather from `output.kind` (above). So today `source` is redundant with the kind; this ADR makes `source` a **live** handler property that actually drives gathering (naming only context vars `build_preview` already injects), and retires the zombie declaration.

The base interface keeps only what **≥2** of these rows share — `produce` + `apply` + the declarative bundle (`source`, `review`, `activation`). The two per-handler capabilities the scan shows are genuinely unique — `commit` (only `extract_to_node`) and `on_accept` (only `inline`) — stay handler-local, never in the base.

**Jinja / template-engine verdict: NO new helper or token is required.** Every source the interface names is an already-injected context variable; the `_text_before` / `_selection` / `_text_after` scan tokens map 1:1 onto context vars `build_preview` already injects; the extractor's only real template need (`field_catalog`) already exists; and the two per-handler capabilities live *outside* the template engine — `commit` via the extraction route, `on_accept` via a TipTap mark + a markdown-comment round-trip read back by the existing `character_thread()` helper. Handed to the template-language thread as the interface's template-support requirement (which is: none).

## Consequences

- **`output.kind` becomes the handler-registry key**; the four concrete bases retire to `{general, snippet}`.
- **The scattered dispatch collapses to a handler lookup** — the frontend's `output.kind` branches (the inline-vs-chat split, the scan-surface gathering) and the backend routes become "look up the registered handler, call `produce`/`apply`."
- **`scan_surface` retires** as a live concept — `source` on the handler drives gathering (or the token labels move onto the `inline` handler).
- **`commit` and `on_accept` stay** as handler-local capabilities; ADR-0063's commit *is* the `extract_to_node` handler.
- **No template change**; no new helper.

## Slice plan — one lane, disjoint, vertical

- **S1 — the scan → the minimal interface.** Done, and recorded here; the interface is grounded in the real behaviors.
- **S2 — the registry + the two handlers.** Introduce `OutputHandler` (produce/apply + the declarative bundle), register `inline` and `extract_to_node`; the core calls the interface; behaviour byte-identical.
- **S3 — collapse the bases.** Re-author the built-ins to `{general, snippet}` + a declared handler; retire the `output.kind` enum and the scattered dispatch; `scan_surface` retires. Behaviour unchanged.

## Deliberately out of scope (deferred, with a named trigger)

- **Non-node / novel handlers** (a Commit that makes a todo, a plot card, a scene). **Trigger:** the first prompt whose output isn't inline-prose or a node patch.
- **Author-defined handlers** (a handler configured, not coded). **Trigger:** a concrete output behaviour a registered class can't express — the same discipline ADR-0054 used to keep the disposition set closed.
