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
  import ProjectsFolderPicker from "@/components/widgets/ProjectsFolderPicker.svelte";
  import InheritsFromList from "@/components/widgets/InheritsFromList.svelte";
  import AiPolicySlider from "@/components/widgets/AiPolicySlider.svelte";
  import ProviderTierPicker from "@/components/widgets/ProviderTierPicker.svelte";
  import ProviderSubscriptions from "@/components/widgets/ProviderSubscriptions.svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";
  import { createWizard as wizard } from "@/lib/stores/createWizard.svelte";
  import { assistantEntriesStore, isAssistantListed } from "@/lib/stores/assistants";
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
            <ProjectsFolderPicker
              value={wizard.rootFolderDraft}
              onChange={(next) => {
                wizard.rootFolderDraft = next;
                wizard.rootError = "";
              }}
              startPath={wizard.getStartPath()}
              pickerTitle="Choose Projects Folder"
            />
          </label>
          {#if wizard.rootError}
            <!-- A div, not a <p>: Modal's `:global(p)` color rule would otherwise
                 out-specify this and paint the error muted grey instead of red. -->
            <div class="wizard-error" role="alert">{wizard.rootError}</div>
          {/if}
        {:else if wizard.currentStep.id === "location"}
          <label>
            Project name
            <input
              type="text"
              data-testid="wizard-project-name"
              bind:value={wizard.title}
              placeholder="The name of your project"
            />
          </label>

          <label>
            Location
            <div class="path-picker-row">
              <input
                type="text"
                data-testid="wizard-project-folder"
                bind:value={wizard.pickedFolder}
                placeholder={wizard.defaultProjectsFolder || "C:\\path\\to\\writing"}
                on:change={() => wizard.reloadCandidates()}
              />
              <button type="button" on:click={() => wizard.openPicker()}>Browse…</button>
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
                <!--
                  The shared provider surface (ADR-0047 slice 2 / #616). Add-only
                  here — `editable` is left false, so first-run setup gets chips +
                  "+ Add provider" but no rotate/remove. It writes each key
                  immediately (unlike Settings' batched draft), so onSaveKey goes
                  through the busy-guarded controller path.
                -->
                <ProviderSubscriptions
                  providers={wizard.machineProviders}
                  defaultProviderId={wizard.defaultProviderId}
                  busy={wizard.aiBusy}
                  onSaveKey={(field, value) => wizard.saveProviderKey(field, value)}
                />
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
                <div class="inline-form">
                  <label>
                    Name
                    <input type="text" bind:value={wizard.hireTitle} placeholder="Drafting assistant" />
                  </label>
                  <ProviderTierPicker
                    policy={wizard.pickerPolicy}
                    onChange={(detail) =>
                      wizard.setHireProvider(detail.provider, detail.tier, detail.model)}
                  />
                  <div class="inline-form-actions">
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
                <button type="button" class="inline-add-btn" on:click={() => wizard.beginHire()}
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
              onChange={(next) => wizard.setDescription(next)}
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

  /* The inline hire draft + "+ Hire" launcher use the shared .inline-form* /
     .inline-add-btn primitives in styles.css (#619). */

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
