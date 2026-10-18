// @vitest-environment happy-dom
// PromptMenu item tooltips (#2546): a prompt's one-line summary rides on the
// menu item as its `title`; a prompt without one gets no tooltip at all.
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import PromptMenu from "./PromptMenu.svelte";
import { buildPromptMenuTree } from "@/lib/editor-core/promptMenuTree";
import type { PromptEntrySummary } from "@/lib/types";

function prompt(title: string, summary?: string): PromptEntrySummary {
  return {
    id: title,
    title,
    body: "",
    entry_type: "prompt:general",
    metadata: summary === undefined ? {} : { summary },
    computed_metadata: {},
    inputs: [],
  };
}

describe("PromptMenu — summary tooltips (#2546)", () => {
  it("titles an item with the prompt's summary, and leaves none off when empty", () => {
    const nodes = buildPromptMenuTree([prompt("Alpha", "Writes the first draft."), prompt("Beta"), prompt("Gamma", "")]);
    render(PromptMenu, { props: { nodes, onSelect: () => {} } });
    expect(screen.getByRole("menuitem", { name: "Alpha" })).toHaveAttribute("title", "Writes the first draft.");
    expect(screen.getByRole("menuitem", { name: "Beta" })).not.toHaveAttribute("title");
    expect(screen.getByRole("menuitem", { name: "Gamma" })).not.toHaveAttribute("title");
  });
});
