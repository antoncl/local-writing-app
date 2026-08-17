# ADR-0063: Commit runs an author-previewable extractor prompt to a declared target

- Status: **Accepted** — 2026-08-17 (Anton). Approved over the prompt/field-system design session.
- Issue: #1107 · Pre-1.0 (no release milestone)
- **Supersedes** ADR-0054 §Why — the `output.extract` rejection (on grounds that no longer hold; see Decision §Why). **Realises** ADR-0054's deferred `commit.target` (whose named trigger is now met).
- Follows: ADR-0054 (a prompt picks a disposition + optional commit), ADR-0046 (AI edit is a reviewable patch; **validate-on-return** is the safety guarantee), ADR-0059 (body-as-field, `ai_proposable` gates authorship), ADR-0049 (the built-in Library — the default extractor's home)
- Composes with: ADR-0061 (the extractor is a prompt → it gets effective inputs / snippets), ADR-0062 (the extractor gets the Template/Preview sub-panes)
- **Verified against `4c93d820` (2026-08-17).**

## Context

The Commit button today runs a **hardcoded, app-owned Jinja template** (`DEFAULT_EXTRACTION_TEMPLATE`, `services/ai/extraction.py`): it instructs the AI to emit the target type's proposable fields as JSON (the field list generated from `field_catalog(entry_type)`), and on reply the backend parses → validates each field against the schema (**validate-on-return**, ADR-0046) → diff-reviews → writes back. Two limits surface once you try to bring in richer prompts:

1. **The extractor is the one prompt body in the app with no preview and no author control.** Its only knob is `commit.fields` — a **blind, typo-prone YAML id-list** with no feedback until it silently produces the wrong field set. ADR-0054 rejected the author-Jinja alternative (`output.extract`) on the premise that a *field-picker is more legible than arbitrary Jinja* — but in practice the "picker" is hand-edited YAML, and the Jinja alternative, being a prompt, would get the **preview loop for free**.
2. **Commit is welded to the launch subject.** A portable prompt whose payoff is a structured artifact aimed *elsewhere* can't say where it commits. (ADR-0054 deferred `commit.target` with exactly this trigger: "the first prompt that needs to commit somewhere other than its launch subject.")

The concrete case that exposes both — imported from NovelCrafter — is a McKee **"Character Spine Wizard"**: an interactive chat that walks the author through four spine elements (conscious desire, unconscious desire, controlling belief, backstory wound) and whose payoff is a clean **Character Spine** the author reuses across other prompts. Its commit produces four named fields, aimed at a character-spine node, and the author wants to *see* the extraction it will run.

## Decision

### 1. Commit runs an extractor *prompt*

The button runs an **extractor prompt** over the transcript → parse → validate against the declared target type → diff-review → write. This is today's pipeline, now modelled as "run a prompt," not a hardcoded constant.

### 2. The extractor is a first-class, previewable Jinja prompt

Its body is authored and **previewed** in the same editor as any prompt body (ADR-0062's Template/Preview). The **default** extractor is the generated all-proposable-fields contract (`field_catalog(target)`); the author edits it to filter, reorder, or add per-field guidance, and **sees the rendered contract**. Preview renders the contract from the target's field list alone — **no transcript needed at author time** (the transcript is a runtime input appended when Commit fires).

### 3. `commit.target` names the destination type

A prompt declares the kind/entry_type it commits to (**create-or-update** a node of that type). **Default (no target) = patch the launch subject** — today's behaviour. So `field_catalog` and validation always have a schema, independent of launch context.

### 4. The write stays app-gated — so author-Jinja is safe

Validate-on-return is unchanged (ADR-0046; ADR-0059's `ai_proposable` via the single `is_proposable_field` predicate): whatever the extractor *asks* for, the backend validates every returned field against the target type's schema and **drops illegal / non-proposable ones** before the review. **The author controls the *ask*; the app controls the *write*.** Author-authored Jinja cannot corrupt the data — at worst it asks for something that's dropped, which the preview shows.

### 5. `commit.fields` retires into the previewable Jinja

The filter is now *visible* in the extractor body + preview, so the blind YAML list is superseded. It optionally survives **only** as a write-ceiling guardrail (belt-and-suspenders — an allow-list the write may never exceed); the primary authoring surface is the extractor prompt.

### Why / rejected alternatives

**Supersede ADR-0054's `output.extract` rejection.** 0054 rejected author-Jinja extraction for two reasons, **both assuming it lived as a Jinja string in the schema-type**: (a) not authorable — a field-picker is legible, arbitrary Jinja isn't; and (b) the escaped-string-in-schema mess (#859). Making the extractor a first-class **prompt node** (not a schema string) defeats both: it's edited in the same code editor as any prompt body — as authorable as the chat itself — and there is no escaped string anywhere. And it **inverts (a)**: the blind `commit.fields` YAML is the *less* legible, *more* typo-prone form; a previewable Jinja extractor lets the author *see* the rendered contract and catch a mistyped field. **The preview is the safety net the declarative list never had** — and the real prize, not "Jinja" for its own sake.

**Keep `commit.fields` (blind YAML) as the primary control.** Rejected — it is precisely the thing being fixed (no preview, silent typos).

**Inline the extractor body onto the chat prompt (a second body).** Rejected — couples chat and extractor, breaks one-body-per-prompt, and isn't reusable. The extractor is *referenced* (default = the built-in), so it can be shared.

**Generalise to arbitrary backend-handler dispatch** (Commit runs any registered handler, not just a node write). Out of scope — the target is always "produce a node of type T." A non-node handler is deferred with a trigger.

## Anti-goals

- **Not arbitrary handler dispatch.** Commit still produces a node patch/draft of a declared type; genuinely different backend actions (a todo, a plot card, a scene) are deferred to the first prompt that needs one.
- **The write stays app-gated** (validate-on-return). Author-Jinja shapes the *ask*, never the write.
- **No technique lives in code.** McKee's spine is *data* — a prompt (the wizard) + a schema (the four fields). The app learns only "a prompt names its target and its extractor," never anything about spines.
- **Not a node-picker for `commit.target`.** It names a **type** (create-or-subject); "commit to a *specific declared* node" is deferred with a trigger.
- **No pre-1.0 migration** — the built-in extraction template is re-authored as the default extractor prompt; test projects recreated.

## User journey

A writer imports (or authors) the **Character Spine Wizard** — a `chat_panel` prompt that interviews them through the four McKee elements. They model a "Character Spine" in their schema (four `long_text` fields — its own entry_type, or a field-group on `character`; **their** choice). On the prompt they set `commit.target` to that type. They open the extractor's **Preview** and see the generated contract asking for exactly those four fields; they tweak the wording and watch it re-render. Later, mid-conversation, they hit **Commit**: the extractor emits the four fields as JSON, validated against the spine schema, shown as a diff, accepted, written. The spine is now a **node** other prompts pull in by reference or `{% import %}` (ADR-0061) — "paste into other prompts / keep as reference," as data.

## Consequences

- **`DEFAULT_EXTRACTION_TEMPLATE` becomes the default extractor prompt** — a built-in **Library** prompt (ADR-0049; read-only, clone-to-customise), not a Python constant.
- **`commit` gains `target` (a type) and an extractor reference** (default = the built-in). `commit.fields` retires (or demotes to a write-ceiling guardrail).
- **The extractor renders through the ordinary preview pipeline** (it already does) and gains a **Preview** surface (ADR-0062); the preview shows the contract without a transcript.
- **The extractor is a prompt**, so ADR-0061 (effective inputs / snippets) and ADR-0062 (sub-panes) apply to it directly.
- **Supersedes ADR-0054 §`output.extract`; realises its deferred `commit.target`.**

## Slice plan — one lane, disjoint, vertical (reorderable)

- **S1 — `commit.target`.** A prompt declares its target type; the extraction contract + validation resolve against it; default = the launch subject. Realises 0054's deferred item — the Wizard's "commit elsewhere" works, extractor still app-generated. *(Smallest useful slice.)*
- **S2 — extractor-as-prompt.** The built-in template becomes the default extractor prompt (Library); the chat's `commit` references it (default = built-in); it renders through the ordinary pipeline as a prompt.
- **S3 — authorable + previewable.** The author supplies/edits their own extractor Jinja and previews it (composes with ADR-0062's Preview sub-pane); `commit.fields` retires into it.

## Deliberately out of scope (deferred, with a named trigger)

- **Arbitrary (non-node) commit handlers** — a Commit that creates a todo / plot card / scene, etc. **Trigger:** the first prompt whose commit isn't "produce a node of type T."
- **`commit.target` naming a *specific existing node*** (not just a type). **Trigger:** the first prompt that must always commit to one particular node, independent of subject.
- **Authoring UX for picking a *non-default* extractor** (a shared custom extractor as its own Library prompt). The reference model allows it; the picker is deferred to its first need.
