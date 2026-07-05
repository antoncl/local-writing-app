<!--
  ProseSlashMenu — presentational floating "/" command palette for ProseBodyView.

  Purely a view: the host owns the menu state, builds + filters the command
  list, positions the popover, and runs commands. This renders the command
  list (grouped) or the table-size grid and calls back on hover / activation.
  The onmousedown handlers preventDefault so clicking a command never blurs
  the editor (the host's commands read the live selection).
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
</script>

{#if menu.visible}
  <div class:table-mode={menu.mode === "table-grid"} class="slash-menu" style={`left: ${menu.x}px; top: ${menu.y}px;`}>
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
                onmousedown={(e) => {
                  e.preventDefault();
                  onInsertTable(rowIndex + 1, colIndex + 1);
                }}
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
      {#each commands as command, index}
        {#if index === 0 || commands[index - 1].group !== command.group}
          <div class="slash-group">{command.group}</div>
        {/if}
        <button
          class:active={index === menu.selectedIndex}
          type="button"
          onmouseenter={() => onHoverCommand(index)}
          onmousedown={(e) => {
            e.preventDefault();
            onRunCommand(command);
          }}
        >
          <strong>{command.label}</strong>
          <span>{command.description}</span>
        </button>
      {/each}
    {/if}
  </div>
{/if}

<style>
  .slash-menu {
    position: absolute;
    z-index: 25;
    display: grid;
    width: min(380px, calc(100% - 32px));
    max-height: min(420px, calc(100% - 32px));
    overflow: auto;
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    box-shadow: var(--elev-2);
  }

  .slash-menu.table-mode {
    width: max-content;
    padding: 4px;
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

  .slash-menu button {
    display: grid;
    gap: 3px;
    width: 100%;
    min-height: 58px;
    padding: 9px 10px;
    border-color: transparent;
    background: transparent;
    text-align: left;
  }

  .slash-menu button.active,
  .slash-menu button:hover {
    background: var(--accent-soft);
  }

  .slash-menu button strong {
    color: var(--text);
    font-size: var(--fs-md);
  }

  .slash-menu button span {
    color: var(--text-3);
    font-size: var(--fs-sm);
    line-height: 1.35;
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
