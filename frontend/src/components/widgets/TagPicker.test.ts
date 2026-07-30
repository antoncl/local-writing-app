// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import TagPicker from "@/components/widgets/TagPicker.svelte";

// #247: the field crystallises typed text into chips on comma / Enter / blur,
// removes via the tip ×, and marks a tag not in the vocabulary as pending
// ("will be created on save"). The committed value stays a comma-joined string
// (the wire contract the parent FieldValueEditor round-trips).
const known = [
  { name: "alpha", scope: { sources: [] } },
  { name: "shifter", scope: { sources: [] } },
];

function setup(props: Record<string, unknown> = {}) {
  const onChange = vi.fn<(v: string) => void>();
  const r = render(TagPicker, {
    props: { value: "alpha", knownTags: known, ariaLabel: "Tags", onChange, ...props },
  });
  const input = screen.getByLabelText("Tags") as HTMLInputElement;
  return { ...r, onChange, input };
}

describe("TagPicker", () => {
  it("renders one chip per committed tag", () => {
    setup({ value: "alpha, shifter" });
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("shifter")).toBeInTheDocument();
  });

  it("marks an unknown tag as pending and leaves a known one solid", () => {
    const { container } = setup({ value: "alpha, feral" });
    const pending = container.querySelectorAll(".tag-chip.pending");
    expect(pending).toHaveLength(1);
    expect(pending[0]).toHaveTextContent("feral");
    // "alpha" is in the vocabulary → not pending.
    expect(container.querySelector(".tag-chip:not(.pending)")).toHaveTextContent("alpha");
  });

  it("crystallises typed text into a chip on Enter", async () => {
    const { onChange, input } = setup({ value: "alpha" });
    await fireEvent.input(input, { target: { value: "feral" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith("alpha, feral");
  });

  it("crystallises on a comma too", async () => {
    const { onChange, input } = setup({ value: "alpha" });
    await fireEvent.input(input, { target: { value: "lunar" } });
    await fireEvent.keyDown(input, { key: "," });
    expect(onChange).toHaveBeenLastCalledWith("alpha, lunar");
  });

  it("crystallises leftover text when the field loses focus", async () => {
    const { onChange, input } = setup({ value: "alpha" });
    await fireEvent.input(input, { target: { value: "feral" } });
    await fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith("alpha, feral");
  });

  it("does not re-emit when every typed token is already present (case-insensitive)", async () => {
    const { onChange, input } = setup({ value: "alpha" });
    await fireEvent.input(input, { target: { value: "Alpha" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    // A pure duplicate is a no-op: no chip added, no redundant autosave.
    expect(onChange).not.toHaveBeenCalled();
  });

  it("renders a duplicated stored value as a single chip without crashing", () => {
    // Exact dups can arrive from hand-edited YAML / an importer; a keyed {#each}
    // would throw each_key_duplicate if they reached it.
    const { container } = setup({ value: "a, a", knownTags: [] });
    expect(container.querySelectorAll(".tag-chip")).toHaveLength(1);
  });

  it("clears the pending style when the roster later includes the tag (reactive)", async () => {
    const props = { value: "feral", ariaLabel: "Tags", onChange: () => {} };
    const { container, rerender } = render(TagPicker, { props: { ...props, knownTags: [] } });
    expect(container.querySelector(".tag-chip.pending")).not.toBeNull();
    await rerender({ ...props, knownTags: [{ name: "feral", scope: { sources: [] } }] });
    expect(container.querySelector(".tag-chip.pending")).toBeNull();
  });

  it("removes a tag from its tip ×", async () => {
    const { onChange } = setup({ value: "alpha, shifter" });
    await fireEvent.click(screen.getByRole("button", { name: /Remove alpha/ }));
    expect(onChange).toHaveBeenLastCalledWith("shifter");
  });

  it("removes the last chip on backspace in an empty input", async () => {
    const { onChange, input } = setup({ value: "alpha, shifter" });
    await fireEvent.keyDown(input, { key: "Backspace" });
    expect(onChange).toHaveBeenLastCalledWith("alpha");
  });
});
