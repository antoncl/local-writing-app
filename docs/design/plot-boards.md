# Plot Boards and Plot Templates

Status: draft for discussion - updated 2026-07-26

Related mockup:

- [Plot board drag-and-drop mockup](mockups/plot-board-drag-and-drop.html)

## What This Is

Plot boards are a planning surface for applying story-structure templates to a
specific book or project without turning those templates into chapter slots.

The core distinction:

- `plot:template` is a reusable rubric: a set of plot beats and craft guidance.
- `plot:template_instance` is the book-specific application of one template:
  beat notes, local labels, status, and author intent for this story.
- `plot:board` is an application of one or more templates to a specific story.

A plot beat is a template-defined story function to be achieved. It is not a
scene, chapter slot, or separate canvas work item. A card carries plot beat
claims: card-local markers that say the card contributes to a beat in a specific
way. One card may carry several beat claims when one narrative action performs
several jobs; several cards may carry claims toward the same beat when the beat
is earned cumulatively. A beat may also be intentionally omitted or subverted.

For authors, the model should feel like this:

- arrange acts, chapters, sequences, and cards on a canvas;
- use plot templates as optional lenses over those cards;
- attach plot beat claims/function markers to the cards that perform those
  functions;
- draw relationships between cards when order, causality, setup/payoff, or
  contrast matters.

The implementation has three separate layers:

- Manuscript Structure owns acts, chapters, sequences, and scene ordering.
- Plot Board owns cards, plotlines, plot beat claims/function markers, and
  relationships.
- Svelte Flow layout owns coordinates, viewport, and visual nesting.

The UI should keep those layers mostly invisible. Authors should not need to
learn "axis", "columns", "claims", or "template instances" to use the board.

### Example: One Plot Beat, Several Claims

In a three-act template, the plot beat "First Turning Point" might mean "the
protagonist crosses a threshold into the main conflict." In this book, that
function may be satisfied by a chapter where Mara steals a ledger and can no
longer return to her old life.

Several card-local claims combine to make that beat credible:

- commitment: Mara chooses theft over obedience;
- lock-in: returning the ledger would expose her;
- escalation: the antagonist now has a reason to hunt her;
- question: what secret is valuable enough to risk exile?

The three layers express the same material differently:

```yaml
manuscript_structure:
  act: Act I
  chapter: Chapter 4 - The Ledger
  scene: scene_archive_breakin

plot_board:
  card:
    id: card_archive_breakin
    title: Archive Break-in
    node_ref: scene:scene_archive_breakin
    structure_column_id: chapter_4
  function_badges:
    - template_plot_point: first_turning_point
      claim_type: satisfies
      evidence:
        - commitment
        - lock-in
        - escalation
        - raises_question

layout:
  group: chapter_4
  node: card_archive_breakin
  position: { x: 80, y: 140 }
```

The manuscript layer says where the scene lives. The plot-board layer says what
story work the card claims to do. The layout layer says where the card appears
on the canvas.

## Design Principles

- Templates are lenses, not outlines. A template may guide diagnosis, but it
  must not create chapters or scenes by default.
- Cards are board state over existing project nodes. They are not a second scene
  system.
- Placeholders are allowed, and may later be promoted into real scenes.
- Cards are the story work surface. Plot beats should not be rendered as
  duplicate work nodes; they appear as function markers/claims on cards and as
  progress/diagnostic state in palettes or inspectors.
- An untagged card is diagnostically suspicious, not automatically wrong. The
  useful question is "what story function does this card serve?"
- The board's structure should be tied to the draft structure where possible:
  acts, chapters, sequences, or whatever structure node types the project
  allows. Template order is not manuscript structure and should not be presented
  as chapter placement.
- AI must read semantic board data, not Svelte Flow coordinates.
- System-provided templates are read-only. Editing starts by duplicating them
  into a local layer, matching the saved-view pattern.
- Layering follows ADR-0039: ancestor layers are visible to descendants; scenes
  remain book-scoped; local copies and overrides are explicit.
- User-authored local content is the user's data. The app should not police
  exact user-entered template wording any more than it polices prose, lore, or
  research notes.

## Terms

**Board-local** means the object lives inside one `plot:board` spec and has no
identity outside that board. Deleting or duplicating the board deletes or
duplicates the object with it. Board-local plotlines are enough when a plotline
exists only to organize one planning canvas.

**Book-level plotting** is the author's full plotting model for the book: main
plot, subplots, character arcs, relationship arcs, mystery threads, thematic
threads, and any other lines of story pressure. In the current model this lives
inside the board. There is no separate book-level plotline registry unless a
future workflow proves one is needed.

**Plot beat** means a template-defined story function. "First Turning Point",
"Midpoint", "Climax", and "Dark Night" are plot beats when a template uses those
labels.

**Plot beat claim** means a card-local assertion that a card contributes to a
plot beat. The claim points from the card to the beat and may carry assignment
type, strength, rationale, evidence, and AI notes. This is the internal model.

**Structure group** means a visual group on the plot board backed by an act,
chapter, sequence, or other Manuscript Structure node. The board may render
these as nested Svelte Flow groups, but the board does not own the manuscript
hierarchy.

**Function marker** or **function badge** is the user-facing term for a plot beat
claim on a card. The badge is not the beat itself; it is the card's claim about
how it participates in that beat.

The expectation is one primary plot board per book. That board can still contain
many plotlines and many template instances. Multiple boards may exist later for
experimentation, alternate structures, or scratch work, but they are not the
reason plotlines exist.

## Node Kinds

Introduce one new kind:

```text
kind: plot
```

Initial entry types:

```text
plot:template
plot:template_instance
plot:board
```

All three are ordinary file-backed nodes. A likely folder layout:

```text
plots/
  templates/
  boards/
```

System templates may be exposed as read-only system nodes and materialized into a
project/book layer on duplicate, as system default views are materialized today.

`plot:template` may carry a prose body for human craft notes, examples, caveats,
or source commentary. The structured template data remains the machine-readable
rubric; the prose body is optional guidance.

`plot:template_instance` is also a proper node backed by a Markdown file. This
keeps the application of a template inspectable, referenceable, and reusable by
AI/context selection. The board references template-instance nodes rather than
owning all instance state inline.

Template instances being nodes is also important for mutation-gated context.
Plot-instance data may contain future reveals, culprit identities, solution
chains, character betrayals, or end-state knowledge that must not leak into a
scene-generation prompt too early. If the prose generator can see the complete
plot board, it may reveal hidden information when it is uncertain or
hallucinating. Treating template instances as nodes lets the existing mutation /
effective-state machinery hide or rewrite future-sensitive plot information for
the active manuscript position.

## Template, Story Use, and Board

A template defines the general class of a plotting rubric:

```yaml
id: template_three_act
entry_type: plot:template
title: Three Act Structure
template:
  family: act
  description: A broad setup/confrontation/resolution structure.
  beats:
    - id: setup
      title: Setup
      function_claim: Establishes the story's starting situation, promises, and central pressure.
      guidance: Show ordinary conditions under pressure; do not treat this as a mandatory opening chapter.
      required: true
    - id: first_turn
      title: First Turning Point
      function_claim: Pushes the protagonist into a changed story situation.
      guidance: The old path should no longer feel fully available.
      required: true
```

A template instance applies one template to the current story:

```yaml
id: inst_main_three_act
entry_type: plot:template_instance
title: Main plot structure
instance:
  template_ref: template_three_act
  beat_notes:
    first_turn:
      notes: Mara commits by stealing the ledger instead of reporting it.
      status: planned
```

A board references template instances and arranges story cards against draft
structure:

```yaml
id: board_main_plot
entry_type: plot:board
title: Main Plot Board
board:
  template_instance_ids:
    - inst_main_three_act
  plotlines:
    - id: main
      title: Main Plot
    - id: romance
      title: Romance
  cards:
    - id: card_archive_breakin
      title: Archive Break-in
      node_ref: scene:scene_archive_breakin
      primary_plotline_id: main
  claims:
    - id: claim_archive_first_turn
      card_id: card_archive_breakin
      template_instance_id: inst_main_three_act
      plot_point_id: first_turn
      plotline_id: main
      claim_type: satisfies
      strength: strong
      rationale: Mara takes an irreversible action that changes her relationship to the Archive.
```

The template explains what a plot beat means in general. The template-instance
node records book-specific notes or disabled beats. The board displays and edits
card-local function markers/claims against those instances.

## Data Contracts

### PlotTemplate

```ts
type PlotTemplate = {
  id: string;
  slug: string;
  display_name: string;
  aliases?: string[];
  family: "act" | "journey" | "cycle" | "genre" | "puzzle" | "relationship" | "character_arc" | "custom";
  description?: string;
  cultural_context?: string;
  prescriptiveness?: "descriptive" | "diagnostic" | "prescriptive";
  ai_use_guidance?: string;
  global_diagnostic_questions?: string[];
  source_refs?: SourceRef[];
  ip_risk?: "low" | "medium" | "high" | "unknown";
  builtin_policy?: "seed" | "seed_generic" | "reference_only" | "user_authored";
  version?: string;
  locale?: string;
  beats: PlotBeat[];
};
```

### PlotBeat

```ts
type PlotBeat = {
  id: string;
  title: string;
  function_claim: string;
  guidance?: string;
  required?: boolean;
  metadata?: Record<string, unknown>;
};
```

Beat order is the array order inside the template, not an editable field on each
beat. Labels derive from `title`. Fields such as value change, polarity, scene
beat mapping, genre-specific diagnostics, or McKee-style value movement should be
user-extensible fields rather than default required fields.

### PlotTemplateInstance

```ts
type PlotTemplateInstance = {
  id: string;
  template_ref: string;
  title: string;
  disabled_beat_ids?: string[];
  beat_notes?: Record<string, PlotBeatInstanceNote>;
  source_layer_id?: string;
  source_layer_label?: string;
};
```

### PlotBeatInstanceNote

```ts
type PlotBeatInstanceNote = {
  local_title?: string;
  notes?: string;
  status?: "unplanned" | "planned" | "drafted" | "satisfied" | "intentionally_omitted";
  metadata?: Record<string, unknown>;
};
```

### PlotBoard

```ts
type PlotBoardSpec = {
  template_instance_ids: string[];
  plotlines: PlotLine[];
  cards: PlotCard[];
  claims: PlotPointClaim[];
  relationships?: PlotRelationship[];
};
```

`PlotBoardSpec` does not need a board-owned structure tree for the normal book
plotting workflow. Draft-backed structure groups are derived from Manuscript
Structure at render time. When the author adds or moves a chapter/container from
the board, the board should call the same backend structure mutation used by the
Draft pane and then refresh from canonical structure data.

Manual planning-only groups may be useful later for scratch boards, but they
should not be the default book plotting model. If added, they should be clearly
separate from Manuscript Structure groups so the board does not become a second
canonical manuscript hierarchy.

### PlotCard

```ts
type PlotCard = {
  id: string;
  title: string;
  synopsis?: string;
  card_kind: "placeholder" | "node";
  node_ref?: string;
  structure_column_id?: string;
  primary_plotline_id?: string;
  metadata?: Record<string, unknown>;
};
```

`node_ref` should use the existing node identity vocabulary where possible. A
placeholder card has no `node_ref`; promotion creates a real scene and adds one.
`structure_column_id` places the card inside an act/chapter/sequence structure
group without implying that the card itself owns the structure node. The name is
legacy from the earlier column-strip prototype; conceptually this is a structure
reference and should migrate toward a clearer name such as `structure_ref_id`
when a schema migration is worth the churn.

### Plot Beat Claim / Function Marker

```ts
type PlotPointClaim = {
  id: string;
  card_id: string;
  template_instance_id: string;
  plot_point_id: string;
  plotline_id?: string;
  claim_type: PlotClaimType;
  claim_label?: string;
  strength?: "weak" | "medium" | "strong";
  confidence?: number;
  evidence?: string;
  rationale?: string;
  ai_notes?: string;
  metadata?: Record<string, unknown>;
};
```

This record is a decorator on a card, not an instruction owned by a plot beat.
It says: "this card is intended to perform this story-function job in service of
this plot beat." The beat defines the target function. The claim records the
card's participation, with optional assignment type, strength, evidence,
rationale, and AI notes.

If the card is promoted to or linked with a scene, its claims become expectations
about elements the scene should contain: an obstacle, reveal, crisis point,
decision, reversal, promise/payoff, relationship shift, clue, cost, or
consequence. The claim still belongs to the card; the scene provides prose
evidence.

AI should check claims in two directions:

- card-level: does this card or linked scene actually perform the claimed
  function?
- beat-level: do all cards claiming the same beat collectively satisfy the
  beat's `function_claim`?

Untagged cards should be surfaced as "no declared function yet" or equivalent.
They are suspicious because they may not advance the story, but they may also be
atmosphere, transition, setup, or a still-unmarked contribution.

Initial badge assignment vocabulary:

```ts
type PlotClaimType =
  | "satisfies"
  | "partially_satisfies"
  | "subverts"
  | "foreshadows"
  | "pays_off"
  | "raises_question"
  | "rejects"
  | "custom";
```

The enum is expected to evolve. `custom`, `claim_label`, and `metadata` keep the
format from freezing the discovery process too early.

### PlotRelationship

```ts
type PlotRelationship = {
  id: string;
  from_card_id: string;
  to_card_id: string;
  kind: "causes" | "blocks" | "reveals" | "setup_payoff" | "echoes" | "contrasts" | "custom";
  label?: string;
  metadata?: Record<string, unknown>;
};
```

## Layout and UI State

Svelte Flow state is presentation, not the semantic board.

```ts
type PlotBoardLayout = {
  nodes: PlotLayoutNode[];
  edges: PlotLayoutEdge[];
  viewport?: { x: number; y: number; zoom: number };
};
```

`PlotBoardSpec` answers "what does this board mean?" `PlotBoardLayout` answers
"where did the author put things on the canvas?"

This mirrors `ViewSpec` / `ViewLayout`.

The visual implementation should keep the normal Svelte Flow affordances visible:
pan, zoom, fit-to-view, and a minimap/overview when the board grows beyond the
current viewport. These controls are presentation state, but they matter to the
authoring workflow because a single board may contain the book's plot,
subplots, character arcs, and unresolved placeholders.

Structure groups are Svelte Flow subflows projected from Manuscript Structure.
Dragging a card into a different group updates the card's structure reference
(`structure_column_id` in the current contract). Dragging a chapter or other
movable container into a different parent routes through the Manuscript
Structure move API. The rendered node parentage and coordinates are layout
state; the board and structure records remain the source of truth.

The default layout should make manuscript organization legible before manual
tuning: top-level containers left-to-right, nested containers left-to-right
within their parent, and cards top-to-bottom within the most specific assigned
container.

Function markers are board interactions over semantic `PlotPointClaim` records.
Dragging from the palette creates a badge on a card. Dragging an existing badge
from one card to another moves that assignment by changing its `card_id`; it
does not create a duplicate unless the user explicitly asks for copy/duplicate
behavior.

## AI Context

Plot-board AI should follow the current prompt/context pattern: store structured
refs and render the actual context at invocation time. Do not store copied scene
or lore bodies in the board.

AI context must resolve plot template instances through the same effective-state
discipline as other mutable story data. A prompt for Chapter 3 should not receive
unguarded future-only plot facts such as "the butler did it" merely because that
fact exists somewhere on the full book board.

A board context packet should include:

- board title and author notes;
- template instances with resolved template and plot-beat definitions;
- plotlines;
- cards with titles, synopses, node refs, and resolved node summaries;
- function markers/claims grouped by template instance and plotline;
- unresolved, weak, partial, rejected, or intentionally omitted beats;
- untagged cards with no declared story function;
- relationships between cards;
- optional selected cards or selected plot beats as target context.

The likely UI is a specialized Plot Context Picker: similar in spirit to the
existing `context_pick`, but centered on boards, template instances, plot beats,
cards, function markers, and plotlines. It should let an author choose "this
board", "these plot beats", "these weak markers", or "this card and its related
plot functions" without forcing a generic node picker to understand
plot-specific intent.

The AI contract should ask for evidence before making an assignment:

```text
Do not mark a plot beat satisfied unless you can cite the contributing card(s),
linked scene summaries, or author notes that perform the function. If evidence
is partial, return partially_satisfies with rationale.
```

AI outputs should land as draft artifacts:

- suggested cards;
- suggested function markers/claims;
- suggested relationship edges;
- critique notes;
- alternate template-instance mappings;
- questions for unresolved plot beats.

No AI operation should silently mutate the board or manuscript.

### Near-Term Essentials

The remaining plotting work should keep sight of these essentials:

- apply AI suggestions back into the board as explicit, user-approved draft
  edits;
- support claim/beat assist at the right granularity: card, function marker,
  plot beat, template instance, and whole board;
- make evidence a first-class workflow so the author can see why a card or
  linked scene does or does not satisfy a function marker;
- keep template-instance editing clear, including renaming, deletion, beat
  specifics, author intent, expected role, and open questions;
- provide a board-level overview for weak, missing, overloaded, duplicated, and
  untagged story work;
- define relationship and sequence semantics well enough that edges mean
  causality, setup/payoff, contrast, blocking, reveal, or custom intent rather
  than just visual lines;
- polish prompt context so XML dumps and Jinja access stay consistent,
  complete, ordered, and understandable to prompt authors and AIs;
- remove usability friction around deleting cards, moving markers, clipped
  statuses, dense rails, and hard-to-grab nested containers.

## Built-In Template Policy

Initial candidates for low-risk generic built-ins:

- Three Act Structure
- Seven Point Structure
- Story Circle style cycle
- Kishotenketsu
- generic Romance Arc
- Fair-Play Mystery Engine
- Thriller Escalation Engine
- Character Arc models

Candidates requiring cautious generic wording or reference-only handling:

- Hero's Journey
- Heroine's Journey / Integration Journey
- Save the Cat
- branded romance or genre beat sheets

Each built-in template should carry source/citation metadata and an explicit
`builtin_policy`. A separate IP/trademark research pass should decide which
templates are seeded exactly, seeded generically, or left user-authored.

The app should support user-authored templates as ordinary local project data.
If a user chooses to type or import exact terminology from a book, course, or
commercial plotting method, that is their responsibility. The app itself should
avoid presenting template import as a way to obtain protected content from the
software.

## V1 Scope

V1 should be a thin vertical slice:

- create/read/save/delete `plot:board` nodes;
- list read-only system `plot:template` nodes;
- duplicate a system template into a local `plot:template_instance` node;
- list/read/save local `plot:template_instance` nodes referenced by a board;
- add board-local plotlines;
- show draft-structure-backed nested groups on a Svelte Flow canvas;
- move cards between structure groups by updating the card's structure
  reference;
- move chapters/containers between supported parents by reusing existing
  Manuscript Structure mutations;
- add a new chapter/structure node from the board by reusing existing structure
  mutations;
- add placeholder cards;
- attach existing scene nodes to cards;
- expose an affordance on placeholder cards for promoting them to scenes;
- add/edit/remove function markers/claims;
- support undo/redo for badge attachment/removal and card/structure edits;
- persist Svelte Flow layout;
- serialize board context for AI prompts.

Not V1:

- a separate book-level plotline registry;
- cross-book plotline sharing;
- automatic template licensing/import marketplace;
- automatic manuscript restructuring from a board;
- server-side AI mutation of boards;
- full template editor polish beyond the minimum needed to duplicate and edit.

## Deferred UX Details

Some interaction details should wait for sketches or a working prototype:

- the exact card affordance for promoting a placeholder into a scene;
- the exact Plot Context Picker surface beyond selecting a template-instance
  band or a specific card;
- how function markers are summarized in palettes, inspectors, and AI
  diagnostics without duplicating the card workspace.

These are not model blockers. The data model should leave room for those
interactions without pretending the UI can be finalized before there is a visual
prototype.
