// @vitest-environment happy-dom
// #2215: a group member's reference targets / select options, authored in
// the disclosure GroupsManagerDialog mounts under each member row.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";
import GroupMemberTargets from "./GroupMemberTargets.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { GroupMember, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  entry_types: {
    "lore:character": { name: "Character", kind: "lore" },
  },
  fields: {},
} as unknown as MetadataSchema;

afterEach(() => metadataSchemaStore.set(null as unknown as MetadataSchema));

function refMember(overrides: Partial<GroupMember> = {}): GroupMember {
  return { key: "who", name: "Who", type: "entity_ref", ...overrides };
}

describe("GroupMemberTargets — reference member (#2215)", () => {
  it("starts OPEN with the warning summary when unconfigured", () => {
    const { container } = render(GroupMemberTargets, {
      props: { member: refMember(), onPickerConfigChange: vi.fn(), onOptionsChange: vi.fn() },
    });
    const details = container.querySelector("details")!;
    expect(details.open).toBe(true);
    expect(details.className).toContain("warn");
    expect(screen.getByText("Points at nothing yet")).toBeTruthy();
  });

  it("picking a type via NodePickerConfigEditor updates the summary and emits picker_config", async () => {
    metadataSchemaStore.set(SCHEMA);
    const onPickerConfigChange = vi.fn();
    // Start from an explicitly EMPTY config (not the null/undefined default,
    // which the editor seeds to "lore" and would already show Character
    // checked) so the click below is a genuine off→on pick.
    const { container, rerender } = render(GroupMemberTargets, {
      props: {
        member: refMember({ picker_config: { sources: [] } }),
        onPickerConfigChange,
        onOptionsChange: vi.fn(),
      },
    });
    await fireEvent.click(screen.getByRole("button", { name: /Character/ }));
    expect(onPickerConfigChange).toHaveBeenCalledOnce();
    const config = onPickerConfigChange.mock.calls[0][0];
    expect(config.sources).toEqual([{ kind: "lore", expr: { type: "lore:character" } }]);

    // Re-render with the picked config: the summary now names the type, no
    // longer the warning tint.
    await rerender({ member: refMember({ picker_config: config }), onPickerConfigChange, onOptionsChange: vi.fn() });
    expect(container.querySelector("summary")?.textContent).toContain("Points at");
    expect(container.querySelector("summary")?.textContent).toContain("Character");
    expect(screen.queryByText("Points at nothing yet")).toBeNull();
  });

  it("starts CLOSED once a source is picked", () => {
    const { container } = render(GroupMemberTargets, {
      props: {
        member: refMember({ picker_config: { sources: [{ kind: "lore" }] } }),
        onPickerConfigChange: vi.fn(),
        onOptionsChange: vi.fn(),
      },
    });
    expect(container.querySelector("details")!.open).toBe(false);
  });
});

describe("GroupMemberTargets — select member (#2215)", () => {
  it("adds a blank option row and emits it via onOptionsChange", async () => {
    const onOptionsChange = vi.fn();
    render(GroupMemberTargets, {
      props: {
        member: { key: "kind", name: "Kind", type: "select" },
        onPickerConfigChange: vi.fn(),
        onOptionsChange,
      },
    });
    expect(screen.getByText("No options yet")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Add option" }));
    expect(onOptionsChange).toHaveBeenCalledWith([{ value: "" }]);
  });

  it("emits an edited option value (SelectOptionsEditor is controlled by `member.options`)", async () => {
    const onOptionsChange = vi.fn();
    render(GroupMemberTargets, {
      props: {
        member: { key: "kind", name: "Kind", type: "select", options: [{ value: "" }] },
        onPickerConfigChange: vi.fn(),
        onOptionsChange,
      },
    });
    const valueInput = screen.getByPlaceholderText("value");
    await fireEvent.input(valueInput, { target: { value: "ally" } });
    expect(onOptionsChange).toHaveBeenCalledWith([{ value: "ally" }]);
  });

  it("shows a joined summary once options exist", () => {
    render(GroupMemberTargets, {
      props: {
        member: {
          key: "kind",
          name: "Kind",
          type: "select",
          options: [{ value: "ally" }, { value: "rival" }],
        },
        onPickerConfigChange: vi.fn(),
        onOptionsChange: vi.fn(),
      },
    });
    expect(screen.getByText("ally · rival")).toBeTruthy();
  });
});

describe("GroupMemberTargets — other member types (#2215)", () => {
  it("renders nothing for a text member", () => {
    const { container } = render(GroupMemberTargets, {
      props: { member: { key: "name", name: "Name", type: "text" }, onPickerConfigChange: vi.fn(), onOptionsChange: vi.fn() },
    });
    expect(container.querySelector("details")).toBeNull();
  });
});
