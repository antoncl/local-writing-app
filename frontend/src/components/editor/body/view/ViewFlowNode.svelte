<!--
  One custom Svelte Flow node for the view designer (0.5.0 step 3, #80;
  approachable roles for #91). A single component renders every kind — injector
  (leaves + All), filter, operation (Venn combinators), sorter, highlight, and
  the View (output) node with its named handles — switching on `data.kind`, so
  the flow registers one node type. Difference exposes explicit keep/remove
  ports (the confusable op, doc §1.2). Config is edited inline and written back
  through the designer context.
-->
<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import ViewGlyph from "./ViewGlyph.svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import { inputArity, outputPayload, type GraphNodeKind, type PredicateKind, type ViewGraphNode, type ViewHandle, type ViewNodeData } from "@/lib/views/viewGraph";
  import { useDesignerContext } from "./designerContext";
  import type { MetadataFieldType, NodePickerRef, ViewGroupByLevel, ViewSort } from "@/lib/types";

  // Svelte Flow passes the node's id/data/selection state as props.
  let { id, data, selected = false }: { id: string; data: { kind: GraphNodeKind; cfg: ViewNodeData }; selected?: boolean } =
    $props();

  const getCtx = useDesignerContext();
  let ctx = $derived(getCtx());
  let kind = $derived(data.kind);
  let cfg = $derived(data.cfg ?? {});
  let arity = $derived(inputArity(kind));
  // A kind with a single entry_type (e.g. assistant) makes Type/Type+subtypes
  // predicates noise — offer them only when there's a real choice (#91).
  let hasTypeChoice = $derived((ctx.entryTypes?.length ?? 0) > 1);
  // The wire this node's `out` handle emits: a scalar `field_of` yields a
  // value-set, everything else a node-set (ADR-0031 §D). The source handle is
  // tinted to match so handle + pipe read as one wire — and a `field_of` shows
  // whether it's projecting nodes or values before you even wire it up.
  let emitsValueSet = $derived(
    outputPayload({ id, kind, position: { x: 0, y: 0 }, data: cfg } as ViewGraphNode, (key: string) => ctx.fieldByKey(key)?.type ?? null) ===
      "value-set",
  );
  // Field roster for THIS node's pickers — anchored to the kind of its input set
  // (ADR-0031 §F), so downstream of a cross-kind `field_of` the dropdowns offer
  // the projected kind's fields instead of the view anchor's.
  let nodeFields = $derived(ctx.fieldsFor?.(id) ?? ctx.fields);

  const LABELS: Record<GraphNodeKind, string> = {
    output: "View result",
    all: "All",
    filter: "Filter",
    sorter: "Sort",
    union: "Union",
    intersect: "Intersect",
    difference: "Difference",
    complement: "Complement",
    nest: "Nest",
    field_of: "Field of",
    self: "This entry",
    highlight: "Highlight",
    type: "Type is",
    descendants_of: "Type & subtypes",
    tagged: "Tagged",
    field: "Field",
    hand_picked: "Hand-picked",
    view_ref: "Saved view",
  };

  function patch(next: Partial<ViewNodeData>) {
    ctx.updateNodeData(id, next);
  }

  // --- predicate-kind options for a Filter (drop Type when there's one type) ---
  let predicateKinds = $derived<{ value: PredicateKind; label: string }[]>(
    [
      ...(hasTypeChoice
        ? ([
            { value: "type", label: "Type is" },
            { value: "descendants_of", label: "Type & subtypes" },
          ] as { value: PredicateKind; label: string }[])
        : []),
      { value: "tagged", label: "Tagged" },
      { value: "field", label: "Field" },
    ],
  );
  let filterKind = $derived<PredicateKind>(cfg.filter_kind ?? (hasTypeChoice ? "type" : "tagged"));
  let filterMode = $derived<"keep" | "drop">(cfg.filter_mode ?? "keep");

  // --- field predicate helpers (comparator adapts to the field's datatype) ---
  let fieldKey = $derived(cfg.field?.key ?? "");
  let fieldOp = $derived<FieldOp>(cfg.field?.op ?? "overlap");
  let fieldDef = $derived(fieldKey ? ctx.fieldByKey(fieldKey) : null);
  let opNeedsValue = $derived(fieldOp !== "set" && fieldOp !== "unset");
  function setField(next: Partial<NonNullable<ViewNodeData["field"]>>) {
    const merged = { key: fieldKey, op: fieldOp, value: cfg.field?.value, ...next };
    patch({ field: merged });
  }

  // --- promote-in-place (#184 Phase 1b, ADR-0032): a field value slot ⇄ a named
  // runtime formal. Promoting freezes the field/op (authoring) and turns the
  // authored literal into an overridable default (runtime); the predicate value
  // becomes `{var: name}`. `name` keys on the node id so a view can carry two
  // formals over the same field. Lowering collects these into ViewSpec.params.
  let fieldParam = $derived(cfg.field_param ?? null);
  let isPromoted = $derived(fieldParam != null);
  // #198: a promoted formal with no default is UNBOUND — by default its predicate
  // is inactive (under (a) "unset = show everything" it imposes no constraint:
  // pass-through in a keep, removes nothing in a drop/complement). Surface that
  // no-op state in the designer so a power user can see the node is currently
  // inert rather than silently filtering. `set`/`unset` carry no operand, so they
  // are never inactive; an unpromoted node's fixed literal is always bound.
  let isInactiveParam = $derived(isPromoted && opNeedsValue && isEmptyValue(fieldParam?.default));
  function isEmptyValue(v: unknown): boolean {
    return v == null || v === "" || (Array.isArray(v) && v.length === 0);
  }
  function promoteField() {
    const name = fieldKey ? `${fieldKey}_${id}` : `param_${id}`;
    const label = fieldDef?.name || fieldKey || "Parameter";
    patch({ field: { key: fieldKey, op: fieldOp, value: { var: name } }, field_param: { name, label, default: cfg.field?.value ?? null } });
  }
  function demoteField() {
    patch({ field: { key: fieldKey, op: fieldOp, value: cfg.field_param?.default ?? null }, field_param: undefined });
  }
  function setParamLabel(label: string) {
    if (cfg.field_param) patch({ field_param: { ...cfg.field_param, label } });
  }
  function setParamDefault(v: unknown) {
    if (cfg.field_param) patch({ field_param: { ...cfg.field_param, default: v } });
  }
  // A valueless op (is set / is empty) has no slot to promote — demote when
  // switching into one so a stale formal can't leak into the parameter strip.
  function changeOp(op: FieldOp) {
    if ((op === "set" || op === "unset") && isPromoted) {
      patch({ field: { key: fieldKey, op, value: undefined }, field_param: undefined });
    } else {
      setField({ op });
    }
  }

  type FieldOp = NonNullable<ViewNodeData["field"]>["op"];
  // Op enum collapsed 6→4 (ADR-0031 §E, #184): overlap/disjoint set-coerce both
  // sides and work for scalar and collection fields alike, so one menu serves
  // every type (the old per-type eq/neq vs includes/not_includes split is gone).
  const FIELD_OPS: { value: FieldOp; label: string }[] = [
    { value: "overlap", label: "any of" },
    { value: "disjoint", label: "none of" },
    { value: "set", label: "is set" },
    { value: "unset", label: "is empty" },
  ];

  // --- sorter helpers (#230 multi-level: an ordered list of keys ⇄ the `then`
  // chain). A key is title|field + dir; "manual" = the EMPTY list (input order). ---
  type SortKey = { by: "title" | "field"; field_key?: string; dir: "asc" | "desc" };
  function sortToList(sort: ViewSort | null | undefined): SortKey[] {
    const list: SortKey[] = [];
    for (let s: ViewSort | null | undefined = sort; s; s = s.then) {
      if (s.by === "title") list.push({ by: "title", dir: s.dir ?? "asc" });
      else if (s.by === "field") list.push({ by: "field", field_key: s.field_key, dir: s.dir ?? "asc" });
      // "manual" carries no ordering key
    }
    return list;
  }
  function listToSort(list: SortKey[]): ViewSort {
    // Fold the list into a right-nested `then` chain; empty ⇒ manual order.
    let chain: ViewSort | null = null;
    for (let i = list.length - 1; i >= 0; i--) {
      const k = list[i];
      chain = {
        by: k.by,
        dir: k.dir,
        ...(k.by === "field" ? { field_key: k.field_key || undefined } : {}),
        ...(chain ? { then: chain } : {}),
      };
    }
    return chain ?? { by: "manual" };
  }
  let sortKeys = $derived<SortKey[]>(sortToList(cfg.sort));
  function commitSortKeys(list: SortKey[]) {
    patch({ sort: listToSort(list) });
  }
  function addSortKey() {
    commitSortKeys([...sortKeys, { by: "title", dir: "asc" }]);
  }
  function setSortKey(i: number, next: Partial<SortKey>) {
    commitSortKeys(
      sortKeys.map((k, j) => {
        if (j !== i) return k;
        const merged = { ...k, ...next };
        if (merged.by !== "field") merged.field_key = undefined;
        return merged;
      }),
    );
  }
  function removeSortKey(i: number) {
    commitSortKeys(sortKeys.filter((_, j) => j !== i));
  }
  function moveSortKey(i: number, delta: -1 | 1) {
    const j = i + delta;
    if (j < 0 || j >= sortKeys.length) return;
    const next = [...sortKeys];
    [next[i], next[j]] = [next[j], next[i]];
    commitSortKeys(next);
  }

  // --- nest (relational op) match-rule helpers ---
  let matchField = $derived(cfg.match?.field ?? "");
  let matchDir = $derived<NonNullable<ViewNodeData["match"]>["direction"]>(cfg.match?.direction ?? "child_to_parent");
  let matchBy = $derived<NonNullable<ViewNodeData["match"]>["by"]>(cfg.match?.by ?? "ref");
  // Joinable field types (ADR-0028 §B): refs (by id) or text/tags (by title). A
  // number/boolean/date/computed/color field is never a tree edge, so keep the
  // picker to the types that can actually carry a parent↔child link. (context_pick
  // is a prompt-runtime input, not a metadata field type, so it can't appear here.)
  const NEST_JOINABLE_TYPES: MetadataFieldType[] = [
    "entity_ref",
    "entity_ref_list",
    "tags",
    "select",
    "multi_select",
    "text",
    "long_text",
  ];
  // Intrinsic identity fields (id/title/entry_type) are top-level node
  // properties, not metadata refs, so they can't carry a parent↔child link —
  // drop them from the join picker. Category is the resolver-stamped signal
  // (ADR-0029 §D).
  let joinableFields = $derived(
    nodeFields.filter((f) => f.def.category !== "intrinsic" && NEST_JOINABLE_TYPES.includes(f.def.type)),
  );
  function setMatch(next: Partial<NonNullable<ViewNodeData["match"]>>) {
    patch({ match: { field: matchField, direction: matchDir, by: matchBy, ...next } });
  }

  // --- field_of (forward projection, #184 ADR-0031 §D) ---
  // The 0.7.0 cut projects to a NODE-SET only: the input kind's reference fields
  // (entity_ref / entity_ref_list) plus the built-in `references` (any-field
  // backlinks — a universal projection offered on every field_of, even though it
  // isn't a member of the anchor kind's types). Scalar projection (a value-set)
  // and its Filter value-slot consumer are deferred (§14.5). Fields are the
  // anchor kind's (single-hop from anchor sources); precise cross-kind
  // intersection is deferred with multi-hop.
  let projectField = $derived(cfg.project_field ?? "");
  let projectFields = $derived(buildProjectFields());
  function buildProjectFields(): { key: string; name: string }[] {
    const out: { key: string; name: string }[] = [];
    for (const f of nodeFields) {
      // Every field projects — a reference field to a node-set, a scalar field
      // to a value-set (#196, ADR-0031 §D) — except `long_text`: freeform prose
      // has no stable identity, so it's presence-only (§H).
      if (f.def.type === "long_text") continue;
      out.push({ key: f.key, name: f.name });
    }
    const refDef = ctx.fieldByKey("references");
    if (refDef && !out.some((o) => o.key === "references")) out.push({ key: "references", name: refDef.name });
    return out;
  }

  // Whether this node's value slot is fed by a wired source edge (#196). When
  // wired, the operand comes from the edge — the inline literal / promote control
  // is hidden (the three fill modes are mutually exclusive, ADR-0031 §E).
  let isValueWired = $derived(ctx.valueWired?.(id) ?? false);
  // The value socket is a Filter (transform) affordance: a Filter with a
  // value-taking field predicate exposes it, so you can wire a projection in. A
  // bare "Field" *injector* is a self-contained source — it shows the socket
  // ONLY to display an already-wired value (e.g. a reopened wired Filter lowers
  // to a field leaf), never as an empty dangling input (#196).
  let hasValueSlot = $derived(
    kind === "filter" ? filterKind === "field" && !!fieldDef && opNeedsValue : kind === "field" && isValueWired,
  );

  // --- hand_picked helpers: ids <-> light refs for NodePicker ---
  // Resolve a picked id's title across the rosters the anchor kind can draw from
  // (lore / assistant / prompt), so an assistant hand-pick shows its title, not
  // its raw id.
  function refTitle(pid: string): string {
    return (
      ctx.loreEntries.find((e) => e.id === pid)?.title ??
      ctx.assistantEntries.find((e) => e.id === pid)?.title ??
      ctx.promptEntries.find((e) => e.id === pid)?.title ??
      pid
    );
  }
  // NodePicker's Category enum has no "prompt" — it surfaces the prompt roster
  // under "snippet". Map the anchor kind so hand-picking a prompt-kind view
  // renders its browse group instead of "No pickable items".
  function pickerCategory(k: string): NodePickerRef["kind"] {
    return (k === "prompt" ? "snippet" : k) as NodePickerRef["kind"];
  }
  let pickerRefs = $derived<NodePickerRef[]>(
    (cfg.hand_picked ?? []).map((pid) => ({
      id: pid,
      kind: pickerCategory(ctx.kind) ?? "lore",
      title: refTitle(pid),
    })),
  );
  function onPickerChange(refs: NodePickerRef[]) {
    patch({ hand_picked: refs.map((r) => r.id) });
  }

  // Stop pointerdown *natively* (not via Svelte's delegated onpointerdown, which
  // fires at the root — too late to beat Svelte Flow's native node-select
  // listener on an ancestor). Keeps interacting with the picker from selecting /
  // dragging the flow node.
  function stopPointerdown(node: HTMLElement) {
    const stop = (e: Event) => e.stopPropagation();
    node.addEventListener("pointerdown", stop);
    return { destroy: () => node.removeEventListener("pointerdown", stop) };
  }

  // --- View (output) named handles = groups ---
  let handles = $derived<ViewHandle[]>(cfg.handles && cfg.handles.length > 0 ? cfg.handles : [{ id: "in", name: "" }]);
  function commitHandles(next: ViewHandle[]) {
    patch({ handles: next });
  }
  function nextHandleId(list: ViewHandle[]): string {
    let max = 0;
    for (const h of list) {
      const m = /^h(\d+)$/.exec(h.id);
      if (m) max = Math.max(max, Number(m[1]));
    }
    return `h${max + 1}`;
  }
  function addHandle() {
    const list = [...handles];
    commitHandles([...list, { id: nextHandleId(list), name: "" }]);
  }
  function renameHandle(hid: string, name: string) {
    commitHandles(handles.map((h) => (h.id === hid ? { ...h, name } : h)));
  }
  function setHandleColor(hid: string, color: string | null) {
    commitHandles(handles.map((h) => (h.id === hid ? { ...h, color: color ?? null } : h)));
  }
  function removeHandle(hid: string) {
    if (handles.length <= 1) return; // keep at least one group
    commitHandles(handles.filter((h) => h.id !== hid));
  }
  function moveHandle(hid: string, delta: -1 | 1) {
    const i = handles.findIndex((h) => h.id === hid);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= handles.length) return;
    const next = [...handles];
    [next[i], next[j]] = [next[j], next[i]];
    commitHandles(next);
  }
  // Even vertical spread for the target ports down the node's left edge.
  function handleTop(i: number): string {
    return `${((i + 1) / (handles.length + 1)) * 100}%`;
  }

  // --- organize levels (ADR-0037 §2/§8 + Amendment 1: ν by attribute, owned per
  // GROUP). Each named group carries its own levels (`ViewHandle.group_by`); the
  // single/unnamed group keeps the output-node `group_by`. The `organizeSection`
  // snippet renders the controls for either owner — the handlers below are pure
  // over a (levels, onCommit) pair so both bindings reuse them.
  //
  // Offer only fields the ADR-0037 §2 table sanctions as organize levels:
  // enum/select, multi-valued (tags / multi-ref), reference fields (real-node
  // buckets), and the intrinsic `entry_type`. Continuous/identity/freeform
  // fields (number, computed, color, long_text, title/id) would make one bucket
  // per value, so they are dropped — mirroring `joinableFields`/`projectFields`.
  // `boolean` is deliberately excluded: it is not in the §2 table and
  // `segmentForField` has no label case for it (would render raw true/false).
  const GROUPABLE_TYPES: MetadataFieldType[] = ["select", "multi_select", "tags", "entity_ref", "entity_ref_list"];
  let groupableFields = $derived(
    nodeFields.filter(
      (f) => f.key === "entry_type" || (f.def.category !== "intrinsic" && GROUPABLE_TYPES.includes(f.def.type)),
    ),
  );
  // A stored level may name a field the roster can't offer — the Assistants
  // default's synthetic `source_layer` projection (groupBy.ts), or a field
  // hidden since authoring. Show a readable label, never a blank <select>; the
  // level is preserved exactly as stored (display-only fallback).
  const SYNTHETIC_LEVEL_LABELS: Record<string, string> = { source_layer: "Source layer" };
  function levelLabel(field: string): string {
    return groupableFields.find((f) => f.key === field)?.name ?? SYNTHETIC_LEVEL_LABELS[field] ?? field;
  }
  // Per-list helpers (each group organizes independently, so used-field sets and
  // add-availability are computed against *that* group's levels).
  function usedFields(levels: ViewGroupByLevel[]): Set<string> {
    return new Set(levels.map((l) => l.field));
  }
  function canAddLevel(levels: ViewGroupByLevel[]): boolean {
    const used = usedFields(levels);
    return groupableFields.some((f) => !used.has(f.key));
  }
  // A level's own <select> offers the unused groupable fields plus its own
  // current field — so the no-duplicate-levels contract can't be bypassed by
  // re-pointing a row at an already-used field.
  function levelOptions(levels: ViewGroupByLevel[], current: string): typeof groupableFields {
    const used = usedFields(levels);
    return groupableFields.filter((f) => f.key === current || !used.has(f.key));
  }
  // Pure mutators over one owner's levels list; each calls that owner's commit.
  type LevelCommit = (next: ViewGroupByLevel[]) => void;
  function addLevelTo(levels: ViewGroupByLevel[], commit: LevelCommit) {
    const pick = groupableFields.find((f) => !usedFields(levels).has(f.key));
    if (pick) commit([...levels, { field: pick.key }]);
  }
  function setLevelFieldAt(levels: ViewGroupByLevel[], commit: LevelCommit, i: number, field: string) {
    commit(levels.map((l, j) => (j === i ? { ...l, field } : l)));
  }
  // first-seen (undefined) ⇄ alphabetical-by-label ("label").
  function toggleLevelOrderAt(levels: ViewGroupByLevel[], commit: LevelCommit, i: number) {
    commit(levels.map((l, j) => (j === i ? { field: l.field, ...(l.order === "label" ? {} : { order: "label" }) } : l)));
  }
  function removeLevelAt(levels: ViewGroupByLevel[], commit: LevelCommit, i: number) {
    commit(levels.filter((_, j) => j !== i));
  }
  function moveLevelAt(levels: ViewGroupByLevel[], commit: LevelCommit, i: number, delta: -1 | 1) {
    const j = i + delta;
    if (j < 0 || j >= levels.length) return;
    const next = [...levels];
    [next[i], next[j]] = [next[j], next[i]];
    commit(next);
  }
  // Organize is ALWAYS owned by a handle (ADR-0037 Amendment 1), including the
  // single/unnamed group (the synthetic `in` handle). One uniform binding — no
  // single-vs-grouped switch — so a group + its Organize move, add, and delete as
  // one unit (graphToSpec lowers a lone handle's `group_by` to `ViewSpec.group_by`).
  function commitHandleLevels(hid: string): LevelCommit {
    return (next) =>
      commitHandles(handles.map((h) => (h.id === hid ? { ...h, group_by: next.length > 0 ? next : undefined } : h)));
  }
</script>

{#snippet typeSelect(useDescendants: boolean)}
  <select
    class="vfield"
    value={useDescendants ? (cfg.descendants_of ?? "") : (cfg.type ?? "")}
    onchange={(e) => patch(useDescendants ? { descendants_of: e.currentTarget.value } : { type: e.currentTarget.value })}
  >
    <option value="">— pick type —</option>
    {#each ctx.entryTypes as et (et.fqn)}
      <option value={et.fqn}>{et.name}</option>
    {/each}
  </select>
{/snippet}

{#snippet organizeSection(levels: ViewGroupByLevel[], commit: LevelCommit)}
  <!-- Organize levels (ADR-0037 §8 + Amendment 1): ordered group-by dropdowns
       for ONE group (a named handle, or the single/unnamed group). Node config,
       not graph shape — so no canvas node competes with Nest. -->
  <div class="organize">
    <div class="org-head">Organize</div>
    {#each levels as level, i (i)}
      <div class="handle-row">
        <select
          class="vfield lname"
          value={level.field}
          onchange={(e) => setLevelFieldAt(levels, commit, i, e.currentTarget.value)}
          aria-label={`Organize level ${i + 1} field`}
        >
          {#if !groupableFields.some((f) => f.key === level.field)}
            <option value={level.field}>{levelLabel(level.field)}</option>
          {/if}
          {#each levelOptions(levels, level.field) as f (f.key)}
            <option value={f.key}>{f.name}</option>
          {/each}
        </select>
        <button
          type="button"
          class="hbtn"
          class:on={level.order === "label"}
          title="Sort buckets A–Z (otherwise by first appearance)"
          aria-label="Toggle alphabetical bucket order"
          aria-pressed={level.order === "label"}
          onclick={() => toggleLevelOrderAt(levels, commit, i)}>A–Z</button
        >
        <button class="hbtn" type="button" title="Move level up" aria-label="Move level up" disabled={i === 0} onclick={() => moveLevelAt(levels, commit, i, -1)}>↑</button>
        <button class="hbtn" type="button" title="Move level down" aria-label="Move level down" disabled={i === levels.length - 1} onclick={() => moveLevelAt(levels, commit, i, 1)}>↓</button>
        <button class="hbtn del" type="button" title="Remove level" aria-label="Remove level" onclick={() => removeLevelAt(levels, commit, i)}>×</button>
      </div>
    {/each}
    {#if groupableFields.length > 0}
      <button class="add-handle" type="button" title="Add organize level" aria-label="Add organize level" disabled={!canAddLevel(levels)} onclick={() => addLevelTo(levels, commit)}>
        + Organize by…
      </button>
    {:else if levels.length === 0}
      <p class="vhint org-empty">No groupable fields on this kind.</p>
    {/if}
  </div>
{/snippet}

{#snippet tagSelect()}
  <select class="vfield" value={cfg.tagged ?? ""} onchange={(e) => patch({ tagged: e.currentTarget.value })}>
    <option value="">— pick tag —</option>
    {#each ctx.tags as tag (tag)}
      <option value={tag}>{tag}</option>
    {/each}
  </select>
{/snippet}

{#snippet fieldEditor()}
  <div class="vfield-row">
    <select class="vfield" value={fieldKey} onchange={(e) => setField({ key: e.currentTarget.value })}>
      <option value="">— field —</option>
      {#each nodeFields as f (f.key)}
        <option value={f.key}>{f.name}</option>
      {/each}
    </select>
    <select class="vfield op" value={fieldOp} onchange={(e) => changeOp(e.currentTarget.value as FieldOp)}>
      {#each FIELD_OPS as op (op.value)}
        <option value={op.value}>{op.label}</option>
      {/each}
    </select>
  </div>
  {#if opNeedsValue && fieldDef}
    {#if isValueWired}
      <!-- Wired: a source edge fills the value slot (#196). The operand comes
           from the wire; the literal / promote controls are hidden. -->
      <div class="vwired" role="note">↳ value from a wired source</div>
    {:else if isPromoted}
      <!-- Promoted: the slot is a runtime formal. Edit its strip label + the
           overridable default; Unlink demotes back to a fixed value. -->
      <div class="vparam" role="group" aria-label="Runtime parameter">
        <div class="vparam-head">
          <span class="vparam-tag">Parameter</span>
          {#if isInactiveParam}<span class="vparam-inert" role="note">inactive</span>{/if}
          <button type="button" class="vparam-unlink" title="Back to a fixed value" onclick={demoteField}>Unlink</button>
        </div>
        <input
          class="vfield"
          type="text"
          placeholder="Parameter label"
          aria-label="Parameter label"
          value={cfg.field_param?.label ?? ""}
          oninput={(e) => setParamLabel(e.currentTarget.value)}
        />
        <div class="vfield-value">
          <FieldValueEditor
            field={fieldDef}
            value={(cfg.field_param?.default ?? null) as import("@/lib/types").MetadataValue}
            onChange={(v) => setParamDefault(v)}
            loreEntries={ctx.loreEntries}
            promptEntries={ctx.promptEntries}
            structure={ctx.structure}
            researchStructure={ctx.researchStructure}
            ariaLabel="Default value"
          />
        </div>
      </div>
    {:else}
      <div class="vfield-value">
        <FieldValueEditor
          field={fieldDef}
          value={(cfg.field?.value ?? null) as import("@/lib/types").MetadataValue}
          onChange={(v) => setField({ value: v })}
          loreEntries={ctx.loreEntries}
          promptEntries={ctx.promptEntries}
          structure={ctx.structure}
          researchStructure={ctx.researchStructure}
          ariaLabel="Field value"
        />
      </div>
      <button type="button" class="vpromote" title="Expose this value as a runtime parameter" onclick={promoteField}>
        Promote to parameter
      </button>
    {/if}
  {/if}
{/snippet}

<div
  class="vnode"
  class:selected
  class:output={kind === "output"}
  class:combinator={arity === "many" || arity === "keep_remove" || arity === "parents_children" || kind === "complement"}
  class:injector={kind === "all"}
  class:inactive={isInactiveParam}
  title={isInactiveParam ? "Unbound parameter — inactive until a value is picked (shows everything by default)" : undefined}
>
  <!-- target ports (left) -->
  {#if kind === "output"}
    {#each handles as h, i (h.id)}
      <Handle type="target" position={Position.Left} id={h.id} class="port port-h" style={`top:${handleTop(i)}`} />
    {/each}
  {:else if kind === "difference"}
    <Handle type="target" position={Position.Left} id="keep" class="port keep" style="top: 34%" />
    <Handle type="target" position={Position.Left} id="remove" class="port remove" style="top: 66%" />
  {:else if kind === "nest"}
    <Handle type="target" position={Position.Left} id="parents" class="port parents" style="top: 34%" />
    <Handle type="target" position={Position.Left} id="children" class="port children" style="top: 66%" />
  {:else if arity !== "none"}
    <Handle type="target" position={Position.Left} id="in" class="port" style={hasValueSlot ? "top: 34%" : ""} />
  {/if}
  <!-- value operand socket (#196): a wired source fills the field's value slot.
       For a Filter it sits below the set `in` port; a bare `field` leaf has only
       this one input. -->
  {#if hasValueSlot}
    <Handle
      type="target"
      position={Position.Left}
      id="value"
      class="port value"
      style={arity !== "none" ? "top: 66%" : "top: 50%"}
    />
  {/if}

  <header class="vnode-head">
    <ViewGlyph {kind} uid={id} />
    <span class="vnode-title">{LABELS[kind]}</span>
    {#if kind !== "output"}
      <button class="vnode-del" title="Delete node" aria-label="Delete node" onclick={() => ctx.removeNode(id)}>×</button>
    {/if}
  </header>

  {#if kind === "difference"}
    <div class="port-legend"><span class="dot keep"></span>keep · <span class="dot remove"></span>remove</div>
  {:else if kind === "nest"}
    <div class="port-legend"><span class="dot parents"></span>parents · <span class="dot children"></span>children</div>
  {:else if hasValueSlot}
    <div class="port-legend">
      {#if arity !== "none"}set · {/if}<span class="dot value"></span>value
    </div>
  {/if}

  <!-- config by kind -->
  {#if kind === "type" || kind === "descendants_of"}
    {@render typeSelect(kind === "descendants_of")}
  {:else if kind === "tagged"}
    {@render tagSelect()}
  {:else if kind === "field"}
    {@render fieldEditor()}
  {:else if kind === "filter"}
    <div class="vseg" role="group" aria-label="Filter mode">
      <button type="button" class:on={filterMode === "keep"} onclick={() => patch({ filter_mode: "keep" })}>Keep</button>
      <button type="button" class:on={filterMode === "drop"} onclick={() => patch({ filter_mode: "drop" })}>Drop</button>
    </div>
    <select
      class="vfield"
      value={filterKind}
      onchange={(e) => patch({ filter_kind: e.currentTarget.value as PredicateKind })}
    >
      {#each predicateKinds as pk (pk.value)}
        <option value={pk.value}>{pk.label}</option>
      {/each}
    </select>
    {#if filterKind === "type"}
      {@render typeSelect(false)}
    {:else if filterKind === "descendants_of"}
      {@render typeSelect(true)}
    {:else if filterKind === "tagged"}
      {@render tagSelect()}
    {:else if filterKind === "field"}
      {@render fieldEditor()}
    {/if}
  {:else if kind === "sorter"}
    <!-- #230 multi-level sort: an ordered list of keys (sort by A, then B, …). -->
    <div class="organize">
      <div class="org-head">Sort by</div>
      {#each sortKeys as key, i (i)}
        <div class="handle-row">
          <select
            class="vfield lname"
            value={key.by}
            onchange={(e) => setSortKey(i, { by: e.currentTarget.value as SortKey["by"] })}
            aria-label={`Sort key ${i + 1} type`}
          >
            <option value="title">Title</option>
            <option value="field">Field…</option>
          </select>
          {#if key.by === "field"}
            <select
              class="vfield lname"
              value={key.field_key ?? ""}
              onchange={(e) => setSortKey(i, { field_key: e.currentTarget.value })}
              aria-label={`Sort key ${i + 1} field`}
            >
              <option value="">— field —</option>
              {#each nodeFields as f (f.key)}
                <option value={f.key}>{f.name}</option>
              {/each}
            </select>
          {/if}
          <button
            type="button"
            class="hbtn"
            title={key.dir === "desc" ? "Descending (click for ascending)" : "Ascending (click for descending)"}
            aria-label="Toggle sort direction"
            onclick={() => setSortKey(i, { dir: key.dir === "desc" ? "asc" : "desc" })}>{key.dir === "desc" ? "Desc" : "Asc"}</button
          >
          <button class="hbtn" type="button" title="Move up" aria-label="Move sort key up" disabled={i === 0} onclick={() => moveSortKey(i, -1)}>↑</button>
          <button class="hbtn" type="button" title="Move down" aria-label="Move sort key down" disabled={i === sortKeys.length - 1} onclick={() => moveSortKey(i, 1)}>↓</button>
          <button class="hbtn del" type="button" title="Remove sort key" aria-label="Remove sort key" onclick={() => removeSortKey(i)}>×</button>
        </div>
      {/each}
      <button class="add-handle" type="button" title="Add sort key" aria-label="Add sort key" onclick={addSortKey}>+ Add sort key</button>
      {#if sortKeys.length === 0}
        <p class="vhint org-empty">No keys → stored/manual order.</p>
      {/if}
    </div>
  {:else if kind === "hand_picked"}
    <!-- nodrag + native stop-pointerdown so interacting with the picker doesn't
         drag or select the flow node (Svelte Flow selects on pointerdown; the
         picker menu itself is portaled to <body>). -->
    <div class="vfield-value nodrag" role="presentation" use:stopPointerdown>
      <NodePicker
        config={{ sources: [{ kind: pickerCategory(ctx.kind) }] }}
        value={pickerRefs}
        label="Pick nodes"
        compact
        loreEntries={ctx.loreEntries}
        promptEntries={ctx.promptEntries}
        assistantEntries={ctx.assistantEntries}
        structure={ctx.structure}
        researchStructure={ctx.researchStructure}
        on:change={(e) => onPickerChange(e.detail.value)}
      />
    </div>
  {:else if kind === "view_ref"}
    <select class="vfield" value={cfg.view_ref ?? ""} onchange={(e) => patch({ view_ref: e.currentTarget.value })}>
      <option value="">— saved view —</option>
      {#each ctx.savedViews as v (v.id)}
        <option value={v.id}>{v.title}</option>
      {/each}
    </select>
  {:else if kind === "nest"}
    <!-- The join rule: which field links parent↔child, which way it points, and
         whether it matches by reference (id) or by title/tag (ADR-0028 §B). -->
    <select class="vfield" value={matchField} onchange={(e) => setMatch({ field: e.currentTarget.value })}>
      <option value="">— link field —</option>
      {#each joinableFields as f (f.key)}
        <option value={f.key}>{f.name}</option>
      {/each}
    </select>
    <select
      class="vfield"
      value={matchDir}
      onchange={(e) => setMatch({ direction: e.currentTarget.value as NonNullable<ViewNodeData["match"]>["direction"] })}
    >
      <option value="child_to_parent">Child → parent (child holds link)</option>
      <option value="parent_to_children">Parent → children (parent holds links)</option>
    </select>
    <div class="vseg" role="group" aria-label="Match by">
      <button type="button" class:on={matchBy === "ref"} onclick={() => setMatch({ by: "ref" })}>By reference</button>
      <button type="button" class:on={matchBy === "title"} onclick={() => setMatch({ by: "title" })}>By title</button>
    </div>
    <p class="vhint">Wire roots into <b>parents</b>, candidates into <b>children</b>. Loop the output back to <b>parents</b> to recurse.</p>
  {:else if kind === "field_of"}
    <!-- Forward projection (#184): follow a reference field from the wired input
         set to the nodes it points at. `References` projects the other way — the
         nodes that reference the input (any-field backlinks). -->
    <select class="vfield" value={projectField} onchange={(e) => patch({ project_field: e.currentTarget.value })}>
      <option value="">— follow field —</option>
      {#each projectFields as f (f.key)}
        <option value={f.key}>{f.name}</option>
      {/each}
    </select>
    <p class="vhint">Wire a set into the input; projects to a set of <b>nodes</b>.</p>
  {:else if kind === "self"}
    <p class="vhint">The entry this pane is anchored to. Feed it into <b>Field of</b> — e.g. <b>References</b> for its backlinks.</p>
  {:else if kind === "highlight"}
    <span class="vswatch" title="Highlight colour">
      <span class="vswatch-label">Colour</span>
      <SwatchPicker value={cfg.color ?? null} onChange={(id) => patch({ color: id ?? "" })} />
    </span>
  {:else if kind === "output"}
    <div class="handles">
      {#each handles as h, i (h.id)}
        <div class="group-block">
          <div class="handle-row">
            <input
              class="vfield hname"
              type="text"
              placeholder={handles.length > 1 ? `Group ${i + 1}` : "All results"}
              value={h.name}
              oninput={(e) => renameHandle(h.id, e.currentTarget.value)}
            />
            <SwatchPicker value={h.color ?? null} onChange={(c) => setHandleColor(h.id, c)} />
            <button class="hbtn" title="Move up" aria-label="Move group up" disabled={i === 0} onclick={() => moveHandle(h.id, -1)}>↑</button>
            <button class="hbtn" title="Move down" aria-label="Move group down" disabled={i === handles.length - 1} onclick={() => moveHandle(h.id, 1)}>↓</button>
            <button class="hbtn del" title="Remove group" aria-label="Remove group" disabled={handles.length <= 1} onclick={() => removeHandle(h.id)}>×</button>
          </div>
          <!-- Amendment 1: each group owns its Organize (the single/unnamed group
               too — its lone handle carries the levels). Group + Organize = one
               unit; the "+ add group" below adds another. -->
          <div class="group-organize">
            {@render organizeSection(h.group_by ?? [], commitHandleLevels(h.id))}
          </div>
        </div>
      {/each}
      <button class="add-handle" type="button" title="Add handle group" aria-label="Add handle group" onclick={addHandle}>+ Add group</button>
    </div>
  {/if}

  <!-- source port (right) — tinted `value` when this node emits a value-set. -->
  {#if kind !== "output"}
    <Handle type="source" position={Position.Right} id="out" class={emitsValueSet ? "port out value" : "port out"} />
  {/if}
</div>

<style>
  .vnode {
    min-width: 150px;
    max-width: 230px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: 9px;
    box-shadow: var(--elev-1);
    font-size: var(--fs-sm);
    color: var(--text);
  }
  .vnode.selected {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }
  .vnode.combinator {
    background: var(--inset);
  }
  .vnode.injector {
    background: var(--inset);
  }
  .vnode.output {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  /* #198: an unbound parameter is inert by default — a recessed, dashed-border
     tint marks the no-op so the author sees it isn't currently constraining.
     Selection still reads clearly on top of it. */
  .vnode.inactive {
    background: var(--inset);
    border-style: dashed;
    border-color: var(--border-strong);
  }
  .vnode.inactive.selected {
    border-style: solid;
    border-color: var(--accent);
  }
  .vnode-head {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
  }
  .vnode-title {
    flex: 1;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .vnode-del {
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-lg);
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
  }
  .vnode-del:hover {
    color: var(--danger);
  }
  .port-legend {
    padding: 0 8px 4px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .port-legend .dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    margin: 0 2px 0 4px;
    vertical-align: middle;
  }
  .dot.keep,
  .dot.parents {
    background: var(--accent);
  }
  .dot.remove {
    background: var(--danger);
  }
  .dot.children {
    background: var(--k-lore);
  }
  .dot.value {
    background: var(--k-snippet);
  }
  /* the value slot is filled by a wired source, not an inline literal (#196) */
  .vwired {
    margin: 0 8px 8px;
    padding: 2px 6px;
    border: 1px dashed var(--border-strong);
    border-radius: 5px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  /* nest match-rule hint under the config selects */
  .vhint {
    margin: 0 8px 8px;
    font-size: var(--fs-xs);
    line-height: 1.35;
    color: var(--text-3);
  }
  .vhint b {
    font-weight: 600;
    color: var(--text-2);
  }
  .vfield,
  .vfield-value,
  .vfield-row {
    margin: 0 8px 8px;
  }
  .vfield {
    display: block;
    width: calc(100% - 16px);
    box-sizing: border-box;
    padding: 3px 5px;
    border: 1px solid var(--border);
    border-radius: 5px;
    font-size: var(--fs-sm);
    background: var(--panel);
  }
  .vfield-row {
    display: flex;
    gap: 5px;
  }
  .vfield-row .vfield {
    margin: 0;
    width: 100%;
  }
  .vfield.op {
    max-width: 96px;
  }
  /* promote-in-place: the "make this a parameter" affordance + the promoted card */
  .vpromote {
    display: block;
    margin: 0 8px 8px;
    padding: 2px 6px;
    border: 1px dashed var(--border-strong);
    background: transparent;
    border-radius: 5px;
    font-size: var(--fs-xs);
    color: var(--text-2);
    cursor: pointer;
  }
  .vpromote:hover {
    background: var(--panel);
  }
  .vparam {
    margin: 0 8px 8px;
    padding: 6px;
    border: 1px solid var(--accent);
    border-radius: 6px;
    background: var(--accent-soft);
  }
  .vparam-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 5px;
  }
  .vparam-tag {
    font-size: var(--fs-xs);
    font-weight: 600;
    color: var(--accent);
  }
  /* #198: the "unbound → inert by default" chip inside the parameter card */
  .vparam-inert {
    font-size: var(--fs-xs);
    font-weight: 600;
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .vparam-unlink {
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-xs);
    cursor: pointer;
    padding: 0 2px;
  }
  .vparam-unlink:hover {
    color: var(--danger);
  }
  .vparam .vfield {
    width: 100%;
    margin: 0 0 5px;
  }
  .vparam .vfield-value {
    margin: 0;
  }
  /* keep/drop + asc/desc segmented toggle */
  .vseg {
    display: flex;
    gap: 0;
    margin: 0 8px 8px;
  }
  .vseg button {
    flex: 1;
    padding: 3px 6px;
    border: 1px solid var(--border-strong);
    background: var(--panel);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .vseg button:first-child {
    border-radius: 5px 0 0 5px;
  }
  .vseg button:last-child {
    border-radius: 0 5px 5px 0;
    border-left: none;
  }
  .vseg button.on {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }
  /* swatch trigger sitting on its own (highlight). */
  .vswatch {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin: 0 8px 8px;
  }
  .vswatch-label {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  /* named-handle (group) editor on the View node */
  .handles {
    padding: 0 8px 8px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .handle-row {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .handle-row .hname {
    margin: 0;
    flex: 1;
    width: auto;
    min-width: 0;
  }
  .hbtn {
    border: 1px solid var(--border);
    background: var(--panel);
    border-radius: 4px;
    font-size: var(--fs-xs);
    line-height: 1;
    padding: 2px 4px;
    cursor: pointer;
    color: var(--text-3);
  }
  .hbtn:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .hbtn.del:hover:not(:disabled) {
    color: var(--danger);
  }
  .add-handle {
    align-self: flex-start;
    border: 1px dashed var(--border-strong);
    background: transparent;
    border-radius: 5px;
    font-size: var(--fs-sm);
    padding: 2px 8px;
    cursor: pointer;
    color: var(--text-2);
  }
  .add-handle:hover {
    background: var(--panel);
  }
  .add-handle:disabled {
    opacity: 0.4;
    cursor: default;
  }
  /* A group = its handle row + (when there are 2+ groups) its own Organize
     (ADR-0037 Amendment 1). The Organize is indented under the row with a left
     rule so it reads as belonging to that group, not to the result. */
  .group-block {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .group-organize {
    margin-left: 14px;
    border-left: 2px solid var(--border);
    padding-left: 6px;
  }
  .group-organize .organize {
    border-top: none;
    margin-top: 0;
    padding: 2px 0 4px;
  }
  /* Organize levels (ADR-0037 §8) — for the single/unnamed group, sits below the
     lone handle, separated by a hairline so "which group" reads distinctly from
     "how to organize within it". */
  .organize {
    padding: 8px 8px 8px;
    margin-top: 2px;
    border-top: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .org-head {
    font-size: var(--fs-xs);
    font-weight: 600;
    color: var(--text-3);
  }
  .handle-row .lname {
    margin: 0;
    flex: 1;
    width: auto;
    min-width: 0;
  }
  .hbtn.on {
    color: var(--accent);
    border-color: var(--accent);
  }
  .org-empty {
    margin: 0;
  }
  /* keep the flow-node ports visually distinct + above node content so the
     whole handle (not just the half sticking out) is grabbable/hoverable. */
  .vnode :global(.port) {
    width: 10px;
    height: 10px;
    z-index: 5;
    background: var(--accent);
    border: 1px solid var(--panel);
  }
  .vnode :global(.port.remove) {
    background: var(--danger);
  }
  .vnode :global(.port.children) {
    background: var(--k-lore);
  }
  /* The value-pipe handles (#196) — the value-operand target socket AND a
     value-emitting source `out` (a scalar field_of). Tinted `--k-snippet` (tan),
     deliberately distinct from Nest's `--k-lore` children port (both were blue and
     clashed). Must sit AFTER the generic `.vnode :global(.port)` rule above: equal
     specificity, so source order decides — placed earlier it lost to `--accent`. */
  .vnode :global(.port.value) {
    background: var(--k-snippet);
  }
</style>
