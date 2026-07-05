<script lang="ts">
  import type { EmbeddedTodoRecord, TodoItem } from "@/lib/types";

  // Embedded (in-prose) TODOs are a rebuildable index over scenes (GH #45),
  // editor-pane independent. This view renders them above the file-level TODOs;
  // every mutation routes through the todoActions controller (intentful backend
  // endpoints) and is passed in as a callback.
  export let todos: TodoItem[];
  export let embeddedTodos: EmbeddedTodoRecord[];
  // Two-way: the "Add" textarea. App clears it on a successful create (only
  // inside its run() success path), so it stays App-owned and binds down.
  export let newTodo: string;

  export let onAddTodo: () => void;
  export let onToggleTodo: (item: TodoItem) => void;
  export let onUpdateTodoText: (item: TodoItem, text: string) => void;
  export let onDeleteTodo: (item: TodoItem) => void;
  export let onTodoTextKeydown: (event: KeyboardEvent, item: TodoItem) => void;
  export let onOpenFileTodo: (item: TodoItem) => void;
  export let onToggleEmbeddedTodo: (item: EmbeddedTodoRecord) => void;
  export let onUpdateEmbeddedTodoNote: (item: EmbeddedTodoRecord, note: string) => void;
  export let onOpenEmbeddedTodo: (item: EmbeddedTodoRecord) => void;
  export let onDeleteEmbeddedTodo: (item: EmbeddedTodoRecord) => void;
</script>

<div class="todo-entry">
  <textarea bind:value={newTodo} placeholder="Add a file-level TODO description" rows="3" on:keydown={(event) => event.key === "Enter" && event.ctrlKey && onAddTodo()}></textarea>
  <button on:click={onAddTodo}>Add</button>
</div>
{#if embeddedTodos.length > 0}
  <div class="todo-section-label">Embedded TODOs</div>
{/if}
{#each embeddedTodos as item (item.scene_id + ":" + item.todo_id)}
  <div class:done={item.status === "done"} class="todo-item">
    <input class="todo-checkbox" type="checkbox" checked={item.status === "done"} aria-label="Toggle embedded TODO" on:change={() => onToggleEmbeddedTodo(item)} />
    <div class="todo-text-stack">
      <textarea
        class="todo-text"
        value={item.note}
        aria-label="Embedded TODO note"
        title="Edit embedded TODO note"
        placeholder={item.text}
        rows="3"
        on:blur={(event) => onUpdateEmbeddedTodoNote(item, event.currentTarget.value)}
      ></textarea>
      <button class="todo-link" type="button" on:click={() => onOpenEmbeddedTodo(item)}>
        <strong>{item.scene_path}</strong>
        <span>{item.text}</span>
      </button>
    </div>
    <small>Embedded</small>
    <button class="todo-delete" type="button" on:click={() => onDeleteEmbeddedTodo(item)}>Remove</button>
  </div>
{/each}
{#if todos.length > 0}
  <div class="todo-section-label">File TODOs</div>
{/if}
{#each todos as item}
  <div class:done={item.status === "done"} class="todo-item">
    <input class="todo-checkbox" type="checkbox" checked={item.status === "done"} aria-label="Toggle TODO" on:change={() => onToggleTodo(item)} />
    <textarea
      class="todo-text"
      value={item.text}
      aria-label="TODO description"
      title="Edit TODO description"
      placeholder="Describe this TODO"
      rows="3"
      on:blur={(event) => onUpdateTodoText(item, event.currentTarget.value)}
      on:keydown={(event) => onTodoTextKeydown(event, item)}
    ></textarea>
    {#if item.scene_id}
      <button class="todo-link compact" type="button" on:click={() => onOpenFileTodo(item)}>Open Scene</button>
    {:else}
      <small>Project</small>
    {/if}
    <button class="todo-delete" type="button" on:click={() => onDeleteTodo(item)}>Delete</button>
  </div>
{/each}

<style>
  /* Todo pane styles co-located from styles.css (#14). Own template DOM →
     scoped, no :global. `.todo-entry` stays global (grouped with the shared
     .button-row/.toolbar form utilities). */
  .todo-item {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto auto;
    align-items: start;
    gap: 8px;
    margin: 8px 0;
  }

  .todo-checkbox {
    width: auto;
  }

  .todo-text {
    min-width: 0;
    min-height: 68px;
    padding: 5px 7px;
    border-color: var(--divider);
    background: var(--surface);
    line-height: 1.35;
  }

  .todo-text:focus {
    border-color: var(--border);
    background: var(--surface);
    outline: none;
  }

  .todo-item.done .todo-text {
    color: var(--text-3);
    text-decoration: line-through;
  }

  .todo-section-label {
    margin: 14px 0 6px;
    color: var(--text-3);
    font-size: var(--fs-sm);
    font-weight: 700;
    text-transform: uppercase;
  }

  .todo-text-stack {
    display: grid;
    gap: 4px;
    min-width: 0;
  }

  .todo-link {
    display: grid;
    gap: 2px;
    width: 100%;
    padding: 5px 7px;
    border-color: var(--divider);
    color: var(--text);
    background: var(--surface);
    text-align: left;
  }

  .todo-link:hover,
  .todo-link:focus {
    border-color: var(--border);
    background: var(--inset);
  }

  .todo-link strong {
    color: var(--text);
    font-size: var(--fs-sm);
  }

  .todo-link span {
    color: var(--text-2);
    font-size: var(--fs-sm);
    line-height: 1.35;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .todo-link.compact {
    width: auto;
    white-space: nowrap;
  }

  .todo-item small {
    color: var(--star);
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
  }

  .todo-delete {
    padding: 3px 7px;
    border-color: var(--danger-border);
    color: var(--danger);
    font-size: var(--fs-sm);
  }
</style>
