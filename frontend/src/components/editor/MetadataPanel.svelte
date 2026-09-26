<script lang="ts">
  import { tick } from "svelte";
  import { isRequiredSelect } from "@/lib/metadataTypes";
  import { leavesRow } from "@/components/editor/RailScalarCell.svelte";
  import RailFieldRow, { type RailRowCallbacks, type RailRowDeps } from "@/components/editor/RailFieldRow.svelte";
  import ProviderTierPicker from "@/components/widgets/ProviderTierPicker.svelte";
  import { aiSettings } from "@/lib/stores/aiSettings.svelte";
  import ColoredSelect from "@/components/widgets/ColoredSelect.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import RailGroupHead from "@/components/editor/RailGroupHead.svelte";
  import { railSectionCollapse } from "@/lib/stores/railSectionCollapse.svelte";
  import { entryTypeIconClass } from "@/lib/utils/fieldIcons";
  import { effectiveFieldHidden, metadataValueDisplayString } from "@/lib/utils/schemaTypeHelpers";
  import type {
    DocumentKind,
    EffectiveFieldValue,
    EntryMetadata,
    EntryTypeDefinition,
    LoreEntrySummary,
    MetadataSchema,
    MetadataValue,
    NavigateTarget,
    PromptEntrySummary,
    ResolvedCascadeField,
    SelectOption,
    StructureDocument,
  } from "@/lib/types";
  import { metadataSchemaStore, projectLayerIdStore } from "@/lib/stores/schema";
  import { tagById, tagTitleById } from "@/lib/stores/tagNodes";
  import { assistantEntriesStore } from "@/lib/stores/assistants";
  import { plotlineEntriesStore } from "@/lib/stores/plotlines";
  import { inheritedLayerLabel } from "@/lib/utils/provenance";
  import { buildRefResolver } from "@/lib/utils/refResolve";
  import { buildRailRowModel, isFlipped, isFlipResolve, isListIndex, isMutated, isRowEmpty, isSectionIndex, type RailRowContext } from "@/lib/rail/fieldRowModel";
  import { stopTargetableFieldIds } from "@/lib/editor-core/stopFieldEditable";
  import { stopEditRowValueFor } from "@/lib/editor-core/stopEditRows";

  interface Props {
    entryType: string;
    status: string;
    metadata: EntryMetadata;
    documentKind: DocumentKind;
    documentLabel: string;
    documentEntryTypes: [string, EntryTypeDefinition][];
    metadataFieldIds: string[];
    // #2037: the rail's trailing sections (Backlinks, Conversations, the
    // mutation timeline, pinned sets) render HERE, between the known rows and
    // the empty-field fold, so the fold is the last entry in the rail. The
    // fold stays in this component because its rows come off this panel's
    // row context.
    trailing?: import("svelte").Snippet;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    // Research tree (sibling to manuscript) — threaded to the picker.
    researchStructure?: StructureDocument | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    excludeId?: string | null;
    // Provenance (#313 / ADR-0039): the entry's owning layer when it is inherited
    // from an ancestor project. Drives the layer treatment at the top of the
    // rail — the rail is where an edit reaching an ancestor most needs to be
    // visible. Null / matching the open project = authored here, no treatment.
    sourceLayerId?: string | null;
    sourceLayerLabel?: string | null;
    // ADR-0082 §2/F2: forwarded to FieldValueEditor → ReferencePicker — the
    // layer a `create_missing` tag is minted at. See ReferencePicker for the
    // rule; NodeEditor computes it.
    createLayerId?: string | null;
    // Layer-override marks (#314 / ADR-0039): the metadata fields whose effective
    // value comes from an override in this project's chain, not inherited canon.
    // Each such field leads its value with the `ti-versions` mark — the hierarchy
    // twin of the manuscript `⤳` mutation mark (design-language.md §marks). A
    // field can be both overridden and mutated; the two marks then co-occur.
    overriddenFields?: string[];
    computedFieldString?: (fieldId: string) => string;
    // Time-travel overlay (#64, ADR-0013): when scrubbed to a mutation point the
    // rail renders effective values read-only. `effectiveOverrides` holds ONLY
    // the mutated fields (the backend override map) — membership IS the "this
    // changed by here" signal, no diffing. Base values render for the rest.
    effectiveOverrides?: Record<string, EffectiveFieldValue> | null;
    // Snapshot compare (ADR-0044 §F, #409). Deliberately NOT `effectiveOverrides`
    // with a flag: that axis draws a `⤳` beside the name, and a snapshot
    // difference must never get a glyph. A glyph marks what is true about the
    // VALUE — permanent, true whenever you look at the card. A snapshot
    // difference exists only while parked and vanishes at Live, so giving it one
    // would put a permanent-looking mark on a temporary condition (§J).
    // **Lenses get colour, not glyphs.**
    //
    // `fields` holds only what differs, both sides carried; `side` is which one
    // to show. Fields FLIP and never interleave — a value is atomic, it resolves
    // in one blink, so interleaving would only make a cramped row cramped.
    //
    // `resolve` turns the lens interactive for an AI lore-proposal review
    // (ADR-0046 slice 3b): each flipped field becomes click-to-adopt (the atomic
    // twin of accepting a prose region), and the rail shows the PROPOSED value
    // (`was`) regardless of `side` — the tint alone says adopted (warm) vs pending
    // (cool). Absent for snapshot compare, which stays a passive uniform-`side`
    // lens with no per-field adopt.
    compare?: {
      fields: Record<string, { was: unknown; now: unknown }>;
      side: "now" | "was";
      resolve?: { adopted: (fieldId: string) => boolean; onToggle: (fieldId: string) => void };
    } | null;
    readOnly?: boolean;
    // ADR-0095 §8: true while the card is scrubbed to a mutation stop.
    // `readOnly` above already excludes the scrub axis (a parked snapshot / an
    // AI review / an inherited-prompt lock stay whole-card read-only) — this
    // is the per-field axis: a field a mutation can target is editable here
    // even though the card is "scrubbed"; every other field stays read-only.
    scrubbed?: boolean;
    // The open scrub stop's own unit (ADR-0095 §8, decision 5's text seam):
    // its resolved records already carry the anchor's set's rows (field/op/
    // value) directly, so a text/long_text row's edit control can seed from
    // its own row value with no extra fetch. `null` off the lore axis or at
    // base (stop 0).
    stopUnit?: import("@/lib/editor-core/mutationUnits").MutationUnitGroup | null;
    // ADR-0095 §8 decision 6: when scrubbed, a row's write/clear/status-change
    // routes HERE instead of `onMetadataChange`/`onStatusChange` — the edit
    // saves the stop's mutation SET, never the scene or the entry's base
    // metadata. `value === null` is a clear (edit to empty). Rows the
    // stop-edit predicate rejects stay read-only, so they never reach this.
    onStopFieldEdit?: (fieldId: string, value: MetadataValue | null) => void;
    // #2009: the open entry's body renders a headed section per long_text
    // field (BodySections) — NodeEditor passes `bodyShape === "prose"`. When
    // true, a long_text row becomes an index row instead of hosting the
    // editor; `onGoToSection` is then required to jump to it.
    sectionsInBody?: boolean;
    // #2009: scroll + focus the body section for a field id — wired to the
    // registry NodeEditor owns (the section's own TipTap editor instance).
    onGoToSection?: (fieldId: string) => void;
    // #2010: the open entry's body renders a tab per `entity_ref_list` field
    // (the body tab strip) — NodeEditor passes `bodyShape !== "chat"`. When
    // true, such a field becomes an index row instead of hosting its own
    // picker/pills; `onGoToList` is then required to switch to its tab.
    listsInBody?: boolean;
    onGoToList?: (fieldId: string) => void;
    // Outbound events as callback props (#14: MetadataPanel is runes — replaces
    // its createEventDispatcher). NodeEditor (legacy parent) passes these.
    onEntryTypeChange?: (entryType: string) => void;
    onStatusChange?: (status: string) => void;
    onMetadataChange?: (metadata: EntryMetadata) => void;
    onCustomData?: () => void;
    onNavigate?: (target: NavigateTarget) => void;
    // Clear-to-inherit (#517): drop a field's layer override so it reverts to the
    // inherited value. Only the lore host wires it; absent → the override mark
    // stays a static marker (nothing to reset), e.g. scrubbed/parked panes.
    onResetField?: (fieldId: string) => void;
    // ADR-0079: this node's resolved narration cascade (pov_mode / pov folded down
    // the manuscript structure). Drives the SAME inherited treatment as the layer
    // axis — a manuscript node is never layer-inherited (book-scoped), so the two
    // axes never collide on one row. Null when the node declares no cascade.
    resolvedCascade?: Record<string, ResolvedCascadeField> | null;
    // #2054 front matter: the same rows at the head of the document while the
    // rail is collapsed — two to a line at the prose measure, at the item
    // rows' compact density, without the index rows (the sections are headed
    // right below the block, the lists are tabs in the strip above it). The
    // host passes no `trailing` in this layout: that material is the appendix.
    layout?: "rail" | "front-matter";
  }

  let {
    entryType,
    status,
    metadata,
    documentKind,
    documentLabel,
    documentEntryTypes,
    metadataFieldIds,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    implicitContextMatcher = null,
    excludeId = null,
    sourceLayerId = null,
    sourceLayerLabel = null,
    createLayerId = null,
    overriddenFields = [],
    computedFieldString = () => "",
    effectiveOverrides = null,
    compare = null,
    readOnly = false,
    scrubbed = false,
    stopUnit = null,
    onStopFieldEdit,
    sectionsInBody = false,
    onGoToSection,
    listsInBody = false,
    onGoToList,
    onEntryTypeChange,
    onStatusChange,
    onMetadataChange,
    onCustomData,
    onNavigate,
    onResetField,
    resolvedCascade = null,
    trailing,
    layout = "rail",
  }: Props = $props();

  // metadataSchema is global per-project — read from the store, not a prop (#14
  // Step 2). This panel only mounts inside NodeEditor's `{#if metadataSchema}`
  // guard, so the non-null assertion holds (matches the prior non-null prop).
  const metadataSchema = $derived($metadataSchemaStore as MetadataSchema);

  // The owning layer's label when this entry is inherited from an ancestor
  // project (#313), else null. `$projectLayerIdStore` is the open project's own
  // layer, tracked so this recomputes when the schema loads.
  const inheritedFromLabel = $derived(
    inheritedLayerLabel(
      { source_layer_id: sourceLayerId ?? undefined, source_layer_label: sourceLayerLabel ?? undefined },
      $projectLayerIdStore,
    ),
  );

  // Assistants surface ai_provider / ai_capability_tier / ai_model via
  // the bespoke ProviderTierPicker rendered above the schema fields.
  // Filter them out of the generic list so we don't render duplicate
  // editors. (Moved here from NodeEditor so the picker decision and the
  // hide rule live in the same component.)
  const ASSISTANT_PICKER_FIELDS = new Set(["ai_provider", "ai_capability_tier", "ai_model"]);
  const visibleFieldIds = $derived(
    documentKind === "assistant"
      ? metadataFieldIds.filter((id) => !ASSISTANT_PICKER_FIELDS.has(id))
      : metadataFieldIds,
  );

  // The selected assistant model's capabilities, lifted from ProviderTierPicker
  // (which owns the catalogue fetch). null = unknown (not yet loaded / orphan
  // id) → leave Temperature editable rather than guessing. When known and the
  // model has no `temperature` capability, the Temperature field goes read-only
  // with a "Not supported by the model" note (#1554). The no-sampling families
  // (Anthropic Opus 4.7+/5, incl. via OpenRouter) are the only ones affected.
  let assistantModelCapabilities = $state<string[] | null>(null);
  const temperatureUnsupported = $derived(
    documentKind === "assistant" &&
      assistantModelCapabilities !== null &&
      !assistantModelCapabilities.includes("temperature"),
  );
  // #1579: which model discarded a stored temperature, so the note can TELL the
  // user it happened rather than stripping the value silently. Null while the
  // model accepts temperature (the field is editable, nothing was dropped).
  let temperatureClearedForModel = $state<string | null>(null);
  // ProviderTierPicker reports the selected model's capabilities here. Beyond
  // gating the read-only field, we drop a stale stored temperature when the model
  // rejects sampling: the value would otherwise be rejected at save (family
  // models) or sent → a 400 (non-family OpenRouter routes the backend send path
  // can't detect as no-temp). Only when we positively know (caps !== null) and a
  // value is present, and only where edits are allowed (#1554). The drop is now
  // announced via the `.fr-temp-cleared` note below (#1579).
  function onModelCapabilities(caps: string[] | null): void {
    assistantModelCapabilities = caps;
    // Unknown (null) or temperature-capable → nothing to drop; retire any notice.
    if (caps === null || caps.includes("temperature")) {
      temperatureClearedForModel = null;
      return;
    }
    if (canClearOwn && metadataValueString(metadata.ai_temperature) !== "") {
      // Name the model minus any leading `provider/` route segment (an OpenRouter
      // id like `anthropic/claude-opus-4-8` → `claude-opus-4-8`; mirrors the
      // backend's family check). Falls back to "this model" for an empty id.
      temperatureClearedForModel =
        metadataValueString(metadata.ai_model).split("/").pop() || "this model";
      clearField("ai_temperature");
    }
  }

  const entryTypeDef = $derived(metadataSchema.entry_types[entryType] ?? null);
  // The open entry's resolved type icon (#316), computed once for the rail header.
  const railTypeIcon = $derived(entryTypeIconClass(entryType, metadataSchema));
  // The head's option list: every type this document kind offers, plus the bare
  // stored value when it is not in the resolved schema (#87 — the warning below
  // explains it; the option keeps the value selectable/visible, as the old
  // <select> did).
  const typeOptions = $derived.by((): SelectOption[] => {
    const known = documentEntryTypes.map(([typeId, definition]) => ({ value: typeId, label: definition.name }));
    if (entryType && !metadataSchema.entry_types[entryType]) return [{ value: entryType, label: entryType }, ...known];
    return known;
  });
  // Inheritance: a field present on the type but not in its own_fields is
  // inherited from the kind / parent. We only mark when own_fields is
  // explicitly present (older schemas omit it → treat all as own).
  const ownFieldSet = $derived(new Set(entryTypeDef?.own_fields ?? []));
  const hasOwnFields = $derived(Array.isArray(entryTypeDef?.own_fields));

  // L1 grouping: ungrouped fields render first (no header), then each
  // group in first-appearance order. A head only renders per block when the
  // type has at least one group (#1884 slice 3) — a type with no groups is
  // one block, a header would be noise. Once there IS anything to fold, every
  // block folds the same way, including the ungrouped one (labelled
  // "General"), and each block's open/closed state persists through
  // `railSectionCollapse`.
  type RailSection = { group: string | null; ids: string[] };
  function buildSections(ids: string[], schema: MetadataSchema): RailSection[] {
    const ungrouped: string[] = [];
    const groups = new Map<string, string[]>();
    for (const id of ids) {
      const field = schema.fields[id];
      if (!field) continue;
      const group = (field.group ?? "").trim();
      if (!group) {
        ungrouped.push(id);
      } else {
        if (!groups.has(group)) groups.set(group, []);
        groups.get(group)!.push(id);
      }
    }
    const out: RailSection[] = [];
    if (ungrouped.length) out.push({ group: null, ids: ungrouped });
    for (const [group, groupIds] of groups) out.push({ group, ids: groupIds });
    return out;
  }
  const renderedFieldIds = $derived(visibleFieldIds.filter(rendersRow));

  // #2006: rail = what is known; empty fields fold away behind one summary
  // line so the rail reads like a filled-in form, not a checklist of blanks.
  // While the fold is OPEN, membership is STICKY — `foldHeld` snapshots the
  // empty ids at open time, and a field filled or emptied afterward stays put
  // (in `foldIds`) until the fold closes — so a row never jumps out from under
  // a writer mid-edit. Closed, fold membership is just the live empty set.
  let foldOpen = $state(false);
  let foldHeld = $state<Set<string>>(new Set());
  // A flipped row (a lore proposal or a snapshot compare, `compare`) and a
  // mutated row (`⤳`) carry information even when the shown value is empty —
  // a proposal to CLEAR a field, a diff against an empty side — so they never
  // fold; only a plain empty row does.
  const emptyIds = $derived(
    renderedFieldIds.filter((id) => {
      const field = metadataSchema.fields[id];
      if (!field || isFlipped(ctx, id) || isMutated(ctx, id)) return false;
      return isRowEmpty(ctx, field, id);
    }),
  );
  const foldIds = $derived(foldOpen ? new Set([...emptyIds, ...foldHeld]) : new Set(emptyIds));
  const knownFieldIds = $derived(renderedFieldIds.filter((id) => !foldIds.has(id)));
  const foldFieldIds = $derived(foldOpen ? renderedFieldIds.filter((id) => foldIds.has(id)) : []);
  const foldCount = $derived(emptyIds.length);
  const showFold = $derived(foldOpen || foldCount > 0);
  function toggleFold() {
    if (foldOpen) {
      foldOpen = false;
      foldHeld = new Set();
    } else {
      foldHeld = new Set(emptyIds);
      foldOpen = true;
    }
  }

  const sections = $derived(buildSections(knownFieldIds, metadataSchema));
  const foldSections = $derived(buildSections(foldFieldIds, metadataSchema));

  // Every block folds the same way once there is anything to fold: when a type
  // has at least one L1 group, the ungrouped fields get a header too (#1884
  // slice 3). A type with no groups is one block — no header at all. The
  // known loop asks this of the KNOWN rows only (#2006): when every grouped
  // field is empty and folded, the rows on screen are one block, and a lone
  // "General" head over them would be the noise this rule exists to avoid.
  // The open fold shows heads when either side has a group, so its chooser
  // reads like the schema.
  const UNGROUPED_LABEL = "General";
  const showGroupHeads = $derived(sections.some((s) => s.group !== null));
  const showFoldHeads = $derived(showGroupHeads || foldSections.some((s) => s.group !== null));
  // #2061: whether ANY rendered row (known or folded, fold open or closed) is
  // grouped — decided on the schema, not on the heads currently on screen, so
  // the front matter's gutter never appears the moment a fold with a group
  // opens and shoves every row 22px.
  const anyGroupedRow = $derived(renderedFieldIds.some((id) => (metadataSchema.fields[id]?.group ?? "").trim() !== ""));
  const GROUP_DEFAULT = true;
  function groupKey(section: RailSection): string { return `group:${section.group ?? "~ungrouped"}`; }
  function groupExpanded(section: RailSection): boolean { return railSectionCollapse.isExpanded(groupKey(section), GROUP_DEFAULT); }

  // The shared record-aware rule (#698): the flip's "Current:" hint and the
  // default hint must render a list of records as member values, never
  // "[object Object]" — this line is what the author reads before adopting.
  const metadataValueString = metadataValueDisplayString;

  // The one rule for "this field gets a row" — shared by the row loop and the
  // section builder, so a block never shows a head over zero rows (#1884 slice
  // 3): intrinsic identity fields have dedicated controls (unless one is an
  // active flip, ADR-0046 3b), per-type hidden fields stay hidden, and a
  // valueless computed field is rail noise (#1684). ADR-0089 Amendment 1 §4
  // (#2101): a computed node-set field (References/Conversations/Mutation
  // sets) is a TAB-ONLY collection with a bound renderer, never a rail row —
  // explicit rather than leaning on its computed string always being empty,
  // since that's incidental, not its contract.
  function rendersRow(fieldId: string): boolean {
    const field = metadataSchema.fields[fieldId];
    if (!field) return false;
    if (field.intrinsic && !isFlipResolve(ctx, fieldId)) return false;
    if (effectiveFieldHidden(metadataSchema, entryType, fieldId)) return false;
    if (layout === "front-matter" && (isSectionIndex(ctx, field) || isListIndex(ctx, field))) return false;
    if (field.type === "computed" && field.computed?.value_type === "node_set") return false;
    return field.type !== "computed" || computedFieldString(fieldId) !== "";
  }

  const FOLD_DEFAULT = false;
  function fieldExpanded(fieldId: string): boolean {
    return railSectionCollapse.isExpanded(`field:${fieldId}`, FOLD_DEFAULT);
  }

  // The reset gesture is live only when a handler is wired and the rail is
  // editable — a scrubbed / snapshot-parked pane shows the mark inertly.
  // ADR-0095 §8: hidden at a stop too — a reset edits base/override state,
  // never a mutation set.
  const canResetOverride = $derived(onResetField != null && !readOnly && !scrubbed);

  // Clear-to-default (#522): the intra-project twin of #517's layer reset. On a
  // locally-owned entry, a field carrying its own stored value can be reverted to
  // its type/kind default — or to unset — by DELETING its sparse metadata key
  // (the owned save drops an omitted key; defaults are seeded only at create, so
  // an absent key stays absent). Inherited entries revert via the #517 override
  // reset instead, so this is gated to non-inherited entries and never collides
  // with it. Same gesture as #517 — the `ti-versions` mark + "Reset to …" chip,
  // just a different target — so a user never wonders why one field reverts and
  // another doesn't. Editable-rail-only, like the override reset. ADR-0095 §8:
  // hidden at a stop too — a stop edit writes the mutation set, never the base
  // metadata this reset targets.
  const canClearOwn = $derived(onMetadataChange != null && !readOnly && !scrubbed);
  function clearField(fieldId: string) {
    // ADR-0095 §8 decision 6: a clear at a stop is an edit TO EMPTY, routed the
    // same as any other stop write (a `replace` with "" unless the baseline is
    // already empty, in which case `rowsForStopEdit` drops the row on its own).
    if (onStopFieldEdit) {
      onStopFieldEdit(fieldId, null);
      return;
    }
    const next = { ...metadata };
    delete next[fieldId];
    onMetadataChange?.(next);
  }

  // Persist a single field edit. A required select (one that declares a default,
  // #1421) that lands back on its default pops the key instead of writing it, so
  // front matter stays sparse — the value resolves to the same default at
  // evaluation. Every other edit writes through unchanged. ADR-0095 §8 decision
  // 6: at a stop, every write routes to `onStopFieldEdit` instead — it saves
  // THIS STOP'S mutation set, never the entry's base metadata.
  function writeField(fieldId: string, v: MetadataValue) {
    if (onStopFieldEdit) {
      onStopFieldEdit(fieldId, v);
      return;
    }
    const field = metadataSchema.fields[fieldId];
    if (isRequiredSelect(field) && String(v) === field.default) {
      clearField(fieldId);
      return;
    }
    onMetadataChange?.({ ...metadata, [fieldId]: v });
  }

  function updateAssistantProvider(provider: string, tier: string, model: string) {
    onMetadataChange?.({ ...metadata, ai_provider: provider, ai_capability_tier: tier, ai_model: model });
  }

  // #2010: resolves an entity_ref_list member id to its entry_type, for a
  // list-index row's per-type summary — the same walk ReferencePicker's pills
  // use (lib/utils/refResolve), over the in-memory sources this panel already
  // holds plus the global assistant/plot/tag rosters (read directly, like
  // ReferencePicker does — no extra prop threading).
  const listMemberResolver = $derived(
    buildRefResolver({
      structure,
      loreEntries,
      promptEntries,
      assistantEntries: $assistantEntriesStore,
      plotEntries: $plotlineEntriesStore,
      tagById: $tagById,
    }),
  );

  // #2009: a long_text index row's hit — bring its body section into view,
  // then hand off to the host to focus that section's own TipTap editor (the
  // rail doesn't own the section registry; NodeEditor does).
  function goToSection(fieldId: string) {
    document.getElementById(`section-${fieldId}`)?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    onGoToSection?.(fieldId);
  }

  // Read at rest, edit on demand (#1884 slice 4): `RailScalarCell` owns the two
  // widgets (rest display + live control) for one scalar row; this component
  // owns only WHICH row is "open" at a time and the document-level
  // outside-click listener that closes it. Transient UI state — never
  // persisted, resets with the node.
  let openFieldId = $state<string | null>(null);
  let openRowEl: HTMLElement | null = null;
  async function openField(fieldId: string, rowEl: HTMLElement) {
    openFieldId = fieldId;
    openRowEl = rowEl;
    await tick();
    // Focus the first control the editor rendered, so Enter on the hit target
    // lands the writer in the input without a second click.
    const first = rowEl.querySelector<HTMLElement>(".fr-val input, .fr-val select, .fr-val textarea, .fr-val button:not(.fr-override-marker)");
    first?.focus();
  }
  function closeField(fieldId: string) { if (openFieldId === fieldId) openFieldId = null; }

  // Reset the open row whenever the shown node changes. MetadataPanel is not
  // remounted per node by NodeEditor (only the Backlinks/Conversations/Pinned-
  // sets panels are keyed on `scene.id`), so the open row has to be reset here
  // — `excludeId` is NodeEditor's `scene?.id`, the node identity this panel is
  // fed for.
  $effect(() => {
    void excludeId;
    openFieldId = null;
  });

  // Outside click (while a row is open): close it when the pointerdown lands
  // outside the open row and outside a body-portaled ColoredSelect popover.
  // `capture: true` so a click on a control that stops propagation still closes.
  $effect(() => {
    if (openFieldId === null) return;
    const rowEl = openRowEl;
    const fieldId = openFieldId;
    function onPointerDown(event: PointerEvent) {
      if (rowEl && leavesRow(rowEl, event.target)) closeField(fieldId);
    }
    document.addEventListener("pointerdown", onPointerDown, { capture: true });
    return () => document.removeEventListener("pointerdown", onPointerDown, { capture: true });
  });

  // ADR-0095 §8: the set of fields a mutation can target, at THIS schema +
  // entry type — derived ONCE per render (not per row: `stopFieldTargetable`
  // used to walk the whole `buildFieldOptions` roster on every row's call, so
  // a panel with N rows rebuilt it N times). `ctx.stopEditable` below just
  // asks the Set.
  const targetableFieldIds = $derived(stopTargetableFieldIds(metadataSchema, entryType));

  // The per-node context every row's model is built from (#2022 split) — one
  // `$derived` shared by every field, rebuilt whenever any input it reads
  // changes. `buildRailRowModel` (fieldRowModel.ts) is pure; this is the only
  // place it's called.
  const ctx = $derived<RailRowContext>({
    schema: metadataSchema,
    entryType,
    documentKind,
    metadata,
    status,
    hasOwnFields,
    ownFieldSet,
    effectiveOverrides,
    overriddenFields,
    compare,
    resolvedCascade,
    structure,
    sourceLayerLabel,
    inheritedFromLabel,
    canClearOwn,
    canResetOverride,
    readOnly,
    temperatureUnsupported,
    temperatureClearedForModel,
    computedFieldString,
    tagTitleById: $tagTitleById,
    openFieldId,
    fieldExpanded,
    sectionsInBody,
    listsInBody,
    resolveListMemberType: (id) => listMemberResolver(id)?.entry_type ?? null,
    resolveListMemberTitle: (id) => listMemberResolver(id)?.title ?? null,
    // ADR-0095 §8: `readOnly` above already folds snapshotParked/reviewing/
    // inheritedReadOnly (NodeEditor's redefined `editorReadOnly`), so the
    // field-membership half is all this needs to ask.
    scrubbed,
    stopEditable: (fieldId) => targetableFieldIds.has(fieldId),
    stopEditValueFor: (fieldId) => stopEditRowValueFor(fieldId, stopUnit?.records ?? []),
  });
  function rowModel(fieldId: string) {
    return buildRailRowModel(ctx, fieldId);
  }

  // The widget pass-throughs a row hands to its children unchanged (#2022
  // split) — everything else a row needs comes off its own `RailRowModel`.
  const deps = $derived<RailRowDeps>({
    readOnly,
    resolveRef: listMemberResolver,
    createLayerId,
    loreEntries,
    promptEntries,
    structure,
    researchStructure,
    implicitContextMatcher,
    excludeId,
  });

  // The panel's write-back callbacks (#2022 split) — a row never touches panel
  // state or stores directly, only these. Built once; each closes over the
  // panel's own reactive props/state and reads their current value at call time.
  const callbacks: RailRowCallbacks = {
    open: openField,
    close: closeField,
    clear: clearField,
    write: writeField,
    toggleExpanded: (fieldId) => railSectionCollapse.toggle(`field:${fieldId}`, FOLD_DEFAULT),
    // ADR-0095 §8 decision 6: `status` routes through `onStopFieldEdit` at a
    // stop, same as every other rail write.
    statusChange: (value) => (onStopFieldEdit ? onStopFieldEdit("status", value) : onStatusChange?.(value)),
    resetField: (fieldId) => onResetField?.(fieldId),
    navigate: (payload) => onNavigate?.(payload),
    toggleFlip: (fieldId) => compare?.resolve?.onToggle(fieldId),
    goToSection: (fieldId) => goToSection(fieldId),
    goToList: (fieldId) => onGoToList?.(fieldId),
  };
</script>

{#snippet editTypeAction({ close }: { close: () => void })}
  <button type="button" class="rail-type-action" onclick={() => { close(); onCustomData?.(); }}>Edit type…</button>
{/snippet}

<section
  class="scene-metadata"
  class:front-matter={layout === "front-matter"}
  class:no-disc={layout === "front-matter" && !anyGroupedRow}
  aria-label={`${documentLabel} details`}
>
  <!-- The head is one fact — the entry's type — and reads as one (#1904, #1884):
       glyph + name + caret, the rail's own ColoredSelect in its quiet face. The
       type list opens on click; "Edit type…" lives behind it as the trailing
       action. readOnly locks the pick; the jump stays reachable. ADR-0095 §8:
       the type selector stays locked at a stop too — a mutation can't
       reclassify an entry. -->
  <div class="rail-type">
    <ColoredSelect
      value={entryType}
      options={typeOptions}
      allowBlank={false}
      icon={railTypeIcon}
      quiet
      readOnly={readOnly || scrubbed}
      ariaLabel={`${documentLabel} type: ${typeOptions.find((o) => o.value === entryType)?.label ?? entryType}`}
      onChange={(next) => onEntryTypeChange?.(next)}
      footer={editTypeAction}
    />
  </div>

  {#if entryType && !metadataSchema.entry_types[entryType]}
    <!-- Unresolved entry_type (#87): the type stored on this node is not in the
         resolved schema (an out-of-band file edit, a stale import, or a machine
         file predating a schema re-key). The type select above already keeps the
         value as a bare option; without this line the editor *also* silently
         falls back to another type's fields and body, so the author reads the
         wrong fields with no signal. Make the fallback visible. -->
    <div class="rail-type-warning" role="status">
      <span class="rail-type-warning-glyph" aria-hidden="true">⚠</span>
      <span
        >Unknown type <code>{entryType}</code> — not in this project's schema.
        Showing fallback fields; the stored type is kept until you change it.</span
      >
    </div>
  {/if}

  {#if inheritedFromLabel}
    <!-- Provenance treatment (#313 / ADR-0039): this entry is owned by an
         ancestor layer. Same --star axis as the level pill and the ancestor
         banner, so the three provenance surfaces read as one vocabulary. -->
    <div class="rail-provenance" title="This entry is inherited from an ancestor project; edits write back to the original.">
      <span>Inherited from <strong>{inheritedFromLabel}</strong></span>
    </div>
  {/if}

  {#if documentKind === "assistant"}
    <div class="rail-assistant">
      <ProviderTierPicker
        provider={metadataValueString(metadata.ai_provider)}
        tier={metadataValueString(metadata.ai_capability_tier) as import("@/lib/types").AICapabilityTier | ""}
        model={metadataValueString(metadata.ai_model)}
        policy={aiSettings.resolvedPolicy}
        onChange={(detail) => updateAssistantProvider(detail.provider, detail.tier, detail.model)}
        onCapabilities={onModelCapabilities}
      />
    </div>
  {/if}

  {#each sections as section}
    {#if showGroupHeads}
      <RailGroupHead
        label={section.group ?? UNGROUPED_LABEL}
        expanded={groupExpanded(section)}
        onToggle={() => railSectionCollapse.toggle(groupKey(section), GROUP_DEFAULT)}
      />
    {/if}
    {#if !showGroupHeads || groupExpanded(section)}
    {#each section.ids as fieldId (fieldId)}
      {#if rendersRow(fieldId)}
        <RailFieldRow model={rowModel(fieldId)} {deps} on={callbacks} />
      {/if}
    {/each}
    {/if}
  {/each}

  {@render trailing?.()}

  {#if showFold}
    <!-- #2006: one summary line stands in for every empty field. Closed, it
         names the live empty count; open, it flips to "fewer fields" and stays
         that way (even as sticky-held fields fill in) until clicked again. -->
    <button type="button" class="rail-fold" data-testid="rail-fold-toggle" aria-expanded={foldOpen} onclick={toggleFold}>
      <GroupCaret size="xs" collapsed={!foldOpen} />
      <span>{foldOpen ? "fewer fields" : `${foldCount} more field${foldCount === 1 ? "" : "s"}`}</span>
    </button>
    {#if foldOpen}
      <div class="rail-fold-body" data-testid="rail-fold-body">
        {#each foldSections as section}
          {#if showFoldHeads}
            <RailGroupHead label={section.group ?? UNGROUPED_LABEL} />
          {/if}
          {#each section.ids as fieldId (fieldId)}
            {#if rendersRow(fieldId)}
              <RailFieldRow model={rowModel(fieldId)} {deps} on={callbacks} />
            {/if}
          {/each}
        {/each}
      </div>
    {/if}
  {/if}
</section>

<style>
  .scene-metadata {
    display: flex;
    flex-direction: column;
    padding: 4px 0 12px;
  }

  /* Generic form-control styling for the metadata subtree, co-located from
     styles.css (#14). The controls are rendered by child pickers (SwatchPicker
     / ColoredSelect / ReferencePicker / TagPicker / ProviderTierPicker /
     MetadataLongTextEditor), so the element targets are :global; the
     .scene-metadata ancestor keeps this scope. */
  .scene-metadata :global(label) {
    color: var(--text-2);
    font-size: var(--fs-sm);
    font-weight: 700;
  }
  .scene-metadata :global(input),
  .scene-metadata :global(select),
  .scene-metadata :global(textarea) {
    margin-top: 4px;
    font-size: var(--fs-md);
    font-weight: 400;
  }
  .scene-metadata :global(input[readonly]) {
    color: var(--text-3);
    background: var(--app-bg);
  }

  /* Type header */
  .rail-type {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px 10px;
    border-bottom: 1px solid var(--divider);
  }
  /* Provenance treatment (#313) — the --star axis, matching the level pill and
     the inherited-entry banner. Sits directly under the type header. */
  .rail-provenance {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: var(--star-soft);
    border-bottom: 1px solid var(--star-border);
    color: var(--star);
    font-size: var(--fs-xs);
  }
  .rail-provenance strong {
    font-weight: 700;
  }
  /* Unresolved entry_type (#87) — the --warn axis, a caution not a hard error:
     the fields shown are a best-effort fallback, and the stored value survives
     the next save. Sits directly under the type header like rail-provenance. */
  .rail-type-warning {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 6px 12px;
    background: var(--warn-soft);
    border-bottom: 1px solid var(--warn-border);
    color: var(--warn);
    font-size: var(--fs-xs);
  }
  .rail-type-warning-glyph {
    flex: none;
    line-height: 1.4;
  }
  .rail-type-warning code {
    font-family: var(--mono);
    font-weight: 700;
  }
  .rail-assistant {
    padding: 10px 12px;
    border-bottom: 1px solid var(--divider);
  }

  /* #2006 fold summary line — gap 17px + the xs caret's 15px slot lines the
     label up with RailGroupHead's label, same as .rgh-toggle (see that
     component's comment). */
  .rail-fold { display: inline-flex; align-items: center; gap: 17px; margin: 2px 0 0; padding: 6px 12px 6px 12px; border: none; background: none; color: var(--text-3); font: inherit; font-size: var(--fs-sm); cursor: pointer; text-align: left; }
  .rail-fold:hover { color: var(--text-2); }
  .rail-fold:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--r-sm); }

  /* Front matter (#2054): the same rows, two to a line at the head of the
     document, at the item rows' compact density (BodyItemRows). Everything
     that is not a fact row spans: the type head, the notices, the group heads,
     the fold line; so does a line-valued row (`.wide`, the rail's own rule,
     and the tags line, which the rail keeps un-wide but is a line all the same).
     An open row keeps its cell: a column is as wide as the rail, so the rail's
     controls fit without spanning and nothing jumps on click. The fold body is
     `display: contents` so its rows flow into the same grid. The wrapper is
     the prose column (serif, for the measure); the block pins the UI font. */
  .scene-metadata.front-matter {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: var(--sp-6);
    align-items: start;
    padding: 0 0 var(--sp-2);
    font-family: var(--sans);
    font-size: var(--fs-sm);
  }
  .scene-metadata.front-matter > .rail-type,
  .scene-metadata.front-matter > .rail-type-warning,
  .scene-metadata.front-matter > .rail-provenance,
  .scene-metadata.front-matter > .rail-assistant,
  .scene-metadata.front-matter > .rail-fold,
  .scene-metadata.front-matter :global(.rail-group-head),
  .scene-metadata.front-matter :global(.field-row.wide) {
    grid-column: 1 / -1;
  }
  /* #2061: the row's 22px disclosure gutter exists so a field's glyph sits
     under a group head's caret. With no group heads on the type (known rows
     or fold), it is dead space that left every label 32px right of the wide
     values' edge — so icons, labels and value lines share the prose edge.
     Only the EMPTY gutter goes: the folding-list caret shares the slot's
     class (`.fr-disc-toggle`), and though no foldable list reaches the front
     matter today (lists are index rows there), a control must never be
     hidden by a spacing rule. */
  .scene-metadata.front-matter.no-disc :global(.fr-disc:not(.fr-disc-toggle)) {
    display: none;
  }
  .scene-metadata.front-matter > .rail-fold-body {
    display: contents;
  }
  .scene-metadata.front-matter > .rail-type,
  .scene-metadata.front-matter > .rail-fold {
    padding-inline: 0;
  }
  .scene-metadata.front-matter :global(.field-row) {
    padding: 3px 0;
  }

  /* L1 section headers live in styles.css (shared with the type
     editor); only the Field row chrome is scoped per-component. */
</style>
