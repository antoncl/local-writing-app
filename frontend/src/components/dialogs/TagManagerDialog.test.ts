// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

// The consolidated "Manage tags" home (#247 PR-3b): both vocabularies governed
// from the SAME roster (TagRosterPopover) with no add-target. The dialog is thin
// glue — it reads the two stores and injects each vocabulary's adapter — so this
// covers the wiring (sections, empty states, manager-mode rows, Close). The
// adapters' loadCounts fire on the rosters' mount; stub the two overview reads so
// the test stays hermetic.
vi.mock("@/lib/api", () => ({
  api: {
    getTagsOverview: vi.fn(async () => ({ tags: [] })),
    getAssistantTagsOverview: vi.fn(async () => ({ tags: [] })),
  },
}));

import { knownTagsStore } from "@/lib/stores/tags";
import { assistantTagsStore } from "@/lib/stores/assistantTags";
import TagManagerDialog from "@/components/dialogs/TagManagerDialog.svelte";

beforeEach(() => {
  vi.clearAllMocks();
  knownTagsStore.set([]);
  assistantTagsStore.set([]);
});

describe("TagManagerDialog (Manage tags home)", () => {
  it("shows both vocabulary sections with empty states when nothing is registered", () => {
    render(TagManagerDialog, { props: { onClose: () => {} } });
    expect(screen.getByText("Project tags")).toBeInTheDocument();
    expect(screen.getByText("Assistant tags")).toBeInTheDocument();
    expect(screen.getByText(/No project tags yet/)).toBeInTheDocument();
    expect(screen.getByText(/No assistant tags yet/)).toBeInTheDocument();
  });

  it("governs each vocabulary from its own roster, as static rows (no add-target)", () => {
    knownTagsStore.set([{ name: "canon", scope: { sources: [] } }]);
    assistantTagsStore.set([{ name: "prose", color: null }]);
    render(TagManagerDialog, { props: { onClose: () => {} } });

    // Both tags render, each with its own governance ⋯.
    expect(screen.getByText("canon")).toBeInTheDocument();
    expect(screen.getByText("prose")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Govern canon" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Govern prose" })).toBeInTheDocument();

    // Manager mode: rows are labels, not "Add …" buttons.
    expect(screen.queryByTitle("Add canon")).toBeNull();
    expect(screen.queryByTitle("Add prose")).toBeNull();

    // Two independent filter inputs, one per section.
    expect(screen.getByLabelText("Filter Project tags")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter Assistant tags")).toBeInTheDocument();
  });

  it("closes via the Close button", async () => {
    const onClose = vi.fn();
    render(TagManagerDialog, { props: { onClose } });
    await fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });
});
