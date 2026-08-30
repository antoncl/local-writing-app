<script lang="ts">
  // The inline "create a type" card (#1659). Creating a type/sub-type is the
  // same act with a different `extends`, so this ONE form serves both entry
  // points (the pane-header "+ New type" and a row's "+"): it's seeded with a
  // parent but the `extends` picker is editable. It renders inline in the Types
  // tree (the "Add field" grammar), and on Create the parent (SchemaPanes)
  // persists the type and opens the type editor for fields/colour/icon.
  //
  // A type is a heavier commitment than a field (a class entries instantiate),
  // so the card is deliberately not throwaway: it names what it creates, shows
  // the `id:` the entries/templates will reference, and makes `extends` — the
  // one consequential choice — a visible, editable control.
  import { untrack } from "svelte";
  import { nestingLocalPrefix, slugifyFieldId, nodeTypeDisplayName, type SchemaKind } from "@/lib/utils/schemaTypeHelpers";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import type { MetadataSchemaLayer } from "@/lib/types";

  interface Props {
    kind: SchemaKind;
    // The parent to seed `extends` with (the kind root for the header "+", or
    // the clicked row for a row "+"). Always a concrete FQN.
    seedParentId: string;
    // The kind's root type — used only to title the card ("New type" vs
    // "New sub-type") so the copy matches what the author is really doing.
    kindRootId: string;
    layers?: MetadataSchemaLayer[];
    defaultLayerId?: string;
    // `localKey` is the parent-nested local key this form composed for the id
    // preview; the parent saves it verbatim (kind-prefixed) so preview == saved.
    onSubmit?: (payload: { name: string; parentId: string; layerId: string; localKey: string }) => void;
    onCancel?: () => void;
  }

  let { kind, seedParentId, kindRootId, layers = [], defaultLayerId = "", onSubmit, onCancel }: Props = $props();

  const metadataSchema = $derived($metadataSchemaStore);

  // Every type of this kind is an eligible parent (single inheritance within a
  // kind); sorted by label so the picker is scannable.
  const eligibleParents = $derived(
    Object.entries(metadataSchema?.entry_types ?? {})
      .filter(([, def]) => def.kind === kind)
      .map(([id, def]) => ({ id, label: nodeTypeDisplayName(id, def) }))
      .sort((a, b) => a.label.localeCompare(b.label)),
  );

  // Seeded ONCE at mount (the card remounts per open, so capturing the initial
  // prop is intentional); `untrack` says so and silences state_referenced_locally.
  let name = $state("");
  let extendsId = $state(untrack(() => seedParentId));
  let layerId = $state(untrack(() => defaultLayerId));

  // Live id preview — the FQN entries and templates will reference. Mirrors
  // SchemaPanes' compose-on-save exactly (kind prefix + parent-nested local key)
  // so what's shown is what's saved.
  const localKey = $derived.by(() => {
    const leaf = slugifyFieldId(name);
    if (!leaf) return "";
    const prefix = nestingLocalPrefix(metadataSchema, kind, extendsId);
    return prefix ? `${prefix}:${leaf}` : leaf;
  });
  const previewId = $derived(localKey ? `${kind}:${localKey}` : "");

  const title = $derived(extendsId === kindRootId ? "New type" : "New sub-type");
  // A non-empty local key implies the name has at least one slug-able character,
  // so this doubles as the "has a usable name" guard.
  const canCreate = $derived(Boolean(localKey));

  function submit() {
    if (!canCreate) return;
    onSubmit?.({ name: name.trim(), parentId: extendsId, layerId, localKey });
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Enter") {
      event.preventDefault();
      submit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      onCancel?.();
    }
  }
</script>

<div class="type-create" role="group" aria-label={title}>
  <div class="tc-title">{title}</div>
  <label class="tc-field">
    <span class="tc-label">Name</span>
    <!-- svelte-ignore a11y_autofocus -->
    <input
      class="tc-input"
      value={name}
      placeholder="Enter type name…"
      autofocus
      oninput={(event) => (name = event.currentTarget.value)}
      onkeydown={onKeydown}
    />
  </label>
  <div class="tc-id" aria-live="polite">
    id: {#if previewId}<code>{previewId}</code>{:else}<span class="tc-id-empty">…</span>{/if}
  </div>
  <label class="tc-field">
    <span class="tc-label">extends</span>
    <select class="tc-select" bind:value={extendsId}>
      {#each eligibleParents as parent (parent.id)}
        <option value={parent.id}>{parent.label}</option>
      {/each}
    </select>
  </label>
  {#if layers.length > 1}
    <label class="tc-field">
      <span class="tc-label">Save layer</span>
      <select class="tc-select" bind:value={layerId}>
        {#each layers as layer (layer.id)}
          <option value={layer.id}>{layer.label}</option>
        {/each}
      </select>
    </label>
  {/if}
  <div class="tc-actions">
    <button type="button" class="tc-btn" onclick={() => onCancel?.()}>Cancel</button>
    <button type="button" class="tc-btn tc-create" disabled={!canCreate} onclick={submit}>Create</button>
  </div>
</div>

<style>
  /* Inline create card. Sits in the tree (the "Add field" grammar) but reads as
     a deliberate step: a titled, accent-anchored card, not a throwaway row. */
  .type-create {
    display: grid;
    gap: 8px;
    margin: 4px 0;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    box-shadow: inset 3px 0 0 0 var(--accent);
  }
  .tc-title {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
  }
  .tc-field {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .tc-label {
    min-width: 60px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .tc-input,
  .tc-select {
    flex: 1;
    min-width: 0;
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--inset);
    color: var(--text);
    font-size: var(--fs-md);
  }
  .tc-id {
    font-size: var(--fs-xs);
    color: var(--text-3);
    padding-left: 68px;
  }
  .tc-id code {
    font-family: var(--mono);
  }
  .tc-id-empty {
    color: var(--text-3);
  }
  .tc-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  .tc-btn {
    padding: 5px 12px;
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    font-size: var(--fs-md);
    cursor: pointer;
  }
  .tc-btn:hover:not(:disabled) {
    background: var(--panel);
  }
  .tc-create {
    border-color: var(--accent-emphasis);
    color: var(--accent-emphasis);
  }
  .tc-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
