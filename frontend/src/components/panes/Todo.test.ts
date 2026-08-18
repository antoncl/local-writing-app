// @vitest-environment happy-dom
// Todo pane render contract. Per the component-test-harness rule (#642: a pane
// that DISPLAYS data needs a test asserting its rows render), and to guard the
// runes conversion (#49): props via `$props()` incl. `$bindable` newTodo, and
// the `on:` → event-prop rename on every checkbox/button. Nothing mounted this
// pane before, so a regression that stopped todos rendering was invisible to
// the logic tests and svelte-check.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import Todo from "./Todo.svelte";
import type { EmbeddedTodoRecord, TodoItem } from "@/lib/types";

function fileTodo(id: string, text: string, scene_id: string | null = null): TodoItem {
  return { id, text, status: "open", scope: scene_id ? "scene" : "project", scene_id };
}

function embedded(todo_id: string, text: string, scene_path: string): EmbeddedTodoRecord {
  return { todo_id, scene_id: `s_${todo_id}`, status: "open", note: "", text, line: 1, scene_path };
}

const noop = () => {};

function baseProps() {
  return {
    todos: [] as TodoItem[],
    embeddedTodos: [] as EmbeddedTodoRecord[],
    newTodo: "",
    onAddTodo: noop,
    onToggleTodo: noop,
    onUpdateTodoText: noop,
    onDeleteTodo: noop,
    onTodoTextKeydown: noop,
    onOpenFileTodo: noop,
    onToggleEmbeddedTodo: noop,
    onUpdateEmbeddedTodoNote: noop,
    onOpenEmbeddedTodo: noop,
    onDeleteEmbeddedTodo: noop,
  };
}

describe("Todo pane — rows render", () => {
  it("renders file-level and embedded TODOs from props", () => {
    render(Todo, {
      props: {
        ...baseProps(),
        todos: [fileTodo("t1", "Buy milk")],
        embeddedTodos: [embedded("e1", "Fix the timeline", "scenes/act-1/arrival.md")],
      },
    });
    // File-level TODO text is the textarea value.
    expect(screen.getByDisplayValue("Buy milk")).toBeInTheDocument();
    // Embedded TODO surfaces its scene path and text.
    expect(screen.getByText("scenes/act-1/arrival.md")).toBeInTheDocument();
    expect(screen.getByText("Fix the timeline")).toBeInTheDocument();
  });

  it("routes a checkbox toggle through the callback (on:change → onchange)", async () => {
    const onToggleTodo = vi.fn();
    const item = fileTodo("t1", "Buy milk");
    render(Todo, { props: { ...baseProps(), todos: [item], onToggleTodo } });

    await fireEvent.click(screen.getByLabelText("Toggle TODO"));
    expect(onToggleTodo).toHaveBeenCalledWith(item);
  });
});
