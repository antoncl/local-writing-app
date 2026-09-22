// @vitest-environment happy-dom
// ADR-0090 Amendment 2 §1 — the computed "Review items" field tab. A pane
// that DISPLAYS data needs a mount test asserting rows render (#642): this
// filters `$todosStore` down to the open, node-scoped items for ONE node, so
// the render contract IS the filter. ADR-0090 §4 adds the Propose tile.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import ReviewItemsPanel from "./ReviewItemsPanel.svelte";
import { todosStore } from "@/lib/stores/todos";
import { loreEntriesStore } from "@/lib/stores/lore";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { todoActions } from "@/lib/stores/todoActions.svelte";
import type { MetadataSchema, PromptEntrySummary, TodoItem } from "@/lib/types";

const SCHEMA = { entry_types: {}, fields: {} } as unknown as MetadataSchema;

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

function reviseEntry(offerOn: string[]): PromptEntrySummary {
  return {
    id: "p-revise",
    title: "Revise entry",
    body: "",
    entry_type: "prompt:general",
    metadata: {},
    inputs: [],
    offer_on: offerOn,
    context_strategy: null,
  } as unknown as PromptEntrySummary;
}

describe("ReviewItemsPanel (ADR-0090 Amendment 2 §1 / §4 Propose)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    loreEntriesStore.set([
      { id: "lore_marek", title: "Marek Vell", body: "", entry_type: "lore:character", metadata: {} },
    ]);
    metadataSchemaStore.set(SCHEMA);
  });

  it("renders exactly the open review items for this node, with their reason detail", () => {
    todosStore.set([
      reviewItem("t1", "guard", "Follow up on Marek Vell's change"),
      reviewItem("t2", "guard", "Second follow-up"),
      reviewItem("t3", "ilse", "A different node's item"),
      { ...reviewItem("t4", "guard", "Already handled"), status: "done" },
    ]);

    render(ReviewItemsPanel, { props: { nodeId: "guard", nodeTitle: "City Guard", promptEntries: [] } });

    expect(screen.getByText("Follow up on Marek Vell's change")).toBeInTheDocument();
    expect(screen.getByText("Second follow-up")).toBeInTheDocument();
    expect(screen.queryByText("A different node's item")).not.toBeInTheDocument();
    expect(screen.queryByText("Already handled")).not.toBeInTheDocument();
    // The reason grammar names the route and the resolved source title.
    expect(screen.getAllByText(/refers to the change · from Marek Vell/).length).toBe(2);
  });

  it("shows the empty state when there are no open review items for this node", () => {
    todosStore.set([reviewItem("t1", "someone-else", "Not this node")]);
    render(ReviewItemsPanel, { props: { nodeId: "guard", nodeTitle: "City Guard", promptEntries: [] } });
    expect(screen.getByText("No open review items.")).toBeInTheDocument();
  });

  it("opens a row through todoActions.openFileTodo", async () => {
    const openFileTodo = vi.spyOn(todoActions, "openFileTodo").mockResolvedValue(undefined);
    const item = reviewItem("t1", "guard", "Follow up on Marek Vell's change");
    todosStore.set([item]);

    render(ReviewItemsPanel, {
      props: { nodeId: "guard", nodeTitle: "City Guard", promptEntries: [] },
    });
    await fireEvent.click(screen.getByText("Follow up on Marek Vell's change"));

    expect(openFileTodo).toHaveBeenCalledWith(item);
  });

  it("renders a disabled Propose tile when no prompt is offered on this type", () => {
    todosStore.set([reviewItem("t1", "guard", "Follow up on Marek Vell's change")]);
    render(ReviewItemsPanel, {
      props: {
        nodeId: "guard",
        nodeTitle: "City Guard",
        subjectEntryType: "lore:character",
        promptEntries: [reviseEntry(["plot:card"])],
      },
    });
    const button = screen.getByRole("button", { name: /Propose a follow-up/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "No prompt is offered on this type");
  });

  it("picking a prompt from the Propose menu calls todoActions.proposeFromReviewItem", async () => {
    const propose = vi.spyOn(todoActions, "proposeFromReviewItem").mockResolvedValue(undefined);
    const item = reviewItem("t1", "guard", "Follow up on Marek Vell's change");
    todosStore.set([item]);
    const prompt = reviseEntry(["lore:character"]);

    render(ReviewItemsPanel, {
      props: {
        nodeId: "guard",
        nodeTitle: "City Guard",
        subjectEntryType: "lore:character",
        promptEntries: [prompt],
      },
    });

    const button = screen.getByRole("button", { name: /Propose a follow-up/ });
    expect(button).not.toBeDisabled();
    await fireEvent.click(button);
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Revise entry" }));

    expect(propose).toHaveBeenCalledTimes(1);
    const [calledItem, calledPrompt, seededInputs, opts] = propose.mock.calls[0];
    expect(calledItem).toEqual(item);
    expect(calledPrompt).toEqual(expect.objectContaining({ id: "p-revise" }));
    expect(seededInputs).toEqual({ entry: "guard" });
    expect(opts).toEqual({ subjectTitle: "City Guard" });
  });
});
