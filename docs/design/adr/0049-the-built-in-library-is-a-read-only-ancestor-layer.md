# ADR-0049: The built-in library is a read-only ancestor layer of nodes

- Status: **Proposed** — 2026-07-29. Designed with Anton over #606.
- Issue: #606 · Pre-1.0 (no release milestone)
- Follows: ADR-0039 (the hierarchy model — inheritance is virtual membership, ancestor
  nodes materialized into the open project), ADR-0042 (the edit gesture on an inherited
  node — the `⧉` fork, and read-only-in-place as a structural property), ADR-0047 (feature
  invocation is an app menu plus contextual actions — the Prompts home is the discovery
  surface)
- Relates: ADR-0046 (the `prompt:revise:entry` pre-rolled brainstorm); the class–instance model
  (`kind` = class, `entry_type` = sub-class, `entry` = instance)

## Context

The app ships, and will keep shipping, **ready-to-use material** — the first two are the
`roleplay` and `revise:entry` prompts, and we expect ~10–15 prompts by ship, with other
kinds (lore scaffolding, and more) on the horizon. The intent is that a writer gets working
material **out of the box** and then leans on it: use it, then clone and extend it into their
own.

Today that material has no home of its own. A pre-rolled prompt is carried as a `default_body`
on the entry *type*, and it becomes a runnable node only when the user manually creates an
instance of that type — a fresh project seeds none. Every surface that could reveal it (the
slash menu, the ADR-0047 Prompts home) lists the writer's own *instances*, so the shipped
material is invisible until the writer already knows to create it. "Pre-rolled" currently
means "comes pre-filled *if* you know to make one," and the gap widens linearly with the count.

Two failure modes bound the design:

- **Clutter.** The obvious fixes — bulk-seeding every shipped node into a new project, or
  materializing one into the project the first time it is run — drop app-owned files into the
  writer's work folders. Anton's requirement is explicit: **the shipped material must not
  clutter the ordinary workfolders.**
- **Prompt-tunnel-vision.** A prompt-only "catalog on the type" solves discovery for prompts
  and nothing else. The concept has to be **kind-agnostic** from the start, or the second kind
  of shipped material re-opens the whole question.

The requirement, in Anton's words: the shipped material should be **uneditable, cloneable, and
hideable**, and it should live outside the writer's folders.

## Decision

**Shipped ready-to-use material is a built-in Library: a read-only ancestor layer of nodes,
owned by the app, present under every project without living in it. A writer uses a Library
item in place, clones it to own an editable copy, and hides the ones they don't want.**

### 1. The Library is a built-in read-only layer of *nodes*

The app already ships a built-in **schema** that sits underneath every project's own settings
without being a file in that project (`default_schema.py`, the base of the ADR-0039 merge). The
Library is the same move for **nodes**: an app-owned layer of ready-made nodes that composes
underneath every project as its deepest ancestor.

This is deliberately not a new subsystem. ADR-0039 already made inheritance *virtual
membership* — an ancestor's nodes are materialized into the open project's working set, marked
by provenance, without being copied into its folders. The Library is one more ancestor at the
bottom of that chain. Everything that already knows how to show an inherited node, mark where it
came from, and offer to fork it applies unchanged.

Because the Library layer is **app-owned**, its physical form is an implementation concern and
is left open here (the ADR-0005 lesson: a guessed storage slot acquires authority it never
earned). The only binding constraints on that form: the material is **not written into the
user's project folders**, and the layer is **never a valid write target** (see §3).

### 2. Three interactions, and only three

- **Use in place.** A Library node is a real, resolved node, so it runs / is used exactly like
  one of the writer's own — no cloning required. This is what "out of the box" means: the writer
  reaches for `/roleplay` and it works before they have authored anything.
- **Clone to own.** Making it yours is the existing ADR-0042 fork gesture (`⧉`): it lifts the
  Library node into a writable layer (the open project) as an editable copy the writer owns, and
  from that point it is an ordinary node. Cloning is the *only* path to a change (§3).
- **Hide.** A per-project suppression so a writer can curate the shelf down to what they actually
  use. Hide is **presentation-scoped and reversible** — it removes the item from *this project's*
  Library view; it does not delete the node, alter canon, or touch other projects. (It is not an
  ADR-0039 tombstone — that ADR's merge is additive by design; this is a view filter the writer
  owns, not a change to the inherited set.)

### 3. Wholly read-only — clone is the only write

A Library node **cannot be edited in place, and cannot be overridden field-by-field.** The only
way to change shipped material is to clone it and edit the copy.

This is stronger than ADR-0042's ancestor-edit gesture, and deliberately so. Under ADR-0042 an
ancestor node *can* be written at its owning layer ("correct canon") or overridden below it,
because those ancestors are the writer's own series/world projects. The Library is **not the
writer's to correct** — it is app-owned. So the read-only property is structural, not a checked
flag: the Library layer sits below every user-writable layer and is **never selectable as an
authoring target**, so "edit the Library" is *unconstructable* rather than something to validate
against (the same shape as ADR-0042's "a name is always asserted at or above the layer holding
its value").

Per-field override of a Library item was considered and **rejected** — see the alternatives
below. The one-sentence reason: partial editability is a surface that looks uniform and
surprises the writer only at the moment it bites, which is precisely the carve-out ADR-0042
itself refused.

### 4. Kind-agnostic — the Library holds nodes, prompts are the first tenant

The Library is a shelf of **nodes**, not a prompt feature. Prompts are simply the first kind
shipped on it; lore scaffolding and whatever follows are later tenants that need **no new
mechanism** — they inherit use-in-place / clone / hide for free, because those are node
operations.

What this ADR does **not** do is build generic "pre-rolled" machinery for kinds that do not yet
exist. The generality lives in the *model* (an ancestor layer is already kind-blind), not in
speculative per-kind code. The rollout is one kind at a time (prompts first), on the
vertical-slice discipline; the ADR commits the shape, not the schedule.

### 5. Discovery is the ADR-0047 invocation surface

ADR-0047 shipped a deliberately-visible app menu with a **Prompts** home. That home is where the
Library surfaces: it gains a **Library section** listing the shipped items of that kind, distinct
from the writer's own nodes, offering *use* and *clone* (and *hide*). The slash menu draws
runnable prompts from the same resolved set, so a Library prompt is invocable **before** any
instance exists — closing the original discovery gap at the surface ADR-0047 already built.

No new invocation model is coined. A Library item is found and run through the surfaces ADR-0047
already decided; the Library only adds *what* those surfaces enumerate (shipped items, not only
instances).

### 6. Layering composes; the Library is the floor

Because the Library is an ancestor layer, it composes with the existing chain rather than
competing with it. Two consequences fall out:

- A writer's own ancestor project (a world or series layer) **can already** contribute shipped-
  style material through the ordinary inheritance chain; the Library does not special-case that,
  it sits beneath it. The Library is the **app-owned floor** of the same stack — the analogue of
  `default_schema.py` at the bottom of the schema merge.
- The Prompts home reflects the **resolved** set, so an item contributed by an ancestor layer and
  an item from the built-in Library appear by the same path. Whether a *writer's* ancestor layer
  should be able to mark its own contributions read-only/hideable the way the app-owned floor is
  is **out of scope here** and noted below — this ADR decides the built-in floor, not a general
  "publish a read-only layer" authoring feature.

### 7. The one rule

> **The Library is an ancestor you cannot author into. You use its nodes where they sit, you
> clone one to own it, and you hide the ones you don't want — and nothing the app ships is ever
> a file in your project.**

Everything else is the existing inheritance, fork, and invocation machinery, unchanged.

## Why / rejected alternatives

**Bulk-seed the shipped nodes into every new project.** The simplest thing that makes them
discoverable: create all ~10–15 as real files on project creation. **Rejected on two counts.**
It clutters every project with material the writer never asked for (the stated anti-requirement),
and — worse — each seeded file is a **frozen copy** of the shipped body, so improving a shipped
prompt after the fact never reaches any existing project. The Library-as-layer keeps the app the
single source of the shipped material until the writer deliberately clones it.

**Lazy-materialize on first run.** (The model I first proposed.) Never seed; the first time a
writer runs a shipped prompt, create the instance in their project and run it. **Rejected:** it
still drops an app-owned node into the writer's work folder — a writer who tries five shipped
prompts to see what they do now has five files they didn't author. It trades bulk clutter for
drip clutter, and the requirement is *no* clutter.

**A prompt-only catalog carried on the entry type.** Enumerate the prompt *types* that carry a
`default_body` and run straight from the type. **Rejected:** it does not generalize past prompts
(the second shipped kind re-opens the whole design), and it entrenches the smell that started
#606 — a *type* carrying a concrete, runnable *body* is a class pretending to be an instance.
The Library makes shipped ready material a *node*, which is what it is.

**Per-field override of a Library item in place.** Let a writer tweak one field of a shipped
prompt without cloning, via the ADR-0042 override delta. **Rejected:** it makes the Library
half-editable — uniform to the eye, writable only in some places — which is the exact
"partial editability surprises the author only when it bites" carve-out ADR-0042 refused. Keeping
the rule "any change means clone" makes *uneditable* legible: the writer always knows whether
they are looking at shipped material or their own.

**Keep `default_body` on the type as the home for shipped ready material.** The `default_body`
stays useful — it is the starting content when a writer authors a **brand-new** prompt of that
type from scratch (the "blank of this type" template). But it is **not the shelf**: the ready-to-
run shipped artifacts live on the Library as nodes. The two do not collide — one is a template
for authoring a new instance, the other is a shipped instance you use or clone.

## Anti-goals

- **Not prompt-specific.** The Library is a general shelf of shipped nodes; prompts are the first
  tenant, not the definition.
- **Never a file in the writer's project.** No bulk seed, no lazy seed, no copy-on-run. Shipped
  material enters a writer's folders only by an explicit clone.
- **No in-place editing of shipped material.** The answer to "I want it different" is always
  *clone*, never *unlock* and never *override one field*.
- **No new invocation model.** Discovery and running reuse ADR-0047's surfaces; the Library only
  changes what they enumerate.

## User journey

A writer opens a fresh project. Nothing is in their prompts folder — the folder is empty and
uncluttered. They open the Prompts home from the app menu and see a **Library** section: the
shipped prompts, marked as shipped, not as theirs. They run `/roleplay` on a scene and it works
immediately — no setup, no "create one first." A week later they want the roleplay prompt to
push harder on dialogue; they **clone** it, and now there is one prompt in their project — the
one they chose to own — which they edit freely. The shipped original stays put, read-only,
untouched. The three prompts they will never use, they **hide**, and their shelf shows only what
they reach for. At no point did the app write a file into their work folders that they did not
ask for.

## Consequences

- **The Prompts home (ADR-0047) gains a Library section** enumerating shipped items of that kind,
  offering use / clone / hide, visually distinct from the writer's own nodes. The slash menu
  draws runnable prompts from the resolved set so a shipped prompt is invocable before any
  instance exists.
- **`⧉` fork generalizes from lore to any kind.** ADR-0042's clone gesture exists for lore; the
  Library needs it kind-agnostic (prompts first). This is a generalization of an existing
  gesture, not a new one.
- **A per-project hide needs a home.** A small, writer-owned, reversible suppression list, scoped
  to the project and to presentation. Its exact storage is deferred (it is a view concern, not
  canon).
- **`default_body` on the type keeps its narrower job** — the starting content for authoring a
  brand-new prompt of that type — and stops being the de-facto home of shipped ready material.
- **The built-in Library is app-owned content with a pre-1.0 shape.** Like `default_schema.py`,
  it ships with the app and is not a user artifact; its on-disk form and update story are
  implementation, decided when the first slice is built, under the single constraint that it is
  not written into project folders and is never a writable layer.

## Deliberately out of scope (deferred, not sketched)

Stated so a later thread does not read silence as *decided*:

- **The Library's physical form** (bundled files, a synthetic layer assembled at load, etc.). The
  model is fixed — read-only app-owned ancestor of nodes; the mechanism is the first slice's to
  choose. This ADR intentionally records no storage slot (ADR-0005).
- **Whether a writer's own ancestor layer can publish read-only/hideable material** the way the
  app floor does. Plausibly the same machinery generalizes, but that is a separate authoring
  feature; committing its shape here would be a P2 guess.
- **Per-kind rollout order and the shipped set's contents.** The ADR fixes that the Library is
  kind-agnostic and prompts are first; which prompts ship, and when lore scaffolding follows, are
  slice-level calls.
- **Hide granularity and its exact storage.** Per-item project-scoped suppression is decided; the
  representation is not.
