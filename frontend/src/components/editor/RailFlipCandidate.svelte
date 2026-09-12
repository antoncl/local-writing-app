<script lang="ts">
  // AI lore-proposal review (ADR-0046 slice 3b), extracted from MetadataPanel's
  // flip-candidate render (#1884 slice 4, second follow-up): an atomic
  // structured flip. The proposed value renders read-only (inert, so its own
  // widgets never steal the click or focus), the whole value is one
  // click-to-adopt hit target — the rail twin of "click the dotted wording to
  // adopt it" — and a muted line shows the current value the adopt would
  // replace. The `.flipped` / `.flip-was` row tint (cool pending, warm
  // adopted) stays on the ROW in MetadataPanel; nothing new-coloured here.
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import TagFlipChips, { type TagFlipItem } from "@/components/widgets/TagFlipChips.svelte";
  import type {
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataValue,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";

  interface Props {
    field: MetadataFieldDefinition;
    fieldLabel: string;
    /** The proposed value (MetadataPanel's displayValue for the flipped field). */
    value: MetadataValue;
    /** Adopted state and the toggle — MetadataPanel's compare.resolve. */
    adopted: boolean;
    onToggle: () => void;
    /** The "Current: …" line (already formatted by the caller; "" → "unset"). */
    currentHint: string;
    /** Tag flips render their own chip strip (#1797); the caller decides via isTagFlipField. */
    tagItems: TagFlipItem[] | null;
    // The rest are FieldValueEditor pass-through for the non-tag read-only
    // display — a flipped `entity_ref_list` renders pills that need these to
    // resolve titles, so they're threaded straight through with the same
    // names/defaults as MetadataPanel's own FieldValueEditor calls.
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    excludeId?: string | null;
  }

  let {
    field,
    fieldLabel,
    value,
    adopted,
    onToggle,
    currentHint,
    tagItems,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    implicitContextMatcher = null,
    excludeId = null,
  }: Props = $props();
</script>

<div class="fr-flip">
  <div class="fr-flip-candidate">
    <div class="fr-flip-value" inert>
      {#if tagItems !== null}
        <!-- #1797: the candidate can mix resolved ids with still-unminted
             titles — the generic ReferencePicker path only knows ids, so this
             renders its own chip strip (`TagFlipChips`, round 2 Y7): a known
             tag shows its title, an unresolved one shows as a "new tag"
             candidate (accepting the flip is what mints it, ADR-0082 §2 —
             never here). -->
        <TagFlipChips items={tagItems} ariaLabel={fieldLabel} />
      {:else}
        <FieldValueEditor
          {field}
          readOnly={true}
          allowUnset={true}
          embedded={true}
          {value}
          ariaLabel={fieldLabel}
          {loreEntries}
          {promptEntries}
          {structure}
          {researchStructure}
          {implicitContextMatcher}
          {excludeId}
          onChange={() => {}}
        />
      {/if}
    </div>
    <button
      type="button"
      class="fr-flip-hit"
      aria-pressed={adopted}
      title={adopted
        ? `Adopted — click to keep the current ${fieldLabel}`
        : `Adopt this proposed ${fieldLabel}`}
      aria-label={adopted
        ? `Adopted proposed ${fieldLabel}; click to keep the current value`
        : `Adopt proposed ${fieldLabel}`}
      onclick={onToggle}
    ></button>
  </div>
  <small class="fr-flip-from">Current: {currentHint || "unset"}</small>
</div>

<style>
  /* Interactive lore-proposal flip (ADR-0046 slice 3b). The `.fr-val` tint on
     MetadataPanel's row already carries adopted (warm) vs pending (cool
     dotted); this only lays out the click-to-adopt candidate + the
     current-value hint. */
  .fr-flip {
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: 100%;
  }
  /* The hit target overlays the read-only value so the *value* is what you click
     (the atomic twin of the body flip's "click the wording"). The candidate's
     own widgets are `inert`, so this button is the row's only interactive part. */
  .fr-flip-candidate {
    position: relative;
  }
  .fr-flip-value {
    pointer-events: none;
  }
  .fr-flip-hit {
    position: absolute;
    inset: -1px -4px;
    width: calc(100% + 8px);
    background: transparent;
    border: 0;
    padding: 0;
    margin: 0;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .fr-flip-hit:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .fr-flip-from {
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
</style>
