// @vitest-environment happy-dom
// ReferencePicker had no test. The #49 runes port turns its `change` / `navigate`
// CustomEvents into `onChange` / `onNavigate` callback props. These lock both:
// a row click reports the navigation target, and removing a ref reports the
// reduced id list. Refs resolve from the in-memory loreEntries prop; a null
// schema is fine (the type pill falls back to the raw entry_type).
//
// The `embedded` block covers #1216: in the metadata rail the field row already
// prints the label, so the embedded picker must drop its own titled header
// (which doubled the label) while keeping the expand/collapse control.
import { afterEach, describe, it, expect, vi } from "vitest";
import { tick } from "svelte";
import { get } from "svelte/store";
import { render, screen, fireEvent } from "@/lib/test/component";
import ReferencePicker from "./ReferencePicker.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { clearTagNodes, tagById, tagNodesStore } from "@/lib/stores/tagNodes";
import { api } from "@/lib/api";
import type { LoreEntrySummary, MetadataFieldDefinition, TagEntry } from "@/lib/types";

const field = {
  name: "Characters",
  type: "entity_ref_list",
  options: [],
  picker_config: { sources: [{ kind: "lore" }] },
} as unknown as MetadataFieldDefinition;

const loreEntries = [
  { id: "lore_1", title: "Mira", entry_type: "lore:character" },
  { id: "lore_2", title: "Jonas", entry_type: "lore:character" },
  { id: "lore_3", title: "Cato", entry_type: "lore:character" },
] as unknown as LoreEntrySummary[];

afterEach(() => {
  metadataSchemaStore.set(null);
  clearTagNodes();
  // Several create_missing tests spy on api.createTagEntry / api.listTagEntries
  // without their own restore — a leftover mock otherwise silently short-
  // circuits a LATER test's real create path.
  vi.restoreAllMocks();
});

describe("ReferencePicker — callback props (runes port of change/navigate)", () => {
  it("reports the navigation target through onNavigate on a row click", async () => {
    const onNavigate = vi.fn();
    render(ReferencePicker, {
      props: { field, value: ["lore_1"], ariaLabel: "Characters", loreEntries, onNavigate },
    });
    // Collapsed by default — expand the group, then click the resolved row.
    await fireEvent.click(screen.getByText("Characters"));
    await fireEvent.click(screen.getByText("Mira"));
    expect(onNavigate).toHaveBeenCalledWith({ id: "lore_1", kind: "lore" });
  });

  it("removing a ref reports the reduced id list through onChange", async () => {
    const onChange = vi.fn();
    render(ReferencePicker, {
      props: { field, value: ["lore_1", "lore_2"], ariaLabel: "Characters", loreEntries, onChange },
    });
    await fireEvent.click(screen.getByText("Characters"));
    await fireEvent.click(screen.getByLabelText("Remove Mira"));
    // entity_ref_list → the list shape is preserved; only Mira drops out.
    expect(onChange).toHaveBeenCalledWith(["lore_2"]);
  });
});

describe("ReferencePicker — embedded header (#1216)", () => {
  it("standalone: renders its own titled header carrying the field label", () => {
    render(ReferencePicker, {
      props: { field, value: [], ariaLabel: "Characters", readOnly: true },
    });
    // Correct when the picker stands alone (chat diff, draft card): the title is
    // the only label the value has.
    expect(screen.getByText("Characters")).toBeInTheDocument();
  });

  it("embedded: drops the duplicate label but keeps expand/collapse", async () => {
    render(ReferencePicker, {
      props: { field, value: [], ariaLabel: "Characters", readOnly: true, embedded: true },
    });
    // The rail already shows the label, so the picker must NOT repeat it as text.
    expect(screen.queryByText("Characters")).not.toBeInTheDocument();

    // The collapse control survives — its accessible name still names the field.
    const toggle = screen.getByRole("button", { name: /characters/i });
    // Collapsed by default; expanding reveals the (empty) reference list.
    expect(screen.queryByText("No references.")).not.toBeInTheDocument();
    await fireEvent.click(toggle);
    expect(screen.getByText("No references.")).toBeInTheDocument();
  });
});

describe("ReferencePicker — controlled rail mode (#1732)", () => {
  // In the rail a reference renders as an inline pill, always visible — no
  // title, no caret, no expand. A single `entity_ref` and an `entity_ref_list`
  // render identical pills. `expanded` now drives the fold (#1884 slice 2) for a
  // `multi` field — see the "fold to first row" describe block below; for a
  // single `entity_ref` it stays vestigial (never folds).
  it("controlled: renders no title and no caret/toggle button", () => {
    render(ReferencePicker, {
      props: { field, value: [], ariaLabel: "Characters", readOnly: true, embedded: true, controlled: true },
    });
    expect(screen.queryByText("Characters")).not.toBeInTheDocument();
    // No picker-owned toggle and no field caret — the pills stand on their own.
    expect(screen.queryByRole("button", { name: /characters/i })).toBeNull();
  });

  it("controlled: renders each ref as an always-visible pill, no expand needed", () => {
    render(ReferencePicker, {
      props: { field, value: ["lore_1", "lore_2"], ariaLabel: "Characters", loreEntries, embedded: true, controlled: true },
    });
    // Both refs show inline without any expand click; the old collapsible list
    // (and its "No references." empty state) is gone.
    expect(screen.getByText("Mira")).toBeInTheDocument();
    expect(screen.getByText("Jonas")).toBeInTheDocument();
    expect(screen.queryByText("No references.")).not.toBeInTheDocument();
  });

  it("controlled: an empty field renders no pills and no list, whatever `expanded` says", () => {
    const { container } = render(ReferencePicker, {
      props: { field, value: [], ariaLabel: "Characters", embedded: true, controlled: true, expanded: true },
    });
    expect(container.textContent).not.toContain("No references.");
    expect(container.querySelector(".ref-pill")).toBeNull();
  });

  it("controlled: clicking a pill reports the navigation target through onNavigate", async () => {
    const onNavigate = vi.fn();
    render(ReferencePicker, {
      props: { field, value: ["lore_1"], ariaLabel: "Characters", loreEntries, embedded: true, controlled: true, onNavigate },
    });
    await fireEvent.click(screen.getByText("Mira"));
    expect(onNavigate).toHaveBeenCalledWith({ id: "lore_1", kind: "lore" });
  });

  it("controlled: a pill's × reports the reduced id list through onChange", async () => {
    const onChange = vi.fn();
    render(ReferencePicker, {
      props: { field, value: ["lore_1", "lore_2"], ariaLabel: "Characters", loreEntries, embedded: true, controlled: true, onChange },
    });
    await fireEvent.click(screen.getByLabelText("Remove Mira"));
    expect(onChange).toHaveBeenCalledWith(["lore_2"]);
  });
});

describe("ReferencePicker — fold to first row (#1884 slice 2)", () => {
  const singleField = {
    name: "Home Place",
    type: "entity_ref",
    options: [],
    picker_config: { sources: [{ kind: "lore" }] },
  } as unknown as MetadataFieldDefinition;

  it("no layout (happy-dom, all rects zero) degrades to everything fits: no chip, all pills, add trigger", () => {
    render(ReferencePicker, {
      props: {
        field,
        value: ["lore_1", "lore_2", "lore_3"],
        ariaLabel: "Characters",
        loreEntries,
        embedded: true,
        controlled: true,
        expanded: false,
      },
    });
    expect(screen.getByText("Mira")).toBeInTheDocument();
    expect(screen.getByText("Jonas")).toBeInTheDocument();
    expect(screen.getByText("Cato")).toBeInTheDocument();
    expect(document.querySelector(".ref-pill-more")).toBeNull();
    expect(screen.getByRole("button", { name: "Add Characters" })).toBeInTheDocument();
  });

  it("no layout: a value that grows after mount still fits — the action re-reads its params on update", async () => {
    // Pins `update(next)` taking the NEW total: with the stale total (2) the
    // no-layout fallback would report 2 visible of 3 and conjure a `+1` chip.
    const props = {
      field,
      value: ["lore_1", "lore_2"],
      ariaLabel: "Characters",
      loreEntries,
      embedded: true,
      controlled: true,
      expanded: false,
    };
    const { rerender } = render(ReferencePicker, { props });
    await rerender({ ...props, value: ["lore_1", "lore_2", "lore_3"] });
    expect(document.querySelectorAll(".ref-pill-slot")).toHaveLength(3);
    expect(document.querySelectorAll(".ref-pill-slot.overflow")).toHaveLength(0);
    expect(document.querySelector(".ref-pill-more")).toBeNull();
  });

  it("single entity_ref never folds, whatever expanded says", () => {
    render(ReferencePicker, {
      props: {
        field: singleField,
        value: "lore_1",
        ariaLabel: "Home Place",
        loreEntries,
        embedded: true,
        controlled: true,
        expanded: false,
      },
    });
    expect(screen.getByText("Mira")).toBeInTheDocument();
    expect(document.querySelector(".ref-pill-more")).toBeNull();
    expect(screen.getByRole("button", { name: "Change Home Place" })).toBeInTheDocument();
  });

  describe("with a stubbed layout", () => {
    // happy-dom reports every rect at zero, so the fold degrades to "everything
    // fits" (above) — this pins the real fold arithmetic by stubbing
    // getBoundingClientRect per element: the row is 200px wide; pills 0 and 1
    // sit on the first line (rights 60, 120), pill 2 wraps to a second line
    // (top 24) — with a 40px fallback chip width and a 0 gap, 2 pills leave
    // room for the chip (120 + 40 = 160 ≤ 200), so the fold keeps 2 and hides 1.
    afterEach(() => vi.restoreAllMocks());

    function stubLayout() {
      vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
        this: HTMLElement,
      ) {
        const zero = { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON() {} };
        if (this.classList.contains("ref-pill-row")) {
          return { ...zero, right: 200, width: 200, bottom: 24, height: 24 };
        }
        if (this.classList.contains("ref-pill") && !this.classList.contains("ref-pill-more")) {
          const pills = [...document.querySelectorAll(".ref-pill:not(.ref-pill-more)")];
          const idx = pills.indexOf(this);
          const defs = [
            { top: 0, right: 60 },
            { top: 0, right: 120 },
            { top: 24, right: 180 },
          ];
          const def = defs[idx] ?? { top: 0, right: 0 };
          return { ...zero, top: def.top, right: def.right, width: def.right, bottom: def.top + 24, height: 24 };
        }
        return zero;
      });
    }

    it("folds to 2 pills + a +1 chip; clicking the chip calls onToggleExpanded", async () => {
      stubLayout();
      const onToggleExpanded = vi.fn();
      render(ReferencePicker, {
        props: {
          field,
          value: ["lore_1", "lore_2", "lore_3"],
          ariaLabel: "Characters",
          loreEntries,
          embedded: true,
          controlled: true,
          expanded: false,
          onToggleExpanded,
        },
      });
      // happy-dom doesn't enforce `display: none` for text queries, so assert
      // the fold's own bookkeeping (the `overflow` class) rather than visibility.
      const slots = document.querySelectorAll(".ref-pill-slot");
      expect(slots).toHaveLength(3);
      expect(slots[0].classList.contains("overflow")).toBe(false);
      expect(slots[1].classList.contains("overflow")).toBe(false);
      expect(slots[2].classList.contains("overflow")).toBe(true);
      const chip = screen.getByText("+1");
      await fireEvent.click(chip);
      expect(onToggleExpanded).toHaveBeenCalledOnce();
    });

    it("flipping `expanded` after mount re-measures: unfold shows all, fold hides again (the action's update path)", async () => {
      stubLayout();
      const props = {
        field,
        value: ["lore_1", "lore_2", "lore_3"],
        ariaLabel: "Characters",
        loreEntries,
        embedded: true,
        controlled: true,
        expanded: false,
      };
      const { rerender } = render(ReferencePicker, { props });
      expect(document.querySelectorAll(".ref-pill-slot.overflow")).toHaveLength(1);
      expect(document.querySelector(".ref-pill-more")).not.toBeNull();

      await rerender({ ...props, expanded: true });
      expect(document.querySelectorAll(".ref-pill-slot.overflow")).toHaveLength(0);
      expect(document.querySelector(".ref-pill-more")).toBeNull();
      expect(screen.getByRole("button", { name: "Add Characters" })).toBeInTheDocument();

      await rerender({ ...props, expanded: false });
      expect(document.querySelectorAll(".ref-pill-slot.overflow")).toHaveLength(1);
      expect(screen.getByText("+1")).toBeInTheDocument();
    });

    it("expanded: true shows every pill, no chip, add trigger present", () => {
      stubLayout();
      render(ReferencePicker, {
        props: {
          field,
          value: ["lore_1", "lore_2", "lore_3"],
          ariaLabel: "Characters",
          loreEntries,
          embedded: true,
          controlled: true,
          expanded: true,
        },
      });
      expect(screen.getByText("Mira")).toBeInTheDocument();
      expect(screen.getByText("Jonas")).toBeInTheDocument();
      expect(screen.getByText("Cato")).toBeInTheDocument();
      expect(document.querySelector(".ref-pill-more")).toBeNull();
      expect(screen.getByRole("button", { name: "Add Characters" })).toBeInTheDocument();
    });
  });
});

describe("ReferencePicker — tag node resolution (ADR-0082 slice 1)", () => {
  // A read-only ref value pointing at a `tag` kind node — not resolvable
  // through any of the in-memory props (loreEntries/promptEntries/…) — falls
  // through resolveRefById's chain to the tag roster store, so a chip shows
  // the tag's title rather than its bare id.
  const tagField = {
    name: "Motifs",
    type: "entity_ref_list",
    options: [],
    picker_config: { sources: [{ kind: "tag", entry_types: ["tag:tag"] }] },
  } as unknown as MetadataFieldDefinition;

  it("read-only: resolves a tag's title from tagNodesStore", async () => {
    tagNodesStore.set([{ id: "tag_1", title: "Coastal", entry_type: "tag:tag", metadata: {} } as TagEntry]);
    render(ReferencePicker, {
      props: { field: tagField, value: ["tag_1"], ariaLabel: "Motifs", readOnly: true },
    });
    await fireEvent.click(screen.getByText("Motifs"));
    expect(screen.getByText("Coastal")).toBeInTheDocument();
  });

  it("shows the raw id when the tag isn't in the roster yet", async () => {
    render(ReferencePicker, {
      props: { field: tagField, value: ["tag_missing"], ariaLabel: "Motifs", readOnly: true },
    });
    await fireEvent.click(screen.getByText("Motifs"));
    expect(screen.getByText("tag_missing")).toBeInTheDocument();
  });
});

describe("ReferencePicker — create_missing wiring (ADR-0082 §2 / F2/F3)", () => {
  const createMissingField = {
    name: "Motifs",
    type: "entity_ref_list",
    options: [],
    picker_config: { sources: [{ kind: "tag", expr: { type: "tag:tag" } }], create_missing: true },
  } as unknown as MetadataFieldDefinition;

  afterEach(() => {
    metadataSchemaStore.set(null);
  });

  function setSchema() {
    metadataSchemaStore.set({
      entry_types: { "tag:tag": { name: "Tag", kind: "tag" } },
      fields: {},
    } as never);
  }

  async function openAndType(props: Record<string, unknown>, query: string) {
    render(ReferencePicker, {
      props: { field: createMissingField, value: [], ariaLabel: "Motifs", ...props },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Add Motifs" }));
    const box = document.querySelector(".ctx-search") as HTMLInputElement;
    await fireEvent.input(box, { target: { value: query } });
    await tick();
    return screen.getByTestId("node-picker-create");
  }

  it("calls createTagEntry with the threaded createLayerId, then selects the new id", async () => {
    setSchema();
    const onChange = vi.fn();
    const createSpy = vi
      .spyOn(api, "createTagEntry")
      .mockResolvedValue({ id: "tag_new", title: "Mystery", entry_type: "tag:tag", metadata: {} } as TagEntry);
    vi.spyOn(api, "listTagEntries").mockResolvedValue({ tags: [] });

    const createRow = await openAndType({ onChange, createLayerId: "layer_x" }, "Mystery");
    await fireEvent.click(createRow);
    await tick();

    // NodePicker's create row emits the trimmed typed title, casing preserved
    // (P1, corrected) — the gate/match check use the parsed needle, but what
    // mints (and shows) keeps the user's own casing.
    expect(createSpy).toHaveBeenCalledWith("Mystery", "tag:tag", null, "layer_x");
    expect(onChange).toHaveBeenCalledWith(["tag_new"]);
  });

  // F3's "stale-roster" race (a roster update landing between the create
  // row's render and the click) used to be pinned here by mocking
  // `findTagByTitle` to disagree with the picker's own live gate. Round 2
  // (Y3) moved the resolve-before-create sequence into the shared
  // `resolveOrCreateTag` (`tagNodes.ts`) — a same-module call `vi.spyOn` no
  // longer intercepts, AND the picker's create-row visibility and
  // `resolveOrCreateTag`'s own `findTagByTitle` now read the identical live
  // `tagNodesStore` reactively in lockstep in this harness (a mid-test
  // `tagNodesStore.set(...)` re-renders the row away before the click can
  // land), so the race can no longer be staged through the DOM at all. The
  // invariant it protected — an existing title wins over minting a
  // duplicate — is unit-tested directly on `resolveOrCreateTag` itself in
  // `tagNodes.test.ts`, which is the more precise place for it now that the
  // sequence lives there as its own function.

  it("two rapid clicks call createTagEntry once (P2 in-flight guard)", async () => {
    setSchema();
    const onChange = vi.fn();
    let resolveCreate!: (value: TagEntry) => void;
    const createSpy = vi.spyOn(api, "createTagEntry").mockImplementation(
      () => new Promise<TagEntry>((resolve) => { resolveCreate = resolve; }),
    );
    vi.spyOn(api, "listTagEntries").mockResolvedValue({ tags: [] });

    const createRow = await openAndType({ onChange, createLayerId: "layer_x" }, "Mystery");
    // The second click fires while the first POST is still pending — the
    // guard that matters is ReferencePicker's own `creating` flag, checked
    // synchronously inside `handleCreate` itself, not the row's `aria-disabled`
    // (which depends on the prop round-trip settling first).
    await fireEvent.click(createRow);
    await fireEvent.click(createRow);
    resolveCreate({ id: "tag_new", title: "mystery", entry_type: "tag:tag", metadata: {} });
    // Two ticks: `handleCreate` now awaits the shared `resolveOrCreateTag`
    // (round 2, Y3), one more promise hop than awaiting `api.createTagEntry`
    // directly — a single `tick()` can land between that hop's microtask and
    // `appendSelected`'s emit.
    await tick();
    await tick();

    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("lands the created tag in tagById before emitting, and the row disappears, even when the follow-up refresh fails (P3)", async () => {
    setSchema();
    const onChange = vi.fn();
    vi.spyOn(api, "createTagEntry").mockResolvedValue({
      id: "tag_new",
      title: "Mystery",
      entry_type: "tag:tag",
      metadata: {},
    } as TagEntry);
    // The best-effort follow-up refresh fails outright — must not undo the
    // upsert or block the emit.
    vi.spyOn(api, "listTagEntries").mockRejectedValue(new Error("offline"));

    const createRow = await openAndType({ onChange, createLayerId: "layer_x" }, "Mystery");
    await fireEvent.click(createRow);
    await tick();
    await Promise.resolve(); // let the failing refreshTagNodes() settle
    await tick();

    expect(get(tagById).get("tag_new")?.title).toBe("Mystery");
    expect(onChange).toHaveBeenCalledWith(["tag_new"]);
    // The roster now carries "Mystery" (via the upsert), so the still-open
    // picker's own gate (unaffected by the failed refresh) hides the row.
    expect(screen.queryByTestId("node-picker-create")).toBeNull();
  });

  it("never offers create when createLayerId is undefined (the default) — no onCreate reaches NodePicker (P5)", async () => {
    setSchema();
    render(ReferencePicker, {
      props: { field: createMissingField, value: [], ariaLabel: "Motifs" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Add Motifs" }));
    const box = document.querySelector(".ctx-search") as HTMLInputElement;
    await fireEvent.input(box, { target: { value: "Mystery" } });
    await tick();
    expect(screen.queryByTestId("node-picker-create")).toBeNull();
  });

  it("dedupes on emit — a found-existing or a created id already selected is never appended twice (P4)", async () => {
    // A real tag titled "Mystery" already exists AND is already selected
    // (`value`) — the picker's own candidate list excludes an already-
    // selected id, so the create row can still render (nothing UNSELECTED
    // matches), but `resolveOrCreateTag`'s `findTagByTitle` reads the WHOLE
    // roster and resolves it anyway. Real roster + real resolve (round 2, Y3
    // — no same-module function spy), so this is the honest reproduction of
    // the race, not a stub of it.
    setSchema();
    tagNodesStore.set([{ id: "tag_existing", title: "Mystery", entry_type: "tag:tag", metadata: {} }]);
    const onChange = vi.fn();
    const createSpy = vi.spyOn(api, "createTagEntry");

    render(ReferencePicker, {
      props: { field: createMissingField, value: ["tag_existing"], ariaLabel: "Motifs", onChange, createLayerId: "layer_x" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Add Motifs" }));
    const box = document.querySelector(".ctx-search") as HTMLInputElement;
    await fireEvent.input(box, { target: { value: "Mystery" } });
    await tick();
    // The row can still render (its own gate reads the search-filtered
    // NodePicker roster, not `value`), but resolving to an already-selected
    // id must not append a duplicate.
    const createRow = screen.queryByTestId("node-picker-create");
    if (createRow) await fireEvent.click(createRow);
    await tick();

    expect(createSpy).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });
});
