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
import { setPalette } from "@/lib/utils/colors";
import { hideLibraryEntry, openProjectHidden } from "@/lib/stores/hiddenLibrary";
import type { MetadataSchema, PlotlineSummary, PromptEntrySummary, ViewNodeSummary } from "@/lib/types";

const SCHEMA = {
  entry_types: {
    "prompt:snippet": { name: "Snippet", kind: "prompt" },
    "prompt:voice_note": { name: "Voice note", kind: "prompt", parent: "prompt:snippet" },
    "prompt:general": { name: "General", kind: "prompt" },
    "plot:plotline": { name: "Plotline", kind: "plot" },
    "plot:card": { name: "Card", kind: "plot" },
    "lore:character": { name: "Character", kind: "lore" },
    "tag:tag": { name: "Tag", kind: "tag" },
    "tag:assistant_tag": { name: "Assistant tag", kind: "tag" },
    "tag:base": { name: "Tag", kind: "tag", abstract: true },
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

function snippet(id: string, title: string, entryType = "prompt:snippet"): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    entry_type: entryType,
    metadata: {},
    computed_metadata: {},
    inputs: [],
    is_library: true,
  };
}

function plotline(id: string, title: string): PlotlineSummary {
  return { id, title, body: "", entry_type: "plot:plotline", metadata: {} };
}

// Collapse-by-default (#1520): every container (act/chapter, tag, view, plotline,
// lore entry-type) opens collapsed, so a test that wants to see or click a member
// first expands the container by its caret ("Expand <title>").
async function expandGroup(scope: HTMLElement, title: string) {
  await fireEvent.click(within(scope).getByRole("button", { name: `Expand ${title}` }));
  await tick();
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
        // A snippet-kind source with no entry_type leaves → the whole prompt
        // roster (see the by-design note below).
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

describe("NodePicker snippet category — the whole prompt roster, BY DESIGN (#1688)", () => {
  it("offers invocable prompts too: hand-picking a prompt-kind view routes through this group", async () => {
    // The Category enum has no "prompt", so ViewFlowNode maps a prompt-kind
    // hand_picked source through the "snippet" category. #1688 tried filtering
    // this roster to snippet-typed prompts and it broke that only live
    // consumer — this pin keeps the roster whole.
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "snippet" }] },
        promptEntries: [
          snippet("sub", "Voice note", "prompt:voice_note"),
          snippet("gen", "Brainstorm beats", "prompt:general"),
        ],
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    expect(screen.getByText("Voice note")).toBeInTheDocument();
    expect(screen.getByText("Brainstorm beats")).toBeInTheDocument();
  });
});

// The search box auto-focuses when the picker opens. Pinned because #1538 moved
// `searchInputEl` across a component boundary: it now binds up from
// NodePickerPopover via `$bindable`, and the controller focuses it after a tick.
// Nothing else asserts that cross-component bind + focus still lands.
describe("NodePicker open-focus (#1538)", () => {
  it("focuses the search box when the menu opens", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "snippet" }] },
        promptEntries: [snippet("a", "Alpha")],
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    await tick(); // let the controller's post-open `await tick()` + focus() flush

    const searchBox = screen.getByPlaceholderText(/Search/i);
    expect(document.activeElement).toBe(searchBox);
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

    const plot = (await screen.findAllByRole("group", { name: "Plot" }))[0];
    expect(within(plot).getByText("The Heist")).toBeInTheDocument();
    expect(within(plot).getByText("Romance")).toBeInTheDocument();
    // Collapsed by default (#1520) — expand each plotline to reveal its cards.
    await expandGroup(plot, "The Heist");
    await expandGroup(plot, "Romance");
    expect(within(plot).getByText("Break-in")).toBeInTheDocument();
    expect(within(plot).getByText("Getaway")).toBeInTheDocument();
    expect(within(plot).queryByText("A kiss")).not.toBeNull(); // under Romance
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

    const plot = (await screen.findAllByRole("group", { name: "Plot" }))[0];
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

    const plot = (await screen.findAllByRole("group", { name: "Plot" }))[0];
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

    const plot = (await screen.findAllByRole("group", { name: "Plot" }))[0];
    await expandGroup(plot, "The Heist");
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
    // Chapter One is collapsed by default (#1520) — open it to reach its scenes.
    await fireEvent.click(screen.getByRole("button", { name: "Expand Chapter One" }));
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
    // Chapter One is collapsed by default (#1520) — open it to reach its scenes.
    await fireEvent.click(screen.getByRole("button", { name: "Expand Chapter One" }));
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
    // The chapter is collapsed by default (#1520); the root stays open.
    await expandGroup(menu, "Chapter One");
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

  // #1520 follow-up (Anton's dogfood): a chapter that carries its OWN scene_id
  // must not be dropped when the config restricts scene types. flattenManuscript's
  // visibility check classified scene-vs-container by `node.scene_id`, so a chapter
  // (which has a backing scene_id) was run through the scene allowlist and filtered
  // — hiding the chapter AND its child scene, while the root still counted them.
  it("keeps a scene_id-bearing chapter under a scene-restricted config", async () => {
    const nested = {
      root: {
        id: "root",
        type: "root",
        title: "Manuscript",
        scene_id: null,
        children: [
          { id: "s_a", type: "manuscript:scene", scene_id: "sa", title: "Untitled Scene" },
          {
            id: "ch",
            type: "manuscript:chapter",
            scene_id: "chp", // a chapter with its own backing prose file
            title: "Chapter",
            children: [{ id: "s_b", type: "manuscript:scene", scene_id: "sb", title: "Nested Scene" }],
          },
        ],
      },
    } as never;
    render(NodePicker, {
      props: {
        // Restricts to scenes — the allowlist that used to swallow the chapter.
        config: { sources: [{ kind: "manuscript", expr: { type: "manuscript:scene" } }] },
        structure: nested,
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    expect(within(menu).getByText("Untitled Scene")).toBeInTheDocument();
    // The chapter shows (a pickable container), not swallowed by the scene filter.
    expect(within(menu).getByText("Chapter")).toBeInTheDocument();
    await expandGroup(menu, "Chapter");
    expect(within(menu).getByText("Nested Scene")).toBeInTheDocument();
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
    // Collapsed by default (#1520) — expand the view to reveal its members.
    await expandGroup(menu, "Villains");
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
    await expandGroup(menu, "Villains");
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
    // Multi-axis config (Lore + By tag) → drill into the By-tag axis (ADR-0074 7b).
    await fireEvent.click(within(menu).getByText("By tag").closest("button")!);
    await tick();
    const tags = (await within(menu).findAllByRole("group", { name: "By tag" }))[0];
    expect(within(tags).getByText("villain")).toBeInTheDocument();
    // The count pluralizes correctly — "matches", not the old "matchs" (slice 7a).
    expect(within(tags).getByText("2 matches")).toBeInTheDocument();
    // Collapsed by default (#1520) — expand the tag to reveal its members.
    await expandGroup(tags, "villain");
    expect(within(tags).getByText("Vex")).toBeInTheDocument();
    expect(within(tags).getByText("Nok")).toBeInTheDocument();
    // Mara is under the 'hero' tag, not 'villain'.
    expect(within(tags).queryByText("Mara")).toBeNull();
  });

  it("checking a tag stores ONE live selector ref (absorb)", async () => {
    const onChange = vi.fn();
    renderWithTags({ onChange });
    const menu = await openMenu();
    // Multi-axis config (Lore + By tag) → drill into the By-tag axis (ADR-0074 7b).
    await fireEvent.click(within(menu).getByText("By tag").closest("button")!);
    await tick();
    const tags = (await within(menu).findAllByRole("group", { name: "By tag" }))[0];
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
    // The sole authored type (lore:character) now opens on its own axis (#1742),
    // so go Back to the root to reach the By-tag axis, then drill in (ADR-0074 7b).
    await fireEvent.click(within(menu).getByRole("button", { name: "Back to sources" }));
    await tick();
    await fireEvent.click(within(menu).getByText("By tag").closest("button")!);
    await tick();
    const tags = (await within(menu).findAllByRole("group", { name: "By tag" }))[0];
    await expandGroup(tags, "villain");
    expect(within(tags).getByText("Vex")).toBeInTheDocument();
    expect(within(tags).queryByText("Dark Keep")).toBeNull();
  });
});

describe("NodePicker tag-kind member picks (ADR-0082 slice 1)", () => {
  async function openMenu(): Promise<HTMLElement> {
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    return document.querySelector(".ctx-menu") as HTMLElement;
  }

  // A picker whose only source is kind "tag" (a real tag NODE, not the
  // legacy `tags` field's scoped-selector literal above) lists tag entries
  // as plain member picks — the "Tags" group — and offers no "By tag"
  // selector axis: `buildSelectorRoster` registers no roster for kind "tag",
  // so every candidate selector resolves to zero members and is dropped
  // (review fix F3 — no code change needed, the existing member/selector
  // split already keeps the two apart; this pins the behaviour).
  it("renders the Tags member group and no By-tag selector axis", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "tag" }], multiple: true },
        tagEntries: [
          { id: "tag_1", title: "Coastal", entry_type: "tag:tag", metadata: {} },
          { id: "tag_2", title: "Urban", entry_type: "tag:tag", metadata: {} },
        ],
        affordance: "add",
      },
    });
    const menu = await openMenu();
    // The sole axis renders directly — no root chooser, no "By tag" anywhere.
    expect(within(menu).getByText("Coastal")).toBeInTheDocument();
    expect(within(menu).getByText("Urban")).toBeInTheDocument();
    expect(within(menu).queryByText("By tag")).toBeNull();
  });
});

describe("NodePicker create row (ADR-0082 §2 / F1)", () => {
  async function openMenu(): Promise<HTMLElement> {
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    return document.querySelector(".ctx-menu") as HTMLElement;
  }
  async function type(q: string) {
    const box = document.querySelector(".ctx-search") as HTMLInputElement;
    await fireEvent.input(box, { target: { value: q } });
    await tick();
  }

  const CREATE_MISSING_CONFIG = {
    sources: [{ kind: "tag", expr: { type: "tag:tag" } }],
    create_missing: true,
    multiple: true,
  };
  const TAGS = [{ id: "tag_1", title: "Coastal", entry_type: "tag:tag", metadata: {} }];

  it("shows the create row when all four conditions hold", async () => {
    render(NodePicker, {
      props: { config: CREATE_MISSING_CONFIG, tagEntries: TAGS, affordance: "add" },
    });
    const menu = await openMenu();
    await type("Urban");
    expect(within(menu).getByTestId("node-picker-create")).toBeInTheDocument();
    expect(within(menu).getByText("Create “Urban”")).toBeInTheDocument();
  });

  it("hides the row when create_missing is unset", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "tag", expr: { type: "tag:tag" } }], multiple: true },
        tagEntries: TAGS,
        affordance: "add",
      },
    });
    const menu = await openMenu();
    await type("Urban");
    expect(within(menu).queryByTestId("node-picker-create")).toBeNull();
  });

  it("hides the row when the config resolves to more than one entry type", async () => {
    render(NodePicker, {
      props: {
        config: {
          sources: [
            { kind: "tag", expr: { union: [{ type: "tag:tag" }, { type: "tag:assistant_tag" }] } },
          ],
          create_missing: true,
          multiple: true,
        },
        tagEntries: TAGS,
        affordance: "add",
      },
    });
    const menu = await openMenu();
    await type("Urban");
    expect(within(menu).queryByTestId("node-picker-create")).toBeNull();
  });

  it("hides the row when the search is empty", async () => {
    render(NodePicker, {
      props: { config: CREATE_MISSING_CONFIG, tagEntries: TAGS, affordance: "add" },
    });
    const menu = await openMenu();
    expect(within(menu).queryByTestId("node-picker-create")).toBeNull();
  });

  it("hides the row when a candidate already matches the search case-insensitively by title", async () => {
    render(NodePicker, {
      props: { config: CREATE_MISSING_CONFIG, tagEntries: TAGS, affordance: "add" },
    });
    const menu = await openMenu();
    await type("coastal");
    expect(within(menu).queryByTestId("node-picker-create")).toBeNull();
    expect(within(menu).getByText("Coastal")).toBeInTheDocument();
  });

  it("onCreate receives the typed title and the resolved entry_type", async () => {
    const onCreate = vi.fn();
    render(NodePicker, {
      props: { config: CREATE_MISSING_CONFIG, tagEntries: TAGS, affordance: "add", onCreate },
    });
    const menu = await openMenu();
    await type("Urban");
    await fireEvent.click(within(menu).getByTestId("node-picker-create"));
    expect(onCreate).toHaveBeenCalledWith("Urban", "tag:tag");
  });
});

describe("NodePicker sole allowed type (#1735 / #1742)", () => {
  async function openMenu(): Promise<HTMLElement> {
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    return document.querySelector(".ctx-menu") as HTMLElement;
  }

  it("opens the sole allowed lore type expanded — no collapse to click through", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }] },
        loreEntries: [loreEntry("l1", "Mara Voss", []), loreEntry("l2", "Quill", [])],
        affordance: "add",
      },
    });
    const menu = await openMenu();
    // The single allowed type's entries are visible immediately — no "Expand
    // Character" step (the lone collapsed-group friction is gone).
    expect(within(menu).getByText("Mara Voss")).toBeInTheDocument();
    expect(within(menu).getByText("Quill")).toBeInTheDocument();
    expect(within(menu).queryByRole("button", { name: "Expand Character" })).toBeNull();
  });

  it("keeps a broad { kind: lore } config collapsed — not an authored single type", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore" }] },
        loreEntries: [loreEntry("l1", "Mara Voss", [])],
        affordance: "add",
      },
    });
    const menu = await openMenu();
    // Broad config (all lore types allowed) → the group still opens collapsed even
    // when the project happens to hold one sub-type; the entry sits behind the caret.
    expect(within(menu).queryByText("Mara Voss")).toBeNull();
    expect(
      within(menu).getByRole("button", { name: "Expand Character" }),
    ).toBeInTheDocument();
  });

  it("still opens on the sole type's entries when a By-tag axis coexists (#1742)", async () => {
    // A lore-scoped tag adds a "By tag" axis, so the picker is no longer a single
    // axis — but a sole authored type must STILL land on its entries, not a
    // Lore/By-tag chooser (the real-project gap #1735 missed).
    setKnownTags([{ name: "villain", scope: { sources: [{ kind: "lore" }] } }] as never);
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }] },
        loreEntries: [loreEntry("l1", "Mara Voss", ["villain"]), loreEntry("l2", "Quill", [])],
        affordance: "add",
      },
    });
    const menu = await openMenu();
    // Characters show immediately even though a By-tag axis exists…
    expect(within(menu).getByText("Mara Voss")).toBeInTheDocument();
    expect(within(menu).getByText("Quill")).toBeInTheDocument();
    // …and "Back to sources" is there to reach the By-tag axis when wanted.
    expect(within(menu).getByRole("button", { name: "Back to sources" })).toBeInTheDocument();
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
    // Lore is grouped by type; open the "Character" section (#1520).
    await fireEvent.click(screen.getByRole("button", { name: "Expand Character" }));
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
    // Lore is grouped by type; open the "Character" section (#1520).
    await fireEvent.click(screen.getByRole("button", { name: "Expand Character" }));
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
    await expandGroup(menu as HTMLElement, "Character");
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

// ADR-0074 slice 7b: the picker is a drill-in popover — a root axis list, drill
// into one axis, ← back to return. Search is contextual (cross-axis at root).
describe("NodePicker drill-in navigation (ADR-0074 slice 7b)", () => {
  function renderMulti(extra: Record<string, unknown> = {}) {
    return render(NodePicker, {
      props: {
        // Two axes (Lore + Snippets) → the root axis list, not a short-circuit.
        config: { sources: [{ kind: "lore" }, { kind: "snippet" }], multiple: true },
        loreEntries: [loreEntry("l1", "Mara Voss", []), loreEntry("l2", "Quill", [])],
        promptEntries: [snippet("s1", "Rephrase")],
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

  it("opens on the root axis list; a source's rows appear only after drilling in", async () => {
    renderMulti();
    const menu = await openMenu();
    // Axis rows, not the entries.
    expect(within(menu).getByText("Lore")).toBeInTheDocument();
    expect(within(menu).getByText("Snippets")).toBeInTheDocument();
    expect(within(menu).queryByText("Mara Voss")).toBeNull();
    // Drill into Lore → its entries; the other axis's rows stay out of this panel.
    await fireEvent.click(within(menu).getByText("Lore").closest("button")!);
    await tick();
    // Drilled into Lore → the "Character" section; open it for the entries (#1520).
    await expandGroup(menu, "Character");
    expect(within(menu).getByText("Mara Voss")).toBeInTheDocument();
    expect(within(menu).getByText("Quill")).toBeInTheDocument();
    expect(within(menu).queryByText("Rephrase")).toBeNull();
  });

  it("← back returns to the root axis list", async () => {
    renderMulti();
    const menu = await openMenu();
    await fireEvent.click(within(menu).getByText("Lore").closest("button")!);
    await tick();
    await expandGroup(menu, "Character");
    expect(within(menu).getByText("Mara Voss")).toBeInTheDocument();
    await fireEvent.click(within(menu).getByRole("button", { name: "Back to sources" }));
    await tick();
    expect(within(menu).getByText("Snippets")).toBeInTheDocument();
    expect(within(menu).queryByText("Mara Voss")).toBeNull();
  });

  it("a single-axis config skips the root list and shows the panel directly", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore" }], multiple: true },
        loreEntries: [loreEntry("l1", "Mara Voss", [])],
        affordance: "add",
      },
    });
    const menu = await openMenu();
    // No drill, no back button — the sole axis renders as the panel.
    await expandGroup(menu, "Character");
    expect(within(menu).getByText("Mara Voss")).toBeInTheDocument();
    expect(within(menu).queryByRole("button", { name: "Back to sources" })).toBeNull();
  });

  it("a query at the root cuts across every axis", async () => {
    renderMulti();
    const menu = await openMenu();
    const box = menu.querySelector(".ctx-search") as HTMLInputElement;
    // "r" matches Mara (lore) and Rephrase (snippet) — both axes surface at once.
    await fireEvent.input(box, { target: { value: "r" } });
    await tick();
    expect(within(menu).getByText("Mara Voss")).toBeInTheDocument();
    expect(within(menu).getByText("Rephrase")).toBeInTheDocument();
    // Not the axis list — the Snippets axis ROW is replaced by its result rows.
    expect(within(menu).queryByRole("button", { name: "Back to sources" })).toBeNull();
  });

  it("clicking the checkbox itself toggles the pick, not only the title", async () => {
    const onChange = vi.fn();
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore" }], multiple: true },
        loreEntries: [loreEntry("l1", "Mara Voss", [])],
        affordance: "add",
        onChange,
      },
    });
    const menu = await openMenu();
    await expandGroup(menu, "Character");
    // The checkbox is its own click target (mouse convenience), not an inert glyph.
    // The type header carries no check, so the first .ctx-row-check is the entry's.
    const check = menu.querySelector(".ctx-row-check") as HTMLButtonElement;
    expect(check).not.toBeNull();
    await fireEvent.click(check);
    await tick();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].value[0]).toMatchObject({ id: "l1", kind: "lore" });
  });
});

// #1520 follow-up: a node's own metadata.color (instance override, e.g. the
// Aetheria lore entry's `color: crimson`) must win over the type/kind default in
// the picker stripe. It was dropped — hexForRef passed null to resolveColor — so
// a custom-coloured entry showed the kind default like every other row.
describe("NodePicker instance colour (#1520)", () => {
  const COLOUR_SCHEMA = {
    entry_types: { "lore:character": { name: "Character", kind: "lore", color: "type-blue" } },
    fields: {},
  } as unknown as MetadataSchema;

  function loreWithColour(id: string, title: string, colour: string | null) {
    return {
      id,
      title,
      body: "",
      entry_type: "lore:character",
      metadata: colour ? { color: colour } : {},
    } as unknown as import("@/lib/types").LoreEntrySummary;
  }

  beforeEach(() => {
    metadataSchemaStore.set(COLOUR_SCHEMA);
    setPalette([
      { id: "type-blue", label: "Type Blue", hex: "#0000ff" },
      { id: "crimson", label: "Crimson", hex: "#dc143c" },
    ]);
  });
  afterEach(() => setPalette([]));

  it("honours a lore entry's own metadata.color over the type default", async () => {
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore" }], multiple: true },
        loreEntries: [loreWithColour("l1", "Aetheria", "crimson"), loreWithColour("l2", "Plainly", null)],
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    await fireEvent.click(within(menu).getByRole("button", { name: "Expand Character" }));
    await tick();

    const custom = within(menu).getByText("Aetheria").closest(".node-row") as HTMLElement;
    const plain = within(menu).getByText("Plainly").closest(".node-row") as HTMLElement;
    // The custom entry uses its instance swatch; the plain one falls back to the
    // type default — they must differ.
    expect(custom.style.getPropertyValue("--row-stripe")).toBe("#dc143c");
    expect(plain.style.getPropertyValue("--row-stripe")).toBe("#0000ff");
  });

  // #1528 follow-up: a member must carry its own colour in a tag's list too — the
  // member ref drops metadata, so it resolves through the ref→colour index.
  it("honours a member's instance colour in a tag's list", async () => {
    setKnownTags([{ name: "epic", scope: { sources: [{ kind: "lore" }] } }] as never);
    render(NodePicker, {
      props: {
        config: { sources: [{ kind: "lore" }], multiple: true },
        loreEntries: [
          {
            id: "l1",
            title: "Aetheria",
            body: "",
            entry_type: "lore:character",
            metadata: { color: "crimson", tags: ["epic"] },
          } as unknown as import("@/lib/types").LoreEntrySummary,
        ],
        affordance: "add",
      },
    });
    await fireEvent.click(screen.getByRole("button", { expanded: false }));
    await tick();
    const menu = document.querySelector(".ctx-menu") as HTMLElement;
    // Multi-axis (Lore + By tag) → drill into the By-tag axis, then expand the tag.
    await fireEvent.click(within(menu).getByText("By tag").closest("button")!);
    await tick();
    const tags = (await within(menu).findAllByRole("group", { name: "By tag" }))[0];
    await expandGroup(tags, "epic");
    const member = within(tags).getByText("Aetheria").closest(".node-row") as HTMLElement;
    expect(member.style.getPropertyValue("--row-stripe")).toBe("#dc143c");
  });
});
