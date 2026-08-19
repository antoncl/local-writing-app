// @vitest-environment happy-dom
// InputsDialog had no test. The #49 runes port turns its four CustomEvents
// (updateDraft / updateAssistant / cancel / submit) into callback props; these
// lock that each still fires — including the `on:mousedown|self` → explicit
// `e.target === e.currentTarget` unroll on the backdrop, the port's most
// error-prone step. Rendered with empty declaredInputs so no PromptInputField
// (TipTap) mounts — that density isn't happy-dom-mountable (#642).
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import InputsDialog from "./InputsDialog.svelte";
import type { AssistantEntrySummary, PromptEntrySummary } from "@/lib/types";

const entry = { id: "prompt_1", title: "Draft a scene" } as unknown as PromptEntrySummary;

describe("InputsDialog — callback props (runes port of its CustomEvents)", () => {
  it("Cancel and Run fire onCancel / onSubmit", async () => {
    const onCancel = vi.fn();
    const onSubmit = vi.fn();
    render(InputsDialog, { props: { entry, onCancel, onSubmit } });
    await fireEvent.click(screen.getByText("Cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
    await fireEvent.click(screen.getByText("Run"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("Esc → onCancel, Ctrl+Enter → onSubmit", async () => {
    const onCancel = vi.fn();
    const onSubmit = vi.fn();
    render(InputsDialog, { props: { entry, onCancel, onSubmit } });
    const dialog = screen.getByRole("dialog");
    await fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
    await fireEvent.keyDown(dialog, { key: "Enter", ctrlKey: true });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("mousedown on the backdrop cancels; mousedown inside the dialog does not (|self)", async () => {
    const onCancel = vi.fn();
    const { container } = render(InputsDialog, { props: { entry, onCancel } });
    const backdrop = container.querySelector(".inputs-dialog-backdrop") as HTMLElement;
    // Bubbles from the inner dialog to the backdrop handler, but target !==
    // currentTarget there, so it must not cancel.
    await fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(onCancel).not.toHaveBeenCalled();
    await fireEvent.mouseDown(backdrop);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("changing the assistant fires onUpdateAssistant with the id", async () => {
    const onUpdateAssistant = vi.fn();
    const assistantEntries = [
      { id: "asst_1", title: "Editor" },
    ] as unknown as AssistantEntrySummary[];
    render(InputsDialog, { props: { entry, assistantEntries, onUpdateAssistant } });
    await fireEvent.change(screen.getByRole("combobox"), { target: { value: "asst_1" } });
    expect(onUpdateAssistant).toHaveBeenCalledWith({ assistantId: "asst_1" });
  });
});
