<!--
  ProseSlashMenu — presentational floating "/" command palette for ProseBodyView.

  Purely a view: the host owns the menu state, builds + filters the command
  list, positions the popover, and runs commands. This renders the command
  list (grouped) or the table-size grid and calls back on hover / activation.
  The root's onmousedown preventDefaults, so no click anywhere on the menu —
  a command, a group label, the scrollbar — blurs the editor: the host's
  commands read the live selection, and its keymap drives the menu (#2454).
  Rows are one line; the highlighted command's description shows in a footer,
  and the highlight is kept scrolled into view for keyboard navigation.
-->
<script lang="ts">
  import {
    TABLE_GRID_MAX_ROWS,
    TABLE_GRID_MAX_COLS,
    type SlashCommand,
    type SlashMenuState,
  } from "@/lib/editor-core/slashMenu";

  interface Props {
    menu: SlashMenuState;
    filterText: string;
    commands: SlashCommand[];
    onRunCommand: (command: SlashCommand) => void;
    onInsertTable: (rows: number, cols: number) => void;
    onHoverCommand: (index: number) => void;
    onHoverGrid: (rows: number, cols: number) => void;
  }

  let { menu, filterText, commands, onRunCommand, onInsertTable, onHoverCommand, onHoverGrid }: Props =
    $props();

  let list: HTMLDivElement | undefined = $state();
  let activeCommand = $derived(commands[menu.selectedIndex]);

  // Keep the highlighted row visible — on a highlight move AND on a filter
  // change that re-renders the rows under the same index. Adjusts only the
  // list's scrollTop: scrollIntoView would also scroll the editor frame
  // behind the menu (the WorkspaceTabStrip trap).
  $effect(() => {
    const index = menu.selectedIndex;
    void commands;
    if (!menu.visible || menu.mode !== "commands" || !list) return;
    const row = list.querySelector<HTMLElement>(`[data-index="${index}"]`);
    if (!row) return;
    // A group's first row brings its group label into view with it.
    const label = row.previousElementSibling?.classList.contains("slash-group") ? row.previousElementSibling : null;
    const top = ((label as HTMLElement | null) ?? row).offsetTop - list.offsetTop;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (top + row.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = top + row.offsetHeight - list.clientHeight;
    }
  });
</script>

{#if menu.visible}
  <div
    class:table-mode={menu.mode === "table-grid"}
    class="slash-menu"
    style={`left: ${menu.x}px; top: ${menu.y}px;`}
    role="presentation"
    onmousedown={(e) => e.preventDefault()}
  >
    {#if menu.mode === "table-grid"}
      <div class="table-grid">
        {#each Array(TABLE_GRID_MAX_ROWS) as _, rowIndex}
          <div class="table-grid-row">
            {#each Array(TABLE_GRID_MAX_COLS) as _, colIndex}
              <button
                class:active={rowIndex < menu.gridRows && colIndex < menu.gridCols}
                type="button"
                aria-label={`${rowIndex + 1} rows by ${colIndex + 1} columns`}
                onmouseenter={() => onHoverGrid(rowIndex + 1, colIndex + 1)}
                onmousedown={() => onInsertTable(rowIndex + 1, colIndex + 1)}
              ></button>
            {/each}
          </div>
        {/each}
      </div>
      <div class="table-grid-label">{menu.gridCols} × {menu.gridRows}</div>
    {:else}
      {#if filterText}
        <div class="slash-filter-indicator">filter: <code>{filterText}</code></div>
      {/if}
      {#if commands.length === 0}
        <div class="slash-empty">No commands match "<code>{filterText}</code>"</div>
      {/if}
      <div class="slash-list" bind:this={list}>
        {#each commands as command, index}
          {#if index === 0 || commands[index - 1].group !== command.group}
            <div class="slash-group">{command.group}</div>
          {/if}
          <button
            class:active={index === menu.selectedIndex}
            type="button"
            data-index={index}
            onmouseenter={() => onHoverCommand(index)}
            onmousedown={() => onRunCommand(command)}
          >
            {command.label}
          </button>
        {/each}
      </div>
      {#if activeCommand}
        <div class="slash-hint">{activeCommand.hint || activeCommand.description}</div>
      {/if}
    {/if}
  </div>
{/if}

<style>
  .slash-menu {
    position: absolute;
    z-index: 25;
    display: flex;
    flex-direction: column;
    width: min(320px, calc(100% - 32px));
    max-height: min(420px, calc(100% - 32px));
    padding: 6px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    box-shadow: var(--elev-2);
  }

  .slash-menu.table-mode {
    width: max-content;
    padding: 4px;
  }

  /* The list scrolls on its own and never hands the wheel on to the editor's
     scroll frame (#2454); the hint footer stays put below it. */
  .slash-list {
    display: grid;
    min-height: 0;
    overflow: auto;
    overscroll-behavior: contain;
  }

  .slash-hint {
    flex: none;
    margin-top: 4px;
    padding: 6px 8px 2px;
    border-top: 1px solid var(--border);
    color: var(--text-3);
    font-size: var(--fs-sm);
    line-height: 1.35;
  }

  .slash-group {
    padding: 8px 6px 5px;
    color: var(--text-3);
    font-size: var(--fs-sm);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .slash-filter-indicator {
    padding: 6px 10px;
    background: var(--inset);
    border-bottom: 1px solid var(--border);
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .slash-filter-indicator code {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--accent-deep);
    background: transparent;
  }

  .slash-empty {
    padding: 14px 12px;
    color: var(--text-3);
    font-size: var(--fs-md);
    font-style: italic;
    text-align: center;
  }

  .slash-empty code {
    font-family: var(--mono);
    font-style: normal;
    color: var(--text-2);
  }

  .slash-list button {
    width: 100%;
    padding: 5px 10px;
    border-color: transparent;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-md);
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .slash-list button.active,
  .slash-list button:hover {
    background: var(--accent-soft);
  }

  .slash-menu .table-grid {
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 6px 10px 2px;
    width: max-content;
  }

  .slash-menu .table-grid-row {
    display: flex;
    gap: 1px;
  }

  .slash-menu .table-grid button {
    display: block;
    width: 13px;
    height: 13px;
    min-width: 13px;
    min-height: 13px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 2px;
    background: var(--surface);
    cursor: pointer;
  }

  .slash-menu .table-grid button.active {
    background: var(--accent);
    border-color: var(--accent-deep);
  }

  .slash-menu .table-grid button:hover {
    background: var(--surface);
  }

  .slash-menu .table-grid button.active:hover {
    background: var(--accent);
  }

  .slash-menu .table-grid button:focus {
    outline: none;
  }

  .slash-menu .table-grid-label {
    padding: 4px 12px 10px;
    color: var(--text-2);
    font-size: var(--fs-sm);
    text-align: center;
  }
</style>
