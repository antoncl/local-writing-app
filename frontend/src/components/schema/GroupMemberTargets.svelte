<script lang="ts">
  // #2215 — a group member's reference targets / select options, authored
  // in place under its row in the Reusable groups dialog. Reuses the SAME
  // editors the schema field editor uses (SchemaFieldInlineEditor) — no new
  // widget: NodePickerConfigEditor (mode="field") for entity_ref /
  // entity_ref_list, SelectOptionsEditor for select / multi_select. Renders
  // nothing for any other member type.
  import { untrack } from "svelte";
  import NodePickerConfigEditor from "@/components/schema/NodePickerConfigEditor.svelte";
  import SelectOptionsEditor, { type OptionDraft } from "@/components/schema/SelectOptionsEditor.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { pickerTargetsSummary } from "@/lib/utils/groupMemberTargets";
  import type { GroupMember, NodePickerConfig, SelectOption } from "@/lib/types";

  interface Props {
    member: GroupMember;
    onPickerConfigChange: (config: NodePickerConfig) => void;
    onOptionsChange: (options: SelectOption[]) => void;
  }

  let { member, onPickerConfigChange, onOptionsChange }: Props = $props();

  const isRefType = $derived(member.type === "entity_ref" || member.type === "entity_ref_list");
  const isSelectType = $derived(member.type === "select" || member.type === "multi_select");

  // An unconfigured member shows an EMPTY tree — never a seeded default the
  // save wouldn't carry, or the tree would claim a target the summary ("Points
  // at nothing yet") and the picker both deny.
  const pickerConfig = $derived<NodePickerConfig>(
    member.picker_config
      ? {
          sources: [...(member.picker_config.sources ?? [])],
          presets: [...(member.picker_config.presets ?? [])],
          multiple: member.picker_config.multiple,
          allow_target_marking: member.picker_config.allow_target_marking,
          create_missing: member.picker_config.create_missing,
        }
      : { sources: [] },
  );
  const optionDrafts = $derived<OptionDraft[]>(
    (member.options ?? []).map((o) => ({
      value: o.value,
      label: o.label ?? "",
      color: o.color ?? null,
      originalValue: o.value,
    })),
  );

  const metadataSchema = $derived($metadataSchemaStore);
  const targetsSummary = $derived(pickerTargetsSummary(member.picker_config, metadataSchema));
  const optionsSummary = $derived((member.options ?? []).map((o) => o.value).join(" · "));

  const unconfigured = $derived(
    isRefType
      ? (member.picker_config?.sources ?? []).length === 0
      : isSelectType
        ? (member.options ?? []).length === 0
        : false,
  );

  // Default open = unconfigured; re-derives whenever the member's TYPE
  // changes (switching into ref/select opens it, since a fresh switch is
  // unconfigured), but never fights a user's own toggle for the same type.
  let open = $state(untrack(() => unconfigured));
  let lastType = untrack(() => member.type);
  $effect(() => {
    const t = member.type;
    if (t !== lastType) {
      lastType = t;
      open = untrack(() => unconfigured);
    }
  });

  function handleToggle(event: Event) {
    open = (event.currentTarget as HTMLDetailsElement).open;
  }

  // Blank-valued rows are kept, not filtered, while the author is mid-edit —
  // SelectOptionsEditor's own "+" adds one to type into, and filtering it
  // out immediately would erase the row the instant it appeared. Final
  // cleanup (drop-blank / trim) happens once, at GroupsManagerDialog's Save
  // (mirrors the schema field editor's own draft → save split).
  function updateOptions(next: OptionDraft[]) {
    onOptionsChange(
      next.map((draft) => {
        const out: SelectOption = { value: draft.value };
        const label = draft.label.trim();
        if (label && label !== draft.value) out.label = label;
        if (draft.color) out.color = draft.color;
        return out;
      }),
    );
  }
</script>

{#if isRefType}
  <details class="gmt" class:warn={!targetsSummary} open={open} ontoggle={handleToggle}>
    <summary>
      <GroupCaret size="xs" ambient />
      {#if targetsSummary}
        <b>Points at</b>{targetsSummary}
      {:else}
        <b>Points at nothing yet</b>— choose what this can reference
      {/if}
    </summary>
    <div class="gmt-body">
      <NodePickerConfigEditor mode="field" config={pickerConfig} onChange={onPickerConfigChange} />
    </div>
  </details>
{:else if isSelectType}
  <details class="gmt" class:warn={!optionsSummary} open={open} ontoggle={handleToggle}>
    <summary>
      {#if optionsSummary}
        <GroupCaret size="xs" ambient /><b>Options</b>{optionsSummary}
      {:else}
        <GroupCaret size="xs" ambient /><b>No options yet</b>
      {/if}
    </summary>
    <div class="gmt-body">
      <SelectOptionsEditor options={optionDrafts} onChange={updateOptions} />
    </div>
  </details>
{/if}

<style>
  /* Matches the chat disclosure vocabulary (ChatRawReply's `.crr` /
     cbv-thinking): a bordered inset well, indented under the member row to
     align with its name input (grip + icon tile width). */
  .gmt {
    margin: 0 0 0 46px;
    border: 1px solid var(--divider);
    border-radius: 9px;
    background: var(--inset);
    padding: 7px 11px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .gmt summary {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    list-style: none;
    --group-caret-open: 0deg;
  }
  .gmt summary::-webkit-details-marker {
    display: none;
  }
  .gmt[open] summary {
    --group-caret-open: 90deg;
    margin-bottom: 8px;
  }
  .gmt summary b {
    color: var(--text);
    font-weight: 600;
    margin-right: 2px;
  }
  .gmt.warn summary,
  .gmt.warn summary b {
    color: var(--star);
  }
  .gmt-body {
    padding-left: 21px;
  }
</style>
