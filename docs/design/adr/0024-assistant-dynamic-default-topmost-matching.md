# ADR-0024: Assistant dynamic default = topmost matching; the ★ default flag is retired

- Status: Accepted (v1) — 0.5.0, 2026-07-02 · **Amendment 1: the default resolves within the
  ACTIVE roster, and the picker shows only it** (2026-07-21, #333)
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §6.3 · Issue: #35
- Amended by: #332 / #333 (assistant curation) — see [Amendment 1](#amendment-1--membership-is-a-precondition-2026-07-21)
- Governed by: `memory/decisions_author_vs_runtime_authority.md`

## Decision
Resolves #35 use case 3 (tagged-assistant picker scoping) and open question 6 (dynamic default):

- The built-in `assistant` entry_type gains a **`tags` field** (default-schema addition;
  tag-scope auto-broadening applies unchanged).
- A prompt declares its assistant constraint as a **source over `kind: assistant`**
  (e.g. `tagged: summary`), per ADR-0023.
- The assistant picker renders that view as a **soft partition**: matching assistants first (in
  manual drag order), the rest reachable below a divider.
  > **Superseded by [Amendment 1](#amendment-1--membership-is-a-precondition-2026-07-21):** the
  > picker shows the **active** roster only; there is no below-the-divider remainder.
- **Dynamic default = the topmost matching row**; if nothing matches, the topmost overall.
  > **Amended by [Amendment 1](#amendment-1--membership-is-a-precondition-2026-07-21):** both
  > "topmost" clauses range over the **active** roster, not everything the app knows about.
- The explicit **`★ default` flag is retired**.

## Why / rejected alternative
Assistants already have a **manual drag order** that expresses global preference. Once a prompt
can scope the picker to a tag, "the relevant default" is simply the first matching row under that
order — no second mechanism needed. With no constraint declared, "topmost overall" degrades to
exactly today's behavior, so nothing regresses. Keeping a separate ★ flag *and* a dynamic rule
means two sources of truth for "which assistant is default"; #35 Q6 is answered **override, not
coexist**.

Rejected **keeping ★ alongside** dynamic defaults — ambiguity about which wins. Rejected a **hard
filter** in the picker — the epic requires the full list stay reachable; a soft partition keeps it
reachable while surfacing relevance first.

## Consequences
- One-line built-in-schema change adds `tags` to `assistant`; confirm auto-broadening semantics
  suit assistants (they do — same as lore).
- Default resolution reads the picker's viewed+sorted list: topmost matching, else topmost.
- Any existing ★ affordance and its storage are removed (pre-1.0, no migration).

## Amendment 1 — membership is a precondition (2026-07-21)

Recorded **as implemented** (#332 / #333), not as designed. v1 was written when the roster *was*
the set of assistants you had, so "topmost overall" could not mean anything but "topmost of what I
can use". #332 introduced curation — a per-layer `.order.yaml` naming which assistants a project
lists — and #333 gave un-listed ones a home on screen. From that point the roster carried two
populations and v1's wording silently began ranging over both.

**What changed**

- The dynamic default resolves over the **active** (listed) roster. Both of v1's clauses stand,
  with their domain narrowed: topmost *matching* within the active set, else topmost active.
- The picker shows the **active roster only**, and is empty when nothing is listed. This
  supersedes the soft partition: there is no below-the-divider remainder, and the "full list stays
  reachable" requirement is met by the Assistants pane, which is the curation surface and shows
  everything the app knows about.
- **No listed assistant ⇒ no dynamic default.** Resolution returns nothing and the caller falls
  through to the legacy provider path rather than reaching past the author's own list for
  something they never chose. Not a state reached by accident: `create_assistant_entry` prepends
  every new assistant to its layer's list, so anything made through the app is listed from birth.

**Why this shape rather than another fallback step**

v1's chain answers two questions in sequence — *which assistant suits this prompt* (tags) and
*which do I prefer generally* (manual order). Curation asks a third, and it is not a third link in
that chain: it is a precondition on the set the chain runs over. Adding "…else the topmost
un-listed one" would have made un-listing a way to keep using something, which is the exact
inversion #333 was fixing. So membership filters the input; the ordering rules are untouched.

**Consequence worth stating plainly**

Un-listing an assistant removes it from every prompt's picker and from tag-scoped defaults. That
is the intended meaning of "not in my roster" — but it is a wider blast radius than the Assistants
pane suggests, since the pane still shows the assistant, greyed into Unlisted, while its effect is
felt in surfaces the pane does not mention.
