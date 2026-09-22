// @vitest-environment happy-dom
// ADR-0090 Amendment 2 §1 — the computed "Review items" field tab. A pane
// that DISPLAYS data needs a mount test asserting rows render (#642): this
// filters `$todosStore` down to the open, node-scoped items for ONE node, so
// the render contract IS the filter.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ReviewItemsPanel from "./ReviewItemsPanel.svelte";
import { todosStore } from "@/lib/stores/todos";
import { loreEntriesStore } from "@/lib/stores/lore";
import { todoActions } from "@/lib/stores/todoActions.svelte";
import type { TodoItem } from "@/lib/types";

function reviewItem(id: string, node_id: string, text: string): TodoItem {
  return {
    id,
    text,
    status: "open",
    scope: "node",
    node_id,
    source: { node_id: "lore_marek", snapshot_id: "", reason: "references_source", marker_id: "" },
  };
}

describe("ReviewItemsPanel (ADR-0090 Amendment 2 §1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    loreEntriesStore.set([
      { id: "lore_marek", title: "Marek Vell", body: "", entry_type: "lore:character", metadata: {} },
    ]);
  });

  it("renders exactly the open review items for this node, with their reason detail", () => {
    todosStore.set([
      reviewItem("t1", "guard", "Follow up on Marek Vell's change"),
      reviewItem("t2", "guard", "Second follow-up"),
      reviewItem("t3", "ilse", "A different node's item"),
      { ...reviewItem("t4", "guard", "Already handled"), status: "done" },
    ]);

    render(ReviewItemsPanel, { props: { nodeId: "guard", nodeTitle: "City Guard" } });

    expect(screen.getByText("Follow up on Marek Vell's change")).toBeInTheDocument();
    expect(screen.getByText("Second follow-up")).toBeInTheDocument();
    expect(screen.queryByText("A different node's item")).not.toBeInTheDocument();
    expect(screen.queryByText("Already handled")).not.toBeInTheDocument();
    // The reason grammar names the route and the resolved source title.
    expect(screen.getAllByText(/refers to the change · from Marek Vell/).length).toBe(2);
  });

  it("shows the empty state when there are no open review items for this node", () => {
    todosStore.set([reviewItem("t1", "someone-else", "Not this node")]);
    render(ReviewItemsPanel, { props: { nodeId: "guard", nodeTitle: "City Guard" } });
    expect(screen.getByText("No open review items.")).toBeInTheDocument();
  });

  it("opens a row through todoActions.openFileTodo", async () => {
    const openFileTodo = vi.spyOn(todoActions, "openFileTodo").mockResolvedValue(undefined);
    const item = reviewItem("t1", "guard", "Follow up on Marek Vell's change");
    todosStore.set([item]);

    render(ReviewItemsPanel, { props: { nodeId: "guard", nodeTitle: "City Guard" } });
    await fireEvent.click(screen.getByText("Follow up on Marek Vell's change"));

    expect(openFileTodo).toHaveBeenCalledWith(item);
  });
});
