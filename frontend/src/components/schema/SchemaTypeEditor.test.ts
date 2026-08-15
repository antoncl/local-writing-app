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

describe("SchemaTypeEditor reusable groups on built-in types (#1033)", () => {
  it("shows Add group and the Reusable-groups section on a readonly (built-in) type", () => {
    // Regression: the affordances were gated `{#if !schemaTypeReadonly}`, so a
    // built-in type like lore:character — where "Add field" already works —
    // could not attach a reusable group, even though the backend accepts group
    // applications as per-layer overlays on built-ins (ADR-0029 §A,
    // set_entry_type_group_applications has "No built-in guard").
    render(SchemaTypeEditor, {
      props: {
        schemaTypeKind: "lore" as const,
        initialName: "Character",
        initialTypeId: "lore:character",
        selectedSchemaTypeId: "lore:character",
        schemaTypeLayerId: "proj",
        schemaTypeReadonly: true,
        onSaveType: vi.fn(),
      },
    });
    // Both formerly-gated affordances render: the peer "Add group" button and
    // the Reusable-groups section's "Manage…" link.
    expect(screen.getByRole("button", { name: "Add group" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Manage…" })).toBeTruthy();
  });
});

describe("SchemaTypeEditor on_accept round-trip (#957)", () => {
  const onAccept = { mark: "character", from_input: "character" } as const;

  it("preserves an inline prompt's on_accept mark-stamp through a save", async () => {
    // on_accept (the roleplay character-stamp) has no authoring control, so it must
    // ride through a save verbatim — the same guarantee as commit.fields. Without
    // this, editing roleplay's type would silently drop the stamp.
    const onSaveType = vi.fn();
    mount(promptWith({ kind: "append_to_body", on_accept: { ...onAccept } }), onSaveType);
    expect(await savedOutput(onSaveType)).toEqual({ kind: "append_to_body", on_accept: { ...onAccept } });
  });

  it("drops on_accept when the disposition is not inline (it rides only on inline)", async () => {
    const onSaveType = vi.fn();
    mount(promptWith({ kind: "chat_panel", on_accept: { ...onAccept } }), onSaveType);
    expect(await savedOutput(onSaveType)).toEqual({ kind: "chat_panel" });
  });
});
