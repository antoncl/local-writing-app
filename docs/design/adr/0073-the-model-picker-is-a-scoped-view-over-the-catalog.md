# ADR-0073: The model picker is a policy-scoped, faceted view over the live provider catalog

**Accepted** 2026-08-24 (Anton). Verified against `79949674`.

**The assistant's model list is a dedicated built-in View over the provider's *live* catalog: the picker offers only providers the project's policy and the machine's credentials permit, every live model the account has is shown (no hand-maintained allow-list that hides them), and the browse is the app's own View machinery — not a bespoke dropdown.**

## Context — the catalog/picker has never had a decision record, and it has drifted three ways

The provider *abstraction* has an ADR (ADR-0058: a provider is a class), but it scopes the model **catalog and picker UX out** as explicit anti-goals. That area lives only in the design note `docs/ai-model-selection.md` — the same "written down nowhere" corner ADR-0058 flagged. Dogfooding surfaced three faults there, each a different root cause:

1. **Stale names, dead Refresh (OpenAI).** The Anthropic/OpenAI catalog *merges* a hand-audited file with the live `/v1/models` call and then **drops any live model absent from the file**. So the OpenAI list is frozen to four ids (no `gpt-4.1`/`o3`/`o4-mini`), and Refresh cannot surface newer models the account actually has — it re-fetches, they're filtered out, and the names come from the frozen file. Refresh is doing its job; the merge-hide defeats it.
2. **An uncurated wall (OpenRouter).** ~300 live models render as one bare native `<select>` — no search, no grouping — and the cost-band tier heuristic made every fast/balanced/premium pick resolve to one vendor (Anthropic-by-pricing): accidental product-placement in a provider whose entire point is neutrality.
3. **A policy- and credential-blind picker.** Project AI policy (`off`/`local-only`/`cloud-allowed`) is enforced *only at use-time*. The picker offers every provider regardless of policy or configured keys, and a fresh assistant defaults to `anthropic` (alphabetical), ignoring the machine `default_provider`. You can hire a cloud assistant under `local-only`; it saves, becomes the silent default, and every send then fails.

`docs/ai-model-selection.md` records the *current* (v1) behaviour this ADR partially supersedes: save-time tier resolution, the Advanced dropdown, and the live-`list_models` merge.

## Decision

1. **The model list is a dedicated, read-only, built-in View — rendered through `ViewNodeList` over adapter-lifted catalog entries.** A `modelDescriptorsToEvalNodes` adapter (mirroring the existing `chatSummariesToEvalNodes`) lifts each catalog entry into an `EvalNode` — `{id, entry_type, title, metadata:{family, free, capabilities, context, price}}` — and a fixed in-memory `ViewSpec` filters by family/capability/free and groups by family, with a param strip. The view **designer is not exposed** (a fixed built-in view, exactly like the Chats and Prompts panes). The `evaluateView` engine is already a pure function of `(spec, supplied nodes)`, so no project node-index, persistence, or API is involved; the drag/rename/add machinery stays dormant behind its existing opt-in gates. This makes the picker consistent with every other list in the app, which is the point.

2. **The picker is policy- and credential-scoped at pick time; the use-time check remains the invariant.** The provider list offered is filtered to those the project's resolved policy permits (`local-only` → local providers only; `off` → the hire surface is suppressed) *and* that have a configured credential (an existing helper, `configuredCloudProviders`, that the picker does not yet consult). A fresh assistant defaults to the machine `default_provider`, not alphabetical. **No save-time validation is added:** hiding forbidden providers prevents the mistake through the only writer (the UI), and the fails-closed guard already lives at use-time and catches everything else — including the one case save-time could not: an assistant hired legitimately, then the project tightened to `local-only`. That case is handled by **mark-and-skip** — a now-forbidden assistant is marked in the roster and skipped by the default-assistant resolver, so a `cloud-allowed → local-only` switch never leaves a silently-broken default.

3. **A provider's catalog surfaces every live model; the merge stops *hiding*.** Known models keep their authored names/tiers/prices; a live model we don't have baked-in is **shown**, with a derived tier and its raw id as the display name (marked new/unverified), instead of being dropped. Each provider declares whether its live catalog is authoritative (`live_catalog`), which drives whether Refresh is offered and whether it is honest.

4. **Descriptors gain slim, presentation-neutral metadata; no curation layer.** `family` (the id prefix) and `free` join the descriptor (free models are already kept as of #1386). There is **no recommended/curated slate** and, for the aggregator, no auto-resolved tier pick — the faceted browse plus a plain default is enough, and skipping recommendation is what keeps it vendor-neutral.

## Why — and the rejected alternatives

- **Hand-rolled search on `NodeRow`/`NodeList` directly** (this ADR's own earlier draft position). **Rejected.** It works, but every other list in the app is a View; a bespoke-search picker is the anomaly — the same argument that kills the `<select>`, one level up. Consistency is the feature.
- **Modelling catalog entries as real project Nodes / routing through `ViewNodeList`'s node path.** **Rejected.** Models are external, ephemeral catalog rows, not project data. The pure `evaluateView` over a *supplied* `EvalNode` array (the Chats/Prompts pattern) gives the whole View UX with none of the node-identity, persistence, or "every tree node is a real Node" coupling.
- **Save-time policy validation.** **Rejected.** It is a defense, not the invariant-holder. Hiding forbidden providers stops the UI mistake; the use-time `_policy_allows` gate holds fails-closed for everything else. Adding save-time validation would defend against a non-UI write that has no real trigger in a single-user local app and is already blocked at use.
- **A curated recommended slate / per-tier auto-pick for the aggregator.** **Rejected initially (deferred).** Its only jobs are choice-reduction (the browse handles that) and feeding a tier quick-pick (which for an aggregator is exactly where the vendor bias lives). Not building it removes the bias by construction; revisit only if real use shows people flailing.
- **Keep the merge-hide, just refresh the baked OpenAI list.** **Rejected.** It re-freezes the lineup at the next model release and leaves Refresh a lie. Surfacing live-only models is the fix that lasts.

## Consequences

- The bare native `<select>` and `ProviderTierPicker`'s "Advanced" model dropdown are replaced by the built-in View; the tier quick-pick stays for providers that rank by tier (Anthropic, OpenAI), and Ollama/OpenRouter lean on the flat/faceted list.
- **The fails-closed invariant is unchanged** — still enforced at use-time (relates to ADR-0056's "a boundary is a gate, not a convention"). The picker adds a *pick-time* guard on top; it does not move or weaken the use-time one.
- **Vendor-neutrality is structural:** with nothing auto-recommended, there is nothing to bias.
- **OpenAI is verified by mocked/CI tests only.** The maintainer has no OpenAI account (a deliberate choice), so the merge-hide fix and OpenAI catalog paths are proven against a mocked `/v1/models`, not smoke-tested live — the same posture as the unsigned, Mac-less macOS build.
- Relates to / **partially supersedes** `docs/ai-model-selection.md`; **follows** ADR-0058 (the provider abstraction it builds on) and ADR-0024 (assistant selection); leans on ADR-0056 for the policy/credential gate.

## Anti-goals

- No view **designer** for the model list — it is a fixed built-in view.
- No **per-project provider/model override** (retired in #330); provider/model stays machine-default + per-assistant, policy the only per-project AI setting.
- No **user-provider configuration UI** (that remains ADR-0058's untouched north star).
- No **model-size** field (OpenRouter doesn't expose it reliably; only sometimes in the name).
- No **recommended slate** initially.

## Deferred to implementation (not decided here)

- The exact facet set and param-strip shape; whether the aggregator shows a tier quick-pick at all.
- The per-family colour map and badge layout (a `detailSlot` vs `detail` string).
- A recommended slate, and any popularity signal it would need, *if* real use demands it.
- The precise home of the `live_catalog` flag and the derived-tier heuristic for live-only models.

## Slices

1. **Free models kept** — #1386, **shipped** (0-priced OpenRouter rows no longer dropped).
2. **Policy/credential-aware picker** — hide forbidden/unconfigured providers; default to machine `default_provider`; mark-and-skip incompatible assistants. Standalone correctness win; needs no descriptor metadata, ships first.
3. **The built-in model View** — the adapter + fixed `ViewSpec` + `ViewNodeList`; family grouping, capability/free facets, context/price badges. Introduces `family`/`free` on the descriptor.
4. **Merge-hide removed + honest Refresh** — surface live-only models; `live_catalog`. (OpenAI: mock-verified.)
