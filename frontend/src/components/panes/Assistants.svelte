<script context="module" lang="ts">
  import type { AssistantEntrySummary } from "@/lib/types";
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import RowCaret from "@/components/widgets/RowCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import { assistantTagsStore, assistantTagColorHexes } from "@/lib/stores/assistantTags";
  import { assistantTagsOf } from "@/lib/chat/assistantScope";
  // `isBareDescendantsOf` / `kindUniverseExpr` went with the whole-roster guard
  // (#333): drag no longer inspects the expr's shape at all.
  import { defaultView } from "@/lib/views/evaluateView";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import type { ViewSpec } from "@/lib/types";

  export let entries: AssistantEntrySummary[];
  // The view to render through, computed by App from the pane's selected view
  // (paneViews) — the reactivity bridge for this legacy `$:` pane. The
  // standalone default is the kind's honest default view (ADR-0037 §7 / #333:
  // the roster in merged priority order, tag-parameterized, grouped Active vs
  // Unlisted).
  export let viewSpec: ViewSpec = defaultView("assistant");
  $: schema = $metadataSchemaStore;
  // Active-row highlight + pin-star read from the editor-focus store, not props (#14 Step 2).
  $: focusedDocument = $focusedDocumentStore;
  // Open an assistant in an editor pane (App owns the pane set).
  export let onOpenEntry: (entryId: string) => void;
  // Persist curation. App owns assistantEntries (shared with the chat pane), so
  // it makes the api calls + updates state; this component only turns a drag
  // into the intent. Neither takes a layer — a curation gesture is always the
  // local layer's opinion (#332/#333), and the backend resolves that.
  export let onSetOrder: (orderedIds: string[]) => Promise<void>;
  export let onUnlist: (entryId: string) => Promise<void>;

  // Per-group collapse is ephemeral and owned by ViewNodeList (phase 1; not
  // persisted, same as the Lore pane).

  // Colored tag chips: name → hex from the machine-global assistant-tag
  // vocabulary (#88). Uncolored tags fall back to the neutral chip.
  $: assistantTagColors = assistantTagColorHexes($assistantTagsStore);
  // Reactive (not const) so the function reference changes when colors update,
  // re-rendering the rows' chips.
  $: tagHexFor = (tag: string): string | null => assistantTagColors.get(tag) ?? null;

  // Every NodeList is backed by a view (ADR-0022), and the view is authoritative
  // for its own shape (ADR-0037 §3): the per-layer buckets come from the spec's
  // `group_by: source_layer` level, never synthesized here. Hand the whole view to
  // ViewNodeList, which owns evaluation + the parameter strip (ADR-0032 §D) — so a
  // parameterized assistant view now gets its strip here too, not only in Lore.
  $: view = {
    spec: viewSpec,
    universe: entries,
    schema,
    referenceIndex: $referenceIndexStore,
  };
  // Drag expresses MANUAL order, so it is offered exactly when the view has not
  // taken ordering out of the author's hands: a `sort` other than manual, or a
  // named-handle shape whose members are not one sequence, means the position a
  // drop implies is not the position the list would then show.
  //
  // #333 retired the old whole-roster guard. It existed because a drag on a
  // FILTERED view could persist a partial order and silently demote the hidden
  // ids — which is no longer a hazard now that being outside the view IS being
  // outside the roster: the tag filter narrows what you curate, and `onSetOrder`
  // rebuilds the sequence from the entries the view actually yielded. It also no
  // longer keys off `group_by`, which #333 re-pointed from provenance to
  // curation — the levels are what the drop TARGETS, not a precondition for
  // dragging at all.
  $: canReorder = (viewSpec.sort?.by ?? "manual") === "manual" && !viewSpec.groups?.length;

  // The listed sequence, in the order the roster presents it. `onSetOrder`
  // replaces a layer's whole opinion, so every drop sends the full sequence —
  // an id absent from it is demoted, which is exactly what un-listing means.
  $: listedIds = entries.filter(isListed).map((entry) => entry.id);

  function isListed(entry: AssistantEntrySummary): boolean {
    return entry.computed_metadata?.listed === "listed";
  }

  // A drop on another ROW. Landing among the listed sequence sets priority
  // relative to that row; landing among the unlisted means "not in my roster",
  // for which un-listing is the whole intent — the tail's internal order is a
  // fallback, not something a drag can express.
  async function reorder(
    moved: AssistantEntrySummary,
    target: AssistantEntrySummary,
    position: "before" | "after" | "into",
  ): Promise<void> {
    if (!isListed(target)) {
      if (isListed(moved)) await onUnlist(moved.id);
      return;
    }
    const without = listedIds.filter((id) => id !== moved.id);
    const at = without.indexOf(target.id);
    if (at === -1) return;
    const insertAt = position === "before" ? at : at + 1;
    await onSetOrder([...without.slice(0, insertAt), moved.id, ...without.slice(insertAt)]);
  }

  // A drop on a BUCKET header — the only way to reach an empty group, and the
  // gesture that crosses the Active/Unlisted boundary outright. Landing on
  // Active prepends, matching `create`'s "topmost, therefore the default"
  // (#332): a header sits above its members, so dropping on it reads as "put
  // this at the top", not "append somewhere below".
  async function groupDrop(moved: AssistantEntrySummary, groupKey: string): Promise<void> {
    if (groupKey === "listed") {
      if (isListed(moved) && listedIds[0] === moved.id) return;
      await onSetOrder([moved.id, ...listedIds.filter((id) => id !== moved.id)]);
    } else if (groupKey === "unlisted") {
      if (isListed(moved)) await onUnlist(moved.id);
    }
  }

  // The same two intents as an EXPLICIT per-row control, not a second mechanism:
  // both funnel into `onSetOrder`/`onUnlist` exactly as the drag does. Drag is
  // the fluent path once you know it exists; this is the discoverable one, it is
  // keyboard-reachable, and it works under any view shape — including the states
  // where drag has no target, since a bucket only renders once it has a member.
  //
  // Listing APPENDS rather than prepending: adding something to your roster is
  // not a claim about its priority, and silently promoting it above everything
  // you already arranged would be. Creating an assistant prepends, because that
  // IS a statement of intent about the one you just made (#332).
  async function toggleListed(entry: AssistantEntrySummary): Promise<void> {
    if (isListed(entry)) await onUnlist(entry.id);
    else await onSetOrder([...listedIds.filter((id) => id !== entry.id), entry.id]);
  }


  function assistantSubtitle(entry: AssistantEntrySummary): string {
    const provider = entry.metadata?.ai_provider;
    const model = entry.metadata?.ai_model;
    if (provider && model) return `${provider} · ${model}`;
    if (model) return String(model);
    if (provider) return String(provider);
    return "";
  }
</script>

<ViewNodeList
  {view}
  active={(entry) => focusedDocument?.type === "assistant" && focusedDocument.id === entry.id}
  onClick={(entry) => onOpenEntry(entry.id)}
  onReorder={canReorder ? reorder : undefined}
  onGroupDrop={canReorder ? groupDrop : undefined}
  row={assistantRow}
>
  {#snippet whenEmpty()}
    {#if entries.length === 0}
      <p class="muted">No assistants defined yet. Click + to create one in the machine layer.</p>
    {:else}
      <p class="muted">No assistants match this view.</p>
    {/if}
  {/snippet}
</ViewNodeList>

<!-- Drag routes through ViewNodeList's `onReorder` escape hatch (ADR-0035), the
     one it was designed for: the wrapper owns the gesture + the before/after
     zones and this snippet only reflects them. #333 migrated it off the
     hand-rolled per-layer drag that predated the hatch, which is also what made
     the cross-layer gesture (#332) and the Active/Unlisted crossing reachable —
     both were structurally impossible while the drop handler compared
     `source_layer_id`. -->
{#snippet assistantRow(entry: AssistantEntrySummary, ctx: RowCtx<AssistantEntrySummary>)}
  <NodeRow
    title={entry.title}
    depth={ctx.depth}
    tags={assistantTagsOf(entry)}
    tagColor={tagHexFor}
    active={ctx.active}
    stripeColor={ctx.stripeColor}
    dragging={ctx.dragging}
    dropPosition={ctx.dropPosition}
    onClick={ctx.onClick}
    ondragover={ctx.reorder?.onDragOver}
    ondrop={ctx.reorder?.onDrop}
  >
    {#snippet leading()}
      {#if ctx.collapsible}
        <RowCaret collapsed={ctx.collapsed} toggle={ctx.toggle} />
      {:else if ctx.reorder}
        <span
          class="assistant-drag-handle"
          draggable="true"
          role="button"
          tabindex="-1"
          aria-label="Drag to reorder"
          ondragstart={ctx.reorder.onDragStart}
          ondragend={ctx.reorder.onDragEnd}
        >⋮⋮</span>
      {/if}
    {/snippet}
    {#snippet detailSlot()}
      <small>{assistantSubtitle(entry)}</small>
    {/snippet}
    {#snippet trailing()}
      {#if ctx.collapsible}
        <CountPill count={ctx.childCount} />
      {:else}
        <!-- A WORD, not a glyph, deliberately. The closed lexicon
             (design-language §"Glyph-first affordances") offers `×` for remove —
             but `×` already means *delete* on four other surfaces, and mistaking
             "drop from this project's roster" for "delete a machine-wide
             assistant file" is the expensive misread the same section reserves
             words for. Its own escape clause applies: no self-evident glyph, so
             it takes a word until one is agreed and added to the table. -->
        <button
          class="assistant-curate"
          type="button"
          title={isListed(entry) ? "Remove from this project's roster" : "Add to this project's roster"}
          aria-label={isListed(entry)
            ? `Remove ${entry.title} from this project's roster`
            : `Add ${entry.title} to this project's roster`}
          onmousedown={(event) => event.stopPropagation()}
          onclick={(event) => {
            // The row itself opens the assistant; this must not.
            event.stopPropagation();
            void toggleListed(entry);
          }}
        >{isListed(entry) ? "Un-list" : "List"}</button>
      {/if}
    {/snippet}
  </NodeRow>
{/snippet}

<style>
  /* Drag handle + default marker are rendered into NodeRow's leading /
     trailing snippets, so they carry this component's scope hash. The row
     drag/drop visuals now come from NodeRow's `dragging`/`dropPosition`
     props, so the old `.assistant-row-wrap` wrapper rules are gone. */
  .assistant-drag-handle {
    display: inline-block;
    padding: 0 4px;
    color: var(--text-3);
    cursor: grab;
    user-select: none;
    font-weight: 700;
    letter-spacing: -2px;
  }

  .assistant-drag-handle:active {
    cursor: grabbing;
  }

  /* Recessive until the row is hovered or the control is focused — the roster is
     read far more often than it is curated, and a per-row verb shouting on every
     line would fight the "quiet writing desk". Focus-visible keeps it reachable
     by keyboard without hovering, which is the whole point of adding an explicit
     control alongside the drag. */
  .assistant-curate {
    padding: 0 6px;
    border: 0;
    border-radius: 6px;
    background: none;
    color: var(--text-3);
    font-family: var(--sans);
    font-size: var(--fs-xs);
    cursor: pointer;
    opacity: 0;
    transition: opacity 120ms ease;
  }

  :global(.node-row:hover) .assistant-curate,
  .assistant-curate:focus-visible {
    opacity: 1;
  }

  .assistant-curate:hover {
    color: var(--text);
    background: var(--accent-soft);
  }
</style>
