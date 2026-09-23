// @vitest-environment happy-dom
// Lore pane mount + default-view grouping. Per the component-test-harness rule
// (#642: a pane that DISPLAYS data needs a test asserting the rows actually
// render), this pins the wiring the API tests cannot see: the roster flows
// through evaluateView's default lore view — `descendants_of lore:base`, grouped
// by entry_type — so a missing root or a mis-stamped entry_type would render the
// pane empty. Also guards the runes conversion (#49): props via `$props()`, the
// `view` as `$derived`, and the search/add-menu local state.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import Lore from "./Lore.svelte";
import { defaultView } from "@/lib/views/evaluateView";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { clearTagNodes, tagNodesStore } from "@/lib/stores/tagNodes";
import { clearPrompts, promptEntriesStore } from "@/lib/stores/prompts";
import { chatSessions } from "@/lib/stores/chatSessions.svelte";
import type { LoreEntrySummary, MetadataSchema, PromptEntrySummary, TagEntry } from "@/lib/types";

// The lore default view resolves the roster to `descendants_of lore:base`, so
// the concrete sub-type must descend from that root or evaluateView yields
// nothing (the empty-pane trap).
const SCHEMA = {
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore" },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base" },
  },
  fields: {},
} as unknown as MetadataSchema;

function entry(id: string, title: string): LoreEntrySummary {
  return { id, title, body: "", entry_type: "lore:character", metadata: {} };
}

function tagged(id: string, title: string, body: string, tags: string[]): LoreEntrySummary {
  return { id, title, body, entry_type: "lore:character", metadata: { tags } };
}

const noop = () => {};

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});
afterEach(() => {
  metadataSchemaStore.set(null as unknown as MetadataSchema);
  clearTagNodes();
});

describe("Lore pane — default view (#642)", () => {
  it("renders every entry through the default lore view, grouped by entry_type", () => {
    const { container } = render(Lore, {
      props: {
        entries: [entry("l-a", "Aragorn"), entry("l-b", "Boromir")],
        viewSpec: defaultView("lore", SCHEMA),
        onOpenEntry: noop,
      },
    });
    expect(screen.getByText("Aragorn")).toBeInTheDocument();
    expect(screen.getByText("Boromir")).toBeInTheDocument();
    // Both rows sit under the entry_type group header (the type's display name),
    // proving the `$derived` view's `group_by` reached the render.
    const headings = Array.from(container.querySelectorAll(".node-row.group-header .node-row-text")).map((el) =>
      el.textContent?.trim(),
    );
    expect(headings).toContain("Character");
  });
});

// ADR-0074 slice 3 (#1468): the Lore search gains the app-wide `#` tag-restrictor
// through the shared parser. Plain queries keep the existing broad match (body
// included); `#tag` narrows to tags only.
describe("Lore pane — # tag search (#1468)", () => {
  const entries = [
    tagged("l-a", "Aragorn", "a ranger of the north", ["hero", "dunedain"]),
    tagged("l-b", "Boromir", "captain of gondor", ["hero"]),
    tagged("l-c", "Gollum", "a wretched creature", ["villain"]),
  ];

  async function typeSearch(container: HTMLElement, q: string) {
    const box = container.querySelector('input[type="search"]') as HTMLInputElement;
    await fireEvent.input(box, { target: { value: q } });
    await tick();
  }

  it("a plain query still matches the body (unchanged breadth)", async () => {
    const { container } = render(Lore, {
      props: { entries, viewSpec: defaultView("lore", SCHEMA), onOpenEntry: noop },
    });
    await typeSearch(container, "gondor"); // body-only hit
    expect(screen.getByText("Boromir")).toBeInTheDocument();
    expect(screen.queryByText("Aragorn")).toBeNull();
  });

  it("#hero restricts to the tag — Gollum (villain) drops, body words don't count", async () => {
    const { container } = render(Lore, {
      props: { entries, viewSpec: defaultView("lore", SCHEMA), onOpenEntry: noop },
    });
    await typeSearch(container, "#hero");
    expect(screen.getByText("Aragorn")).toBeInTheDocument();
    expect(screen.getByText("Boromir")).toBeInTheDocument();
    expect(screen.queryByText("Gollum")).toBeNull();
  });

  it("ADR-0082 §2: #tag matches by the resolved TITLE, not the stored id", async () => {
    tagNodesStore.set([{ id: "tag_x", title: "Coastal", entry_type: "tag:tag", metadata: {} } as TagEntry]);
    const withIdTag = [tagged("l-d", "Faramir", "captain of the rangers", ["tag_x"])];
    const { container } = render(Lore, {
      props: { entries: withIdTag, viewSpec: defaultView("lore", SCHEMA), onOpenEntry: noop },
    });
    await typeSearch(container, "#coastal");
    expect(screen.getByText("Faramir")).toBeInTheDocument();
    await typeSearch(container, "#tag_x");
    expect(screen.queryByText("Faramir")).toBeNull();
  });
});

// ADR-0091 §4: "Follow a change" ships with a required `entry` input (no
// create mode) precisely so create resolution — the "Draft <Type>" menu —
// skips it and still resolves to "Revise entry" when both built-ins are
// offered on the type.
describe("Lore pane — Draft resolution skips an entry-required committing prompt (ADR-0091 §4)", () => {
  const SCHEMA_WITH_CHARACTER = {
    entry_types: {
      "lore:base": { name: "Lore", kind: "lore" },
      "lore:character": { name: "Character", kind: "lore", parent: "lore:base" },
    },
    fields: {},
  } as unknown as MetadataSchema;

  function reviseEntry(): PromptEntrySummary {
    return {
      id: "p-revise",
      title: "Revise entry",
      body: "",
      entry_type: "prompt:general",
      metadata: {},
      computed_metadata: {},
      inputs: [{ name: "entry", type: "context_pick", required: false }],
      offer_on: ["lore:base"],
      context_strategy: { output: { handler: "extract_to_node", commit: { review: "visual_diff" } } },
    } as unknown as PromptEntrySummary;
  }

  function followAChange(): PromptEntrySummary {
    return {
      id: "p-follow",
      title: "Follow a change",
      body: "",
      entry_type: "prompt:general",
      metadata: {},
      computed_metadata: {},
      inputs: [{ name: "entry", type: "context_pick", required: true }],
      offer_on: ["lore:base"],
      context_strategy: { output: { handler: "extract_to_node", commit: { review: "visual_diff" } } },
    } as unknown as PromptEntrySummary;
  }

  beforeEach(() => {
    metadataSchemaStore.set(SCHEMA_WITH_CHARACTER);
  });
  afterEach(() => {
    clearPrompts();
  });

  it("Draft Character opens Revise entry, not Follow a change, when both are offered", async () => {
    // "Follow a change" sorts before "Revise entry" by title — the required
    // `entry` is what keeps it out of create resolution, not sort order.
    promptEntriesStore.set([followAChange(), reviseEntry()]);
    const openSpy = vi
      .spyOn(chatSessions, "openChatFromPromptEntry")
      .mockResolvedValue("chat_1");

    const { component } = render(Lore, {
      props: {
        entries: [],
        viewSpec: defaultView("lore", SCHEMA_WITH_CHARACTER),
        onOpenEntry: noop,
      },
    });
    (component as unknown as { toggleAddMenu: (event?: MouseEvent) => void }).toggleAddMenu();
    await tick();

    const draftRow = screen.getByText("✨ Draft Character");
    await fireEvent.click(draftRow);

    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy.mock.calls[0][0]).toEqual(expect.objectContaining({ id: "p-revise" }));
  });
});
