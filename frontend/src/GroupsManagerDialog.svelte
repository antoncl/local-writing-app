<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { api } from "./api";
  import IconPicker from "./IconPicker.svelte";
  import { fieldIconClass, DEFAULT_FIELD_GLYPH } from "./fieldIcons";
  import type { GroupMember, MetadataGroupDefinition, MetadataSchema } from "./types";

  // Reusable L2 group definitions (keyed by id) + the layer to save into.
  export let groups: Record<string, MetadataGroupDefinition> = {};
  export let layerId: string;

  const dispatch = createEventDispatcher<{ changed: { schema: MetadataSchema }; close: void }>();

  const MEMBER_TYPES: { value: GroupMember["type"]; label: string }[] = [
    { value: "text", label: "Text" },
    { value: "long_text", label: "Long Text" },
    { value: "number", label: "Number" },
    { value: "boolean", label: "Boolean" },
    { value: "select", label: "Select" },
    { value: "multi_select", label: "Multi-select" },
    { value: "entity_ref", label: "Reference" },
    { value: "entity_ref_list", label: "Reference list" },
    { value: "tags", label: "Tags" },
    { value: "color", label: "Colour" },
  ];

  // null = list view; "__new__" or an id = the editor.
  let editingId: string | null = null;
  let draftIsNew = false;
  let draftId = "";
  let draftIdTouched = false;
  let draftName = "";
  let draftMembers: GroupMember[] = [];
  let error = "";
  let busy = false;

  function slug(value: string): string {
    return value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[0-9]/, "g_$&");
  }

  $: groupList = Object.entries(groups);

  function openNew() {
    editingId = "__new__";
    draftIsNew = true;
    draftId = "";
    draftIdTouched = false;
    draftName = "";
    draftMembers = [];
    error = "";
  }

  function openEdit(id: string) {
    const group = groups[id];
    if (!group) return;
    editingId = id;
    draftIsNew = false;
    draftId = id;
    draftIdTouched = true;
    draftName = group.name;
    draftMembers = group.members.map((member) => ({ ...member }));
    error = "";
  }

  function onNameInput(value: string) {
    draftName = value;
    if (draftIsNew && !draftIdTouched) draftId = slug(value);
  }

  function addMember() {
    draftMembers = [...draftMembers, { key: "", name: "", type: "text" }];
  }
  function updateMemberName(index: number, value: string) {
    const member = draftMembers[index];
    draftMembers[index] = { ...member, name: value, key: slug(value) };
    draftMembers = draftMembers;
  }
  function updateMemberType(index: number, value: GroupMember["type"]) {
    draftMembers[index] = { ...draftMembers[index], type: value };
    draftMembers = draftMembers;
  }
  function removeMember(index: number) {
    draftMembers = draftMembers.filter((_, i) => i !== index);
  }
  // Per-member icon picker (the tile is the trigger). null = none open.
  let iconPickerFor: number | null = null;
  function updateMemberIcon(index: number, icon: string | null) {
    draftMembers[index] = { ...draftMembers[index], icon: icon ?? undefined };
    draftMembers = draftMembers;
    iconPickerFor = null;
  }

  // Drag-reorder members — same before/after insertion-line marker as the
  // field/option lists for a consistent feel.
  let memberDragIndex: number | null = null;
  let memberDropTarget: { index: number; position: "before" | "after" } | null = null;
  function onMemberDragOver(event: DragEvent, index: number) {
    if (memberDragIndex === null || memberDragIndex === index) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const position = event.clientY < rect.top + rect.height / 2 ? "before" : "after";
    memberDropTarget = { index, position };
  }
  function clearMemberDrag() {
    memberDragIndex = null;
    memberDropTarget = null;
  }
  function onMemberDrop(index: number) {
    const from = memberDragIndex;
    const position = memberDropTarget?.position ?? "before";
    clearMemberDrag();
    if (from === null || from === index) return;
    const next = [...draftMembers];
    const [moved] = next.splice(from, 1);
    let insertAt = index > from ? index - 1 : index;
    if (position === "after") insertAt += 1;
    next.splice(insertAt, 0, moved);
    draftMembers = next;
  }

  async function saveGroup() {
    const id = draftIsNew ? slug(draftId || draftName) : draftId;
    if (!id) {
      error = "A group name is required.";
      return;
    }
    const members = draftMembers
      .filter((member) => member.name.trim())
      .map((member) => ({
        key: member.key || slug(member.name),
        name: member.name.trim(),
        type: member.type,
        ...(member.icon ? { icon: member.icon } : {}),
      }));
    const group: MetadataGroupDefinition = {
      name: draftName.trim() || id,
      members,
    };
    busy = true;
    error = "";
    try {
      const schema = await api.upsertMetadataGroup(layerId, id, group);
      dispatch("changed", { schema });
      editingId = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  async function deleteGroup(id: string) {
    busy = true;
    error = "";
    try {
      const schema = await api.deleteMetadataGroup(id);
      dispatch("changed", { schema });
      editingId = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="gm-backdrop" role="presentation" on:mousedown={() => dispatch("close")}>
  <div class="gm-dialog" role="dialog" aria-modal="true" aria-label="Reusable groups" tabindex="-1" on:mousedown|stopPropagation>
    <header class="gm-head">
      <i class="ti ti-stack-2" aria-hidden="true"></i>
      <h2>Reusable groups</h2>
      <button class="gm-close" type="button" on:click={() => dispatch("close")}>Close</button>
    </header>

    {#if error}
      <p class="gm-error">{error}</p>
    {/if}

    {#if editingId === null}
      <div class="gm-body">
        {#if groupList.length === 0}
          <p class="muted">No reusable groups yet. A group (e.g. GMO = Goal / Motivation / Obstacle) can be applied to several types.</p>
        {/if}
        {#each groupList as [id, group]}
          <button class="gm-row" type="button" on:click={() => openEdit(id)}>
            <span class="sfr-tile"><i class={`ti ti-${group.icon || "stack-2"}`} aria-hidden="true"></i></span>
            <span class="gm-row-name">{group.name}</span>
            <span class="gm-row-members">{group.members.map((m) => m.name).join(" · ")}</span>
            <code class="gm-row-id">{id}</code>
          </button>
        {/each}
        <div class="gm-foot">
          <button class="sfi-done" type="button" on:click={openNew}>+ New group</button>
        </div>
      </div>
    {:else}
      <div class="gm-body">
        <div class="gm-editor-head">
          <label class="sfi-field gm-grow">Name
            <input value={draftName} placeholder="GMO" on:input={(event) => onNameInput(event.currentTarget.value)} />
          </label>
          {#if draftIsNew}
            <label class="sfi-field">Id
              <input value={draftId} placeholder="gmo" on:input={(event) => { draftId = slug(event.currentTarget.value); draftIdTouched = true; }} />
            </label>
          {:else}
            <span class="gm-id-static">id <code>{draftId}</code></span>
          {/if}
        </div>

        <span class="lbl">Members</span>
        <div class="gm-members">
          {#each draftMembers as member, index (index)}
            <div
              class="gm-member"
              role="listitem"
              class:dragging={memberDragIndex === index}
              class:drop-before={memberDropTarget?.index === index && memberDropTarget?.position === "before"}
              class:drop-after={memberDropTarget?.index === index && memberDropTarget?.position === "after"}
              on:dragover={(event) => onMemberDragOver(event, index)}
              on:dragleave={() => { if (memberDropTarget?.index === index) memberDropTarget = null; }}
              on:drop|preventDefault={() => onMemberDrop(index)}
            >
              <span
                class="gm-member-grip"
                role="button"
                tabindex="-1"
                aria-label="Drag to reorder"
                title="Drag to reorder"
                draggable="true"
                on:dragstart={() => (memberDragIndex = index)}
                on:dragend={clearMemberDrag}
              ><i class="ti ti-grip-vertical"></i></span>
              <div class="gm-member-icon-anchor">
                <button
                  type="button"
                  class="sfr-tile gm-icon-btn"
                  aria-label="Choose icon"
                  title="Choose icon"
                  on:click={() => (iconPickerFor = iconPickerFor === index ? null : index)}
                >
                  <i class={fieldIconClass({ type: member.type, icon: member.icon ?? null })} aria-hidden="true"></i>
                </button>
                {#if iconPickerFor === index}
                  <div class="gm-icon-pop">
                    <IconPicker
                      value={member.icon ?? null}
                      defaultGlyph={DEFAULT_FIELD_GLYPH[member.type] ?? "letter-case"}
                      fieldLabel={member.name || "member"}
                      onSelect={(icon) => updateMemberIcon(index, icon)}
                      onClose={() => (iconPickerFor = null)}
                    />
                  </div>
                {/if}
              </div>
              <input class="gm-member-name" value={member.name} placeholder="Goal" on:input={(event) => updateMemberName(index, event.currentTarget.value)} />
              <select class="gm-member-type" value={member.type} on:change={(event) => updateMemberType(index, event.currentTarget.value as GroupMember["type"])}>
                {#each MEMBER_TYPES as option}
                  <option value={option.value}>{option.label}</option>
                {/each}
              </select>
              <code class="gm-member-key" title={member.key || slug(member.name)}>{member.key || slug(member.name)}</code>
              <button class="link-danger" type="button" on:click={() => removeMember(index)} aria-label="Remove member">✕</button>
            </div>
          {/each}
          <button class="gm-add-member" type="button" on:click={addMember}>+ Add member</button>
        </div>

        <div class="gm-editor-foot">
          {#if !draftIsNew}
            <button class="link-danger" type="button" disabled={busy} on:click={() => deleteGroup(draftId)}>Delete group</button>
          {/if}
          <span class="sfi-spacer"></span>
          <button class="sfi-cancel" type="button" on:click={() => (editingId = null)}>Cancel</button>
          <button class="sfi-done" type="button" disabled={busy || !(draftName.trim() || draftId.trim())} on:click={saveGroup}>Save group</button>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .gm-backdrop {
    position: fixed;
    inset: 0;
    z-index: 200;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(20, 30, 27, 0.32);
  }
  .gm-dialog {
    width: 540px;
    max-width: calc(100vw - 40px);
    max-height: calc(100vh - 80px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--border-strong, #b4c2bc);
    border-radius: 14px;
    background: var(--surface, #fff);
    box-shadow: 0 20px 60px rgba(20, 40, 35, 0.28);
  }
  .gm-head {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 13px 16px;
    border-bottom: 1px solid var(--divider, #e2e8e5);
    background: var(--panel, #edf3f1);
  }
  .gm-head h2 {
    flex: 1;
    margin: 0;
    font-family: Newsreader, Georgia, serif;
    font-size: 18px;
    font-weight: 600;
  }
  .gm-close {
    padding: 5px 11px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    font-size: 12.5px;
    cursor: pointer;
  }
  .gm-error {
    margin: 0;
    padding: 9px 16px;
    background: var(--danger-soft);
    color: var(--danger);
    font-size: 12.5px;
  }
  .gm-body {
    display: flex;
    flex-direction: column;
    gap: 9px;
    padding: 14px 16px;
    overflow: auto;
  }
  .gm-row {
    display: flex;
    align-items: center;
    gap: 11px;
    width: 100%;
    padding: 9px 10px;
    border: 1px solid var(--divider, #e2e8e5);
    border-radius: 9px;
    background: var(--surface, #fff);
    text-align: left;
    cursor: pointer;
  }
  .gm-row:hover {
    border-color: var(--border-strong, #b4c2bc);
    background: var(--inset, #f1f5f3);
  }
  .gm-row-name {
    font-size: 14px;
    font-weight: 600;
  }
  .gm-row-members {
    flex: 1;
    font-size: 12px;
    color: var(--text-3, #74817b);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .gm-row-id {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
    color: var(--text-3, #74817b);
  }
  .gm-foot,
  .gm-editor-foot {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 4px;
  }
  .gm-editor-head {
    display: flex;
    align-items: flex-end;
    gap: 12px;
  }
  .gm-grow {
    flex: 1;
  }
  .sfi-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
    color: var(--text-2, #4d5753);
  }
  .sfi-field input,
  .gm-member-name,
  .gm-member-type {
    padding: 6px 9px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    font-size: 13px;
  }
  .gm-id-static {
    font-size: 11px;
    color: var(--text-3, #74817b);
    padding-bottom: 7px;
  }
  .lbl {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--text-3, #74817b);
  }
  .gm-members {
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .gm-member {
    display: flex;
    align-items: center;
    gap: 9px;
    position: relative;
  }
  .gm-member.dragging {
    opacity: 0.5;
  }
  .gm-member-grip {
    flex: none;
    display: inline-flex;
    color: var(--border-strong, #b4c2bc);
    font-size: 15px;
    cursor: grab;
  }
  .gm-member-icon-anchor {
    position: relative;
    flex: none;
  }
  .gm-icon-btn {
    padding: 0;
    cursor: pointer;
  }
  .gm-icon-btn:hover {
    border-color: var(--accent, #2f6f5e);
    color: var(--accent-strong, #234e43);
  }
  .gm-icon-pop {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 60;
  }
  .gm-member.drop-before::before,
  .gm-member.drop-after::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--accent, #2f6f5e);
    pointer-events: none;
    z-index: 2;
  }
  .gm-member.drop-before::before {
    top: -4px;
  }
  .gm-member.drop-after::after {
    bottom: -4px;
  }
  /* Fixed-width columns so members line up in neat columns: only the name
     flexes (and is therefore identical across rows); the type select and the
     key are fixed so they don't shift with content. */
  .gm-member-name {
    flex: 1 1 0;
    min-width: 0;
  }
  .gm-member-type {
    flex: 0 0 140px;
    width: 140px;
    min-width: 0;
  }
  .gm-member-key {
    flex: 0 0 84px;
    width: 84px;
    text-align: right;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
    color: var(--text-3, #74817b);
  }
  .gm-add-member {
    align-self: flex-start;
    padding: 5px 10px;
    border: 1px dashed var(--border-strong, #b4c2bc);
    border-radius: 8px;
    background: transparent;
    font-size: 12.5px;
    color: var(--accent, #2f6f5e);
    cursor: pointer;
  }
  .sfr-tile {
    flex: none;
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 7px;
    background: var(--inset, #f1f5f3);
    border: 1px solid var(--divider, #e2e8e5);
    color: var(--text-2, #4d5753);
    font-size: 15px;
  }
  .sfi-spacer {
    flex: 1;
  }
  .sfi-cancel {
    padding: 6px 12px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    font-size: 12.5px;
    cursor: pointer;
  }
  .sfi-done {
    padding: 6px 14px;
    border: 1px solid var(--accent, #2f6f5e);
    border-radius: 8px;
    background: var(--accent, #2f6f5e);
    color: #fff;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
  }
  .sfi-done:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .link-danger {
    border: 0;
    background: transparent;
    font-size: 12px;
    color: var(--danger);
    cursor: pointer;
  }
  .link-danger:hover {
    text-decoration: underline;
  }
  .muted {
    font-size: 13px;
    color: var(--text-3, #74817b);
  }
</style>
