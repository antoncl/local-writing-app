<script lang="ts">
  // The create-project wizard (#318 slice 2 — design-doc §4/§5 steps 1–2). The
  // ONLY net-new UI in this slice: a multi-step stepper *inside* a dialog. It
  // composes the existing Modal (a dialog per design-language.md:296) and every
  // step body reuses existing widgets. Domain state lives in the createWizard
  // rune controller; this view is thin.
  //
  // Three rules the stepper fixes once (design-doc §4): a breadcrumb of step
  // names (a completed step navigates back), a Next gated on the step's
  // consistency, and a fixed-size frame that does not resize between steps.
  import Modal from "@/components/dialogs/Modal.svelte";
  import DirectoryPickerModal from "@/components/dialogs/DirectoryPickerModal.svelte";
  import InheritsFromList from "@/components/widgets/InheritsFromList.svelte";
  import AiPolicySlider from "@/components/widgets/AiPolicySlider.svelte";
  import ProviderTierPicker from "@/components/widgets/ProviderTierPicker.svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";
  import { createWizard as wizard } from "@/lib/stores/createWizard.svelte";
  import { assistantEntriesStore, isAssistantListed } from "@/lib/stores/assistants";
  import { cloudKeyPlaceholder } from "@/lib/utils/aiProviders";
  import { resetTargetLabel } from "@/lib/utils/projectReview";
  import { moveBefore } from "@/lib/utils/listOrder";
  import { get } from "svelte/store";

  // This component stays in LEGACY mode (on:/bind: directives). The wizard's
  // open/step state lives on the imported `createWizard` rune controller, and a
  // legacy `$:` reactive statement silently stops the template from tracking
  // reads of that external rune — `{#if wizard.open}` then never re-renders and
  // the dialog stays invisible (the documented Svelte-5 `$:` trap). So the
  // assistant roster is derived inline in the template ({@const} over the store
  // subscription) rather than via `$:`. During creation these are the
  // machine-level default assistants the new book inherits (#547).

  // Ephemeral drag-to-reorder state; the ordering maths is the pure moveBefore.
  let draggingId: string | null = null;
  function dropOnAssistant(targetId: string) {
    const ids = get(assistantEntriesStore).filter(isAssistantListed).map((entry) => entry.id);
    if (draggingId && draggingId !== targetId) {
      void wizard.reorderAssistants(moveBefore(ids, draggingId, targetId));
    }
    draggingId = null;
  }
</script>

{#if wizard.open}
  <!--
    Fixed frame: a definite height plus `grid-template-rows: auto 1fr auto`
    (overriding Modal's auto rows) so the header and footer stay put and only the
    step body flexes/scrolls. The frame never resizes between steps.
  -->
  <Modal
    title="New Project"
    label="Create project"
    frameClass="create-wizard-modal"
    frameStyle="--modal-width: 560px; height: 560px; max-height: calc(100vh - 48px); grid-template-rows: auto minmax(0, 1fr) auto;"
  >
    <div class="wizard">
      <nav class="wizard-steps" aria-label="Steps">
        {#each wizard.steps as step, index (step.id)}
          {#if index > 0}
            <span class="crumb-sep" aria-hidden="true">›</span>
          {/if}
          <!--
            Backward-only: a completed step (index < current) is an enabled
            button that navigates back; the active step and any future step are
            disabled, so forward motion happens only through the gated Next. The
            future steps still render, so the row does not reflow as steps pass.
          -->
          <button
            type="button"
            class="wizard-crumb"
            class:active={index === wizard.currentIndex}
            aria-current={index === wizard.currentIndex ? "step" : undefined}
            disabled={index >= wizard.currentIndex}
            on:click={() => wizard.goToStep(step.id)}
          >{step.label}</button>
        {/each}
      </nav>

      <div class="wizard-body">
        {#if wizard.currentStep.id === "root"}
          <p class="muted">
            Choose the one folder this app works within. New projects are created here, and a
            project inherits from the projects above it up to this folder.
          </p>
          <label>
            Projects folder
            <div class="path-picker-row">
              <input
                type="text"
                bind:value={wizard.rootFolderDraft}
                placeholder="C:\path\to\writing"
              />
              <button type="button" on:click={() => wizard.openPicker("root")}>Browse…</button>
            </div>
          </label>
          {#if wizard.rootError}
            <!-- A div, not a <p>: Modal's `:global(p)` color rule would otherwise
                 out-specify this and paint the error muted grey instead of red. -->
            <div class="wizard-error" role="alert">{wizard.rootError}</div>
          {/if}
        {:else if wizard.currentStep.id === "location"}
          <label>
            Project name
            <input type="text" bind:value={wizard.title} placeholder="Honor's First Command" />
          </label>

          <label>
            Location
            <div class="path-picker-row">
              <input
                type="text"
                bind:value={wizard.pickedFolder}
                placeholder={wizard.defaultProjectsFolder || "C:\\path\\to\\writing"}
                on:change={() => wizard.reloadCandidates()}
              />
              <button type="button" on:click={() => wizard.openPicker("location")}>Browse…</button>
            </div>
            <!--
              The location can be any folder — including one *inside* an existing
              project — which is what lets a new book declare a real ancestor
              chain. The wizard builds the project folder from the name below it.
            -->
            <small class="muted">
              Pick where the project lives. Browse into an existing project to create this one
              inside it.
            </small>
          </label>

          <p class="muted">
            Will be created at:
            <code>{wizard.title.trim() && wizard.pickedFolder ? wizard.resolvedRoot : "(name and location required)"}</code>
          </p>

          {#if wizard.pickedFolder}
            <section class="wizard-inherits" aria-label="Inherit from">
              <h3>Inherit from</h3>
              {#if wizard.candidatesLoading}
                <p class="muted">Reading ancestor folders…</p>
              {:else if wizard.inheritRows.length > 0}
                <InheritsFromList
                  rows={wizard.inheritRows}
                  onToggle={(path) => wizard.toggleInherit(path)}
                />
              {:else}
                <p class="muted">
                  Nothing to inherit from here — this project stands alone.
                </p>
              {/if}
            </section>
          {/if}
        {:else if wizard.currentStep.id === "ai"}
          <!--
            Gated from the top (design-doc §5 step 3): the policy slider leads,
            and only a concrete on-policy stated here unfolds the provider +
            assistant surface. Off shows nothing more; inheriting takes the
            ancestors' whole AI setup, so there is nothing to configure at this
            layer.
          -->
          <p class="muted">
            {#if wizard.canInheritPolicy}
              AI policy leads and gates the rest. Inherited from the projects above — pick a
              stop to set a policy for this project.
            {:else}
              AI policy leads and gates the rest. Choose how this project may use AI.
            {/if}
          </p>

          <AiPolicySlider
            value={wizard.aiSliderValue}
            canInherit={wizard.canInheritPolicy}
            onChange={(next) => wizard.setAiPolicy(next)}
          />

          {#if wizard.showProviderSurface}
            {@const listedAssistants = $assistantEntriesStore.filter(isAssistantListed)}
            <section class="ai-section" aria-label="Provider">
              {#if wizard.providerModeCloud}
                <h3>Your subscriptions</h3>
                {#if wizard.configuredProviders.length > 0}
                  <div class="provider-chips">
                    {#each wizard.configuredProviders as prov (prov.id)}
                      <span class="provider-chip" class:is-default={prov.id === wizard.defaultProviderId}
                        >{prov.label}</span
                      >
                    {/each}
                  </div>
                {:else}
                  <p class="muted">No cloud provider configured yet — add one to use cloud AI.</p>
                {/if}

                {#if wizard.addingProvider}
                  <div class="ai-add">
                    <label>
                      Provider
                      <select bind:value={wizard.providerDraftId}>
                        {#each wizard.addableProviders as prov (prov.id)}
                          <option value={prov.id}>{prov.label}</option>
                        {/each}
                      </select>
                    </label>
                    <label>
                      API key
                      <input
                        type="password"
                        autocomplete="off"
                        bind:value={wizard.providerDraftSecret}
                        placeholder={cloudKeyPlaceholder(wizard.providerDraftId)}
                      />
                    </label>
                    <div class="ai-actions">
                      <button type="button" on:click={() => wizard.cancelAddProvider()}>Cancel</button>
                      <button
                        type="button"
                        class="primary"
                        disabled={wizard.aiBusy || !wizard.providerDraftSecret.trim()}
                        on:click={() => wizard.saveProvider()}>Save</button
                      >
                    </div>
                  </div>
                {:else if wizard.addableProviders.length > 0}
                  <button
                    type="button"
                    class="ai-linkbtn"
                    on:click={() => wizard.beginAddProvider(wizard.addableProviders[0].id)}
                    >+ Add provider</button
                  >
                {/if}
              {:else}
                <h3>Local model</h3>
                <div class="arow">
                  <span>Ollama</span><span class="arow-detail">{wizard.ollamaHost}</span>
                </div>
                <p class="muted">Change the Ollama host in Machine settings.</p>
              {/if}
            </section>

            <section class="ai-section" aria-label="Assistants">
              <h3>Assistants for this book</h3>
              {#if listedAssistants.length > 0}
                <ul class="assistant-rows">
                  {#each listedAssistants as entry, index (entry.id)}
                    <li
                      class="assistant-row"
                      class:dragging={draggingId === entry.id}
                      draggable="true"
                      on:dragstart={(event) => {
                        draggingId = entry.id;
                        // Firefox only starts a native drag once dataTransfer is
                        // set; without this the whole reorder is a no-op there.
                        event.dataTransfer?.setData("text/plain", entry.id);
                      }}
                      on:dragover={(event) => event.preventDefault()}
                      on:drop={(event) => {
                        event.preventDefault();
                        dropOnAssistant(entry.id);
                      }}
                      on:dragend={() => (draggingId = null)}
                    >
                      <span class="grip" aria-hidden="true"><i class="ti ti-grip-vertical"></i></span>
                      <span class="assistant-name">{entry.title}</span>
                      {#if index === 0}<span class="assistant-default">default</span>{/if}
                      <button
                        type="button"
                        class="assistant-unlist"
                        title="Remove from this project's roster"
                        disabled={wizard.aiBusy}
                        on:click={() => wizard.unlistAssistant(entry.id)}>Un-list</button
                      >
                    </li>
                  {/each}
                </ul>
              {:else}
                <p class="muted">No assistants yet — hire one below.</p>
              {/if}

              {#if wizard.hiring}
                <div class="ai-add">
                  <label>
                    Name
                    <input type="text" bind:value={wizard.hireTitle} placeholder="Drafting assistant" />
                  </label>
                  <ProviderTierPicker
                    on:change={(event) =>
                      wizard.setHireProvider(event.detail.provider, event.detail.tier, event.detail.model)}
                  />
                  <div class="ai-actions">
                    <button type="button" on:click={() => wizard.cancelHire()}>Cancel</button>
                    <!-- Gate on a chosen provider so a stray Hire can't create an
                         assistant pointed at a provider you never configured. -->
                    <button
                      type="button"
                      class="primary"
                      disabled={wizard.aiBusy || !wizard.hireProvider}
                      on:click={() => wizard.submitHire()}>Hire</button
                    >
                  </div>
                </div>
              {:else}
                <button type="button" class="ai-linkbtn" on:click={() => wizard.beginHire()}
                  >+ Hire an assistant…</button
                >
              {/if}
            </section>
          {:else if wizard.aiSliderValue === "off"}
            <p class="muted">AI is off — no provider or assistants. Nothing more to set.</p>
          {/if}
        {:else if wizard.currentStep.id === "review"}
          <!--
            The review pane (design-doc §5 step 4 / §6): the project node's
            authored fields, resolved over the ticked chain before the project
            exists. Everything is shown filled-in; a value inherited from an
            ancestor reads muted and names its source, and setting one authors it
            here (a live override with a Reset-to-source control). Row logic is
            the pure, tested projectReviewRows; the widgets are the same
            FieldValueEditor the rail uses.
          -->
          <p class="muted">
            Review this project's settings. Values inherited from the projects above are shown
            filled-in — change any to set it for this project.
          </p>
          {#if wizard.reviewLoading}
            <p class="muted">Resolving settings…</p>
          {:else if wizard.reviewSchema}
            <div class="review-fields">
              {#each wizard.reviewRows as row (row.fieldId)}
                <div class="review-field" class:is-local={row.provenance === "local"}>
                  <div class="review-field-head">
                    <span class="review-label">{row.label}</span>
                    {#if row.provenance === "inherited"}
                      <span class="review-source" title={`Inherited from ${row.sourceLabel}`}
                        >Inherited from {row.sourceLabel}</span
                      >
                    {:else if row.clearable}
                      <!-- The interactive ti-versions mark (§8), naming the
                           source it would defer to rather than the word
                           "inherit". -->
                      <button
                        type="button"
                        class="review-reset"
                        title={`Reset to ${resetTargetLabel(row)}`}
                        on:click={() => wizard.resetNodeField(row.fieldId)}
                      >
                        <i class="ti ti-versions" aria-hidden="true"></i>
                        Reset to {resetTargetLabel(row)}
                      </button>
                    {/if}
                  </div>
                  <FieldValueEditor
                    field={row.field}
                    value={row.value}
                    ariaLabel={row.label}
                    documentKind="project"
                    entryType="project:project"
                    onChange={(value) => wizard.setNodeField(row.fieldId, value)}
                  />
                </div>
              {/each}
            </div>
          {:else}
            <div class="wizard-error" role="alert">
              Couldn't resolve this project's settings — go back and check the location.
            </div>
          {/if}
        {:else if wizard.currentStep.id === "describe"}
          <!--
            Description (design-doc §5 step 5): a blurb into the project node
            body, edited with the app's long_text editor so it matches every
            other long-text surface. Skippable — Create is enabled regardless.
          -->
          <p class="muted">
            Add a short description for this project. You can skip this and add it later.
          </p>
          <div class="describe-editor">
            <MetadataLongTextEditor
              ariaLabel="Description"
              value={wizard.description}
              on:change={(event) => wizard.setDescription(event.detail.value)}
            />
          </div>
        {/if}
      </div>
    </div>

    {#snippet actions()}
      <button type="button" on:click={() => wizard.close()}>Cancel</button>
      {#if wizard.currentIndex > 0}
        <button type="button" on:click={() => wizard.back()}>Back</button>
      {/if}
      {#if wizard.isFinalStep}
        <button
          type="button"
          class="primary"
          disabled={!wizard.canAdvance}
          on:click={() => wizard.submit()}
        >Create</button>
      {:else}
        <button
          type="button"
          class="primary"
          disabled={!wizard.canAdvance}
          on:click={() => wizard.next()}
        >Next</button>
      {/if}
    {/snippet}
  </Modal>

  <!--
    The wizard owns its OWN picker instance (separate from App's shared
    open-project one). DirectoryPickerModal keeps its own high-z backdrop, so it
    layers correctly over this dialog's frame.
  -->
  <DirectoryPickerModal
    open={wizard.pickerOpen}
    initialPath={wizard.pickerInitialPath}
    title={wizard.pickerTitle}
    selectLabel={wizard.pickerSelectLabel}
    onClose={() => wizard.closePicker()}
    onSelect={(path) => wizard.onPickFolder(path)}
  />
{/if}

<style>
  /* Fills the fixed frame's middle grid row; the body is the only scroller. */
  .wizard {
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-height: 0;
    height: 100%;
  }

  .wizard-steps {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
  }

  /* Same crumb lexicon as ProjectBreadcrumb: quiet by default, `›` between. */
  .wizard-crumb {
    padding: 4px 8px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-md);
    cursor: pointer;
  }

  .wizard-crumb:disabled {
    cursor: default;
  }

  .wizard-crumb:not(:disabled):hover {
    background: var(--panel);
    color: var(--text);
  }

  /* The active step is the one live crumb — leading with the accent the app uses
     for the current selection elsewhere, not a box that reads as clickable. */
  .wizard-crumb.active {
    color: var(--text);
    font-weight: 600;
  }

  .crumb-sep {
    color: var(--text-3);
    font-size: var(--fs-sm);
    user-select: none;
  }

  /* The step body absorbs the height difference between steps and scrolls its
     own overflow (a long candidate list) rather than growing the frame. */
  .wizard-body {
    display: flex;
    flex-direction: column;
    gap: 14px;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }

  .wizard-body label {
    display: grid;
    gap: 6px;
  }

  .wizard-inherits {
    display: grid;
    gap: 8px;
  }

  .wizard-inherits h3 {
    margin: 0;
    font-size: var(--fs-md);
    color: var(--text-2);
  }

  /* Root-save failure feedback, shown in-step because App's error toast sits
     behind the modal. */
  .wizard-error {
    margin: 0;
    color: var(--danger);
    font-size: var(--fs-sm);
  }

  /* ---- Review step (book settings / overrides) ---- */
  .review-fields {
    display: grid;
    gap: 12px;
  }

  .review-field {
    display: grid;
    gap: 4px;
    padding-left: 10px;
    /* A quiet left rail: transparent by default, the star axis when the author
       has overridden the row (the "live" treatment of §8). */
    border-left: 2px solid transparent;
  }

  .review-field.is-local {
    border-left-color: var(--star);
  }

  .review-field-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }

  .review-label {
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  /* Inherited rows name their source quietly — the wizard's job is to make the
     inheritance legible, so this is inline rather than tooltip-only. */
  .review-source {
    margin-left: auto;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  /* The interactive ti-versions mark + "Reset to <source>" (§8), on the star
     axis, zero-chrome until hovered. */
  .review-reset {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 1px solid transparent;
    background: transparent;
    color: var(--star);
    font-size: var(--fs-xs);
    padding: 2px 6px;
    border-radius: 6px;
    cursor: pointer;
  }
  .review-reset:hover {
    border-color: var(--border);
    background: var(--surface);
  }

  /* Give the long-text description room to breathe within the fixed frame. */
  .describe-editor {
    min-height: 180px;
  }

  /* ---- AI step ---- */
  /* Each unfolded block (provider, assistants) sits under a hairline, echoing
     the mockup's provider-block separator. */
  .ai-section {
    display: grid;
    gap: 8px;
    padding-top: 12px;
    border-top: 1px solid var(--divider);
  }

  .ai-section h3 {
    margin: 0;
    font-size: var(--fs-sm);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }

  /* A read-only detail row (the Local/Ollama host). */
  .arow {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    font-size: var(--fs-sm);
  }
  .arow-detail {
    margin-left: auto;
    color: var(--text-3);
    font-size: var(--fs-xs);
  }

  .provider-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .provider-chip {
    padding: 2px 10px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-sm);
  }

  /* The machine default provider reads as the live one. */
  .provider-chip.is-default {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent-emphasis);
    font-weight: 600;
  }

  /* Inline add-provider / hire drafts. */
  .ai-add {
    display: grid;
    gap: 8px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
  }

  .ai-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }

  /* Dashed link-style action, matching the mockup's "+ Add" / "+ Hire". */
  .ai-linkbtn {
    justify-self: start;
    border: 1px dashed var(--border-strong);
    background: transparent;
    color: var(--accent-emphasis);
    font-size: var(--fs-sm);
    padding: 4px 12px;
    border-radius: 6px;
    cursor: pointer;
  }
  .ai-linkbtn:hover {
    background: var(--surface);
  }

  .assistant-rows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 4px;
  }

  .assistant-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    font-size: var(--fs-sm);
  }
  .assistant-row.dragging {
    opacity: 0.5;
  }

  .grip {
    color: var(--text-3);
    cursor: grab;
  }

  .assistant-name {
    color: var(--text);
  }

  .assistant-default {
    font-size: var(--fs-xs);
    color: var(--accent-emphasis);
  }

  /* Push the un-list control to the trailing edge. */
  .assistant-unlist {
    margin-left: auto;
    border: 1px solid transparent;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-xs);
    padding: 2px 6px;
    border-radius: 6px;
    cursor: pointer;
  }
  .assistant-unlist:hover:not(:disabled) {
    border-color: var(--border);
    color: var(--text-2);
  }
</style>
