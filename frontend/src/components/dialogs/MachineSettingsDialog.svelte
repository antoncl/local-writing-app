<script lang="ts">
  // Machine-settings dialog. Holds the editing UI for the user's
  // machine config: default folder, provider API keys, Ollama host,
  // and the color palette. The parent loads / persists the draft; this
  // component owns only the local mutations on the draft it's been handed
  // (the palette surface is delegated to PaletteEditor).
  import type {
    MachineSettingsDraft,
    MachineSettingsView,
    ProviderCredentialsView,
  } from "@/lib/types";
  import Modal from "@/components/dialogs/Modal.svelte";
  import DirectoryPickerModal from "@/components/dialogs/DirectoryPickerModal.svelte";
  import ProviderSubscriptions from "@/components/widgets/ProviderSubscriptions.svelte";
  import PaletteEditor from "@/components/widgets/PaletteEditor.svelte";
  import { applyProsePresentation } from "@/lib/utils/prose-presentation";

  // Live-preview the display prefs as the user edits — the master text scaler is
  // visible immediately (it scales the whole UI, this dialog included). The
  // parent reverts to the saved values on Cancel (cancelMachineSettings).
  function previewDisplay() {
    if (draft) applyProsePresentation(draft.display);
  }

  export let open: boolean = false;

  // The projects-root folder picker (#530). Machine Settings used to force a
  // hand-typed absolute path; now it drives the same unified picker as the
  // create flow. Closing the dialog also closes the picker, so it never
  // reappears on top of a later reopen.
  let projectsPickerOpen = false;
  $: if (!open) projectsPickerOpen = false;
  // The persisted view (read-only here — used for `config_path` and
  // any context that shouldn't be edited inline).
  export let settings: MachineSettingsView | null = null;
  // The editable draft. Two-way bound so the parent sees changes to
  // text inputs and the palette without needing per-field callbacks.
  export let draft: MachineSettingsDraft | null = null;
  export let onCancel: () => void = () => {};
  export let onSave: () => void = () => {};

  // PaletteEditor is controlled — it hands back a whole new ordered list, which
  // we assign onto the draft. A member assignment is reactive here the same way
  // the provider-key mutations below are.
  function setPalette(next: MachineSettingsDraft["palette"]) {
    if (draft) draft.palette = next;
  }

  // The scroll became three tabs by concern (ADR-0047 §3): AI credentials,
  // Appearance (writing surface + palette), Storage (the projects root). The
  // controls themselves are unchanged here — this slice only re-homes them.
  type SettingsTab = "ai" | "appearance" | "storage";
  const TABS: { key: SettingsTab; label: string }[] = [
    { key: "ai", label: "AI" },
    { key: "appearance", label: "Appearance" },
    { key: "storage", label: "Storage" },
  ];
  let activeTab: SettingsTab = "ai";
  // Land on the first tab whenever the dialog reopens, never a stale one.
  $: if (!open) activeTab = "ai";

  // The AI tab presents providers via the shared ProviderSubscriptions surface,
  // which edits the flat credential fields on the draft; Save persists the whole
  // draft (batched), so these just mutate it. A member assignment is reactive
  // here the same way the palette mutations are.
  function setProviderKey(field: keyof ProviderCredentialsView, value: string) {
    if (draft) draft[field] = value;
  }
  function clearProviderKey(field: keyof ProviderCredentialsView) {
    if (draft) draft[field] = "";
  }
</script>

{#if open && draft}
  <Modal
    title="Settings"
    label="Settings"
    frameClass="machine-settings-modal"
    frameStyle="--modal-width: min(640px, calc(100vw - 48px)); --modal-max-height: calc(100vh - 80px); --modal-overflow-y: auto;"
  >
      <div class="settings-tabs" role="tablist" aria-label="Settings sections">
        {#each TABS as tab (tab.key)}
          <button
            id={`settings-tab-${tab.key}`}
            type="button"
            class="settings-tab"
            class:active={activeTab === tab.key}
            role="tab"
            aria-selected={activeTab === tab.key}
            aria-controls="settings-panel"
            on:click={() => (activeTab = tab.key)}
          >{tab.label}</button>
        {/each}
      </div>

      <div
        id="settings-panel"
        class="settings-panel"
        role="tabpanel"
        aria-labelledby={`settings-tab-${activeTab}`}
      >
        {#if activeTab === "ai"}
          <p class="muted">Your cloud subscriptions. Keys are masked on read — a provider stays configured until you remove it, and rotating a key replaces it.</p>

          <ProviderSubscriptions
            providers={{
              anthropic_api_key: draft.anthropic_api_key,
              openai_api_key: draft.openai_api_key,
              openrouter_api_key: draft.openrouter_api_key,
              ollama_host: draft.ollama_host,
            }}
            defaultProviderId={draft.default_provider}
            editable
            onSaveKey={setProviderKey}
            onClearKey={clearProviderKey}
          />

          <label>
            Ollama host
            <input type="text" bind:value={draft.ollama_host} placeholder="http://127.0.0.1:11434" />
          </label>
        {:else if activeTab === "appearance"}
          <section class="writing-surface">
            <h3>Writing surface</h3>
            <p class="muted">How prose looks while you write. Display only — it never changes the saved text.</p>

            <label class="range-label">
              Text size — {Math.round(draft.display.ui_scale * 100)}%
              <input
                type="range"
                min="0.85"
                max="1.5"
                step="0.05"
                bind:value={draft.display.ui_scale}
                on:input={previewDisplay}
              />
              <small class="muted">Scales the whole interface. Sizes snap to whole pixels.</small>
            </label>

            <fieldset class="prose-align">
              <legend>Paragraph alignment</legend>
              <label class="choice-row">
                <input type="radio" value="left" bind:group={draft.display.paragraph_align} on:change={previewDisplay} />
                Left (ragged right)
              </label>
              <label class="choice-row">
                <input type="radio" value="justify" bind:group={draft.display.paragraph_align} on:change={previewDisplay} />
                Justified (both edges)
              </label>
            </fieldset>

            <label class="choice-row">
              <input type="checkbox" bind:checked={draft.display.paragraph_indent} on:change={previewDisplay} />
              Indent the first line of each paragraph
            </label>
          </section>

          <PaletteEditor swatches={draft.palette} onChange={setPalette} />
        {:else if activeTab === "storage"}
          <label>
            Projects folder
            <div class="path-picker-row projects-folder-row">
              <input type="text" bind:value={draft.default_projects_folder} placeholder="C:\path\to\writing" />
              <button type="button" on:click={() => (projectsPickerOpen = true)}>Browse…</button>
              <button
                type="button"
                disabled={!draft.default_projects_folder}
                on:click={() => draft && (draft.default_projects_folder = "")}
              >Clear</button>
            </div>
            <!--
              The copy here used to describe this as a creation convenience only.
              Since #429 it is also the outer bound of every project's inheritance
              chain, so clearing it is not a neutral "ask me each time" — it stops
              every project inheriting. Saying so is the difference between an
              informed choice and a silent, machine-wide loss of schema, assistants
              and lore. The label lost "Default" for the same reason: the value is
              authoritative, not a suggestion.
            -->
            <small class="muted">
              The one folder this app works within. New projects are created here, and a project
              inherits from the projects above it up to this folder — so widening it deepens every
              chain at once. Leave empty and each project stands alone, inheriting nothing. The
              project switcher reads recent projects from this config too.
            </small>
          </label>
        {/if}
      </div>

      <p class="muted stored-at">Stored locally at: <code>{settings?.config_path}</code></p>

      {#snippet actions()}
        <button type="button" on:click={onCancel}>Cancel</button>
        <button class="primary" type="button" on:click={onSave}>Save</button>
      {/snippet}
  </Modal>

  <DirectoryPickerModal
    open={projectsPickerOpen}
    initialPath={draft.default_projects_folder}
    title="Projects Folder"
    selectLabel="Use This Folder"
    onClose={() => (projectsPickerOpen = false)}
    onSelect={(path) => {
      if (draft) draft.default_projects_folder = path;
      projectsPickerOpen = false;
    }}
  />
{/if}

<style>
  /* Projects-root row: the shared `.path-picker-row` is a two-column grid
     (input + one button); this variant adds the third column for Browse. */
  .projects-folder-row {
    grid-template-columns: minmax(0, 1fr) auto auto;
  }

  /* Tab strip + panel. The panel restores the 14px grid gap the Modal gives its
     direct children (they're now nested inside this one wrapper). */
  .settings-tabs {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--border);
  }

  .settings-tab {
    appearance: none;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    padding: 6px 12px;
    font-size: var(--fs-md);
    color: var(--text-2);
    cursor: pointer;
  }

  .settings-tab:hover {
    color: var(--text);
  }

  /* Active state is color + the accent underline only — deliberately no
     font-weight change, which would widen the label and reflow the strip on
     every switch. */
  .settings-tab.active {
    color: var(--text);
    border-bottom-color: var(--accent-emphasis);
  }

  .settings-panel {
    display: grid;
    gap: 14px;
  }

  .stored-at {
    font-size: var(--fs-sm);
  }

  .writing-surface {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 0;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
  }

  .writing-surface h3 {
    margin: 0;
    font-size: var(--fs-md);
    font-weight: 600;
  }

  .writing-surface p.muted {
    margin: 0 0 8px;
    font-size: var(--fs-sm);
  }

  .range-label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: var(--fs-sm);
  }

  .writing-surface .prose-align {
    margin: 8px 0 0;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
  }

  .writing-surface legend {
    padding: 0 4px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .choice-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    font-size: var(--fs-sm);
  }

  /* The frame's `.machine-settings-modal` class lives on Modal's own <div>
     (child scope), so it must be :global; the code/label/input it anchors are
     this dialog's slotted content and stay scoped. Sizing is handled by the
     --modal-* custom props set via frameStyle, so there's no bare frame rule. */
  :global(.machine-settings-modal) code {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    background: var(--inset);
    padding: 1px 5px;
    border-radius: 3px;
  }

  :global(.machine-settings-modal) label {
    display: grid;
    gap: 4px;
    font-size: var(--fs-md);
  }

  :global(.machine-settings-modal) input {
    font-size: var(--fs-md);
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
  }
</style>
