// The metadata rail's per-field row model (#2022 split of MetadataPanel).
// Pure — no Svelte imports beyond types — so it's unit-testable without
// mounting anything. `buildRailRowModel` takes a `RailRowContext` (the panel's
// resolved per-node state) and a `fieldId`, and returns every value/flag the
// row markup needs; the row's own `<script>` is then just the props
// destructure. The predicates below were lifted verbatim from MetadataPanel —
// see that file's history for the `#…` issue references behind each rule.
import { derivedSelectValue } from "@/lib/metadataTypes";
import { isTagFlipField, tagFlipItemsFor, type TagFlipItem } from "@/components/widgets/TagFlipChips.svelte";
import { isTagListField } from "@/lib/utils/pickerCreate";
import { fieldIconClass } from "@/lib/utils/fieldIcons";
import { resolveColor } from "@/lib/utils/colors";
import { effectiveFieldLabel, isMetadataValuePresent, metadataValueDisplayString } from "@/lib/utils/schemaTypeHelpers";
import { fieldProvenance, isFieldOwnClearable } from "@/lib/utils/provenance";
import { findStructureNodeById } from "@/lib/utils/treeHelpers";
import { countWords } from "@/lib/utils/wordCount";
import { listHasProseItems } from "@/lib/editor-core/bodySections";
import { itemMemberDetail, keyedListKeyMember, listItemKey } from "@/lib/editor-core/keyedList";
import type {
  DocumentKind,
  EffectiveFieldValue,
  EntryMetadata,
  MetadataFieldDefinition,
  MetadataSchema,
  MetadataValue,
  ResolvedCascadeField,
  StructureDocument,
} from "@/lib/types";

/** The panel's resolved per-node state a row's predicates read from. Built
 *  once per render (`$derived` in MetadataPanel) and reused for every field. */
export type RailRowContext = {
  schema: MetadataSchema;
  entryType: string;
  documentKind: DocumentKind;
  metadata: EntryMetadata;
  status: string;
  hasOwnFields: boolean;
  ownFieldSet: Set<string>;
  effectiveOverrides: Record<string, EffectiveFieldValue> | null;
  overriddenFields: string[];
  compare: {
    fields: Record<string, { was: unknown; now: unknown }>;
    side: "now" | "was";
    resolve?: { adopted: (fieldId: string) => boolean; onToggle: (fieldId: string) => void };
  } | null;
  resolvedCascade: Record<string, ResolvedCascadeField> | null;
  structure: StructureDocument | null;
  sourceLayerLabel: string | null;
  inheritedFromLabel: string | null;
  // #2009: the open entry's body renders a headed section per long_text field
  // (BodySections). When true, a long_text row becomes a rail INDEX row (a
  // word-count "Go to …" jump) instead of hosting the editor — see `sectionIndex`.
  sectionsInBody: boolean;
  // #2010: the open entry's body renders a tab per `entity_ref_list` field
  // (the body tab strip). When true, such a field becomes a rail INDEX row (a
  // per-type-count "Open …" jump) instead of hosting its own picker/pills —
  // see `listIndex`. False for chat (the strip never renders there).
  listsInBody: boolean;
  // #2010: resolves a list member id to its entry_type, for the list-index
  // row's per-type summary — the same walk `lib/utils/refResolve.ts` shares
  // with ReferencePicker/ReferenceListTab. Absent id (unresolvable) → null.
  resolveListMemberType?: (id: string) => string | null;
  // A reference-keyed list's target id → its title (ADR-0089 §6), from the same
  // `buildRefResolver` walk as `resolveListMemberType` — used by the proposal
  // flip's "Current:" hint so it names targets instead of dumping raw ids.
  resolveListMemberTitle?: (id: string) => string | null;
  canClearOwn: boolean;
  canResetOverride: boolean;
  readOnly: boolean;
  temperatureUnsupported: boolean;
  temperatureClearedForModel: string | null;
  computedFieldString: (fieldId: string) => string;
  tagTitleById: ReadonlyMap<string, string>;
  openFieldId: string | null;
  fieldExpanded: (fieldId: string) => boolean;
  // ADR-0095 §8: at a scrub stop, every field a mutation can target is
  // editable in place — `editorReadOnly` no longer folds `scrubbed` in
  // (NodeEditor), so each row asks this per-field predicate instead.
  // `scrubbed` false outside the lore axis, so `stopEditable` is never
  // consulted then.
  scrubbed: boolean;
  stopEditable: (fieldId: string) => boolean;
  // §8's text-field seam (decision 5): the set's own row value for a
  // text/long_text field at a stop — the replace row's value, else the add
  // row's fragment, else `null` (no row yet). Only consulted for a
  // stop-editable text/long_text row.
  stopEditValueFor?: (fieldId: string) => string | null;
};

export type RailRowModel = {
  // identity
  field: MetadataFieldDefinition;
  fieldId: string;
  fieldLabel: string;
  iconClass: string;
  description: string | undefined;

  // flags
  inherited: boolean;
  layerInherited: boolean;
  cascadeInherited: boolean;
  cascadeOverridden: boolean;
  mutated: boolean;
  overridden: boolean;
  flipped: boolean;
  flipWas: boolean;
  flipResolve: boolean;
  flipAdopted: boolean;
  empty: boolean;
  scalar: boolean;
  // #2058: a single `entity_ref` — a rest/open row (`scalar`) whose rest face
  // is the resolved name and whose open face is the picker.
  singleRef: boolean;
  editing: boolean;
  wide: boolean;
  // #2009: this row is a long_text index row (its editor lives in a body
  // section instead) — `wordCount` is over the field's current value.
  sectionIndex: boolean;
  wordCount: number;
  // #2043: a list-of-prose-items section index row reads an item count
  // instead of a word count; null for a long_text index row.
  sectionSummary: string | null;
  // #2010: this row is an entity_ref_list index row (its editor lives in a
  // body tab instead) — `listSummary` is the per-type count line.
  listIndex: boolean;
  listSummary: string;
  colorRow: boolean;
  foldableList: boolean;
  fieldExpanded: boolean;
  isStatus: boolean;
  isComputed: boolean;
  isTagList: boolean;
  isRef: boolean;
  closesOnPick: boolean;
  showTempNote: boolean;

  // values
  value: MetadataValue;
  statusValue: string;
  computedText: string;
  defaultHint: string;
  inheritedTooltip: string | undefined;
  cascadeSourceLabel: string;
  cascadeOverrideSourceLabel: string;
  sourceLayerLabel: string | null;
  flipCurrentHint: string;
  tagFlipItems: TagFlipItem[] | null;
  colorValue: string | null;
  colorPlaceholderHex: string | null;
  colorUnset: boolean;
  tempClearedForModel: string | null;

  // permissions
  fieldReadOnly: boolean;
  canClearOwn: boolean;
  ownClearable: boolean;
  canResetOverride: boolean;
  canResetCascade: boolean;

  // ADR-0095 §8 decision 5: a stop-editable text/long_text row's edit control
  // opens on the SET's own row value, not the effective display — `undefined`
  // for every other row (its control just reads `value` as always).
  stopEditValue: string | undefined;
};

// The shared record-aware rule (#698): the flip's "Current:" hint and the
// default hint must render a list of records as member values, never
// "[object Object]" — this line is what the author reads before adopting.
const metadataValueString = metadataValueDisplayString;

// A select holding its field's derived state (#1911) — a state the app set,
// e.g. a plot card's On the page from its scene link — is read-only: the
// author cannot leave it by hand (the healer would put it straight back).
function holdsDerivedState(ctx: RailRowContext, fieldId: string): boolean {
  const held = derivedSelectValue(ctx.schema.fields[fieldId]);
  return held !== null && metadataValueString(displayValue(ctx, fieldId)) === held;
}

function fieldReadOnly(ctx: RailRowContext, fieldId: string): boolean {
  if (ctx.readOnly) return true;
  if ((fieldId === "ai_temperature" && ctx.temperatureUnsupported) || holdsDerivedState(ctx, fieldId)) return true;
  // ADR-0095 §8: `editorReadOnly` (`ctx.readOnly`) no longer folds `scrubbed`
  // in — a scrub stop is per-field now, so a row that ISN'T one a mutation
  // can target stays read-only exactly the way the whole card used to.
  if (ctx.scrubbed) return !ctx.stopEditable(fieldId);
  return false;
}

// Inheritance: a field present on the type but not in its own_fields is
// inherited from the kind / parent. We only mark when own_fields is
// explicitly present (older schemas omit it → treat all as own).
function isInherited(ctx: RailRowContext, fieldId: string): boolean {
  return ctx.hasOwnFields && !ctx.ownFieldSet.has(fieldId);
}

function isMutated(ctx: RailRowContext, fieldId: string): boolean {
  return ctx.effectiveOverrides != null && fieldId in ctx.effectiveOverrides;
}

// Whether this field's effective value comes from a layer override (#314).
// A permanent fact about the value — like `⤳`, it draws a glyph — so it is a
// separate axis from the snapshot-compare lens (which gets colour, not a glyph).
function isOverridden(ctx: RailRowContext, fieldId: string): boolean {
  return ctx.overriddenFields.includes(fieldId);
}

// Provenance tint (#517 / §8): whether the entry itself is inherited from an
// ancestor layer. A non-overridden field on such an entry reads *muted* (its
// value flows from the owner); an overridden field reads *live* with the reset
// gesture. On a locally-authored entry there is no layer treatment at all.
function isLayerInherited(ctx: RailRowContext, fieldId: string): boolean {
  const entryIsInherited = ctx.inheritedFromLabel !== null;
  return fieldProvenance(fieldId, entryIsInherited, ctx.overriddenFields) === "layer-inherited";
}

// ADR-0079 structure axis: narration (pov_mode / pov) inherited down the
// manuscript tree. Reuses the layer-axis `.layer-inherited` treatment — the two
// axes never share a node kind (a manuscript node is never layer-inherited), so
// one treatment reads cleanly, the per-field source label saying whence.
const NO_CHARACTER_MODES = ["third_omniscient", "third_objective"];
function isCascadeField(ctx: RailRowContext, fieldId: string): boolean {
  return (ctx.schema.cascade_fields ?? []).includes(fieldId);
}
function cascadeInfo(ctx: RailRowContext, fieldId: string): ResolvedCascadeField | null {
  if (!isCascadeField(ctx, fieldId)) return null;
  return ctx.resolvedCascade?.[fieldId] ?? null;
}
function isCascadeInherited(ctx: RailRowContext, fieldId: string): boolean {
  const info = cascadeInfo(ctx, fieldId);
  if (info == null || info.own || info.value == null || info.value === "") return false;
  // An omniscient / objective mode has no viewpoint character — don't surface an
  // inherited `pov` the mode makes moot (the rail twin of resolved_narration's gate).
  if (fieldId === "pov" && NO_CHARACTER_MODES.includes(String(ctx.resolvedCascade?.pov_mode?.value)))
    return false;
  return true;
}
// A cascade source's human label: the book (null id), else the structure node's
// title, else a generic fallback. Shared by the inherited + override labels.
function cascadeNodeLabel(ctx: RailRowContext, sourceId: string | null): string {
  if (sourceId == null) return "the book";
  return (ctx.structure ? findStructureNodeById(ctx.structure.root, sourceId)?.title : null) || "an ancestor";
}
function cascadeSourceLabel(ctx: RailRowContext, fieldId: string): string {
  return cascadeNodeLabel(ctx, cascadeInfo(ctx, fieldId)?.source_id ?? null);
}
// ADR-0079 override axis (#1734): this node SETS its own cascade value AND that
// value shadows one it would otherwise inherit. Distinct from a value merely set
// with nothing above it — only a shadowing override earns the persistent mark.
function isCascadeOverridden(ctx: RailRowContext, fieldId: string): boolean {
  const info = cascadeInfo(ctx, fieldId);
  return info != null && info.own === true && info.overrides === true;
}
// Whom an overriding value shadows — the "Reset to inherited (from …)" target.
function cascadeOverrideSourceLabel(ctx: RailRowContext, fieldId: string): string {
  return cascadeNodeLabel(ctx, cascadeInfo(ctx, fieldId)?.inherited_source_id ?? null);
}

// Clear-to-default (#522): the intra-project twin of #517's layer reset.
function isOwnClearable(ctx: RailRowContext, fieldId: string): boolean {
  const field = ctx.schema.fields[fieldId];
  const entryIsInherited = ctx.inheritedFromLabel !== null;
  // status has its own "(no status)" control; computed is read-only;
  // intrinsics never reach this loop — the pure gate encodes all of that.
  return isFieldOwnClearable({
    fieldId,
    fieldExists: field != null,
    fieldType: field?.type,
    fieldCategory: field?.category,
    entryIsInherited,
    isOverridden: isOverridden(ctx, fieldId),
    hasStoredValue: fieldId in ctx.metadata,
  });
}
// The default a cleared field falls back to, named for the chip/tooltip so the
// gesture "shows what the default is" (#522). Empty when the field defines no
// default — reverting then simply unsets it.
function defaultHint(ctx: RailRowContext, fieldId: string): string {
  const field = ctx.schema.fields[fieldId];
  const raw = metadataValueString(field?.default ?? undefined);
  // A select's default is named by its option label, as the row shows it —
  // "One hop", not "one_hop" (#1900).
  return field?.options?.find((option) => option.value === raw)?.label ?? raw;
}

function displayValue(ctx: RailRowContext, fieldId: string): MetadataValue {
  if (isMutated(ctx, fieldId)) return ctx.effectiveOverrides?.[fieldId] ?? "";
  const flipped = ctx.compare?.fields[fieldId];
  // A lore-proposal review (`resolve`) always shows the proposed `was` — the
  // candidate you click to adopt; snapshot compare shows the uniform `side`.
  if (flipped) return (flipped[ctx.compare?.resolve ? "was" : (ctx.compare?.side as "now" | "was")] ?? "") as MetadataValue;
  // A cascade field the scene doesn't own shows its RESOLVED (inherited) value —
  // it isn't in `metadata` (absence is what makes it inherit), so read it from the
  // fold (ADR-0079); editing writes it through as this node's own value.
  if (isCascadeInherited(ctx, fieldId)) return cascadeInfo(ctx, fieldId)?.value ?? "";
  return ctx.metadata[fieldId];
}

/** Whether this field differs from the parked snapshot / proposal. Colour only. */
function isFlipped(ctx: RailRowContext, fieldId: string): boolean {
  return ctx.compare != null && fieldId in ctx.compare.fields;
}

/** A flipped field under the interactive lore-proposal lens — rendered as a
 *  click-to-adopt candidate rather than a passive one-sided value. */
function isFlipResolve(ctx: RailRowContext, fieldId: string): boolean {
  return ctx.compare?.resolve != null && isFlipped(ctx, fieldId);
}

/** Whether an interactive flip has been adopted (take the proposed value). */
function isFlipAdopted(ctx: RailRowContext, fieldId: string): boolean {
  return ctx.compare?.resolve?.adopted(fieldId) ?? false;
}

/** The entry's current value of a flipped field, for the "Current: …" hint —
 *  the row shows the proposed candidate, so the author needs to see what it
 *  would replace. The candidate side already reads as resolved names, so the
 *  "Current:" side must match rather than fall back to a bare id / raw record:
 *  a tag-vocabulary `entity_ref_list` flip (#1797, ADR-0082 §2) resolves its
 *  ids through `tagTitleById`; a reference-keyed `list` flip (#2168, ADR-0089
 *  §6) names each target and appends the item's member detail, the same shape
 *  ListValueEditor renders on the candidate side. */
function flipCurrentHint(ctx: RailRowContext, fieldId: string): string {
  const field = ctx.schema.fields[fieldId];
  const value = ctx.compare?.fields[fieldId]?.now as MetadataValue;
  if (field?.type === "entity_ref_list" && Array.isArray(value)) {
    return value.map((id) => ctx.tagTitleById.get(String(id)) ?? String(id)).join(", ");
  }
  if (keyedListKeyMember(field) && Array.isArray(value)) {
    return value
      .map((item) => {
        const id = listItemKey(field, item);
        // Name the target, else its id; an orphaned item (blank key, ADR-0089
        // §9) has neither. `||` so an empty/absent title still falls to the id.
        const name = (id ? ctx.resolveListMemberTitle?.(id) : null) || id || "(orphaned)";
        const detail = itemMemberDetail(field, item);
        return detail ? `${name} · ${detail}` : name;
      })
      .join(", ");
  }
  return metadataValueString(value);
}

// Reference fields render inline pills through the controlled ReferencePicker
// (#1732): a single `entity_ref` sits compact on the value line, an
// `entity_ref_list` wraps across the wide value line.
function isRefFieldType(field: MetadataFieldDefinition): boolean {
  return field.type === "entity_ref" || field.type === "entity_ref_list";
}

// Wide field types take the full rail width (control wraps below the name);
// compact types keep their control inline on the right. See MetadataPanel's
// prior comment history (#1810, #1949) for the full reasoning per type.
function isWide(ctx: RailRowContext, field: MetadataFieldDefinition, fieldId: string): boolean {
  if (isListIndex(ctx, field) || isSectionIndex(ctx, field)) return false;
  // A tags field (#2007) is one mono line under its name, at rest and while
  // editing alike (#2059): wide always, so the row has ONE shape — it used to
  // sit inline while short and wrap once long, and its edit state jumped
  // between name-left / input-right and three lines as the tokens grew.
  if (isTagListField(field, ctx.schema)) return true;
  const populated = isMetadataValuePresent(displayValue(ctx, fieldId));
  return (
    (field.type === "long_text" && !ctx.sectionsInBody) ||
    field.type === "list" ||
    (field.type === "entity_ref_list" && populated) ||
    (field.type === "multi_select" && (field.options.length > 0 || populated))
  );
}

// #2009: a long_text row becomes an index row when its editor lives in a body
// section instead of the rail; #2043: so does a list whose items carry prose
// (its items are the body's repeating sub-sections).
function isSectionIndex(ctx: RailRowContext, field: MetadataFieldDefinition): boolean {
  return ctx.sectionsInBody && (field.type === "long_text" || listHasProseItems(field));
}

// The list-section index row's line: the item count ("5 items"); "" when
// empty (the row reads "empty" through the same branch as a long_text row).
function listSectionSummary(ctx: RailRowContext, fieldId: string): string {
  const value = displayValue(ctx, fieldId);
  const count = Array.isArray(value) ? value.length : 0;
  if (count === 0) return "";
  return count === 1 ? "1 item" : `${count} items`;
}

// #2010: an entity_ref_list row becomes an index row when its editor lives in
// a body tab instead of the rail. #2072/ADR-0089 §6: a reference-keyed `list`
// routes here too — the key outranks the prose gate (`listHasProseItems`,
// bodySections.ts), so a relationships-style field is a list-index row
// whether or not its items carry prose. A tags field never routes here — it
// keeps its own mono-line treatment (#2007) regardless of `listsInBody`.
function isListIndex(ctx: RailRowContext, field: MetadataFieldDefinition): boolean {
  if (!ctx.listsInBody || isTagListField(field, ctx.schema)) return false;
  return field.type === "entity_ref_list" || !!keyedListKeyMember(field);
}

// The list-index row's summary line: the total count, then a per-entry-type
// breakdown in first-appearance order ("12 · 5 Characters, 4 Locations"). An
// id `resolveListMemberType` can't resolve counts as "missing" — the same
// "unresolved but still countable" treatment ReferencePicker's own pill gives
// a stale/broken ref, just folded into the summary instead of a row of its own.
function listSummary(ctx: RailRowContext, fieldId: string): string {
  const value = displayValue(ctx, fieldId);
  const field = ctx.schema.fields[fieldId];
  const ids = Array.isArray(value)
    ? value.map((v) => listItemKey(field, v)).filter((id): id is string => id != null)
    : [];
  if (ids.length === 0) return "";
  const order: string[] = [];
  const counts = new Map<string, number>();
  for (const id of ids) {
    const entryType = ctx.resolveListMemberType?.(id) ?? null;
    const label = entryType ? (ctx.schema.entry_types[entryType]?.name ?? entryType) : "missing";
    if (!counts.has(label)) {
      counts.set(label, 0);
      order.push(label);
    }
    counts.set(label, counts.get(label)! + 1);
  }
  const parts = order.map((label) => `${counts.get(label)} ${label}`);
  // One type: `2 Character` — the leading total would only repeat it.
  if (parts.length === 1) return parts[0];
  return `${ids.length} · ${parts.join(", ")}`;
}

// An empty row recedes (#1884 slice 3): label + glyph in --text-3. `color`
// always shows an effective swatch and a valueless `computed` row is not
// rendered at all, so neither is ever "empty" to the eye.
function isRowEmpty(ctx: RailRowContext, field: MetadataFieldDefinition, fieldId: string): boolean {
  if (field.type === "color" || field.type === "computed") return false;
  // `status` is stored off `metadata` (shell state) — read the prop this row
  // itself renders, not the metadata bag.
  if (fieldId === "status") return !ctx.status;
  // A SELECT with a declared default shows that default when unset
  // (FieldValue/FieldValueEditor's required-select rule, #1421) — a value is
  // on screen, so not empty. Only selects render a default this way.
  if (field.type === "select" && field.default !== undefined && field.default !== null && field.default !== "") return false;
  return !isMetadataValuePresent(displayValue(ctx, fieldId));
}

// A folding list field (#1884 slice 2): a non-empty `entity_ref_list` gets the
// gutter's disclosure caret. A tags field (#2007) never folds — it is one mono
// line, not a pill list, so it has nothing to disclose.
function isFoldableList(ctx: RailRowContext, field: MetadataFieldDefinition, fieldId: string): boolean {
  if (isTagListField(field, ctx.schema)) return false;
  if (isListIndex(ctx, field)) return false;
  return field.type === "entity_ref_list" && isMetadataValuePresent(displayValue(ctx, fieldId));
}

// Read at rest, edit on demand (#1884 slice 4). A single reference joins
// them (#2058): at rest its picker (pill + trigger) wrapped to two lines in
// any narrow slot; the rest face is the resolved name on one line.
const SCALAR_TYPES = new Set(["text", "number", "boolean", "select", "multi_select", "date", "entity_ref"]);
function isScalarRow(ctx: RailRowContext, field: MetadataFieldDefinition, fieldId: string): boolean {
  // A field-level read-only (e.g. ai_temperature on a no-sampling model) has
  // no edit state to toggle into — it stays the plain read-only editor.
  if (fieldReadOnly(ctx, fieldId) || isFlipResolve(ctx, fieldId)) return false;
  return fieldId === "status" || SCALAR_TYPES.has(field.type);
}
// Single-pick controls: the pick IS the edit, so the row returns to rest on
// change. A single reference resolves in one pick like a select (#2058).
function closesOnPick(field: MetadataFieldDefinition, fieldId: string): boolean {
  return fieldId === "status" || field.type === "select" || field.type === "boolean" || field.type === "entity_ref";
}

/** Build the row model for one field. Only called once `rendersRow(fieldId)`
 *  is true (the panel's own guard), so `ctx.schema.fields[fieldId]` exists. */
export function buildRailRowModel(ctx: RailRowContext, fieldId: string): RailRowModel {
  const field = ctx.schema.fields[fieldId]!;
  const fieldLabel = effectiveFieldLabel(ctx.schema, ctx.entryType, fieldId);
  const value = displayValue(ctx, fieldId);

  const mutated = isMutated(ctx, fieldId);
  const overridden = isOverridden(ctx, fieldId);
  const flipped = isFlipped(ctx, fieldId);
  const flipResolve = isFlipResolve(ctx, fieldId);
  const flipAdopted = isFlipAdopted(ctx, fieldId);
  const flipWas = flipped && (ctx.compare?.resolve ? !flipAdopted : ctx.compare?.side === "was");
  const layerInherited = isLayerInherited(ctx, fieldId);
  const cascadeInherited = isCascadeInherited(ctx, fieldId);
  const cascadeOverridden = isCascadeOverridden(ctx, fieldId);
  const empty = isRowEmpty(ctx, field, fieldId);
  const scalar = isScalarRow(ctx, field, fieldId);
  const editing = ctx.openFieldId === fieldId;
  const wide = isWide(ctx, field, fieldId);
  const sectionIndex = isSectionIndex(ctx, field);
  const listIndex = isListIndex(ctx, field);
  const colorRow = field.type === "color";
  const isComputed = field.type === "computed";
  const isStatus = fieldId === "status";

  const inheritedTooltip = layerInherited && ctx.inheritedFromLabel
    ? `Inherited from ${ctx.inheritedFromLabel}`
    : cascadeInherited
      ? `Inherited from ${cascadeSourceLabel(ctx, fieldId)}`
      : undefined;

  const computedRaw = isComputed ? ctx.computedFieldString(fieldId) : "";
  const computedText = isComputed
    ? (field.options ?? []).find((option) => option.value === computedRaw)?.label ?? computedRaw
    : "";

  const statusValue = isStatus
    ? isMutated(ctx, "status")
      ? metadataValueString(ctx.effectiveOverrides?.["status"])
      : isFlipped(ctx, "status")
        ? metadataValueString(ctx.compare?.fields["status"]?.[ctx.compare?.side as "now" | "was"] as MetadataValue)
        : ctx.status
    : "";

  const colorValueRaw = colorRow ? metadataValueString(value) : "";

  // ADR-0095 §8 decision 5: only for a stop-editable text/long_text row —
  // every other row's control reads `value` (the effective display) as always.
  const stopEditValue =
    ctx.scrubbed && ctx.stopEditable(fieldId) && (field.type === "text" || field.type === "long_text")
      ? (ctx.stopEditValueFor?.(fieldId) ?? "")
      : undefined;

  return {
    field,
    fieldId,
    fieldLabel,
    iconClass: fieldIconClass(field),
    description: field.description || undefined,

    inherited: isInherited(ctx, fieldId),
    layerInherited,
    cascadeInherited,
    cascadeOverridden,
    mutated,
    overridden,
    flipped,
    flipWas,
    flipResolve,
    flipAdopted,
    empty,
    scalar,
    singleRef: field.type === "entity_ref",
    editing,
    wide,
    sectionIndex,
    wordCount: sectionIndex && field.type === "long_text" ? countWords(metadataValueString(value)) : 0,
    sectionSummary: sectionIndex && field.type === "list" ? listSectionSummary(ctx, fieldId) : null,
    listIndex,
    listSummary: listIndex ? listSummary(ctx, fieldId) : "",
    colorRow,
    foldableList: isFoldableList(ctx, field, fieldId),
    fieldExpanded: ctx.fieldExpanded(fieldId),
    isStatus,
    isComputed,
    isTagList: isTagListField(field, ctx.schema),
    isRef: isRefFieldType(field),
    closesOnPick: closesOnPick(field, fieldId),
    showTempNote: fieldId === "ai_temperature" && ctx.temperatureUnsupported,

    value,
    statusValue,
    computedText,
    defaultHint: defaultHint(ctx, fieldId),
    inheritedTooltip,
    cascadeSourceLabel: cascadeSourceLabel(ctx, fieldId),
    cascadeOverrideSourceLabel: cascadeOverrideSourceLabel(ctx, fieldId),
    sourceLayerLabel: ctx.sourceLayerLabel,
    flipCurrentHint: flipCurrentHint(ctx, fieldId),
    tagFlipItems: isTagFlipField(field, ctx.schema) ? tagFlipItemsFor(value, ctx.tagTitleById) : null,
    colorValue: colorRow ? colorValueRaw || null : null,
    colorPlaceholderHex: colorRow ? resolveColor(null, ctx.entryType, ctx.documentKind, ctx.schema)?.hex ?? null : null,
    colorUnset: colorRow ? !colorValueRaw : false,
    tempClearedForModel: ctx.temperatureClearedForModel,

    fieldReadOnly: fieldReadOnly(ctx, fieldId),
    canClearOwn: ctx.canClearOwn,
    ownClearable: ctx.canClearOwn && isOwnClearable(ctx, fieldId) && !cascadeOverridden,
    canResetOverride: ctx.canResetOverride,
    canResetCascade: ctx.canClearOwn,
    stopEditValue,
  };
}

// Exported for MetadataPanel: the empty-fold partition (`isRowEmpty`,
// `isFlipped`/`isMutated` exempt a flipped/mutated row from folding even when
// its value reads empty), `rendersRow`'s intrinsic-flip carve-out
// (`isFlipResolve`) and its front-matter carve-out (#2054: no index rows,
// `isSectionIndex`/`isListIndex`) all still live in the panel.
export { isRowEmpty, isFlipped, isMutated, isFlipResolve, isSectionIndex, isListIndex };
