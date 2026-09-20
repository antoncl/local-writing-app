<script lang="ts" module>
  // Shared row model + field-scoping logic for the two mutation dialogs
  // (/mutate authoring + the set editor). One row = one (field, op, value)
  // change; the same shape a saved set stores and a marker carries.
  import { keyedListKeyMember } from "@/lib/editor-core/keyedList";
  import type { KeyedListShape } from "@/lib/editor-core/mutationListEdit";
  import type { MetadataFieldDefinition, MetadataSchema, MetadataValue } from "@/lib/types";

  export type MutationRow = {
    field: string;
    op: string;
    value: MetadataValue;
    /** List-edit mode for a collection row (#71, ADR-0017): the effective
     *  membership at the authoring position that the widget was seeded with.
     *  When present the row shows the field's own list widget (no op selector)
     *  and a live +/− chip strip of the records the diff will emit. Absent in
     *  the set editor, which keeps authoring literal (field, op, value) rows —
     *  a template has no entity, so there is no baseline to diff against. */
    baseline?: string[];
    /** Item-edit mode for a reference-keyed list row (ADR-0089 §2/§5, #2072):
     *  the effective ITEMS at the authoring position — the same idea as
     *  `baseline` but for a `list` field's folded item-map shape, so its own
     *  `ListValueEditor` renders directly (no per-element expansion) and the
     *  diff emits `add`/`replace`/`remove` records per key/member. Mutually
     *  exclusive with `baseline`. */
    itemBaseline?: Record<string, MetadataValue>[];
  };

  export const COLLECTION_TYPES = ["multi_select", "entity_ref_list"];
  export const isCollectionType = (type: string) => COLLECTION_TYPES.includes(type);

  // Scalar text types that accept an additive `add` (append) op — the backend
  // resolves base + appends in start order (ADR-0009 amendment).
  export const TEXT_APPEND_TYPES = ["text", "long_text"];
  export const isTextAppendType = (type: string) => TEXT_APPEND_TYPES.includes(type);

  // Name-ish fields carry the scene-granular resolution caveat (#61).
  const NAME_FIELDS = ["title", "name", "aliases"];
  export const isNameField = (id: string) => NAME_FIELDS.includes(id);

  // Intrinsic node fields (not schema fields) that are always mutable.
  export const INTRINSIC_FIELDS: Array<{ id: string; def: MetadataFieldDefinition }> = [
    { id: "title", def: { name: "Title (name)", type: "text", options: [] } as MetadataFieldDefinition },
    { id: "body", def: { name: "Body", type: "long_text", options: [] } as MetadataFieldDefinition },
  ];

  export type FieldOption = { id: string; label: string; def: MetadataFieldDefinition };

  // Serialize one row value to a marker string (shared by both mutation
  // dialogs). Collections are never passed here as a whole array — they author
  // as single-element add/remove rows — so a bare String() is comma-safe.
  export function toMarkerString(value: MetadataValue): string {
    if (value === null || value === undefined) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value);
  }

  // The default op for a freshly (re)targeted row: collections author as
  // add/remove (ADR-0017, no whole-list replace in the UI), everything else
  // starts at replace.
  export function defaultOpForField(fieldId: string, schema: MetadataSchema | null): string {
    return isCollectionType(fieldDefFor(fieldId, schema).type) ? "add" : "replace";
  }

  // The mutable fields for an entry type: intrinsic title/body + its resolved
  // schema fields, minus computed (derived) and most `list` fields (#698: the
  // marker grammar is string-typed — a structured item has no honest
  // representation in a mutation row, and String() would write
  // "[object Object]" into the scene body). A reference-keyed list (ADR-0089
  // §2/§5) is the one `list` shape that DOES have a record grammar — offered
  // only when `allowItemLists` is set, since it needs an entity baseline to
  // diff against (the /mutate authoring form has one; the set editor, which
  // authors a template with no entity, does not and keeps skipping every list).
  export function buildFieldOptions(
    schema: MetadataSchema | null,
    entryType: string,
    allowItemLists = false,
  ): FieldOption[] {
    const opts = INTRINSIC_FIELDS.map((f) => ({ id: f.id, label: f.def.name, def: f.def }));
    const seen = new Set(opts.map((o) => o.id));
    for (const id of schema?.entry_types[entryType]?.fields ?? []) {
      const def = schema?.fields[id];
      if (!def || def.type === "computed") continue;
      if (def.type === "list" && !(allowItemLists && keyedListKeyMember(def))) continue;
      // The resolver injects the intrinsic identity triple (title/entry_type/id)
      // into every type's resolved membership (schema.py). title is already
      // seeded above and entry_type/id aren't author-mutable, so skip anything
      // intrinsic; the seen-guard then keeps any duplicate id out of the keyed
      // {#each} (a duplicate `title` key crashes the whole editor render).
      if (def.category === "intrinsic" || seen.has(id)) continue;
      seen.add(id);
      opts.push({ id, label: def.name ?? id, def });
    }
    return opts;
  }

  export function fieldDefFor(fieldId: string, schema: MetadataSchema | null): MetadataFieldDefinition {
    return (
      schema?.fields[fieldId] ??
      INTRINSIC_FIELDS.find((f) => f.id === fieldId)?.def ??
      ({ name: fieldId, type: "text", options: [] } as MetadataFieldDefinition)
    );
  }

  // The item-widget field def for an add/remove op: a collection resolves to
  // its single-element type (entity_ref_list → entity_ref, multi_select →
  // select), so each add/remove marker carries one element. A list-edit row
  // (baseline present, #71) always uses the field's own widget — as does an
  // item-edit row (itemBaseline present, ADR-0089 §5): `def.type === "list"`
  // already fails `isCollectionType`, so it falls through unchanged either
  // way and `FieldValueEditor` mounts `ListValueEditor` directly.
  export function effectiveFieldDef(row: MutationRow, def: MetadataFieldDefinition): MetadataFieldDefinition {
    if (!isCollectionType(def.type) || row.baseline !== undefined || row.op === "replace") return def;
    if (def.type === "entity_ref_list") return { ...def, type: "entity_ref" };
    return { ...def, type: "select" };
  }

  // A reference-keyed list's shape (ADR-0089 §5), read off the resolver-stamped
  // `item_members`: the key member (empty string when the field isn't one —
  // callers only reach here for an item row, where it always resolves) and
  // every member's declared type, for `keyedListRowsFromEdit`'s member diff.
  // Shared by the dialogs' chip/lock wiring and the authoring form's seeding.
  export function keyedShapeFor(def: MetadataFieldDefinition): KeyedListShape {
    const memberTypes: Record<string, string> = {};
    for (const member of def.item_members ?? []) memberTypes[member.key] = member.type;
    return { keyMember: keyedListKeyMember(def) ?? "", memberTypes };
  }
</script>

<script lang="ts">
  // The rows list itself: per row a header line (field picker or fixed label +
  // op selector + remove), with the value editor on its own full-width line
  // below the caption — long_text gets room instead of a squeezed inline slot.
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import {
    asItemList,
    asMembershipList,
    decodeItem,
    diffCollectionMembership,
    keyedListRowsFromEdit,
    splitMemberPath,
  } from "@/lib/editor-core/mutationListEdit";
  import type { LoreEntrySummary, PromptEntrySummary, StructureDocument } from "@/lib/types";

  let {
    rows,
    schema = null,
    entryType,
    fieldOptions,
    fieldEditable = true,
    showAdd = true,
    showNameFieldNote = false,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    implicitContextMatcher = null,
    onRowChange,
    onRowRemove,
    onRowAdd,
  }: {
    rows: MutationRow[];
    schema: MetadataSchema | null;
    entryType: string;
    fieldOptions: FieldOption[];
    /** False in marker-edit mode: the field is fixed, rows can't be added/removed. */
    fieldEditable?: boolean;
    showAdd?: boolean;
    /** Show the per-scene resolution caveat on name-ish fields (/mutate only). */
    showNameFieldNote?: boolean;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    onRowChange: (index: number, patch: Partial<MutationRow>) => void;
    onRowRemove?: (index: number) => void;
    onRowAdd?: () => void;
  } = $props();

  function labelFor(fieldId: string): string {
    return fieldOptions.find((f) => f.id === fieldId)?.label ?? fieldId;
  }

  function itemChipLabel(id: string): string {
    return loreEntries.find((e) => e.id === id)?.title ?? id;
  }

  type Chip = { op: "add" | "remove" | "replace"; label: string };

  // An item row's chips (ADR-0089 §5): the same add/replace/remove records
  // `submit` will emit, rendered as "+ <target>" / "− <target>" /
  // "<member> → value" — the reference-keyed twin of the flat-collection
  // chips below. `existing` is irrelevant here (chips never show an id), so
  // the diff runs against an empty reuse set.
  function itemEditChips(row: MutationRow): Chip[] {
    if (row.itemBaseline === undefined) return [];
    const def = fieldDefFor(row.field, schema);
    const keyed = keyedShapeFor(def);
    const edited = asItemList(row.value);
    const chips: Chip[] = [];
    for (const draft of keyedListRowsFromEdit(row.field, keyed, row.itemBaseline, edited, [])) {
      if (draft.op === "add") {
        const decoded = decodeItem(draft.value);
        const id = decoded ? String(decoded[keyed.keyMember] ?? "") : "";
        chips.push({ op: "add", label: itemChipLabel(id) });
      } else if (draft.op === "remove") {
        chips.push({ op: "remove", label: itemChipLabel(draft.value) });
      } else {
        const path = splitMemberPath(draft.field, row.field);
        if (!path) continue;
        const memberName = def.item_members?.find((m) => m.key === path.member)?.name ?? path.member;
        chips.push({ op: "replace", label: `${memberName} → ${draft.value}` });
      }
    }
    return chips;
  }

  // List-edit transparency chips (#71): the add/remove records the diff will
  // emit, kept visible while the list is edited — the author still authors
  // deltas; the widget just compiles them. Entity-ref values display as the
  // entry's title (the stored record still carries the id).
  function listEditChips(row: MutationRow): Chip[] {
    if (row.itemBaseline !== undefined) return itemEditChips(row);
    if (row.baseline === undefined) return [];
    const isRefList = fieldDefFor(row.field, schema).type === "entity_ref_list";
    const label = (value: string) =>
      isRefList ? (loreEntries.find((e) => e.id === value)?.title ?? value) : value;
    const { adds, removes } = diffCollectionMembership(row.baseline, asMembershipList(row.value));
    return [
      ...adds.map((value) => ({ op: "add" as const, label: label(value) })),
      ...removes.map((value) => ({ op: "remove" as const, label: label(value) })),
    ];
  }

  // The locked/unique member forwarded to a keyed item row's `ListValueEditor`
  // (ADR-0089 §2): the key never changes once an item exists, and a target
  // can't be picked twice — both are display-only guards, not validation.
  function itemLockedKeys(row: MutationRow): { member: string; keys: string[] } | undefined {
    if (row.itemBaseline === undefined) return undefined;
    const keyed = keyedShapeFor(fieldDefFor(row.field, schema));
    if (!keyed.keyMember) return undefined;
    const keys = row.itemBaseline
      .map((item) => item[keyed.keyMember])
      .filter((value): value is string => typeof value === "string" && value.length > 0);
    return { member: keyed.keyMember, keys };
  }

  function itemUniqueMember(row: MutationRow): string | undefined {
    if (row.itemBaseline === undefined) return undefined;
    return keyedShapeFor(fieldDefFor(row.field, schema)).keyMember || undefined;
  }
</script>

<div class="mrow-list">
  {#each rows as row, i (i)}
    <div class="mrow">
      <div class="mrow-head">
        {#if fieldEditable}
          <select
            class="mrow-field"
            aria-label="Field"
            value={row.field}
            onchange={(e) =>
              onRowChange(i, {
                field: e.currentTarget.value,
                op: defaultOpForField(e.currentTarget.value, schema),
                value: "",
              })}
          >
            {#if row.field && !fieldOptions.some((f) => f.id === row.field)}
              <!-- An existing row can target a field the roster now excludes
                   (e.g. retyped to `list`, #698) — keep its target visible
                   instead of a blank select the author can't interpret. -->
              <option value={row.field} disabled>{labelFor(row.field)} — not mutable</option>
            {/if}
            {#each fieldOptions as f (f.id)}
              <option value={f.id}>{f.label}</option>
            {/each}
          </select>
        {:else}
          <span class="mrow-label">{labelFor(row.field)}</span>
        {/if}
        {#if isCollectionType(fieldDefFor(row.field, schema).type)}
          <!-- List-edit rows (#71) drop the op selector: the author edits the
               list; the diff emits the add/remove records (chips below). The
               selector remains only where no baseline exists (set editor). -->
          {#if row.baseline === undefined}
            <!-- Collections author as add/remove single-element rows (ADR-0017);
                 no whole-list "replace" in the UI — it packs multiple elements
                 into one comma-joined value that can't round-trip a member
                 containing a comma. Hand-authored replace markers must
                 url-encode internal commas (docs/mutations.md). -->
            <select
              class="mrow-op"
              aria-label="{labelFor(row.field)} operation"
              value={row.op}
              onchange={(e) => onRowChange(i, { op: e.currentTarget.value, value: "" })}
            >
              <option value="add">Add item</option>
              <option value="remove">Remove item</option>
            </select>
          {/if}
        {:else if isTextAppendType(fieldDefFor(row.field, schema).type)}
          <!-- Same string shape either way, so the typed value survives an op flip. -->
          <select
            class="mrow-op"
            aria-label="{labelFor(row.field)} operation"
            value={row.op}
            onchange={(e) => onRowChange(i, { op: e.currentTarget.value })}
          >
            <option value="replace">Replace</option>
            <option value="add">Append</option>
          </select>
        {/if}
        <span class="mrow-spacer"></span>
        {#if fieldEditable && onRowRemove}
          <button type="button" class="mrow-remove" title="Remove row" aria-label="Remove row" onclick={() => onRowRemove(i)}>×</button>
        {/if}
      </div>
      <div class="mrow-value">
        <FieldValueEditor
          field={effectiveFieldDef(row, fieldDefFor(row.field, schema))}
          value={row.value}
          ariaLabel={labelFor(row.field)}
          loreEntries={loreEntries}
          promptEntries={promptEntries}
          structure={structure}
          researchStructure={researchStructure}
          implicitContextMatcher={implicitContextMatcher}
          lockedKeys={itemLockedKeys(row)}
          uniqueMember={itemUniqueMember(row)}
          onChange={(v) => onRowChange(i, { value: v })}
        />
      </div>
      {#if row.baseline !== undefined || row.itemBaseline !== undefined}
        {@const chips = listEditChips(row)}
        {#if chips.length > 0}
          <div class="mrow-chips" aria-label="Derived records">
            {#each chips as chip (chip.op + chip.label)}
              <span class="mrow-chip" class:remove={chip.op === "remove"}>
                {#if chip.op === "add"}+{:else if chip.op === "remove"}−{/if}{chip.label}
              </span>
            {/each}
          </div>
        {:else}
          <p class="mrow-chips-empty">No changes to this list yet.</p>
        {/if}
      {/if}
      {#if showNameFieldNote && isNameField(row.field)}
        <p class="mrow-note">
          Name changes resolve <strong>per scene</strong>: within the scene of the change,
          auto-detection uses one name for the whole scene.
          <a
            href="https://github.com/antoncl/local-writing-app/blob/master/docs/mutations.md#how-resolution-works--and-its-one-limit"
            target="_blank"
            rel="noopener"
          >How resolution works ↗</a>
        </p>
      {/if}
    </div>
  {/each}
  {#if showAdd && onRowAdd}
    <button type="button" class="mrow-add" title="Add field change" aria-label="Add field change" onclick={onRowAdd}>+</button>
  {/if}
</div>

<style>
  .mrow-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
    margin-bottom: 12px;
  }
  /* Each field-change row wears a hairline frame (#70): under the entity
     header the framed rows read as the unit — a frame, not a card explosion. */
  .mrow {
    display: flex;
    flex-direction: column;
    gap: 6px;
    border: 1px solid var(--divider, var(--border));
    border-radius: 8px;
    background: var(--inset, color-mix(in oklab, var(--text) 3%, transparent));
    padding: 8px 10px;
  }
  .mrow-head {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .mrow-label {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
  }
  .mrow-field,
  .mrow-op {
    padding: 4px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: var(--fs-md);
  }
  .mrow-op {
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  .mrow-spacer {
    flex: 1 1 auto;
  }
  .mrow-remove {
    flex: none;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-3);
    border-radius: 4px;
    padding: 0 8px;
    cursor: pointer;
  }
  .mrow-value {
    display: flex;
  }
  .mrow-value > :global(*) {
    flex: 1 1 auto;
    min-width: 0;
  }
  /* Inside the (resizable) mutation dialogs the long-text editor is capped so
     a long Body scrolls within the row instead of pushing the buttons off the
     dialog. The widget itself no longer caps or scrolls (#1884: in the rail it
     takes its natural height), so the overflow is this host's to set. */
  .mrow-value :global(.metadata-long-text-body) {
    max-height: 48vh;
    overflow: auto;
  }
  .mrow-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .mrow-chip {
    font-size: var(--fs-sm);
    padding: 1px 7px;
    border-radius: 999px;
    border: 1px solid color-mix(in oklab, var(--mutation-color) 45%, transparent);
    background: color-mix(in oklab, var(--mutation-color) 12%, transparent);
    color: var(--text-2);
    white-space: nowrap;
  }
  .mrow-chip.remove {
    border-style: dashed;
    text-decoration: line-through;
    text-decoration-color: color-mix(in oklab, var(--text-3) 60%, transparent);
  }
  .mrow-chips-empty {
    margin: 0;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .mrow-note {
    margin: 0;
    font-size: var(--fs-sm);
    line-height: 1.35;
    color: var(--text-3);
  }
  .mrow-note a {
    color: var(--accent);
    white-space: nowrap;
  }
  .mrow-add {
    align-self: flex-start;
    background: transparent;
    border: 1px dashed var(--border);
    border-radius: 6px;
    padding: 6px 10px;
    color: var(--text-2);
    font: inherit;
    cursor: pointer;
  }
</style>
