<script lang="ts">
  import type {
    AIPolicy,
    AncestorCandidate,
    ProjectChild,
    ProjectValidation,
  } from "@/lib/types";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import { formatCostEur } from "@/lib/utils/money";
  import { declarationRows } from "@/lib/utils/projectChain";

  export let isProjectOpen: boolean;
  export let projectTitle: string;
  export let projectPath: string;
  export let projectCostTotal: number | null;
  export let projectCostBreakdown: { id: string; title: string; cost_usd: number }[];
  export let validation: ProjectValidation | null;
  // Project folders directly inside this one (#310). Direct children only —
  // a level offers the places you can open *from here*, not the whole shelf.
  // Empty for a leaf, which is the only thing that distinguishes one: there
  // is no level type to branch on, and depth is not consulted anywhere.
  export let projectChildren: ProjectChild[] = [];
  // The WHOLE ancestor enumeration (#309), not the declared subset — the
  // editor's job is to offer the rows the breadcrumb filters out. Flags, not
  // filtering, is why one payload serves both consumers.
  export let ancestors: AncestorCandidate[] = [];
  // Applied on the click, not on a Save button. There is nothing to compose:
  // one tick is one complete intent, and a draft would need a dirty model to
  // buy nothing. It is not a permission control, so the fail-closed rule that
  // keeps AI access behind an explicit save does not reach here.
  export let onToggleInherit: (path: string) => void;
  // True for the duration of a declaration save, including the project-data
  // reload it triggers. See the checkbox below for why it has to disable them.
  export let inheritSaving: boolean = false;

  $: inheritRows = declarationRows(ancestors);

  // Two-way bound: App is the source of truth. aiPolicy is set on project load
  // and read back when saving AI settings; projectCostExpanded is bound because
  // App resets it on project switch. Both stay there and bind down.
  //
  // "inherit" is the draft-only value the pane can hold that the stored policy
  // cannot (#471): the project states no policy of its own and defers to its
  // parent. Saving it clears the key; it is never a resolved value.
  export let aiPolicy: AIPolicy | "inherit";
  export let projectCostExpanded: boolean;

  // Actions — App owns the side effects (API calls). Several moved out: Validate
  // to the pane header, Chats/Prompts/Mutations to the app menu, Health Check to
  // the Settings AI tab (#629); loose-scene import to its own "Import documents…"
  // surface (#635). This pane keeps only the AI-policy apply and TODO repair.
  export let onSaveAISettings: () => void;
  export let onRepair: () => void;
  // Opening a child is a resolution-scope change, i.e. a unit boundary
  // (ADR-0045) — App routes it through the same open path as the switcher
  // rather than mutating anything in place.
  export let onOpenChild: (path: string) => void;
</script>

{#if !isProjectOpen}
  <p class="muted project-empty-hint">
    No project open. Pick one from the switcher above — recents, browse, or create new.
  </p>
{:else}
  <div class="project-identity">
    <strong class="project-identity-title">{projectTitle}</strong>
    <code class="project-identity-path" title={projectPath}>{projectPath}</code>
    {#if projectCostTotal != null && projectCostTotal > 0}
      <button
        type="button"
        class="project-cost-chip"
        title="AI cost across all chats in this project. Click to break down by chat."
        on:click={() => (projectCostExpanded = !projectCostExpanded)}
      >
        {formatCostEur(projectCostTotal)} this project
        <span class="project-cost-caret" aria-hidden="true">{projectCostExpanded ? "▾" : "▸"}</span>
      </button>
      {#if projectCostExpanded}
        <ul class="project-cost-breakdown">
          {#each projectCostBreakdown.filter((r) => r.cost_usd > 0) as row (row.id)}
            <li>
              <span class="project-cost-breakdown-title">{row.title}</span>
              <span class="project-cost-breakdown-value">{formatCostEur(row.cost_usd)}</span>
            </li>
          {/each}
          {#if projectCostBreakdown.filter((r) => r.cost_usd > 0).length === 0}
            <li class="muted">No chats with cost yet.</li>
          {/if}
        </ul>
      {/if}
    {/if}
  </div>

  <!--
    The inheritance declaration (#426). Rendered only when the walk found
    something: a project directly under the machine root, or one outside it,
    has an empty enumeration and there is nothing to choose from. Same rule as
    the child roster below — an always-present empty section is noise on every
    flat project, and #427 owns the affordance for the empty case.

    Placed above "Contains" so the pane reads the way the chain does: what this
    project is built on, then what is built inside it.
  -->
  <!--
    Inheritance block (#629): the ancestor declarations and the AI access
    policy sit together — both are per-project, inherit-flavoured settings (the
    policy's headline option is literally "Inherit"). Rendered for any open
    project; the declaration list only when the walk found ancestors to choose.
  -->
  <section class="project-inheritance" aria-label="Inheritance and AI access">
    <h3>Inheritance</h3>
    {#if inheritRows.length > 0}
      <div class="inherit-block" role="group" aria-labelledby="project-inherits-label">
        <span class="field-label" id="project-inherits-label">Inherits from</span>
        <NodeList isEmpty={false}>
        {#each inheritRows as row (row.path)}
          <!--
            `clickable={false}`: the checkbox IS the gesture, so the title must
            not also be a button competing for the same click. A disabled row
            is still shown — it is the organisational folder the walk crossed,
            and hiding it would leave a gap that reads as a defect.

            No `active`: that state means "open in a pane", and the checkbox is
            already the canonical indicator of what is declared. Two treatments
            for one fact is the density smell the widget taxonomy codifies
            against, and the stale row says its piece in `detail` rather than in
            a colour nothing else on this pane uses.
          -->
          <NodeRow title={row.label} detail={row.detail} clickable={false}>
            {#snippet leading()}
              <!--
                The box shows the DECLARATION, never the click. `on:change` puts
                it straight back to the model value and lets the round trip move
                it, because a save can fail (a 422, a vanished folder) and the
                browser's own toggle would then leave a ticked box over an
                unchanged manifest — the one state this pane must never show.
                On success `ancestors` comes back changed and Svelte flips it.

                `disabled` while a save is in flight is the other half: each
                request is derived from the ancestors currently on screen, so a
                second click during the round trip would compute from the stale
                enumeration and silently undo the first tick.
              -->
              <input
                type="checkbox"
                class="project-inherit-check"
                checked={row.checked}
                disabled={!row.toggleable || inheritSaving}
                aria-label={`Inherit from ${row.label}`}
                on:change={(event) => {
                  event.currentTarget.checked = row.checked;
                  onToggleInherit(row.path);
                }}
              />
            {/snippet}
          </NodeRow>
        {/each}
        </NodeList>
      </div>
    {/if}

    <fieldset class="ai-policy">
      <legend>AI access</legend>
      <label title="Set no policy of your own — inherit it from an ancestor project, or default to Off (#471)">
        <input type="radio" bind:group={aiPolicy} value="inherit" /> Inherit
      </label>
      <label><input type="radio" bind:group={aiPolicy} value="off" /> Off</label>
      <label><input type="radio" bind:group={aiPolicy} value="local-only" /> Local only</label>
      <label><input type="radio" bind:group={aiPolicy} value="cloud-allowed" /> Cloud allowed</label>
    </fieldset>
    <div class="button-row">
      <button type="button" on:click={onSaveAISettings}>Save AI Settings</button>
    </div>
  </section>

  <!--
    The child roster (#310). Rendered only when there is something in it: a
    leaf has no children, and an always-present empty section would be noise on
    every book. That emptiness IS the only leaf/non-leaf distinction in the UI —
    no depth, no level type, nothing derived from the chain's shape.
  -->
  {#if projectChildren.length > 0}
    <section class="project-children" aria-label="Projects inside this one">
      <h3>Contains</h3>
      <NodeList isEmpty={false}>
        {#each projectChildren as child (child.path)}
          <!--
            `detail` is the folder name, and only when it differs from the
            title: a project keeps its folder name as its default title, so
            passing it unconditionally prints the same string twice on exactly
            the projects nobody has renamed yet.

            No `dataNodeId`: it exists so focus helpers can find a row by node
            id, and a filesystem path is not one. ViewNodeList interpolates that
            attribute straight into a `querySelector`, so putting a Windows path
            there is a hazard bought for nothing.
          -->
          <NodeRow
            title={child.title}
            detail={child.name === child.title ? null : child.name}
            ariaLabel={`Open ${child.title}`}
            onClick={() => onOpenChild(child.path)}
          />
        {/each}
      </NodeList>
    </section>
  {/if}
{/if}

{#if validation}
  <section class:invalid={!validation.valid} class="validation-panel" aria-label="Project validation result">
    <h3>{validation.valid ? "Project Looks Consistent" : "Project Issues Found"}</h3>
    {#if validation.migrations_applied.length > 0}
      <strong>Migrations Applied</strong>
      {#each validation.migrations_applied as migration}
        <p class="migration-applied">{migration}</p>
      {/each}
    {/if}
    {#if validation.errors.length > 0}
      <strong>Errors</strong>
      {#each validation.errors as validationError}
        <p>{validationError}</p>
      {/each}
    {/if}
    {#if validation.warnings.length > 0}
      <strong>Warnings</strong>
      {#each validation.warnings as validationWarning}
        <p>{validationWarning}</p>
      {/each}
    {/if}
    {#if validation.errors.length === 0 && validation.warnings.length === 0}
      <p>No structure, scene, or TODO synchronization issues found.</p>
    {/if}
    {#if validation.errors.length > 0 || validation.warnings.length > 0}
      <div class="validation-actions">
        <button type="button" on:click={onRepair}>Repair TODO Links</button>
      </div>
    {/if}
  </section>
{/if}

<style>
  /* Co-located from styles.css (#14): single-owner Project styles. `.muted` and
     `.button-row` are also used here but stay global (shared utilities). */
  .project-empty-hint {
    margin: 4px 0;
    font-size: var(--fs-md);
  }

  .project-identity {
    display: grid;
    gap: 6px;
    margin-bottom: 8px;
  }

  .project-identity-title {
    font-size: var(--fs-xl);
    color: var(--text);
  }

  .project-identity-path {
    font-size: var(--fs-xs);
    color: var(--text-3);
    background: var(--inset);
    border: 1px solid var(--divider);
    border-radius: 3px;
    padding: 2px 6px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--mono);
  }

  .project-cost-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 6px;
    padding: 2px 8px;
    font-size: var(--fs-xs);
    background: transparent;
    border: 1px solid var(--divider);
    border-radius: 10px;
    color: var(--text-2);
    cursor: pointer;
    font-variant-numeric: tabular-nums;
  }
  .project-cost-chip:hover {
    background: var(--inset);
  }
  .project-cost-caret {
    font-size: var(--fs-xs);
    opacity: 0.6;
  }
  .project-cost-breakdown {
    list-style: none;
    margin: 4px 0 0;
    padding: 4px 0;
    font-size: var(--fs-xs);
    border-top: 1px dashed var(--divider);
  }
  .project-cost-breakdown li {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    padding: 2px 8px;
  }
  .project-cost-breakdown-value {
    font-variant-numeric: tabular-nums;
    color: var(--text-3);
  }

  /* Same section rhythm as the AI block below — a sibling section of the
     pane, not a nested treatment. The rows inside are plain NodeRows, so
     they carry the canonical card chrome and need nothing here. */
  .project-inheritance,
  .project-children {
    display: grid;
    gap: 10px;
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
  }

  .project-inheritance h3,
  .project-children h3 {
    margin: 0;
    font-size: var(--fs-md);
    font-weight: 600;
    color: var(--text);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .inherit-block {
    display: grid;
    gap: 6px;
  }

  /* Sub-label for the ancestor declarations inside the Inheritance block. */
  .field-label {
    font-size: var(--fs-xs);
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  /* `width: auto` is load-bearing, not tidying: styles.css:401 sets
     `input, select { width: 100% }` for the app's form fields, and a checkbox
     in a flex row inherits it as its flex basis — the box ate the whole row
     and pushed the title off the right edge with zero width. `flex: none`
     alone does NOT fix it (basis `auto` reads the width property back); the
     width has to be overridden. Measured in the browser, not reasoned. */
  .project-inherit-check {
    flex: none;
    width: auto;
    margin: 0;
  }
  .project-inherit-check:disabled {
    opacity: 0.45;
  }

  .ai-policy {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 10px;
  }

  .ai-policy legend {
    font-size: var(--fs-sm);
    color: var(--text-2);
    padding: 0 4px;
  }

  .ai-policy label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--fs-md);
  }

  /* The global `input, select { width: 100% }` (styles.css) stretches a radio
     to fill its flex label, distorting these controls (#426 noted it here,
     unfiled). Resetting the width is what fixes it — `flex: none` does not, as
     the basis just reads the width property back. */
  .ai-policy label input[type="radio"] {
    width: auto;
  }

  .migration-applied {
    color: var(--accent-deep);
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }

  .validation-panel {
    display: grid;
    gap: 5px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
  }

  .validation-panel.invalid {
    border-color: var(--star-border);
    background: var(--star-soft);
  }

  .validation-panel strong {
    margin-top: 4px;
    color: var(--text-2);
    font-size: var(--fs-sm);
    text-transform: uppercase;
  }

  .validation-panel p {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-sm);
    line-height: 1.35;
  }

  .validation-actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 6px;
  }
</style>
