<script lang="ts">
  // Machine-settings dialog. Holds the editing UI for the user's
  // machine config: default folder, provider API keys, Ollama host,
  // and the color palette. The parent loads / persists the draft; this
  // component owns only the local mutations on the draft it's been handed
  // (the palette surface is delegated to PaletteEditor).
  import type {
    AIHealthResponse,
    AIPolicy,
    MachineSettingsDraft,
    MachineSettingsView,
    ProviderCredentialsView,
  } from "@/lib/types";
  import type { AIPolicyDraft } from "@/lib/stores/aiSettings.svelte";
  import Modal from "@/components/dialogs/Modal.svelte";
  import PolicyRadioGroup from "@/components/widgets/PolicyRadioGroup.svelte";
  import ProjectsFolderPicker from "@/components/widgets/ProjectsFolderPicker.svelte";
  import ProviderSubscriptions from "@/components/widgets/ProviderSubscriptions.svelte";
  import PaletteEditor from "@/components/widgets/PaletteEditor.svelte";
  import { applyProsePresentation } from "@/lib/utils/prose-presentation";

  // Live-preview the display prefs as the user edits — the master text scaler is
  // visible immediately (it scales the whole UI, this dialog included). The
  // parent reverts to the saved values on Cancel (cancelMachineSettings).
  function previewDisplay() {
    if (draft) applyProsePresentation(draft.display);
  }

  let {
    open = false,
    // The persisted view (read-only here — used for `config_path` and
    // any context that shouldn't be edited inline).
    settings = null,
    // The editable draft. Two-way bound so the parent sees changes to
    // text inputs and the palette without needing per-field callbacks.
    draft = $bindable(null),
    onCancel = () => {},
    onSave = () => {},
    // The application-global default AI policy (#746). Deliberately NOT part of
    // the batched `draft`/`onSave`: widening AI permission must be its own
    // explicit gesture, never a side effect of saving an unrelated field like a
    // provider key (decisions_ai_permission_fails_closed). It holds its own draft,
    // seeded from the persisted `settings` on each open, and commits via
    // `onApplyPolicy` — mirroring the per-project AIPolicyModal.
    onApplyPolicy = async () => false,
    // The AI-connection test, re-homed from the Project pane (#629): it pings the
    // default assistant's provider, so it belongs beside the providers it tests.
    // The host owns the gate — the ping needs an open project with AI access, so
    // `disabledReason` is non-null (and shown) when it can't run.
    health = null,
  }: {
    open?: boolean;
    settings?: MachineSettingsView | null;
    draft?: MachineSettingsDraft | null;
    onCancel?: () => void;
    onSave?: () => void;
    onApplyPolicy?: (policy: AIPolicy) => Promise<boolean>;
    health?: {
      onCheck: () => void;
      result: AIHealthResponse | null;
      checking: boolean;
      disabledReason: string | null;
    } | null;
  } = $props();

  // Typed as the draft superset so it can bind the shared PolicyRadioGroup, but
  // the "inherit" stop is never rendered here (the app-wide floor can't inherit),
  // so `applyPolicy` narrows back to AIPolicy before committing.
  let policyDraft = $state<AIPolicyDraft>("off");
  let policyWasOpen = $state(false);
  let applyingPolicy = $state(false);
  // Snapshot the stored policy on each open→shown transition only; our own apply
  // re-syncs `settings` from the parent, and re-seeding on that would be a no-op
  // anyway (draft already equals the saved value).
  $effect(() => {
    if (open !== policyWasOpen) {
      if (open) policyDraft = settings?.ai_policy ?? "off";
      policyWasOpen = open;
    }
  });
  const policyDirty = $derived(policyDraft !== (settings?.ai_policy ?? "off"));

  async function applyPolicy() {
    // The floor has no "inherit" stop; guard so the type stays honest and a
    // stray value can never widen past the three real policies (fails-closed).
    if (applyingPolicy || policyDraft === "inherit") return;
    applyingPolicy = true;
    await onApplyPolicy(policyDraft);
    applyingPolicy = false;
  }

  // PaletteEditor is controlled — it hands back a whole new ordered list, which
  // we assign onto the draft. A member assignment is reactive here the same way
  // the provider-key mutations below are.
  function setPalette(next: MachineSettingsDraft["palette"]) {
    if (draft) draft.palette = next;
  }

  // The scroll became tabs by concern (ADR-0047 §3): AI credentials, Writing
  // (prose display), Palette (reusable colours), Storage (the projects root).
  // Writing and Palette are separate tabs so neither runs tall — the palette
  // alone can be dozens of swatches.
  type SettingsTab = "ai" | "writing" | "palette" | "storage";
  const TABS: { key: SettingsTab; label: string }[] = [
    { key: "ai", label: "AI" },
    { key: "writing", label: "Writing" },
    { key: "palette", label: "Palette" },
    { key: "storage", label: "Storage" },
  ];
  let activeTab = $state<SettingsTab>("ai");
  // Land on the first tab whenever the dialog reopens, never a stale one.
  $effect(() => {
    if (!open) activeTab = "ai";
  });

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
      <div class="tab-strip" role="tablist" aria-label="Settings sections">
        {#each TABS as tab (tab.key)}
          <button
            id={`settings-tab-${tab.key}`}
            type="button"
            class="tab-strip-tab"
            class:active={activeTab === tab.key}
            role="tab"
            aria-selected={activeTab === tab.key}
            aria-controls="settings-panel"
            onclick={() => (activeTab = tab.key)}
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
          <section class="app-policy">
            <h3>Default AI access</h3>
            <p class="muted">
              The policy a project falls back to when it states none of its own — the top of every
              inheritance chain. New and standalone projects resolve here. Applied on its own, so a
              stray click never widens AI access.
            </p>
            <PolicyRadioGroup bind:value={policyDraft} />
            <div class="button-row">
              <button
                type="button"
                class="primary"
                disabled={!policyDirty || applyingPolicy}
                onclick={applyPolicy}
              >{applyingPolicy ? "Applying…" : "Apply"}</button>
            </div>
          </section>

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

          {#if health}
            <section class="health-check">
              <h3>Connection</h3>
              <p class="muted">Pings the default assistant (the topmost) to confirm its provider answers. To test a specific assistant, use its Test button in the Assistants pane.</p>
              <div class="button-row">
                <button
                  type="button"
                  disabled={health.checking || !!health.disabledReason}
                  title={health.disabledReason ?? "Ping the default assistant's provider"}
                  onclick={() => health?.onCheck()}
                >{health.checking ? "Testing…" : "Test connection"}</button>
              </div>
              {#if health.disabledReason}
                <small class="muted">{health.disabledReason}</small>
              {/if}
              {#if health.result}
                <p class="ai-health-result" class:ok={health.result.ok} class:fail={!health.result.ok}>
                  {#if health.result.ok}
                    ✓ {#if health.result.assistant_name}{health.result.assistant_name} · {/if}{health.result.provider} · {health.result.model} · {health.result.latency_ms} ms
                  {:else}
                    ✗ {#if health.result.assistant_name}{health.result.assistant_name} · {/if}{health.result.provider || "(no provider)"} — {health.result.error}
                  {/if}
                </p>
              {/if}
            </section>
          {/if}
        {:else if activeTab === "writing"}
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
                oninput={previewDisplay}
              />
              <small class="muted">Scales the whole interface. Sizes snap to whole pixels.</small>
            </label>

            <fieldset class="prose-align">
              <legend>Paragraph alignment</legend>
              <label class="choice-row">
                <input type="radio" value="left" bind:group={draft.display.paragraph_align} onchange={previewDisplay} />
                Left (ragged right)
              </label>
              <label class="choice-row">
                <input type="radio" value="justify" bind:group={draft.display.paragraph_align} onchange={previewDisplay} />
                Justified (both edges)
              </label>
            </fieldset>

            <label class="choice-row">
              <input type="checkbox" bind:checked={draft.display.paragraph_indent} onchange={previewDisplay} />
              Indent the first line of each paragraph
            </label>
          </section>
        {:else if activeTab === "palette"}
          <PaletteEditor swatches={draft.palette} onChange={setPalette} />
        {:else if activeTab === "storage"}
          <label>
            Projects folder
            <ProjectsFolderPicker
              value={draft.default_projects_folder}
              onChange={(next) => {
                if (draft) draft.default_projects_folder = next;
              }}
              showClear
            />
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
        <button type="button" onclick={onCancel}>Cancel</button>
        <button class="primary" type="button" onclick={onSave}>Save</button>
      {/snippet}
  </Modal>
{/if}

<style>
  /* The tab strip uses the shared .tab-strip / .tab primitives in styles.css
     (#610). The panel restores the 14px grid gap the Modal gives its direct
     children (they're now nested inside this one wrapper), and pins a
     min-height so switching tabs doesn't resize the whole dialog (#613): the
     shorter tabs (Writing, Storage) leave whitespace instead of shrinking the
     frame, while a tall palette still grows into the Modal's own scroll. */
  .settings-panel {
    display: grid;
    grid-auto-rows: min-content;
    gap: 14px;
    min-height: 320px;
  }

  .stored-at {
    font-size: var(--fs-sm);
  }

  /* The app-wide AI policy section (#746). The radio group itself is the shared
     PolicyRadioGroup widget (#780); this just lays out its heading and blurb. */
  .app-policy {
    display: grid;
    grid-auto-rows: min-content;
    gap: 8px;
  }

  .app-policy h3 {
    margin: 0;
  }

  .health-check {
    display: grid;
    gap: 6px;
  }

  .health-check h3 {
    margin: 0;
    font-size: var(--fs-md);
    font-weight: 600;
  }

  .health-check p.muted {
    margin: 0;
    font-size: var(--fs-sm);
  }

  /* Mirrors the health readout that used to live in the Project pane. */
  .ai-health-result {
    margin: 4px 0 0;
    padding: 8px 10px;
    border-radius: 4px;
    font-size: var(--fs-md);
    line-height: 1.4;
  }

  .ai-health-result.ok {
    background: var(--accent-soft);
    color: var(--accent-deep);
    border: 1px solid var(--accent-soft2);
  }

  .ai-health-result.fail {
    background: var(--danger-soft);
    color: var(--danger);
    border: 1px solid var(--danger-border);
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
