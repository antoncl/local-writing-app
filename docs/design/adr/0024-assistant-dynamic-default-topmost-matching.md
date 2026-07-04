# ADR-0024: Assistant dynamic default = topmost matching; the ★ default flag is retired

- Status: Accepted (v1) — 0.5.0, 2026-07-02
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §6.3 · Issue: #35
- Governed by: `memory/decisions_author_vs_runtime_authority.md`

## Decision
Resolves #35 use case 3 (tagged-assistant picker scoping) and open question 6 (dynamic default):

- The built-in `assistant` entry_type gains a **`tags` field** (default-schema addition;
  tag-scope auto-broadening applies unchanged).
- A prompt declares its assistant constraint as a **source over `kind: assistant`**
  (e.g. `tagged: summary`), per ADR-0023.
- The assistant picker renders that view as a **soft partition**: matching assistants first (in
  manual drag order), the rest reachable below a divider.
- **Dynamic default = the topmost matching row**; if nothing matches, the topmost overall.
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
