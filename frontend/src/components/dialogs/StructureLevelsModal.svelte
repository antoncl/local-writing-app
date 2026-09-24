<script lang="ts">
  // One tree's level list (ADR-0094 §7): what a container at each depth is
  // called, the type it is created as, and whether its `{number}` restarts in
  // each parent or runs on through the tree. The list is also the depth limit —
  // "+" offers no container past its end — so adding a level is how an author
  // makes room for a deeper one ("Act, Chapter" → "Act, Chapter, Sequence").
  //
  // A local draft; only Save writes. A save that would rename or strand
  // containers already in the tree comes back as a conflict, which is put to
  // the author before it is forced.
  import { tick } from "svelte";
  import Modal from "@/components/dialogs/Modal.svelte";
  import { portalToBody } from "@/lib/actions/portal";
  import { projectSession } from "@/lib/stores/projectSession.svelte";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { entryTypeChoicesByKind } from "@/lib/utils/treeHelpers";
  import { entryTypeIsA } from "@/lib/utils/schemaTypeHelpers";
  import type { StructureLevel } from "@/lib/types";

  let {
    open,
    tree,
    containerType,
    levels,
    onClose,
  }: {
    open: boolean;
    tree: "manuscript" | "research";
    containerType: string;
    levels: StructureLevel[];
    onClose: () => void;
  } = $props();

  type DraftLevel = { key: number; name: string; type: string; numbering: "restart" | "continuous" };

  let draft = $state<DraftLevel[]>([]);
  let saving = $state(false);
  let nextKey = 0;
  let list = $state<HTMLOListElement | null>(null);

  // Seed on each open→shown transition only; a structure reload while the
  // dialog is up (our own save) must not overwrite a live edit.
  let wasOpen = false;
  $effect(() => {
    if (open && !wasOpen) {
      draft = levels.map((level) => ({
        key: nextKey++,
        name: level.name,
        type: level.type ?? "",
        numbering: level.numbering ?? "restart",
      }));
    }
    wasOpen = open;
  });

  const schema = $derived($metadataSchemaStore);
  // The types a level may be created as: the tree's container type (the ""
  // option) and every concrete type that is_a it.
  const subTypes = $derived(
    entryTypeChoicesByKind(schema, tree).filter(
      (choice) => choice.id !== containerType && entryTypeIsA(schema, choice.id, containerType),
    ),
  );
  const containerName = $derived(schema?.entry_types[containerType]?.name ?? "Container");
  const valid = $derived(draft.length > 0 && draft.every((level) => level.name.trim() !== ""));

  async function add(): Promise<void> {
    draft.push({ key: nextKey++, name: "", type: "", numbering: "restart" });
    await tick();
    list?.querySelector<HTMLInputElement>("li:last-child .level-name")?.focus();
  }
  function remove(index: number): void {
    draft.splice(index, 1);
  }
  function swap(index: number, other: number): void {
    [draft[index], draft[other]] = [draft[other], draft[index]];
  }

  function payload(): StructureLevel[] {
    return draft.map((level) => ({
      name: level.name.trim(),
      type: level.type || null,
      numbering: level.numbering,
    }));
  }

  async function save(): Promise<void> {
    if (!valid || saving) return;
    saving = true;
    try {
      const levelsToSave = payload();
      const result = await projectSession.setLevels(tree, levelsToSave);
      if (result.status === "saved") {
        onClose();
      } else if (result.status === "conflict") {
        confirmService.request({
          title: "Change levels?",
          message: `${result.message} Their files are not changed; the tree names them by the new list.`,
          confirmLabel: "Change levels",
          destructive: false,
          onConfirm: async () => {
            const forced = await projectSession.setLevels(tree, levelsToSave, true);
            if (forced.status === "saved") onClose();
          },
        });
      }
    } finally {
      saving = false;
    }
  }
</script>

{#if open}
  <div use:portalToBody>
    <Modal
      title={tree === "manuscript" ? "Manuscript levels" : "Research levels"}
      frameStyle="--modal-width: min(580px, 94vw);"
    >
      <p class="levels-help">What a container is called at each depth, from the top. A container can only be added at a level listed here.</p>
      <ol class="levels-list" bind:this={list}>
        {#each draft as level, index (level.key)}
          <li class="level-row">
            <span class="level-depth" aria-hidden="true">{index + 1}</span>
            <input
              class="level-name"
              aria-label={`Level ${index + 1} name`}
              placeholder="Name"
              bind:value={level.name}
            />
            <select class="level-type" aria-label={`Level ${index + 1} type`} bind:value={level.type}>
              <option value="">{containerName}</option>
              {#each subTypes as choice (choice.id)}
                <option value={choice.id}>{choice.name}</option>
              {/each}
            </select>
            <select
              class="level-numbering"
              aria-label={`Level ${index + 1} numbering`}
              bind:value={level.numbering}
            >
              <option value="restart">Restart per parent</option>
              <option value="continuous">Run on</option>
            </select>
            <span class="level-actions">
              <button
                type="button"
                aria-label={`Move level ${index + 1} up`}
                disabled={index === 0}
                onclick={() => swap(index, index - 1)}>↑</button
              >
              <button
                type="button"
                aria-label={`Move level ${index + 1} down`}
                disabled={index === draft.length - 1}
                onclick={() => swap(index, index + 1)}>↓</button
              >
              <button
                type="button"
                aria-label={`Remove level ${index + 1}`}
                disabled={draft.length === 1}
                onclick={() => remove(index)}>×</button
              >
            </span>
          </li>
        {/each}
      </ol>
      <button type="button" class="level-add" onclick={add}>Add level</button>
      {#snippet actions()}
        <button type="button" onclick={onClose}>Cancel</button>
        <button type="button" class="primary" disabled={!valid || saving} onclick={save}>Save</button>
      {/snippet}
    </Modal>
  </div>
{/if}

<style>
  .levels-help {
    margin: 0 0 12px;
    font-size: var(--fs-sm);
    color: var(--text-2);
    line-height: 1.4;
  }
  .levels-list {
    display: grid;
    gap: 6px;
    margin: 0 0 10px;
    padding: 0;
    list-style: none;
  }
  .level-row {
    display: grid;
    grid-template-columns: 16px minmax(0, 1fr) minmax(0, 0.8fr) minmax(0, 1.2fr) auto;
    gap: 6px;
    align-items: center;
  }
  .level-depth {
    font-size: var(--fs-xs);
    color: var(--text-3);
    text-align: right;
  }
  .level-name,
  .level-type,
  .level-numbering {
    min-width: 0;
    font-size: var(--fs-sm);
  }
  .level-actions {
    display: inline-flex;
    gap: 2px;
  }
  .level-actions button {
    padding: 2px 6px;
    font-size: var(--fs-sm);
  }
  .level-add {
    width: auto;
    font-size: var(--fs-sm);
  }
</style>
