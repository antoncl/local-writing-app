// @vitest-environment happy-dom
// StructureTree render contract (#979). This is the manuscript/research tree,
// and it renders entirely through ViewNodeList → evaluateView (ADR-0035): the
// containment Nest over each node's `parent` ref is what turns the flat roster
// back into a tree. That view layer is exactly where the #724 "empty pane" trap
// lives — a wrong roster root or a stale entry_type stamp filters every node out
// and the pane renders nothing, which the API/structure tests cannot see. So the
// core assertion is that a real manuscript actually reaches the DOM as rows.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import StructureTree, { type TreeConfig } from "./StructureTree.svelte";
import { defaultView } from "@/lib/views/evaluateView";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type {
  MetadataSchema,
  StructureDocument,
  StructureNode,
  StructureNodeDeletePreview,
} from "@/lib/types";

// scene root + act/scene sub-types + the `parent` ref the containment Nest joins
// on. Drop the root or the `parent` field and defaultView("manuscript") resolves to a
// roster that renders nothing — the trap under test.
const SCHEMA = {
  version: 1,
  fields: { parent: { name: "Parent", type: "entity_ref", category: "stored" } },
  entry_types: {
    "manuscript:base": { name: "Scene root", kind: "manuscript", abstract: true },
    "manuscript:act": { name: "Act", kind: "manuscript", parent: "manuscript:base" },
    "manuscript:scene": { name: "Scene", kind: "manuscript", parent: "manuscript:base" },
  },
} as unknown as MetadataSchema;

function manuscript(): StructureDocument {
  return {
    root: {
      id: "root",
      type: "root",
      title: "Manuscript",
      children: [
        {
          id: "act1",
          type: "manuscript:act",
          title: "Act One",
          computed_metadata: { number: 1 },
          children: [
            { id: "s1", type: "manuscript:scene", title: "Arrival", scene_id: "s1", status: "complete", metadata: {}, computed_metadata: { number: 1 }, children: [] },
            { id: "s2", type: "manuscript:scene", title: "Departure", scene_id: "s2", status: "draft", metadata: {}, computed_metadata: { number: 2 }, children: [] },
          ],
        },
      ],
    },
  } as unknown as StructureDocument;
}

const noopAsync = async () => {};

// A manuscript-shaped config. Only the render-relevant flags matter here; the
// mutation callbacks are never triggered by these tests, so they are inert stubs.
function manuscriptConfig(): TreeConfig {
  return {
    kind: "manuscript",
    leafType: "manuscript:scene",
    getStructure: () => manuscript(),
    applyStructure: () => {},
    refresh: noopAsync,
    api: {
      create: async () => manuscript(),
      rename: async () => manuscript(),
      move: async () => manuscript(),
      cascadePreview: async () => ({}) as unknown as StructureNodeDeletePreview,
      delete: async () => manuscript(),
    },
    openLeaf: noopAsync,
    cascadeLabels: {
      leaf: { singular: "scene", plural: "scenes" },
      container: { singular: "act", plural: "acts" },
    },
    supportsDrag: true,
    showStatusStripe: true,
    containerHasEditor: true,
    inlineRenameOnLeafCreate: true,
    rootAddMenuKey: "manuscript-root",
    // false = ephemeral collapse, so the test never hits the /ui persist endpoint.
    persistCollapse: false,
  };
}

const run = (action: () => Promise<void>) => action().then(() => true);

function renderTree(structure: StructureDocument | null) {
  return render(StructureTree, {
    props: {
      config: manuscriptConfig(),
      structure,
      viewSpec: defaultView("manuscript", SCHEMA),
      sectionLabel: "Manuscript",
      emptyLabel: "No scenes yet.",
      draftTitles: new Map<string, string>(),
      run,
      onRequestDelete: (_node: StructureNode) => {},
    },
  });
}

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});
afterEach(() => {
  metadataSchemaStore.set(null as unknown as MetadataSchema);
});

describe("StructureTree — the manuscript renders through the view (#724 guard)", () => {
  it("renders the container and its scenes as rows", () => {
    renderTree(manuscript());
    // The whole point: a real manuscript reaches the DOM. If the containment
    // Nest resolved to an empty roster (the #724 trap) none of these would exist.
    expect(screen.getByText("Act One")).toBeInTheDocument();
    expect(screen.getByText("Arrival")).toBeInTheDocument();
    expect(screen.getByText("Departure")).toBeInTheDocument();
  });

  it("shows the no-project message when there is no structure", () => {
    renderTree(null);
    expect(screen.getByText("Open or create a project to begin.")).toBeInTheDocument();
    expect(screen.queryByText("Arrival")).toBeNull();
  });
});
