# ADR-0061: A snippet carries its fields — inclusion contributes field definitions

- Status: **Proposed** — 2026-08-16. Awaiting Anton.
- Issue: #1104 · Pre-1.0 (no release milestone)
- Follows: ADR-0054 (a prompt picks a disposition + optional commit; **`inputs` and `offer_on` live on the node's front-matter**, read as structured metadata), the prompt-as-kind model (four concrete bases; `snippet` = "a prompt with no invocation contract")
- Depends on: the template-language thread's rename of `{% include %}` → `{% snippet %}` (ADR-0060 area). This ADR is written in terms of `{% snippet %}` and adds only the *field* semantics; the directive itself is that thread's.
- Relates: ADR-0039 (layered `metadata.schema.yaml` inheritance — the *nearer-wins* precedent reused here), ADR-0040 (the reference index / reverse adjacency the dependency alert reads), ADR-0057 (lore is gated by **runtime execution**, never a static text scan — the mirror-image distinction this ADR draws for *fields*)
- **Verified against `f0c20603` (2026-08-16).**

## Context

A prompt declares its `inputs` on its front-matter and references them in its Jinja body as `{{ input.<name> }}` (ADR-0054). A **snippet** is a prompt with no invocation contract — reusable text pulled into another prompt's body by name (`{% snippet "house_voice" %}`).

Today inclusion carries **only the text.** If a snippet's text references `{{ input.tone }}`, the *including* prompt must **re-declare `tone`** in its own `inputs`, or the render fails (the Jinja sandbox is strict-undefined). So a snippet cannot be self-contained: its input contract leaks upward into every prompt that includes it, hand-copied and free to drift. The abstraction — "reuse this fragment" — is broken by the requirement to also reproduce the fragment's parameters.

This lands on more than the editor. A prompt's inputs drive **four surfaces** — the invocation dialog, the preview inputs panel, chat's inputs strip, and the prompt editor's inputs list. Each reads "the prompt's declared inputs." If a snippet's fields aren't part of that set, every one of them asks for the wrong inputs.

## Decision

A snippet contributes its **field definitions**, not only its text. A prompt's inputs become its **effective** inputs.

### 1. Effective inputs = own ∪ the transitive union of included snippets' inputs

A prompt's effective input set is its own declared `inputs` plus, recursively, the `inputs` of every snippet it `{% snippet %}`-includes. A snippet that includes another snippet contributes that one's inputs too.

### 2. Fields are gathered statically, before render — always

The input form must exist **before** the template runs: the user fills it, *then* the body renders. So effective inputs come from a **static scan** of literal `{% snippet "name" %}` tags in the body, recursively — not from executing the body.

- **Runtime conditionals decide execution, never gathering.** A snippet inside `{% if … %}` still contributes its fields; the condition only decides whether that fragment is *expanded* at render time. (This is the deliberate inverse of ADR-0057's lore gate, which is a *runtime execution* signal precisely because a conditional makes source a wrong predictor. Here the opposite is wanted: the form must over-provide, never under-provide, so it is built from *source*, not execution.)
- **A dynamically-named snippet contributes nothing.** `{% snippet input.x %}` cannot be resolved statically, so it adds no fields. **Literal names are the contract** for field inheritance.

### 3. Collisions resolve nearer-wins, and a type clash is surfaced

When names coincide, resolution mirrors the layered `metadata.schema.yaml` merge (ADR-0039): **nearer wins.**

- The **outer prompt** overrides an included input's `default` / `label` / `hidden`. The **snippet owns the input's existence and its type** — the outer prompt selects, it does not redefine.
- **Same-name, different-type across snippets is a conflict.** It is **surfaced as an error** (in the preview and the editor), never silently resolved to one type — because a silent pick would mean a change to one snippet quietly breaks a prompt that includes both.

### 4. One resolver, in the backend, read by every surface

Effective-inputs resolution lives in a **single backend resolver**. The invocation dialog, the preview, chat's inputs strip, and the editor all read *its* output — the set is computed **once**, not re-derived per surface (one traversal, not four; a per-surface copy is exactly the drift this ADR removes). Cycle detection and a recursion-depth guard live in that resolver.

### 5. A `{% snippet %}` inclusion is a reference edge, so dependents are alertable

Because a chat persists its input **values** and, transitively, its snippets, editing a snippet's fields can invalidate a resumable chat or an including prompt. A `{% snippet %}` reference is recorded as a **graph edge** (ADR-0040's extraction), so the reverse index can answer *"what includes this snippet?"* — and the editor **warns on edit**: *"used by N prompts / M chats — changing these fields may affect them."* The warning is advisory (it never blocks the edit); its obligation is to name the count truthfully.

## Why / rejected alternatives

**Keep re-declaring the fields in the outer prompt (status quo).** Rejected — it is the leak. The snippet is not reusable if reuse means also hand-copying its parameters, and the copies drift the moment one side changes.

**Gather fields dynamically, from the rendered output.** Rejected — impossible by ordering: the form is filled *before* the render, so the set of inputs must be known without running the template. Static gather is not a choice, it is a constraint.

**First-wins / farthest-wins / error-on-any-duplicate collision rules.** Rejected in favour of **nearer-wins** because the codebase already has exactly this merge — layered schema inheritance (ADR-0039) — and a second, different override rule for the same shape of problem is a contract leak. A type clash is the one case nearer-wins cannot quietly absorb, so it is surfaced rather than resolved.

**Compute the effective set per surface.** Rejected — four consumers each walking the includes is four chances to disagree; the resolver is the single traversal ([[feedback-one-traversal-not-six]]).

**Silently coerce a same-name type conflict.** Rejected — it converts an authoring error into a running-chat break with no signal. Surfacing it is the whole point of §3.

## Anti-goals

- **Not a new input type or a new template directive.** This is a *resolution rule* over the existing `inputs` model and the `{% snippet %}` directive (owned by the template-language thread). Field-gathering adds no syntax.
- **Field-gathering never depends on render-time state.** The form is a static function of the body's literal `{% snippet %}` tags — never of what a conditional evaluates to (§2), and never a runtime signal (unlike ADR-0057's lore gate).
- **The outer prompt does not redefine an inherited input's type** — only its `default` / `label` / `hidden`. Retyping-on-inherit is out of scope (below).
- **The dependency alert is advisory, not a gate.** It names a count; it does not prevent the edit or cascade-migrate chats.
- **No pre-1.0 migration.** Prompts and snippets are re-authored to the new shape; test projects are recreated.

## User journey

A writer authors a snippet **"villain voice"** that declares one input, `menace` (a `select`), and whose text reads `{{ input.menace }}`. In a separate revise prompt they write `{% snippet "villain_voice" %}`. The prompt's **Inputs** now shows `menace` as an **inherited** field, tagged *from villain_voice* and read-only there; the preview, the run dialog, and — when this prompt is offered in a chat — chat's inputs strip all ask for `menace`. Later they open the "villain voice" snippet and change `menace`'s options; the editor notes *"used by 2 prompts / 3 chats."* They proceed knowingly.

## Consequences

- **A backend effective-inputs resolver** — the single source, read by the invocation dialog, preview, chat inputs strip, and the editor. Holds cycle/depth guards.
- **`{% snippet %}` becomes an extracted reference edge** (ADR-0040), so *"what includes this snippet?"* is a reverse-index lookup.
- **The editor's Inputs surface becomes two-tier** — own inputs, then inherited-from-snippet inputs with provenance, the inherited ones read-only. That is consumed by **ADR-0062** (the editor overhaul) and is the reason its Inputs surface needs room.
- **A same-name/different-type conflict is a first-class error state** in the preview and editor.
- **The dependency alert** rides the reverse index on the snippet editor's save path.

## Slice plan — one lane, disjoint, vertical (reorderable)

- **S1 — the resolver.** Static `{% snippet %}` scan → transitive effective-inputs union, nearer-wins merge, cycle/depth guard, in one backend function. Unit-tested (no UI). Every existing surface switches to reading it; behaviour for prompts *without* snippet-inputs is unchanged.
- **S2 — the reference edge + conflict surfacing.** Record `{% snippet %}` as an edge (dependency lookups light up); surface the same-name/different-type conflict in the preview.
- **S3 — provenance in the editor + the dependency alert.** The two-tier Inputs list (own vs inherited, inherited read-only) and the "used by N/M" warning on a snippet's save. *(Composes with ADR-0062's Inputs sub-tab.)*

## Deliberately out of scope (deferred, with a named trigger)

- **Retyping or renaming an inherited input at the include site** (an alias / remap). The outer prompt overrides only presentation-ish aspects (`default`/`label`/`hidden`) today. **Trigger:** a real prompt that must include a snippet but bind its input under a different name/type — not built speculatively.
- **A full dependency-impact review UI** (which chats, diffed, with per-chat repair). The alert names a count only. **Trigger:** the count proving insufficient in practice — a writer who needs to *see and fix* the affected chats, not just be warned.
- **Cross-kind field inheritance** beyond prompt→snippet (e.g. a prompt pulling a lore entry's field defs). This ADR is prompt/snippet only; the mechanism is not generalised speculatively.
