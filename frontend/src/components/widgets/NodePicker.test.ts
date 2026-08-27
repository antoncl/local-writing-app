// @vitest-environment happy-dom
// NodePicker snippet picker respects the Library hide filter (ADR-0049 #682).
// hidePromptEntries is unit-tested on its own; this pins that NodePicker actually
// ROUTES its snippet enumeration through it — the wiring a future refactor could
// silently drop, since no shipped prompt is snippet-typed so it can't be caught
// in the browser.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent, within } from "@/lib/test/component";
import NodePicker from "./NodePicker.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { hideLibraryEntry, openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { MetadataSchema, PlotlineSummary, PromptEntrySummary } from "@/lib/types";

const SCHEMA = {
  entry_types: {
    "prompt:snippet": { name: "Snippet" },
    "plot:plotline": { name: "Plotline" },
    "lore:character": { name: "Character", kind: "lore" },
  },
  fields: {},
} as unknown as MetadataSchema;

function loreEntry(id: string, title: string, tags: string[], aliases: string[] = []) {
  return {
    id,
    title,
    body: "",
    entry_type: "lore:character",
    metadata: { tags, aliases },
  } as unknown as import("@/lib/types").LoreEntrySummary;
}

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

// ADR-0074 slice 4b (#1476): the manuscript group is a tri-state tree — root,
// acts, chapters as live containers over scenes.
describe("NodePicker manuscript tree (#1476)", () => {
  const structure = {
    root: {
      id: "root",
      type: "root",
      title: "The Manuscript",
      children: [
        {
          id: "ch1",
          type: "manuscript:chapter",
          title: "Chapter One",
          children: [
            { id: "n1", type: "manuscript:scene", scene_id: "s1", title: "Plain scene" },
            { id: "n2", type: "manuscript:scene", scene_id: "s2", title: "Battle scene" },
          ],
        },
      ],
    },
  } as never;

  it("renders the whole-manuscript root and containers over scenes", async () => {
    render(NodePicker, {
      props: { config: { sources: [{ kind: "manuscript" }] }, structure, affordance: "add" },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    expect(within(menu).getByText("The Manuscript")).toBeInTheDocument();
    expect(within(menu).getByText("Chapter One")).toBeInTheDocument();
    expect(within(menu).getByText("Plain scene")).toBeInTheDocument();
  });

  it("checking a chapter stores one live container ref", async () => {
    const onChange = vi.fn();
    render(NodePicker, {
      props: { config: { sources: [{ kind: "manuscript" }] }, structure, affordance: "add", onChange },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    await fireEvent.click(within(menu).getByText("Chapter One").closest("button")!);
    await tick();

    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toHaveLength(1);
    expect(detail.value[0]).toMatchObject({ id: "ch1", kind: "manuscript", entry_type: "manuscript:chapter" });
  });

  it("checking the root stores the whole-manuscript ref", async () => {
    const onChange = vi.fn();
    render(NodePicker, {
      props: { config: { sources: [{ kind: "manuscript" }] }, structure, affordance: "add", onChange },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    await fireEvent.click(within(menu).getByText("The Manuscript").closest("button")!);
    await tick();

    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toEqual([
      expect.objectContaining({ id: "root", kind: "manuscript", entry_type: "root" }),
    ]);
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

// ADR-0074 slice 2 (#1464): a candidate row toggles — clicking an
// already-picked candidate removes it, so you never leave the flow to unpick.
// The old inert "✓ Added" row (dimmed + non-clickable) is retired.
describe("NodePicker candidate toggle (ADR-0074 #1464)", () => {
  it("clicking an already-picked candidate removes it", async () => {
    const onChange = vi.fn();
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }] },
        plotEntries: [plotline("p1", "Main plot"), plotline("p2", "Romance")],
        value: [
          { id: "p1", kind: "plot", title: "Main plot" },
          { id: "p2", kind: "plot", title: "Romance" },
        ],
        affordance: "add",
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    // "Main plot" now renders twice — the candidate row AND the picked chip
    // (both NodeRows, ADR-0068). Scope to the candidate menu; that picked
    // candidate is a live, clickable row (not the old inert one), so clicking
    // it unpicks, leaving the other.
    const menu = document.querySelector(".ctx-menu")!;
    expect(menu).not.toBeNull();
    const row = within(menu as HTMLElement).getByText("Main plot").closest("button")!;
    await fireEvent.click(row);
    await tick();

    const [detail] = onChange.mock.calls[0];
    expect(detail.value.map((r: { id: string }) => r.id)).toEqual(["p2"]);
  });
});

// ADR-0074 slice 3 (#1468): search widened from title-only to title + tags +
// aliases, with a leading `#` restricting to tags.
describe("NodePicker widened search (#1468)", () => {
  function openWithLore() {
    const result = render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore" }] },
        loreEntries: [
          loreEntry("l1", "Mara Voss", ["heist"], ["the counter"]),
          loreEntry("l2", "Harbormaster Quill", ["harbor"]),
        ],
        affordance: "add",
      },
    });
    return result;
  }

  async function type(q: string) {
    const box = document.querySelector(".ctx-search") as HTMLInputElement;
    await fireEvent.input(box, { target: { value: q } });
    await tick();
  }

  it("finds an entry by a tag its title does not contain", async () => {
    openWithLore();
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    await type("heist");
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    expect(within(menu).getByText("Mara Voss")).toBeInTheDocument();
    expect(within(menu).queryByText("Harbormaster Quill")).toBeNull();
  });

  it("finds an entry by an alias", async () => {
    openWithLore();
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    await type("counter");
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    expect(within(menu).getByText("Mara Voss")).toBeInTheDocument();
  });

  it("#tag restricts to tags — a title/alias hit does not count", async () => {
    openWithLore();
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    // "voss" is in the title but is not a tag → #voss finds nothing.
    await type("#voss");
    let menu = document.querySelector(".ctx-menu") as HTMLElement;
    expect(within(menu).queryByText("Mara Voss")).toBeNull();
    // "#harbor" is a real tag → Quill surfaces.
    await type("#harbor");
    menu = document.querySelector(".ctx-menu") as HTMLElement;
    expect(within(menu).getByText("Harbormaster Quill")).toBeInTheDocument();
  });
});
