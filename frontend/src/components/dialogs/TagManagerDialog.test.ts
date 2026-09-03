// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

// The "Manage tags" home (#247 PR-3b) — PROJECT tags governed from the
// TagRosterPopover roster with no add-target. The assistant half retired
// (ADR-0082 slice 2b): the assistant vocabulary is now `tag:assistant_tag`
// nodes, governed like any other tag node, not this legacy dialog. The
// adapter's loadCounts fires on the roster's mount; stub the overview read
// so the test stays hermetic.
vi.mock("@/lib/api", () => ({
  api: {
    getTagsOverview: vi.fn(async () => ({ tags: [] })),
  },
}));

import { knownTagsStore } from "@/lib/stores/tags";
import TagManagerDialog from "@/components/dialogs/TagManagerDialog.svelte";

beforeEach(() => {
  vi.clearAllMocks();
  knownTagsStore.set([]);
});

describe("TagManagerDialog (Manage tags home)", () => {
  it("shows the project section with an empty state when nothing is registered", () => {
    render(TagManagerDialog, { props: { onClose: () => {} } });
    expect(screen.getByText("Project tags")).toBeInTheDocument();
    expect(screen.getByText(/No project tags yet/)).toBeInTheDocument();
    expect(screen.queryByText("Assistant tags")).toBeNull();
  });

  it("governs the project vocabulary from its roster, as static rows (no add-target)", () => {
    knownTagsStore.set([{ name: "canon", scope: { sources: [] } }]);
    render(TagManagerDialog, { props: { onClose: () => {} } });

    expect(screen.getByText("canon")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Govern canon" })).toBeInTheDocument();

    // Manager mode: the row is a label, not an "Add …" button.
    expect(screen.queryByTitle("Add canon")).toBeNull();

    expect(screen.getByLabelText("Filter Project")).toBeInTheDocument();
  });

  it("closes via the Close button", async () => {
    const onClose = vi.fn();
    render(TagManagerDialog, { props: { onClose } });
    await fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });
});
