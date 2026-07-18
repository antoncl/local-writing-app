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
  import ParamMark from "./ParamMark.svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import { defaultFilterKind, inputArity, isEmptyValue, outputPayload, promotableSlot, type GraphNodeKind, type PredicateKind, type ViewGraphNode, type ViewHandle, type ViewNodeData } from "@/lib/views/viewGraph";
  import { nodeSummary } from "@/lib/views/nodeSummary";
  import { isSortableField } from "@/lib/views/fieldAccess";
  import { useDesignerContext } from "./designerContext";
  import type { MetadataFieldType, MetadataValue, NodePickerRef, ViewGroupByLevel, ViewLeafValue, ViewSort } from "@/lib/types";
  import type { Snippet } from "svelte";

  // Svelte Flow passes the node's id/data/selection state as props.
  let { id, data, selected = false }: { id: string; data: { kind: GraphNodeKind; cfg: ViewNodeData }; selected?: boolean } =
    $props();

  const getCtx = useDesignerContext();
  let ctx = $derived(getCtx());
  let kind = $derived(data.kind);
  let cfg = $derived(data.cfg ?? {});
  // Expanded = editing in place (§A). Toggled by the header, cleared by a
  // canvas-background click — NOT Svelte Flow selection, so a second header
  // click collapses (#220 dogfood). `selected` still drives the highlight border.
  let isExpanded = $derived(ctx.expandedId === id);
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

  // A wired port stays filled at rest (§240), not only while hovered: append
  // `connected` when this handle currently has an edge. Reads flowEdges through
  // the context, so it re-evaluates when the wiring changes.
  function portClass(base: string, handleId: string): string {
    return ctx.handleConnected(id, handleId) ? `${base} connected` : base;
  }

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
    orphans_ref: "Orphans", // synthetic lowering scaffolding — never rendered as a canvas node
    field_of: "Field of",
    self: "This entry",
    highlight: "Highlight",
    hand_picked: "Hand-picked",
  };

  function patch(next: Partial<ViewNodeData>) {
    ctx.updateNodeData(id, next);
  }

  // One-line config summary shown on the COMPACT (unselected) node body (§A):
  // the resting canvas stays small; selecting a node expands it to the editor
  // below. Structural nodes (set ops / output / self / highlight) return "".
  let summaryText = $derived(
    nodeSummary(kind, cfg, {
      fieldName: (key) => ctx.fieldByKey(key)?.name ?? key,
      entryTypeName: (fqn) => ctx.entryTypes.find((t) => t.fqn === fqn)?.name ?? fqn,
    }),
  );

  // --- predicate-kind options for a Filter (drop Type when there's one type) ---
  let predicateKinds = $derived<{ value: PredicateKind; label: string }[]>(
    [
      ...(hasTypeChoice
        ? ([
            { value: "type", label: "Type is" },
            { value: "descendants_of", label: "Type & subtypes" },
          ] as { value: PredicateKind; label: string }[])
        : []),
      { value: "field", label: "Field" },
    ],
  );
  // Show the predicate <select> only when there's a real choice to make; with a
  // single option (a single-type kind → just Field) render its editor directly.
  let showPredicateSelect = $derived(predicateKinds.length > 1);
  // `tagged` is retired as an authoring predicate — `Field → tags` covers it (and
  // handles multi-tag correctly); shared with `defaultCfg` so the two can't drift.
  let filterKind = $derived<PredicateKind>(cfg.filter_kind ?? defaultFilterKind(hasTypeChoice));
  let filterMode = $derived<"keep" | "drop">(cfg.filter_mode ?? "keep");

  // Cross-kind authoring warning (ADR-0031 §F, Slice B / #215). §F is about FIELD
  // selectors, so this surfaces on the nodes whose picker reads the per-node input
  // roster (`fieldsFor`): `field_of`, a Filter narrowing on a field, and a Sorter's
  // "Sort by field" selector. `type`/`descendants_of` read the anchor entryTypes,
  // not the input roster; a `tagged` picker degrades the TAG roster, whose warning
  // needs tag-worded copy (a follow-up); a bare `field` leaf has no set input so is
  // never cross-kind. Reactive on `filterKind`, so it appears/clears as the author
  // switches a Filter's predicate.
  let usesInputRoster = $derived(
    kind === "field_of" || kind === "sorter" || (kind === "filter" && filterKind === "field"),
  );
  let rosterWarning = $derived(usesInputRoster ? (ctx.rosterWarningFor?.(id) ?? null) : null);
  let rosterWarnText = $derived.by(() => {
    if (!rosterWarning) return "";
    const { kinds, thin } = rosterWarning;
    // No named kinds = a cross-kind INTERSECT that collapsed to the empty set (its
    // branches share no kind) — the thinnest roster; name the phenomenon, not kinds.
    if (kinds.length === 0) return "Cross-kind intersection with no common kind — only intrinsic fields (title, type) are offered.";
    const names = kinds.map((k) => k.charAt(0).toUpperCase() + k.slice(1)).join(", ");
    return thin
      ? `Cross-kind input (${names}) — no fields shared across these kinds, so only intrinsic fields (title, type) are offered.`
      : `Cross-kind input (${names}) — the picker offers only fields shared across these kinds.`;
  });

  // --- field predicate helpers (comparator adapts to the field's datatype) ---
  let fieldKey = $derived(cfg.field?.key ?? "");
  let fieldOp = $derived<FieldOp>(cfg.field?.op ?? "overlap");
  let fieldDef = $derived(fieldKey ? ctx.fieldByKey(fieldKey) : null);
  let opNeedsValue = $derived(fieldOp !== "set" && fieldOp !== "unset");
  function setField(next: Partial<NonNullable<ViewNodeData["field"]>>) {
    // A value belongs to a specific field. When the field KEY changes, start the
    // value slot fresh (and drop any promotion of it) — otherwise a color-field
    // swatch id bleeds into, e.g., a tags field's input as raw text (dogfood bug).
    if (next.key !== undefined && next.key !== fieldKey) {
      patch({ field: { key: next.key, op: fieldOp, value: undefined }, param: undefined });
      return;
    }
    patch({ field: { key: fieldKey, op: fieldOp, value: cfg.field?.value, ...next } });
  }

  // --- uniform promote-in-place (ADR-0032; per-slot for ADR-0038 §C, #222) ---
  // Every value-carrying slot — a field value, or a type/descendants_of/tagged
  // leaf — promotes to a named runtime formal: the authored literal becomes an
  // overridable default and the slot value becomes `{var: name}`. `name` keys on
  // the node id so a view can carry two formals over the same slot. `collectParams`
  // lowers these into ViewSpec.params. Structural selectors (nest/sort)
  // carry no promotable slot (Amendment 1) so `slotKind` is null and no promote
  // affordance shows.
  let slotKind = $derived(promotableSlot({ id, kind, position: { x: 0, y: 0 }, data: cfg } as ViewGraphNode));
  let param = $derived(cfg.param ?? null);
  let isPromoted = $derived(param != null);
  // #198: a promoted formal with no default is UNBOUND — by default its predicate
  // is inactive (under (a) "unset = show everything" it imposes no constraint:
  // pass-through in a keep, removes nothing in a drop/complement). Surface that
  // no-op state so a power user sees the node is inert rather than silently
  // filtering. A field `set`/`unset` op carries no operand → never inactive.
  let isInactiveParam = $derived(
    isPromoted && isEmptyValue(param?.default) && (slotKind !== "field" || opNeedsValue),
  );
  // The slot's current literal (seeds the default on promote).
  function slotLiteral(): unknown {
    switch (slotKind) {
      case "field":
        return cfg.field?.value ?? null;
      case "type":
        return typeof cfg.type === "string" ? cfg.type : "";
      case "descendants_of":
        return typeof cfg.descendants_of === "string" ? cfg.descendants_of : "";
      case "tagged":
        return typeof cfg.tagged === "string" ? cfg.tagged : "";
      default:
        return null;
    }
  }
  // Patch the slot's VALUE (a literal or a `{var}` operand); the field slot keeps
  // its key/op. A leaf's empty default lowers to a blank leaf (null → "").
  function slotValuePatch(value: unknown): Partial<ViewNodeData> {
    switch (slotKind) {
      case "field":
        return { field: { key: fieldKey, op: fieldOp, value: value as NonNullable<ViewNodeData["field"]>["value"] } };
      case "type":
        return { type: (value ?? "") as ViewLeafValue };
      case "descendants_of":
        return { descendants_of: (value ?? "") as ViewLeafValue };
      case "tagged":
        return { tagged: (value ?? "") as ViewLeafValue };
      default:
        return {};
    }
  }
  function slotParamLabel(): string {
    switch (slotKind) {
      case "field":
        return fieldDef?.name || fieldKey || "Parameter";
      case "type":
      case "descendants_of":
        return "Type";
      case "tagged":
        return "Tag";
      default:
        return "Parameter";
    }
  }
  function promoteSlot() {
    if (!slotKind) return;
    const base = slotKind === "field" ? fieldKey || "param" : slotKind;
    const name = `${base}_${id}`;
    patch({ ...slotValuePatch({ var: name }), param: { name, label: slotParamLabel(), default: slotLiteral() } });
  }
  function demoteSlot() {
    if (!slotKind) return;
    patch({ ...slotValuePatch(cfg.param?.default ?? null), param: undefined });
  }
  function setParamLabel(label: string) {
    if (cfg.param) patch({ param: { ...cfg.param, label } });
  }
  function setParamDefault(v: unknown) {
    if (cfg.param) patch({ param: { ...cfg.param, default: v } });
  }
  // A valueless op (is set / is empty) has no slot to promote — demote when
  // switching into one so a stale formal can't leak into the parameter strip.
  function changeOp(op: FieldOp) {
    if ((op === "set" || op === "unset") && isPromoted) {
      patch({ field: { key: fieldKey, op, value: undefined }, param: undefined });
    } else {
      setField({ op });
    }
  }
  // A Filter's `param` is keyed to whichever slot `filter_kind` currently selects.
  // Switching kinds would strand it on the old slot — a ghost card the §D rail
  // can't see (collectParamBindings reads the NEW slot's value) that silently
  // drops on save. So demote first (restore the old slot's literal from the
  // default, clear the formal), then switch — the same guard changeOp applies.
  function changeFilterKind(next: PredicateKind) {
    if (isPromoted && slotKind) {
      patch({ ...slotValuePatch(cfg.param?.default ?? null), param: undefined, filter_kind: next });
    } else {
      patch({ filter_kind: next });
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

  // Fields this sorter can order by: the node roster minus set-valued/opaque
  // types, which have no natural order (#237). `title` is an intrinsic field and
  // lives in this list, so the picker offers it inline — there is no separate
  // "Title vs Field" dichotomy (it is a field, per ADR-0029's intrinsic model).
  let sortableFields = $derived(nodeFields.filter((f) => isSortableField(f.def.type)));

  // --- sorter helpers (#230 multi-level: an ordered list of keys ⇄ the `then`
  // chain). A key is a field_key (title included) + dir; "manual" = the EMPTY
  // list (input order). Every key is `by:"field"` on the wire; a legacy stored
  // `by:"title"` is read as field/title and normalized on the next edit. ---
  type SortKey = { field_key: string; dir: "asc" | "desc" };
  function sortToList(sort: ViewSort | null | undefined): SortKey[] {
    const list: SortKey[] = [];
    for (let s: ViewSort | null | undefined = sort; s; s = s.then) {
      if (s.by === "title") list.push({ field_key: "title", dir: s.dir ?? "asc" });
      else if (s.by === "field") list.push({ field_key: s.field_key ?? "title", dir: s.dir ?? "asc" });
      // "manual" carries no ordering key
    }
    return list;
  }
  function listToSort(list: SortKey[]): ViewSort {
    // Fold the list into a right-nested `then` chain; empty ⇒ manual order.
    let chain: ViewSort | null = null;
    for (let i = list.length - 1; i >= 0; i--) {
      const k = list[i];
      chain = { by: "field", field_key: k.field_key, dir: k.dir, ...(chain ? { then: chain } : {}) };
    }
    return chain ?? { by: "manual" };
  }
  let sortKeys = $derived<SortKey[]>(sortToList(cfg.sort));
  function commitSortKeys(list: SortKey[]) {
    patch({ sort: listToSort(list) });
  }
  function addSortKey() {
    // Default to the first orderable field (title leads the roster); fall back to
    // a bare "title" key if the roster hasn't resolved yet.
    commitSortKeys([...sortKeys, { field_key: sortableFields[0]?.key ?? "title", dir: "asc" }]);
  }
  function setSortKey(i: number, next: Partial<SortKey>) {
    commitSortKeys(sortKeys.map((k, j) => (j === i ? { ...k, ...next } : k)));
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
  // value-taking field predicate exposes it, so you can wire a projection in
  // (#196). Only a Filter carries it now — the standalone `field` leaf that once
  // also showed it is retired (#271/#284).
  let hasValueSlot = $derived(kind === "filter" && filterKind === "field" && !!fieldDef && opNeedsValue);

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

<!-- Base slot widgets (§C): a slot's typed picker, parametrized by value + setter
     so the literal slot and the promoted default reuse ONE control. -->
{#snippet entryTypeWidget(value: string, onSet: (v: string) => void)}
  <select class="vfield" value={value} onchange={(e) => onSet(e.currentTarget.value)}>
    <option value="">— pick type —</option>
    {#each ctx.entryTypes as et (et.fqn)}
      <option value={et.fqn}>{et.name}</option>
    {/each}
  </select>
{/snippet}

<!-- The field value widget (§C + #226): the intrinsic `entry_type` field offers
     the closed entry-type set instead of raw text; every other field routes to
     FieldValueEditor by datatype. Parametrized by value + setter for reuse in the
     literal slot and the promoted default. -->
{#snippet fieldValueWidget(value: unknown, onSet: (v: unknown) => void, ariaLabel: string)}
  {#if fieldKey === "entry_type"}
    {@render entryTypeWidget(typeof value === "string" ? value : "", onSet)}
  {:else if fieldDef}
    <FieldValueEditor
      field={fieldDef}
      value={(value ?? null) as MetadataValue}
      onChange={(v) => onSet(v)}
      loreEntries={ctx.loreEntries}
      promptEntries={ctx.promptEntries}
      structure={ctx.structure}
      researchStructure={ctx.researchStructure}
      knownTags={ctx.knownTagsFor(id)}
      {ariaLabel}
    />
  {/if}
{/snippet}

<!-- Shared promote card chrome (§C): label + overridable default + unlink. The
     default's typed widget is passed per slot. -->
{#snippet promoteCard(defaultWidget: Snippet)}
  <div class="vparam nodrag" role="group" aria-label="Runtime parameter" use:stopPointerdown>
    <div class="vparam-head">
      <!-- The half→whole mark carries the bound state (§240): whole once a
           default/value fills it, half while unbound (imposing no constraint). -->
      <ParamMark bound={!isInactiveParam} size={13} />
      <span class="vparam-tag">Parameter</span>
      <button type="button" class="vparam-unlink" title="Back to a fixed value" onclick={demoteSlot}>Unlink</button>
    </div>
    {#if isInactiveParam}
      <!-- #206: the quiet dashed tint marks the no-op at rest; the expanded body
           gets the plain-words reason. -->
      <p class="vparam-note" role="note">Unbound — imposes no constraint (shows everything) until a default or picked value fills it.</p>
    {/if}
    <input
      class="vfield"
      type="text"
      placeholder="Parameter label"
      aria-label="Parameter label"
      value={cfg.param?.label ?? ""}
      oninput={(e) => setParamLabel(e.currentTarget.value)}
    />
    <div class="vfield-value">{@render defaultWidget()}</div>
  </div>
{/snippet}

{#snippet promoteButton()}
  <!-- §240: the promote affordance is the half-mark itself (not a dashed button
       that widens the card) — click it to promote the slot to a parameter; it
       then completes to whole once a default/value binds it. -->
  <button type="button" class="vpromote" title="Promote this value to a runtime parameter" aria-label="Promote to a runtime parameter" onclick={promoteSlot}>
    <ParamMark size={13} />
  </button>
{/snippet}

<!-- Type / Type+subtypes leaf slot (§C uniform): literal picker + promote, or the
     promote card with an entry-type default. -->
{#snippet typeDefault()}
  {@render entryTypeWidget(typeof cfg.param?.default === "string" ? cfg.param.default : "", (v) => setParamDefault(v))}
{/snippet}
{#snippet typeSlot(useDescendants: boolean)}
  {#if isPromoted}
    {@render promoteCard(typeDefault)}
  {:else}
    {@const cur = useDescendants ? cfg.descendants_of : cfg.type}
    <div class="vslot-lit nodrag" role="presentation" use:stopPointerdown>
      {@render entryTypeWidget(typeof cur === "string" ? cur : "", (v) => patch(useDescendants ? { descendants_of: v } : { type: v }))}
      {@render promoteButton()}
    </div>
  {/if}
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

<!-- Field predicate slot (§C uniform): field + op selects, then the value slot
     as literal | promoted formal | wired source — the same three modes every
     value-carrying slot follows. -->
{#snippet fieldDefault()}
  {@render fieldValueWidget(cfg.param?.default, (v) => setParamDefault(v), "Default value")}
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
      {@render promoteCard(fieldDefault)}
    {:else}
      <div class="vfield-value nodrag" role="presentation" use:stopPointerdown>
        {@render fieldValueWidget(cfg.field?.value, (v) => setField({ value: v }), "Field value")}
      </div>
      {@render promoteButton()}
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
  <!-- target ports (left). The output node's group handles are NOT here — they
       live inside each group row (below) so every handle sits ON its group's
       name row (§240 / Wiring Desk), instead of an even spread that drifts out
       of line with the groups. -->
  {#if kind === "difference"}
    <Handle type="target" position={Position.Left} id="keep" class={portClass("port keep", "keep")} style="top: 34%" />
    <Handle type="target" position={Position.Left} id="remove" class={portClass("port remove", "remove")} style="top: 66%" />
  {:else if kind === "nest"}
    <Handle type="target" position={Position.Left} id="parents" class={portClass("port parents", "parents")} style="top: 34%" />
    <Handle type="target" position={Position.Left} id="children" class={portClass("port children", "children")} style="top: 66%" />
  {:else if kind !== "output" && arity !== "none"}
    <!-- output is excluded: its group handles live in the group rows below, so it
         must not also get a generic `in` port here (it's arity "many"). -->
    <Handle type="target" position={Position.Left} id="in" class={portClass("port", "in")} style={hasValueSlot ? "top: 34%" : ""} />
  {/if}
  <!-- value operand socket (#196): a wired source fills the field's value slot.
       For a Filter it sits below the set `in` port; a bare `field` leaf has only
       this one input. -->
  {#if hasValueSlot}
    <Handle
      type="target"
      position={Position.Left}
      id="value"
      class={portClass("port value", "value")}
      style={arity !== "none" ? "top: 66%" : "top: 50%"}
    />
  {/if}

  <header class="vnode-head">
    <!-- The header is the expand/collapse toggle (#220): glyph + title in one
         button. Delete stays a sibling button (no nested interactives). -->
    <button
      class="vnode-toggle"
      type="button"
      aria-expanded={isExpanded}
      title={isExpanded ? "Collapse" : "Expand"}
      aria-label={`${isExpanded ? "Collapse" : "Expand"} ${LABELS[kind]}`}
      onclick={() => ctx.toggleExpanded(id)}
    >
      <ViewGlyph {kind} uid={id} />
      <span class="vnode-title">{LABELS[kind]}</span>
    </button>
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

  <!-- config by kind — only the SELECTED node expands to its editor (§A); the
       resting node shows a one-line summary. `nodrag` + native stop-pointerdown
       keep interacting with any config control from dragging/selecting the node
       (Svelte Flow acts on pointerdown; picker menus portal to <body>). -->
  {#if kind === "output"}
  <!-- Output groups render in BOTH states (§240 / Wiring Desk) so each handle
       sits ON its group's name row: at rest a read-only name row, expanded the
       full group editor. The handle lives inside the row, so Svelte Flow aligns
       it (and its wire) to that row instead of an even spread down the node. -->
  <div class="handles nodrag" role="presentation" use:stopPointerdown>
    {#each handles as h, i (h.id)}
      <div class="group-block">
        <div class="handle-row group-row">
          <Handle type="target" position={Position.Left} id={h.id} class={portClass("port port-h", h.id)} />
          {#if isExpanded}
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
          {:else}
            <span class="group-name">{h.name || (handles.length > 1 ? `Group ${i + 1}` : "All results")}</span>
          {/if}
        </div>
        {#if isExpanded}
          <div class="group-organize">
            {@render organizeSection(h.group_by ?? [], commitHandleLevels(h.id))}
          </div>
        {/if}
      </div>
    {/each}
    {#if isExpanded}
      <button class="add-handle" type="button" title="Add handle group" aria-label="Add handle group" onclick={addHandle}>+ Add group</button>
    {/if}
  </div>
  {:else if isExpanded}
  <div class="vconfig nodrag" role="presentation" use:stopPointerdown>
  {#if rosterWarnText}
    <!-- Cross-kind roster degradation (ADR-0031 §F, Slice B). A WORD, not a glyph:
         the lexicon has no warning mark and the design language forbids
         glyph-only-with-tooltip (state hidden behind a hover). `role="note"` (not
         `alert`) — a persistent authoring advisory, so it must not re-interrupt the
         screen reader each time the text recomputes on a rewire. -->
    <p class="vwarn" role="note">{rosterWarnText}</p>
  {/if}
  {#if kind === "filter"}
    <div class="vseg" role="group" aria-label="Filter mode">
      <button type="button" class:on={filterMode === "keep"} onclick={() => patch({ filter_mode: "keep" })}>Keep</button>
      <button type="button" class:on={filterMode === "drop"} onclick={() => patch({ filter_mode: "drop" })}>Drop</button>
    </div>
    <!-- The predicate select is context-dependent: Type / Type & subtypes only
         appear when the anchor kind has >1 entry_type. When that leaves a single
         option (a single-type kind → just Field), hide the select and render the
         editor directly — no zero-choice dropdown. -->
    {#if showPredicateSelect}
      <select
        class="vfield"
        value={filterKind}
        onchange={(e) => changeFilterKind(e.currentTarget.value as PredicateKind)}
      >
        {#each predicateKinds as pk (pk.value)}
          <option value={pk.value}>{pk.label}</option>
        {/each}
      </select>
    {/if}
    {#if filterKind === "type"}
      {@render typeSlot(false)}
    {:else if filterKind === "descendants_of"}
      {@render typeSlot(true)}
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
            value={key.field_key}
            onchange={(e) => setSortKey(i, { field_key: e.currentTarget.value })}
            aria-label={`Sort key ${i + 1} field`}
          >
            {#if key.field_key && !sortableFields.some((f) => f.key === key.field_key)}
              <!-- A legacy/cross-roster key on a now-unsortable or absent field: keep it
                   visible + labelled (the evaluator no-ops it) so the row isn't a blank
                   select the author can't read or fix. -->
              <option value={key.field_key}>
                {(nodeFields.find((f) => f.key === key.field_key)?.name ?? key.field_key) + " — not sortable"}
              </option>
            {/if}
            {#each sortableFields as f (f.key)}
              <option value={f.key}>{f.name}</option>
            {/each}
          </select>
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
    <p class="vhint">
      Wire roots into <b>parents</b>, candidates into <b>children</b>. Loop the output back to <b>parents</b> to recurse.
      The lower-right <b>orphans</b> output carries candidates that matched no parent — wire it on (a filter, a group, a
      second Nest) to keep them, or leave it to drop them.
    </p>
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
  {/if}
  </div>
  {:else if summaryText}
    <div class="vnode-summary" title={summaryText}>{summaryText}</div>
  {/if}

  <!-- source port(s) (right). A Nest has a SECOND output — the routable orphans
       set (ADR-0028 Amdt 1, #260) — stacked below its results output; wiring it
       folds a downstream chain into `nest.orphans`. Other nodes emit one, tinted
       `value` when it carries a value-set. -->
  {#if kind === "nest"}
    <Handle type="source" position={Position.Right} id="out" class={portClass("port out", "out")} style="top: 34%" />
    <Handle type="source" position={Position.Right} id="orphans" class={portClass("port out orphans", "orphans")} style="top: 66%" />
  {:else if kind !== "output"}
    <Handle type="source" position={Position.Right} id="out" class={portClass(emitsValueSet ? "port out value" : "port out", "out")} />
  {/if}
</div>

<style>
  .vnode {
    min-width: 150px;
    max-width: 230px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-lg);
    /* The kind-stripe (§240): a 4px accent band down the left edge, drawn as an
       INSET box-shadow exactly like NodeRow (variant-card) so it follows the
       card's rounded corners — the same signature that ties every NodeRow to its
       kind, now on the flow nodes. Uniform on every kind. */
    box-shadow: inset 4px 0 0 0 var(--accent), var(--elev-1);
    font-size: var(--fs-sm);
    color: var(--text);
  }
  .vnode.selected {
    border-color: var(--accent);
    box-shadow: inset 4px 0 0 0 var(--accent), 0 0 0 2px var(--accent-soft);
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
    padding: 6px 8px 6px 11px;
  }
  /* The glyph+title expand toggle — reads as the header, not a button. */
  .vnode-toggle {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
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
  /* Compact one-line config summary on the resting (unselected) node — the
     glance state; selecting the node swaps it for the full editor (§A). */
  .vnode-summary {
    padding: 0 8px 8px 11px;
    font-size: var(--fs-sm);
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .port-legend {
    padding: 0 8px 4px 11px;
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
  /* §240: a hairline separates the header (the collapse/expand area) from the
     expanded edit area, on EVERY node — the divider Sort already had via its
     `.organize`. Suppressed on a leading `.organize` so the two don't double up. */
  .vconfig {
    border-top: 1px solid var(--divider);
    padding-top: 6px;
  }
  .vconfig > .organize:first-child {
    border-top: none;
    margin-top: 0;
    padding-top: 0;
  }
  /* the value slot is filled by a wired source, not an inline literal (#196) */
  .vwired {
    margin: 0 8px 8px;
    padding: 2px 6px;
    border: 1px dashed var(--border-strong);
    border-radius: var(--r-sm);
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
  /* Cross-kind roster degradation note (ADR-0031 §F, Slice B). The shared warning
     role (#125), matching the preview's `.preview-warnings` banner. */
  .vwarn {
    margin: 0 8px 8px;
    padding: 4px 8px;
    font-size: var(--fs-xs);
    line-height: 1.35;
    color: var(--warn);
    background: var(--warn-soft);
    border: 1px solid var(--warn-border);
    border-radius: 4px;
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
    border-radius: var(--r-sm);
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
  /* promote-in-place (§240): the affordance is the half-mark glyph, right-aligned
     under its slot — click to promote — not a dashed button that widens the card. */
  .vpromote {
    display: block;
    margin: 0 8px 6px auto;
    padding: 2px;
    border: none;
    background: transparent;
    border-radius: var(--r-sm);
    line-height: 0;
    cursor: pointer;
  }
  .vpromote:hover {
    background: var(--panel);
  }
  .vparam {
    margin: 0 8px 8px;
    padding: 6px;
    border: 1px solid var(--accent);
    border-radius: var(--r-md);
    background: var(--accent-soft);
  }
  .vparam-head {
    display: flex;
    align-items: center;
    gap: 5px;
    margin-bottom: 5px;
  }
  .vparam-tag {
    font-size: var(--fs-xs);
    font-weight: 600;
    color: var(--accent);
  }
  .vparam-unlink {
    margin-left: auto;
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-xs);
    cursor: pointer;
    padding: 0 2px;
  }
  /* #206: plain-words reason for the inactive tint, in the expanded card */
  .vparam-note {
    margin: 4px 0 0;
    font-size: var(--fs-xs);
    line-height: 1.35;
    color: var(--text-3);
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
    border-radius: var(--r-sm) 0 0 var(--r-sm);
  }
  .vseg button:last-child {
    border-radius: 0 var(--r-sm) var(--r-sm) 0;
    border-left: none;
  }
  .vseg button.on {
    background: var(--accent);
    border-color: var(--accent);
    /* ink on accent-solid — theme-flipping --surface, not a raw #fff (§G) */
    color: var(--surface);
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
  /* The output node's group list (§240). No left padding so each group's handle
     sits at the node's left edge; the row content is indented to clear it + the
     stripe. A header divider matches the other nodes' expanded configs. */
  .handles {
    padding: 6px 8px 8px 0;
    border-top: 1px solid var(--divider);
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .handles > .add-handle {
    margin-left: 15px;
  }
  .handle-row {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  /* Each group row owns its handle (positioned at the node edge) so the port
     lines up with the group name — at rest and expanded. */
  .group-row {
    position: relative;
    padding-left: 15px;
  }
  .group-name {
    flex: 1;
    min-width: 0;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
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
    border-radius: var(--r-sm);
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
    border-radius: var(--r-sm);
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
  /* Ports = hollow rings (§240 Claude Design pass): a socket, not a bullet —
     quiet at rest (surface fill + kind-colored border), filling with the kind
     color on hover so it announces itself only when you're about to wire. Kept
     above node content so the whole handle is grabbable. Semantic color moves
     from fill → border so the hollow reads as a ring. */
  .vnode :global(.port) {
    width: 11px;
    height: 11px;
    z-index: 5;
    box-sizing: border-box;
    background: var(--surface);
    border: 1.5px solid var(--accent);
  }
  /* a port fills with its kind color both on hover AND while wired (§240) */
  .vnode :global(.port:hover),
  .vnode :global(.port.connected) {
    background: var(--accent);
  }
  .vnode :global(.port.remove) {
    border-color: var(--danger);
  }
  .vnode :global(.port.remove:hover),
  .vnode :global(.port.remove.connected) {
    background: var(--danger);
  }
  .vnode :global(.port.children) {
    border-color: var(--k-lore);
  }
  .vnode :global(.port.children:hover),
  .vnode :global(.port.children.connected) {
    background: var(--k-lore);
  }
  /* The value-pipe handles (#196) — the value-operand target socket AND a
     value-emitting source `out` (a scalar field_of). Tinted `--k-snippet` (tan),
     deliberately distinct from Nest's `--k-lore` children port (both were blue and
     clashed). Must sit AFTER the generic `.vnode :global(.port)` rule above: equal
     specificity, so source order decides — placed earlier it lost to `--accent`. */
  .vnode :global(.port.value) {
    border-color: var(--k-snippet);
  }
  .vnode :global(.port.value:hover),
  .vnode :global(.port.value.connected) {
    background: var(--k-snippet);
  }
  /* The Nest's second output — the routable orphans set (ADR-0028 Amdt 1, #260).
     Muted, since it carries the residue (the unplaced candidates), distinct from
     the `--accent` results `out` port directly above it. */
  .vnode :global(.port.orphans) {
    border-color: var(--text-3);
  }
  .vnode :global(.port.orphans:hover),
  .vnode :global(.port.orphans.connected) {
    background: var(--text-3);
  }
</style>
