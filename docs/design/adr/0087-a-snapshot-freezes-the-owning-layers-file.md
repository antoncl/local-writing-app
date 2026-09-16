# ADR-0087: A snapshot freezes the owning layer's file, so snapshots generalize to any authored node — restore is an edit that inheritance re-folds, and the witness stays scene-only

- Status: **Proposed** — 2026-09-16 (authored by Claude; awaiting Anton's review). Answers the deferred non-goal of ADR-0043. This is the **model** ADR; the combined-scrubber **surface** is a companion ADR (ADR-0088), as ADR-0044 followed ADR-0043.
- **Feature:** node-scoped snapshots — generalize scene snapshots (#401 / ADR-0043) to lore, tags/motifs, research, prompts, and plot nodes.
- **Relates to:** ADR-0043 (scene snapshots are witnesses — this **amends its "other node kinds" non-goal by reference**), ADR-0044 (the snapshot-strip surface; the companion surface ADR-0088 will **amend** it), ADR-0013 (the in-fiction/mutation scrubber this surface unifies with), ADR-0039/0040/0042 (layer composition, the node index, the inherited-edit gesture — the question 0043 deferred, now answerable), ADR-0082 (tags are a node kind — why a motif qualifies), ADR-0071 (migration-at-restore, already document-generic), ADR-0085 (the node-index write seam restore rides).
- **Surface evidence (feeds ADR-0088, not normative here):** [`../mockups/0087-rotary-scrubber.html`](../mockups/0087-rotary-scrubber.html) — an interactive prototype on the real token layer, iterated with Anton over one session (the mode gadget, the two-timeline track, the diff and the per-layer caption were *tried*, not sketched). A single self-contained file with fixture data, no build step; open it in a browser.

> **Verified against `e05b2d99` (2026-09-16).** Citations name the symbol first; the line is a convenience and is what rots.

## Problem

Snapshots — named, restorable photographs of a document plus a *witness* of the lore-world that gave its prose meaning — exist for scenes only. ADR-0043 shipped them "scenes-only v1" and listed the rest as an explicit non-goal:

> **Snapshots of lore entries or other node kinds.** Out of v1 scope; the layer-composition question above must be answered first. (`0043` Non-goals)

Two things have changed. First, the layer-composition question ADR-0043 punted now has an answer (ADR-0039/0040/0042 landed, and the model below settles it). Second, lore entries — and, since ADR-0082, **tags used as motifs/themes** — are exactly the long-lived, hand-curated canon a writer most wants to revert, and today they have no version history at all.

The hard part is already built. The persistence engine — a two-file store (a byte-for-byte `.md` copy plus a `.yaml` sidecar), retention/thinning, pin/describe/delete, byte-exact restore, and migration-on-restore — is already kind-neutral: every internal method takes `(root, node_id, path)` and copies *whatever* file it is handed (`_capture`, `_snapshots_dir` in `backend/app/services/project/scene_snapshots.py:280, 142`). Only the public wrappers inject the literal `"manuscript"` kind (`_snapshot_source_id`, `capture_snapshot`, `restore_snapshot`, `finalize_scene` — `scene_snapshots.py:268, 276, 415, 482`). What is genuinely scene-locked is (a) that literal, (b) the store's *root*, (c) restore's manuscript-only post-write healers, (d) the `Scene` response contracts, and (e) the **witness**, whose meaning rests on manuscript position and mutation intervals and evaporates off the manuscript.

So the question is not "how do we build snapshots for lore" — it is "what does a snapshot of a *layered* node freeze, where does it live, and what does restoring it mean." This ADR answers those; the on-card surface is ADR-0088's.

## Intent

**A snapshot is a photograph of one file — the single file you author at one layer — so restoring it is nothing more than an edit at that layer, and downstream inheritance re-folds on its own.** The version store scenes already use therefore generalizes to any authored node with a kind parameter and node-scoped addressing; the drift *witness*, which is manuscript-semantic, stays scene-only. What stays: the scene witness/drift model of ADR-0043, unchanged. What changes: snapshots become available to every authored-canon kind, and the store moves to travel with the file it photographs.

## Anti-goals (what this must not do)

- **Not a witness for non-scene kinds.** The witness resolves "the world that gave this prose its meaning" from manuscript ordering + mutation intervals (`build_witness`, `snapshot_witness.py:120`); `effective_state` returns `{}` for a node with no manuscript position. A lore or tag snapshot carries **no** witness and shows **no** drift panel — it is a plain restore point (version + diff). Forcing a witness onto them would be inventing meaning that isn't there.
- **Not a snapshot of the resolved fold.** A snapshot freezes the *single authored file at one layer* (a base file, or an override delta), never the composed cross-layer value. Freezing the fold would bake one book's overrides into a series photograph and make "restore" ambiguous. The unit is the file you edited.
- **Not undo.** Snapshots are sparse, named restore points a writer curates; they are not the fine-grained command-pattern undo (ADR-0050, a separate settled concern). Restore captures-first and is itself an edit, not a rewind of the edit log.
- **Not a storage root that orphans on move.** Snapshots co-locate with their file's own project folder and are keyed by the entity's *stable* canonical id — never keyed by a layer-id or an override's salted id (both non-persistable path hashes), never pinned to whichever project happened to be open at capture.
- **Not a config/surface feature in v1.** `assistant`, `project`, and `view` nodes are deferred (see Scope) — the engine can photograph them, but the writer-facing surface isn't built here.

## Decision

### 1 — A snapshot is node-scoped; the store engine is already kind-generic, so only the kind and the addressing change

The store's internals are already `(root, node_id, path)` and copy bytes blindly (`_capture` byte-copies the file at the resolved path; restore byte-writes it back — `scene_snapshots.py:280, 400`). Generalizing means: take the node's real `kind` from its `NodeIndexEntry` (`node_index.py:25`) instead of the literal `"manuscript"` at the four public entry points, and address the lifecycle by the entity id + a layer scope (§3/§3b) rather than by a scene id under `/api/scenes/{id}`. Every in-scope authored file is one `.md` file (`---\nfront matter\n---\n\nbody`), so a byte photograph captures **the whole authored file at that layer** — the base file with body + all metadata inside it (including the body-less kinds, whose payload is entirely front matter), or the override delta. `revision = sha256(file)` (`project_service.py:647`) is already uniform, so the concurrency token a snapshot pins needs no per-kind logic.

### 2 — A snapshot freezes the owning layer's file; restoring it is an edit at that layer, and inheritance re-folds downstream

You never author the composed entry — you author *one layer's file*, chosen with the "Editing at" selector (`LayerAuthoringBar.svelte`). A snapshot copies that file's bytes; restore writes those bytes back to that same file, which is structurally what a normal save at that layer already does (`save_lore_entry` → `_save_owned_lore_entry` for an owning-layer file, or `_save_lore_override` for a nearer-layer override — `lore.py:237, 241`). The composed view recomposes through the ordinary inheritance path; the snapshot machinery never models layers. This is what dissolves ADR-0043's "layer-composition question": there is no composition for snapshots to understand.

One honest consequence, surfaced rather than hidden: restoring a *series* base whose fields a *book* overrides will not move the overridden fields — the nearer layer still wins, exactly as a normal series edit would behave. The card names the effect so a correct restore never reads as a no-op (ADR-0088).

### 3 — The store co-locates under the owning layer's project folder, keyed by the entity's canonical id

A snapshot lives at **`<owning-layer-project-folder>/snapshots/<entity-canonical-id>/`**. The **folder** separates layers (a base file's history sits in the series project; a book override's sits in the book project); the **id** is the entity's stable front-matter id (a base file's own id, or an override's `target` — `overrides.py:263`), never the file's salted own id. This is a deliberate change from today's root, which is the *open* project (`_snapshots_dir(root=_require_project(), …)`, `scene_snapshots.py:142, 276`). The open-project root is wrong the moment a node can be authored above the open project: a series character edited from book A would drop its history under book A's `snapshots/`, scattering it across whichever book was open and failing the store's own invariants — "a photograph co-located with its file" and "a node and its snapshots are one unit of deletion/move" (`scene_snapshots.py:8, 615`).

Two keyings are rejected in favor of the owning-layer *folder* + the *entity* id:
- **Not keyed by a path hash.** Layer-ids are `sha256(resolved-folder-path)[:16]` and are documented as never persisted — "a path-hash id survives neither a moved project folder nor a re-resolved symlink" (`layers.py:103`); an override's own id embeds that same layer-id hash (`_override_id`, `overrides.py:84`). Keying a snapshot directory by either orphans it on any project move. The layer's *folder* gives the same (layer, entity) separation while staying move-stable, because the folder **is** the layer.
- **Not the single open-project root with a kind parameter.** It preserves the detach-on-open bug above.

For a scene the owning layer **is** the open project and the entity id **is** the scene id, so `<owning-layer-folder>/snapshots/<entity-id>/` is byte-identical to today's `<project>/snapshots/<id>/` — existing scene snapshots are already in the right place, and nothing is migrated.

Because ancestor layers now hold `snapshots/` directories for the first time, the ADR-0043 invariant "`snapshots/` is excluded from the node index, once" must now apply **at every layer's `snapshots/`** — the index collector, ADR-0040's staleness manifest, and the ADR-0085 `SearchCorpus` (built off `NodeIndex.by_id`) all skip it — or an ancestor's byte-copies (which carry the live entity's id) collide as duplicate ids, every capture invalidates the index, and snapshot bodies leak into search. The existing duplicate-id / staleness-manifest guard test is repeated at an ancestor layer.

### 3b — The one authored file that is not an index node: an override, addressed by (entity id + layer)

An override delta is deliberately **not** an index node — it never enters `by_id` (`overrides.py:20`; ADR-0071 §3). So it cannot be reached by `/api/nodes/{override-id}` and has no `NodeIndexEntry` of its own. It participates by the same coordinates the authoring-layer save already uses: **the entity's canonical id (`target`) + the authoring layer**. Its snapshot's **kind** is the entity's kind, read from the base node's `NodeIndexEntry` (the entity is always an index node even when an override refines it at a nearer layer). Capture triggers on the `_save_lore_override` / `_save_prompt_override` path, not only the owned-save path. Restore writes the override delta back and returns the **re-folded composite** the open project resolves (a `LoreEntry`, not a bare delta), via the §4 reconciliation. This is the single in-scope file that is addressed by entity+layer rather than by its own node route.

### 4 — Restore is: migrate-if-behind → byte-write → the shared structural index-write seam → a small per-kind healer

Restore preserves the ADR-0071 §7 / ADR-0043 branch first: **byte-exact when the sidecar `schema_version == CURRENT`, else `migrate_document` over the one body** before the write (`scene_snapshots.py:426-440`). This is inherited by *every* in-scope kind, not scene-only. Then, because a byte-copy restore bypasses the text writer, it must re-enter the shared write seam explicitly as **structural** — `_apply_index_write((path,), structural=True)` (`references.py:462`), which the scene restore already does (`scene_snapshots.py:451`). The structural write re-derives the index signature and forward-reference edges a byte copy would skip, and rebuilds the memo cold whenever the chain carries overrides or redirect fan-in (`references.py:559`), so the override re-fold and the composite-revision recompute happen with no extra call.

On top of that shared seam, each kind replays only its **out-of-index** healers — a small, named per-kind restore adapter:

- **scene:** structure-title sync + todo-anchor prune (`_update_scene_title_in_structure`, `_remove_missing_scene_todo_anchors` — `scene_snapshots.py:457`). Unchanged.
- **research:** structure-title sync (`_update_research_title_in_structure`, `research.py:399`) — the exact analogue.
- **plot:** re-run the card/beat link healer (`_normalise_card_metadata`, `plot.py:362`) so the healed form persists rather than waiting for the next read.
- **lore / prompt / tag:** nothing beyond the structural write. Their reconciliation is entirely index-build-time — the override fold, and the `merged_into` redirect resolution via `canonical_id` (`tag_nodes.py:195`). In particular a tag restore must **not** replay the eager `_rewrite_references_from_to` sweep (`tag_nodes.py:256`): carriers already resolve through `canonical_id`, so replaying it is neither needed nor part of a byte restore.

The general rule for any future kind: migrate-if-behind, byte-write, structural index write, then replay only that kind's out-of-index healers (structure-title, todo-anchor, or link-heal).

### 5 — The witness stays scene-only

Non-scene snapshots omit the witness entirely and render no drift panel; the compare surface for them is the content/field diff alone (which already moved client-side, #583). This lifts ADR-0043's "other node kinds" non-goal *by reference* while leaving its scene-witness model (`snapshot_witness.py`) untouched. If a non-scene kind ever earns a meaningful "world that changed underneath" story, it can add its own witness adapter later; nothing here forecloses it.

### 6 — The card unifies the two time axes under one foot dock; the full surface is a companion ADR

A node can carry two *timelines* — for a lore entry, **mutations** (story time: the entity's canon as rewritten through the manuscript by in-scene ⤳ markers, `MutationScrubber.svelte`; the axis of ADR-0013) and **snapshots** (edit time: §1–4) — plus one *scope*, the **layer** ("Editing at"). The load-bearing decision here: the two timelines share **one full-width foot dock** (the slot where the snapshot strip docks for scenes) with a **mode control** selecting which the track travels; the **layer stays a separate scope** the snapshot track reads from; and a node with a single timeline (research/prompt/tag/motif/plot have snapshots but no mutations) shows that track alone.

The *surface itself* is **deliberately not decided here** — the specific mode gadget, the two timelines' visual languages, whether the mutation scrubber moves from its current Details/rail home (it was relocated there by #1249, which overtook ADR-0042 §1 / ADR-0044 §A's "foot-docked" description) down to the shared dock, and the combined key model reconciled with ADR-0044's settled `←→`/`A/S/B`/`Esc` bindings — all belong to a **companion surface ADR (ADR-0088)**, for which the [mockup](../mockups/0087-rotary-scrubber.html) is the evidence, mirroring how ADR-0044 followed ADR-0043. That companion ADR **amends ADR-0044**, realizing its explicit "if both axes ever share a card" case (ADR-0044 §A named three-axes-on-a-lore-card as where that legibility problem "actually bites").

## User journey (the definition of done — engine)

Anton opens the series character **Seraphine Vale** while the book *The Marrowgate* is open. "Editing at" reads **Series**. He rewrites her ledger and saves; a snapshot is captured under the **series** project's `snapshots/`, keyed by her entity id — not the book's. A day later he clicks the earlier restore point, previews the diff, and restores: a safety snapshot is captured first, the series base file is rewritten, and *The Marrowgate*'s composed view of Seraphine re-folds automatically. He switches "Editing at" to **Book**; the track now shows the book override's separate, shorter history (addressed by her entity id at the book layer, §3b). Separately he opens a **motif** tag and reverts an over-eager edit; restore writes the tag file and the index rebuilds `canonical_id`/redirects — no reference sweep replayed, no witness, no drift panel.

## Scope

**In (authored-canon kinds):** `manuscript` (scenes — today, unchanged), `lore`, `research`, `prompt`, `plot` (cards/plotlines/arcs/templates), and `tag` (including motif/theme tags per ADR-0082).

**Deferred (engine-capable, surface not built in v1):** `assistant`, `project`, `view`. The store can photograph them (they are one `.md` file each), so this is a **surface deferral, not a principled "never":** they are not the motivating canon, `assistant`/`project` are configuration-shaped, and a `view` (ADR-0021, an authored node) has an autosaved single-owner surface where restore-point value is lower — but if a writer wants view/project history later, the engine already supports it and only the card surface is owed.

## Alternatives considered

- **Snapshot the resolved fold rather than the owning file.** Rejected: lossy (bakes one book's overrides into a series photograph), makes "restore" ambiguous, and couples the snapshot engine to inheritance — the opposite of §2's insight.
- **Keep the store at the open-project root, thread only a kind parameter.** Rejected: scatters an ancestor file's history across whichever book was open and breaks "snapshots move/delete with the file" (§3).
- **Key the store path by layer-id or the override's own salted id.** Rejected: both are non-persistable path hashes; they orphan every snapshot on a project move (`layers.py:103`, `overrides.py:84`).
- **Extend the witness to all kinds.** Deferred, not rejected: off the manuscript it has no referent. Non-scene snapshots ship witness-free; a kind can add its own witness adapter later.
- **One shared foot dock (mode-switched) vs. two separate docks.** A real fork: keeping the mutation scrubber where it is and docking snapshots separately avoids relocating a working control, at the cost of two timeline docks on one card (and #1249's history of moving that scrubber already). Which wins is **ADR-0088's** call; the *model* here needs only that the two time axes be independently selectable, not that they share a track. (The failure mode both avoid is three *always-on* axes on a lore card — ADR-0044 §A.)

## Consequences

- **Save/delete hooks per kind.** Automatic session-boundary capture and the delete cascade are wired only into the scene service today (`maybe_capture_session_boundary` from `save_scene`; `delete_scene_snapshots` from `delete_scene`). Each in-scope kind's saver/deleter — **including the override save paths** (§3b) — must gain the equivalent hook, or that kind gets no auto-capture and leaks snapshot dirs on delete. The **tag merge-survivor delete cascade** (ADR-0082 §5: deleting a survivor cascades to its `merged_into` redirects) must reap **each** cascaded tag's snapshot dir, not only the directly-deleted node's.
- **Per-kind response contracts.** Restore returns the node's own model — a `LoreEntry`, a `TagEntry`, or (for an override) the **re-folded composite** — not `Scene`.
- **The mutation-scrubber's home may change** (ADR-0088's decision), a real visible UI move justified there, not here.
- **No data migration.** Existing scene snapshots stay put (§3); the store-root change is a no-op for scenes. (Distinct from the per-restore `migrate_document` branch of §4, which is preserved.)
- **Tags/plot get a metadata-first diff.** Body-less or synopsis-light kinds diff their front-matter fields rather than prose; the compare UI needs the field-diff mode (`FieldDiff` already exists — `models/snapshots.py`).

## Rollout (slices)

- **S1 — node-scoped store, proven on research (witness-free).** Thread `kind` off the `NodeIndexEntry`; move the store root to the owning-layer folder keyed by the entity id; entity-scoped addressing; the per-layer `snapshots/` exclusion (+ its guard test at an ancestor layer); restore = migrate-if-behind → structural index write → the research title heal. *Not:* lore, overrides, the combined surface. *Done when:* a research note captures/lists/diffs/byte-restores with its tree title healed, its snapshots in the note's own project folder.
- **S2 — lore, including the override case (§3b).** Owning-layer keying for base files; override addressing by entity+layer with capture on the override save and re-folded restore; the layer-scoped snapshot histories. Surface work lands with **ADR-0088**. *Done when:* the engine user journey holds — base and override keep separate histories, and a base restore re-folds downstream.
- **S3 — tags / motifs.** Snapshots-only; restore rebuilds `canonical_id`/redirects and does not replay the reference sweep; the merge/delete cascade reaps snapshot dirs; field-diff compare. *Done when:* a motif tag reverts cleanly with redirects intact.
- **S4 — prompt + plot.** Prompt (override-aware; body read-only on overrides); plot cards (persist the beat/link heal on restore). *Done when:* both capture/restore with their healers.

## Acceptance

1. A lore/research/tag/prompt/plot node captures, lists, reads, byte-restores (migrating if behind), pins, describes, and deletes snapshots through entity-scoped addressing, restore capturing a safety snapshot first.
2. A series-layer node's snapshots live under the **series** project's folder and travel with it on move/delete; opening the same node from two different books does not scatter its history.
3. A base and its book override keep **separate** snapshot histories, the override addressed by its entity id at the book layer.
4. Restoring an owning-layer file re-folds the composed downstream view without the snapshot code referencing inheritance; an overridden field correctly does not move.
5. Non-scene snapshots carry no witness and render no drift panel.
6. On a node with two timelines, one foot dock shows either, selected by a mode control; a single-timeline node shows the track with no mode control. (The surface's specifics are ADR-0088's acceptance.)
7. No existing scene snapshot is moved or invalidated; each layer's `snapshots/` is excluded from the index, the staleness manifest, and the search corpus.

## To verify / build at implementation

- Exact placement of the pre-save capture hook per kind and per save path — including the override save paths — reading the *prior* bytes before the overwrite (as `maybe_capture_session_boundary` does for scenes; the post-write index seam is too late for a "before this edit" photograph).
- The field-diff compare surface for body-less kinds (tags, and any node whose payload is front matter).
- Whether `finalize` (roleplay → clean prose, ADR-0070) stays scene-only (it should — it is manuscript-semantic).
- ADR-0088 owns the surface: the mode gadget, the two timelines' visual languages, the mutation-scrubber's home, and the combined key model reconciled with ADR-0044.

---

*This ADR amends ADR-0043's "Snapshots of lore entries or other node kinds" non-goal by reference, lifting it. ADR-0043's scene-witness model is unchanged. The on-card surface is a companion ADR (ADR-0088), for which the mockup is the evidence.*
