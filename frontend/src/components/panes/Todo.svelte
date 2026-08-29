<script lang="ts">
  import type { EmbeddedTodoRecord, TodoItem } from "@/lib/types";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeCard from "@/components/widgets/NodeCard.svelte";

  // Embedded (in-prose) TODOs are a rebuildable index over scenes (GH #45),
  // editor-pane independent. This view renders them above the file-level TODOs
  // as a NodeList of NodeCards (#1604): the done-toggle is the card's leading
  // slot, the editable description its body, the open/delete actions its
  // trailing slot. Every mutation routes through the todoActions controller
  // (intentful backend endpoints) and is passed in as a callback.
  let {
    todos,
    embeddedTodos,
    // Two-way: the "Add" textarea. App clears it on a successful create (only
    // inside its run() success path), so it stays App-owned and binds down.
    newTodo = $bindable(),
    onAddTodo,
    onToggleTodo,
    onUpdateTodoText,
    onDeleteTodo,
    onTodoTextKeydown,
    onOpenFileTodo,
    onToggleEmbeddedTodo,
    onUpdateEmbeddedTodoNote,
    onOpenEmbeddedTodo,
    onDeleteEmbeddedTodo,
  }: {
    todos: TodoItem[];
    embeddedTodos: EmbeddedTodoRecord[];
    newTodo: string;
    onAddTodo: () => void;
    onToggleTodo: (item: TodoItem) => void;
    onUpdateTodoText: (item: TodoItem, text: string) => void;
    onDeleteTodo: (item: TodoItem) => void;
    onTodoTextKeydown: (event: KeyboardEvent, item: TodoItem) => void;
    onOpenFileTodo: (item: TodoItem) => void;
    onToggleEmbeddedTodo: (item: EmbeddedTodoRecord) => void;
    onUpdateEmbeddedTodoNote: (item: EmbeddedTodoRecord, note: string) => void;
    onOpenEmbeddedTodo: (item: EmbeddedTodoRecord) => void;
    onDeleteEmbeddedTodo: (item: EmbeddedTodoRecord) => void;
  } = $props();
</script>

<div class="todo-entry">
  <textarea bind:value={newTodo} placeholder="Add a file-level TODO description" rows="3" data-gramm="false" data-gramm_editor="false" onkeydown={(event) => event.key === "Enter" && event.ctrlKey && onAddTodo()}></textarea>
  <button onclick={onAddTodo}>Add</button>
</div>

{#if embeddedTodos.length > 0}
  <div class="todo-section-label">Embedded TODOs</div>
  <NodeList>
    {#each embeddedTodos as item (item.scene_id + ":" + item.todo_id)}
      <!-- Embedded TODOs live in prose → the sanctioned amber anchor stripe
           (the one non-pin gold; the source is carried by the stripe, not a
           coloured badge). -->
      <NodeCard stripeColor="var(--star)" title={item.scene_path} detail={item.text}>
        {#snippet leading()}
          <input class="todo-checkbox" type="checkbox" checked={item.status === "done"} aria-label="Toggle embedded TODO" onchange={() => onToggleEmbeddedTodo(item)} />
        {/snippet}
        {#snippet trailing()}
          <button class="todo-open" type="button" onclick={() => onOpenEmbeddedTodo(item)}>Open scene</button>
          <button class="todo-delete" type="button" onclick={() => onDeleteEmbeddedTodo(item)}>Remove</button>
        {/snippet}
        {#snippet body()}
          <div class="todo-text-stack" class:done={item.status === "done"}>
            <textarea
              class="todo-text"
              value={item.note}
              aria-label="Embedded TODO note"
              title="Edit embedded TODO note"
              placeholder={item.text}
              rows="3"
              data-gramm="false"
              data-gramm_editor="false"
              onblur={(event) => onUpdateEmbeddedTodoNote(item, event.currentTarget.value)}
            ></textarea>
          </div>
        {/snippet}
      </NodeCard>
    {/each}
  </NodeList>
{/if}

{#if todos.length > 0}
  <div class="todo-section-label">File TODOs</div>
  <NodeList>
    {#each todos as item}
      <NodeCard>
        {#snippet leading()}
          <input class="todo-checkbox" type="checkbox" checked={item.status === "done"} aria-label="Toggle TODO" onchange={() => onToggleTodo(item)} />
        {/snippet}
        {#snippet trailing()}
          {#if item.scene_id}
            <button class="todo-open" type="button" onclick={() => onOpenFileTodo(item)}>Open scene</button>
          {:else}
            <span class="todo-source">Project</span>
          {/if}
          <button class="todo-delete" type="button" onclick={() => onDeleteTodo(item)}>Delete</button>
        {/snippet}
        {#snippet body()}
          <div class="todo-text-stack" class:done={item.status === "done"}>
            <textarea
              class="todo-text"
              value={item.text}
              aria-label="TODO description"
              title="Edit TODO description"
              placeholder="Describe this TODO"
              rows="3"
              data-gramm="false"
              data-gramm_editor="false"
              onblur={(event) => onUpdateTodoText(item, event.currentTarget.value)}
              onkeydown={(event) => onTodoTextKeydown(event, item)}
            ></textarea>
          </div>
        {/snippet}
      </NodeCard>
    {/each}
  </NodeList>
{/if}

<style>
  /* Todo pane styles co-located from styles.css (#14). Own template DOM →
     scoped, no :global. `.todo-entry` stays global (grouped with the shared
     .button-row/.toolbar form utilities). The row layout is now NodeCard's;
     what remains here is the composer's chrome, the section labels, and the
     TODO field + its trailing atoms placed in the card slots. */
  .todo-section-label {
    margin: var(--sp-4) 0 var(--sp-2);
    color: var(--text-3);
    font-size: var(--fs-sm);
    font-weight: var(--w-bold);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .todo-checkbox {
    flex: none;
    width: 15px;
    height: 15px;
    accent-color: var(--accent);
  }

  /* The editable field stays wrapped in `.todo-text-stack` so a writing-assistant
     extension's injected overlay is contained here, inside the card body, rather
     than perturbing the header row (checkbox + actions). This is stronger than
     the old grid defence: the header and body are separate flex children of the
     card column, so body injection can't shift the checkbox. See GH #1330. */
  .todo-text-stack {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    min-width: 0;
    width: 100%;
  }

  .todo-text {
    width: 100%;
    min-height: 62px;
    padding: var(--sp-1) var(--sp-2);
    border: 1px solid var(--divider);
    border-radius: var(--r-md);
    background: var(--surface);
    color: var(--text);
    font-family: inherit;
    font-size: var(--fs-md);
    line-height: 1.4;
    resize: vertical;
  }

  .todo-text:focus {
    outline: none;
    border-color: var(--border);
  }

  .todo-text-stack.done .todo-text {
    color: var(--text-3);
    text-decoration: line-through;
  }

  /* Source label — neutral. Gold is the pin + the prose-TODO anchor stripe, so
     a plain "Project" label must not borrow it (design language §3.2). */
  .todo-source {
    align-self: center;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: var(--w-bold);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .todo-open {
    padding: 3px 9px;
    border: 1px solid var(--divider);
    border-radius: var(--r-sm);
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-sm);
    white-space: nowrap;
    cursor: pointer;
  }

  .todo-open:hover {
    border-color: var(--border);
    background: var(--inset);
  }

  .todo-delete {
    padding: 3px 9px;
    border: 1px solid var(--danger-border);
    border-radius: var(--r-sm);
    color: var(--danger);
    background: transparent;
    font-size: var(--fs-sm);
    cursor: pointer;
  }

  .todo-delete:hover {
    background: var(--danger-soft);
  }
</style>
