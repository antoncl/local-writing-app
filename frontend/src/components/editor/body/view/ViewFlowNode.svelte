<!--
  One custom Svelte Flow node for the view designer (0.5.0 step 3, #80). A
  single component renders every kind — leaf, combinator, annotate, output —
  switching on `data.kind`, so the flow registers one node type. Combinators
  wear a Venn glyph (ViewGlyph); difference exposes explicit keep/remove target
  ports (the confusable op, doc §1.2). Leaf/annotate config is edited inline and
  written back through the designer context.
-->
<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import ViewGlyph from "./ViewGlyph.svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import { inputArity, type GraphNodeKind, type ViewNodeData } from "@/lib/views/viewGraph";
  import { useDesignerContext } from "./designerContext";
  import type { NodePickerRef } from "@/lib/types";

  // Svelte Flow passes the node's id/data/selection state as props.
  let { id, data, selected = false }: { id: string; data: { kind: GraphNodeKind; cfg: ViewNodeData }; selected?: boolean } =
    $props();

  const getCtx = useDesignerContext();
  let ctx = $derived(getCtx());
  let kind = $derived(data.kind);
  let cfg = $derived(data.cfg ?? {});
  let arity = $derived(inputArity(kind));

  const LABELS: Record<GraphNodeKind, string> = {
    output: "View result",
    union: "Union",
    intersect: "Intersect",
    difference: "Difference",
    complement: "Complement",
    group: "Group",
    highlight: "Highlight",
    type: "Type is",
    descendants_of: "Type & subtypes",
    tagged: "Tagged",
    field: "Field",
    hand_picked: "Hand-picked",
    view_ref: "Saved view",
  };

  const FIELD_OPS: { value: NonNullable<ViewNodeData["field"]>["op"]; label: string }[] = [
    { value: "eq", label: "=" },
    { value: "neq", label: "≠" },
    { value: "includes", label: "includes" },
    { value: "not_includes", label: "excludes" },
    { value: "set", label: "is set" },
    { value: "unset", label: "is empty" },
  ];

  function patch(next: Partial<ViewNodeData>) {
    ctx.updateNodeData(id, next);
  }

  // --- field predicate helpers ---
  let fieldKey = $derived(cfg.field?.key ?? "");
  let fieldOp = $derived(cfg.field?.op ?? "eq");
  let fieldDef = $derived(fieldKey ? ctx.fieldByKey(fieldKey) : null);
  let opNeedsValue = $derived(fieldOp !== "set" && fieldOp !== "unset");
  function setField(next: Partial<NonNullable<ViewNodeData["field"]>>) {
    const merged = { key: fieldKey, op: fieldOp, value: cfg.field?.value, ...next };
    patch({ field: merged });
  }

  // --- hand_picked helpers: ids <-> light refs for NodePicker ---
  let pickerRefs = $derived<NodePickerRef[]>(
    (cfg.hand_picked ?? []).map((pid) => {
      const lore = ctx.loreEntries.find((e) => e.id === pid);
      return { id: pid, kind: (ctx.kind as NodePickerRef["kind"]) ?? "lore", title: lore?.title ?? pid };
    }),
  );
  function onPickerChange(refs: NodePickerRef[]) {
    patch({ hand_picked: refs.map((r) => r.id) });
  }
</script>

<div class="vnode" class:selected class:output={kind === "output"} class:combinator={arity === "many" || arity === "keep_remove" || kind === "complement"}>
  <!-- target ports (left) -->
  {#if kind === "difference"}
    <Handle type="target" position={Position.Left} id="keep" class="port keep" style="top: 34%" />
    <Handle type="target" position={Position.Left} id="remove" class="port remove" style="top: 66%" />
  {:else if arity !== "none"}
    <Handle type="target" position={Position.Left} id="in" class="port" />
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
  {/if}

  <!-- leaf / annotate config -->
  {#if kind === "type" || kind === "descendants_of"}
    <select
      class="vfield"
      value={kind === "type" ? (cfg.type ?? "") : (cfg.descendants_of ?? "")}
      onchange={(e) => patch(kind === "type" ? { type: e.currentTarget.value } : { descendants_of: e.currentTarget.value })}
    >
      <option value="">— pick type —</option>
      {#each ctx.entryTypes as et (et.fqn)}
        <option value={et.fqn}>{et.name}</option>
      {/each}
    </select>
  {:else if kind === "tagged"}
    <select class="vfield" value={cfg.tagged ?? ""} onchange={(e) => patch({ tagged: e.currentTarget.value })}>
      <option value="">— pick tag —</option>
      {#each ctx.tags as tag (tag)}
        <option value={tag}>{tag}</option>
      {/each}
    </select>
  {:else if kind === "field"}
    <div class="vfield-row">
      <select class="vfield" value={fieldKey} onchange={(e) => setField({ key: e.currentTarget.value })}>
        <option value="">— field —</option>
        {#each ctx.fields as f (f.key)}
          <option value={f.key}>{f.name}</option>
        {/each}
      </select>
      <select class="vfield op" value={fieldOp} onchange={(e) => setField({ op: e.currentTarget.value as NonNullable<ViewNodeData["field"]>["op"] })}>
        {#each FIELD_OPS as op (op.value)}
          <option value={op.value}>{op.label}</option>
        {/each}
      </select>
    </div>
    {#if opNeedsValue && fieldDef}
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
    {/if}
  {:else if kind === "hand_picked"}
    <div class="vfield-value">
      <NodePicker
        config={{ sources: [{ kind: ctx.kind }] }}
        value={pickerRefs}
        label="Pick nodes"
        compact
        loreEntries={ctx.loreEntries}
        promptEntries={ctx.promptEntries}
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
  {:else if kind === "group"}
    <input
      class="vfield"
      type="text"
      placeholder="Group name"
      value={cfg.label ?? ""}
      oninput={(e) => patch({ label: e.currentTarget.value })}
    />
    <div class="vfield-row">
      <input
        class="vfield rank"
        type="number"
        title="Group order — sort position of this named group in the output"
        value={cfg.rank ?? 0}
        onchange={(e) => patch({ rank: Number(e.currentTarget.value) || 0 })}
      />
      <span class="vswatch" title="Group tint (optional)">
        <span class="vswatch-label">Tint</span>
        <SwatchPicker value={cfg.color ?? null} onChange={(id) => patch({ color: id ?? "" })} />
      </span>
    </div>
  {:else if kind === "highlight"}
    <span class="vswatch" title="Highlight colour">
      <span class="vswatch-label">Colour</span>
      <SwatchPicker value={cfg.color ?? null} onChange={(id) => patch({ color: id ?? "" })} />
    </span>
  {/if}

  <!-- source port (right) -->
  {#if kind !== "output"}
    <Handle type="source" position={Position.Right} id="out" class="port out" />
  {/if}
</div>

<style>
  .vnode {
    min-width: 150px;
    max-width: 230px;
    background: var(--panel, #fff);
    border: 1px solid var(--border-strong, #cbd0d8);
    border-radius: 9px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    font-size: 12px;
    color: var(--text, #1f2430);
  }
  .vnode.selected {
    border-color: var(--accent, #4361ee);
    box-shadow: 0 0 0 2px var(--accent-soft, #d9e2ff);
  }
  .vnode.combinator {
    background: var(--inset, #f7f8fa);
  }
  .vnode.output {
    border-color: var(--accent, #4361ee);
    background: var(--accent-soft, #eef2ff);
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
    color: var(--text-3, #6b7280);
    font-size: 15px;
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
  }
  .vnode-del:hover {
    color: var(--danger, #d64545);
  }
  .port-legend {
    padding: 0 8px 4px;
    font-size: 10px;
    color: var(--text-3, #6b7280);
  }
  .port-legend .dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    margin: 0 2px 0 4px;
    vertical-align: middle;
  }
  .dot.keep {
    background: var(--accent, #4361ee);
  }
  .dot.remove {
    background: var(--danger, #d64545);
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
    border: 1px solid var(--border, #e2e5ea);
    border-radius: 5px;
    font-size: 12px;
    background: var(--panel, #fff);
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
    max-width: 84px;
  }
  .vfield.rank {
    max-width: 62px;
  }
  /* swatch-picker row: a small labelled trigger sitting inline with the
     rank input (group) or on its own (highlight). */
  .vswatch {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin: 0 8px 8px;
  }
  .vfield-row .vswatch {
    margin: 0;
    flex: 1;
  }
  .vswatch-label {
    font-size: 11px;
    color: var(--text-3, #6b7280);
  }
  /* keep the flow-node ports visually distinct + above node content so the
     whole handle (not just the half sticking out) is grabbable/hoverable. */
  .vnode :global(.port) {
    width: 10px;
    height: 10px;
    z-index: 5;
    background: var(--accent, #4361ee);
    border: 1px solid var(--panel, #fff);
  }
  .vnode :global(.port.remove) {
    background: var(--danger, #d64545);
  }
</style>
