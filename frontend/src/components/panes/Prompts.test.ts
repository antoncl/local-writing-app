// @vitest-environment happy-dom
// Prompts pane hide/reveal/un-hide UI (ADR-0049 slice 3, #680). The store and
// the discovery filter are unit-tested elsewhere; this pins the PANE's own
// state logic — that hiding drops a Library row off the shelf, "Show N hidden"
// reveals it with an un-hide, and (the regression the review caught) un-hiding
// the last one un-latches "Show hidden" so the NEXT hide removes rather than
// dims.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import Prompts from "./Prompts.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { MetadataSchema, PromptEntrySummary } from "@/lib/types";

// The shelf vocabulary, from the shared drift-gate file — so the shelf-order
// assertion below fails on a real reorder instead of passing against a stale
// private copy (#1692 review).
const here = dirname(fileURLToPath(import.meta.url));
const vocab = JSON.parse(
  readFileSync(resolve(here, "../../../../spec/prompt-disposition-labels.json"), "utf-8"),
);
const DISPOSITIONS: string[] = vocab.dispositions;

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
    // ADR-0065 S3: roleplay collapsed to prompt:general. Disposition arrives
    // backend-stamped (#1684); shelving itself is untested in the hide/reveal
    // describe (its SCHEMA declares no computed fields), the stamp is just the
    // realistic summary shape.
    entry_type: "prompt:general",
    metadata: {},
    computed_metadata: { disposition: "Chat", runnable: "runnable" },
    inputs: [],
    source_layer_id: "layer_library",
    source_layer_label: "Library",
    is_library: true,
  };
}

const noop = () => {};

// A schema for the disposition-shelving describe below. The disposition VALUES
// arrive backend-stamped in each summary's `computed_metadata` (#1684), set
// directly by promptOf(); the schema declares `disposition`/`runnable` as
// computed fields the way the resolved backend schema does — that is what
// routes `fieldValue` to `computed_metadata`, and the declared option order is
// the shelf order `show_empty` renders.
const DISPOSITION_SCHEMA = {
  entry_types: {
    "prompt:base": { name: "Prompt" },
    "prompt:general": { name: "General", parent: "prompt:base" },
    "prompt:snippet": { name: "Snippet", parent: "prompt:base" },
  },
  fields: {
    disposition: {
      name: "Disposition",
      type: "computed",
      category: "computed",
      options: DISPOSITIONS.map((value) => ({ value, label: value })),
      computed: { function: "prompt_disposition", value_type: "select" },
    },
    runnable: {
      name: "Runnable",
      type: "computed",
      category: "computed",
      options: [{ value: "runnable", label: "Runnable" }],
      computed: { function: "prompt_runnable", value_type: "select" },
    },
  },
} as unknown as MetadataSchema;

function promptOf(
  id: string,
  title: string,
  entry_type: string,
  disposition = "Chat",
  runnable = "",
): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    entry_type,
    metadata: {},
    computed_metadata: { disposition, runnable },
    inputs: [],
  };
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

describe("Prompts pane — disposition shelves (#951/#1684)", () => {
  it("groups the roster onto the five declared shelves, in declared order", () => {
    metadataSchemaStore.set(DISPOSITION_SCHEMA);
    const { container } = render(Prompts, {
      props: {
        entries: [
          // Deliberately out of shelf order to prove declared-option ordering.
          promptOf("s", "A snippet", "prompt:snippet", "Snippets"),
          promptOf("g", "Free chat", "prompt:general", "Chat"),
          promptOf("c", "Continue scene", "prompt:general", "Continue"),
          promptOf("b", "Revise a character", "prompt:general", "Revise entities"),
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
    // `show_empty` (#1684): ALL five declared shelves render in option order —
    // the empty "Revise prose" shelf included — regardless of input order. The
    // expectation comes from the vocabulary file, so a shelf reorder fails here
    // rather than passing against a stale literal.
    expect(headings).toEqual(DISPOSITIONS);
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

describe("Prompts pane — ▶ Run affordance (#1433)", () => {
  it("shows Run on a runnable (Chat, no offer_on) row, not on a non-runnable one", () => {
    metadataSchemaStore.set(DISPOSITION_SCHEMA);
    render(Prompts, {
      props: {
        entries: [
          promptOf("chat", "Free chat", "prompt:general", "Chat", "runnable"),
          promptOf("cont", "Continue scene", "prompt:general", "Continue"),
        ],
        onOpenEntry: noop,
        onNewEntry: noop,
        onCloneEntry: noop,
      },
    });
    expect(screen.getByLabelText("Run Free chat")).toBeInTheDocument();
    expect(screen.queryByLabelText("Run Continue scene")).toBeNull();
  });

  it("excludes a Chat prompt anchored to a host type via offer_on (e.g. impersonate)", () => {
    metadataSchemaStore.set(DISPOSITION_SCHEMA);
    // Backend stamps runnable "" for an offer_on-anchored Chat (#1684).
    const impersonate = promptOf("imp", "Impersonate", "prompt:general", "Chat", "");
    render(Prompts, {
      props: { entries: [impersonate], onOpenEntry: noop, onNewEntry: noop, onCloneEntry: noop },
    });
    expect(screen.queryByLabelText("Run Impersonate")).toBeNull();
  });

  it("fires onRunEntry with the prompt id when Run is clicked", async () => {
    metadataSchemaStore.set(DISPOSITION_SCHEMA);
    const onRunEntry = vi.fn();
    render(Prompts, {
      props: {
        entries: [promptOf("chat", "Free chat", "prompt:general", "Chat", "runnable")],
        onOpenEntry: noop,
        onNewEntry: noop,
        onCloneEntry: noop,
        onRunEntry,
      },
    });
    await fireEvent.click(screen.getByLabelText("Run Free chat"));
    expect(onRunEntry).toHaveBeenCalledWith("chat");
  });
});
