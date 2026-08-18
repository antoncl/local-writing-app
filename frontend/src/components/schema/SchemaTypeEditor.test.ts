// @vitest-environment happy-dom
// ADR-0054 S3 / ADR-0065 — the commit authoring block in "Prompt defaults". A
// CONVERSATION prompt may declare a `commit` (turning it into an extract_to_node
// brainstorm); this editor authors its presence + review mode. Invariants that are
// easy to regress: (a) the commit control exists ONLY under a conversation surface
// (the backend rejects a commit on the inline handler); (b) a handler-less general
// chat saves as an empty `context_strategy` (no output block) — its presence is what
// marks it INVOCABLE vs a snippet (ADR-0065), so it must not collapse to no strategy;
// and (c) `commit.fields` / `on_accept` have no UI but must ride through verbatim.
//
// The surface is seeded through `initialPrompt` rather than by driving the Output
// <select>: that select carries an empty `value=""` option that the happy-dom /
// Svelte-5 select binding doesn't update under fireEvent (the app's real browser
// behaviour is fine — S2 verified it). Seeding exercises the same
// `{#if promptOutputSurface === "conversation"}` gate from both sides.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import type { PromptContextStrategy, PromptEntryTypeExtras, PromptOutput } from "@/lib/types";
import SchemaTypeEditor from "./SchemaTypeEditor.svelte";

const TOGGLE = "Commit results back to the subject";

// A prompt whose output block is `output` (an inline or extract prompt).
function promptWith(output: PromptOutput | null): PromptEntryTypeExtras | null {
  return output ? { context_strategy: { output } } : null;
}

// A handler-less general chat: an (empty) context_strategy, no output block.
function generalPrompt(): PromptEntryTypeExtras {
  return { context_strategy: {} };
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

async function savedStrategy(
  onSaveType: ReturnType<typeof vi.fn>,
): Promise<PromptContextStrategy | undefined> {
  await fireEvent.click(screen.getByRole("button", { name: "Save Type" }));
  return onSaveType.mock.calls.at(-1)?.[0]?.promptExtras?.context_strategy;
}

describe("SchemaTypeEditor commit authoring (ADR-0054 S3 / ADR-0065)", () => {
  it("offers no commit control unless the surface is a conversation", () => {
    mount(promptWith({ handler: "inline" }), vi.fn());
    expect(screen.queryByLabelText(TOGGLE)).toBeNull();
  });

  it("shows an unchecked toggle on a plain conversation, and writes an extract_to_node commit when enabled", async () => {
    const onSaveType = vi.fn();
    mount(generalPrompt(), onSaveType);

    const toggle = screen.getByLabelText(TOGGLE) as HTMLInputElement;
    // A plain conversation is not a brainstorm until the author opts in.
    expect(toggle.checked).toBe(false);
    expect(screen.queryByRole("combobox", { name: /Review as/ })).toBeNull();
    // Saved as an empty context_strategy — no output block, but present ⇒ invocable.
    expect(await savedStrategy(onSaveType)).toEqual({});

    onSaveType.mockClear();
    await fireEvent.click(toggle);
    expect(await savedStrategy(onSaveType)).toEqual({
      output: { handler: "extract_to_node", commit: { review: "visual_diff" } },
    });
  });

  it("preserves the commit.fields allow-list verbatim through an unrelated edit", async () => {
    const onSaveType = vi.fn();
    mount(
      promptWith({ handler: "extract_to_node", commit: { review: "replace", fields: ["summary"] } }),
      onSaveType,
    );

    // Seeded state reflects the existing commit.
    expect((screen.getByLabelText(TOGGLE) as HTMLInputElement).checked).toBe(true);
    const review = screen.getByRole("combobox", { name: /Review as/ }) as HTMLSelectElement;
    expect(review.value).toBe("replace");

    // Change only the review mode — fields has no UI and must ride through.
    await fireEvent.change(review, { target: { value: "visual_diff" } });
    expect(await savedStrategy(onSaveType)).toEqual({
      output: { handler: "extract_to_node", commit: { review: "visual_diff", fields: ["summary"] } },
    });
  });

  it("drops the whole commit (fields included) when the author turns it off", async () => {
    const onSaveType = vi.fn();
    mount(
      promptWith({ handler: "extract_to_node", commit: { review: "replace", fields: ["summary"] } }),
      onSaveType,
    );

    await fireEvent.click(screen.getByLabelText(TOGGLE));
    // Turning the commit off makes it a plain (handler-less) conversation again.
    expect(await savedStrategy(onSaveType)).toEqual({});
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
    mount(promptWith({ handler: "inline", on_accept: { ...onAccept } }), onSaveType);
    expect(await savedStrategy(onSaveType)).toEqual({
      output: { handler: "inline", on_accept: { ...onAccept } },
    });
  });

  it("drops on_accept when the surface is not inline (it rides only on inline)", async () => {
    const onSaveType = vi.fn();
    // A handler-less conversation carrying an on_accept — the stamp must drop, leaving
    // a plain conversation (an empty context_strategy).
    mount(promptWith({ on_accept: { ...onAccept } }), onSaveType);
    expect(await savedStrategy(onSaveType)).toEqual({});
  });
});
