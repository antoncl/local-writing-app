// @vitest-environment happy-dom
// ItemDetailSegments (ADR-0089 Amendment 2, #2221) — the detail-line segment
// editor in isolation. ReferenceListTab.test.ts pins the end-to-end wiring
// (text/select segments through the real tab, the new-item autofocus, the
// scrubbed read-only case); this file covers the segment widget's own rules
// that don't need a whole tab: the empty placeholder, number coercion, a
// non-editable render, and a `multi_select` popover staying open across
// multiple picks.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@/lib/test/component";
import ItemDetailSegments from "./ItemDetailSegments.svelte";
import type { GroupMember } from "@/lib/schemaTypes";

const DEPS = { loreEntries: [], promptEntries: [], structure: null, researchStructure: null };

function baseProps(over: Record<string, unknown> = {}) {
  return {
    members: [
      { key: "kind", name: "Kind", type: "text" },
      { key: "count", name: "Count", type: "number" },
    ] as GroupMember[],
    record: { kind: "kinship", count: 3 },
    editable: true,
    editingKey: null,
    deps: DEPS,
    onEditStart: vi.fn(),
    onEditEnd: vi.fn(),
    onCommit: vi.fn(),
    ...over,
  };
}

describe("ItemDetailSegments", () => {
  it("renders each member's value, separated by · ", () => {
    render(ItemDetailSegments, { props: baseProps() });
    expect(screen.getByText("kinship")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("an empty member shows its own name, muted", () => {
    render(ItemDetailSegments, { props: baseProps({ record: { kind: "", count: null } }) });
    expect(screen.getByText("Kind")).toHaveClass("idl-empty");
    expect(screen.getByText("Count")).toHaveClass("idl-empty");
  });

  it("not editable renders plain (non-button) segments", () => {
    const { container } = render(ItemDetailSegments, { props: baseProps({ editable: false }) });
    expect(container.querySelector("button.idl-seg")).toBeNull();
    expect(screen.getByText("kinship").tagName).toBe("SPAN");
  });

  it("clicking a number segment opens an input seeded with the value; typing a blank commits null", async () => {
    const onCommit = vi.fn();
    const onEditStart = vi.fn();
    const { rerender } = render(ItemDetailSegments, { props: baseProps({ onCommit, onEditStart }) });
    await fireEvent.click(screen.getByText("3"));
    expect(onEditStart).toHaveBeenCalledWith("count");
    await rerender(baseProps({ onCommit, onEditStart, editingKey: "count" }));
    const input = screen.getByDisplayValue("3") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommit).toHaveBeenCalledWith("count", null);
  });

  it("a multi_select popover stays open across more than one pick", async () => {
    const onCommit = vi.fn();
    const onEditEnd = vi.fn();
    const multiMembers: GroupMember[] = [
      { key: "tags", name: "Tags", type: "multi_select", options: [{ value: "a", label: "A" }, { value: "b", label: "B" }] },
    ];
    const { rerender } = render(ItemDetailSegments, {
      props: baseProps({ members: multiMembers, record: { tags: [] }, onCommit, onEditEnd, editingKey: null }),
    });
    await fireEvent.click(screen.getByText("Tags"));
    await rerender(baseProps({ members: multiMembers, record: { tags: [] }, onCommit, onEditEnd, editingKey: "tags" }));
    const popover = document.querySelector(".idl-popover") as HTMLElement;
    await fireEvent.click(within(popover).getByText("A"));
    expect(onCommit).toHaveBeenCalledWith("tags", ["a"]);
    expect(onEditEnd).not.toHaveBeenCalled(); // continuous type: stays open for a second pick
  });
});
