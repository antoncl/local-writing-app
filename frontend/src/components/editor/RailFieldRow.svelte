<script module lang="ts">
  // One metadata rail field row (#2022 split of MetadataPanel — the
  // `{#snippet fieldRow}` markup, moved verbatim). MetadataPanel still decides
  // WHICH fields render a row (`rendersRow`) and owns all cross-field state
  // (open row, sections, the empty fold); this component only renders one row
  // from a fully-resolved `RailRowModel` (`fieldRowModel.ts`) plus the widget
  // pass-throughs (`RailRowDeps`) and the panel's write-back callbacks
  // (`RailRowCallbacks`).
  import type { LoreEntrySummary, MetadataValue, NavigateTarget, PromptEntrySummary, StructureDocument } from "@/lib/types";

  import type { PeekableRef } from "@/lib/utils/peekTarget";
  export type RailRowDeps = {
    readOnly: boolean;
    // #2058: the host's id → node walk (`buildRefResolver`), so a single
    // reference's rest face can show the name and peek the target. Absent,
    // the rest face shows the stored id.
    resolveRef?: (id: string) => PeekableRef | null;
    createLayerId?: string | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    excludeId?: string | null;
  };

  export type RailRowCallbacks = {
    open: (fieldId: string, rowEl: HTMLElement) => void;
    close: (fieldId: string) => void;
    clear: (fieldId: string) => void;
    write: (fieldId: string, value: MetadataValue) => void;
    toggleExpanded: (fieldId: string) => void;
    statusChange: (value: string) => void;
    resetField: (fieldId: string) => void;
    navigate: (payload: NavigateTarget) => void;
    toggleFlip: (fieldId: string) => void;
    // #2009: a long_text index row's hit — scroll to (and focus) its body section.
    goToSection: (fieldId: string) => void;
    // #2010: an entity_ref_list index row's hit — switch the body tab strip to
    // this field's list tab.
    goToList: (fieldId: string) => void;
  };
</script>

<script lang="ts">
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import RailScalarCell from "@/components/editor/RailScalarCell.svelte";
  import RailFlipCandidate from "@/components/editor/RailFlipCandidate.svelte";
  import RailTagLine from "@/components/editor/RailTagLine.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import ColoredSelect from "@/components/widgets/ColoredSelect.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import type { RailRowModel } from "@/lib/rail/fieldRowModel";

  interface Props {
    model: RailRowModel;
    deps: RailRowDeps;
    on: RailRowCallbacks;
  }

  let { model, deps, on }: Props = $props();
</script>

<!-- Intrinsic identity fields (id/title/entry_type, #116) are surfaced
     via dedicated rail controls (the type select above, the shell title
     header) and stored off `metadata`, so skip them in the generic
     value-editor loop — otherwise they'd render as empty rows. -->
<!-- Intrinsic identity fields (id/title/entry_type) get dedicated controls
     and are normally skipped here — EXCEPT when one is an active proposal
     flip (a `title` rename, ADR-0046 3b): then it renders as a rail flip so
     the author can adopt it, and adoption routes back to the shell state. -->
<!-- A computed field with no value renders no row at all (#1684): the row
     would be a padlock beside nothing (a scene's cost before any
     invocation, a non-runnable prompt's `runnable`), which is rail noise,
     not information. The field stays in the schema/type editor. -->
<div class="field-row" class:color-row={model.colorRow} class:wide={model.wide} class:inherited={model.inherited} class:layer-inherited={model.layerInherited || model.cascadeInherited} class:mutated={model.mutated} class:overridden={model.overridden} class:flipped={model.flipped} class:flip-was={model.flipWas} class:empty={model.empty} class:scalar={model.scalar} class:editing={model.editing}>
  <!-- Disclosure gutter — reserved so the field glyph lines up with the
       collapsible sections' glyph column (RailSectionHeader): caret ·
       glyph on every rail line (#1438). Reference fields no longer
       collapse to their own list (#1732 — they render inline pills); the
       gutter carries the caret for a folding LIST field instead (#1884
       slice 2), empty for every other row. -->
  {#if model.foldableList}
    <button
      type="button"
      class="fr-disc fr-disc-toggle"
      aria-expanded={model.fieldExpanded}
      aria-label={model.fieldExpanded ? `Show fewer ${model.fieldLabel}` : `Show all ${model.fieldLabel}`}
      title={model.fieldExpanded ? "Show fewer" : "Show all"}
      onclick={() => on.toggleExpanded(model.fieldId)}
    ><GroupCaret size="xs" collapsed={!model.fieldExpanded} /></button>
  {:else}
    <span class="fr-disc" aria-hidden="true"></span>
  {/if}
  {#if model.ownClearable}
    <!-- Clear-to-default (#522): the intra-project twin of #517's reset.
         #517 hangs its "Reset to <source>" gesture off the `ti-versions`
         override-delta glyph — which only exists on an overridden field.
         An intra-project node has no such glyph, but every field carries
         its own default glyph (the type/field icon, rendered on every
         row), so THAT glyph becomes the affordance here: hover it to
         reveal a "Reset to default" chip, click it to delete the sparse
         metadata key and revert the field to its default / unset. A cascade
         OVERRIDE never reaches this branch (it carries the ti-versions mark
         in the value cell, #1734), so a cascade field here is one set with
         nothing above it — "default", not "inherited". -->
    <button
      type="button"
      class="fr-icon fr-icon-reset"
      title={model.defaultHint
        ? `Set here — reset ${model.fieldLabel} to its default (${model.defaultHint})`
        : `Set here — clear ${model.fieldLabel} (revert to default)`}
      aria-label={`Reset ${model.fieldLabel} to default`}
      onclick={() => on.clear(model.fieldId)}
    >
      <i class={model.iconClass} aria-hidden="true"></i>
      <span class="fr-reset-chip">Reset to default</span>
    </button>
  {:else}
    <span class="fr-icon"><i class={model.iconClass} aria-hidden="true"></i></span>
  {/if}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <!-- The description is the tooltip of the name AND of the at-rest
       value control (RailScalarCell's hit target) — #1900 — not of the
       whole row, which would hover it over a long_text's prose. -->
  <span
    class="fr-name"
    title={model.description || undefined}
    onclick={(e) => { if (model.scalar && !model.editing) on.open(model.fieldId, e.currentTarget.closest(".field-row") as HTMLElement); }}
  >{model.fieldLabel}</span>
  <div class="fr-val" title={model.inheritedTooltip}>
    {#if model.overridden}
      {#if model.canResetOverride}
        <!-- The `ti-versions` mark PR 2 ships, made interactive (#517):
             the primary provenance signal AND the reset control. Its
             hover/focus reveals a "Reset to <source>" chip above it. -->
        <button
          type="button"
          class="fr-override-marker fr-reset"
          title={`Overridden here — reset this value to ${model.sourceLayerLabel ?? "inherited canon"}`}
          aria-label={`Reset ${model.fieldLabel} to ${model.sourceLayerLabel ?? "the inherited value"}`}
          onclick={() => on.resetField(model.fieldId)}
        >
          <i class="ti ti-versions" aria-hidden="true"></i>
          <span class="fr-reset-chip"><i class="ti ti-arrow-back-up" aria-hidden="true"></i>Reset to {model.sourceLayerLabel ?? "inherited"}</span>
        </button>
      {:else}
        <i class="ti ti-versions fr-override-marker" title={`Overridden here — this value comes from a layer override in this project, not from ${model.sourceLayerLabel ?? "inherited canon"}`}></i>
      {/if}
    {:else if model.cascadeOverridden}
      <!-- ADR-0079 override (#1734): this scene sets a cascade value that
           SHADOWS the one it would inherit. Same ti-versions mark + reset
           as the layer override (#517), but the reset drops the own value
           so the field inherits again (clearField), and it names the
           ancestor it would fall back to. -->
      {#if model.canResetCascade}
        <button
          type="button"
          class="fr-override-marker fr-reset"
          title={`Overridden here — reset ${model.fieldLabel} to the value inherited from ${model.cascadeOverrideSourceLabel}`}
          aria-label={`Reset ${model.fieldLabel} to the value inherited from ${model.cascadeOverrideSourceLabel}`}
          onclick={() => on.clear(model.fieldId)}
        >
          <i class="ti ti-versions" aria-hidden="true"></i>
          <span class="fr-reset-chip"><i class="ti ti-arrow-back-up" aria-hidden="true"></i>Reset to inherited</span>
        </button>
      {:else}
        <i class="ti ti-versions fr-override-marker" title={`Overridden here — differs from the value inherited from ${model.cascadeOverrideSourceLabel}`}></i>
      {/if}
    {/if}
    {#if model.flipResolve}
      <RailFlipCandidate
        field={model.field} fieldLabel={model.fieldLabel}
        value={model.value}
        adopted={model.flipAdopted}
        onToggle={() => on.toggleFlip(model.fieldId)}
        currentHint={model.flipCurrentHint}
        tagItems={model.tagFlipItems}
        loreEntries={deps.loreEntries}
        promptEntries={deps.promptEntries}
        structure={deps.structure}
        researchStructure={deps.researchStructure}
        implicitContextMatcher={deps.implicitContextMatcher}
        excludeId={deps.excludeId}
      />
    {:else if model.isStatus}
      <!-- status is stored off `metadata` and edited via onStatusChange. -->
      {#if !model.scalar}
        <ColoredSelect
          value={model.statusValue}
          options={model.field.options}
          ariaLabel={model.fieldLabel}
          placeholder="(no status)"
          readOnly={deps.readOnly}
          onChange={(value) => on.statusChange(value)}
        />
      {:else}
        <RailScalarCell
          field={model.field}
          fieldId={model.fieldId}
          fieldLabel={model.fieldLabel}
          value={model.statusValue}
          empty={model.empty}
          editing={model.editing}
          closesOnPick={model.closesOnPick}
          onOpen={on.open}
          onClose={on.close}
          onChange={(v) => on.statusChange(String(v))}
        />
      {/if}
    {:else if model.isComputed}
      <!-- Read-only derived value, shown by its declared option label
           when the field has one (a select-valued computed field like
           `runnable` stores "runnable", displays "Runnable" — #1684).
           The text breaks on any character so a long, space-less
           computed value (a filesystem `path`, #417 s3) wraps within
           the rail instead of overflowing, and the full value sits on
           the title tooltip. -->
      <span class="fr-computed" title={model.computedText}><span class="fr-computed-text">{model.computedText}</span><i class="ti ti-lock" aria-hidden="true"></i></span>
    {:else if model.colorRow}
      <!-- Color renders at its display_order slot like any field
           (ADR-0029 §G) — the hoist is gone. When unset, the swatch shows
           the RESOLVED inherited color (type → parent → kind default) as a
           dashed placeholder, so the actual colour is visible; the label
           only has to say it's inherited (#1440). -->
      <SwatchPicker
        value={model.colorValue}
        placeholderHex={model.colorPlaceholderHex}
        readOnly={deps.readOnly}
        onChange={(id) => (id ? on.write(model.fieldId, id) : on.clear(model.fieldId))}
      />
      {#if model.colorUnset}
        <small class="muted">inherited</small>
      {/if}
    {:else if model.isTagList}
      <!-- A tags field (#2007): ADR-0082's single-kind-`tag` carve-out renders as one mono line, never pills. -->
      <RailTagLine
        field={model.field}
        fieldId={model.fieldId}
        fieldLabel={model.fieldLabel}
        value={model.value}
        readOnly={model.fieldReadOnly}
        editing={model.editing}
        onOpen={on.open}
        onClose={on.close}
        createLayerId={deps.createLayerId}
        onChange={(ids) => on.write(model.fieldId, ids)}
        onNavigate={(payload) => on.navigate(payload)}
        deps={{ loreEntries: deps.loreEntries, promptEntries: deps.promptEntries, structure: deps.structure }}
      />
    {:else if model.sectionIndex}
      <!-- #2009: the field's editor lives in a body section instead of the
           rail — this row is an index into it. Word count over the current
           value; an empty field reads "empty" (the row itself still carries
           `.empty`, so #2006's fold still folds it). Never `.wide` — an index
           line is one row like any scalar. -->
      <button
        type="button"
        class="fr-rest-hit fr-section-index"
        aria-label={`Go to ${model.fieldLabel}`}
        onclick={() => on.goToSection(model.fieldId)}
      >{model.empty ? "empty" : model.sectionSummary ?? (model.wordCount === 1 ? "1 word" : `${model.wordCount} words`)}</button>
    {:else if model.listIndex}
      <!-- #2010: the field's editor lives in a body tab instead of the rail —
           this row is an index into it. Per-type summary; an empty list reads
           "empty" (the row itself still carries `.empty`, so #2006's fold
           still folds it). Never `.wide` — an index line is one row like any
           scalar. Same `fr-rest-hit fr-section-index` chrome as the #2009
           long_text index row — both are "this field's editor lives
           elsewhere" jumps and read as one vocabulary. -->
      <button
        type="button"
        class="fr-rest-hit fr-section-index"
        aria-label={`Open ${model.fieldLabel}`}
        onclick={() => on.goToList(model.fieldId)}
      >{model.empty ? "empty" : model.listSummary}</button>
    {:else if !model.scalar}
      <FieldValueEditor
        field={model.field}
        readOnly={model.fieldReadOnly}
        allowUnset={true}
        embedded={true}
        controlled={model.isRef}
        expanded={model.fieldExpanded}
        onToggleExpanded={() => on.toggleExpanded(model.fieldId)}
        value={model.value}
        ariaLabel={model.fieldLabel}
        loreEntries={deps.loreEntries}
        promptEntries={deps.promptEntries}
        structure={deps.structure}
        researchStructure={deps.researchStructure}
        implicitContextMatcher={deps.implicitContextMatcher}
        excludeId={deps.excludeId}
        createLayerId={deps.createLayerId}
        onChange={(v) => on.write(model.fieldId, v)}
        onNavigate={(payload) => on.navigate(payload)}
      />
    {:else}
      <RailScalarCell
        field={model.field}
        fieldId={model.fieldId}
        fieldLabel={model.fieldLabel}
        value={model.value}
        empty={model.empty}
        editing={model.editing}
        closesOnPick={model.closesOnPick}
        onOpen={on.open}
        onClose={on.close}
        onChange={(v) => on.write(model.fieldId, v)}
        resolveRef={deps.resolveRef}
        refDeps={deps}
        onNavigate={(target) => on.navigate(target)}
      />
    {/if}
    {#if model.mutated}
      <!-- Mutation mark (#64) trails the value, co-located with the
           `ti-versions` override mark that leads it, so a field that is
           both overridden and mutated reads `[versions] Captain ⤳` on
           one line — design-language.md §marks, not split across cells (#492). -->
      <span class="fr-mutated-marker" title="Changed by here">⤳</span>
    {/if}
    {#if model.showTempNote}
      {#if model.tempClearedForModel}
        <!-- #1579: a stored temperature was just discarded because the
             selected model dropped sampling — announce it, so the value
             isn't stripped silently. -->
        <small class="fr-temp-note fr-temp-cleared" role="status">
          <i class="ti ti-alert-triangle" aria-hidden="true"></i>
          Temperature cleared — {model.tempClearedForModel} doesn't support it.
        </small>
      {:else}
        <!-- The selected model dropped sampling (Anthropic Opus 4.7+/5,
             incl. via OpenRouter): the field renders read-only above and
             this quiet note says why, so the empty control doesn't read as
             a bug (#1554). -->
        <small class="muted fr-temp-note">Not supported by the model</small>
      {/if}
    {/if}
  </div>
</div>

<style>
  /* Field row: ‹disclosure gutter› · glyph · name · value — the rail's one row
     grammar (#1438), shared with RailSectionHeader so glyphs align vertically. */
  .field-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 12px;
  }
  .field-row.wide {
    flex-wrap: wrap;
  }
  /* Empty disclosure gutter — same width as GroupCaret (22px) so a field row's
     glyph sits directly under a section header's glyph. */
  .fr-disc {
    flex: none;
    width: 22px;
  }
  /* Folding-list caret (#1884 slice 2) — same 22px slot as the empty `.fr-disc`.
     It is only a control when there is something to unfold or fold back: the
     picker renders its `+N` chip exactly when pills are hidden, so the caret
     shows for a row that HAS the chip, or one already expanded (to fold it
     back). Otherwise it stays in the slot but invisible — out of the tab order
     and the a11y tree, not a no-op button announcing "Show all". */
  .fr-disc-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: none;
    background: none;
    color: var(--text-3);
    cursor: pointer;
    visibility: hidden;
  }
  /* The chip is ReferencePicker's, so it needs `:global` inside `:has()` —
     a scoped `.ref-pill-more` would carry this component's hash and never match. */
  .field-row:has(:global(.ref-pill-more)) .fr-disc-toggle,
  .fr-disc-toggle[aria-expanded="true"] {
    visibility: visible;
  }
  .fr-disc-toggle:hover {
    color: var(--text);
  }
  .fr-disc-toggle:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .fr-icon {
    flex: none;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-2);
    font-size: var(--fs-md);
  }
  .fr-name {
    flex: 0 1 auto;
    font-size: var(--fs-md);
    font-weight: var(--w-medium);
    color: var(--text);
    min-width: 78px;
  }
  .fr-val {
    margin-left: auto;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  /* Wide fields: the control drops to its own full-width line. */
  .field-row.wide .fr-val {
    flex-basis: 100%;
    margin-left: 0;
    margin-top: 2px;
    justify-content: stretch;
  }
  .field-row.wide .fr-val > :global(*) {
    flex: 1 1 auto;
    min-width: 0;
  }

  /* The "Not supported by the model" note (#1554) breaks to its own line under
     the (read-only) Temperature control, right-aligned with the value column. */
  .fr-temp-note {
    flex-basis: 100%;
    text-align: right;
  }
  .field-row.wide .fr-val > .fr-temp-note {
    flex: 0 0 100%;
  }
  /* #1579: the model discarded a stored temperature — a real notice (a value was
     removed), so it's not muted; a small alert glyph leads it, right-aligned like
     the quiet note it replaces. */
  .fr-temp-cleared {
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    gap: 4px;
    color: var(--text-2);
  }
  .fr-temp-cleared > .ti {
    color: var(--danger);
  }

  /* Inherited fields read a touch quieter — still fully editable. */
  .field-row.inherited .fr-icon,
  .field-row.inherited .fr-name {
    opacity: 0.62;
  }

  /* Empty at rest (#1884 slice 3): the row is still there — a schema field is a
     prompt to fill — but its label and glyph step back to the tertiary ink.
     Declared before the mutated/layer-inherited/flipped rules below, at equal
     selector specificity, so an active mark on an empty field still wins the
     cascade and reads as a mark, not as empty. */
  .field-row.empty .fr-name,
  .field-row.empty .fr-icon {
    color: var(--text-3);
  }
  /* Inherited AND empty takes the tertiary ink alone — stacking the 62% dim
     above on top of it would fade the label past legibility. */
  .field-row.inherited.empty .fr-name,
  .field-row.inherited.empty .fr-icon {
    opacity: 1;
  }

  /* Mutated-by-here rows (#64): the in-prose mutation pill's vocabulary —
     violet + a miniaturized ⤳. Trails the value, co-located with the
     `ti-versions` override mark that leads it (#492); the `.fr-val` flex gap
     spaces it, so no own margin. Unchanged rows render plain read-only. */
  .fr-mutated-marker {
    flex: 0 0 auto;
    color: var(--mutation-color);
    font-weight: 700;
    font-size: var(--fs-sm);
  }
  /* Keep the trailing mark on the value's line in wide fields — the value
     widget flexes to fill, the mark stays its own size (twin of the
     override-marker rule below). */
  .field-row.wide .fr-val > .fr-mutated-marker {
    flex: 0 0 auto;
  }

  /* Layer-override mark (#314): the hierarchy twin of `⤳`, leading the value.
     On the `--star` provenance axis — the same vocabulary as the level pill,
     ancestor banner and rail-provenance block — because it says where this
     value came from. `flex: 0 0 auto` keeps the glyph from being stretched by
     the wide-field `.fr-val > *` rule below. */
  .fr-override-marker {
    flex: 0 0 auto;
    color: var(--star);
    font-size: var(--fs-md);
    line-height: 1;
  }
  /* Clear-to-inherit (#517 / §8): the mark doubles as the reset control. As a
     button it sheds the browser chrome and anchors the "Reset to <source>" chip;
     the chip floats above the mark on hover/focus (keyboard-reachable — the
     button itself is the tab stop, so the reset is never hover-only). */
  button.fr-override-marker {
    display: inline-flex;
    align-items: center;
    position: relative;
    padding: 0;
    border: 0;
    background: none;
    cursor: pointer;
  }
  button.fr-override-marker:focus-visible {
    outline: 2px solid var(--star);
    outline-offset: 2px;
    border-radius: var(--r-sm);
  }
  .fr-reset-chip {
    display: none;
    position: absolute;
    bottom: 100%;
    left: 0;
    margin-bottom: 3px;
    align-items: center;
    gap: 3px;
    padding: 2px 8px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    box-shadow: var(--elev-2);
    border-radius: var(--r-md);
    font-size: var(--fs-xs);
    color: var(--star);
    white-space: nowrap;
    z-index: 6;
  }
  button.fr-override-marker:hover .fr-reset-chip,
  button.fr-override-marker:focus-visible .fr-reset-chip {
    display: inline-flex;
  }
  .field-row.wide .fr-val > .fr-override-marker {
    flex: 0 0 auto;
  }

  /* Clear-to-default (#522): the field's own default glyph (the `.fr-icon` box,
     rendered on every row) becomes the reset control on a locally-owned field
     that carries a value — the intra-project twin of #517's override-glyph
     reset. Neutral tint, NOT the `--star` provenance axis: reverting to a type
     default is not a provenance fact, so it must not borrow the inherited/
     override vocabulary. Hover/focus reveals the "Reset to default" chip; the
     button is the tab stop, so the reset is keyboard-reachable, not hover-only. */
  button.fr-icon-reset {
    position: relative;
    cursor: pointer;
    padding: 0;
    font-size: var(--fs-md);
    transition: border-color 120ms ease, color 120ms ease;
  }
  button.fr-icon-reset:hover,
  button.fr-icon-reset:focus-visible {
    border-color: var(--accent);
    color: var(--accent-strong);
  }
  button.fr-icon-reset:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  button.fr-icon-reset .fr-reset-chip {
    color: var(--text-2);
  }
  button.fr-icon-reset:hover .fr-reset-chip,
  button.fr-icon-reset:focus-visible .fr-reset-chip {
    display: inline-flex;
  }

  /* Layer-inherited fields (#517 / §8): the value flows from an ancestor, so it
     reads gently muted — a text dim only (no box, so dark mode isn't overpowered)
     with the source in the row tooltip. Overridden rows keep the default full
     strength ("live"), so the two read as one visual language against each other.
     Distinct from `.field-row.inherited` above, which marks *schema* field
     membership, not layer provenance — the two may co-occur. */
  .field-row.layer-inherited .fr-name {
    color: var(--text-3);
  }
  .field-row.layer-inherited .fr-val {
    cursor: help;
  }
  .field-row.layer-inherited .fr-val :global(input),
  .field-row.layer-inherited .fr-val :global(select),
  .field-row.layer-inherited .fr-val :global(.fv-static),
  .field-row.layer-inherited .fr-val :global(.fv-static-longtext) {
    color: var(--text-2);
  }
  .field-row.mutated .fr-name {
    color: var(--mutation-color);
    font-weight: 600;
  }
  .field-row.mutated .fr-val :global(.fv-static),
  .field-row.mutated .fr-val :global(.fv-static-longtext) {
    color: var(--mutation-color);
  }
  /* Chips in a mutated row pick up the pill's tint recipe (14% bg / 42% border). */
  .field-row.mutated .fr-val :global(.multi-select-chip.static) {
    background: color-mix(in srgb, var(--mutation-color) 14%, transparent);
    border-color: color-mix(in srgb, var(--mutation-color) 42%, transparent);
    color: var(--mutation-color);
  }
  /* Tag chips carry the same tint. The fill/border live on the luggage-tag SVG
     path, but the chip exposes them as `--tag-fill` / `--tag-stroke` custom props
     (#705), so set those on the chip's public surface instead of reaching into
     its private path. `:not(.pending)` leaves an uncreated tag's dashed "will be
     created" outline alone. */
  .field-row.mutated .fr-val :global(.tag-chip:not(.pending)) {
    color: var(--mutation-color);
    --tag-fill: color-mix(in srgb, var(--mutation-color) 14%, transparent);
    --tag-stroke: color-mix(in srgb, var(--mutation-color) 42%, transparent);
  }

  /* Snapshot-compare rows (#409): the SAME two colours as the body, because the
     colour means temporal provenance everywhere and location carries the
     subject — no second vocabulary. Warm = the value in the scene now, cool =
     the value in the snapshot. No glyph, ever (§J).

     The pair is written as two rules on one class rather than one rule with a
     variable, so a state class cannot silently outrank an identity class for one
     property — which is exactly how slice 1 shipped the Live notch painted in
     the snapshot's colour. */
  .field-row.flipped .fr-name {
    color: var(--diff-now);
    font-weight: 600;
  }
  .field-row.flipped.flip-was .fr-name {
    color: var(--diff-was);
  }
  /* On `.fr-val` itself, not on the inner value widgets. A changed field can
     render as a plain static, a chip, a swatch or a select, and marking only
     some of them left the rail carrying its difference on the LABEL's hue
     alone — the hue-only failure §H rules out, reintroduced in the one place
     the body had just fixed it. */
  .field-row.flipped .fr-val {
    background-color: var(--diff-now-soft);
    box-shadow: inset 0 -2px 0 var(--diff-now-edge);
    border-radius: var(--r-sm);
    padding: 1px 4px;
  }
  /* Dotted rather than solid, so the pair survives greyscale on a channel that
     is neither hue nor lightness — see ReadOnlyBodyOverlay for the reasoning. */
  .field-row.flipped.flip-was .fr-val {
    background-color: var(--diff-was-soft);
    background-image: repeating-linear-gradient(
      to right,
      var(--diff-was-edge) 0 3px,
      transparent 3px 6px
    );
    background-repeat: no-repeat;
    background-position: 0 100%;
    background-size: 100% 2px;
    box-shadow: none;
  }

  /* Read at rest (#1884 slice 4): the rest/edit cell itself is
     `RailScalarCell` (extracted to stay under the file-size budget); these two
     rules key off `.field-row` state, which is this component's own class. */
  .field-row.scalar:not(.editing) .fr-name { cursor: pointer; }
  .field-row.editing { background: var(--inset); box-shadow: inset 2px 0 0 var(--accent); }

  /* #2009: the long_text index row's "Go to …" hit. A plain inline text
     button (not the absolute-overlay `.fr-rest-hit` recipe RailScalarCell
     uses over a separate display) — the button's own text IS the display. */
  .fr-section-index {
    display: inline-flex;
    align-items: center;
    border: 0;
    background: none;
    padding: 2px 6px;
    border-radius: var(--r-sm);
    color: var(--text-3);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .fr-section-index:hover {
    color: var(--text-2);
    background: var(--inset);
  }
  .fr-section-index:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }

  .fr-computed {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    min-width: 0;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .fr-computed-text {
    /* A computed value can be a long, space-less string (a filesystem `path`,
       #417 s3); break on any character so it wraps within the rail rather than
       overflowing it. Short values (word_count / cost) are unaffected. */
    overflow-wrap: anywhere;
  }
  .fr-computed .ti-lock {
    flex: none;
  }

  .color-row .fr-val {
    gap: 8px;
  }
  .color-row .muted {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  /* Controls inside a row — keep them compact and on-palette. */
  .fr-val :global(input),
  .fr-val :global(select) {
    font-size: var(--fs-md);
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
  }
  /* Free-text scalars (a `text` field, the option-less `multi_select`
     fallback, the legacy `date` input) edit through a bare `<input>` inside
     RailScalarCell's `.fr-edit`. Let it GROW into the free width instead of
     the old fixed 160px cap, so a long value (e.g. an alias list) is fully
     visible on a wide rail (#1949) rather than clipped in a narrow
     right-anchored box. `flex: 1 1 0` — grow from a ZERO basis, not `width:
     100%` and not `flex: … auto`: `.fr-val` is `flex-wrap: wrap`, and the
     fixed-size leading override / trailing mutation markers are flex siblings
     of the input (`.fr-edit` is display:contents). A 100%/auto (intrinsic)
     basis makes line-collection wrap each marker onto its own line while
     editing; a zero basis lets the input sit BETWEEN the markers and grow into
     the leftover width, keeping the one-line `[versions] value ⤳` layout.
     Scoped to `.fr-edit` so nested picker/list inputs (not wrapped in it) are
     untouched. */
  .field-row .fr-val :global(.fr-edit input[type="text"]),
  .field-row .fr-val :global(.fr-edit input:not([type])) {
    flex: 1 1 0;
    min-width: 0;
    text-align: left;
  }
  /* The compact row's cell only claims the row's free width while such an
     input is open, so its right-anchored value column at rest — and the
     changed-field flip highlight, which rides `.fr-val` — stay put. */
  .field-row:not(.wide) .fr-val:has(:global(.fr-edit input[type="text"])),
  .field-row:not(.wide) .fr-val:has(:global(.fr-edit input:not([type]))) {
    flex: 1 1 auto;
  }
  /* Numbers are short scalars — keep them compact, at the value column. */
  .field-row:not(.wide) .fr-val :global(.fr-edit input[type="number"]) {
    max-width: 160px;
    text-align: left;
  }
  .fr-val :global(input[type="checkbox"]) {
    padding: 0;
  }
</style>
