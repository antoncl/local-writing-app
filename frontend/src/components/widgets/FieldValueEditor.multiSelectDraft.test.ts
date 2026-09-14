// @vitest-environment happy-dom
// #1951 — an option-less `multi_select` (e.g. the built-in Aliases) is edited
// through a bare comma `<input>`. `emit` reformats the value on every keystroke
// (split on commas -> de-dupe -> re-join with ", "), so binding the input
// straight to the re-derived value rewrote its own text mid-typing ("a,b" ->
// "a, b") and browsers bounce the caret to the end whenever a controlled
// input's value is rewritten. The input now shows a caret-preserving DRAFT: the
// user's own text verbatim while typing, adopting the derived value only on an
// EXTERNAL change. happy-dom can't observe the caret, so these tests lock the
// mechanism that caused the jump — the raw text survives the round-trip instead
// of being reformatted back onto the input.
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@/lib/test/component";
import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
import type { MetadataFieldDefinition, MetadataValue } from "@/lib/types";

const aliases = { name: "Aliases", type: "multi_select", options: [] } as unknown as MetadataFieldDefinition;

function mount(value: MetadataValue) {
  const onChange = vi.fn();
  const { container, rerender } = render(FieldValueEditor, {
    props: { field: aliases, value, onChange },
  });
  const input = container.querySelector("input") as HTMLInputElement;
  // Mirror the real parent (MetadataPanel): apply the emitted value back.
  const apply = (next: MetadataValue) => rerender({ field: aliases, value: next, onChange });
  return { input, onChange, apply };
}

describe("FieldValueEditor — option-less multi_select keeps a caret-preserving draft (#1951)", () => {
  it("emits the normalized array but keeps the raw typed text on the input through the round-trip", async () => {
    const { input, onChange, apply } = mount(["Alpha"]);
    expect(input.value).toBe("Alpha");

    // Type a comma-list WITHOUT the canonical ", " spacing.
    await fireEvent.input(input, { target: { value: "Alpha,Beta" } });
    // The store gets the normalized (space-joined, de-duped) list …
    expect(onChange).toHaveBeenLastCalledWith(["Alpha", "Beta"]);

    // … the parent applies it back, and the input STILL shows exactly what was
    // typed — not the reformatted "Alpha, Beta" whose rewrite reset the caret.
    await apply(["Alpha", "Beta"]);
    expect(input.value).toBe("Alpha,Beta");
  });

  it("keeps the raw text when normalize REFORMATS the value (a case-duplicate is de-duped)", async () => {
    // Typing a case-duplicate de-dupes on the way to the store ("Alpha,alpha" ->
    // ["Alpha"]), so the derived string genuinely CHANGES ("" -> "Alpha"). That
    // is the reformat class that, on the old binding, rewrote the box (dropping
    // the "alpha" mid-type) and reset the caret; the draft keeps it verbatim.
    const { input, onChange, apply } = mount([]);
    await fireEvent.input(input, { target: { value: "Alpha,alpha" } });
    expect(onChange).toHaveBeenLastCalledWith(["Alpha"]);
    await apply(["Alpha"]);
    expect(input.value).toBe("Alpha,alpha");
  });

  it("adopts the derived value on an EXTERNAL change (a reset, or a parent switching the value)", async () => {
    const { input, apply } = mount(["Alpha"]);
    await fireEvent.input(input, { target: { value: "Alpha,Beta" } });
    await apply(["Gamma"]); // an external change, not from our keystroke
    expect(input.value).toBe("Gamma");
  });

  it("a plain text field is unaffected (no reformat) — the draft is a no-op", async () => {
    const onChange = vi.fn();
    const textField = { name: "Epithet", type: "text" } as unknown as MetadataFieldDefinition;
    const { container, rerender } = render(FieldValueEditor, {
      props: { field: textField, value: "The", onChange },
    });
    const input = container.querySelector("input") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "The Painted" } });
    expect(onChange).toHaveBeenLastCalledWith("The Painted");
    await rerender({ field: textField, value: "The Painted", onChange });
    expect(input.value).toBe("The Painted");
  });
});
