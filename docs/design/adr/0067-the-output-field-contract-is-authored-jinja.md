# ADR-0067: The output field-contract is authored Jinja, rendered at chat-start and at commit

- Status: **Proposed** — 2026-08-19
- Issue: (to file) · Pre-1.0 (no release milestone)
- Follows: ADR-0065 (two prompt kinds; a `general` prompt's output is a config area — this ADR is where its *field* scope lives), ADR-0063 (commit runs a previewable extractor prompt — this ADR is its S3, "the field contract is authored Jinja"), ADR-0061 (a snippet/include carries its fields — the include mechanism this reuses), ADR-0060 (the prompt language — the helper set this adds to), ADR-0059 (`ai_proposable` gates which fields may be proposed)
- **Retracts** ADR-0065 §Grounding's "NO new Jinja helper or token is required" verdict.

## Context

ADR-0065 collapses prompt types to `{general, snippet}`, so a `general` prompt's node-write behaviour is *config*, not a sub-type (ADR-0065 Amendment 1). That collapse removes the home of the one piece of node-write config that was schema-declared per behaviour: **`output.commit.fields`** — the allow-list narrowing which of a target type's proposable fields a commit produces. It lived on `prompt:revise:scene_summary` (`[summary]`) and friends; once every such prompt is just `general`, there is no per-behaviour type to carry it.

So the "which fields" scope has to move to the only per-prompt authored surface left: **the Jinja**. And the extractor template *already* generates the field list — `DEFAULT_EXTRACTION_TEMPLATE` hand-inlines `{% for f in fields(inputs.entry_type) if f.proposable and (inputs.commit_fields is none or f.id in inputs.commit_fields) %}` and renders each descriptor. Making that authored (and narrowable in the template, not via a separate static list) is exactly ADR-0063's deferred **S3** — "the author supplies/edits their own extractor Jinja; `commit.fields` retires into it."

Two further facts force this ADR's shape:

- **The list must not drift.** ADR-0051 S4 already learned that a field contract carried through a growing chat gets unreliable, and rebuilt it fresh at commit. The recurring design intent (raised repeatedly during the ADR work) is a **two-step** contract: the fields are stated at **chat-start** (so the AI knows, and the author/user can see, what will be produced) and re-asserted at **commit** (the authoritative extraction). Both must come from **one authored source**, or the two drift.
- **The hand-inlined loop is not reusable.** A `{% for f in fields(...) %}` loop copy-pasted into a prompt body *and* an extractor cannot be the "one source." The field contract needs to be a **fragment authored once** and rendered at both points — which needs template-layer support ADR-0065 assumed away.

## Decision

**The fields a prompt outputs are an authored Jinja *field-contract fragment*, rendered from one source at chat-start and at commit, produced by a dedicated helper.**

### 1. The field contract is authored Jinja, not `commit.fields` on a type

A node-writing `general` prompt expresses *which fields it produces* in its Jinja, against its authored **target type** (ADR-0065 Amendment 1 §2 / ADR-0063 S1). The static `output.commit.fields` allow-list **retires** — narrowing is what the template author writes (render all proposable fields, or a chosen subset). `fields()` supplies the universe (`ai_proposable`-gated, ADR-0059); the author narrows it.

### 2. One fragment, rendered at two points

The field contract is authored **once** as a fragment — a role-less **include** (ADR-0061 amendment: includes carry no `{% role %}`; the includer wraps it) that both the prompt body and the extractor pull in. It is rendered:

- **at chat-start** — wrapped in the prompt body's `{% role "system" %}`, so the model (and the author's Preview) sees the target fields up front; and
- **at commit** — as the authoritative extraction contract (the fresh pass of ADR-0051 S4 / ADR-0063).

Given the same authored target type, the two renders are **identical by construction** — the list cannot drift across the conversation, and it is *visible* at both points. This realises the two-step intent without duplicating the list.

### 3. A new Jinja helper renders the field contract

The hand-inlined descriptor loop becomes a **helper** the app provides — sketch: `field_contract(target_type, only=None)` (name illustrative) → the rendered "fields you may set" contract for that type: each proposable field's id, label, type, options, and item-shape, in the exact wording the extractor needs, narrowable by `only`. It is the single source of the descriptor/item-shape rendering (the "one source, not two" the extraction module already prizes), now callable from any prompt or include rather than copy-pasted. The related raw helper `fields()` stays as the field *roster*; `field_contract` is the *rendered contract* built on it.

### 4. The target type is authored; the caller binds the instance

Per ADR-0065 Amendment 1 §2 and ADR-0063 S1: the **target type is authored on the prompt** (so a location prompt can't be aimed at a character). The caller supplies only the **instance** — the existing node to update (of that type), or nothing (a create). `create` vs `update` falls out of "is there a subject?"; `diff` (ADR-0065 Amendment 1 §2) governs the review.

## Why / rejected alternatives

**Keep `output.commit.fields` as a static per-type list.** No home once types collapse to `{general, snippet}`; and even before that it was a hand-maintained list of bare field-id strings with **no validation** that the ids exist on the target type — a rename or typo silently narrows to nothing. The template author is already looking at the target's fields; expressing the scope there removes the drift surface.

**Duplicate the field list at chat-start and at commit (two authored copies).** Rejected — two copies drift, which is the exact failure ADR-0051 S4 fixed. One fragment, two renders.

**Keep the hand-inlined `{% for f in fields(...) %}` loop (no helper).** Rejected — it is non-trivial (item-shape logic for list/select fields) and would be copy-pasted into every custom extractor and every prompt body that wants to show its contract. One helper, one source.

**A fully free-form extractor (arbitrary Jinja, no helper).** The author *may* write arbitrary Jinja — but the common, safe path (render this type's proposable fields) must be one helper call, not a re-derivation. The helper is the paved road, not a cage.

## Anti-goals

- **Not a re-opening of the handler set.** The output *method* set stays closed and backend-owned (ADR-0065). This ADR is only about the **field scope** of the `node` method and how it is authored/rendered.
- **Not a general template-macro system.** One curated helper for the field contract, added to the existing curated helper set (ADR-0060) — not arbitrary author-defined macros.
- **No pre-1.0 migration.** The built-in extractor + brainstorm prompts are re-authored; test projects recreated.

## Consequences

- `DEFAULT_EXTRACTION_TEMPLATE`'s inlined descriptor loop moves behind the `field_contract` helper; the built-in extractor and the brainstorm prompt bodies both render the contract via the helper (the extractor at commit; the prompt body at chat-start).
- `output.commit.fields` and the `commit_fields` request field retire (their narrowing is expressed in the template `only=`).
- The prompt **check / validator** must know `field_contract` (and the rest of the ADR-0060 helper set — see the ADR-0060/0061 amendment) so authored contracts don't flag as errors.
- ADR-0065's `prompt:extractor` withdrawal (Amendment 1 §3) lands here: the default extractor is a `general` + `headless` prompt whose body is one `field_contract` call.

## Slice plan (proposed — one lane, disjoint, vertical)

- **S1 — the helper.** Add `field_contract(target_type, only=None)` to the prompt helpers + the check's known set; re-point `DEFAULT_EXTRACTION_TEMPLATE`'s loop at it (behaviour byte-identical).
- **S2 — the fragment + two-step render.** Author the field contract as a role-less include; render it at chat-start (in the brainstorm prompt body) as well as at commit; retire `output.commit.fields` / `commit_fields`.
- **S3 — the built-ins.** Re-author the brainstorm/extractor built-ins onto `general` + config + the helper (folds ADR-0063 S2's #1174 and ADR-0065 S3's collapse).

## Open questions (for review)

- **Helper surface:** is `field_contract(type, only=…)` the right shape, or should narrowing be by *inclusion* (`only=[…]`) *and* *exclusion*, and should it take the whole contract wording or just the descriptor list (leaving prose to the author)?
- **Chat-start injection:** the field contract at chat-start is *guidance*; should it be the same rendered text as the commit contract, or a softer "you'll be asked to produce: …" phrasing that shares only the field set?
