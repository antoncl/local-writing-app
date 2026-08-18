// @vitest-environment happy-dom
// Assistants pane mount + tag-color reactivity. Per the component-test-harness
// rule (#642: a pane that DISPLAYS data needs a test asserting the rows render),
// the first test pins the roster flowing through evaluateView's default
// assistant view — the tag-parameterized roster grouped Active/Unlisted (#333).
// The second test guards the one non-mechanical conversion in the runes pass
// (#49): `tagHexFor` is a `$derived.by` over `assistantSwatchIds`, passed as
// NodeRow's `tagColor`. It asserts a chip both takes its color from the tag
// vocabulary AND recolors when the vocabulary changes — the reactivity a
// vocabulary-independent (non-reactive) rewrite would drop.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { tick } from "svelte";
import { render, screen } from "@/lib/test/component";
import Assistants from "./Assistants.svelte";
import { defaultView } from "@/lib/views/evaluateView";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { assistantTagsStore } from "@/lib/stores/assistantTags";
import { setPalette } from "@/lib/utils/colors";
import type { AssistantEntrySummary, MetadataSchema } from "@/lib/types";

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
    metadata: { tags },
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
  assistantTagsStore.set([]);
  setPalette([]);
});

describe("Assistants pane — default view (#642)", () => {
  it("renders a listed assistant with its tag chip through the default view", () => {
    renderPane([assistant("a1", "Editor Bot", ["hero"])]);
    expect(screen.getByText("Editor Bot")).toBeInTheDocument();
    expect(screen.getByText("hero")).toBeInTheDocument();
  });
});

describe("Assistants pane — tag chip color reactivity (#49 tagHexFor)", () => {
  it("colors the chip from the tag vocabulary and recolors when it changes", async () => {
    setPalette([
      { id: "sw-red", label: "Red", hex: "#ff0000" },
      { id: "sw-blue", label: "Blue", hex: "#0000ff" },
    ]);
    // The vocabulary paints "hero" red via its swatch id.
    assistantTagsStore.set([{ name: "hero", color: "sw-red" }]);

    const { container } = renderPane([assistant("a1", "Editor Bot", ["hero"])]);

    // The chip carries the resolved hex in its inline style (--tag-text/-bg/-border).
    const chipStyle = () =>
      Array.from(container.querySelectorAll<HTMLElement>(".node-row-tag"))
        .find((el) => el.textContent?.trim() === "hero")
        ?.getAttribute("style") ?? "";
    expect(chipStyle()).toContain("#ff0000");

    // Recolor the vocabulary. `tagHexFor` reads `assistantSwatchIds` (derived from
    // this store), so the chip must follow to blue. A conversion that resolved the
    // color once and stopped tracking would leave it red.
    assistantTagsStore.set([{ name: "hero", color: "sw-blue" }]);
    await tick();
    expect(chipStyle()).toContain("#0000ff");
    expect(chipStyle()).not.toContain("#ff0000");
  });
});
