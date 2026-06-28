<script context="module" lang="ts">
  // Embedded TODOs are extracted by App from open scene editor panes (the
  // note/status live on the editor pane component, hence paneId). This view
  // renders them above the file-level TODOs; App owns every mutation (they all
  // route through api or the editor pane components) and passes them as
  // callbacks. The shape lives here with its renderer.
  export type EmbeddedTodo = {
    id: string;
    text: string;
    status: "open" | "done";
    note: string;
    paneId: string;
    sceneId: string;
    sceneTitle: string;
  };
</script>

<script lang="ts">
  import type { TodoItem } from "./types";

  export let todos: TodoItem[];
  export let embeddedTodos: EmbeddedTodo[];
  // Two-way: the "Add" textarea. App clears it on a successful create (only
  // inside its run() success path), so it stays App-owned and binds down.
  export let newTodo: string;

  export let onAddTodo: () => void;
  export let onToggleTodo: (item: TodoItem) => void;
  export let onUpdateTodoText: (item: TodoItem, text: string) => void;
  export let onDeleteTodo: (item: TodoItem) => void;
  export let onTodoTextKeydown: (event: KeyboardEvent, item: TodoItem) => void;
  export let onOpenFileTodo: (item: TodoItem) => void;
  export let onToggleEmbeddedTodo: (item: EmbeddedTodo) => void;
  export let onUpdateEmbeddedTodoNote: (item: EmbeddedTodo, note: string) => void;
  export let onOpenEmbeddedTodo: (item: EmbeddedTodo) => void;
  export let onDeleteEmbeddedTodo: (item: EmbeddedTodo) => void;
</script>

<div class="todo-entry">
  <textarea bind:value={newTodo} placeholder="Add a file-level TODO description" rows="3" on:keydown={(event) => event.key === "Enter" && event.ctrlKey && onAddTodo()}></textarea>
  <button on:click={onAddTodo}>Add</button>
</div>
{#if embeddedTodos.length > 0}
  <div class="todo-section-label">Embedded TODOs from open scenes</div>
{/if}
{#each embeddedTodos as item}
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
        <strong>{item.sceneTitle}</strong>
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
