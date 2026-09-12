// @vitest-environment happy-dom
// #1884 slice 3 — L1 groups fold. Once a type has at least one group, every
// block (including the ungrouped fields, under "General") gets a
// RailGroupHead and can be collapsed; state persists through
// railSectionCollapse (`group:<name>`, default expanded). A type with no
// groups at all renders no heads.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { railSectionCollapse } from "@/lib/stores/railSectionCollapse.svelte";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["alias", "want", "need"] } },
  fields: {
    alias: { name: "Alias", type: "text" },
    want: { name: "Want", type: "long_text", group: "Arc" },
    need: { name: "Need", type: "long_text", group: "Arc" },
  },
} as unknown as MetadataSchema;

const UNGROUPED_SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["alias"] } },
  fields: {
    alias: { name: "Alias", type: "text" },
  },
} as unknown as MetadataSchema;

beforeEach(() => {
  localStorage.clear();
  railSectionCollapse.set("group:Arc", true);
  railSectionCollapse.set("group:~ungrouped", true);
});

function mount(schema: MetadataSchema, fieldIds: string[], metadata: EntryMetadata = {}) {
  render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status: "",
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", schema.entry_types["lore:character"]]] as never,
      metadataFieldIds: fieldIds,
      onMetadataChange: vi.fn(),
    },
  });
}

function headFor(label: string): HTMLElement {
  const head = screen.getByText(label).closest(".rail-group-head");
  if (!head) throw new Error(`no .rail-group-head ancestor for "${label}"`);
  return head as HTMLElement;
}

describe("MetadataPanel — L1 groups fold (#1884 slice 3)", () => {
  it("renders General and Arc heads, both expanded, all three rows present", () => {
    metadataSchemaStore.set(SCHEMA);
    mount(SCHEMA, ["alias", "want", "need"]);
    const generalButton = headFor("General").querySelector("button.rgh-toggle") as HTMLElement;
    const arcButton = headFor("Arc").querySelector("button.rgh-toggle") as HTMLElement;
    expect(generalButton).toHaveAttribute("aria-expanded", "true");
    expect(arcButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Alias")).toBeTruthy();
    expect(screen.getByText("Want")).toBeTruthy();
    expect(screen.getByText("Need")).toBeTruthy();
  });

  it("clicking Arc folds its two rows, leaves General's row, and persists; clicking again unfolds", async () => {
    metadataSchemaStore.set(SCHEMA);
    mount(SCHEMA, ["alias", "want", "need"]);
    const arcButton = headFor("Arc").querySelector("button.rgh-toggle") as HTMLElement;
    await fireEvent.click(arcButton);
    expect(screen.queryByText("Want")).toBeNull();
    expect(screen.queryByText("Need")).toBeNull();
    expect(screen.getByText("Alias")).toBeTruthy();
    expect(railSectionCollapse.isExpanded("group:Arc", true)).toBe(false);

    await fireEvent.click(headFor("Arc").querySelector("button.rgh-toggle") as HTMLElement);
    expect(screen.getByText("Want")).toBeTruthy();
    expect(screen.getByText("Need")).toBeTruthy();
    expect(railSectionCollapse.isExpanded("group:Arc", true)).toBe(true);
  });

  it("clicking General folds the alias row and persists group:~ungrouped", async () => {
    metadataSchemaStore.set(SCHEMA);
    mount(SCHEMA, ["alias", "want", "need"]);
    const generalButton = headFor("General").querySelector("button.rgh-toggle") as HTMLElement;
    await fireEvent.click(generalButton);
    expect(screen.queryByText("Alias")).toBeNull();
    expect(railSectionCollapse.isExpanded("group:~ungrouped", true)).toBe(false);
  });

  it("a group nobody has toggled is EXPANDED by default — its rows render without any stored state", () => {
    // "Voice" is set in no beforeEach and no other test, so this is the store's
    // fallback, i.e. GROUP_DEFAULT — folding is opt-in, never the first sight.
    const schema = {
      ...SCHEMA,
      fields: { ...SCHEMA.fields, tone: { name: "Tone", type: "text", group: "Voice" } },
      entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["alias", "want", "need", "tone"] } },
    } as unknown as MetadataSchema;
    metadataSchemaStore.set(schema);
    mount(schema, ["alias", "want", "need", "tone"]);
    expect(headFor("Voice").querySelector("button.rgh-toggle")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Tone")).toBeTruthy();
    expect(railSectionCollapse.isExpanded("group:Voice", false)).toBe(false); // nothing stored — the component's default did it
  });

  it("a schema whose fields have no group renders no rail-group-head at all", () => {
    metadataSchemaStore.set(UNGROUPED_SCHEMA);
    mount(UNGROUPED_SCHEMA, ["alias"]);
    expect(document.querySelector(".rail-group-head")).toBeNull();
    expect(screen.getByText("Alias")).toBeTruthy();
  });
});
