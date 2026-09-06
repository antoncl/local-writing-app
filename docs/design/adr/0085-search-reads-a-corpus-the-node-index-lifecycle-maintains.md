# ADR-0085: Search reads a corpus the node-index lifecycle maintains; a hit is an anchored range, and replace is a conflict-checked write through the node's own save

- Status: **Proposed** — 2026-09-06, authored by Claude for Anton Lauridsen's review.
- **Issue:** #1605 (search-and-replace + incremental search; both need an index)
- **Relates to:** ADR-0040 (the node index is persisted, incremental, and not SQLite), ADR-0039 (per-field layer overrides; the composite revision), ADR-0045 (scope is the unit of work), ADR-0049 §5 (the owned-here predicate), ADR-0071 (storage-shape changes owe a migration — this one owes none, §8), #1332 (the Search pane is a `NodeList` of `NodeRow`s), `CLAUDE.md` § Project format ("caches and indexes (`.cache/`) are always rebuildable")

> **Verified against `ca77804a` (2026-09-06).** Citations name the symbol first; the line is a convenience and is what rots. A cold-implementer simulation was run against the first draft; its findings are folded into §§2, 4, 5, 6 and the slice scopes.

## Problem

The Search pane finds, and only on an explicit submit. Replace was in the original design and was dropped for effort; as-you-type search was wanted and never built. Both stopped at the same wall, and the code shows why it is one wall, not two.

**1. A query is a full scan.** `ProjectService.search` (`backend/app/services/project/search.py:59`) walks `(root / "scenes").rglob("*.md")` (`search.py:129`) and `(root / "lore").rglob("*.md")` (`search.py:180`), parsing the front matter of each file with `_read_markdown_with_front_matter` (`project_service.py:455`) and regex-matching the body and the metadata on every request. With "Include open TODOs" ticked, `_search_open_todos` (`search.py:81`) reaches `_scan_embedded_todos` (`embedded_todos.py:42`), which rglobs and re-parses the scenes a second time. The cost is files × queries, paid in YAML parses. The pane knows it: `Search.svelte:24–28` explains that search never fires on a keystroke because the endpoint is an un-indexed scan and names #1605 as the prerequisite.

**2. A hit has nothing a replace can hold on to.** `SearchHit` (`backend/app/models/annotations.py:185`) carries `kind`, `file_id` (the node id — `search.py:152`, `:201`), a display `path`, a `line`, and an `excerpt`. No offset, no range, no revision. A replace built on it would have to re-find the text at write time and hope it is the same text; the pane's click handler already ignores `line` (`openSearchHit`, `frontend/src/lib/stores/todoActions.svelte.ts:134`).

**3. The scan sees less than the app knows.** It reads the root layer's `scenes/` and `lore/` folders only. Inherited lore, research notes, plot cards, and prompts are all nodes the node index lists (`NodeIndex.by_id`, `backend/app/services/project/node_index.py:144`), and none of them is searchable. The scan is a second, narrower enumeration of files beside the one the index already keeps — and the pane hard-codes the three kinds it can show (`KIND_ORDER`, `Search.svelte:33`).

**4. The maintenance seam already exists and is guarded.** Every node write passes `_atomic_write` (`project_service.py:409`), which calls `_maintain_index_after_write` (`project_service.py:417`); that routes to `_apply_index_write(paths, structural=...)` (`references.py:462`), and a test forbids a bare `.unlink(` or hand-rolled node write under `services/project/` (`test_node_index_memo.py:554`). Deletes and renames go through the same method with `structural=True`. A search structure hooked anywhere else would be a convention; hooked here it is an encapsulation, and the docstring at `project_service.py:418–438` makes exactly that argument for the node index.

So the prerequisite the issue names is not "a search engine". It is: stop re-reading files per query, give a hit a stable anchor, and let the write seam that already maintains one cache maintain a second.

## Intent

A writer types in the Search pane and the hits keep up with the typing. A hit names a node, a field, and a character range that is still valid when the writer acts on it. Replace writes through the same intentful saves the editor uses, refuses when the file under a hit has changed since the search, and never touches a file the open project does not own. The files stay the truth; the structure that makes this fast is rebuildable from them at any time and lives in memory.

## Anti-goals (what this must not do)

- **Not a database.** No SQLite, no FTS extension, no inverted index. ADR-0040 decided that for the node index and the reasons hold here: a writer's project is megabytes of prose, and a substring scan over strings already in memory is faster than the round trip to any engine.
- **Not a second enumeration of files.** The corpus is built from the node index's roster (`NodeIndex.by_id`), never from its own `rglob`. A guard test bans `rglob` from `search.py` the way `test_node_index_memo.py:554` bans `.unlink(`.
- **Not a second lifecycle.** The corpus has no invalidation triggers of its own. It is dropped where the node index is dropped and patched where the node index is patched (§1), so the eleven-odd callers of `node_index_gate.invalidate()` cover it without knowing it exists.
- **Not held by the frontend.** The frontend sends a query and receives hits. It never holds file contents or computes matches; it never writes a file.
- **Not a new write path.** Replace writes through the save primitive the kind's own PUT already uses (§4). A kind with no such primitive is not replaceable; nothing hand-rolls a file write to make it so.
- **Not regular expressions, fuzzy matching, or ranking.** Queries stay literal substrings, as today (`re.escape(query)`, `search.py:68`). Match-case and whole-word toggles are the only additions. A regex or relevance mode is a different feature with its own decision; this ADR does not sketch it.
- **Not a jump-to-offset in the editor.** Clicking a hit opens the node, as today. Positioning the TipTap cursor at a markdown offset needs a markdown-offset ↔ ProseMirror-position seam that does not exist (`ProseBodyView.svelte` has only `highlightEmbeddedTodo`, `:392`, which scrolls to a DOM attribute). That seam is its own decision. Nothing here reserves a shape for it.
- **Not replace into metadata, titles, inherited nodes, or chats.** Replace edits prose bodies of nodes the open project owns. Metadata hits and inherited-layer hits are find-only; chats are not in the corpus at all (§1).
- **Not a snapshot in `.cache/`.** The corpus is memory-only (§1). This is a measured bet, not a deferral; §Acceptance names the measurement.

## Decision

### 1 — The corpus is a memory-only cache that rides the node index's lifecycle

A `SearchCorpus` holds, per node id in the resolved index's winners view (`NodeIndex.by_id`): the node's `kind`, `entry_type`, `title`, `path`, source layer id, whether the open project owns it, the **body** as one string (the text after the front-matter split, line endings normalised to `\n`), the **metadata text** as today's search derives it (`_normalise_metadata` then `_resolve_reference_titles`, `search.py:135–137`, so a reference field matches on the referenced title), and the node's **save revision** — the value that kind's save primitive will compare a `base_revision` against (§4), obtained by calling the same helper the save calls, never re-derived.

**What is in it.** Nodes whose file is Markdown with front matter and whose body is prose. That is a predicate plus one named exclusion, not a list of kinds: **chats are excluded**, because a chat's body is a YAML-serialised transcript (`_write_chat_session`, `chats.py:64`; read back with `yaml.safe_load(body)`, `chats.py:192`) — a substring match inside it would match structure, not prose, and a character-offset replace into it could leave a transcript that no longer parses. Inherited nodes are in the corpus because they are in `by_id`; the layer id rides along so §4 can refuse to write them.

**How it is built.** Lazily, on the first query after it is empty, by reading each listed node's file once through `_read_markdown_with_front_matter`. It keeps a `path → id` reverse map, because a delete reaches the maintenance seam after the file is gone (`_delete_node_files` unlinks first, then calls `_apply_index_write`, `references.py:773–776`) and the corpus must drop by path without re-reading.

**How it follows the index's lifecycle.** The corpus is a module-level memo beside the gate, with two entry points, and both are called from inside the seams the index already owns — not from their callers:
- `NodeIndexGate.invalidate()` (`node_index_gate.py:207`) drops the corpus. Every existing invalidate site — project open, `project.yaml` / `metadata.schema.yaml` writes, override writes, migrations, promotion — is covered by that one line.
- `_apply_index_write(paths, structural=...)` (`references.py:462`) patches the corpus for exactly the paths it is given, unconditionally: re-read a written path, drop a deleted one, re-key a renamed one. The node index's own change-gate may decide a prose-only save changes nothing *it* holds and publish nothing; the corpus always re-reads, because prose is precisely what it holds. The call sits in `_apply_index_write` itself, so the guard test that keeps every writer on that seam protects the corpus too.

**Why memory-only.** The node index needed a `.cache/node-index.json` snapshot (ADR-0040; `node_index_snapshot.py:144`) because its cold build parses YAML and extracts reference edges across the whole layer chain. The corpus's cold build is the same file read the index build already performs, with the body kept instead of discarded; it adds no parse the app is not already paying at open. Persisting it would add a second manifest to keep coherent for no read it avoids. If measurement (§Acceptance 3) contradicts this, the decision is reopened by amendment; this ADR does not pre-decide what that amendment would build.

**Why a sibling memo, not fields on `ResolvedIndex`.** `ResolvedIndex` (`node_index_gate.py:83`) is frozen, published without a lock, and snapshotted to disk. Bodies do not belong in it: they would be written to `.cache/node-index.json` on every flush and would multiply its size for readers that never need them. The corpus shares the gate's *events*, not its *object*.

### 2 — A hit is an anchored range, and it opens by kind

`SearchHit` gains `field: "body" | "metadata"`, `start` and `end` (character offsets into the corpus body string, half-open, `end - start` equal to the match length), `revision` (the corpus's save revision for the node at query time), and `owned: bool`. `file_id` keeps carrying the node id under its existing name; `path`, `line`, and `excerpt` stay as the display fields they are. Metadata hits carry `start = end = 0` and are marked by `field`; they are not replaceable (§4).

`kind` widens from `"manuscript" | "lore" | "project"` to the node's kind as the index stamps it. Two consumers must follow, and slice 1 owns both: `openSearchHit` (`todoActions.svelte.ts:134`) today branches lore-else-scene and would send a prompt or plot hit to the scene opener; it switches to `editorPanes.openNodeOfKind(nodeId, kind)` (`editorPanes.svelte.ts:853`), the cross-kind opener the rest of the app uses. The pane's hard-coded `KIND_ORDER` / `KIND_LABEL` (`Search.svelte:33–34`) becomes a lookup over the kinds the hits actually carry, in the order the app lists kinds elsewhere, with unknown kinds shown rather than filtered out. TODO hits keep `kind: "project"` and their `todo_id`; `_search_open_todos` reads scene bodies from the corpus instead of the second rglob and is otherwise unchanged.

### 3 — Search is served from the corpus, and the pane searches as the writer types

`/api/search` (`routers/entries.py:297`) computes hits from the corpus. `SearchRequest` (`annotations.py:178`) gains `match_case: bool = False` and `whole_word: bool = False`; `include_scenes` / `include_lore` become a `kinds: list[str] | None` filter (None = all), and `include_open_todos` stays.

The pane fires the query on input, debounced, and drops any response that arrives for a superseded query (the monotonic-token pattern `ChatBodyView.fetchChatEstimate` already uses). The "Find" button goes; the search input is the only trigger. Hits render as `NodeRow`s in a `NodeList` grouped by kind, as #1332 settled. Domain state — query, options, hits, in-flight token — moves to a rune controller under `lib/stores/`, not the component (`CLAUDE.md` § Where do I stop splitting).

### 4 — Replace is a conflict-checked write through the node's own save

`POST /api/search/replace` takes `{ replacement: str, hits: [{ file_id, field, start, end, revision }] }` and returns one outcome per hit — `replaced`, `stale`, or `not_replaceable` — plus the node's new revision where a write happened.

Per node, in order:

1. **Refuse what is not ours to change.** A hit is `not_replaceable` when its node is not owned by the open project (`_node_is_owned_here`, `library_tenant.py:35` — the predicate the Library tenants already share, ADR-0049 §5), when its `field` is not `"body"`, or when its kind has no entry in the replace dispatch (below). Inherited lore is edited through the override/fork paths `save_lore_entry` implements (`lore.py:184`); a search-and-replace must not become a third way to write an ancestor's file. Titles and metadata are edited on the node; a reference field's hit matched a *resolved title* that is not stored text at all.

2. **Refuse what moved.** The node's current save revision — the same value the kind's save primitive checks — must equal the hit's, and the corpus body's `[start:end]` must equal the text the query matched. Either mismatch makes every hit on that node `stale` and writes nothing to it. For a scene that value is `_revision(path)` (`project_service.py:642`, a sha256 of the file), compared in `save_scene` (`manuscript.py:546`); for a lore or prompt entry it is `_composite_revision([path, *override_paths])` (`overrides.py:378`), which folds in every override file in the chain and reduces to `_revision` when there are none. The corpus stores whichever the kind's save checks (§1), so an entry with per-field overrides is not permanently stale, and a metadata edit that lands between search and replace makes the body hits stale too — correctly, since the file changed.

3. **Write once per node, through its own save.** All of a node's body hits are applied from the highest offset down. There is no body-only save: the save request models require the whole node (`SaveSceneRequest`, `SaveLoreEntryRequest`, …, `models/entries.py`), so the endpoint reads the node through the kind's read primitive, substitutes the body, and submits it to the kind's save with `base_revision` set to the revision it verified in step 2. The read-modify-write window is the same one every editor save has, and the same revision check guards it. The dispatch is one table in the search service mirroring `_SAVE_NODE_DISPATCH` (`node_ops.py:45`) — manuscript → `save_scene`, lore → `save_lore_entry`, prompt → `save_prompt_entry` (`prompts.py:399`), research → `save_research_note` (`research.py:285`) — plus the plot family, whose primitives are per entry type (`save_card`, `save_plotline`, `save_character_arc`, `save_plot_template`, `plot.py`) and which `_SAVE_NODE_DISPATCH` does not cover. A kind absent from the table (assistant, view, tag, chat) is `not_replaceable`. Revision, node index, and corpus maintenance then happen exactly as for any save; nothing writes a file directly.

The endpoint is the whole mechanism; "Replace" (one hit) and "Replace all" (all current hits) are the pane sending one or many. After a replace the pane re-runs the query and shows what remains.

### 5 — The open editor

A node open in an editor with unsaved edits would lose them to a replace or make the replace stale. `editorPanes` keeps `dirty` as the single source of truth for autosave (`editorPanes.svelte.ts` header, lines 13–17); the pane marks hits on dirty-open nodes "unsaved edits in the editor — save first", excludes them from Replace all, and does not send them. The backend revision check is the backstop, not the message.

A node open and clean is reconciled from the server after its replace lands. One generic entry point on `editorPanes` does this by node id; `reconcileSceneFromServer` (already called from `todoActions.svelte.ts:93`, `:128` after an embedded-TODO write) becomes its scene implementation, the lore pane path becomes its lore implementation, and a kind that can be replaced (§4's table) but has no reconcile path gains one in slice 3. The Search pane calls the one entry point; it never knows per-kind reload functions exist.

### 6 — Layers

The corpus is the chain the index resolved: innermost layer wins per id, as `by_id` already decides. A hit shows its layer where the pane shows layers elsewhere. Find sees the chain; replace writes the root layer only (§4 rule 1, via `_node_is_owned_here`).

### 7 — What this settles from #1605's scope list

- "A rebuildable search index over scene + lore content (in `.cache/`)": rebuildable, yes; over every prose-bodied node the index lists, not two folders; in memory, not `.cache/` (§1 says why and §Acceptance 3 says what would reopen it).
- "Incremental search-as-you-type on top of it (retire the explicit Find button then)": §3, as written.
- "Search-and-replace: preview hits, replace-one / replace-all, atomic writes through intentful endpoints": §4, with the ownership, revision, and dispatch rules the issue did not spell out.

### 8 — No migration is owed

Nothing on disk changes shape. The corpus is memory; `SearchHit` and `SearchRequest` are API models, not stored documents. ADR-0071's ladder is not engaged.

## User journey (the definition of done)

The writer renames a city. She opens Search and types "Aetheria"; by the third letter the pane is listing hits under Scenes, Lore, Plot, and Prompts, each row a node title with the matching line and the match marked. Two hits are in lore inherited from the series project and show that layer. She clicks a plot-card hit and the card opens. She types "Aetherion" in the replace field and each excerpt shows what it would become. She presses Replace all. Twelve hits across seven owned nodes are written; the scene she has open, unedited, redraws with the new name; the two inherited hits are still listed, marked as not replaceable here; the one scene she had been editing without saving is listed as "unsaved edits — save first" and untouched. She saves that scene, the search re-runs on its own, one hit remains, she presses Replace on it, and the list is empty except for the two inherited lore entries.

## Scope

**In:** `SearchCorpus`, its build from `by_id` with the chat exclusion, its reverse map, and its two entry points called from `NodeIndexGate.invalidate()` and `_apply_index_write`; `/api/search` served from it with `match_case`, `whole_word`, and `kinds`; the anchored `SearchHit` with the widened `kind`; `openSearchHit` on `openNodeOfKind` and the pane's kind grouping made data-driven; as-you-type in the pane with a rune controller; `POST /api/search/replace` with the ownership, revision, and dispatch rules; the pane's replace field, per-hit and replace-all actions, and the dirty-editor and inherited-hit markings; the generic reconcile entry point and the per-kind implementations it needs; the `rglob` guard test on `search.py`.

**Out:** regex or fuzzy search and any ranking; jumping the editor cursor to a hit; replacing in metadata, titles, inherited nodes, or chats; searching chats; a `.cache/` snapshot of the corpus; changes to the TODO index or its pane; any change to how nodes are stored.

## Alternatives considered

- **SQLite with FTS5 in `.cache/`.** Real full-text search with ranking and prefix queries. Rejected: ADR-0040 already declined SQLite for the node index and the reasons hold — a second storage engine, a binary file to keep coherent with the files, and a dependency, for a corpus small enough that a substring scan in memory answers a keystroke. Ranking is not what a writer doing a rename wants; she wants every occurrence.
- **Bodies inside `ResolvedIndex`, snapshotted with the node index.** One memo instead of two. Rejected: the snapshot would carry all prose on every flush, and every existing reader of `ResolvedIndex` would hold bodies it never reads. Two memos with one set of events keeps the index small and the coupling where it belongs.
- **A corpus with its own invalidation.** Hooks at project open and at each writer. Rejected: the node index already found that per-writer hooks are a convention that decays; there are eleven-odd `invalidate()` call sites today, and a corpus that must be told about each is a corpus that will be stale at the twelfth.
- **Frontend-side search over documents already loaded.** No backend change. Rejected: the frontend holds only the open documents; a project-wide find needs the files, and the frontend never reads or writes them (`CLAUDE.md` § What this is).
- **Replace by re-finding the text at write time (no anchor, no revision).** Simpler hit model. Rejected: it writes the *current* first match, not the one the writer saw, and it has no way to say "this file changed since you searched". The anchor and revision are what make replace safe to offer.
- **A body-only save primitive for replace.** Would avoid the read-modify-write. Rejected: it is a second write path for the same node, outside the request models the editor validates through; the revision check already closes the window the read-modify-write opens.
- **Allowing replace into inherited nodes via the override path.** Tempting for a series-wide rename. Rejected here: it turns a text operation into a layer decision (override or fork?) the writer did not make. The lore save paths own that decision; a writer who wants it opens the entry.
- **Including chats in the corpus for find only.** Rejected: the body is a serialised transcript, so a match reports a line inside YAML structure the writer cannot act on from the pane, and the kind would need a permanent "find-only" exception. Chats have their own pane and their own search surface if one is ever wanted.

## Consequences

- Memory holds the project's prose once more than today (the corpus) while a project is open. For a novel that is megabytes; the acceptance check measures it rather than assumes it.
- A prose-only save now costs one extra file read (the corpus re-read) that the node index's change-gate previously skipped. It is the file the save just wrote, warm in the OS cache.
- `_apply_index_write` and `NodeIndexGate.invalidate()` each gain one call. Every existing caller of either is covered without change; the guard test that protects the choke point protects the corpus for free.
- The pane loses the Find button and gains a replace field; its domain state moves into a controller, and its kind grouping stops being a three-entry constant — both things #1332 asked of it and the modernization left undone.
- `SearchHit.kind` widening changes `openSearchHit`; slice 1 carries that change so no hit ever opens the wrong pane.
- `editorPanes` gains one generic reconcile-by-id entry point in slice 3, which is also where any future "another writer changed this file" surface would attach. This ADR does not design that surface.

## Rollout (slices)

**Slice 1 — the corpus behind the existing find.** `SearchCorpus` with the chat exclusion, the reverse map, and its two entry points wired into `NodeIndexGate.invalidate()` and `_apply_index_write`; `/api/search` served from it; `SearchHit` gains `field`, `start`, `end`, `revision`, `owned` and the widened `kind`; `openSearchHit` moves to `openNodeOfKind`; the pane's kind grouping becomes data-driven; `_search_open_todos` reads scenes from the corpus; the `rglob` guard test.
*Not:* the Find button, debounce, options, or replace; no `.cache/` file; no reconcile work.
*Done when:* the pane's Find returns the same scene and lore hits as before on a fixture project plus research, plot, prompt, and inherited-lore hits under their own groups, and clicking each opens the right node; saving, deleting, and renaming a node updates the next query without a project reopen; the counting test asserts one file read per node per cold build; the slice-1 PR records the cold-build time and corpus size on Anton's largest project.

**Slice 2 — as-you-type.** Debounced query with stale-response dropping in a `lib/stores/` controller; Find button removed; `match_case`, `whole_word`, and the `kinds` filter.
*Not:* replace; regex; cursor positioning.
*Done when:* typing in the pane updates hits without a submit, a fast second keystroke never shows the first keystroke's hits, and the toggles change the hit set.

**Slice 3 — replace.** `POST /api/search/replace` with §4's three rules and dispatch table; the replace field, per-hit Replace, Replace all; inherited, metadata, and undispatched hits marked not replaceable; dirty-open nodes marked and skipped; the generic reconcile entry point with implementations for the dispatched kinds.
*Not:* replace into metadata, inherited nodes, or chats; any write outside the kind's save primitive; a body-only save.
*Done when:* the user journey above runs end to end in the browser; a test proves a node edited between search and replace yields `stale` and an unchanged file; a test proves an overridden lore entry with no intervening edit is *not* stale (the composite revision matches).

## Acceptance

1. `search.py` contains no `rglob`; a guard test fails if one appears.
2. A cold corpus build reads each node's file once (a counting test on `_read_markdown_with_front_matter`), and chats are not read.
3. Measured on Anton's largest live project at implementation: cold build time and corpus memory are recorded in the slice-1 PR. If cold build exceeds what a writer notices at open (the PR states the number and the judgement), §1's memory-only decision is reopened by amendment before slice 2.
4. Save, delete, rename, a schema or override write, and a promotion each leave the next query correct, with tests per path through `_apply_index_write` and the gate's invalidate — including a delete, which reaches the seam after the file is gone.
5. A replace with a stale revision writes nothing and reports `stale`; a replace on an inherited, metadata, or undispatched-kind hit reports `not_replaceable`; a replace on an owned body hit goes through that kind's save primitive (asserted by spying the primitive, not the file); an overridden lore entry's revision matches its save's check.
6. Every widened kind that can appear in a hit opens through `openNodeOfKind` (a table test over the corpus's kinds).
7. The Search pane holds no file content and calls no write endpoint other than `/api/search/replace`.
8. The journey in §User journey is performed in the browser and its steps recorded in the slice-3 PR.

## To verify / build at implementation

- The kinds the index lists whose files are Markdown with front matter, beyond chat: confirm assistants, views, and tags parse under `_read_markdown_with_front_matter` and decide per kind whether they are in the corpus for find (they are never replaceable — §4's table). The ADR's predicate admits them; the slice-1 PR states the outcome.
- The plot family's read primitives, to pair with the four save primitives in §4's dispatch.
- `_search_open_todos`: whether the embedded-TODO scan needs anything from front matter that the corpus does not hold, or only the body it does.
- How the lore pane reconciles after a server write today (`editorPaneAncestry.ts`), so the generic entry point in §5 wraps it rather than duplicating it.
- Whether `openNodeOfKind` needs the entry type as well as the kind for plot nodes; if so, `SearchHit` carries `entry_type` from the corpus.
