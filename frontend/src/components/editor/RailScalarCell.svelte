<script module lang="ts">
  // A focus move INSIDE the row, or into ColoredSelect's body-portaled listbox
  // (`.colored-select-popover`), is still "editing"; anything else ends it.
  // Exported so MetadataPanel's document-level outside-click listener shares
  // the same rule (it owns which row is open; this owns what counts as "in it").
  export function leavesRow(rowEl: HTMLElement, target: EventTarget | null): boolean {
    if (!(target instanceof Node)) return false; // null / non-node: don't guess
    if (rowEl.contains(target)) return false;
    return !(target instanceof Element && target.closest(".colored-select-popover"));
  }
</script>

<script lang="ts">
  // The rest/edit cell for a scalar rail row (#1884 slice 4): at rest the value
  // shows through the canonical read-only display behind an inert overlay + a
  // hit button; a click/Enter/Space opens the live control in a `.fr-edit`
  // wrapper that owns Escape and focus-out. This component owns BOTH widgets
  // (status → ColoredSelect, everything else → FieldValueEditor) so a call
  // site only hands over data, not markup twice. MetadataPanel owns WHICH row
  // is open (`openFieldId`) and the document-level outside-click listener.
  // Same overlay-hit-button recipe as RailFlipCandidate (the display widgets
  // are themselves buttons — ColoredSelect, ToggleSwitch — so they can't nest
  // inside another button). The inert display leaves the accessibility tree,
  // so the hit button's name carries the value: "Edit Alias: The Painted".
  import { tick } from "svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import ColoredSelect from "@/components/widgets/ColoredSelect.svelte";
  import { metadataValueDisplayString } from "@/lib/utils/schemaTypeHelpers";
  import type { MetadataFieldDefinition, MetadataValue } from "@/lib/types";

  interface Props {
    field: MetadataFieldDefinition;
    fieldId: string;
    fieldLabel: string;
    /** The value the row displays/edits (MetadataPanel's displayValue, or the status string for `status`). */
    value: MetadataValue;
    empty: boolean;
    editing: boolean;
    /** Single-pick controls return to rest right after the pick. */
    closesOnPick: boolean;
    onOpen: (fieldId: string, rowEl: HTMLElement) => void;
    onClose: (fieldId: string) => void;
    onChange: (value: MetadataValue) => void;
  }

  let { field, fieldId, fieldLabel, value, empty, editing, closesOnPick, onOpen, onClose, onChange }: Props = $props();

  function noop() {}

  // What a screen reader hears for the value the inert display shows: the
  // option's label for a select/status, on/off for a boolean, the display
  // string otherwise.
  const restText = $derived.by(() => {
    if (fieldId === "status" || field.type === "select") {
      const raw = String(value ?? "");
      return field.options.find((o) => o.value === raw)?.label ?? raw;
    }
    if (field.type === "boolean") return value ? "on" : "off";
    return metadataValueDisplayString(value);
  });

  // Returning to rest hands focus back to the hit target after the DOM has
  // flipped, so a keyboard user's place in the rail survives the swap — the
  // live control they were on is gone.
  async function restoreFocus(rowEl: HTMLElement | null) {
    await tick();
    rowEl?.querySelector<HTMLElement>(".fr-rest-hit")?.focus();
  }
  let editEl = $state<HTMLDivElement | null>(null);
  function pick(v: MetadataValue) {
    onChange(v);
    if (closesOnPick) {
      const rowEl = editEl?.closest<HTMLElement>(".field-row") ?? null;
      onClose(fieldId);
      void restoreFocus(rowEl);
    }
  }

  // Escape closes the row AND hands focus back to its rest-state hit target
  // (after the DOM has flipped back to rest), so a keyboard user doesn't lose
  // their place in the rail.
  function closeViaEscape(rowEl: HTMLElement) {
    onClose(fieldId);
    void restoreFocus(rowEl);
  }
</script>

{#if editing}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fr-edit"
    bind:this={editEl}
    onkeydown={(e) => { if (e.key === "Escape") { e.stopPropagation(); closeViaEscape(e.currentTarget.closest(".field-row") as HTMLElement); } }}
    onfocusout={(e) => { if (leavesRow(e.currentTarget.closest(".field-row") as HTMLElement, e.relatedTarget)) onClose(fieldId); }}
  >
    {#if fieldId === "status"}
      <ColoredSelect value={String(value ?? "")} options={field.options} ariaLabel={fieldLabel} placeholder="(no status)" onChange={pick} />
    {:else}
      <FieldValueEditor {field} allowUnset={true} embedded={true} {value} ariaLabel={fieldLabel} onChange={pick} />
    {/if}
  </div>
{:else}
  <div class="fr-rest">
    <div class="fr-rest-value" inert>
      {#if empty}
        <span class="fr-rest-add" aria-hidden="true">+</span>
      {:else if fieldId === "status"}
        <ColoredSelect value={String(value ?? "")} options={field.options} ariaLabel={fieldLabel} placeholder="(no status)" readOnly onChange={noop} />
      {:else}
        <FieldValueEditor {field} readOnly={true} allowUnset={true} embedded={true} {value} ariaLabel={fieldLabel} onChange={noop} />
      {/if}
    </div>
    <button
      type="button"
      class="fr-rest-hit"
      aria-label={empty ? `Set ${fieldLabel}` : `Edit ${fieldLabel}: ${restText}`}
      title={empty ? `Set ${fieldLabel}` : `Edit ${fieldLabel}`}
      onclick={(e) => onOpen(fieldId, e.currentTarget.closest(".field-row") as HTMLElement)}
    ></button>
  </div>
{/if}

<style>
  .fr-edit { display: contents; }

  .fr-rest { position: relative; display: flex; align-items: center; justify-content: flex-end; min-width: 0; min-height: 24px; }
  :global(.field-row.wide) .fr-rest { justify-content: flex-start; }
  .fr-rest-value { pointer-events: none; min-width: 0; display: flex; align-items: center; }
  .fr-rest-add { color: var(--text-3); font-size: var(--fs-lg); line-height: 1; padding: 0 6px; }
  .fr-rest-hit { position: absolute; inset: -2px -4px; width: calc(100% + 8px); background: transparent; border: 0; padding: 0; margin: 0; border-radius: var(--r-sm); cursor: pointer; }
  .fr-rest-hit:hover { background: color-mix(in srgb, var(--inset) 70%, transparent); }
  .fr-rest-hit:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

  /* A long status/select label must show in full at rest — the whole point of
     the "no more `suppo…`" win over the always-editing rail — so the read-only
     ColoredSelect pill can't truncate here the way its editable trigger does
     (#1438's ellipsis is an editing-affordance trade-off, not a read-mode one).
     ColoredSelect itself is untouched; this only lifts the width cap and lets
     the label wrap where the rest cell renders it. */
  .fr-rest-value :global(.colored-select-trigger.read-only) {
    max-width: none;
  }
  .fr-rest-value :global(.colored-select-trigger.read-only .colored-select-label) {
    white-space: normal;
    overflow-wrap: anywhere;
    text-overflow: clip;
  }
</style>
