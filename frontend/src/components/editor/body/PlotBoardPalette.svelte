<script lang="ts">
  import type {
    PlotNode,
    PlotNodeSummary,
    PlotPointClaim,
    PlotTemplateInstancePoint,
  } from "@/lib/types";

  type TemplatePointRow = {
    instance: PlotNode;
    point: PlotTemplateInstancePoint;
    status: "missing" | "partial" | "used";
    claim: PlotPointClaim | null;
  };

  type RenameAction = (node: HTMLInputElement) => { destroy: () => void };

  interface Props {
    addTemplateInstance: () => void;
    availableTemplates: PlotNodeSummary[];
    cancelRenameTemplateInstance: () => void;
    clearDragOver: () => void;
    commitTemplateInstanceRename: (instance: PlotNode) => Promise<void>;
    deleteTemplateInstance: (instance: PlotNode) => Promise<void>;
    dragPalettePoint: (row: TemplatePointRow, event: DragEvent) => void;
    focusRenameInput: RenameAction;
    handleTemplateRenameKeydown: (instance: PlotNode, event: KeyboardEvent) => void;
    instanceDisplayTitle: (instance: PlotNode) => string;
    paletteRows: TemplatePointRow[];
    pointKey: (instanceId: string, pointId: string) => string;
    rawInstanceTitle: (instance: Pick<PlotNode, "id" | "title" | "template_instance">) => string;
    renamingTemplateInstanceId: string | null;
    renamingTemplateInstanceTitle: string;
    savingMessage: string;
    selectedPalettePoint: string | null;
    selectPalettePoint: (row: TemplatePointRow) => void;
    startRenameTemplateInstance: (instance: PlotNode) => void;
    templateFilterId: string;
    templateInstances: PlotNode[];
    templateLoadError: string;
    templateToAddId: string;
    visibleTemplateInstances: PlotNode[];
  }

  let {
    addTemplateInstance,
    availableTemplates,
    cancelRenameTemplateInstance,
    clearDragOver,
    commitTemplateInstanceRename,
    deleteTemplateInstance,
    dragPalettePoint,
    focusRenameInput,
    handleTemplateRenameKeydown,
    instanceDisplayTitle,
    paletteRows,
    pointKey,
    rawInstanceTitle,
    renamingTemplateInstanceId = $bindable(null),
    renamingTemplateInstanceTitle = $bindable(""),
    savingMessage,
    selectedPalettePoint,
    selectPalettePoint,
    startRenameTemplateInstance,
    templateFilterId = $bindable(""),
    templateInstances,
    templateLoadError,
    templateToAddId = $bindable(""),
    visibleTemplateInstances,
  }: Props = $props();
</script>

<aside class="plot-palette" aria-label="Plot templates">
  <div class="add-template">
    <label class="filter-label">
      Add template
      <select bind:value={templateToAddId}>
        {#each availableTemplates as template (template.id)}
          <option value={template.id}>{template.title}</option>
        {/each}
      </select>
    </label>
    <button
      type="button"
      class="tool-button icon-only"
      title="Add template to board"
      aria-label="Add template to board"
      disabled={!templateToAddId || Boolean(savingMessage)}
      onclick={() => addTemplateInstance()}
    >
      <i class="ti ti-copy-plus" aria-hidden="true"></i>
    </button>
  </div>

  <label class="filter-label template-filter">
    Template
    <select bind:value={templateFilterId}>
      <option value="">All templates on board</option>
      {#each templateInstances as instance (instance.id)}
        <option value={instance.id}>{instanceDisplayTitle(instance)}</option>
      {/each}
    </select>
  </label>

  <div class="palette-list">
    {#if templateLoadError}
      <p class="muted-line">{templateLoadError}</p>
    {/if}
    {#if visibleTemplateInstances.length === 0}
      <p class="muted-line">No templates on this board.</p>
    {:else}
      {#each visibleTemplateInstances as instance (instance.id)}
        <section class="template-block">
          <header>
            <div class="template-title-row">
              {#if renamingTemplateInstanceId === instance.id}
                <input
                  class="template-title-input"
                  aria-label="Template instance name"
                  bind:value={renamingTemplateInstanceTitle}
                  disabled={Boolean(savingMessage)}
                  use:focusRenameInput
                  onkeydown={(event) => handleTemplateRenameKeydown(instance, event)}
                  onblur={() => {
                    void commitTemplateInstanceRename(instance);
                  }}
                />
                <button
                  type="button"
                  class="template-title-action"
                  title="Save name"
                  aria-label="Save name"
                  disabled={Boolean(savingMessage)}
                  onmousedown={(event) => event.preventDefault()}
                  onclick={() => {
                    void commitTemplateInstanceRename(instance);
                  }}
                >
                  <i class="ti ti-check" aria-hidden="true"></i>
                </button>
                <button
                  type="button"
                  class="template-title-action"
                  title="Cancel rename"
                  aria-label="Cancel rename"
                  disabled={Boolean(savingMessage)}
                  onmousedown={(event) => event.preventDefault()}
                  onclick={cancelRenameTemplateInstance}
                >
                  <i class="ti ti-x" aria-hidden="true"></i>
                </button>
              {:else}
                <strong title={rawInstanceTitle(instance)}>{instanceDisplayTitle(instance)}</strong>
                <button
                  type="button"
                  class="template-title-action"
                  title="Rename template instance"
                  aria-label="Rename template instance"
                  disabled={Boolean(savingMessage)}
                  onclick={() => startRenameTemplateInstance(instance)}
                >
                  <i class="ti ti-pencil" aria-hidden="true"></i>
                </button>
                <button
                  type="button"
                  class="template-title-action danger"
                  title="Delete template instance"
                  aria-label="Delete template instance"
                  disabled={Boolean(savingMessage)}
                  onclick={() => {
                    void deleteTemplateInstance(instance);
                  }}
                >
                  <i class="ti ti-trash" aria-hidden="true"></i>
                </button>
              {/if}
            </div>
            <span>{instance.template_instance?.plot_points?.length ?? 0} points</span>
          </header>
          {#each paletteRows.filter((row) => row.instance.id === instance.id) as row (row.point.plot_point_id)}
            <button
              type="button"
              class="point-row"
              class:selected={selectedPalettePoint === pointKey(row.instance.id, row.point.plot_point_id)}
              draggable={true}
              onclick={() => selectPalettePoint(row)}
              ondragstart={(event) => dragPalettePoint(row, event)}
              ondragend={clearDragOver}
            >
              <span class="point-title">{row.point.title || row.point.plot_point_id}</span>
              <span class="point-status" class:used={row.status === "used"} class:partial={row.status === "partial"} class:missing={row.status === "missing"}>
                {row.status}
              </span>
            </button>
          {/each}
        </section>
      {/each}
    {/if}
  </div>
</aside>
