// @vitest-environment happy-dom
// ADR-0090 Amendment 2 §1 — the computed "Review items" field tab. A pane
// that DISPLAYS data needs a mount test asserting rows render (#642): this
// filters `$todosStore` down to the open, node-scoped items for ONE node, so
// the render contract IS the filter. ADR-0090 §4 adds the Propose tile.
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import ReviewItemsPanel from "./ReviewItemsPanel.svelte";
import { todosStore } from "@/lib/stores/todos";
import { loreEntriesStore } from "@/lib/stores/lore";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { todoActions } from "@/lib/stores/todoActions.svelte";
import { hideLibraryEntry, openProjectHidden, unhideLibraryEntry } from "@/lib/stores/hiddenLibrary";
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

// ADR-0091 §4: the built-in Propose default — a committing prompt titled
// "Follow a change", offered wherever Revise entry is.
function followAChange(offerOn: string[], overrides: Partial<PromptEntrySummary> = {}): PromptEntrySummary {
  return {
    id: "p-follow",
    title: "Follow a change",
    body: "",
    entry_type: "prompt:general",
    metadata: {},
    inputs: [{ name: "entry", type: "context_pick", required: true }],
    offer_on: offerOn,
    context_strategy: { output: { handler: "extract_to_node", commit: { review: "visual_diff" } } },
    is_library: true,
    ...overrides,
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

// ADR-0093 §4: a prompt declaring the two hidden change inputs.
function promptWithChangeInputs(offerOn: string[]): PromptEntrySummary {
  return {
    id: "p-change",
    title: "Prompt with change inputs",
    body: "",
    entry_type: "prompt:general",
    metadata: {},
    inputs: [
      { name: "source", type: "context_pick", required: false, hidden: true },
      { name: "baseline", type: "text", required: false, hidden: true },
    ],
    offer_on: offerOn,
    context_strategy: null,
  } as unknown as PromptEntrySummary;
}

describe("ReviewItemsPanel — ADR-0093 §4: seeding the change inputs", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    loreEntriesStore.set([
      { id: "lore_marek", title: "Marek Vell", body: "", entry_type: "lore:character", metadata: {} },
    ]);
    metadataSchemaStore.set(SCHEMA);
  });

  it("seeds source and baseline from the item's source block", async () => {
    const propose = vi.spyOn(todoActions, "proposeFromReviewItem").mockResolvedValue(undefined);
    const item: TodoItem = {
      ...reviewItem("t1", "guard", "Follow up on Marek Vell's change"),
      source: { node_id: "lore_marek", snapshot_id: "snap_1", reason: "references_source", marker_id: "" },
    };
    todosStore.set([item]);

    render(ReviewItemsPanel, {
      props: {
        nodeId: "guard",
        nodeTitle: "City Guard",
        subjectEntryType: "lore:character",
        promptEntries: [promptWithChangeInputs(["lore:character"])],
      },
    });

    await fireEvent.click(screen.getByRole("button", { name: /Propose a follow-up/ }));
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Prompt with change inputs" }));

    expect(propose).toHaveBeenCalledTimes(1);
    const [, , seededInputs] = propose.mock.calls[0];
    expect(seededInputs).toEqual({
      entry: "guard",
      source: [{ id: "lore_marek", kind: "lore", title: "Marek Vell" }],
      baseline: "snap_1",
    });
  });

  it("seeds baseline \"\" when the item's source has no snapshot (the whole entry)", async () => {
    const propose = vi.spyOn(todoActions, "proposeFromReviewItem").mockResolvedValue(undefined);
    const item = reviewItem("t1", "guard", "Follow up on Marek Vell's change"); // snapshot_id: ""
    todosStore.set([item]);

    render(ReviewItemsPanel, {
      props: {
        nodeId: "guard",
        nodeTitle: "City Guard",
        subjectEntryType: "lore:character",
        promptEntries: [promptWithChangeInputs(["lore:character"])],
      },
    });

    await fireEvent.click(screen.getByRole("button", { name: /Propose a follow-up/ }));
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Prompt with change inputs" }));

    const [, , seededInputs] = propose.mock.calls[0];
    expect(seededInputs).toEqual({
      entry: "guard",
      source: [{ id: "lore_marek", kind: "lore", title: "Marek Vell" }],
      baseline: "",
    });
  });
});

// ADR-0091 §4: the two-button tile — a primary that opens the default
// straight away, and a second "Other prompts…" button for the rest, once
// something besides the default is offered.
describe("ReviewItemsPanel — the two-button Propose tile (ADR-0091 §4)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    loreEntriesStore.set([
      { id: "lore_marek", title: "Marek Vell", body: "", entry_type: "lore:character", metadata: {} },
    ]);
    metadataSchemaStore.set(SCHEMA);
    openProjectHidden("test-project");
  });
  afterEach(() => {
    // Undo any hide a test above made (localStorage persists across tests in
    // this file), before dropping the current project.
    unhideLibraryEntry("p-follow");
    openProjectHidden(null);
  });

  it("the primary button proposes the built-in default with the same seeded inputs, no popover", async () => {
    const propose = vi.spyOn(todoActions, "proposeFromReviewItem").mockResolvedValue(undefined);
    const item = reviewItem("t1", "guard", "Follow up on Marek Vell's change");
    todosStore.set([item]);

    render(ReviewItemsPanel, {
      props: {
        nodeId: "guard",
        nodeTitle: "City Guard",
        subjectEntryType: "lore:character",
        promptEntries: [reviseEntry(["lore:character"]), followAChange(["lore:character"])],
      },
    });

    const primary = screen.getByRole("button", { name: /Propose a follow-up/ });
    expect(primary).toHaveAttribute("title", "Propose with Follow a change");
    await fireEvent.click(primary);

    expect(propose).toHaveBeenCalledTimes(1);
    const [calledItem, calledPrompt, seededInputs, opts] = propose.mock.calls[0];
    expect(calledItem).toEqual(item);
    expect(calledPrompt).toEqual(expect.objectContaining({ id: "p-follow" }));
    // "Follow a change"'s `entry` is a context_pick, so the seed is the encoded
    // ref shape (seedConversationInputs/seedSubjectEntryInput), not a bare id.
    expect(seededInputs).toEqual({
      entry: [{ id: "guard", kind: "lore", title: "City Guard", entry_type: "lore:character" }],
    });
    expect(opts).toEqual({ subjectTitle: "City Guard" });
    // No menu popover opened by the primary — a direct action, not a picker.
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("an owned Follow a change shadows the Library's as the default", async () => {
    const propose = vi.spyOn(todoActions, "proposeFromReviewItem").mockResolvedValue(undefined);
    todosStore.set([reviewItem("t1", "guard", "Follow up on Marek Vell's change")]);
    const owned = followAChange(["lore:character"], { id: "p-follow-mine", is_library: false });

    render(ReviewItemsPanel, {
      props: {
        nodeId: "guard",
        nodeTitle: "City Guard",
        subjectEntryType: "lore:character",
        promptEntries: [reviseEntry(["lore:character"]), followAChange(["lore:character"]), owned],
      },
    });

    await fireEvent.click(screen.getByRole("button", { name: /Propose a follow-up/ }));
    expect(propose.mock.calls[0][1]).toEqual(expect.objectContaining({ id: "p-follow-mine" }));
  });

  it("hiding the built-in default leaves the menu alone, unchanged from before S3", async () => {
    hideLibraryEntry("p-follow");
    const propose = vi.spyOn(todoActions, "proposeFromReviewItem").mockResolvedValue(undefined);
    todosStore.set([reviewItem("t1", "guard", "Follow up on Marek Vell's change")]);

    render(ReviewItemsPanel, {
      props: {
        nodeId: "guard",
        nodeTitle: "City Guard",
        subjectEntryType: "lore:character",
        promptEntries: [reviseEntry(["lore:character"]), followAChange(["lore:character"])],
      },
    });

    // No primary — the single menu-button tile, exactly as it shipped before S3.
    const button = screen.getByRole("button", { name: /Propose a follow-up/ });
    expect(button).toHaveAttribute("title", "Propose…");
    await fireEvent.click(button);
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Revise entry" }));
    expect(propose.mock.calls[0][1]).toEqual(expect.objectContaining({ id: "p-revise" }));
  });

  it("the Other prompts menu still lists Revise entry, and picking it proposes it", async () => {
    const propose = vi.spyOn(todoActions, "proposeFromReviewItem").mockResolvedValue(undefined);
    todosStore.set([reviewItem("t1", "guard", "Follow up on Marek Vell's change")]);

    render(ReviewItemsPanel, {
      props: {
        nodeId: "guard",
        nodeTitle: "City Guard",
        subjectEntryType: "lore:character",
        promptEntries: [reviseEntry(["lore:character"]), followAChange(["lore:character"])],
      },
    });

    const other = screen.getByRole("button", { name: /Other prompts/ });
    expect(other).toHaveAttribute("title", "Other prompts…");
    await fireEvent.click(other);
    await tick();
    await fireEvent.click(screen.getByRole("menuitem", { name: "Revise entry" }));

    expect(propose).toHaveBeenCalledTimes(1);
    expect(propose.mock.calls[0][1]).toEqual(expect.objectContaining({ id: "p-revise" }));
  });

  it("no second button when the default is the only prompt offered", () => {
    todosStore.set([reviewItem("t1", "guard", "Follow up on Marek Vell's change")]);
    render(ReviewItemsPanel, {
      props: {
        nodeId: "guard",
        nodeTitle: "City Guard",
        subjectEntryType: "lore:character",
        promptEntries: [followAChange(["lore:character"])],
      },
    });
    expect(screen.getByRole("button", { name: /Propose a follow-up/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Other prompts/ })).not.toBeInTheDocument();
  });
});
