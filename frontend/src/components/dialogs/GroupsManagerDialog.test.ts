// @vitest-environment happy-dom
// Reusable-group manager, #1003:
//   - built-in `system` groups (plot-board machinery) stay out of the list;
//   - creating a new group whose id collides with an existing one — including a
//     HIDDEN system group — is blocked before it can shadow the built-in.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import type { MetadataGroupDefinition } from "@/lib/types";
import GroupsManagerDialog from "./GroupsManagerDialog.svelte";

const upsertMetadataGroup = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    upsertMetadataGroup: (...args: unknown[]) => upsertMetadataGroup(...args),
    deleteMetadataGroup: vi.fn(),
  },
}));

const GROUPS: Record<string, MetadataGroupDefinition> = {
  gmo: { name: "GMO", members: [{ key: "goal", name: "Goal", type: "text" }] },
  plot_beat_link: {
    name: "Beat link",
    system: true,
    members: [{ key: "plotline", name: "Plotline", type: "text" }],
  },
};

function mount() {
  render(GroupsManagerDialog, {
    props: { groups: GROUPS, layerId: "proj", onChanged: vi.fn(), onClose: vi.fn() },
  });
}

beforeEach(() => upsertMetadataGroup.mockReset());

describe("GroupsManagerDialog (#1003)", () => {
  it("hides built-in system groups from the list", () => {
    mount();
    expect(screen.getByText("GMO")).toBeTruthy();
    expect(screen.queryByText("Beat link")).toBeNull();
  });

  it("blocks a new group whose id collides with a hidden system group", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("New group"));
    // Type an id that collides with the hidden `plot_beat_link` system group.
    await fireEvent.input(screen.getByLabelText("Id"), { target: { value: "plot_beat_link" } });
    await fireEvent.click(screen.getByText("Save group"));
    expect(screen.getByText(/already exists/i)).toBeTruthy();
    expect(upsertMetadataGroup).not.toHaveBeenCalled();
  });

  it("saves a new group whose id is free", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("New group"));
    await fireEvent.input(screen.getByLabelText("Id"), { target: { value: "stakes" } });
    await fireEvent.click(screen.getByText("Save group"));
    expect(upsertMetadataGroup).toHaveBeenCalledOnce();
    expect(upsertMetadataGroup.mock.calls[0][1]).toBe("stakes");
  });
});
