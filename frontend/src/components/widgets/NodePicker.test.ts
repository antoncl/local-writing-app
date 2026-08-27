// @vitest-environment happy-dom
// NodePicker snippet picker respects the Library hide filter (ADR-0049 #682).
// hidePromptEntries is unit-tested on its own; this pins that NodePicker actually
// ROUTES its snippet enumeration through it — the wiring a future refactor could
// silently drop, since no shipped prompt is snippet-typed so it can't be caught
// in the browser.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import NodePicker from "./NodePicker.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { hideLibraryEntry, openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { MetadataSchema, PlotlineSummary, PromptEntrySummary } from "@/lib/types";

const SCHEMA = {
  entry_types: { "prompt:snippet": { name: "Snippet" }, "plot:plotline": { name: "Plotline" } },
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

function plotline(id: string, title: string): PlotlineSummary {
  return { id, title, body: "", entry_type: "plot:plotline", metadata: {} };
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

describe("NodePicker plot source (#742)", () => {
  it("enumerates plotline candidates for a plot:plotline ref", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }] },
        plotEntries: [plotline("p1", "Main plot"), plotline("p2", "Romance")],
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    // The gap #742 closes: before the plot branch, this list was empty.
    expect(screen.getByText("Plotlines")).toBeInTheDocument();
    expect(screen.getByText("Main plot")).toBeInTheDocument();
    expect(screen.getByText("Romance")).toBeInTheDocument();
  });

  it("filters candidates to the config's entry_type whitelist", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }] },
        // A stray non-plotline plot node must not leak into the plotline picker.
        plotEntries: [plotline("p1", "Main plot"), { ...plotline("c1", "A card"), entry_type: "plot:card" }],
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    expect(screen.getByText("Main plot")).toBeInTheDocument();
    expect(screen.queryByText("A card")).toBeNull();
  });
});

// #1461 (ADR-0074 slice 1): manuscript sources store kind "manuscript", so the
// scene filter must read entryTypes.manuscript — the old `.scene` read was a
// key pickerMembership never produces, leaving the author's checkbox a no-op.
describe("NodePicker manuscript entry-type allowlist (#1461)", () => {
  const structure = {
    root: {
      id: "root",
      type: "root",
      title: "Manuscript",
      children: [
        {
          id: "ch1",
          type: "manuscript:chapter",
          title: "Chapter One",
          children: [
            { id: "n1", type: "manuscript:scene", scene_id: "s1", title: "Plain scene" },
            {
              id: "n2",
              type: "manuscript:scene",
              scene_id: "s2",
              title: "Battle scene",
              entry_type: "manuscript:battle",
            },
          ],
        },
      ],
    },
  } as never;

  it("filters scenes to the config's manuscript scene-type selection", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "manuscript", expr: { type: "manuscript:battle" } }] },
        structure,
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    expect(screen.getByText("Battle scene")).toBeInTheDocument();
    expect(screen.queryByText("Plain scene")).toBeNull();
  });

  it("ignores structural container types until containers are pickable (ADR-0074 slice 4)", async () => {
    render(NodePicker, {
      props: {
        // An act/chapter-only selection gates nothing yet — it must not blank
        // the scene list (the original dogfooding complaint made worse).
        config: {
          sources: [
            {
              kind: "manuscript",
              expr: { union: [{ type: "manuscript:act" }, { type: "manuscript:chapter" }] },
            },
          ],
        },
        structure,
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    expect(screen.getByText("Plain scene")).toBeInTheDocument();
    expect(screen.getByText("Battle scene")).toBeInTheDocument();
  });
});

describe("NodePicker onChange callback (runes conversion #49)", () => {
  // The dispatch("change", …) → onChange callback prop is the crux of the runes
  // conversion; lock the payload shape and the multi-select append so a later
  // edit can't silently regress it.
  it("reports the picked ref through onChange with the { value } payload", async () => {
    const onChange = vi.fn();
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }] },
        plotEntries: [plotline("p1", "Main plot"), plotline("p2", "Romance")],
        affordance: "add",
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    await fireEvent.click(screen.getByText("Main plot").closest("button")!);
    await tick();

    expect(onChange).toHaveBeenCalledTimes(1);
    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toHaveLength(1);
    expect(detail.value[0]).toMatchObject({ id: "p1", kind: "plot" });
  });

  it("appends to the existing value when multiple selection is allowed", async () => {
    const onChange = vi.fn();
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }] },
        plotEntries: [plotline("p1", "Main plot"), plotline("p2", "Romance")],
        value: [{ id: "p2", kind: "plot", title: "Romance" }],
        affordance: "add",
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    await fireEvent.click(screen.getByText("Main plot").closest("button")!);
    await tick();

    const [detail] = onChange.mock.calls[0];
    expect(detail.value.map((r: { id: string }) => r.id)).toEqual(["p2", "p1"]);
  });
});
