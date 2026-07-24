# Plot Boards and Plot Templates

Status: draft for discussion · 2026-07-18

## What This Is

Plot boards are a planning surface for applying story-structure templates to a
specific book or project without turning those templates into chapter slots.

The core distinction:

- `plot:template` is a reusable rubric: a set of plot points and craft guidance.
- `plot:template_instance` is the book-specific application of one template:
  point notes, local labels, status, and author intent for this story.
- `plot:board` is an application of one or more templates to a specific story.

A plot point is a story function claim, not a required location in the manuscript.
One scene may satisfy several plot points across several plotlines; one plot point
may be satisfied by several scenes; a plot point may also be intentionally omitted
or subverted.

## Design Principles

- Templates are lenses, not outlines. A template may guide diagnosis, but it
  must not create chapters or scenes by default.
- Cards are board state over existing project nodes. They are not a second scene
  system.
- Placeholders are allowed, and may later be promoted into real scenes.
- The board's horizontal structure should be tied to the draft structure where
  possible: acts, chapters, sequences, or whatever structure node types the
  project allows. Plot phases and template placement guidance are overlays, not
  the primary manuscript axis.
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

Both are ordinary file-backed nodes. A likely folder layout:

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

## Template As Class, Board As Instance

A template defines the general class of a plotting rubric:

```yaml
id: template_three_act
entry_type: plot:template
title: Three Act Structure
template:
  family: act
  description: A broad setup/confrontation/resolution structure.
  points:
    - id: setup
      label: Setup
      purpose: Establish the story's starting situation, promises, and central pressure.
    - id: first_turn
      label: First Turning Point
      purpose: Push the protagonist into a changed story situation.
```

A template instance applies one template to the current story:

```yaml
id: inst_main_three_act
entry_type: plot:template_instance
title: Main plot structure
instance:
  template_ref: template_three_act
  point_notes:
    first_turn:
      status: planned
      author_intent: Mara commits by stealing the ledger instead of reporting it.
```

A board references template instances and arranges story cards against draft
structure:

```yaml
id: board_main_plot
entry_type: plot:board
title: Main Plot Board
board:
  template_instance_refs:
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

The template explains what a plot point means in general. The template-instance
node records what that point means in this book. The board displays and edits
claims against those instances.

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
  supports_compression?: boolean;
  supports_expansion?: boolean;
  source_refs?: SourceRef[];
  ip_risk?: "low" | "medium" | "high" | "unknown";
  builtin_policy?: "seed" | "seed_generic" | "reference_only" | "user_authored";
  version?: string;
  locale?: string;
  points: PlotPoint[];
};
```

### PlotPoint

```ts
type PlotPoint = {
  id: string;
  key: string;
  order_index: number;
  label: string;
  label_variants?: string[];
  short_label?: string;
  phase_label?: string;
  parent_point_id?: string;
  function: PlotPointFunction;
  placement?: PlotPointPlacement;
  diagnostic_questions?: string[];
  failure_modes?: string[];
  compression?: PlotPointCompression;
  claim_evidence_prompts?: string[];
  ai_rubric?: PlotPointAIRubric;
  source_ref_ids?: string[];
};
```

### PlotTemplateInstance

```ts
type PlotTemplateInstance = {
  id: string;
  template_ref: string;
  title: string;
  enabled_point_ids?: string[];
  point_notes?: Record<string, PlotPointInstanceNote>;
  source_layer_id?: string;
  source_layer_label?: string;
};
```

### PlotPointInstanceNote

```ts
type PlotPointInstanceNote = {
  local_label?: string;
  author_intent?: string;
  expected_role?: string;
  open_questions?: string[];
  status?: "unplanned" | "planned" | "drafted" | "satisfied" | "intentionally_omitted";
};
```

### PlotBoard

```ts
type PlotBoardSpec = {
  template_instance_refs: string[];
  structure_axis?: PlotStructureAxis;
  plotlines: Plotline[];
  cards: PlotCard[];
  claims: PlotPointClaim[];
  relationships?: PlotRelationship[];
};
```

### PlotStructureAxis

```ts
type PlotStructureAxis = {
  source: "draft_structure" | "manual";
  columns: PlotStructureColumn[];
};
```

```ts
type PlotStructureColumn = {
  id: string;
  title: string;
  structure_node_id?: string;
  parent_structure_node_id?: string;
  entry_type?: string;
  kind?: "act" | "chapter" | "sequence" | "manual" | "custom";
  position: number;
  metadata?: Record<string, unknown>;
};
```

When `source` is `draft_structure`, columns are backed by Manuscript Structure
nodes such as acts, chapters, or sequences. When the author adds a chapter from
the board, the board should call the same backend structure mutation used by the
Draft pane and then refresh the axis from canonical structure data.

When `source` is `manual`, columns are planning-only buckets. This should be a
fallback for scratch boards, not the default book plotting model.

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
`structure_column_id` places the card under an act/chapter/sequence column
without implying that the card itself owns the structure node.

### PlotPointClaim

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

Initial claim vocabulary:

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

Function-claim badges are board interactions over semantic `PlotPointClaim`
records. Dragging from the palette creates a claim on a card. Dragging an
existing badge from one card to another moves that claim by changing its
`card_id`; it does not create a duplicate claim unless the user explicitly asks
for copy/duplicate behavior.

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
- template instances with resolved template and plot-point definitions;
- plotlines;
- cards with titles, synopses, node refs, and resolved node summaries;
- claims grouped by template instance and plotline;
- unresolved, weak, partial, rejected, or intentionally omitted points;
- relationships between cards;
- optional selected cards or selected plot points as target context.

The likely UI is a specialized Plot Context Picker: similar in spirit to the
existing `context_pick`, but centered on boards, template instances, plot points,
cards, claims, and plotlines. It should let an author choose "this board", "these
plot points", "these weak claims", or "this card and its related claims" without
forcing a generic node picker to understand plot-specific intent.

The AI contract should ask for evidence before making a claim:

```text
Do not mark a plot point satisfied unless you can cite a card, scene summary,
or author note that performs the function. If evidence is partial, return
partially_satisfies with rationale.
```

AI outputs should land as draft artifacts:

- suggested cards;
- suggested claims;
- suggested relationship edges;
- critique notes;
- alternate template-instance mappings;
- questions for unresolved plot points.

No AI operation should silently mutate the board or manuscript.

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
- show a draft-structure-backed horizontal axis;
- add a new chapter/structure node from the board by reusing existing structure
  mutations;
- add placeholder cards;
- attach existing scene nodes to cards;
- expose an affordance on placeholder cards for promoting them to scenes;
- add/edit/remove function claims;
- support undo/redo for claim attachment/removal and card/structure edits;
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
- how function-claim badges, bands, lanes, and cards are visually balanced on
  the canvas.

These are not model blockers. The data model should leave room for those
interactions without pretending the UI can be finalized before there is a visual
prototype.
