<!--
  The View (output) node's group editor, split out of ViewFlowNode (#2528): the
  named handles (one per group), each with its own Organize levels. Renders in
  BOTH node states (§240 / Wiring Desk) so each handle sits ON its group's name
  row — at rest a read-only name row, expanded the full editor. Edits go back
  through `onCommitHandles`; the node's config stays owned by ViewFlowNode.
-->
<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import type { ViewHandle } from "@/lib/views/viewGraph";
  import { effectiveFieldType } from "@/lib/views/fieldAccess";
  import { setLevelField, toggleLevelOrder } from "@/lib/views/groupLevelEdits";
  import { moveAt, removeAt } from "@/lib/utils/listEdits";
  import type { FieldOption } from "./designerContext";
  import type { ViewGroupByLevel } from "@/lib/types";

  let {
    handles,
    isExpanded,
    nodeFields,
    portClass,
    onCommitHandles,
  }: {
    handles: ViewHandle[];
    isExpanded: boolean;
    nodeFields: FieldOption[];
    portClass: (base: string, handleId: string) => string;
    onCommitHandles: (next: ViewHandle[]) => void;
  } = $props();

  // Stop pointerdown *natively* (not via Svelte's delegated onpointerdown, which
  // fires at the root — too late to beat Svelte Flow's native node-select
  // listener on an ancestor). Keeps interacting with the group controls from
  // selecting / dragging the flow node.
  function stopPointerdown(node: HTMLElement) {
    const stop = (e: Event) => e.stopPropagation();
    node.addEventListener("pointerdown", stop);
    return { destroy: () => node.removeEventListener("pointerdown", stop) };
  }

  // --- View (output) named handles = groups ---
  function commitHandles(next: ViewHandle[]) {
    onCommitHandles(next);
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
    const next = moveAt(handles, handles.findIndex((h) => h.id === hid), delta);
    if (next) commitHandles(next);
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
  // Tested against the EFFECTIVE type, so a computed field whose declared
  // `value_type` is groupable (the assistants roster's `listed`, #333) is
  // offered like any other — `type: "computed"` states authorship, not shape,
  // and a read-only field is still a perfectly good bucket key.
  const GROUPABLE_TYPES: string[] = ["select", "multi_select", "entity_ref", "entity_ref_list"];
  let groupableFields = $derived(
    nodeFields.filter(
      (f) =>
        f.key === "entry_type" ||
        (f.def.category !== "intrinsic" && GROUPABLE_TYPES.includes(effectiveFieldType(f.def) ?? "")),
    ),
  );
  // A stored level may name a field the roster can't currently offer — e.g. a
  // field hidden since the level was authored. Show its raw key rather than a
  // blank <select>; the level is preserved exactly as stored (display-only).
  function levelLabel(field: string): string {
    return groupableFields.find((f) => f.key === field)?.name ?? field;
  }
  // Per-list helpers (each group organizes independently, so used-field sets and
  // add-availability are computed against *that* group's levels). The `used` set
  // is built ONCE per group by the `organizeSection` snippet and threaded through
  // — `canAddLevel`/`levelOptions` are called per level row, so recomputing the
  // Set inside each would be O(levels²) work every render.
  function usedFields(levels: ViewGroupByLevel[]): Set<string> {
    return new Set(levels.map((l) => l.field));
  }
  function canAddLevel(used: Set<string>): boolean {
    return groupableFields.some((f) => !used.has(f.key));
  }
  // A level's own <select> offers the unused groupable fields plus its own
  // current field — so the no-duplicate-levels contract can't be bypassed by
  // re-pointing a row at an already-used field.
  function levelOptions(used: Set<string>, current: string): typeof groupableFields {
    return groupableFields.filter((f) => f.key === current || !used.has(f.key));
  }
  // Pure mutators over one owner's levels list; each calls that owner's commit.
  type LevelCommit = (next: ViewGroupByLevel[]) => void;
  function addLevelTo(levels: ViewGroupByLevel[], commit: LevelCommit) {
    const pick = groupableFields.find((f) => !usedFields(levels).has(f.key));
    if (pick) commit([...levels, { field: pick.key }]);
  }
  // `setLevelField` / `toggleLevelOrder` are pure and unit-tested in
  // groupLevelEdits.test.ts — the show_empty-preservation invariant (#374)
  // lives there, not in these thin commit wrappers.
  function setLevelFieldAt(levels: ViewGroupByLevel[], commit: LevelCommit, i: number, field: string) {
    commit(setLevelField(levels, i, field));
  }
  function toggleLevelOrderAt(levels: ViewGroupByLevel[], commit: LevelCommit, i: number) {
    commit(toggleLevelOrder(levels, i));
  }
  function removeLevelAt(levels: ViewGroupByLevel[], commit: LevelCommit, i: number) {
    commit(removeAt(levels, i));
  }
  function moveLevelAt(levels: ViewGroupByLevel[], commit: LevelCommit, i: number, delta: -1 | 1) {
    const next = moveAt(levels, i, delta);
    if (next) commit(next);
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

{#snippet organizeSection(levels: ViewGroupByLevel[], commit: LevelCommit)}
  <!-- Organize levels (ADR-0037 §8 + Amendment 1): ordered group-by dropdowns
       for ONE group (a named handle, or the single/unnamed group). Node config,
       not graph shape — so no canvas node competes with Nest. -->
  {@const used = usedFields(levels)}
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
          {#each levelOptions(used, level.field) as f (f.key)}
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
      <button class="add-handle" type="button" title="Add organize level" aria-label="Add organize level" disabled={!canAddLevel(used)} onclick={() => addLevelTo(levels, commit)}>
        + Organize by…
      </button>
    {:else if levels.length === 0}
      <p class="vhint org-empty">No groupable fields on this kind.</p>
    {/if}
  </div>
{/snippet}

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

<style>
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
  /* Shared with the sorter in ViewFlowNode (copied, since scoped styles don't
     cross the component boundary): .vfield, .vhint, .hbtn, .add-handle,
     .organize, .org-head, .lname, .org-empty. */
  .vfield {
    display: block;
    margin: 0 8px 8px;
    width: calc(100% - 16px);
    box-sizing: border-box;
    padding: 3px 5px;
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    font-size: var(--fs-sm);
    background: var(--panel);
  }
  .vhint {
    margin: 0 8px 8px;
    font-size: var(--fs-xs);
    line-height: 1.35;
    color: var(--text-3);
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
  /* A group = its handle row + (when expanded) its own Organize
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
</style>
