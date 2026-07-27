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
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import { createWizard as wizard } from "@/lib/stores/createWizard.svelte";
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
                <NodeList isEmpty={false}>
                  {#each wizard.inheritRows as row (row.path)}
                    <!--
                      Mirrors the post-hoc declaration editor (Project.svelte):
                      the checkbox IS the gesture, so `clickable={false}`; a
                      disabled (non-toggleable) row is the organisational folder
                      the walk crossed, shown so the list has no unexplained gap.
                      Unlike that editor there is no save round-trip — the toggle
                      updates local state and the derived rows re-render
                      synchronously — so no revert dance and no in-flight disable.
                    -->
                    <NodeRow title={row.label} detail={row.detail} clickable={false}>
                      {#snippet leading()}
                        <input
                          type="checkbox"
                          class="wizard-inherit-check"
                          checked={row.checked}
                          disabled={!row.toggleable}
                          aria-label={`Inherit from ${row.label}`}
                          on:change={() => wizard.toggleInherit(row.path)}
                        />
                      {/snippet}
                    </NodeRow>
                  {/each}
                </NodeList>
              {:else}
                <p class="muted">
                  Nothing to inherit from here — this project stands alone.
                </p>
              {/if}
            </section>
          {/if}
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

  /* Small control in a flex row — styles.css sets `input { width: 100% }`, which
     would otherwise make the checkbox eat the row (the #426/#311 trap). */
  .wizard-inherit-check {
    width: auto;
  }

  /* Root-save failure feedback, shown in-step because App's error toast sits
     behind the modal. */
  .wizard-error {
    margin: 0;
    color: var(--danger);
    font-size: var(--fs-sm);
  }
</style>
