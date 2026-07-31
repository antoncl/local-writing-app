<script lang="ts">
  import type {
    AncestorCandidate,
    ProjectChild,
  } from "@/lib/types";
  import InheritsFromList from "@/components/widgets/InheritsFromList.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import { formatCostEur } from "@/lib/utils/money";
  import { declarationRows } from "@/lib/utils/projectChain";

  export let isProjectOpen: boolean;
  export let projectTitle: string;
  export let projectCostTotal: number | null;
  export let projectCostBreakdown: { id: string; title: string; cost_usd: number }[];
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

  // Two-way bound: App resets projectCostExpanded on project switch, so it binds
  // down and back up.
  export let projectCostExpanded: boolean;

  // Actions — App owns the side effects (API calls). All moved out: Validate +
  // its result panel to the project window as a modal (#417), alongside the
  // AI-policy control; Chats/Prompts/Mutations to the app menu, Health Check to
  // the Settings AI tab (#629); loose-scene import to its own "Import
  // documents…" surface (#635). What's left here is read-only project info plus
  // the inheritance roster, all bound for the breadcrumb before the pane goes.
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
    <!-- The filesystem path moved to the project node's editor window as a
         read-only `path` computed field (#417 slice 3) — off the pane so it
         survives the pane's removal. Title + cost stay here until slice 6. -->
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
    project is built on, then what is built inside it. The AI access policy that
    used to share this block (#629) moved to the project window as a modal (#417),
    so the section is now just the declarations — and renders only when there are
    ancestors to declare, rather than always carrying an AI fieldset.
  -->
  {#if inheritRows.length > 0}
    <section class="project-inheritance" aria-label="Inheritance">
      <h3>Inheritance</h3>
      <div class="inherit-block" role="group" aria-labelledby="project-inherits-label">
        <span class="field-label" id="project-inherits-label">Inherits from</span>
        <InheritsFromList rows={inheritRows} busy={inheritSaving} onToggle={onToggleInherit} />
      </div>
    </section>
  {/if}

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

<style>
  /* Co-located from styles.css (#14): single-owner Project styles. `.muted` is
     also used here but stays global (shared utility). */
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

  /* Sibling sections of the pane, not nested treatments. The rows inside are
     plain NodeRows, so they carry the canonical card chrome and need nothing
     here. */
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

</style>
