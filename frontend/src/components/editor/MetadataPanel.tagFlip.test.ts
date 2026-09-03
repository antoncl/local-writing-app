// @vitest-environment happy-dom
// #1797 — a tag-vocabulary `entity_ref_list` flip (ADR-0082 §2) is now
// reviewable (entryProposal.svelte.ts's `structuredFlips`). The validator only
// resolves a title matching an EXISTING tag; an unmatched one rides through
// as a plain string (never minted at validation — see the module note in
// `entryProposal.svelte.ts`), so the candidate side can MIX resolved ids with
// unresolved titles. Both must render sensibly: a known id as its title (the
// candidate via `MetadataPanel`'s own tag-chip strip, `tagFlipItems`; the
// "Current:" hint via `tagTitleById`), and an unresolved title as a visually
// distinct "new tag" candidate (`data-testid="flip-new-tag"`) — accepting the
// flip is what mints it (`resolveAdoptedTagFieldValue`, `tagNodes.ts`), never
// this render.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { tagNodesStore } from "@/lib/stores/tagNodes";
import type { MetadataSchema, TagEntry } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:note": { name: "Note", kind: "lore", fields: ["tags"] },
    // `createTargetFor`/`singleConcreteTarget` resolve the picker_config's
    // target entry_type against the schema — must be present for
    // `isTagFlipField` to recognise `tags` as the tag-vocabulary carve-out.
    "tag:tag": { name: "Tag", kind: "tag" },
  },
  fields: {
    tags: {
      name: "Tags",
      type: "entity_ref_list",
      options: [],
      picker_config: {
        create_missing: true,
        sources: [{ kind: "tag", expr: { type: "tag:tag" } }],
      },
    },
  },
} as unknown as MetadataSchema;

const OLD: TagEntry = { id: "tag_old", title: "Old Tag", entry_type: "tag:tag", metadata: {} };
const NEW: TagEntry = { id: "tag_new", title: "New Tag", entry_type: "tag:tag", metadata: {} };

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
  tagNodesStore.set([OLD, NEW]);
});

function mount(was: string[]) {
  render(MetadataPanel, {
    props: {
      entryType: "lore:note",
      status: "",
      metadata: { tags: [OLD.id] },
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:note", SCHEMA.entry_types["lore:note"]]] as never,
      metadataFieldIds: ["tags"],
      compare: {
        fields: { tags: { was, now: [OLD.id] } },
        side: "was",
        resolve: { adopted: () => false, onToggle: vi.fn() },
      },
      onMetadataChange: vi.fn(),
    },
  });
}

describe("MetadataPanel — tag-vocabulary flip resolves both sides to titles (#1797)", () => {
  it('shows "Current: Old Tag", not the raw id', () => {
    mount([NEW.id]);
    expect(screen.getByText("Current: Old Tag")).toBeTruthy();
  });

  it("renders a known id's title as an ordinary chip", () => {
    mount([NEW.id]);
    expect(screen.getByText("New Tag")).toBeTruthy();
    expect(screen.queryByTestId("flip-new-tag")).toBeNull();
  });

  it('renders an unresolved title as a "new tag" candidate, marked and unminted', () => {
    mount(["Brand New Tag"]);
    const marker = screen.getByTestId("flip-new-tag");
    expect(marker.textContent).toBe("+ Brand New Tag");
    // Rendering the candidate never mints anything — the roster is untouched.
    expect(get(tagNodesStore).some((t) => t.title === "Brand New Tag")).toBe(false);
  });

  it("a mixed proposal renders one of each", () => {
    mount([NEW.id, "Brand New Tag"]);
    expect(screen.getByText("New Tag")).toBeTruthy();
    expect(screen.getByTestId("flip-new-tag").textContent).toBe("+ Brand New Tag");
  });
});
