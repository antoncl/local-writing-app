// @vitest-environment happy-dom
// #2054 front matter: the rail's rows at the head of the document while the
// rail is collapsed. The layout is CSS (a two-column grid on the root); what
// this pins is the contract the CSS hangs off: the root class, and that the
// index rows (a long_text section, a list-of-prose-items section, a reference
// list tab) are NOT rows here — the sections are headed right below the block
// and the lists are tabs above it — while every fact row still renders and
// the empties still fold.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": {
      name: "Character",
      kind: "lore",
      fields: ["alias", "role", "bio", "beats", "kin", "aliases"],
    },
  },
  fields: {
    alias: { name: "Alias", type: "text" },
    role: { name: "Role", type: "text" },
    bio: { name: "Bio", type: "long_text" },
    beats: {
      name: "Beats",
      type: "list",
      item_members: [{ key: "function", name: "Function", type: "long_text" }],
    },
    kin: {
      name: "Kin",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
    aliases: { name: "Aliases", type: "list" },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

const METADATA: EntryMetadata = {
  alias: "The Painted Lady",
  bio: "Long prose.",
  beats: [{ function: "one" }],
  kin: ["lore_1"],
  aliases: ["Evening Star"],
};

function mount(layout: "rail" | "front-matter") {
  return render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status: "",
      metadata: METADATA,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["alias", "role", "bio", "beats", "kin", "aliases"],
      sectionsInBody: true,
      onGoToSection: vi.fn(),
      listsInBody: true,
      onGoToList: vi.fn(),
      onMetadataChange: vi.fn(),
      layout,
    } as never,
  });
}

describe("MetadataPanel — front matter layout (#2054)", () => {
  it("the rail layout keeps its index rows (the control)", () => {
    mount("rail");
    expect(document.querySelector(".scene-metadata.front-matter")).toBeNull();
    expect(document.querySelectorAll(".fr-section-index")).toHaveLength(3);
    expect(screen.getByText("Bio")).toBeInTheDocument();
    expect(screen.getByText("Beats")).toBeInTheDocument();
    expect(screen.getByText("Kin")).toBeInTheDocument();
  });

  it("front matter renders the fact rows without the index rows, empties still folded", () => {
    mount("front-matter");
    expect(document.querySelector(".scene-metadata.front-matter")).not.toBeNull();
    expect(document.querySelectorAll(".fr-section-index")).toHaveLength(0);
    expect(screen.queryByText("Bio")).toBeNull();
    expect(screen.queryByText("Beats")).toBeNull();
    expect(screen.queryByText("Kin")).toBeNull();
    // The facts: a filled scalar, and a line-valued list (wide, so it spans).
    expect(screen.getByText("Alias")).toBeInTheDocument();
    expect(screen.getByText("Aliases").closest(".field-row")?.classList.contains("wide")).toBe(true);
    // The empty `role` folds behind the same summary line as in the rail, and
    // the index rows do not count as empties.
    expect(screen.getByText("1 more field")).toBeInTheDocument();
    // #2061: no group heads anywhere (known rows or fold) → the rows' disclosure
    // gutter is dropped so icons, labels and wide values share one edge.
    expect(document.querySelector(".scene-metadata.front-matter.no-disc")).not.toBeNull();
  });

  it("front matter keeps the disclosure gutter when the type has a group, even one that is folded (#2061)", () => {
    metadataSchemaStore.set({
      ...SCHEMA,
      fields: { ...SCHEMA.fields, role: { name: "Role", type: "text", group: "Arc" } },
    } as unknown as MetadataSchema);
    mount("front-matter");
    expect(document.querySelector(".scene-metadata.front-matter")).not.toBeNull();
    expect(document.querySelector(".scene-metadata.no-disc")).toBeNull();
  });
});
