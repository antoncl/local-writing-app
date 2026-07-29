// @vitest-environment happy-dom
// NodePicker snippet picker respects the Library hide filter (ADR-0049 #682).
// hidePromptEntries is unit-tested on its own; this pins that NodePicker actually
// ROUTES its snippet enumeration through it — the wiring a future refactor could
// silently drop, since no shipped prompt is snippet-typed so it can't be caught
// in the browser.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import NodePicker from "./NodePicker.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { hideLibraryEntry, openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { MetadataSchema, PromptEntrySummary } from "@/lib/types";

const SCHEMA = {
  entry_types: { "prompt:snippet": { name: "Snippet" } },
  fields: {},
} as unknown as MetadataSchema;

function snippet(id: string, title: string): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    entry_type: "prompt:snippet",
    metadata: {},
    inputs: [],
    is_library: true,
  };
}

beforeEach(() => {
  localStorage.clear();
  openProjectHidden("nodepicker-test");
  metadataSchemaStore.set(SCHEMA);
});
afterEach(() => {
  openProjectHidden(null);
  localStorage.clear();
});

describe("NodePicker snippet picker — hide filter (ADR-0049 #682)", () => {
  it("omits a hidden Library prompt from the snippet list", async () => {
    hideLibraryEntry("gone");
    render(NodePicker, {
      props: {
        // A snippet-kind source with no entry_type leaves → every prompt is a snippet.
        config: { sources: [{ kind: "snippet" }] },
        promptEntries: [snippet("keep", "Keeper"), snippet("gone", "Goner")],
        affordance: "add",
      },
    });
    // Open the picker (its list renders only while open).
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    expect(screen.getByText("Keeper")).toBeInTheDocument();
    expect(screen.queryByText("Goner")).toBeNull();
  });
});
