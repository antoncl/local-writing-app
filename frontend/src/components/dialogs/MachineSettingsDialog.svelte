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
    UpdateCheck,
  } from "@/lib/types";
  import type { AIPolicyDraft } from "@/lib/stores/aiSettings.svelte";
  import { api } from "@/lib/api";
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

  // The running app version + build stamp (ADR-0072 §6). Fetched once on first
  // open — a static app constant, unrelated to the editable draft, so it isn't
  // threaded through the parent's settings load. `build` is the frozen commit
  // (null in a source run); the Updates tab shows it, the footer shows version.
  let appVersion = $state<string | null>(null);
  let appBuild = $state<string | null>(null);
  $effect(() => {
    if (open && appVersion === null) {
      api
        .getVersion()
        .then((v) => {
          appVersion = v.version;
          appBuild = v.build;
        })
        .catch(() => {});
    }
  });

  // The update check (ADR-0072 S6). On demand — never on open — so the dialog
  // makes no network call the user didn't ask for. The check runs against the
  // *saved* channel (the backend reads config.yaml), so a switched-but-unsaved
  // channel prompts a Save first (see the tab). `checkForUpdate` returns
  // `reachable: false` for offline rather than throwing; a genuine failure
  // (a 500) is the only catch path.
  let updateChecking = $state(false);
  let updateResult = $state<UpdateCheck | null>(null);
  let updateError = $state(false);
  async function runUpdateCheck() {
    if (updateChecking || channelDirty) return;
    updateChecking = true;
    updateResult = null;
    updateError = false;
    try {
      const result = await api.checkForUpdate();
      // A channel switch during the request makes this verdict stale — drop it
      // rather than show a saved-channel result under a "Save to check" nudge.
      if (!channelDirty) updateResult = result;
    } catch {
      if (!channelDirty) updateError = true;
    } finally {
      updateChecking = false;
    }
  }
  // The saved channel the last/next check runs against. A draft edit that
  // diverges from it makes the readout stale, so we clear it and nudge a Save.
  const savedChannel = $derived(settings?.update_channel ?? "stable");
  const channelDirty = $derived(!!draft && draft.update_channel !== savedChannel);
  $effect(() => {
    // Reading channelDirty registers the dep; clear a now-stale result.
    if (channelDirty) updateResult = null;
  });
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

  // Ollama host reachability check (#1380) — model-less, so it answers the
  // firewall/connectivity question even on a box with no local Ollama. Tests the
  // value currently typed (not the saved one) so a user can iterate before
  // saving; the readout is cleared when the host is edited so it never goes stale.
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
  type SettingsTab = "ai" | "writing" | "palette" | "storage" | "updates";
  const TABS: { key: SettingsTab; label: string }[] = [
    { key: "ai", label: "AI" },
    { key: "writing", label: "Writing" },
    { key: "palette", label: "Palette" },
    { key: "storage", label: "Storage" },
    { key: "updates", label: "Updates" },
  ];
  let activeTab = $state<SettingsTab>("ai");
  // Land on the first tab whenever the dialog reopens, never a stale one, and
  // drop any update-check readout so a reopen never shows a stale verdict.
  $effect(() => {
    if (!open) {
      activeTab = "ai";
      updateResult = null;
      updateError = false;
    }
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
            {#if policyDirty}
              <!--
                The Apply is deliberately separate from the batched Save (widening
                AI access must never ride a stray Save). That safety is easy to
                miss, though, so once the choice differs from the saved policy we
                say plainly that Save won't carry it (#1382).
              -->
              <p class="policy-unapplied" role="status">
                Not applied yet — press <strong>Apply</strong>. Saving other settings won't change AI access.
              </p>
            {/if}
          </section>

          <p class="muted">Your providers. A cloud key is masked on read and stays configured until you remove it; Ollama is a local host you can edit and test. Edit a provider from its chip.</p>

          <!--
            One provider chooser for every provider (#1417). Ollama is just another
            provider here — a URL credential with a reachability test — edited from
            its chip like the cloud keys, not a separate block. `editable` gives
            secrets rotate/remove; onSaveKey mutates the batched draft (Save
            persists), and onTestReachability probes the host the chip form has
            typed, so a user still iterates before saving (#1380).
          -->
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
            onTestReachability={(_id, value) => api.checkOllamaHost(value)}
          />

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
        {:else if activeTab === "updates"}
          <section class="updates-surface">
            <h3>Updates</h3>
            <p class="muted">
              This app checks GitHub for new releases on the channel you choose. Checking is manual —
              nothing is ever downloaded or installed on its own. When something newer exists, you get
              a link to its release page.
            </p>

            <fieldset class="channel-group">
              <legend>Channel</legend>
              <label class="choice-row">
                <input type="radio" value="stable" bind:group={draft.update_channel} />
                <span class="choice-text">
                  Stable
                  <small class="muted">Tagged releases. The recommended channel.</small>
                </span>
              </label>
              <label class="choice-row">
                <input type="radio" value="nightly" bind:group={draft.update_channel} />
                <span class="choice-text">
                  Bleeding edge
                  <small class="muted">The latest build from the main branch — newer, less tested.</small>
                </span>
              </label>
            </fieldset>

            <div class="version-lines muted">
              <span>Version {appVersion ?? "…"}</span>
              {#if appBuild}<span>Build <code>{appBuild.slice(0, 12)}</code></span>{/if}
            </div>

            <div class="button-row">
              <button
                type="button"
                disabled={updateChecking || channelDirty}
                title={channelDirty
                  ? "Save to check on the selected channel"
                  : "Check GitHub for a newer release"}
                onclick={runUpdateCheck}
              >{updateChecking ? "Checking…" : "Check for updates"}</button>
            </div>
            {#if channelDirty}
              <small class="muted">
                Save to check on the
                <strong>{draft.update_channel === "nightly" ? "Bleeding edge" : "Stable"}</strong>
                channel.
              </small>
            {/if}

            {#if updateError}
              <p class="update-result fail">Couldn't check for updates. Try again.</p>
            {:else if updateResult}
              {#if !updateResult.reachable}
                <p class="update-result info">
                  Couldn't reach GitHub{updateResult.detail ? ` — ${updateResult.detail}` : ""}. You may be offline.
                </p>
              {:else if updateResult.update_available}
                <p class="update-result ok">
                  A newer {updateResult.channel === "nightly" ? "build" : "version"} is available{updateResult.latest
                    ? `: ${updateResult.latest}`
                    : ""}.
                  {#if updateResult.latest_url}
                    <a href={updateResult.latest_url} target="_blank" rel="noopener noreferrer">Open the release page ↗</a>
                  {/if}
                </p>
              {:else if updateResult.detail}
                <p class="update-result info">{updateResult.detail}.</p>
              {:else}
                <p class="update-result ok">You're on the latest {updateResult.channel === "nightly" ? "build" : "version"}.</p>
              {/if}
            {/if}
          </section>
        {/if}
      </div>

      {#if policyDirty && activeTab !== "ai"}
        <!--
          Same reminder as the AI tab's inline hint, surfaced from any other tab
          so an unapplied AI-access change is impossible to miss on the way to
          Save (#1382). Suppressed on the AI tab itself, where the inline hint by
          the Apply button already says it.
        -->
        <p class="policy-unapplied" role="status">
          AI access change not applied — press <strong>Apply</strong> on the AI tab.
        </p>
      {/if}
      {#if appVersion}
        <p class="muted app-version">Version {appVersion}</p>
      {/if}
      <p class="muted stored-at">Stored locally at: <code>{settings?.config_path}</code></p>
      <p class="muted stored-at">Logs: <code>{settings?.config_dir}</code> (app.log, errors.log)</p>

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

  .app-version {
    font-size: var(--fs-sm);
    margin-bottom: 0;
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

  /* The unapplied-AI-access reminder (#1382): the amber --warn role — visible
     without alarming, matching the "quiet writing desk" restraint. */
  .policy-unapplied {
    margin: 0;
    color: var(--warn);
    font-size: var(--fs-sm);
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

  /* Updates tab (ADR-0072 S7). Mirrors .writing-surface: a bordered card with a
     heading, the channel radios, the version/build lines, and the check readout. */
  .updates-surface {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: 0;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
  }

  .updates-surface h3 {
    margin: 0;
    font-size: var(--fs-md);
    font-weight: 600;
  }

  .updates-surface p.muted {
    margin: 0;
    font-size: var(--fs-sm);
  }

  .channel-group {
    margin: 0;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    display: grid;
    gap: 8px;
  }

  .channel-group legend {
    padding: 0 4px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  /* The radios sit top-aligned against a two-line label (name + hint). */
  .channel-group .choice-row {
    align-items: flex-start;
  }

  .choice-text {
    display: grid;
    gap: 2px;
  }

  .choice-text small {
    font-size: var(--fs-sm);
  }

  .version-lines {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 16px;
    font-size: var(--fs-sm);
  }

  .update-result {
    margin: 0;
    padding: 8px 10px;
    border-radius: 4px;
    font-size: var(--fs-md);
    line-height: 1.4;
  }

  .update-result.ok {
    background: var(--accent-soft);
    color: var(--accent-deep);
    border: 1px solid var(--accent-soft2);
  }

  .update-result.fail {
    background: var(--danger-soft);
    color: var(--danger);
    border: 1px solid var(--danger-border);
  }

  .update-result.info {
    background: var(--inset);
    color: var(--text-2);
    border: 1px solid var(--border);
  }

  .update-result a {
    color: inherit;
    font-weight: 600;
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
