# ADR-0067: The output field-contract is authored Jinja, rendered at chat-start and at commit

- Status: **Accepted** — 2026-08-19 (Anton). Shipped in full: the `field_contract` accumulator (#1181), read-back at commit (#1208), and the built-ins re-authored onto it (#1206).
- Issue: #1181 / #1208 / #1206 · Pre-1.0 (no release milestone)
- Follows: ADR-0065 (two prompt kinds; a `general` prompt's output is a config area — this ADR is where its *field* scope lives), ADR-0063 (commit runs a previewable extractor — this ADR is its S3, "the field contract is authored Jinja," and it retires the *separate* extractor prompt), ADR-0060 (the prompt language — the helper surface + `{% do %}` this adds to), ADR-0059 (`ai_proposable` gates which fields may be proposed), ADR-0026 (`fields()` — the roster this builds on)
- **Retracts** ADR-0065 §Grounding's "NO new Jinja helper or token is required" verdict.

## Context

ADR-0065 collapses prompt types to `{general, snippet}`, so a `general` prompt's node-write behaviour is *config*, not a sub-type (ADR-0065 Amendment 1). That collapse removes the home of the one piece of node-write config that was schema-declared per behaviour: **`output.commit.fields`** — the allow-list narrowing which of a target type's proposable fields a commit produces. It lived on `prompt:revise:scene_summary` (`[summary]`) and friends; once every such prompt is just `general`, there is no per-behaviour type to carry it.

So the "which fields" scope has to move to the only per-prompt authored surface left: **the Jinja**. And the extractor template *already* generates the field list — `DEFAULT_EXTRACTION_TEMPLATE` hand-inlines `{% for f in fields(inputs.entry_type) if f.proposable and (inputs.commit_fields is none or f.id in inputs.commit_fields) %}` and renders each descriptor. Making that authored (and narrowable in the template, not via a separate static list) is exactly ADR-0063's deferred **S3** — "the author supplies/edits their own extractor Jinja; `commit.fields` retires into it."

Two further facts force this ADR's shape:

- **The list must not drift.** ADR-0051 S4 already learned that a field contract carried through a growing chat gets unreliable, and rebuilt it fresh at commit. The recurring design intent (raised repeatedly during the ADR work) is a **two-step** contract: the fields are stated at **chat-start** (so the AI knows, and the author/user can see, what will be produced) and re-asserted at **commit** (the authoritative extraction). Both must come from **one authored source**, or the two drift.
- **The commit must know the field set without re-parsing text.** If the field list lives only as a `{% for %}` inside the prompt's system role, the Commit button would have to find-and-parse it out of rendered prose — a marker problem. The field set has to be captured as **data** when the prompt renders, so the commit reads it rather than scrapes it — which needs template-layer support ADR-0065 assumed away.

## Decision

**A node-writing prompt declares the fields it outputs inline, in the one prompt, via a `field_contract` accumulator — populated as the prompt renders, and read back as data by the backend at commit.**

### 1. One prompt — no snippet, no separate extractor

A node-writing `general` prompt carries its field contract **in its own body**. There is no second artifact to keep synchronised: no field-contract snippet to import, and **no separate "extractor prompt."** The author selects the fields with an ordinary `fields()` loop and registers them into `field_contract`; the backend reads the registered set at commit. `output.commit.fields` retires entirely.

### 2. `field_contract` is a per-render accumulator

`field_contract` is a per-render object with two operations, split so the Jinja reads honestly — **a side effect is a statement; output is an expression**:

- **`{% do field_contract.store(f) %}`** — register field descriptor `f` (from `fields(...)`) into the contract, optionally with author guidance: `store(f, note="lead with the wound")`. Emits nothing.
- **`{{ field_contract.render }}`** — emit everything registered so far as the descriptor list.

`{% do %}` — Jinja's side-effecting call that prints nothing — is a standard extension **not currently enabled** (`create_environment()` installs only `RoleExtension`); this ADR turns it on: `extensions=[RoleExtension, "jinja2.ext.do"]`.

### 3. The backend reads the registered set — no marker, no re-parse

Rendering the prompt at **chat-start** does two things at once: it prints the field list into the system role (`{{ field_contract.render }}` — so the model and the author's Preview see it up front), **and** it leaves the backend holding the **registered field set as data.** So the Commit button never has to find-and-parse a `{% for %}` buried in the system role (the marker problem): it reads the set the render already captured. At **commit** the backend emits that same set inside its JSON envelope (system-owned wording). Start and commit share the set by construction — they cannot drift.

### 4. Narrowing, guidance, and the write-ceiling fall out of the accumulator

- **Narrowing** is the loop's `if f.id in [...]` filter — authored, previewable, ordinary Jinja over `fields()` (`ai_proposable`-gated, ADR-0059).
- **Per-field guidance** rides the `store(f, note=…)` argument, folded in by `render`.
- **The write-ceiling** answers itself — the registered set *is* the machine-readable list the backend validates and writes against; no config remnant of `commit.fields` survives.

### 5. The target type is authored; the caller binds the instance

Per ADR-0065 Amendment 1 §2 and ADR-0063 S1: the **target type is authored on the prompt** (so a location prompt can't be aimed at a character). The caller supplies only the **instance** — the existing node to update, or nothing (a create). `create` vs `update` falls out of "is there a subject?"; `diff` (ADR-0065 Amendment 1) governs the review.

### The worked example — Goal / Motivation / Obstacle onto a character

Given a `lore:character` type with proposable `goal` / `motivation` / `obstacle`, the **one** prompt body is:

```jinja
{% role "system" %}
You're a story-development partner. Help the writer pin down one character's
drive. Probe, offer options, push back. By the end we need these three fields:
{% for f in fields(target) if f.id in ["goal", "motivation", "obstacle"] %}
{% do field_contract.store(f) %}
{% endfor %}
{{ field_contract.render }}
{% endrole %}
{% role "user" %}Let's develop {{ target.title }}.{% endrole %}
```

**Chat-start** (launched from character *Kevery* → `target` = Kevery) renders the system message with the three descriptors, and leaves the backend holding `{goal, motivation, obstacle}`. **Commit** — the backend emits, from that registered set:

```
Reply with ONLY a JSON object, no prose, of exactly this shape — one key per
field, its value the field's content:
- Goal (`goal`): What the character is consciously chasing.
- Motivation (`motivation`): The need underneath the goal.
- Obstacle (`obstacle`): What stands in the way.
```

→ validate against the schema, diff (`diff: true`), accept, write.

## Why / rejected alternatives

**A separate field-contract snippet the prompt imports.** Rejected — a second artifact the author must keep in sync with the prompt (the GMO mock surfaced exactly this). The accumulator keeps the contract in the one prompt.

**A static `commit.fields` list (even relocated to config).** Rejected — it re-introduces the hand-maintained, unvalidated id-list this ADR removes; the loop filter is authored and previewable, and the registered set is what the backend validates against anyway.

**Overload `{{ field_contract(f) }}` to register-and-return-`""`.** Rejected — `{{ }}` means "emit text"; a no-output side effect must read as a `{% do %}` statement. (A custom `{% field_contract.store f %}` tag built like `RoleExtension` is the only near-equal alternative — house-consistent, but more code than enabling `do` for no behavioural gain.)

**A `{% for %}` the backend text-scans at commit.** Rejected — that is the marker problem; the accumulator captures the set as data, so nothing is parsed back out of rendered text.

## Anti-goals

- **Not a re-opening of the output-method set.** That set stays closed and backend-owned (ADR-0065). This ADR is only the `node` method's field scope + how it is authored and read back.
- **Not a general macro/DSL.** One curated accumulator (`store` / `render`) on the existing helper surface (ADR-0060), reading `fields()` — not author-defined tags.
- **No pre-1.0 migration.** The built-in node-writing prompts are re-authored; test projects recreated.

## Consequences

- `DEFAULT_EXTRACTION_TEMPLATE` **and the separate default-extractor prompt go away**; each node-writing prompt carries its field contract inline via `field_contract`. A "revise everything" prompt registers all proposable fields (a `store` over the full `fields(target)`), so there is no default extractor to maintain. This subsumes ADR-0063 S2's #1174 and its withdrawn `prompt:extractor`.
- `output.commit.fields` and the `commit_fields` request field retire.
- `{% do %}` is enabled on the render environment.
- The prompt **check** must know `field_contract` and `{% do %}` (see the ADR-0060 amendment) so authored contracts don't flag as errors.

## Slice plan (proposed — one lane, disjoint, vertical)

- **S1 — the accumulator + `{% do %}`.** Add `field_contract` (`store` / `render`) to the helper surface, enable `jinja2.ext.do`, teach the check both; re-express today's extraction as "render the registered set" (behaviour byte-identical once the current built-ins are re-authored).
- **S2 — read-back at commit.** Commit reads the registered set the chat-start render captured (no re-parse), and emits the JSON envelope from it; retire `commit.fields` / `commit_fields`.
- **S3 — the built-ins.** Re-author the node-writing built-ins onto `general` + config + inline `field_contract` (folds ADR-0063 S2/#1174 and ADR-0065 S3's collapse).

## Open question (for review)

- **(b) Commit: cached continuation vs. fresh pass.** Because the contract is in the system prompt from turn 1, it is never buried — so the extraction can **continue the already-cached conversation** (a short "commit now" turn, no transcript re-ship) rather than run ADR-0051 S4's **fresh pass** (a small clean context, but the transcript re-shipped). The accumulator is orthogonal to this choice; it stays open pending a reliability check on the noisier continuation context.
