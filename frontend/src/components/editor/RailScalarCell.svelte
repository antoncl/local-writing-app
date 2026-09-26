<script module lang="ts">
  // A focus move INSIDE the row, or into a body-portaled surface the row's
  // control raised — ColoredSelect's listbox (`.colored-select-popover`), the
  // implicit-context hover card over a long-text field's lore-name match
  // (`.implicit-context-popup`, #1923) — is still "editing"; anything else ends it.
  // Exported so MetadataPanel's document-level outside-click listener shares
  // the same rule (it owns which row is open; this owns what counts as "in it").
  export function leavesRow(rowEl: HTMLElement, target: EventTarget | null): boolean {
    if (!(target instanceof Node)) return false; // null / non-node: don't guess
    if (rowEl.contains(target)) return false;
    // `.peek-card` (#2011): a reference pill's hover/focus peek card is body-
    // portaled like the other two — its own Swap picker can be mid-use
    // without the row it floats off reading as "left". `.ctx-menu` (#2058):
    // the open face of a single reference is a NodePicker, whose dropdown is
    // body-portaled the same way.
    return !(
      target instanceof Element && target.closest(".colored-select-popover, .implicit-context-popup, .peek-card, .ctx-menu")
    );
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
  import PeekCard from "@/components/widgets/PeekCard.svelte";
  import { peekAnchor } from "@/lib/actions/peekAnchor";
  import { buildPeekTarget, type PeekableRef } from "@/lib/utils/peekTarget";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { metadataValueDisplayString } from "@/lib/utils/schemaTypeHelpers";
  import type { NavigateTarget } from "@/lib/referenceTypes";
  import type {
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataValue,
    NodePickerEmptyHint,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";

  interface Props {
    field: MetadataFieldDefinition;
    fieldId: string;
    fieldLabel: string;
    /** The value the row displays/edits (MetadataPanel's displayValue, or the status string for `status`). */
    value: MetadataValue;
    /** ADR-0095 §8 decision 5: at a scrub stop, a text field's edit control
     *  opens on a DIFFERENT value than its rest display — the set's own row
     *  value, not the effective one (§8: "the DISPLAY stays the effective
     *  value, but its EDIT control opens on the set's own row value"). Defaults
     *  to `value` so every other row's rest/edit stay the one value they've
     *  always been. */
    editValue?: MetadataValue;
    empty: boolean;
    editing: boolean;
    /** Single-pick controls return to rest right after the pick. */
    closesOnPick: boolean;
    onOpen: (fieldId: string, rowEl: HTMLElement) => void;
    onClose: (fieldId: string) => void;
    onChange: (value: MetadataValue) => void;
    // #2058, a single `entity_ref`: the host's id → node walk for the rest
    // face's name and peek; the picker's rosters for the open face; where the
    // peek card's Open goes.
    resolveRef?: (id: string) => PeekableRef | null;
    refDeps?: {
      loreEntries?: LoreEntrySummary[];
      promptEntries?: PromptEntrySummary[];
      structure?: StructureDocument | null;
      researchStructure?: StructureDocument | null;
      excludeId?: string | null;
      createLayerId?: string | null;
    };
    onNavigate?: (target: NavigateTarget) => void;
    // #2215: the picker's field-worded empty state (RailFieldRow is always a
    // metadata-field host, never a prompt input) — undefined keeps the
    // picker's original copy.
    emptyHint?: NodePickerEmptyHint | null;
  }

  let {
    field, fieldId, fieldLabel, value, editValue = undefined, empty, editing, closesOnPick, onOpen, onClose, onChange,
    resolveRef = undefined, refDeps = {}, onNavigate = undefined, emptyHint = null,
  }: Props = $props();

  const liveEditValue = $derived(editValue ?? value);

  // --- A single reference (#2058): one line at rest, the picker when open ---
  // The rest face is the target's resolved title (the stored id when the host
  // threads no resolver or the id no longer resolves), and the hit target is
  // also the peek anchor: hover/focus peeks the target (B2, #2011, with its
  // Open), click opens the picker in place like every other scalar row.
  const singleRef = $derived(field.type === "entity_ref");
  const refId = $derived(singleRef && typeof value === "string" ? value : "");
  const refTarget = $derived<PeekableRef | null>(refId ? (resolveRef?.(refId) ?? null) : null);
  const refTitle = $derived(refTarget?.title ?? refId);
  let peekAt = $state<HTMLElement | null>(null);
  const peekModel = $derived(
    peekAt && refTarget
      ? buildPeekTarget(refTarget, $metadataSchemaStore, { resolveRef: resolveRef ?? (() => null) })
      : null,
  );
  function navigateToRef() {
    if (refTarget) onNavigate?.({ id: refTarget.id, kind: refTarget.kind, entryType: refTarget.entry_type });
  }

  function noop() {}

  // What a screen reader hears for the value the inert display shows: the
  // option's label for a select/status, on/off for a boolean, the display
  // string otherwise.
  const restText = $derived.by(() => {
    if (singleRef) return refTitle;
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
    {:else if singleRef}
      <!-- The picker (pill + swap / add trigger), only while open (#2058). The
           row drives the picker's pill fold and a single reference has nothing
           to fold, so it is always expanded (uncontrolled, the #1216 caret
           would start it folded and hide the one pill). -->
      <FieldValueEditor
        {field}
        allowUnset={true}
        embedded={true}
        controlled={true}
        expanded={true}
        {value}
        ariaLabel={fieldLabel}
        loreEntries={refDeps.loreEntries}
        promptEntries={refDeps.promptEntries}
        structure={refDeps.structure}
        researchStructure={refDeps.researchStructure}
        excludeId={refDeps.excludeId}
        createLayerId={refDeps.createLayerId}
        onChange={pick}
        onNavigate={(target) => onNavigate?.(target)}
        {emptyHint}
      />
    {:else}
      <FieldValueEditor {field} allowUnset={true} embedded={true} value={liveEditValue} ariaLabel={fieldLabel} onChange={pick} />
    {/if}
  </div>
{:else}
  <div class="fr-rest">
    <div class="fr-rest-value" inert>
      {#if empty}
        <span class="fr-rest-add" aria-hidden="true">+</span>
      {:else if singleRef}
        <span class="fr-ref-name" data-testid="rail-ref-name">{refTitle}</span>
      {:else if fieldId === "status"}
        <ColoredSelect value={String(value ?? "")} options={field.options} ariaLabel={fieldLabel} placeholder="(no status)" readOnly onChange={noop} />
      {:else}
        <FieldValueEditor {field} readOnly={true} allowUnset={true} embedded={true} {value} ariaLabel={fieldLabel} onChange={noop} />
      {/if}
    </div>
    {#if singleRef && refTarget}
      <!-- The same hit target, plus the peek anchor (#2058): `use:` cannot be
           conditional, so the anchored variant is its own element. Opening the
           row unmounts this button, and the action's teardown does not close
           a card it opened — so the click closes the peek itself, or the card
           would float over the picker off a detached anchor. -->
      <button
        type="button"
        class="fr-rest-hit"
        aria-label={`Edit ${fieldLabel}: ${restText}`}
        title={field.description || `Edit ${fieldLabel}`}
        onclick={(e) => { peekAt = null; onOpen(fieldId, e.currentTarget.closest(".field-row") as HTMLElement); }}
        use:peekAnchor={{ onOpen: (anchor) => { peekAt = anchor; }, onClose: () => { peekAt = null; } }}
      ></button>
    {:else}
      <button
        type="button"
        class="fr-rest-hit"
        aria-label={empty ? `Set ${fieldLabel}` : `Edit ${fieldLabel}: ${restText}`}
        title={field.description || (empty ? `Set ${fieldLabel}` : `Edit ${fieldLabel}`)}
        onclick={(e) => onOpen(fieldId, e.currentTarget.closest(".field-row") as HTMLElement)}
      ></button>
    {/if}
  </div>
{/if}

{#if peekAt && peekModel}
  <PeekCard model={peekModel} anchor={peekAt} {field} on={{ open: navigateToRef, close: () => { peekAt = null; } }} />
{/if}

<style>
  .fr-edit { display: contents; }

  .fr-rest { position: relative; display: flex; align-items: center; justify-content: flex-end; min-width: 0; min-height: 24px; }
  :global(.field-row.wide) .fr-rest { justify-content: flex-start; }
  .fr-rest-value { pointer-events: none; min-width: 0; display: flex; align-items: center; }
  .fr-rest-add { color: var(--text-3); font-size: var(--fs-lg); line-height: 1; padding: 0 6px; }
  /* A single reference at rest (#2058): the name as a value, one line; a long
     one clips, the peek card carries it in full. */
  .fr-ref-name { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: var(--fs-md); color: var(--text); }
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
