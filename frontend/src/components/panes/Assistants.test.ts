// @vitest-environment happy-dom
// Assistants pane mount + tag-chip display. Per the component-test-harness
// rule (#642: a pane that DISPLAYS data needs a test asserting the rows render),
// the first test pins the roster flowing through evaluateView's default
// assistant view — the tag-parameterized roster grouped Active/Unlisted (#333).
// The second test pins ADR-0082 §2's rename: `assistant_tags` holds tag-node
// ids now, resolved to a title through the tag roster store (`tagTitleById`)
// at the row — and, until colour returns in slice 3 (the picker's
// instance-colour helper), the chip carries none, replacing the old
// `assistantTagsStore`-keyed `tagHexFor` reactivity test.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { tick } from "svelte";
import { render, screen } from "@/lib/test/component";
import Assistants from "./Assistants.svelte";
import { defaultView } from "@/lib/views/evaluateView";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { tagNodesStore } from "@/lib/stores/tagNodes";
import type { AssistantEntrySummary, MetadataSchema, TagEntry } from "@/lib/types";

// `assistant:assistant` is the kind root the default view descends from; the
// listed/unlisted split comes from `computed_metadata.listed` (#332/#333).
const SCHEMA = {
  entry_types: {
    "assistant:assistant": { name: "Assistant", kind: "assistant" },
  },
  fields: {},
} as unknown as MetadataSchema;

function assistant(id: string, title: string, tags: string[] = []): AssistantEntrySummary {
  return {
    id,
    title,
    entry_type: "assistant:assistant",
    metadata: { assistant_tags: tags },
    computed_metadata: { listed: "listed", position: 0 },
  } as AssistantEntrySummary;
}

const noop = () => {};
const asyncNoop = async () => {};

function renderPane(entries: AssistantEntrySummary[]) {
  return render(Assistants, {
    props: {
      entries,
      viewSpec: defaultView("assistant", SCHEMA),
      onOpenEntry: noop,
      onSetOrder: asyncNoop,
      onUnlist: asyncNoop,
    },
  });
}

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});
afterEach(() => {
  metadataSchemaStore.set(null as unknown as MetadataSchema);
  tagNodesStore.set([]);
});

describe("Assistants pane — default view (#642)", () => {
  it("renders a listed assistant with its tag chip through the default view", () => {
    renderPane([assistant("a1", "Editor Bot", ["tag_hero"])]);
    expect(screen.getByText("Editor Bot")).toBeInTheDocument();
    // Unresolved (no matching roster entry) falls back to the raw id.
    expect(screen.getByText("tag_hero")).toBeInTheDocument();
  });
});

describe("Assistants pane — roster search field, not a tag param strip (#1816)", () => {
  it("renders the search field and no runtime parameter strip", () => {
    const { container } = renderPane([assistant("a1", "Editor Bot", ["tag_hero"])]);
    // Tag-filtering is the search field (its `filter` logic is unit-tested in
    // nodeSearch.test.ts), so the pane wires `searchPlaceholder`…
    expect(screen.getByPlaceholderText("Search assistants, #tags")).toBeInTheDocument();
    // …and the default view declares no formal, so no parameter strip renders
    // (the "tags header" this fixes).
    expect(container.querySelector(".param-strip")).toBeNull();
  });
});

describe("Assistants pane — tag chip title resolution (ADR-0082 §2)", () => {
  it("resolves an assistant_tags id to its title through the tag roster store, uncoloured", async () => {
    tagNodesStore.set([
      { id: "tag_hero", title: "Hero", entry_type: "tag:assistant_tag", metadata: {} } as TagEntry,
    ]);

    const { container } = renderPane([assistant("a1", "Editor Bot", ["tag_hero"])]);
    await tick();

    expect(screen.getByText("Hero")).toBeInTheDocument();
    // No colour until slice 3 (the picker's instance-colour helper) — the
    // chip carries no --tag-* inline style regardless of any vocabulary.
    const chipStyle = Array.from(container.querySelectorAll<HTMLElement>(".node-row-tag")).find(
      (el) => el.textContent?.trim() === "Hero",
    );
    expect(chipStyle?.getAttribute("style") || "").toBe("");
  });
});
