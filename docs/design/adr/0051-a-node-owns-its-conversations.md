# ADR-0051: A node owns its conversations — chats are subject-referencing first-class nodes

- Status: **Proposed** — 2026-08-10. Designed with Anton over the brainstorm-usability thread.
- Issue: #811 (umbrella) · Pre-1.0 (no release milestone)
- Follows: ADR-0046 (AI lore editing is a reviewable patch — the commit loop this generalizes),
  ADR-0040 (the node index — edges are a function of value **and** definition, so an added
  `entity_ref` mints edges from values already on disk), ADR-0039 (nodes materialize through the
  layer chain), ADR-0035 (`ViewNodeList` / `ViewResult` is the sole render input; `nodeSet()` is
  the degenerate non-view lift the Chats pane uses today)
- Relates: ADR-0032 Amendment 2 (`$self` removed — the reason per-entry *designable* views need a
  caller-scoped universe, not the anchor-in-spec binding), ADR-0021 (saved views are
  frontmatter-only nodes — the prior art for where a chat's structured payload lives), the
  class–instance model (`kind` = class, `entry_type` = sub-class, `entry` = instance)
- **Verified against `7989721` (2026-08-10).**

## Context

The brainstorm feature (ADR-0046) shipped a chat that revises a lore entry through a reviewable
patch, and it works. But every use of it exposes the same seam: **the brainstorm launch always
mints a new chat**, titled after the *prompt* rather than the entry, so a writer who brainstorms a
character twice gets two identically-named chats and the accumulated context of the first is
stranded (`chatSessions.svelte.ts` `openChatFromPromptEntry` — unconditional `createChatSession`).
The context machinery the app invests in — the append-only implicit-context journal and the
cache-coherent envelope — is built for *continuity*, and the entry point throws it away.

Underneath the UX complaint is a structural one. A chat has **no findable link to what it is
about**. The only trace is the originating entry id buried in the chat's `inputs.entry`, which the
roster summary omits, so "which conversations are about this entry?" is a question the app cannot
answer. And chats are, by deliberate design today, **outside the node/reference machinery**: they
are bespoke YAML sessions at `<project>/chats/<id>.yaml`, excluded from edge extraction
(`REFERENCE_BEARING_KINDS`, `references.py` — *"Chats are absent on purpose… no collector derives
edges from them"*), and their `chat:chat_session` schema type carries only `color`
(`default_schema.py`). Chat-as-a-Node is half-built: the kind is registered, `read_node` /
`save_node` / `delete_node` dispatch it, and the frontend already reads and saves chats through
`/api/nodes/{id}` — but storage, discovery, and references never crossed over. A comment on the
type names the gap: *"ChatSession storage… stays the source of truth until Phase 3b migrates it
onto the Node CRUD path."*

That half-migration is why chats are the thing that has to be special-cased whenever the node model
grows: they are excluded from references, they cannot be a View universe (the Chats pane bypasses
`evaluateView` via `nodeSet()`), and they have no metadata to filter, group, or sort on. The
writer's ask — *offer to reuse an existing chat, and show me the prompts for this entry* — is not
reachable without first making a chat a node like any other.

A third seam, surfaced while scoping: **the commit gets less reliable the longer a chat runs.** The
"emit an EntryPatch shaped like `{…}`" contract lives only in the system prompt rendered at the
first turn; the finalize call (`runFinalizeTurn`, a `chat_id:null` side-call) replays that same
frozen prompt plus the whole transcript and a terse *"finalize as instructed"* cue, trusting the
model to still honour a format described far up an ever-growing context. The deterministic parser
rescues near-misses; it cannot rescue a model that wandered off format.

## Decision

**A node owns its conversations.** A chat becomes a first-class node that carries a `subject`
reference to what it is about; the node it references surfaces its conversations resume-first
through the existing reverse-reference machinery; each conversation kind commits through its own
fresh, self-instructed extraction; and the whole thing is a View, designable like any other list.
Reuse, "the prompts for this entry", and the roleplay-with-a-character conversations you foresee
all fall out of that one move — none is a new subsystem.

### 1. A chat is a first-class node — finish Phase 3b

Chat storage converges onto the generic node path. The bespoke `chats/*.yaml` writer is retired in
favour of the frontmatter node writer (`_write_node_entry_file`); `chat` becomes a real
`NodeFamily`, so it is discovered, indexed, and **edge-bearing** like every other kind, and the
`_collect_chat_*` special-case in the index is deleted. All the invariant logic already in
`save_chat_session` — the preset lock, the append-only journal guard, the per-turn invocation-cost
append, the cache-time stamping — is preserved; only the write primitive changes.

**The conversation lives in frontmatter, not the body** — the established shape for a structured
node (ADR-0021 views carry their spec in frontmatter with an empty body; mutation sets carry their
rows the same way). A chat's `messages` / `journal` / `context_items` / `cache_write_times` are
structured records (each turn carries its own role, usage, and cost), not prose, so they belong in
frontmatter data with an empty Markdown body — which is what the YAML `ChatSession` already is, in
disguise. `cost` is already derived from `ai_invocations` and stays telemetry-owned, off the node.
The exact frontmatter serialization is an implementation choice for the first slice, not fixed here
(ADR-0005: a guessed storage slot acquires authority it never earned).

**No migration.** Pre-1.0, existing chat files are recreated, not migrated — no migration script,
no defensive reads (the standing pre-1.0 rule).

Anton's reason for paying this foundation cost, recorded because it is the load-bearing *why*: a
chat that is a real node stops being the special case that breaks every time a feature touches "all
nodes." Doing only the lighter thing below (a bare back-reference) would buy reuse and leave the
recurring tax in place.

### 2. A node owns its conversations — the `subject` reference

The chat type gains a **`subject` field of type `entity_ref`**, stored in the chat's frontmatter
`metadata`. Once chats are edge-bearing (§1), the index emits the edge with no new traversal, and
the existing reverse-reference index answers *"which chats are about node X?"* the same way the
Backlinks panel already answers it for any node.

`subject` is **kind-neutral**: it can point at a lore entry, a character, or a scene, which is
exactly what makes "chat with the protagonist" (a roleplay conversation whose subject is that
character) and "brainstorm this scene" the *same* surface pointed at a different node, not parallel
features to build.

**`subject` generalizes `target_scene_id`.** A scene-anchored chat's subject is its scene; the
bespoke `target_scene_id` folds into `subject` over time. Because that fold touches the scene-chat
send path, it is **its own reviewable slice**, not part of the §1 convergence.

### 3. Conversation identity is a name plus its seeding prompt — no type facet

A conversation is identified by a **manually assignable name plus the name of the prompt that
seeded it**. There is **no stored "conversation type" facet** — not now, and the intent is never.
"Brainstorm", "chat with this character", and a freeform chat differ by which prompt seeded them,
which is data the chat already carries. New chats are named from their subject (and prompt), ending
the pile of identically-named chats.

### 4. Commit is a per-type, fresh, self-instructed extraction

Each conversation kind is a seed prompt plus an **optional commit capability**, and that capability
is its *own* extraction contract. Commit runs a **fresh, self-instructed pass over the transcript**:
the extraction prompt carries the full format contract every time, so the transcript is pure input
and the structuring no longer depends on an instruction rendered far up a long context. Brainstorm
extracts an EntryPatch (the ADR-0046 loop, unchanged downstream); a roleplay conversation might
extract *"facts learned about this character"*, or nothing. This replaces the `runFinalizeTurn`
replay of the frozen system prompt.

It is **length-independent by construction** and **cache-neutral**: conversation history was never
part of the cached prefix either way, and a smaller fresh extraction prompt is a cheap cache miss on
the system block, not a regression.

### 5. Conversations are surfaced and designed through the view algebra

Because a chat is now a node with real metadata and a `subject` edge, its surfaces are the ones the
app already has:

- **On the subject node** — a resume-first *Conversations* section: the reverse-reference set
  filtered to the chat kind, listing existing threads (resume, context intact) with a **＋ New** menu
  of the prompts applicable to that node, which doubles as *"the prompts associated with this
  entry"*. This is the Backlinks-panel shape (a reverse-index lookup anchored to the current node,
  deliberately outside `evaluateView`), so it ships without waiting on anything.
- **The global Chats pane becomes a real, designable View.** It stops being a `nodeSet()` bypass and
  flows the chat roster through `evaluateView` (which is already kind-generic and knows the chat
  kind) — so the writer can design their own filter / group / sort over chats, because chats finally
  have metadata to key on.

**Per-entry designable views do not need Views 2.0.** `evaluateView`'s universe argument already
accepts an arbitrary node set, so the surface computes *"chats whose subject → this node"* and hands
that set in as the universe; a user's saved spec then filters / groups / sorts *within* it. Only a
spec that **names the anchor inside its own predicates** (relational `references contains $self`)
needs the `$self` binding ADR-0032 Amendment 2 removed — and *"my conversations about this entry, my
way"* does not.

### 6. Caching is a live-session optimization, never a store

Stated so the feature is not mis-sold: the provider cache (system prefix at 1h, journal at 5m) is
best-effort and non-persistent. Resuming a chat after the TTL lapses pays a full cache-write on the
next turn. **The payoff of reuse is continuity — the AI still remembers the thread (journal +
history) — not cheaper tokens on resume.** Prolonged reuse is, if anything, *friendly* to the cache
(the preset lock keeps the 1h prefix byte-stable for the chat's life); the only length-fragility was
the commit, which §4 removes.

### 7. The one rule

> **A chat is a node that knows its subject. The subject shows its conversations, you resume one
> instead of spawning a duplicate, and committing runs a fresh extraction that never depends on how
> long the chat ran — all of it the ordinary node, reference, view, and patch machinery, with chats
> finally inside it.**

## Why / rejected alternatives

**Reuse via an `inputs.entry` index, leaving chats outside the node model.** The cheapest path to
the writer's literal ask: build a rebuildable index over the `inputs.entry` value already on disk and
resume from it, no schema change. **Rejected as the destination** (kept only as a possible throwaway
UX probe): it answers *reuse* while leaving chats a bespoke island, so every later all-nodes feature
re-special-cases them — the exact recurring tax Anton called out. It is also a *second* linkage
parallel to the reference machinery, which is the shape this project systematically refuses.

**A lighter `subject_ref` on `ChatSession` without finishing 3b.** Add a back-reference field to the
YAML model and index it specially, skipping the storage/family convergence. **Rejected:** it is the
`inputs.entry` objection one level up — chats still are not edge-bearing nodes, the Chats pane still
cannot be a real View, and the special-casing persists. Anton's decision was explicit: pay the full
3b cost so the problem stops recurring.

**Keep the finalize-replay commit, just re-inject the format at finalize.** The minimal reliability
fix: leave the mechanism, but re-send the full format block in the finalize turn instead of the terse
cue. **Rejected as the destination** (fine as an interim if §4 slips): it fixes drift but gives no
per-type structure, and the commit contract still is not owned by the commit action — the moment a
second conversation kind wants a different commit, the single frozen shape blocks it.

**Store the conversation in the Markdown body.** Put the transcript in the prose body like a scene.
**Rejected:** turns are structured records (role, usage, cost, journal deltas), not prose; the
frontmatter-payload pattern (ADR-0021 views, mutation sets) is the honest home, and the body stays
empty.

**A stored "conversation type" facet.** Model brainstorm / roleplay / freeform as an explicit type on
the chat. **Rejected** (Anton): the seeding prompt already distinguishes them, and a name plus the
prompt is enough — *"hopefully never"* a separate facet.

**Defer per-entry designable views to Views 2.0.** An earlier framing assumed the per-entry surface
needed the removed `$self`. **Rejected as over-deferral:** caller-scoped universe injection delivers
designable per-entry views today; only anchor-in-spec relational predicates wait for Views 2.0.

## Anti-goals

- **Not a new chat-management subsystem.** It is `NodeList` / `NodeRow`, the view algebra, and the
  backlinks reverse-index, reused. A bespoke chat widget is the smell.
- **Not lore-only.** The surface keys off *"this node has conversations + applicable prompts"*, so
  scenes and characters inherit it unchanged.
- **No pre-1.0 migration.** Existing chat files are recreated, not migrated.
- **Not Views 2.0.** The per-entry surface ships on a caller-scoped universe; no `$self`.
- **No auto-create on click.** The silent spawn is the bug being removed.
- **Don't oversell caching.** Reuse buys continuity, not a warm cache.

## User journey

A writer opens a character's entry. A **Conversations** section lists the threads they have had about
this character, most-recent first, with a **＋ New** menu — *Brainstorm this entry*, *Chat with this
character*, and whatever other prompts apply. They resume last week's brainstorm and the assistant
still has the thread in view; they add a few turns and click **Commit**, and a fresh extraction turns
the conversation into a reviewable patch — reliable whether the chat is five turns or fifty. Later
they open the global **Chats** pane and, because chats now carry real metadata, they *design* the
view: group by subject, filter to this book, sort by last-active. When scenes get the same section, it
is the identical surface pointed at a scene — nothing new was built for it.

## Consequences

- **`chat` joins `NodeFamily` and `REFERENCE_BEARING_KINDS`;** the `_collect_chat_*` index
  special-case is retired. Chat storage moves to the frontmatter node writer.
- **The last bespoke chat endpoints (list / create / delete) converge** onto the node path; the
  roster source updates accordingly (read / save already went through `/api/nodes/{id}`).
- **The chat type gains a `subject` `entity_ref`;** brainstorm launch stamps it, and new chats are
  named from their subject + seeding prompt.
- **`target_scene_id` folds into `subject`** — its own slice, because it touches the scene-chat send
  path.
- **`ChatBodyView`'s commit switches** from the finalize-replay to a per-type extraction contract.
- **The Chats pane flows through `evaluateView`;** the per-entry Conversations panel is a
  backlinks-anchored list.
- **Two pre-existing cache-cost inaccuracies are noted, not fixed here:** the 1h system cache write is
  billed at the 5m multiplier (under-reported), and the "lore" TTL chip is defined but never fed (only
  the `system` slot is stamped). Separate cleanup.

## Slice plan — one lane, disjoint, vertical (reorderable)

- **S1 — 3b convergence.** Chats become real node files: storage + family + index + edge machinery.
  No user-visible change; the foundation.
- **S2 — `subject` ref + backlinks + naming.** Brainstorm launch stamps `subject`; the reverse index
  answers "chats about X"; new chats get subject-derived names.
- **S3 — Conversations surface** on the lore entry (resume-first list + ＋ New menu). Kills the
  duplicate-spawn bug — the original complaint.
- **S4 — Per-type fresh-extraction commit.** Replace the finalize replay.
- **S5 — `subject` generalizes `target_scene_id`.** The scene-chat fold.
- **S6 — Designable chat views.** Global Chats pane through `evaluateView`; per-entry caller-scoped
  view.
- **Later / separate:** the scenes Conversations surface; Views 2.0 anchor-in-spec relational views;
  the two cache-cost inaccuracies.

Binding is the decision, anti-goals, and the one rule; the slice order may change freely, and a
surprise that argues against a binding item amends this ADR before code (the ADR-0048 discipline).

## Deliberately out of scope (deferred, not sketched)

Stated so a later thread does not read silence as *decided*:

- **The frontmatter serialization of the transcript** (how `messages` / `journal` / `context_items`
  are laid out in the node file). The model is fixed — a frontmatter-payload node, empty body; the
  shape is the first slice's to choose (ADR-0005).
- **The scenes Conversations surface.** Same machinery, its own later slice; not designed here.
- **Anchor-in-spec relational views** (a saved view whose predicates name the current node). Waits on
  the `$self` reintroduction deferred to Views 2.0 (ADR-0032 Amendment 2).
- **The two cache-cost inaccuracies.** Real, separate, and not this feature's to fix.
