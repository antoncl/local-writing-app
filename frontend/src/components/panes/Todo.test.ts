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

function fileTodo(
  id: string,
  text: string,
  scene_id: string | null = null,
  extra: Partial<TodoItem> = {},
): TodoItem {
  return {
    id,
    text,
    status: "open",
    scope: scene_id ? "scene" : "project",
    scene_id,
    ...extra,
  };
}

// A review item (ADR-0090 §3): node-scoped, with a `source` block naming the
// change it followed from.
function nodeTodo(id: string, text: string, node_id: string): TodoItem {
  return {
    id,
    text,
    status: "open",
    scope: "node",
    node_id,
    source: { node_id: "lore_marek", snapshot_id: "snap_1", reason: "mentions_source", marker_id: "" },
  };
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

  // Browser writing-assistant hardening (GH #1330). The fix is invisible without
  // an extension mounted, so guard the two DOM invariants it rests on: the
  // editable field stays wrapped in `.todo-text-stack` (injection contained in
  // grid column 2, keeping the checkbox aligned) and carries the Grammarly
  // opt-out. A regression here would only surface with an extension enabled.
  it("keeps the file-TODO field wrapped and extension-opted-out", () => {
    render(Todo, { props: { ...baseProps(), todos: [fileTodo("t1", "Buy milk")] } });
    const field = screen.getByDisplayValue("Buy milk");
    expect(field.closest(".todo-text-stack")).not.toBeNull();
    expect(field).toHaveAttribute("data-gramm", "false");
  });

  // ADR-0090 §3/§6: a review item is `node`-scoped and carries a `source` —
  // it renders "Open entry" (not "Open scene"/"Project") and its provenance
  // line, and opening it routes through the same onOpenFileTodo callback.
  it("renders a node-scoped review item's 'Open entry' button and source line", async () => {
    const onOpenFileTodo = vi.fn();
    const item = nodeTodo("t1", "Follow up on Marek Vell's change", "guard");
    render(Todo, {
      props: {
        ...baseProps(),
        todos: [item],
        onOpenFileTodo,
        nodeTitle: (id: string) => (id === "lore_marek" ? "Marek Vell" : undefined),
      },
    });

    expect(screen.getByDisplayValue("Follow up on Marek Vell's change")).toBeInTheDocument();
    const openButton = screen.getByRole("button", { name: "Open entry" });
    expect(openButton).toBeInTheDocument();
    // The row leads with the HOME the button opens (#2145): the bare id when
    // no lookup resolves it, never the source twice.
    expect(screen.getByText(/^guard · mentions the change · from Marek Vell$/)).toBeInTheDocument();

    await fireEvent.click(openButton);
    expect(onOpenFileTodo).toHaveBeenCalledWith(item);
  });

  // #2145: the home resolves live through the same lookup as the source — a
  // lore dependent by its title, a scene dependent by its scene id.
  it("leads a review item's line with its home's title, for a lore and a scene dependent", () => {
    const loreItem = nodeTodo("t1", "Follow up on Marek Vell's change", "lore_guard");
    const sceneItem: TodoItem = {
      id: "t2",
      text: "Follow up on Marek Vell's change",
      status: "open",
      scope: "scene",
      scene_id: "scene_ch5",
      source: { node_id: "lore_marek", snapshot_id: "snap_1", reason: "mutates_source", marker_id: "m_rank" },
    };
    const titles: Record<string, string> = {
      lore_marek: "Marek Vell",
      lore_guard: "City Guard",
      scene_ch5: "Chapter 5 · The Gate",
    };
    render(Todo, {
      props: { ...baseProps(), todos: [loreItem, sceneItem], nodeTitle: (id: string) => titles[id] },
    });

    expect(screen.getByText("City Guard · mentions the change · from Marek Vell")).toBeInTheDocument();
    expect(screen.getByText("Chapter 5 · The Gate · ⤳ a marker on the change · from Marek Vell")).toBeInTheDocument();
    expect(screen.queryByText(/^review item ·/)).not.toBeInTheDocument();
  });
});
