// @vitest-environment happy-dom
// PromptInputField had no test. The #49 runes port turns its `change`
// CustomEvent into an `onChange(value)` callback prop. These lock the callback
// for the native-input branches (text / number / select / boolean) — the ones
// that render plain DOM controls and so are happy-dom-mountable. The picker
// branches (ReferencePicker / NodePicker / PlainTextEditor) still dispatch and
// are covered by their own slices / the real-browser pass (#642).
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PromptInputField from "./PromptInputField.svelte";
import type { PromptInputDefinition } from "@/lib/types";

function def(over: Partial<PromptInputDefinition> = {}): PromptInputDefinition {
  return { type: "text", name: "q", label: "Question", ...over } as unknown as PromptInputDefinition;
}

describe("PromptInputField — onChange callback (runes port of the `change` event)", () => {
  it("text input reports the typed value", async () => {
    const onChange = vi.fn();
    render(PromptInputField, { props: { input: def(), value: "", onChange } });
    await fireEvent.input(screen.getByRole("textbox"), { target: { value: "hello" } });
    expect(onChange).toHaveBeenLastCalledWith("hello");
  });

  it("number input reports the raw string value", async () => {
    const onChange = vi.fn();
    render(PromptInputField, { props: { input: def({ type: "number" }), value: "", onChange } });
    await fireEvent.input(screen.getByRole("spinbutton"), { target: { value: "42" } });
    expect(onChange).toHaveBeenLastCalledWith("42");
  });

  it("select reports the chosen option", async () => {
    const onChange = vi.fn();
    const input = def({
      type: "select",
      options: [
        { value: "a", label: "A" },
        { value: "b", label: "B" },
      ],
    });
    render(PromptInputField, { props: { input, value: "", onChange } });
    await fireEvent.change(screen.getByRole("combobox"), { target: { value: "b" } });
    expect(onChange).toHaveBeenLastCalledWith("b");
  });

  it("boolean tri-state reports 'true' / 'false' / '' verbatim", async () => {
    const onChange = vi.fn();
    render(PromptInputField, { props: { input: def({ type: "boolean" }), value: "", onChange } });
    const select = screen.getByRole("combobox");
    await fireEvent.change(select, { target: { value: "true" } });
    expect(onChange).toHaveBeenLastCalledWith("true");
    await fireEvent.change(select, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith("");
  });
});

describe("PromptInputField — shared value types delegate to FieldValueEditor (#1225)", () => {
  it("multi_select renders option chips and encodes the selection as a JSON array", async () => {
    const onChange = vi.fn();
    const input = def({
      type: "multi_select",
      name: "senses",
      label: "Senses",
      options: [
        { value: "sight", label: "Sight" },
        { value: "sound", label: "Sound" },
      ],
    });
    render(PromptInputField, { props: { input, value: "[]", onChange } });
    // The FieldValueEditor chip widget renders one toggle per option.
    await fireEvent.click(screen.getByRole("button", { name: "Sight" }));
    // Wire form is the JSON array the backend coercer expects — not "Sight".
    expect(onChange).toHaveBeenLastCalledWith(JSON.stringify(["sight"]));
  });

  it("multi_select shows a scalar default (stored bare, not JSON) as the active selection", async () => {
    const onChange = vi.fn();
    const input = def({
      type: "multi_select",
      name: "senses",
      options: [
        { value: "sight", label: "Sight" },
        { value: "sound", label: "Sound" },
      ],
    });
    // The author's default is stored as the bare value "sight" and seeded via
    // String() — the widget must still render it selected, not drop it.
    render(PromptInputField, { props: { input, value: "sight", onChange } });
    await fireEvent.click(screen.getByRole("button", { name: "Sight" }));
    // Toggling the (correctly selected) chip clears it → empty array.
    expect(onChange).toHaveBeenLastCalledWith(JSON.stringify([]));
  });

  it("list renders one scalar item input per value plus the add control (synthesized scalar shape)", () => {
    const input = def({ type: "list", name: "beats", label: "Beats" });
    render(PromptInputField, {
      props: { input, value: JSON.stringify(["escape", "betrayal"]), onChange: vi.fn() },
    });
    // The synthesized one-member scalar list drives ListValueEditor: a text input
    // per item, plus the "+ Add item" row.
    expect(screen.getByDisplayValue("escape")).toBeInTheDocument();
    expect(screen.getByDisplayValue("betrayal")).toBeInTheDocument();
    expect(screen.getByText("+ Add item")).toBeInTheDocument();
  });

  it("multi_select decodes an existing JSON-array value as the active selection", async () => {
    const onChange = vi.fn();
    const input = def({
      type: "multi_select",
      name: "senses",
      options: [
        { value: "sight", label: "Sight" },
        { value: "sound", label: "Sound" },
      ],
    });
    render(PromptInputField, { props: { input, value: JSON.stringify(["sound"]), onChange } });
    // Toggling the already-selected chip clears it back to an empty array.
    await fireEvent.click(screen.getByRole("button", { name: "Sound" }));
    expect(onChange).toHaveBeenLastCalledWith(JSON.stringify([]));
  });
});
