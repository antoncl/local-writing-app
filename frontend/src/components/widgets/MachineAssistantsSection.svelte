<script lang="ts">
  // Machine Settings → Assistants tab (#2444): the machine layer's own roster —
  // add, edit, reorder, un-list, delete — without a project open. The list is
  // the Assistants pane itself in its "machine" scope; writes go through
  // machineAssistants.ts (shared with the New-project wizard).
  import { onMount } from "svelte";
  import Assistants from "@/components/panes/Assistants.svelte";
  import ProviderTierPicker from "@/components/widgets/ProviderTierPicker.svelte";
  import { defaultView } from "@/lib/views/evaluateView";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import {
    deleteMachineAssistant,
    hireMachineAssistant,
    loadMachineAssistants,
    reorderMachineAssistants,
    unlistMachineAssistant,
    updateMachineAssistant,
  } from "@/lib/stores/machineAssistants";
  import type { AICapabilityTier, AIPolicy, AssistantEntrySummary } from "@/lib/types";

  let { policy }: { policy: AIPolicy } = $props();

  // With no project open the schema store is empty, and the default view's
  // roster falls back to a `assistant:base` root that no assistant descends
  // from — so state the concrete root (`assistant:assistant`) then. With a
  // schema loaded, its own kind root (and sub-types) applies as usual.
  const viewSpec = $derived(
    $metadataSchemaStore
      ? defaultView("assistant", $metadataSchemaStore)
      : { ...defaultView("assistant"), expr: { descendants_of: "assistant:assistant" } },
  );

  let entries = $state<AssistantEntrySummary[]>([]);
  let busy = $state(false);
  let error = $state("");

  // The inline form: `null` = closed, "new" = hiring, otherwise the id being edited.
  let formFor = $state<string | null>(null);
  let formTitle = $state("");
  let provider = $state("");
  let tier = $state<AICapabilityTier | "">("");
  let model = $state("");

  const editing = $derived(formFor && formFor !== "new" ? entries.find((e) => e.id === formFor) : undefined);

  async function reload(): Promise<void> {
    entries = await loadMachineAssistants();
  }

  async function act(fn: () => Promise<void>): Promise<void> {
    busy = true;
    error = "";
    try {
      await fn();
      await reload();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    void act(async () => {});
  });

  function beginHire(): void {
    formFor = "new";
    formTitle = "";
    provider = "";
    tier = "";
    model = "";
  }

  function beginEdit(id: string): void {
    const entry = entries.find((e) => e.id === id);
    if (!entry) return;
    formFor = id;
    formTitle = entry.title;
    // Seed the picker from what the assistant stores; it keeps a preset provider.
    provider = String(entry.metadata?.ai_provider ?? "");
    tier = (entry.metadata?.ai_capability_tier ?? "") as AICapabilityTier | "";
    model = String(entry.metadata?.ai_model ?? "");
  }

  function closeForm(): void {
    formFor = null;
  }

  async function submit(): Promise<void> {
    const id = formFor;
    if (!id) return;
    const title = formTitle.trim() || (id === "new" ? "Untitled assistant" : (editing?.title ?? ""));
    await act(async () => {
      if (id === "new") await hireMachineAssistant(title, provider, tier, model);
      else await updateMachineAssistant(id, { title, provider, tier, model });
      closeForm();
    });
  }

  function requestDelete(entry: AssistantEntrySummary): void {
    confirmService.request({
      title: "Delete Assistant",
      message: `Delete "${entry.title}"? This removes the assistant file from the machine layer — every project that uses it loses it.`,
      confirmLabel: "Delete Assistant",
      destructive: true,
      onConfirm: () =>
        act(async () => {
          await deleteMachineAssistant(entry.id);
          closeForm();
        }),
    });
  }
</script>

<section class="machine-assistants" data-testid="machine-assistants">
  <h3>Assistants</h3>
  <p class="muted">
    Assistants shared by every project. A project can reorder or un-list them for itself; changes here apply immediately.
  </p>

  {#if error}
    <p class="ai-health-result fail" role="alert">✗ {error}</p>
  {/if}

  <div class="roster">
    <Assistants
      {entries}
      {viewSpec}
      scope="machine"
      onSetOrder={(ids) => act(() => reorderMachineAssistants(ids))}
      onUnlist={(id) => act(() => unlistMachineAssistant(id))}
      onOpenEntry={(id) => beginEdit(id)}
    />
  </div>

  {#if formFor}
    <div class="inline-form" data-testid="machine-assistant-form">
      {#if editing}
        <strong>Edit {editing.title}</strong>
      {/if}
      <label>
        Name
        <input type="text" bind:value={formTitle} placeholder="Drafting assistant" />
      </label>
      {#key formFor}
        <ProviderTierPicker
          {policy}
          bind:provider
          bind:tier
          bind:model
          onChange={(detail) => {
            provider = detail.provider;
            tier = detail.tier;
            model = detail.model;
          }}
        />
      {/key}
      <div class="inline-form-actions">
        <button type="button" disabled={busy} onclick={closeForm}>Cancel</button>
        {#if editing}
          <button
            type="button"
            class="danger"
            data-testid="machine-assistant-delete"
            disabled={busy}
            onclick={() => editing && requestDelete(editing)}>Delete…</button
          >
        {/if}
        <!-- Gate on a chosen provider so a stray save can't point an assistant at
             a provider you never configured (same as the wizard's Hire). -->
        <button
          type="button"
          class="primary"
          data-testid="machine-assistant-save"
          disabled={busy || !provider}
          onclick={() => void submit()}>{editing ? "Save" : "Hire"}</button
        >
      </div>
      <small class="muted"
        >Other fields (prompt, temperature, tags) are in the assistant's editor — open it from the Assistants pane in a project.</small
      >
    </div>
  {:else}
    <button
      type="button"
      class="inline-add-btn"
      data-testid="machine-assistant-hire"
      disabled={busy}
      onclick={beginHire}>+ Hire an assistant…</button
    >
  {/if}
</section>

<style>
  .roster {
    max-height: 260px;
    overflow-y: auto;
    margin: 8px 0;
  }

  .danger {
    margin-right: auto;
    color: var(--danger);
  }
</style>
