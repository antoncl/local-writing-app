// @vitest-environment happy-dom
// ADR-0054 S3 — the commit authoring block in "Prompt defaults". A chat_panel
// prompt may declare a `commit` (turning it into a brainstorm); this editor
// authors its presence + review mode. Two invariants matter and are easy to
// regress: (a) the commit control exists ONLY under a chat_panel disposition
// (the backend rejects a commit on any other), and (b) the `commit.fields`
// allow-list has no UI but must survive an edit through this editor verbatim —
// the built-in scene-summary carries `fields: [summary]`, and stripping it on an
// unrelated edit would let a summary regenerate rewrite the manuscript body.
//
// The disposition is seeded through `initialPrompt` rather than by driving the
// Output <select>: that select carries an empty `value=""` option that the
// happy-dom / Svelte-5 select binding doesn't update under fireEvent (the app's
// real browser behaviour is fine — S2 verified it). Seeding exercises the same
// `{#if output.kind === "chat_panel"}` gate from both sides.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import type { PromptEntryTypeExtras, PromptOutput } from "@/lib/types";
import SchemaTypeEditor from "./SchemaTypeEditor.svelte";

const TOGGLE = "Commit results back to the subject";

function promptWith(output: PromptOutput | null): PromptEntryTypeExtras | null {
  return output ? { context_strategy: { output } } : null;
}

function mount(initialPrompt: PromptEntryTypeExtras | null, onSaveType: ReturnType<typeof vi.fn>) {
  render(SchemaTypeEditor, {
    props: {
      schemaTypeKind: "prompt" as const,
      initialName: "Summarize scene",
      initialTypeId: "revise:summarize",
      schemaTypeLayerId: "proj",
      initialPrompt,
      onSaveType,
    },
  });
}

async function savedOutput(onSaveType: ReturnType<typeof vi.fn>): Promise<PromptOutput | undefined> {
  await fireEvent.click(screen.getByRole("button", { name: "Save Type" }));
  return onSaveType.mock.calls.at(-1)?.[0]?.promptExtras?.context_strategy?.output;
}

describe("SchemaTypeEditor commit authoring (ADR-0054 S3)", () => {
  it("offers no commit control unless the disposition is chat_panel", () => {
    mount(promptWith({ kind: "append_to_body" }), vi.fn());
    expect(screen.queryByLabelText(TOGGLE)).toBeNull();
  });

  it("shows an unchecked toggle on a plain chat panel, and writes a default commit when enabled", async () => {
    const onSaveType = vi.fn();
    mount(promptWith({ kind: "chat_panel" }), onSaveType);

    const toggle = screen.getByLabelText(TOGGLE) as HTMLInputElement;
    // A plain chat panel is not a brainstorm until the author opts in.
    expect(toggle.checked).toBe(false);
    expect(screen.queryByRole("combobox", { name: /Review as/ })).toBeNull();
    expect(await savedOutput(onSaveType)).toEqual({ kind: "chat_panel" });

    onSaveType.mockClear();
    await fireEvent.click(toggle);
    expect(await savedOutput(onSaveType)).toEqual({ kind: "chat_panel", commit: { review: "visual_diff" } });
  });

  it("preserves the commit.fields allow-list verbatim through an unrelated edit", async () => {
    const onSaveType = vi.fn();
    mount(promptWith({ kind: "chat_panel", commit: { review: "replace", fields: ["summary"] } }), onSaveType);

    // Seeded state reflects the existing commit.
    expect((screen.getByLabelText(TOGGLE) as HTMLInputElement).checked).toBe(true);
    const review = screen.getByRole("combobox", { name: /Review as/ }) as HTMLSelectElement;
    expect(review.value).toBe("replace");

    // Change only the review mode — fields has no UI and must ride through.
    await fireEvent.change(review, { target: { value: "visual_diff" } });
    expect(await savedOutput(onSaveType)).toEqual({
      kind: "chat_panel",
      commit: { review: "visual_diff", fields: ["summary"] },
    });
  });

  it("drops the whole commit (fields included) when the author turns it off", async () => {
    const onSaveType = vi.fn();
    mount(promptWith({ kind: "chat_panel", commit: { review: "replace", fields: ["summary"] } }), onSaveType);

    await fireEvent.click(screen.getByLabelText(TOGGLE));
    expect(await savedOutput(onSaveType)).toEqual({ kind: "chat_panel" });
  });
});
