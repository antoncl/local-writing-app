// @vitest-environment happy-dom
// #1458: a collapsed context-pick input row's only expand affordance was an
// 18px chevron — the header is wall-to-wall live controls, so the "click
// anywhere on a collapsed row" gesture the generic input rows get had nowhere
// to land. The collapsed summary strip is now a second, big-surface expand
// target. These pin the affordance pair: both controls exist with accessible
// names, and clicking the strip actually opens the config body.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/lib/test/component";

// The editor no longer fetches saved views (ADR-0074 Amendment 3 retired the
// per-input view source), but stub the api client anyway so no transitive path
// trips the network guard (#973 pattern, see TagManagerDialog.test.ts).
vi.mock("@/lib/api", () => ({
  api: {
    listViews: vi.fn(async () => ({ entries: [] })),
  },
}));

import NodePickerConfigEditor from "./NodePickerConfigEditor.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataSchema } from "@/lib/types";

function renderCollapsed() {
  // Prompt mode starts collapsed by design (a fresh prompt shouldn't dump
  // the full picker tree). An empty config + empty schema store renders the
  // "Nothing pickable yet" warning inside the strip.
  return render(NodePickerConfigEditor, {
    props: { config: {}, mode: "prompt" as const, label: "Lore", name: "lore" },
  });
}

describe("NodePickerConfigEditor — collapsed expand affordances (#1458)", () => {
  it("offers both the chevron and the summary strip as expand controls", () => {
    const { container } = renderCollapsed();
    const chevron = screen.getByRole("button", { name: "Expand context picker" });
    expect(chevron.getAttribute("aria-expanded")).toBe("false");
    // The strip is a real <button> carrying the summary (the warning here),
    // not an inert div — the biggest click target on the row.
    const strip = container.querySelector(".ctx-collapsed-strip");
    expect(strip?.tagName).toBe("BUTTON");
    expect(strip?.textContent).toContain("Nothing pickable yet");
  });

  it("clicking the summary strip expands the picker config", async () => {
    const { container } = renderCollapsed();
    expect(container.querySelector(".ctx-body")).toBeNull();
    await fireEvent.click(container.querySelector(".ctx-collapsed-strip")!);
    // The config body is open, the strip is gone, and the chevron now
    // offers (and announces) collapse.
    expect(container.querySelector(".ctx-body")).toBeTruthy();
    expect(container.querySelector(".ctx-collapsed-strip")).toBeNull();
    const chevron = screen.getByRole("button", { name: "Collapse context picker" });
    expect(chevron.getAttribute("aria-expanded")).toBe("true");
  });
});

// ADR-0074 slice 6: plot becomes an offerable source. Its non-content types
// (plot:board — a presentation singleton; plot:template — a Library lens) stay
// hidden, so an author sees only plotline + card.
describe("NodePickerConfigEditor — plot source (ADR-0074 slice 6)", () => {
  const PLOT_SCHEMA = {
    entry_types: {
      "plot:base": { name: "All plots", kind: "plot", abstract: true },
      "plot:plotline": { name: "Plotline", kind: "plot", parent: "plot:base" },
      "plot:card": { name: "Card", kind: "plot", parent: "plot:base" },
      "plot:template": { name: "Template", kind: "plot", parent: "plot:base" },
      "plot:board": { name: "Board", kind: "plot", parent: "plot:base" },
    },
    fields: {},
  } as unknown as MetadataSchema;

  afterEach(() => metadataSchemaStore.set(null as unknown as MetadataSchema));

  it("offers plotline + card and hides plot:board / plot:template", () => {
    metadataSchemaStore.set(PLOT_SCHEMA);
    // Field mode renders the tree always-expanded — no collapse gesture needed.
    render(NodePickerConfigEditor, { props: { config: {}, mode: "field" as const } });
    // Plotline + card render only if "plot" was added to the offered kinds.
    expect(screen.getByText("Plotline")).toBeInTheDocument();
    expect(screen.getByText("Card")).toBeInTheDocument();
    // The two non-content types are filtered out of the offered tree.
    expect(screen.queryByText("Board")).toBeNull();
    expect(screen.queryByText("Template")).toBeNull();
  });
});

// ADR-0082 §2 / F1, P8 (round 2): the "Create when missing" checkbox — enabled
// only when the config reduces to exactly one concrete entry type
// (`singleConcreteTarget`, shared with `createTargetFor`), and an edit that
// breaks that clears `create_missing` in the same emit so the backend
// validator can never reject a config this editor produced.
describe("NodePickerConfigEditor — create_missing checkbox (P8)", () => {
  const TAG_SCHEMA = {
    entry_types: {
      "tag:tag": { name: "Tag", kind: "tag" },
      "tag:assistant_tag": { name: "Assistant tag", kind: "tag" },
    },
    fields: {},
  } as unknown as MetadataSchema;

  afterEach(() => metadataSchemaStore.set(null as unknown as MetadataSchema));

  it("enables the checkbox when the config resolves to one concrete type, and toggling it emits create_missing: true", async () => {
    metadataSchemaStore.set(TAG_SCHEMA);
    const onChange = vi.fn();
    render(NodePickerConfigEditor, {
      props: {
        config: { sources: [{ kind: "tag", expr: { type: "tag:tag" } }] },
        mode: "field" as const,
        onChange,
      },
    });
    const checkbox = screen.getByTestId("picker-create-missing") as HTMLInputElement;
    expect(checkbox.disabled).toBe(false);
    expect(checkbox.checked).toBe(false);
    await fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ create_missing: true }));
  });

  it("disables the checkbox when the config names no single concrete type (an unconstrained kind-only source)", () => {
    metadataSchemaStore.set(TAG_SCHEMA);
    render(NodePickerConfigEditor, {
      props: { config: { sources: [{ kind: "tag" }] }, mode: "field" as const },
    });
    const checkbox = screen.getByTestId("picker-create-missing") as HTMLInputElement;
    expect(checkbox.disabled).toBe(true);
  });

  it("clears create_missing in the SAME emit when an edit adds a second concrete type", async () => {
    metadataSchemaStore.set(TAG_SCHEMA);
    const onChange = vi.fn();
    render(NodePickerConfigEditor, {
      props: {
        config: { sources: [{ kind: "tag", expr: { type: "tag:tag" } }], create_missing: true },
        mode: "field" as const,
        onChange,
      },
    });
    const checkbox = screen.getByTestId("picker-create-missing") as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    expect(checkbox.disabled).toBe(false);

    // Check the second tag entry type — the config now names two, so
    // singleConcreteTarget fails and create_missing must clear right here. (The
    // tree toggle's accessible name now carries its tri-state word, #1947.)
    await fireEvent.click(screen.getByRole("button", { name: "Assistant tag: not a source" }));
    expect(onChange).toHaveBeenCalled();
    const patch = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(patch.create_missing).toBeUndefined();
  });
});

// #1947, ADR-0074 Amendment 5: each type's checkbox is a tri-state cycle —
// off → this type (`{type}`) → this type + subtypes (`{descendants_of}`) → off.
// A concrete type WITH subtypes (character, whose deity/hero are specializations)
// is the load-bearing case: the old leaf-only model could not attach a scope to a
// non-leaf, so a family default rendered as unchecked ("Nothing pickable yet").
describe("NodePickerConfigEditor — tri-state per-type scope (#1947)", () => {
  const LORE_SCHEMA = {
    entry_types: {
      "lore:character": { name: "Character", kind: "lore" },
      "lore:character:deity": { name: "Deity", kind: "lore", parent: "lore:character" },
      "lore:character:hero": { name: "Hero", kind: "lore", parent: "lore:character" },
    },
    fields: {},
  } as unknown as MetadataSchema;

  afterEach(() => metadataSchemaStore.set(null as unknown as MetadataSchema));

  const lastPatch = (onChange: ReturnType<typeof vi.fn>) =>
    onChange.mock.calls[onChange.mock.calls.length - 1][0];

  it("off → this type: first click on a concrete branch emits an exact `{type}` source", async () => {
    metadataSchemaStore.set(LORE_SCHEMA);
    const onChange = vi.fn();
    render(NodePickerConfigEditor, { props: { config: {}, mode: "field" as const, onChange } });
    await fireEvent.click(screen.getByRole("button", { name: "Character: not a source" }));
    expect(lastPatch(onChange).sources).toEqual([{ kind: "lore", expr: { type: "lore:character" } }]);
  });

  it("this type → this type + subtypes: a second click promotes exact to a family `{descendants_of}` source", async () => {
    metadataSchemaStore.set(LORE_SCHEMA);
    const onChange = vi.fn();
    render(NodePickerConfigEditor, {
      props: {
        config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }] },
        mode: "field" as const,
        onChange,
      },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Character: this type" }));
    expect(lastPatch(onChange).sources).toEqual([
      { kind: "lore", expr: { descendants_of: "lore:character" } },
    ]);
  });

  it("renders a family-scoped config as family — subtypes implied, no empty warning (the misrepresentation fix)", () => {
    metadataSchemaStore.set(LORE_SCHEMA);
    render(NodePickerConfigEditor, {
      props: {
        config: { sources: [{ kind: "lore", expr: { descendants_of: "lore:character" } }] },
        mode: "field" as const,
      },
    });
    // The parent carries the family scope (was invisible under the leaf model)...
    expect(
      screen.getByRole("button", { name: "Character: this type and its subtypes" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("+ subtypes").length).toBeGreaterThan(0);
    // ...its subtypes read as implied and are locked (the parent owns them)...
    const deity = screen.getByRole("button", {
      name: "Deity: included via its parent",
    }) as HTMLButtonElement;
    expect(deity.disabled).toBe(true);
    // ...and the config is NOT reported as empty.
    expect(screen.queryByText(/Nothing is pickable/)).toBeNull();
  });

  it("this type + subtypes → off: a third click clears the type", async () => {
    metadataSchemaStore.set(LORE_SCHEMA);
    const onChange = vi.fn();
    render(NodePickerConfigEditor, {
      props: {
        config: { sources: [{ kind: "lore", expr: { descendants_of: "lore:character" } }] },
        mode: "field" as const,
        onChange,
      },
    });
    await fireEvent.click(
      screen.getByRole("button", { name: "Character: this type and its subtypes" }),
    );
    expect(lastPatch(onChange).sources).toEqual([]);
  });

  it("readonly disables the cycle", () => {
    metadataSchemaStore.set(LORE_SCHEMA);
    render(NodePickerConfigEditor, {
      props: {
        config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }] },
        mode: "field" as const,
        readonly: true,
      },
    });
    const character = screen.getByRole("button", {
      name: "Character: this type",
    }) as HTMLButtonElement;
    expect(character.disabled).toBe(true);
  });

  it("renders an indeterminate parent (a subtype-only scope) with a mixed toggle and an N-of-M count", () => {
    metadataSchemaStore.set(LORE_SCHEMA);
    render(NodePickerConfigEditor, {
      props: {
        config: { sources: [{ kind: "lore", expr: { type: "lore:character:deity" } }] },
        mode: "field" as const,
      },
    });
    // Scoping only Deity leaves its Character parent partial: a "mixed" toggle
    // announcing the roll-up, with the subtype itself exact.
    const character = screen.getByRole("button", { name: "Character: some subtypes" });
    expect(character.getAttribute("aria-pressed")).toBe("mixed");
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deity: this type" })).toBeInTheDocument();
  });

  it("seeds a legacy kind-only source as family on a concrete-branch root (no false empty warning)", () => {
    metadataSchemaStore.set(LORE_SCHEMA);
    render(NodePickerConfigEditor, {
      props: { config: { sources: [{ kind: "lore" }] }, mode: "field" as const },
    });
    // A bare {kind:"lore"} historically meant "all sub-types allowed" — the
    // concrete-branch root reflects that as family (this type + subtypes), not
    // exact-only, so the subtypes aren't silently dropped on the first save.
    expect(
      screen.getByRole("button", { name: "Character: this type and its subtypes" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("+ subtypes").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Nothing is pickable/)).toBeNull();
  });
});
