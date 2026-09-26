<script lang="ts">
  import { api } from "@/lib/api";
  import IconPicker from "@/components/widgets/IconPicker.svelte";
  import GroupMemberTargets from "@/components/schema/GroupMemberTargets.svelte";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { fieldIconClass, DEFAULT_FIELD_GLYPH } from "@/lib/utils/fieldIcons";
  import { dropPositionFromEvent, reorderByPosition } from "@/lib/utils/listOrder";
  import type { GroupMember, MetadataGroupDefinition, MetadataSchema, NodePickerConfig, SelectOption } from "@/lib/types";

  let {
    // Reusable L2 group definitions (keyed by id) + the layer to save into.
    groups = {},
    layerId,
    // Callback props (#14: App is runes — no on:event on components).
    onChanged = undefined,
    onClose = undefined,
  }: {
    groups?: Record<string, MetadataGroupDefinition>;
    layerId: string;
    onChanged?: (payload: { schema: MetadataSchema }) => void;
    onClose?: () => void;
  } = $props();

  const MEMBER_TYPES: { value: GroupMember["type"]; label: string }[] = [
    { value: "text", label: "Text" },
    { value: "long_text", label: "Long Text" },
    { value: "number", label: "Number" },
    { value: "boolean", label: "Boolean" },
    { value: "select", label: "Select" },
    { value: "multi_select", label: "Multi-select" },
    { value: "entity_ref", label: "Reference" },
    { value: "entity_ref_list", label: "Reference list" },
    { value: "color", label: "Colour" },
  ];

  // null = list view; "__new__" or an id = the editor.
  let editingId = $state<string | null>(null);
  let draftIsNew = $state(false);
  let draftId = $state("");
  let draftIdTouched = $state(false);
  let draftName = $state("");
  // A draft member carries `isNew` while it has never been saved (#2239): only
  // such a member derives its key from its name. Tracked on the member itself,
  // not inferred from its key — a new member typing "Notes" passes through an
  // existing member's key `note` on the way, and must not freeze there.
  type DraftMember = GroupMember & { isNew?: boolean };
  let draftMembers = $state<DraftMember[]>([]);
  // ADR-0096 §1: the group's identity choice — null (none) or one of the
  // group's own `text` members' keys. Tracked by key, kept in step with the
  // members below (a member never saved yet derives its key from its name,
  // so its key can still change under this reference until it's saved).
  let draftIdentity = $state<string | null>(null);
  let error = $state("");
  let busy = $state(false);
  // The group as it stood when the editor opened (null for a new group) — the
  // baseline for detecting a save that would delete data (#2239).
  let originalGroup = $state<MetadataGroupDefinition | null>(null);

  function slug(value: string): string {
    return value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[0-9]/, "g_$&");
  }

  // A confirm message naming what a save would delete — a member key gone
  // entirely, or a select/multi_select option value gone from a member that
  // stays — or null when nothing would be lost. Matches what the backend
  // actually detects (`_reconcile_group_member_data`, read BEFORE the write):
  // a disappearance, never a rename, since both keys and option values are
  // stable once saved.
  function describeGroupDataLoss(original: MetadataGroupDefinition | null, nextMembers: GroupMember[]): string | null {
    if (!original) return null;
    const nextByKey = new Map(nextMembers.map((member) => [member.key, member]));
    const removedMembers = original.members.filter((member) => !nextByKey.has(member.key));
    const optionLosses: string[] = [];
    for (const member of original.members) {
      const next = nextByKey.get(member.key);
      if (!next || (next.type !== "select" && next.type !== "multi_select")) continue;
      const nextValues = new Set((next.options ?? []).map((o) => o.value));
      const removedValues = (member.options ?? []).map((o) => o.value).filter((v) => !nextValues.has(v));
      if (removedValues.length > 0) optionLosses.push(`${member.name} (${removedValues.join(", ")})`);
    }
    if (removedMembers.length === 0 && optionLosses.length === 0) return null;
    const parts: string[] = [];
    if (removedMembers.length > 0) {
      const names = removedMembers.map((m) => m.name).join(", ");
      parts.push(
        `Removing ${names} deletes ${removedMembers.length > 1 ? "their" : "its"} values from every item and change that uses ${removedMembers.length > 1 ? "them" : "it"}.`,
      );
    }
    if (optionLosses.length > 0) {
      parts.push(`Removing ${optionLosses.join("; ")} clears that value everywhere it's used.`);
    }
    return parts.join(" ");
  }

  // System groups (built-in plot-board machinery) are not author-editable and
  // stay out of the manager list (#1003); `groups` still holds them so the
  // save guard below can catch an id collision against a hidden one.
  const groupList = $derived(Object.entries(groups).filter(([, group]) => !group.system));

  function openNew() {
    editingId = "__new__";
    draftIsNew = true;
    draftId = "";
    draftIdTouched = false;
    draftName = "";
    draftMembers = [];
    draftIdentity = null;
    originalGroup = null;
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
    draftIdentity = group.identity ?? null;
    originalGroup = group;
    error = "";
  }

  // The identity choice's candidates: the draft's own `text` members — never
  // the identity member itself once chosen (it's still a text member, so it
  // stays its own candidate; nothing excludes it from the list it's IN).
  const identityCandidates = $derived(draftMembers.filter((member) => member.type === "text"));

  function onIdentityChange(value: string) {
    draftIdentity = value === "" ? null : value;
  }

  function onNameInput(value: string) {
    draftName = value;
    if (draftIsNew && !draftIdTouched) draftId = slug(value);
  }

  function addMember() {
    draftMembers = [...draftMembers, { key: "", name: "", type: "text", isNew: true }];
  }
  function updateMemberName(index: number, value: string) {
    const member = draftMembers[index];
    // A member never saved yet still derives its key from the name (the
    // authoring convenience); one already on disk keeps its key — the name
    // is the human handle, the key is identity (same rule as a node id).
    // ADR-0096 §1: the identity choice tracks a member by key, so a new
    // member's rename — which moves its key — must follow (`upsert_metadata_group`
    // does the same for a member already on disk, keyed by its stable key).
    if (member.isNew) {
      const nextKey = slug(value);
      if (draftIdentity === member.key) draftIdentity = nextKey;
      draftMembers[index] = { ...member, name: value, key: nextKey };
    } else {
      draftMembers[index] = { ...member, name: value };
    }
    draftMembers = draftMembers;
  }
  function updateMemberType(index: number, value: GroupMember["type"]) {
    const member = draftMembers[index];
    // A member retyped away from `text` can no longer be the identity — reset
    // to None rather than leave a stale reference (ADR-0096 §1).
    if (draftIdentity === member.key && value !== "text") draftIdentity = null;
    draftMembers[index] = { ...member, type: value };
    draftMembers = draftMembers;
  }
  function removeMember(index: number) {
    const member = draftMembers[index];
    if (draftIdentity === member.key) draftIdentity = null;
    draftMembers = draftMembers.filter((_, i) => i !== index);
  }
  // #2215: a member's reference targets / select options, authored in the
  // disclosure under its row (GroupMemberTargets.svelte).
  function updateMemberPickerConfig(index: number, config: NodePickerConfig) {
    draftMembers[index] = { ...draftMembers[index], picker_config: config };
    draftMembers = draftMembers;
  }
  function updateMemberOptions(index: number, options: SelectOption[]) {
    draftMembers[index] = { ...draftMembers[index], options };
    draftMembers = draftMembers;
  }
  // Per-member icon picker (the tile is the trigger). null = none open.
  let iconPickerFor = $state<number | null>(null);
  function updateMemberIcon(index: number, icon: string | null) {
    draftMembers[index] = { ...draftMembers[index], icon: icon ?? undefined };
    draftMembers = draftMembers;
    iconPickerFor = null;
  }

  // Drag-reorder members — same before/after insertion-line marker as the
  // field/option lists for a consistent feel.
  let memberDragIndex = $state<number | null>(null);
  let memberDropTarget = $state<{ index: number; position: "before" | "after" } | null>(null);
  function onMemberDragOver(event: DragEvent, index: number) {
    if (memberDragIndex === null || memberDragIndex === index) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    memberDropTarget = { index, position: dropPositionFromEvent(event) };
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
    draftMembers = reorderByPosition(draftMembers, from, index, position);
  }

  async function saveGroup() {
    const id = draftIsNew ? slug(draftId || draftName) : draftId;
    if (!id) {
      error = "A group name is required.";
      return;
    }
    // A new group must not collide with an existing id — including a hidden
    // system group (#1003), which the merge would otherwise let a user group
    // shadow, breaking the feature that consumes it.
    if (draftIsNew && groups[id]) {
      error = `A group with id "${id}" already exists — pick a different name or id.`;
      return;
    }
    // Spread the DRAFT member first: it was loaded as {...member} from the
    // resolved group, so member `options`, `picker_config`, and `default`
    // ride through untouched. Rebuilding from a hand-picked key set here
    // silently wiped all three (plus the group's own icon) on every save —
    // and since #698 makes members a validation-bearing item shape, a wiped
    // select member also disabled its allowed-values check.
    const members = draftMembers
      .filter((member) => member.name.trim())
      .map(({ isNew: _isNew, ...member }) => {
        const next: GroupMember = {
          ...member,
          key: member.key || slug(member.name),
          name: member.name.trim(),
        };
        // #2215 item 3: a type change away from reference/select must not
        // leave the now-irrelevant setting riding along — cleared here, on
        // save, not the moment the type changes (a mid-edit type switch back
        // and forth keeps the draft's own settings until then).
        if (next.type !== "entity_ref" && next.type !== "entity_ref_list") delete next.picker_config;
        if (next.type !== "select" && next.type !== "multi_select") delete next.options;
        // A blank option row (GroupMemberTargets keeps one live while the
        // author is mid-edit, #2215) never reaches the saved definition.
        else if (next.options) next.options = next.options.filter((o) => o.value.trim());
        return next;
      });
    // The group's own icon is deliberately NOT written here: this dialog has
    // no icon editor, so it never round-trips through the draft. Reading it
    // back off the merged `groups` map and re-persisting would copy an
    // ANCESTOR layer's icon down into this layer's file, freezing it against
    // later ancestor changes (the layered-schema hygiene the backend
    // model_dump excludes enforce). Omitting it leaves an ancestor's icon
    // intact in the merged view; a same-layer icon is the same "no editor"
    // limitation member options had before this PR — tracked, not regressed.
    // The identity choice only counts when it still names a `text` member of
    // the members actually being saved (a blank-name row was just dropped
    // above, which could orphan it) — null for anything else, never a stale key.
    const identity = members.some((member) => member.key === draftIdentity && member.type === "text")
      ? draftIdentity
      : null;
    const group: MetadataGroupDefinition = {
      name: draftName.trim() || id,
      members,
      identity,
    };

    const doSave = async () => {
      busy = true;
      error = "";
      try {
        const schema = await api.upsertMetadataGroup(layerId, id, group);
        onChanged?.({ schema });
        editingId = null;
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        busy = false;
      }
    };

    // A member key or a select/multi_select option value that disappears
    // orphans every stored item/row that used it (the backend detects this
    // and cleans it up — #2239 follow-up) — confirm before that happens,
    // rather than silently losing data on a routine "delete a row" edit.
    const removal = describeGroupDataLoss(originalGroup, members);
    if (removal) {
      confirmService.request({
        title: "This will remove stored data",
        message: removal,
        confirmLabel: "Remove & save",
        destructive: true,
        cannotBeUndone: true,
        onConfirm: doSave,
      });
      return;
    }
    await doSave();
  }

  async function deleteGroup(id: string) {
    busy = true;
    error = "";
    try {
      const schema = await api.deleteMetadataGroup(id);
      onChanged?.({ schema });
      editingId = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="gm-backdrop" role="presentation" onmousedown={() => onClose?.()}>
  <div class="gm-dialog" role="dialog" aria-modal="true" aria-label="Reusable groups" tabindex="-1" onmousedown={(event) => event.stopPropagation()}>
    <header class="gm-head">
      <i class="ti ti-stack-2" aria-hidden="true"></i>
      <h2>Reusable groups</h2>
      <button class="gm-close" type="button" onclick={() => onClose?.()}>Close</button>
    </header>

    {#if error}
      <p class="gm-error">{error}</p>
    {/if}

    {#if editingId === null}
      <div class="gm-body">
        {#if groupList.length === 0}
          <p class="muted">No reusable groups yet. A group is a set of fields defined once and reused as a whole on several types.</p>
        {/if}
        {#each groupList as [id, group]}
          <button class="gm-row" type="button" onclick={() => openEdit(id)}>
            <span class="sfr-tile"><i class={`ti ti-${group.icon || "stack-2"}`} aria-hidden="true"></i></span>
            <span class="gm-row-name">{group.name}</span>
            <span class="gm-row-members">{group.members.map((m) => m.name).join(" · ")}</span>
            <code class="gm-row-id">{id}</code>
          </button>
        {/each}
        <div class="gm-foot">
          <button class="sfi-done" type="button" title="New group" aria-label="New group" onclick={openNew}>+</button>
        </div>
      </div>
    {:else}
      <div class="gm-body">
        <div class="gm-editor-head">
          <label class="sfi-field gm-grow">Name
            <input value={draftName} placeholder="Group name" oninput={(event) => onNameInput(event.currentTarget.value)} />
          </label>
          {#if draftIsNew}
            <label class="sfi-field">Id
              <input value={draftId} placeholder="group_id" oninput={(event) => { draftId = slug(event.currentTarget.value); draftIdTouched = true; }} />
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
              ondragover={(event) => onMemberDragOver(event, index)}
              ondragleave={() => { if (memberDropTarget?.index === index) memberDropTarget = null; }}
              ondrop={(event) => { event.preventDefault(); onMemberDrop(index); }}
            >
              <span
                class="gm-member-grip"
                role="button"
                tabindex="-1"
                aria-label="Drag to reorder"
                title="Drag to reorder"
                draggable="true"
                ondragstart={() => (memberDragIndex = index)}
                ondragend={clearMemberDrag}
              ><i class="ti ti-grip-vertical"></i></span>
              <div class="gm-member-icon-anchor">
                <button
                  type="button"
                  class="sfr-tile gm-icon-btn"
                  aria-label="Choose icon"
                  title="Choose icon"
                  onclick={() => (iconPickerFor = iconPickerFor === index ? null : index)}
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
              <input class="gm-member-name" value={member.name} placeholder="Member name" oninput={(event) => updateMemberName(index, event.currentTarget.value)} />
              <select class="gm-member-type" value={member.type} onchange={(event) => updateMemberType(index, event.currentTarget.value as GroupMember["type"])}>
                {#each MEMBER_TYPES as option}
                  <option value={option.value}>{option.label}</option>
                {/each}
              </select>
              <code class="gm-member-key" title={member.key || slug(member.name)}>{member.key || slug(member.name)}</code>
              <button class="link-danger" type="button" onclick={() => removeMember(index)} aria-label="Remove member">✕</button>
            </div>
            <GroupMemberTargets
              member={member}
              onPickerConfigChange={(config) => updateMemberPickerConfig(index, config)}
              onOptionsChange={(options) => updateMemberOptions(index, options)}
            />
          {/each}
          <button class="gm-add-member" type="button" title="Add member" aria-label="Add member" onclick={addMember}>+</button>
        </div>

        <label class="sfi-field">Identity
          <select
            class="gm-identity"
            value={draftIdentity ?? ""}
            onchange={(event) => onIdentityChange(event.currentTarget.value)}
          >
            <option value="">None</option>
            {#each identityCandidates as member (member.key)}
              <option value={member.key}>{member.name || member.key}</option>
            {/each}
          </select>
        </label>

        <div class="gm-editor-foot">
          {#if !draftIsNew}
            <button class="link-danger" type="button" disabled={busy} onclick={() => deleteGroup(draftId)}>Delete group</button>
          {/if}
          <span class="sfi-spacer"></span>
          <button class="sfi-cancel" type="button" onclick={() => (editingId = null)}>Cancel</button>
          <button class="sfi-done" type="button" disabled={busy || !(draftName.trim() || draftId.trim())} onclick={saveGroup}>Save group</button>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .gm-backdrop {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--scrim);
  }
  .gm-dialog {
    width: 540px;
    max-width: calc(100vw - 40px);
    max-height: calc(100vh - 80px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--border-strong);
    border-radius: 14px;
    background: var(--surface);
    box-shadow: var(--elev-3);
  }
  .gm-head {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 13px 16px;
    border-bottom: 1px solid var(--divider);
    background: var(--panel);
  }
  .gm-head h2 {
    flex: 1;
    margin: 0;
    font-family: var(--serif);
    font-size: var(--fs-xl);
    font-weight: 600;
  }
  .gm-close {
    padding: 5px 11px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .gm-error {
    margin: 0;
    padding: 9px 16px;
    background: var(--danger-soft);
    color: var(--danger);
    font-size: var(--fs-sm);
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
    border: 1px solid var(--divider);
    border-radius: 9px;
    background: var(--surface);
    text-align: left;
    cursor: pointer;
  }
  .gm-row:hover {
    border-color: var(--border-strong);
    background: var(--inset);
  }
  .gm-row-name {
    font-size: var(--fs-md);
    font-weight: 600;
  }
  .gm-row-members {
    flex: 1;
    font-size: var(--fs-sm);
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .gm-row-id {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--text-3);
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
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .sfi-field input,
  .gm-member-name,
  .gm-member-type {
    padding: 6px 9px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-md);
  }
  .gm-id-static {
    font-size: var(--fs-xs);
    color: var(--text-3);
    padding-bottom: 7px;
  }
  .lbl {
    font-size: var(--fs-xs);
    font-weight: 800;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--text-3);
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
    color: var(--border-strong);
    font-size: var(--fs-lg);
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
    border-color: var(--accent);
    color: var(--accent-strong);
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
    background: var(--accent);
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
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .gm-identity {
    padding: 6px 9px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-md);
    align-self: flex-start;
  }
  .gm-add-member {
    align-self: flex-start;
    padding: 5px 10px;
    border: 1px dashed var(--border-strong);
    border-radius: 8px;
    background: transparent;
    font-size: var(--fs-sm);
    color: var(--accent);
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
    background: var(--inset);
    border: 1px solid var(--divider);
    color: var(--text-2);
    font-size: var(--fs-lg);
  }
  .sfi-spacer {
    flex: 1;
  }
  .sfi-cancel {
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .sfi-done {
    padding: 6px 14px;
    border: 1px solid var(--accent);
    border-radius: 8px;
    background: var(--accent);
    color: #fff;
    font-size: var(--fs-sm);
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
    font-size: var(--fs-sm);
    color: var(--danger);
    cursor: pointer;
  }
  .link-danger:hover {
    text-decoration: underline;
  }
  .muted {
    font-size: var(--fs-md);
    color: var(--text-3);
  }
</style>
