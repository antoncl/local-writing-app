<script lang="ts">
  // Machine-settings dialog. Holds the editing UI for the user's
  // machine config: default folder, provider API keys, Ollama host,
  // and the color palette editor. The parent loads / persists the
  // draft; this component owns only the local mutations on the draft
  // it's been handed.
  import type {
    MachineSettingsDraft,
    MachineSettingsView,
    ProviderCredentialsView,
    Swatch,
  } from "@/lib/types";
  import Modal from "@/components/dialogs/Modal.svelte";
  import DirectoryPickerModal from "@/components/dialogs/DirectoryPickerModal.svelte";
  import ProviderSubscriptions from "@/components/widgets/ProviderSubscriptions.svelte";
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

  function paletteAddSwatch() {
    if (!draft) return;
    const baseId = "new-color";
    const existing = new Set(draft.palette.map((s) => s.id));
    let id = baseId;
    let n = 2;
    while (existing.has(id)) id = `${baseId}-${n++}`;
    draft.palette = [
      ...draft.palette,
      { id, label: "New color", hex: "#888888" },
    ];
  }

  function paletteRemoveSwatch(index: number) {
    if (!draft) return;
    draft.palette = draft.palette.filter((_, i) => i !== index);
  }

  function paletteMoveSwatch(from: number, to: number) {
    if (!draft) return;
    const list = draft.palette.slice();
    const [moved] = list.splice(from, 1);
    list.splice(to, 0, moved);
    draft.palette = list;
  }

  function paletteSetSwatch(index: number, patch: Partial<Swatch>) {
    if (!draft) return;
    draft.palette = draft.palette.map((s, i) =>
      i === index ? { ...s, ...patch } : s,
    );
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

          <p class="muted">
            Assistants moved to the <strong>Assistants</strong> pane (open from the AI section of the Project pane). Each lives as its own file under the machine config dir and can be overridden by ancestor projects.
          </p>
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

          <section class="palette-editor">
            <h3>Color palette</h3>
            <p class="muted">
              Colors picked here are reusable across types, entries, and select options. The first four (Forest, Slate Blue, Warm Brown, Graphite) seed the context picker's built-in chip colors.
            </p>
            <div class="palette-row palette-header">
              <span></span>
              <span>Id</span>
              <span>Label</span>
              <span>Hex</span>
              <span></span>
            </div>
            {#each draft.palette as swatch, i (swatch.id + ":" + i)}
              <div class="palette-row">
                <span class="palette-swatch-dot" style="background: {swatch.hex}"></span>
                <input
                  type="text"
                  class="palette-id-input"
                  value={swatch.id}
                  pattern="^[a-z0-9][a-z0-9-]*$"
                  title="Lowercase letters, digits, dashes"
                  on:input={(e) => paletteSetSwatch(i, { id: (e.currentTarget as HTMLInputElement).value })}
                />
                <input
                  type="text"
                  class="palette-label-input"
                  value={swatch.label}
                  on:input={(e) => paletteSetSwatch(i, { label: (e.currentTarget as HTMLInputElement).value })}
                />
                <input
                  type="color"
                  class="palette-color-input"
                  value={swatch.hex}
                  on:input={(e) => paletteSetSwatch(i, { hex: (e.currentTarget as HTMLInputElement).value })}
                />
                <span class="palette-row-actions">
                  <button
                    type="button"
                    class="palette-row-btn"
                    title="Move up"
                    disabled={i === 0}
                    on:click={() => paletteMoveSwatch(i, i - 1)}
                  >▲</button>
                  <button
                    type="button"
                    class="palette-row-btn"
                    title="Move down"
                    disabled={i === draft.palette.length - 1}
                    on:click={() => paletteMoveSwatch(i, i + 1)}
                  >▼</button>
                  <button
                    type="button"
                    class="palette-row-btn palette-row-delete"
                    title="Delete swatch"
                    aria-label="Delete swatch"
                    on:click={() => paletteRemoveSwatch(i)}
                  >×</button>
                </span>
              </div>
            {/each}
            <div class="palette-add-row">
              <button type="button" title="Add color" aria-label="Add color" on:click={paletteAddSwatch}>+</button>
            </div>
          </section>
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

  .palette-editor,
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

  .palette-editor h3,
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

  .palette-editor p.muted {
    margin: 0 0 8px;
    font-size: var(--fs-sm);
  }

  .palette-row {
    display: grid;
    grid-template-columns: 22px 1fr 1.5fr 44px auto;
    gap: 8px;
    align-items: center;
    font-size: var(--fs-sm);
  }

  .palette-row.palette-header {
    font-size: var(--fs-xs);
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 0 2px 4px;
    border-bottom: 1px solid var(--divider);
    margin-bottom: 4px;
  }

  .palette-swatch-dot {
    display: inline-block;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 1px solid rgba(0, 0, 0, 0.18);
  }

  .palette-id-input,
  .palette-label-input {
    font-size: var(--fs-sm);
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: 4px;
    min-width: 0;
  }

  .palette-id-input {
    font-family: var(--mono);
  }

  .palette-color-input {
    width: 44px;
    height: 26px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
  }

  .palette-row-actions {
    display: inline-flex;
    gap: 2px;
  }

  .palette-row-btn {
    appearance: none;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: var(--fs-xs);
    color: var(--text-2);
    cursor: pointer;
    line-height: 1;
  }

  .palette-row-btn:hover:not(:disabled) {
    background: var(--panel);
    border-color: var(--border);
  }

  .palette-row-btn:disabled {
    opacity: 0.35;
    cursor: default;
  }

  .palette-row-delete:hover:not(:disabled) {
    color: var(--danger);
    background: var(--danger-soft);
    border-color: var(--danger-border);
  }

  .palette-add-row {
    margin-top: 8px;
  }

  .palette-add-row button {
    font-size: var(--fs-sm);
    padding: 4px 10px;
    border: 1px dashed var(--border-strong);
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
    color: var(--text-2);
  }

  .palette-add-row button:hover {
    border-style: solid;
    background: var(--panel);
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
