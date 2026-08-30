// @vitest-environment happy-dom
// Types kind-tabs RENDER guard (#729). Making plot a first-class kind in
// the schema-authoring UI means the "Plot" tab actually has to appear in the tab
// strip and route through `onSwitchKind("plot")`. The strip renders from the
// shared SCHEMA_KINDS/SCHEMA_KIND_META table, so this drives its expectations
// off the SAME table — a kind added to the table without a rendered tab (or a
// relabelled tab) fails here. The cascade the tab feeds (entry-type → kind →
// heading in SchemaPanes) is pinned by the asSchemaKind/SCHEMA_KIND_META unit
// tests in schemaTypeHelpers.test.ts; together they cover the whole path that
// shipped broken (the Plot tab silently collapsing to the Scene tree).
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { SCHEMA_KINDS, SCHEMA_KIND_META } from "@/lib/utils/schemaTypeHelpers";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataSchema, MetadataSchemaLayer } from "@/lib/types";
import SchemaTreePane from "./SchemaTreePane.svelte";

describe("SchemaTreePane kind tabs (#729)", () => {
  it("renders one tab per schema kind — including Plot — labelled from the shared table", () => {
    render(SchemaTreePane, { props: {} });
    expect(screen.getByRole("tablist", { name: "Type kind" })).toBeInTheDocument();
    // Every kind in the table has a rendered tab; Plot is present, not just typed.
    expect(SCHEMA_KINDS).toContain("plot");
    for (const kind of SCHEMA_KINDS) {
      expect(screen.getByRole("tab", { name: SCHEMA_KIND_META[kind].label })).toBeInTheDocument();
    }
  });

  it("marks the Plot tab selected when the pane is scoped to plot, and switches to it on click", async () => {
    const onSwitchKind = vi.fn();
    const { rerender } = render(SchemaTreePane, { props: { schemaFieldKind: "manuscript", onSwitchKind } });

    await fireEvent.click(screen.getByRole("tab", { name: "Plot" }));
    expect(onSwitchKind).toHaveBeenCalledWith("plot");

    await rerender({ schemaFieldKind: "plot", onSwitchKind });
    expect(screen.getByRole("tab", { name: "Plot" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Scene" })).toHaveAttribute("aria-selected", "false");
  });
});

describe("SchemaTreePane inline create (#1659)", () => {
  const SCHEMA = {
    entry_types: {
      "lore:base": { kind: "lore", name: "Lore Entries", parent: null, abstract: true, fields: [] },
      "lore:character": { kind: "lore", name: "Character", parent: "lore:base", fields: [] },
    },
    fields: {},
    groups: {},
  } as unknown as MetadataSchema;

  const NODE = {
    id: "lore:character",
    label: "Character",
    depth: 0,
    definition: SCHEMA.entry_types["lore:character"],
    children: [],
    fieldEntries: [],
  };

  beforeEach(() => metadataSchemaStore.set(SCHEMA));
  afterEach(() => metadataSchemaStore.set(null));

  it("the heading '+ New type' is always present and seeds a top-level create at the kind root", async () => {
    const onRequestCreate = vi.fn();
    render(SchemaTreePane, {
      props: { schemaFieldKind: "lore", schemaNodeTypeTree: [NODE], kindRootId: "lore:base", onRequestCreate },
    });
    await fireEvent.click(screen.getByRole("button", { name: "New type" }));
    expect(onRequestCreate).toHaveBeenCalledWith("lore:base");
  });

  it("a row '+' requests the create card under that type (not a full pane)", async () => {
    const onRequestCreate = vi.fn();
    render(SchemaTreePane, {
      props: { schemaFieldKind: "lore", schemaNodeTypeTree: [NODE], onRequestCreate },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Add sub-type to Character" }));
    expect(onRequestCreate).toHaveBeenCalledWith("lore:character");
  });

  it("renders the create card inline under the seeded type", () => {
    render(SchemaTreePane, {
      props: {
        schemaFieldKind: "lore",
        schemaNodeTypeTree: [NODE],
        createSeedParentId: "lore:character",
        kindRootId: "lore:base",
        metadataSchemaLayers: [{ id: "proj", label: "Project" }] as unknown as MetadataSchemaLayer[],
      },
    });
    // Extends a non-root type ⇒ "New sub-type"; the card is in the tree, inline.
    expect(screen.getByText("New sub-type")).toBeTruthy();
    expect(screen.getByPlaceholderText("Enter type name…")).toBeTruthy();
  });
});
