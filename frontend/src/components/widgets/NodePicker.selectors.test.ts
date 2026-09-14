// @vitest-environment happy-dom
// NodePicker selector-axis tests (saved-view + tag selectors), split out of
// NodePicker.test.ts for the file-size cap. Shared harness in NodePicker.testkit.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent, within } from "@/lib/test/component";
import NodePicker from "./NodePicker.svelte";
import { tagNodesStore } from "@/lib/stores/tagNodes";
import { paneViews } from "@/lib/stores/paneViews.svelte";
import type { ViewNodeSummary } from "@/lib/types";
import { loreEntry, expandGroup, setupNodePicker, teardownNodePicker } from "./NodePicker.testkit";

beforeEach(setupNodePicker);
afterEach(teardownNodePicker);

// ADR-0074 Amendment 3 (#1939): saved views are offered APP-WIDE, like the
// By-tag axis — every saved view whose KIND the input accepts appears, with no
// per-input {view:id} source. So a lore input surfaces a lore view purely from
// the app-wide listViews() roster; the config below names only {kind:"lore"}.
// Under the pre-amendment code that same config named no view, so nothing
// showed — the config shape here is the regression guard for the app-wide gate.
describe("NodePicker saved-view selectors — app-wide axis (#1487, #1939)", () => {
  const villainsView: ViewNodeSummary = {
    id: "v1",
    title: "Villains",
    entry_type: "view:view",
    view_kind: "lore",
    spec: { kind: "lore", expr: { tagged: "villain" } },
  };
  // A view of another KIND must not appear on a lore input (kind scoping).
  const scenesView: ViewNodeSummary = {
    id: "m1",
    title: "All scenes",
    entry_type: "view:view",
    view_kind: "manuscript",
    spec: { kind: "manuscript", expr: null },
  };

  function renderLoreInput(extra: Record<string, unknown> = {}) {
    return render(NodePicker, {
      props: {
        allowSelectors: true, // a context_pick input — selectors on (PromptInputField)
        // A LORE input — a kind source only, NO {view:id}. The view rides the
        // app-wide listViews() roster (Amendment 3), not config curation.
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

  // A lore input has two axes (Lore + Saved views) → the root shows axis rows;
  // drill into "Saved views" (ADR-0074 7b) and return that panel. If a sole
  // authored entity_type short-circuited straight into its own panel (#1742),
  // step Back to the root first.
  async function openViewsAxis(menu: HTMLElement): Promise<HTMLElement> {
    const back = within(menu).queryByRole("button", { name: "Back to sources" });
    if (back) {
      await fireEvent.click(back);
      await tick();
    }
    await fireEvent.click(within(menu).getByText("Saved views").closest("button")!);
    await tick();
    return (await within(menu).findAllByRole("group", { name: "Saved views" }))[0];
  }

  beforeEach(() => {
    // Seed the app-wide roster the picker reads (grouped by view_kind), the way
    // App.svelte's loadForProject does — not a per-input {view:id} source.
    paneViews.views = { lore: [villainsView] };
  });
  afterEach(() => vi.restoreAllMocks());

  it("surfaces a lore view app-wide (no {view:id} source) over its live members", async () => {
    renderLoreInput();
    const menu = await openMenu();
    const views = await openViewsAxis(menu);
    expect(within(views).getByText("Villains")).toBeInTheDocument();
    // Collapsed by default (#1520) — expand the view to reveal its members.
    await expandGroup(views, "Villains");
    expect(within(views).getByText("Vex")).toBeInTheDocument();
    expect(within(views).getByText("Nok")).toBeInTheDocument();
    // "Mara" is not tagged villain — not a member.
    expect(within(views).queryByText("Mara")).toBeNull();
  });

  it("does not offer a view whose kind the input rejects (manuscript view on a lore input)", async () => {
    // A manuscript view is grouped under `manuscript`; a lore input reads only
    // viewsFor("lore"), so it is never even considered — kind scoping.
    paneViews.views = { lore: [villainsView], manuscript: [scenesView] };
    renderLoreInput();
    const menu = await openMenu();
    const views = await openViewsAxis(menu);
    expect(within(views).getByText("Villains")).toBeInTheDocument();
    expect(within(menu).queryByText("All scenes")).toBeNull();
  });

  it("checking the view stores ONE live selector ref (absorb)", async () => {
    const onChange = vi.fn();
    renderLoreInput({ onChange });
    const menu = await openMenu();
    const views = await openViewsAxis(menu);
    await fireEvent.click(within(views).getByText("Villains").closest("button")!);
    await tick();
    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toHaveLength(1);
    expect(detail.value[0]).toMatchObject({ id: "view:v1", kind: "view" });
    // A kind-only lore input applies no entry-type clip, so the stored selector
    // is the view's own spec.
    expect(detail.value[0].selector).toEqual(villainsView.spec);
  });

  it("drilling in and checking a member stores that explicit member ref", async () => {
    const onChange = vi.fn();
    renderLoreInput({ onChange });
    const menu = await openMenu();
    const views = await openViewsAxis(menu);
    await expandGroup(views, "Villains");
    await fireEvent.click(within(views).getByText("Vex").closest("button")!);
    await tick();
    const [detail] = onChange.mock.calls[0];
    expect(detail.value).toEqual([expect.objectContaining({ id: "lore_a", kind: "lore" })]);
  });

  it("a search matching no member hides the view (#1488)", async () => {
    renderLoreInput();
    const menu = await openMenu();
    const box = document.querySelector(".ctx-search") as HTMLInputElement;
    // A term matching neither the view title nor any member → the view is gone.
    await fireEvent.input(box, { target: { value: "zzzznope" } });
    await tick();
    expect(within(menu).queryByText("Villains")).toBeNull();
    // A member-name search brings the view back ("Villains" is unique to the view).
    await fireEvent.input(box, { target: { value: "Nok" } });
    await tick();
    expect(within(menu).getByText("Villains")).toBeInTheDocument();
  });

  it("clips a view's members and stored selector to the input's entry types", async () => {
    const onChange = vi.fn();
    render(NodePicker, {
      props: {
        allowSelectors: true,
        // Restrict the lore input to lore:character — a lore:location the view
        // matches by tag must be clipped out (the tagSpecFor-style intersect).
        config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }], multiple: true },
        loreEntries: [
          loreEntry("lore_a", "Vex", ["villain"]), // lore:character
          {
            id: "lore_x",
            title: "Dread Keep",
            body: "",
            entry_type: "lore:location",
            metadata: { tags: ["villain"], aliases: [] },
          } as unknown as import("@/lib/types").LoreEntrySummary,
        ],
        affordance: "add",
        onChange,
      },
    });
    const menu = await openMenu();
    const views = await openViewsAxis(menu);
    await expandGroup(views, "Villains");
    expect(within(views).getByText("Vex")).toBeInTheDocument();
    // The location is tagged villain but the input accepts only characters.
    expect(within(views).queryByText("Dread Keep")).toBeNull();
    await fireEvent.click(within(views).getByText("Villains").closest("button")!);
    await tick();
    const [detail] = onChange.mock.calls[0];
    // Per-type scope (#1947): the config scopes lore:character EXACT (`{type}`), so
    // the stored clip is exact `type` — a lore:location is kept out, and a
    // lore:character:deity would be too (see the family vs exact tests below).
    expect(detail.value[0].selector).toEqual({
      kind: "lore",
      expr: { intersect: [{ tagged: "villain" }, { type: "lore:character" }] },
    });
  });

  it("does not offer the read-only system default view", async () => {
    // The materialized `view_default_lore` (title "Default", system:true) is the
    // pane's implicit default, not a user selection — ViewSwitcher excludes it and
    // so must the picker, or it would show a "Default" row absorbing all lore.
    const systemView: ViewNodeSummary = {
      id: "sys1",
      title: "Default",
      entry_type: "view:view",
      view_kind: "lore",
      system: true,
      spec: { kind: "lore", expr: { descendants_of: "lore:character" } },
    };
    paneViews.views = { lore: [villainsView, systemView] };
    renderLoreInput();
    const menu = await openMenu();
    const views = await openViewsAxis(menu);
    expect(within(views).getByText("Villains")).toBeInTheDocument();
    expect(within(menu).queryByText("Default")).toBeNull();
  });

  it("carries a grouped view WHOLE (its handles), not rewritten to the type roster", async () => {
    // A view with 2+ named handles stores `{groups:[…]}` and NO top-level `expr`.
    // The clip must NOT rewrite it to `{expr:typeExpr}` (which would inject the
    // whole type roster); the stored selector is the view's whole spec.
    const groupedView: ViewNodeSummary = {
      id: "g1",
      title: "Cast by allegiance",
      entry_type: "view:view",
      view_kind: "lore",
      spec: {
        kind: "lore",
        groups: [
          { name: "Heroes", expr: { tagged: "hero" } },
          { name: "Villains", expr: { tagged: "villain" } },
        ],
      },
    };
    paneViews.views = { lore: [groupedView] };
    const onChange = vi.fn();
    render(NodePicker, {
      props: {
        allowSelectors: true,
        // Type-restricted: the buggy path rewrote a grouped view to
        // `{expr:{type:lore:character}}` and pulled in every character.
        config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }], multiple: true },
        loreEntries: [
          loreEntry("lore_a", "Vex", ["villain"]),
          loreEntry("lore_b", "Mara", ["hero"]),
          loreEntry("lore_z", "Bystander", []), // a character in NEITHER handle
        ],
        affordance: "add",
        onChange,
      },
    });
    const menu = await openMenu();
    const views = await openViewsAxis(menu);
    await expandGroup(views, "Cast by allegiance");
    expect(within(views).getByText("Vex")).toBeInTheDocument();
    expect(within(views).getByText("Mara")).toBeInTheDocument();
    // A rewritten `{type}` selector would wrongly include this untagged character;
    // the whole grouped spec resolves only to its handles' members.
    expect(within(views).queryByText("Bystander")).toBeNull();
    await fireEvent.click(within(views).getByText("Cast by allegiance").closest("button")!);
    await tick();
    const [detail] = onChange.mock.calls[0];
    expect(detail.value[0].selector).toEqual(groupedView.spec);
  });
});

// ADR-0074 slice 5 pt.2 (#1491) / ADR-0082 slice 2b: the general tag-node
// vocabulary becomes per-kind tag selectors — absorb "everything tagged X" as
// one live ref, or drill in and pick members. Selector refs name a tag by id
// (`tagged:${kind}:${tag.id}`), not name.
describe("NodePicker tag selectors (#1491)", () => {
  const villainTag = { id: "tag_villain", title: "villain", entry_type: "tag:tag" };

  function renderWithTags(extra: Record<string, unknown> = {}) {
    return render(NodePicker, {
      props: {
        allowSelectors: true, // a context_pick input — selectors on (PromptInputField)
        config: { sources: [{ kind: "lore" }], multiple: true },
        loreEntries: [
          loreEntry("lore_a", "Vex", ["tag_villain"]),
          loreEntry("lore_b", "Mara", ["tag_hero"]),
          loreEntry("lore_c", "Nok", ["tag_villain"]),
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
    tagNodesStore.set([villainTag] as never);
  });

  it("renders a tag node as a selector over its tagged members", async () => {
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

  it("checking a tag stores ONE live selector ref (absorb), keyed by id", async () => {
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
    expect(detail.value[0]).toMatchObject({ id: "tagged:lore:tag_villain", kind: "tag", title: "villain" });
    expect(detail.value[0].selector).toEqual({ kind: "lore", expr: { tagged: "tag_villain" } });
  });

  it("respects the config's entry_type constraint — a tag can't over-match past scope (#1493 review)", async () => {
    render(NodePicker, {
      props: {
        allowSelectors: true,
        config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }], multiple: true },
        loreEntries: [
          loreEntry("lore_a", "Vex", ["tag_villain"]), // a character
          // A location sharing the 'villain' tag — must NOT be pulled into a
          // character-restricted input.
          { ...loreEntry("loc_1", "Dark Keep", ["tag_villain"]), entry_type: "lore:location" },
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

  // Per-type scope is tri-state (#1947): a FAMILY (`descendants_of`) scope includes
  // a specialization under its tag; an EXACT (`type`) scope does not. These two
  // tests pin both directions on the tag-selector path.
  async function openByTag(deityConfig: { descendants_of: string } | { type: string }): Promise<HTMLElement> {
    render(NodePicker, {
      props: {
        allowSelectors: true,
        config: { sources: [{ kind: "lore", expr: deityConfig }], multiple: true },
        loreEntries: [
          loreEntry("lore_a", "Vex", ["tag_villain"]), // a lore:character
          { ...loreEntry("deity_1", "Hespera", ["tag_villain"]), entry_type: "lore:character:deity" },
        ],
        affordance: "add",
      },
    });
    const menu = await openMenu();
    // Sole authored type opens on its own axis (#1742) → Back, then By-tag (ADR-0074 7b).
    await fireEvent.click(within(menu).getByRole("button", { name: "Back to sources" }));
    await tick();
    await fireEvent.click(within(menu).getByText("By tag").closest("button")!);
    await tick();
    return (await within(menu).findAllByRole("group", { name: "By tag" }))[0];
  }

  it("a FAMILY scope includes a specialization under its tag — deity under lore:character (#1947)", async () => {
    const tags = await openByTag({ descendants_of: "lore:character" });
    // Both surface. Under an EXACT scope the count would read "1 match" and Hespera
    // never appears — see the sibling exact test.
    expect(within(tags).getByText("2 matches")).toBeInTheDocument();
    await expandGroup(tags, "villain");
    expect(within(tags).getByText("Vex")).toBeInTheDocument();
    expect(within(tags).getByText("Hespera")).toBeInTheDocument();
  });

  it("an EXACT scope excludes a specialization — deity NOT under a plain lore:character scope (#1947)", async () => {
    const tags = await openByTag({ type: "lore:character" });
    expect(within(tags).getByText("1 match")).toBeInTheDocument();
    await expandGroup(tags, "villain");
    expect(within(tags).getByText("Vex")).toBeInTheDocument();
    expect(within(tags).queryByText("Hespera")).toBeNull();
  });

  it("offers a user-authored vocabulary (tag:motifs) as a By-tag row, but never tag:assistant_tag (review)", async () => {
    const motifTag = { id: "tag_mirrors", title: "mirrors", entry_type: "tag:motifs" };
    const assistantTag = { id: "tag_editor", title: "Editor", entry_type: "tag:assistant_tag" };
    tagNodesStore.set([villainTag, motifTag, assistantTag] as never);
    render(NodePicker, {
      props: {
        allowSelectors: true,
        config: { sources: [{ kind: "lore" }], multiple: true },
        loreEntries: [loreEntry("lore_a", "Vex", ["tag_mirrors"])],
        affordance: "add",
      },
    });
    const menu = await openMenu();
    await fireEvent.click(within(menu).getByText("By tag").closest("button")!);
    await tick();
    const tags = (await within(menu).findAllByRole("group", { name: "By tag" }))[0];
    // tag:motifs is first-class — its tagged member surfaces the row.
    expect(within(tags).getByText("mirrors")).toBeInTheDocument();
    // tag:assistant_tag is the assistant/prompt vocabulary, never offered here
    // (it has no lore members either way, but the exclusion is by entry_type,
    // not just the members guard).
    expect(within(tags).queryByText("Editor")).toBeNull();
  });
});

