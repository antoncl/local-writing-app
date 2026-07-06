# Research Strategy — Design Note

## Problem

"Research" today is a flat list of `lore_note` entries living in the Lore
pane next to characters, locations, and items. It works for a handful of
notes, but breaks down at any real scale:

- A serious project accumulates dozens to hundreds of research notes
  (worldbuilding sources, interview transcripts, web clippings, primary
  documents, the author's own marginalia).
- The mental shape is **hierarchical**: authors group research by topic
  ("Industrial Revolution → Factory conditions → Lancashire mill towns
  → Worker testimonies"). A flat list collapses that hierarchy into a
  string-tag at best.
- A note about Manchester factory conditions has structural kinship to
  a *scene*, not to a *character entry*. It's prose, it sits in a
  container, it gets read top-to-bottom. The `lore_note` shape (one
  metadata-rich card per entry) actively fights that.
- Searching, filtering, and reordering all degrade as the corpus grows —
  the lore pane was tuned for the character / location / item shape,
  not for a notebook with a TOC.

The Node Model strategy ([[strategy-node-model]]) anticipates this:
every container should generalize. The manuscript tree already models
"ordered hierarchy of typed containers + leaves" (act → scene). Research
wants the same shape; today it has to pretend to be a flat lore list.

## Decision

**Research becomes its own Node kind with its own structure tree,
sibling to `manuscript_structure`.** Two new entry_types: `topic`
(container, like `act`) and `note` (leaf, like `scene`).

The kind id is `research`. The structure file is
`research.structure.yaml`, mirroring `manuscript.structure.yaml`. The
on-disk layout is `research/topics/<slug>/notes/<slug>.md`, mirroring
the act/scene folder layout. Topics nest (a topic can contain
sub-topics), the same way acts can nest.

The existing `lore_note` entry_type is **deprecated** but kept readable
for a migration window. Existing entries get an automatic
"Move to Research" affordance in the Lore pane. After migration, the
`lore_note` entry_type retires.

## Why this shape

**The hierarchy is the feature.** A "topic" container that holds notes
is exactly what users reach for when their research grows past ~20
notes. Tags and aliases don't substitute — they let you slice the data,
but they don't give you a TOC you can scan top-to-bottom. The
manuscript tree proves the UX shape works; research gets it for free.

**The Node Model generalizes the tree.** `manuscript_structure` and
`research` are two instances of "ordered tree of typed nodes." The
structure-tree code already handles drag-to-reorder, nested
containers, leaf-vs-container affordances, and per-node metadata.
Implementation cost is "instantiate the existing machinery with new
entry_types and a different storage folder," not "build a new tree
widget."

**Lore stays for entities, not for notes.** The lore pane is the right
home for characters, locations, items, organizations, magic systems —
things that have a *name*, *aliases*, and *a body describing them*.
Research notes are prose with a *topic* heading, not entities. Putting
them in the lore pane was a Phase-1 expedient that's now in the way.

**Context inclusion comes along for free.** The
[[decisions-implicit-context]] alias matcher and the
[[decisions-context-picker]] explicit picker both filter by `kind`.
Research notes participate by setting `matchable: true` (default for
the new kind) — if "Lancashire mill" shows up in the user's draft,
the matching research note gets pulled into context, same as a
character mention does today. The per-entry [[decisions-context-policy]]
mechanism (`always` / `auto` / `manual_only` / `never`) applies
unchanged.

## Alternatives considered, rejected

### A. Stay flat, lean on tags

Just add a `topic: string` tag-style field to `lore_note` and group
the lore pane view by topic. Cheapest path; no schema or storage
changes.

**Rejected because** tags model adjacency, not containment. You can
filter to "notes tagged Lancashire," but you can't put a topic
**inside** another topic (Lancashire is a sub-topic of Factory
conditions which is a sub-topic of Industrial Revolution). At any
non-trivial scale the author wants nesting. Tags also don't give a
scannable TOC view of the research corpus.

### B. Fold research into the manuscript tree

Add `topic` / `note` entry_types under `scene:base`, so the
research notes live alongside acts and scenes in one tree. Reuses
existing machinery with zero new infrastructure.

**Rejected because** the manuscript tree is the *prose outline of the
book being written.* Mixing research notes into it conflates two
different mental models — "what I'm writing" and "what I'm referencing
to write it." Authors switch between those constantly; the UI must
keep them apart. (Also: scenes are sequential; research is not. Putting
them in one tree forces a false ordering.)

### C. Generic "trees of nodes" abstraction first, then research

Refactor the manuscript tree's hierarchy logic out into a generic
`tree_structure` Node kind whose subclasses are `manuscript_structure`
and `research`. Most architecturally pure.

**Deferred, not rejected.** The right thing if a third hierarchical
kind appears (revisions tree? scratchpad tree?). For now the
manuscript-structure code can be parameterized in place — the seam is
cheap to extract later. Avoids upfront abstraction cost for a 2-instance
problem.

## Out of scope

- **Images.** A separate concern with three sub-problems (vision-capable
  assistant gating, in-body rendering, ref-library storage). Filed
  separately; do not fold into the research roll-out.
- **Web-clip import.** Pasting from a browser into a research note
  should preserve formatting and capture source URL, but the import
  pipeline is its own slice.
- **Citation export.** Research notes that ship in published prose
  need attribution — a footnote / endnote feature is downstream.
- **Cross-project research sharing.** A "research library" attached to
  a universe layer ([[decisions-project-nesting]]) rather than a single
  book is a real ask but lives in the project-hierarchies epic
  ([#7](https://github.com/antoncl/local-writing-app/issues/7)).

## Implementation slices

1. **`research` kind + structure tree backend.** Add `research`,
   `topic`, `note` to the seed schema. Implement
   `research.structure.yaml` reader / writer mirroring
   `manuscript.structure.yaml`. Storage at
   `research/topics/<slug>/notes/<slug>.md`. No UI yet.
2. **Research pane.** New pane next to Lore, showing the research
   structure tree. Reuse `NodeList` mode="tree", drag-to-reorder,
   the existing structure-node CRUD path.
3. **Note editor.** Reuse `NodeEditor` (prose body shape). Topics get
   a minimal editor — just title and color, like an `act`.
4. **Context-policy + matcher integration.** Confirm the alias matcher
   and explicit picker pick up `research/note` entries as matchable.
   Add `research` to the kind list in the implicit-context plumbing.
5. **Migration: lore_note → research/note.** Provide a one-shot
   "Move to research" action on each existing `lore_note` in the lore
   pane. Drop the `lore_note` entry_type from the seed schema after
   the user's project migrates.
6. **Lore-pane polish.** Once `lore_note` is gone, the lore pane is
   purely entities (character / place / item / organization /
   custom-kinds). Surface treatment can lean further into the
   "entity card" shape without notes diluting it.

## Follow-up issues to file

- `research` kind + structure tree backend (slice 1)
- Research pane + tree UI (slice 2-3)
- Migration tool for existing `lore_note` entries (slice 5)
- Lore pane purification post-migration (slice 6)
