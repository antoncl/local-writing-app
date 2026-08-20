// @vitest-environment happy-dom
// Prompts pane hide/reveal/un-hide UI (ADR-0049 slice 3, #680). The store and
// the discovery filter are unit-tested elsewhere; this pins the PANE's own
// state logic — that hiding drops a Library row off the shelf, "Show N hidden"
// reveals it with an un-hide, and (the regression the review caught) un-hiding
// the last one un-latches "Show hidden" so the NEXT hide removes rather than
// dims.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import Prompts from "./Prompts.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { MetadataSchema, PromptContextStrategy, PromptEntrySummary } from "@/lib/types";

// The Prompts view roster is `descendants_of prompt:base` (defaultView →
// kindUniverseExpr), so the concrete type must be linked under the prompt root or
// evaluateView renders nothing.
const SCHEMA = {
  entry_types: {
    "prompt:base": { name: "Prompt" },
    "prompt:general": { name: "General", parent: "prompt:base" },
  },
  fields: {},
} as unknown as MetadataSchema;

function libraryPrompt(id: string, title: string): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    // ADR-0065 S3: roleplay collapsed to prompt:general; disposition here is
    // untested (this describe covers hide/reveal only), so no context_strategy.
    entry_type: "prompt:general",
    metadata: {},
    inputs: [],
    source_layer_id: "layer_library",
    source_layer_label: "Library",
    is_library: true,
  };
}

const noop = () => {};

// A schema for the disposition-shelving describe below — the dispositions
// themselves are now read off each prompt INSTANCE's own `context_strategy`
// (ADR-0065 S3), set directly by promptOf(); the schema only needs the prompt
// root so the roster's `descendants_of prompt:base` view resolves.
const DISPOSITION_SCHEMA = {
  entry_types: {
    "prompt:base": { name: "Prompt" },
    "prompt:general": { name: "General", parent: "prompt:base" },
    "prompt:snippet": { name: "Snippet", parent: "prompt:base" },
  },
  fields: {},
} as unknown as MetadataSchema;

function promptOf(
  id: string,
  title: string,
  entry_type: string,
  contextStrategy?: PromptContextStrategy | null,
): PromptEntrySummary {
  return { id, title, body: "", entry_type, metadata: {}, inputs: [], context_strategy: contextStrategy ?? null };
}

function renderPane() {
  return render(Prompts, {
    props: {
      entries: [libraryPrompt("p-alpha", "Alpha"), libraryPrompt("p-beta", "Beta")],
      onOpenEntry: noop,
      onNewEntry: noop,
      onCloneEntry: noop,
    },
  });
}

beforeEach(() => {
  localStorage.clear();
  openProjectHidden("test-project");
  metadataSchemaStore.set(SCHEMA);
});
afterEach(() => {
  openProjectHidden(null);
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("Prompts pane — disposition shelves (#951)", () => {
  it("groups the roster onto its disposition shelves, in shelf order", () => {
    metadataSchemaStore.set(DISPOSITION_SCHEMA);
    const { container } = render(Prompts, {
      props: {
        entries: [
          // Deliberately out of shelf order to prove the pane clusters them.
          promptOf("s", "A snippet", "prompt:snippet"),
          promptOf("g", "Free chat", "prompt:general"),
          promptOf("c", "Continue scene", "prompt:general", { output: { handler: "inline" } }),
          promptOf("b", "Revise a character", "prompt:general", {
            output: { handler: "extract_to_node", commit: { review: "visual_diff" } },
          }),
        ],
        onOpenEntry: noop,
        onNewEntry: noop,
        onCloneEntry: noop,
      },
    });
    // The label sits in `.node-row-text`; the header also carries a disclosure caret
    // (leading) and a count pill (trailing), so read the label element, not the row.
    const headings = Array.from(container.querySelectorAll(".node-row.group-header")).map((el) =>
      el.querySelector(".node-row-text")?.textContent?.trim(),
    );
    // Only populated shelves appear (no replace_selection prompt → no "Revise prose"),
    // and they appear in shelf order regardless of input order.
    expect(headings).toEqual(["Continue", "Chat", "Revise entities", "Snippets"]);
    // The rows themselves still render under their shelves.
    expect(screen.getByText("Continue scene")).toBeInTheDocument();
    expect(screen.getByText("Revise a character")).toBeInTheDocument();
  });
});

describe("Prompts pane — Library hide (ADR-0049 slice 3)", () => {
  it("hides a row off the shelf, reveals it, and un-hides it", async () => {
    renderPane();
    // Both Library rows carry a hide affordance.
    expect(screen.getByLabelText("Hide Alpha from this project")).toBeInTheDocument();

    await fireEvent.click(screen.getByLabelText("Hide Alpha from this project"));
    await tick();
    // Alpha left the shelf; the reveal appeared.
    expect(screen.queryByLabelText("Hide Alpha from this project")).toBeNull();
    expect(screen.getByRole("button", { name: /Show 1 hidden/ })).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: /Show 1 hidden/ }));
    await tick();
    // Revealed, now offering un-hide instead of hide.
    expect(screen.getByLabelText("Show Alpha again")).toBeInTheDocument();

    await fireEvent.click(screen.getByLabelText("Show Alpha again"));
    await tick();
    // Restored: hide is back and the reveal is gone.
    expect(screen.getByLabelText("Hide Alpha from this project")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /hidden/ })).toBeNull();
  });

  it("un-hiding the last row un-latches Show hidden, so the next hide removes it", async () => {
    renderPane();

    // Hide, reveal, then un-hide — leaving showHidden latched under the old bug.
    await fireEvent.click(screen.getByLabelText("Hide Alpha from this project"));
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: /Show 1 hidden/ }));
    await tick();
    await fireEvent.click(screen.getByLabelText("Show Alpha again"));
    await tick();

    // Now hide a different row: it must LEAVE the shelf (not merely dim in place).
    await fireEvent.click(screen.getByLabelText("Hide Beta from this project"));
    await tick();
    expect(screen.queryByLabelText("Hide Beta from this project")).toBeNull();
    // And the reveal reads "Show" (collapsed), not "Hide" (latched-open).
    expect(screen.getByRole("button", { name: /Show 1 hidden/ })).toBeInTheDocument();
  });
});
