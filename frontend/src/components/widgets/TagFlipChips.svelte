<script module lang="ts">
  // The AI-proposal review's tag-vocabulary flip candidate (ADR-0082 §2 /
  // #1797), extracted from MetadataPanel's flip-candidate render (round 2,
  // Y7). Two pure helpers a host (MetadataPanel) calls to decide + build
  // props, plus the render itself below.
  //
  // A proposed tag-field value can MIX resolved ids (rendered as their title)
  // with still-unresolved titles (the validator never mints at validation —
  // see `entryProposal.svelte.ts`'s module note): those render as a distinct
  // "new tag" pill BESIDE the title (round 2, Y5) — never a `+ ` text prefix,
  // which would misread for a title that itself starts with a symbol/digit
  // (e.g. a proposed tag literally titled "+1"). Accepting the flip is what
  // mints it (`resolveAdoptedTagFieldValue`, `tagNodes.ts`) — never this
  // render.
  import { createTargetFor } from "@/lib/utils/pickerCreate";
  import type { MetadataFieldDefinition, MetadataSchema, MetadataValue } from "@/lib/types";

  export type TagFlipItem = { key: string; label: string; isNew: boolean };

  /** Whether `field` is the ADR-0082 §2 / #1797 tag-vocabulary carve-out — the
   *  only `entity_ref_list` shape that ever reaches a flip, so its `was`
   *  value gets this chip strip instead of the generic `FieldValueEditor`/
   *  `ReferencePicker` path, which only knows ids. */
  export function isTagFlipField(
    field: MetadataFieldDefinition | undefined,
    schema: MetadataSchema | null,
  ): boolean {
    if (!field || field.type !== "entity_ref_list") return false;
    return createTargetFor(field.picker_config, schema)?.kind === "tag";
  }

  /** A tag-vocabulary flip candidate's value, tagged per item with whether
   *  it's a known id (renders its title) or a still-unresolved title (renders
   *  as a "new tag" candidate). `titleById` is `$tagTitleById` — passed in
   *  rather than read here so the caller's own subscription is what tracks
   *  reactively. */
  export function tagFlipItemsFor(
    value: MetadataValue | undefined,
    titleById: ReadonlyMap<string, string>,
  ): TagFlipItem[] {
    const items = Array.isArray(value) ? value : [];
    return items.map((item) => {
      const id = String(item);
      const known = titleById.get(id);
      return known !== undefined
        ? { key: id, label: known, isNew: false }
        : { key: id, label: id, isNew: true };
    });
  }
</script>

<script lang="ts">
  interface Props {
    items: TagFlipItem[];
    ariaLabel?: string;
  }

  let { items, ariaLabel = "" }: Props = $props();
</script>

<div class="tag-flip-chips" aria-label={ariaLabel}>
  {#each items as item (item.key)}
    {#if item.isNew}
      <span
        class="tag-flip-chip tag-flip-chip-new"
        data-testid="flip-new-tag"
        title="New tag — created only if this flip is adopted"
      >
        {item.label}<span class="tag-flip-new-pill">new</span>
      </span>
    {:else}
      <span class="tag-flip-chip" data-testid="flip-tag-chip" title={item.label}>{item.label}</span>
    {/if}
  {/each}
</div>

<style>
  .tag-flip-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  /* Mirrors FieldValueEditor's `.multi-select-chip` shape/tokens — a static
     pill (no click affordance of its own; the flip row's own hit-target
     overlay is what's interactive). */
  .tag-flip-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 9px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .tag-flip-chip-new {
    border-style: dashed;
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent-emphasis);
  }
  /* The "will be created" marker (Y5) — a separate solid pill, never folded
     into the title text, so a title that itself starts with a symbol/digit
     can't be misread as part of the marker. `#fff` is the sanctioned
     ink-on-accent-solid exception (design-language.md §5). */
  .tag-flip-new-pill {
    padding: 1px 5px;
    border-radius: 999px;
    background: var(--accent);
    color: #fff;
    font-size: var(--fs-xs);
    font-weight: 700;
    line-height: 1.4;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
</style>
