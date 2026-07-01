# ADR-0008: Mutable names segment the implicit-context matcher

- Status: Accepted (deferred to v1.1+) — 0.4.0 planning, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `docs/design/mid-scene-lore-mutations.md` §4.4
- Related: `memory/decisions_implicit_context.md`

## Decision
The implicit-context matcher must be **effective-name-aware**. `name` / `title` / `aliases` are
both mutable fields **and** the strings the matcher compiles to auto-inject mentioned entities.
Only mutations to those fields change the matchable set, so they partition the manuscript into at
most **N+1 segments** (N = count of name/title/alias mutations — rare). Compile **one matcher per
segment**, keyed on the mutations-index version, and scan each scene with its segment's matcher.
Non-name field mutations never touch the matcher. This applies to **both** the backend send-time
scan and the frontend per-keystroke highlighter.

**Scope:** deferred to **v1.1+**. Implicit context's send-time pipeline is itself only partly
built; v1.0 may compile from base names only (a renamed entity simply isn't auto-injected under its
new name yet), with the limitation documented.

## Why / rejected alternative
A single matcher compiled from base (or current) names misses a renamed entity under the name it
doesn't carry — "John" who becomes "Jonathan" wouldn't be detected as "Jonathan" (or vice-versa).

The **union matcher + post-filter** alternative — compile once over *every* name-form any entity
ever has, then drop hits whose form isn't effective at the scene — is simpler (one compile) but
**over-matches when a name is reused across eras** (a name belonging to a different entity in a
different span). Per-segment is precise, and cheap: compiling a merged regex-OR is <5ms even at 10k
patterns and is compile-rare (only when a name/alias base or mutation changes). N is small.

## Consequences
- This is the **one** place mutable metadata reaches past value-resolution (ADR-0006) into the
  detection layer — worth an ADR precisely because it's the exception to "mutations only affect
  resolved values."
- Both matcher consumers pick the matcher for the scene's segment; segment set invalidates with the
  mutations-index version.

## Amendment (v1.1, 2026-07-01) — per-resolution-scene, not precompiled segments
Verified against the shipped consumers: neither scans the whole manuscript. Backend `_alias_match`
(`services/ai/helpers.py:748`) scans the **chat user message** at the chat's **one** resolution
scene (ADR-0012); the frontend highlighter (`implicitContextMatcher.ts:62`) scans **one open
scene's** prose. So the "N+1 segments across the manuscript" framing collapses to the primitive both
actually need: **the effective name-set as-of scene X**. v1.1 delivers a small
`GET /api/scenes/{id}/effective-names` read and feeds it to both consumers, rather than precompiling
per-segment matchers. Resolution is **scene-granular** (a mid-scene rename uses the scene's
end-of-scene name-set) — documented limitation. The full segment machinery would only be warranted
if something ever scanned many scenes in one pass; nothing does. See
`mid-scene-lore-mutations-v1.1.md` §4.
