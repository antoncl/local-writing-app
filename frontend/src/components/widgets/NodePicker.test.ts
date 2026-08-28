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
import { api } from "@/lib/api";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { setKnownTags, clearKnownTags } from "@/lib/stores/tags";
import { cardEntriesStore } from "@/lib/stores/plotCards";
import { hideLibraryEntry, openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { MetadataSchema, PlotlineSummary, PromptEntrySummary, ViewNodeSummary } from "@/lib/types";

const SCHEMA = {
  entry_types: {
    "prompt:snippet": { name: "Snippet" },
    "plot:plotline": { name: "Plotline", kind: "plot" },
    "plot:card": { name: "Card", kind: "plot" },
    "lore:character": { name: "Character", kind: "lore" },
  },
  fields: {},
} as unknown as MetadataSchema;

// A plot card summary shape (metadata.plotline is the scalar membership ref).
function plotCard(id: string, title: string, plotlineId: string | null) {
  return {
    id,
    title,
    body: "",
    entry_type: "plot:card",
    metadata: plotlineId ? { plotline: plotlineId } : {},
  } as never;
}

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
  // The picker lazily fetches saved views when the menu opens (ADR-0074 slice
  // 5); default it empty so tests that don't exercise views never touch the
  // network (#973). Tags come from knownTagsStore (no fetch) — empty by default.
  vi.spyOn(api, "listViews").mockResolvedValue({ entries: [] });
  clearKnownTags();
  cardEntriesStore.set([]);
});
afterEach(() => {
  openProjectHidden(null);
  localStorage.clear();
  clearKnownTags();
  cardEntriesStore.set([]);
  vi.restoreAllMocks();
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

// ADR-0074 slice 6: a plotline is the 6th container shape — a live selector over
// the cards whose scalar metadata.plotline points at it, not a leaf node ref.
describe("NodePicker plot source — plotline containers (ADR-0074 slice 6)", () => {
  it("renders each plotline as a container over its cards", async () => {
    cardEntriesStore.set([
      plotCard("c1", "Break-in", "p1"),
      plotCard("c2", "Getaway", "p1"),
      plotCard("c3", "A kiss", "p2"),
    ]);
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }] },
        plotEntries: [plotline("p1", "The Heist"), plotline("p2", "Romance")],
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    const plot = (await screen.findAllByRole("group", { name: "Plotlines" }))[0];
    expect(within(plot).getByText("The Heist")).toBeInTheDocument();
    expect(within(plot).getByText("Romance")).toBeInTheDocument();
    // Drill: The Heist's cards are its members; the Romance card is not.
    expect(within(plot).getByText("Break-in")).toBeInTheDocument();
    expect(within(plot).getByText("Getaway")).toBeInTheDocument();
    expect(within(plot).queryByText("A kiss")).not.toBeNull(); // under Romance, still rendered
  });

  it("checking a plotline stores ONE live selector ref, not the plotline node (absorb)", async () => {
    const onChange = vi.fn();
    cardEntriesStore.set([plotCard("c1", "Break-in", "p1"), plotCard("c2", "Getaway", "p1")]);
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }] },
        plotEntries: [plotline("p1", "The Heist")],
        affordance: "add",
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    const plot = (await screen.findAllByRole("group", { name: "Plotlines" }))[0];
    await fireEvent.click(within(plot).getByText("The Heist").closest("button")!);
    await tick();

    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toHaveLength(1);
    expect(detail.value[0]).toMatchObject({ id: "plotline:p1", kind: "plot", entry_type: "plot:plotline" });
    // The stored ref carries its inline selector spec — the plotline's cards, live.
    expect(detail.value[0].selector).toMatchObject({ kind: "plot" });
  });

  it("unchecking a picked plotline removes it, does not duplicate it (regression)", async () => {
    const onChange = vi.fn();
    cardEntriesStore.set([plotCard("c1", "Break-in", "p1"), plotCard("c2", "Getaway", "p1")]);
    const spec = {
      kind: "plot",
      expr: { intersect: [{ type: "plot:card" }, { field: { key: "plotline", op: "overlap", value: "p1" } }] },
    };
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }], multiple: true },
        plotEntries: [plotline("p1", "The Heist")],
        // Already picked as a live selector — a kind-based isSel misread this and
        // re-absorbed on the next click, appending a duplicate.
        value: [{ id: "plotline:p1", kind: "plot", title: "The Heist", entry_type: "plot:plotline", selector: spec }] as never,
        affordance: "add",
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    const plot = (await screen.findAllByRole("group", { name: "Plotlines" }))[0];
    await fireEvent.click(within(plot).getByText("The Heist").closest("button")!);
    await tick();

    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toEqual([]);
  });

  it("drilling in and checking a card stores that explicit (ungated) card ref", async () => {
    const onChange = vi.fn();
    cardEntriesStore.set([plotCard("c1", "Break-in", "p1"), plotCard("c2", "Getaway", "p1")]);
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }], multiple: true },
        plotEntries: [plotline("p1", "The Heist")],
        affordance: "add",
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    const plot = (await screen.findAllByRole("group", { name: "Plotlines" }))[0];
    await fireEvent.click(within(plot).getByText("Break-in").closest("button")!);
    await tick();

    const [detail] = onChange.mock.calls[0];
    // A concrete card ref — no selector, so it's ungated and expands to itself.
    expect(detail.value).toEqual([expect.objectContaining({ id: "c1", kind: "plot" })]);
    expect(detail.value[0].selector).toBeUndefined();
  });

  it("does not promote a stray non-plotline node to a container", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "plot", expr: { type: "plot:plotline" } }] },
        // A stray plot:card in the plotline roster must not become a container.
        plotEntries: [plotline("p1", "The Heist"), { ...plotline("c1", "A card"), entry_type: "plot:card" }],
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    expect(screen.getByText("The Heist")).toBeInTheDocument();
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

// ADR-0074 slice 5 (#1487): an author-configured saved view ({view:id}) renders
// as a tri-state selector — absorb the whole view (one live ref) or drill in and
// pick members. pickerMembership drops view-refs, so this pins that the runtime
// picker surfaces them (the invisible-view bug) and expands their members.
describe("NodePicker saved-view selectors (#1487)", () => {
  const villainsView: ViewNodeSummary = {
    id: "v1",
    title: "Villains",
    entry_type: "view:view",
    view_kind: "lore",
    spec: { kind: "lore", expr: { tagged: "villain" } },
  };

  function renderWithView(extra: Record<string, unknown> = {}) {
    return render(NodePicker, {
      props: {
        config: { sources: [{ view: "v1" }], multiple: true },
        loreEntries: [
          loreEntry("lore_a", "Vex", ["villain"]),
          loreEntry("lore_b", "Mara", ["hero"]),
          loreEntry("lore_c", "Nok", ["villain"]),
        ],
        affordance: "add",
        ...extra,
      },
    });
  }

  async function openMenu(): Promise<HTMLElement> {
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    return document.querySelector(".ctx-menu") as HTMLElement;
  }

  beforeEach(() => {
    vi.spyOn(api, "listViews").mockResolvedValue({ entries: [villainsView] });
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the configured view as a selector over its live members", async () => {
    renderWithView();
    const menu = await openMenu();
    // The view (dropped by pickerMembership) is surfaced, with its tagged members.
    expect(await within(menu).findByText("Villains")).toBeInTheDocument();
    expect(within(menu).getByText("Vex")).toBeInTheDocument();
    expect(within(menu).getByText("Nok")).toBeInTheDocument();
    // "Mara" is not tagged villain — not a member.
    expect(within(menu).queryByText("Mara")).toBeNull();
  });

  it("checking the view stores ONE live selector ref (absorb)", async () => {
    const onChange = vi.fn();
    renderWithView({ onChange });
    const menu = await openMenu();
    await fireEvent.click((await within(menu).findByText("Villains")).closest("button")!);
    await tick();
    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toHaveLength(1);
    expect(detail.value[0]).toMatchObject({ id: "view:v1", kind: "view" });
    expect(detail.value[0].selector).toEqual(villainsView.spec);
  });

  it("drilling in and checking a member stores that explicit member ref", async () => {
    const onChange = vi.fn();
    renderWithView({ onChange });
    const menu = await openMenu();
    await within(menu).findByText("Villains");
    await fireEvent.click(within(menu).getByText("Vex").closest("button")!);
    await tick();
    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toEqual([expect.objectContaining({ id: "lore_a", kind: "lore" })]);
  });

  it("a search matching no member hides the view entirely (#1488 review)", async () => {
    renderWithView();
    const menu = await openMenu();
    await within(menu).findByText("Villains");
    const box = document.querySelector(".ctx-search") as HTMLInputElement;
    // A term matching neither the view title nor any member.
    await fireEvent.input(box, { target: { value: "zzzznope" } });
    await tick();
    expect(within(menu).queryByText("Villains")).toBeNull();
    expect(within(menu).queryByText("Vex")).toBeNull();
    // A member-name search shows the view with just that member.
    await fireEvent.input(box, { target: { value: "Vex" } });
    await tick();
    expect(within(menu).getByText("Villains")).toBeInTheDocument();
    expect(within(menu).getByText("Vex")).toBeInTheDocument();
    expect(within(menu).queryByText("Nok")).toBeNull();
  });
});

// ADR-0074 slice 5 pt.2 (#1491): the scoped known-tag vocabulary becomes
// per-kind tag selectors — absorb "everything tagged X" as one live ref, or
// drill in and pick members.
describe("NodePicker tag selectors (#1491)", () => {
  const villainTag = { name: "villain", scope: { sources: [{ kind: "lore" }] } };

  function renderWithTags(extra: Record<string, unknown> = {}) {
    return render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore" }], multiple: true },
        loreEntries: [
          loreEntry("lore_a", "Vex", ["villain"]),
          loreEntry("lore_b", "Mara", ["hero"]),
          loreEntry("lore_c", "Nok", ["villain"]),
        ],
        affordance: "add",
        ...extra,
      },
    });
  }
  async function openMenu(): Promise<HTMLElement> {
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    return document.querySelector(".ctx-menu") as HTMLElement;
  }

  beforeEach(() => {
    setKnownTags([villainTag] as never);
  });

  it("renders a scoped tag as a selector over its tagged members", async () => {
    renderWithTags();
    const menu = await openMenu();
    const tags = (await within(menu).findAllByRole("group", { name: "Tags" }))[0];
    expect(within(tags).getByText("villain")).toBeInTheDocument();
    // Drill: the villain-tagged lore are its members.
    expect(within(tags).getByText("Vex")).toBeInTheDocument();
    expect(within(tags).getByText("Nok")).toBeInTheDocument();
    // Mara is under the 'hero' tag, not 'villain'.
    expect(within(tags).queryByText("Mara")).toBeNull();
  });

  it("checking a tag stores ONE live selector ref (absorb)", async () => {
    const onChange = vi.fn();
    renderWithTags({ onChange });
    const menu = await openMenu();
    const tags = (await within(menu).findAllByRole("group", { name: "Tags" }))[0];
    await fireEvent.click(within(tags).getByText("villain").closest("button")!);
    await tick();
    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toHaveLength(1);
    expect(detail.value[0]).toMatchObject({ id: "tag:lore:villain", kind: "tag", title: "villain" });
    expect(detail.value[0].selector).toEqual({ kind: "lore", expr: { tagged: "villain" } });
  });

  it("respects the config's entry_type constraint — a tag can't over-match past scope (#1493 review)", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }], multiple: true },
        loreEntries: [
          loreEntry("lore_a", "Vex", ["villain"]), // a character
          // A location sharing the 'villain' tag — must NOT be pulled into a
          // character-restricted input.
          { ...loreEntry("loc_1", "Dark Keep", ["villain"]), entry_type: "lore:location" },
        ],
        affordance: "add",
      },
    });
    const menu = await openMenu();
    const tags = (await within(menu).findAllByRole("group", { name: "Tags" }))[0];
    expect(within(tags).getByText("Vex")).toBeInTheDocument();
    expect(within(tags).queryByText("Dark Keep")).toBeNull();
  });
});

describe("NodePicker onChange callback (runes conversion #49)", () => {
  // The dispatch("change", …) → onChange callback prop is the crux of the runes
  // conversion; lock the payload shape and the multi-select append so a later
  // edit can't silently regress it. Uses a leaf lore source (plot is a container
  // now, ADR-0074 slice 6).
  it("reports the picked ref through onChange with the { value } payload", async () => {
    const onChange = vi.fn();
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore" }] },
        loreEntries: [loreEntry("l1", "Mara Voss", []), loreEntry("l2", "Quill", [])],
        affordance: "add",
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    await fireEvent.click(screen.getByText("Mara Voss").closest("button")!);
    await tick();

    expect(onChange).toHaveBeenCalledTimes(1);
    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toHaveLength(1);
    expect(detail.value[0]).toMatchObject({ id: "l1", kind: "lore" });
  });

  it("appends to the existing value when multiple selection is allowed", async () => {
    const onChange = vi.fn();
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore" }], multiple: true },
        loreEntries: [loreEntry("l1", "Mara Voss", []), loreEntry("l2", "Quill", [])],
        value: [{ id: "l2", kind: "lore", title: "Quill" }],
        affordance: "add",
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    await fireEvent.click(screen.getByText("Mara Voss").closest("button")!);
    await tick();

    const [detail] = onChange.mock.calls[0];
    expect(detail.value.map((r: { id: string }) => r.id)).toEqual(["l2", "l1"]);
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
        config: { sources: [{ kind: "lore" }], multiple: true },
        loreEntries: [loreEntry("l1", "Mara Voss", []), loreEntry("l2", "Quill", [])],
        value: [
          { id: "l1", kind: "lore", title: "Mara Voss" },
          { id: "l2", kind: "lore", title: "Quill" },
        ],
        affordance: "add",
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();

    // "Mara Voss" now renders twice — the candidate row AND the picked chip
    // (both NodeRows, ADR-0068). Scope to the candidate menu; that picked
    // candidate is a live, clickable row (not the old inert one), so clicking
    // it unpicks, leaving the other.
    const menu = document.querySelector(".ctx-menu")!;
    expect(menu).not.toBeNull();
    const row = within(menu as HTMLElement).getByText("Mara Voss").closest("button")!;
    await fireEvent.click(row);
    await tick();

    const [detail] = onChange.mock.calls[0];
    expect(detail.value.map((r: { id: string }) => r.id)).toEqual(["l2"]);
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
