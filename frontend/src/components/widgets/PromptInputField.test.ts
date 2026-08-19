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
