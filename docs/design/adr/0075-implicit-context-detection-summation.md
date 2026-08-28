# ADR-0075: Implicit context is detected on each side from one shared name-set, never handed across

- Status: **Accepted** — 2026-08-28, Anton
- **This ADR is a summation — qualified by §7.** For the settled design (§§1–6)
  it decides nothing new: those decisions were made and shipped incrementally, had
  no single home (so "does the backend scan `long_text` fields?" had no answer a
  reader could find), and an implementation gap hid behind that. This gathers them
  into the one authoritative reference for implicit / dynamic context detection.
  The qualification is **§7**: it stated the implementation gap plainly and
  *authorized* closing it — a summation plus one named, bounded forward step, not a
  pure record. That forward step is **now done**: §7 records the gap closed across
  slices 1–4. (Two §3 rules — the possessive and space≡hyphen — were likewise
  decided here as new behavior; §7 tracked them from not-yet-in-the-code to shipped
  in slice 2.)
- Verified against `fd03deac` (2026-08-28).
- Consolidates: the `decisions-implicit-context` design note (2026-06-20);
  ADR-0008 (effective-name-aware matcher); `snapshots-and-the-witness.md` §4
  ("where the dynamic context comes from"); `mid-scene-lore-mutations.md` §4;
  `frontend/benchmarks/` (the algorithm benchmark); ADR-0057 (the one gated
  selector); #447 (no FE→BE list handoff, closed maintainer-WONTFIX).
- Feature: #33 / #439 / #447 lineage · Relates: ADR-0008, ADR-0043, ADR-0057.

## 1. What implicit context is

**Implicit (dynamic) context is the automatic injection of entities named in the
author's prose into the AI's context.** When the author writes "Bob" in a scene
or a chat message, Bob's lore entry is added to what the model sees, without the
author picking it. It is the counterpart to the explicit context picker
(ADR-0074): same entity-index plumbing, no author action.

**The on-screen highlight is a promise, and the promise is the feature.** The
coloured underline + hover preview the author sees while typing is *secondary* —
it tells the author "this entity will be in context." The actual product is that
the model then *does* receive it. When the highlight and the delivered context
disagree, the highlight is a **silent lie in the most expensive direction**: the
author stops checking precisely because the UI appears to confirm it (the
motivating harm in #447).

Detection is over **author-authored prose only** — never assistant replies (that
would let tool output inject context) and never template source (code, not
prose).

## 2. The detection surface — what text is scanned

Decided in the design note (§"Surface coverage"). Detection runs on:

- the **scene body** (prose),
- **every `long_text` field** — `summary`, `description`, `notes`, and any
  schema-defined `long_text` field,
- the **chat composer** (the user's typed message),
- the **first-turn rendered prompt output** (Jinja renders once; names surfaced
  via `{{ entry('x').name }}` are on the wire, so they count).

Plus **depth-1 textual expansion**: an entity named inside a *matched* entity's
body is pulled in one hop; those pulled-in bodies are **not** re-scanned (depth
strictly 1, to bound the fan-out).

Detection does **not** run on: single-line `text` fields (name/title — recursive
nonsense), the `aliases` field (circular), Jinja template source, or assistant
replies.

Structural expansion (following `entity_ref` graph edges) is a **separate,
opt-in** mechanism — a template helper the author calls explicitly — not part of
automatic textual detection. The author did not want structural refs auto-followed
by default.

## 3. The algorithm — regex-OR; Aho-Corasick / a hand-rolled trie is rejected

The matcher is a **merged regex-OR** (`(Bob's house|Bob|…)`, effective-name
alternation) compiled over each in-scope entity's title + aliases. Three
semantics are load-bearing and must hold identically on both sides:

- **Longest match wins (maximal munch).** Where two names overlap at a position —
  "Bob" and "Bob's house" (or "Bob" and "Bob Smith") — the **longest** is the
  match and the shorter is not detected. The prose "Peter walked to Bob's house"
  detects **Bob's house**, not Bob. This is not free from a regex alternation
  (which is leftmost-*first*, ordered): it requires the alternation to be built
  **name-length-descending**, so the longest candidate is tried first at each
  start (`implicitContextMatcher.ts` sorts refs by length desc for exactly this).
- **Case-insensitive match, original-casing render.** "Bob's House" in the prose
  matches the entry "Bob's house"; the highlight paints the prose's own casing.
- **A possessive or enclitic attaches to the name; it does not break it.** A base
  name may be followed by `'s`, a lone `'` (plural / classical possessive — "the
  Smiths'", "Jesus'"), or a contraction enclitic (`'ll` / `'d` / `'re` / `'ve`) and
  still matches: "Bob's house" detects **Bob** (when no longer "Bob's house" entity
  outranks it by maximal munch), because a possessive *is* a reference to the
  entity. An apostrophe *inside* a token still blocks — "O'Brien" does not let
  "Brien" match. So the boundary is: name, an optional trailing `'`-clitic, then a
  real word boundary — not bare `\b`, and not the blanket "any apostrophe extends
  the word" that would (wrongly) hide the possessive.
- **Space and hyphen are one separator; fusion is not.** A multi-word name matches
  across a space *or* a hyphen — "Code Warrior" detects "code-warrior" (its internal
  separator compiles to `[\s-]+`), because hyphen and space are interchangeable
  stylistic variants ("well known" / "well-known", "Spider-Man"). A **fused**
  spelling ("codewarrior") is deliberately **not** auto-matched: matching it needs
  separator-stripping normalization that discards the word boundaries and hit
  positions the matcher relies on, and a closed compound is an authorial choice,
  not whitespace variance — so the fused spelling belongs in an **alias**, the
  author's explicit control. Single-word boundary behavior is unchanged (a bare
  "Warrior" still matches inside "code-warrior"; maximal munch lets "Code Warrior"
  win when both entities exist).

**Aho-Corasick (and any hand-rolled trie automaton) was benchmarked and
rejected** (`frontend/benchmarks/`, run 2026-06-20; reproduce via
`matcher.html`). At the reference scale (5000 patterns ≈ Honorverse, a 200-char
per-keystroke window, a 50 KB scene):

- regex-OR **0.0018 ms**/keystroke vs Aho-Corasick **0.0053 ms** — regex-OR is
  **2.6–4× faster across every tested scale** (100–10k patterns × 1 KB–500 KB
  text), and the two **agree exactly on hits** (147 hits at identical positions
  at 5000 patterns × 50 KB).
- Compile is single-digit ms even at 10k patterns and fires only on entity-set
  change, not per keystroke.

The theoretical Aho-Corasick win (O(n) regardless of pattern count) **does not
materialize at our scale**: V8's compiled regex engine plus the *trie-fused
alternation it builds internally* gives regex-OR a constant-factor advantage that
swamps the asymptotic difference up to ~10k patterns. So the hand-rolled trie
loses to letting the engine build the trie natively — while costing ~120 LOC
against regex-OR's ~30. **Re-evaluate only** past ~50k patterns (5× the worst
realistic case) or if a per-keystroke window scan ever measures > 1 ms in real
use.

The matcher is **effective-name-aware** (ADR-0008): it compiles from the entity
name-set *as of the resolution scene*, so a renamed entity is matched under the
name it carries there. The name-set is served by `GET /api/scenes/{id}/effective-names`.

## 4. No list handoff between frontend and backend

**Each side runs its own matcher over the shared name-set; neither hands the
other its results.** The shared artifact is the **name-set** (the entity-index /
effective-names endpoint), *not* the hit list.

This is the ruling in #447 (closed maintainer-WONTFIX): the frontend must not
offer its implicit-context list to the backend. Two reasons make an FE→BE handoff
wrong, not merely unnecessary:

- **The backend cannot trust a list it did not derive.** The genuinely breaking
  case is a **manual edit of the backing document** — which the frontend never
  observes, so its list is stale exactly when it matters.
- **The backend is the authority for what reaches the model.** Context assembly
  is a send-time backend concern (ADR-0057); a frontend product cannot be load-
  bearing for it.

So there are, by design, **two implementations of one specified algorithm** —
they share the name-set and the *spec* (§3), never the code: a TypeScript regex-OR
over a ProseMirror document (the highlighter) and a Python detector over raw text
(the backend). Today they are not even the same shape — the frontend is the
positional, longest-match regex-OR §3 describes, while the backend `_alias_match`
is a word-**set membership** test that resolves no overlaps (§7) — which is
precisely why §5 makes their agreement a standing gate rather than an assumption.

(The snapshot **witness** (ADR-0043) is a separate consumer with its own
resolution: there the frontend *does* own the scan and ship its set on save,
because the witness records what the author saw. That is orthogonal to AI-context
detection and is not changed here.)

## 5. Testing — the FE/BE parity gate

Because §4 mandates two independent implementations of one algorithm, **their
agreement must be a gate, not a hope.** This is a first-class, standing test — not
a one-off benchmark check.

- **One hand-authored fixture corpus**, checked into the repo: a set of cases,
  each `{ name-set (entities with titles + aliases), input text, expected hit
  ids + positions }`. **Hand-authored is load-bearing** — a corpus generated from
  either matcher grades the code against itself and proves nothing (the concrete
  lesson from an earlier snapshot slice that shipped self-generated fixtures;
  `snapshots-and-the-witness.md` §4).
- **Both suites assert against that one corpus.** A `pytest` case drives the
  backend detector (`_alias_match` and the detection path); a `vitest` case drives
  the frontend matcher (`implicitContextMatcher`). Each asserts its matcher
  reproduces the corpus's expected hits. If both pass the same independent oracle,
  they agree with each other — transitively, without a cross-language bridge.
- **The corpus must exercise the drift-prone cases**, since those are where two
  hand-tuned regex engines diverge: **longest-match / overlap** ("Bob" vs "Bob
  Smith" over "…Bob Smith" → only Bob Smith; §3); **possessive attaches** ("Bob's
  house" → Bob when no "Bob's house" entity; plural "the Smiths'") while an
  apostrophe *inside* a token blocks ("O'Brien" ↛ "Brien"); **space ≡ hyphen**
  ("Code Warrior" matches "code-warrior") but **fusion does not match without an
  alias** ("codewarrior" ↛ "Code Warrior"); case folding (match case-insensitive,
  render original casing); multi-word and aliased names; effective-name-as-of-scene
  renames; the reused-name-across-eras case (ADR-0008); unicode / punctuation
  adjacency.
- **It lives in the two test suites, not a `gates.yml` step** (per #435), so it
  runs on Windows with everything else and **cannot be deleted unnoticed**.

A single cross-compiled matcher (one implementation, both runtimes, à la the
ViewExpr IDL of ADR-0041) is **rejected here as over-built**: at this scale two
~30-LOC regex-OR functions plus the corpus gate is cheaper to own than a shared
codegen pipeline, and the gate makes divergence a failing test rather than silent
drift.

## 6. The journal and the one gate

Detection fires **at send time, not per keystroke** — mid-typing "Sam… no, Helen"
must not pollute anything. Detections accumulate on the chat's **per-session,
append-only journal** (monotonic: once an entity enters scope it stays for the
session), which keeps the assembled context **cache-coherent** — a new detection
invalidates only forward.

The journal is one **input** to the single gated lore selector (ADR-0057), not a
rival selector: the final set is `{ explicit picks ∪ detected (journal) ∪ always }
− { never, manual_only }`, deduped by id, gated on `lore_enabled`. An auto-added
entity is surfaced to the author (an audit chip with a "remove + suppress for
session" action) — **visible** auto-injection is fine; hidden is what scares.

## 7. Implementation gap — closed (slices 1–4)

The design above is the decided target, and the send-time pipeline was built
incrementally toward it. **As of slice 4 the pipeline has reached §2 in full.**
This section records what the gaps were and how each closed — a summation that
hid a shortfall would be worse than one that names it.

The **surface-coverage gap** — backend detection once scanned only the chat
composer (`expand_context`) and the scene `summary` (`_implicit_lore_ids`), not
the scene body or the other `long_text` fields — is **closed**: slice 3 (#1495)
added the scene body + every `long_text` field on both send paths via the shared
`_scene_prose_ids`, and slice 3b (#1502) added the first-turn rendered prompt
output (`expand_context`'s `rendered_text`). The highlight's promise (§1), once
only partly kept — the live defect `snapshots-and-the-witness.md` §4 named and
#447's "why it matters" section described — is now kept for every scanned surface.

The **second axis — the backend matcher was not the §3 algorithm — is now
closed** (slice 1, #1486). `_alias_match` previously did a per-entry word-**set
membership** test (no overlap resolution, no maximal munch: "Bob" and "Bob Smith"
over "…Bob Smith" returned **both**, and it used standard `\b`). It now delegates
to a positional longest-match regex-OR (`services/ai/name_matcher.py`) that
mirrors the frontend, apostrophe-aware boundary and all, whose hit set feeds the
same journal. The §5 parity gate proves the convergence rather than trading one
silent disagreement for another.

Two of the §3 rules were **new behavior on both sides** — the frontend used to
*block* the possessive (its boundary rejected "Bob" before "'s") and neither side
unified space with hyphen. They **landed as a lockstep change in both matchers**,
gated by the same corpus, in slice 2 (#1490); the corpus's possessive,
space≡hyphen, and deterministic-tie-break rows are the standing guard. Case
folding stays IGNORECASE-based: common accented letters (é/É) fold identically
across Python and JS, while the rare fold-divergent characters (Greek final sigma
ς/σ, Turkish İ/ı, ß/ẞ) are an accepted known limitation, not guaranteed identical.
The `[\s-]+` separator class carries the same caveat: ordinary whitespace and
non-breaking spaces are treated identically on both sides, but the engines' `\s`
sets differ on a few exotic characters (e.g. U+FEFF), so a name split by one of
those is a matching corner both sides are not guaranteed to agree on.

The mirror-image shortfall was a **UI over-promise**: the highlighter decorated
names the backend would drop. Slice 4 (#1508) closed it — `compileMatcher` now
skips `never`/`manual_only` `context_policy` entries, so the highlight decorates
exactly the entities detection delivers (the surface gating — scene body +
`long_text` only, never single-line `text` or `aliases` — was already correct).
With every §2 surface scanned and the highlighter policy-aligned, **the highlight
is once again a promise the backend keeps**, and this ADR's §7 gap is resolved.

## Rejected alternatives (consolidated)

- **Frontend hands the backend its hit list** — #447. The backend can't trust a
  list it didn't derive; manual doc edits are invisible to the FE.
- **Aho-Corasick / hand-rolled trie** — benchmarked 2.6–4× slower than regex-OR
  at our scale, for 4× the code; the engine builds the trie natively. §3.
- **A single cross-compiled matcher (ViewExpr-IDL style)** — over-built at this
  scale; two small regex-OR impls + the corpus gate is cheaper. §5.
- **Self-generated parity fixtures** — grade the code against itself; the corpus
  must be hand-authored. §5.
- **Auto-following structural `entity_ref` edges by default** — kept opt-in via a
  template helper; automatic detection is textual only. §2.
- **Union matcher + post-filter for effective names** — over-matches a name reused
  across eras; per-resolution-scene name-set instead. ADR-0008.

## Consequences

- Implicit context now has one place a reader (or a future ADR) can cite for
  *what is scanned, by what algorithm, and why the two sides can't drift* — the
  scatter that produced this session's confusion is closed.
- The FE/BE mismatch is settled as **incomplete implementation**, not a design or
  documentation defect: §2 is the decided surface, §7 is the shortfall, and the
  parity gate (§5) is the standing guarantee that closing it keeps the two sides
  identical.
- The parity gate is a prerequisite for the surface-coverage slices: a backend
  that newly scans the scene body must be provably identical to the highlighter
  the author already trusts, or it trades a silent under-promise for a silent
  disagreement.
