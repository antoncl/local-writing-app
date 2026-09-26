// @vitest-environment happy-dom
// Reusable-group manager, #1003:
//   - built-in `system` groups (plot-board machinery) stay out of the list;
//   - creating a new group whose id collides with an existing one — including a
//     HIDDEN system group — is blocked before it can shadow the built-in.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataGroupDefinition, MetadataSchema } from "@/lib/types";
import GroupsManagerDialog from "./GroupsManagerDialog.svelte";

const upsertMetadataGroup = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    upsertMetadataGroup: (...args: unknown[]) => upsertMetadataGroup(...args),
    deleteMetadataGroup: vi.fn(),
  },
}));

const confirmRequest = vi.fn();
vi.mock("@/lib/stores/confirmService.svelte", () => ({
  confirmService: { request: (...args: unknown[]) => confirmRequest(...args) },
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

beforeEach(() => {
  upsertMetadataGroup.mockReset();
  confirmRequest.mockReset();
});

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

  // #2214: the GMO/Goal development-example copy is gone — generic placeholders.
  it("uses generic placeholders instead of the GMO/Goal example (#2214)", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("New group"));
    expect(screen.getByPlaceholderText("Group name")).toBeTruthy();
    expect(screen.getByPlaceholderText("group_id")).toBeTruthy();
    await fireEvent.click(screen.getByLabelText("Add member"));
    expect(screen.getByPlaceholderText("Member name")).toBeTruthy();
  });

  it("empty state reads generically, not GMO-specific (#2214)", () => {
    render(GroupsManagerDialog, {
      props: { groups: {}, layerId: "proj", onChanged: vi.fn(), onClose: vi.fn() },
    });
    expect(
      screen.getByText(
        "No reusable groups yet. A group is a set of fields defined once and reused as a whole on several types.",
      ),
    ).toBeTruthy();
  });
});

// #2215: a Reference/Select member's targets/options disclosure, and the
// save-time cleanup of a now-irrelevant setting after a type change.
describe("GroupsManagerDialog — member targets disclosure (#2215)", () => {
  it("shows the disclosure under a Reference member, warning when unconfigured", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("New group"));
    await fireEvent.input(screen.getByLabelText("Id"), { target: { value: "connections" } });
    await fireEvent.click(screen.getByLabelText("Add member"));
    const typeSelect = screen.getByDisplayValue("Text") as HTMLSelectElement;
    await fireEvent.change(typeSelect, { target: { value: "entity_ref" } });
    expect(screen.getByText("Points at nothing yet")).toBeTruthy();
  });

  it("shows the disclosure under a Select member reading 'No options yet'", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("New group"));
    await fireEvent.click(screen.getByLabelText("Add member"));
    const typeSelect = screen.getByDisplayValue("Text") as HTMLSelectElement;
    await fireEvent.change(typeSelect, { target: { value: "select" } });
    expect(screen.getByText("No options yet")).toBeTruthy();
  });

  it("clears a stale picker_config on save when the type changes away from reference", async () => {
    render(GroupsManagerDialog, {
      props: {
        groups: {
          connections: {
            name: "Connections",
            members: [
              {
                key: "who",
                name: "Who",
                type: "entity_ref",
                picker_config: { sources: [{ kind: "lore" }] },
              },
            ],
          },
        },
        layerId: "proj",
        onChanged: vi.fn(),
        onClose: vi.fn(),
      },
    });
    await fireEvent.click(screen.getByText("Connections"));
    const typeSelect = screen.getByDisplayValue("Reference") as HTMLSelectElement;
    await fireEvent.change(typeSelect, { target: { value: "text" } });
    await fireEvent.click(screen.getByText("Save group"));
    expect(upsertMetadataGroup).toHaveBeenCalledOnce();
    const saved = upsertMetadataGroup.mock.calls[0][2];
    expect(saved.members[0].picker_config).toBeUndefined();
  });

  it("clears stale options on save when the type changes away from select", async () => {
    render(GroupsManagerDialog, {
      props: {
        groups: {
          connections: {
            name: "Connections",
            members: [
              { key: "kind", name: "Kind", type: "select", options: [{ value: "ally" }] },
            ],
          },
        },
        layerId: "proj",
        onChanged: vi.fn(),
        onClose: vi.fn(),
      },
    });
    await fireEvent.click(screen.getByText("Connections"));
    const typeSelect = screen.getByDisplayValue("Select") as HTMLSelectElement;
    await fireEvent.change(typeSelect, { target: { value: "text" } });
    await fireEvent.click(screen.getByText("Save group"));
    const saved = upsertMetadataGroup.mock.calls[0][2];
    expect(saved.members[0].options).toBeUndefined();
  });

  it("persists a picked picker_config in the save payload", async () => {
    metadataSchemaStore.set({
      entry_types: { "lore:character": { name: "Character", kind: "lore" } },
      fields: {},
    } as unknown as MetadataSchema);
    // Seed the group with a reference member whose config already names NO
    // source, so the click below is a genuine off→on pick (a brand-new
    // member's editor defaults to "lore" pre-checked, ADR-0074's kind-only
    // fallback — clicking it there would toggle it back OFF instead).
    render(GroupsManagerDialog, {
      props: {
        groups: {
          connections: {
            name: "Connections",
            members: [
              { key: "who", name: "Who", type: "entity_ref", picker_config: { sources: [] } },
            ],
          },
        },
        layerId: "proj",
        onChanged: vi.fn(),
        onClose: vi.fn(),
      },
    });
    await fireEvent.click(screen.getByText("Connections"));
    // Pick "Character" via the disclosure's embedded NodePickerConfigEditor —
    // the same tree the schema field editor uses.
    await fireEvent.click(screen.getByRole("button", { name: /Character/ }));
    await fireEvent.click(screen.getByText("Save group"));
    expect(upsertMetadataGroup).toHaveBeenCalledOnce();
    const saved = upsertMetadataGroup.mock.calls[0][2];
    expect(saved.members[0].picker_config.sources).toEqual([{ kind: "lore", expr: { type: "lore:character" } }]);
    metadataSchemaStore.set(null as unknown as MetadataSchema);
  });
});

// #2239 follow-up: a member's key is stable once saved (same rule as a node
// id) — retyping its NAME must never silently re-key stored items/rows. An
// option value follows the same rule. Removing a member/option that carries
// data is confirmed, not silent.
describe("GroupsManagerDialog — member key stability (#2239)", () => {
  const CONNECTIONS: Record<string, MetadataGroupDefinition> = {
    connections: {
      name: "Connections",
      members: [
        { key: "who", name: "Who", type: "entity_ref" },
        { key: "state", name: "State", type: "select", options: [{ value: "trusted" }, { value: "wary" }] },
      ],
    },
  };

  function mountConnections() {
    render(GroupsManagerDialog, {
      props: { groups: CONNECTIONS, layerId: "proj", onChanged: vi.fn(), onClose: vi.fn() },
    });
  }

  it("keeps an existing member's key when its name is retyped", async () => {
    mountConnections();
    await fireEvent.click(screen.getByText("Connections"));
    const nameInputs = screen.getAllByPlaceholderText("Member name") as HTMLInputElement[];
    await fireEvent.input(nameInputs[1], { target: { value: "Standing" } });
    await fireEvent.click(screen.getByText("Save group"));
    expect(upsertMetadataGroup).toHaveBeenCalledOnce();
    const saved = upsertMetadataGroup.mock.calls[0][2] as MetadataGroupDefinition;
    const renamed = saved.members.find((m) => m.name === "Standing");
    expect(renamed?.key).toBe("state");
  });

  it("still derives a key from the name for a brand-new member", async () => {
    mountConnections();
    await fireEvent.click(screen.getByText("Connections"));
    await fireEvent.click(screen.getByLabelText("Add member"));
    const nameInputs = screen.getAllByPlaceholderText("Member name") as HTMLInputElement[];
    await fireEvent.input(nameInputs[nameInputs.length - 1], { target: { value: "Notes" } });
    await fireEvent.click(screen.getByText("Save group"));
    const saved = upsertMetadataGroup.mock.calls[0][2] as MetadataGroupDefinition;
    const added = saved.members.find((m) => m.name === "Notes");
    expect(added?.key).toBe("notes");
  });

  it("a new member's key keeps following its name even when it passes an existing key", async () => {
    mountConnections();
    await fireEvent.click(screen.getByText("Connections"));
    await fireEvent.click(screen.getByLabelText("Add member"));
    const nameInputs = screen.getAllByPlaceholderText("Member name") as HTMLInputElement[];
    const input = nameInputs[nameInputs.length - 1];
    // Typed one keystroke at a time: "State" slugs to the existing key "state"
    // on the way to "Statement".
    for (const value of ["S", "St", "Sta", "Stat", "State", "Statem", "Stateme", "Statemen", "Statement"]) {
      await fireEvent.input(input, { target: { value } });
    }
    await fireEvent.click(screen.getByText("Save group"));
    const saved = upsertMetadataGroup.mock.calls[0][2] as MetadataGroupDefinition;
    const added = saved.members.find((m) => m.name === "Statement");
    expect(added?.key).toBe("statement");
    // The existing member keeps its own key, so no two members share one.
    expect(saved.members.filter((m) => m.key === "state")).toHaveLength(1);
  });

  it("confirms before a save that removes a member", async () => {
    mountConnections();
    await fireEvent.click(screen.getByText("Connections"));
    const removeButtons = screen.getAllByLabelText("Remove member");
    await fireEvent.click(removeButtons[0]);
    await fireEvent.click(screen.getByText("Save group"));
    expect(confirmRequest).toHaveBeenCalledOnce();
    expect(confirmRequest.mock.calls[0][0].message).toMatch(/Removing Who deletes/);
    expect(upsertMetadataGroup).not.toHaveBeenCalled();

    await confirmRequest.mock.calls[0][0].onConfirm();
    expect(upsertMetadataGroup).toHaveBeenCalledOnce();
  });

  it("confirms before a save that removes an option value", async () => {
    mountConnections();
    await fireEvent.click(screen.getByText("Connections"));
    await fireEvent.click(screen.getByText(/Options/));
    const valueInputs = screen.getAllByLabelText("Option value") as HTMLInputElement[];
    // Remove the second option ("wary") via its row's remove button.
    const removeButtons = screen.getAllByLabelText("Remove option");
    await fireEvent.click(removeButtons[removeButtons.length - 1]);
    await fireEvent.click(screen.getByText("Save group"));
    expect(confirmRequest).toHaveBeenCalledOnce();
    expect(confirmRequest.mock.calls[0][0].message).toMatch(/State \(wary\)/);
    expect(valueInputs.length).toBeGreaterThan(0); // sanity: options rendered before removal
  });

  it("saves without confirming when nothing is removed (a pure relabel)", async () => {
    mountConnections();
    await fireEvent.click(screen.getByText("Connections"));
    const nameInputs = screen.getAllByPlaceholderText("Member name") as HTMLInputElement[];
    await fireEvent.input(nameInputs[0], { target: { value: "Contact" } });
    await fireEvent.click(screen.getByText("Save group"));
    expect(confirmRequest).not.toHaveBeenCalled();
    expect(upsertMetadataGroup).toHaveBeenCalledOnce();
  });
});

// ADR-0096 §1: the identity choice — none, or one of the group's own `text`
// members — saved as `identity` alongside `name`/`members`.
describe("GroupsManagerDialog — identity choice (ADR-0096 §1)", () => {
  const BEATS: Record<string, MetadataGroupDefinition> = {
    plot_beat: {
      name: "Beat",
      identity: "id",
      members: [
        { key: "title", name: "Title", type: "text" },
        { key: "id", name: "Id", type: "text" },
      ],
    },
  };

  it("saves null identity by default for a new group", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("New group"));
    await fireEvent.input(screen.getByLabelText("Id"), { target: { value: "stakes" } });
    await fireEvent.click(screen.getByText("Save group"));
    const saved = upsertMetadataGroup.mock.calls[0][2] as MetadataGroupDefinition;
    expect(saved.identity).toBeNull();
  });

  it("loads and re-saves an existing group's declared identity", async () => {
    render(GroupsManagerDialog, {
      props: { groups: BEATS, layerId: "proj", onChanged: vi.fn(), onClose: vi.fn() },
    });
    await fireEvent.click(screen.getByText("Beat"));
    expect((screen.getByLabelText("Identity") as HTMLSelectElement).value).toBe("id");
    await fireEvent.click(screen.getByText("Save group"));
    const saved = upsertMetadataGroup.mock.calls[0][2] as MetadataGroupDefinition;
    expect(saved.identity).toBe("id");
  });

  it("picking a text member as identity saves its key", async () => {
    mount();
    await fireEvent.click(screen.getByLabelText("New group"));
    await fireEvent.input(screen.getByLabelText("Id"), { target: { value: "stakes" } });
    await fireEvent.click(screen.getByLabelText("Add member"));
    const nameInputs = screen.getAllByPlaceholderText("Member name") as HTMLInputElement[];
    await fireEvent.input(nameInputs[0], { target: { value: "Stakes" } });
    await fireEvent.change(screen.getByLabelText("Identity"), { target: { value: "stakes" } });
    await fireEvent.click(screen.getByText("Save group"));
    const saved = upsertMetadataGroup.mock.calls[0][2] as MetadataGroupDefinition;
    expect(saved.identity).toBe("stakes");
  });

  it("resets to None when the identity member is removed", async () => {
    render(GroupsManagerDialog, {
      props: { groups: BEATS, layerId: "proj", onChanged: vi.fn(), onClose: vi.fn() },
    });
    await fireEvent.click(screen.getByText("Beat"));
    const removeButtons = screen.getAllByLabelText("Remove member");
    await fireEvent.click(removeButtons[1]); // removes "Id"
    // Data-loss confirm fires (the identity member disappears entirely) — confirm it.
    await fireEvent.click(screen.getByText("Save group"));
    await confirmRequest.mock.calls[0][0].onConfirm();
    const saved = upsertMetadataGroup.mock.calls[0][2] as MetadataGroupDefinition;
    expect(saved.identity).toBeNull();
  });

  it("resets to None when the identity member is retyped away from text", async () => {
    render(GroupsManagerDialog, {
      props: { groups: BEATS, layerId: "proj", onChanged: vi.fn(), onClose: vi.fn() },
    });
    await fireEvent.click(screen.getByText("Beat"));
    const typeSelects = screen.getAllByDisplayValue("Text") as HTMLSelectElement[];
    // The second Text member is "Id" (index 1: Title, Id).
    await fireEvent.change(typeSelects[1], { target: { value: "number" } });
    await fireEvent.click(screen.getByText("Save group"));
    const saved = upsertMetadataGroup.mock.calls[0][2] as MetadataGroupDefinition;
    expect(saved.identity).toBeNull();
  });
});
