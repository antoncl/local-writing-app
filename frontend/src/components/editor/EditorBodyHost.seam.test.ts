// @vitest-environment happy-dom
// #2029 — EditorBodyHost's seams for a shape that mounts NO prose view (chat /
// view / none). The shell composes bodies as `bodyHost?.getBody() ?? scene?.body
// ?? ""` (snapshot capture, the scrub overlay, the review's current-body
// read), so the seam must report "no body" as `undefined`, never "": coalescing
// here would silently capture an empty body for those kinds. The none shape
// is the one branch that mounts without TipTap, so it is the one under test.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@/lib/test/component";
import EditorBodyHost from "./EditorBodyHost.svelte";
import type { MetadataSchema } from "@/lib/types";

type Seams = {
  getBody(): string | undefined;
  tryMergeProse(baseBody: string, remoteBody: string): Promise<string | null>;
};

function baseModel(over: Record<string, unknown> = {}) {
  const noop = () => {};
  return {
    scene: null,
    documentKind: "project",
    bodyShape: "none",
    rawBodyLanguage: "markdown",
    loadedSceneId: null,
    entryType: "",
    metadata: {},
    metadataSchema: null,
    editorReadOnly: false,
    inheritedReadOnly: false,
    reviewing: false,
    scrubbed: false,
    snapshotParked: false,
    overlayBodyHtml: "",
    snapshotRibbon: null,
    scrub: {},
    snapshots: {},
    entryReview: { hasReview: false, proposal: null },
    detailsDetached: false,
    chatTitleField: noop,
    metaContent: noop,
    activeBodyTab: "body",
    ...over,
  };
}

function baseDeps(over: Record<string, unknown> = {}) {
  const noop = () => {};
  return {
    loreEntries: [],
    promptEntries: [],
    assistantEntries: [],
    availableScenes: [],
    structure: null,
    researchStructure: null,
    implicitContextMatcher: null,
    defaultAssistantId: "",
    documentLabel: "Project",
    hostPaneId: "p1",
    sectionRegistry: { register: noop, unregister: noop, neighboursFor: () => ({ prev: null, next: null }), focus: noop },
    promptDrafts: { drafts: {} },
    ...over,
  };
}

function mountNoneShape(modelOver: Record<string, unknown> = {}, depsOver: Record<string, unknown> = {}) {
  const noop = () => {};
  return render(EditorBodyHost, {
    props: {
      model: baseModel(modelOver),
      deps: baseDeps(depsOver),
      on: { change: noop, focus: noop, openChat: noop, requestInputsDialog: noop, metadataChange: noop, viewSaveState: noop, navigate: noop },
    } as never,
  });
}

function seams(): Seams {
  return mountNoneShape().component as unknown as Seams;
}

describe("EditorBodyHost seams without a prose view (#2029)", () => {
  it("getBody reports no body as undefined, never an empty string", () => {
    expect(seams().getBody()).toBeUndefined();
  });

  it("tryMergeProse resolves null (non-prose), so the 409 handler falls to the dialog", async () => {
    await expect(seams().tryMergeProse("base", "remote")).resolves.toBeNull();
  });
});

const SCHEMA = {
  version: 1,
  entry_types: {
    "structure_node:project": { name: "Project", kind: "structure_node", fields: ["kin"] },
    "lore:character": { name: "Character", kind: "lore", fields: [] },
  },
  fields: {
    kin: { name: "Kin", type: "entity_ref_list", options: [], picker_config: { sources: [{ kind: "lore" }] } },
  },
} as unknown as MetadataSchema;

describe("EditorBodyHost — none shape + a list tab (#2010)", () => {
  it("renders ReferenceListTab and hides the none-shape metaContent host, without unmounting it", () => {
    const { container } = mountNoneShape({
      scene: { id: "proj_1", title: "Project" },
      entryType: "structure_node:project",
      metadata: { kin: ["lore_1"] },
      metadataSchema: SCHEMA,
      activeBodyTab: "list:kin",
    });
    const host = container.querySelector(".none-body-host");
    expect(host).not.toBeNull();
    expect(host?.classList.contains("hidden")).toBe(true);
    // Still mounted underneath — never unmounted (TipTap-analogous state).
    expect(container.querySelector(".editor-pane-meta")).not.toBeNull();
    // The list tab itself rendered.
    expect(container.querySelector(".ref-list-tab")).not.toBeNull();
    expect(container.querySelector(".ref-list-label")?.textContent).toContain("Kin");
  });

  it("a remove in the list tab reaches metadataChange with the field replaced and every sibling key intact", async () => {
    const metadataChange = vi.fn();
    const noop = () => {};
    const { container } = render(EditorBodyHost, {
      props: {
        model: baseModel({
          scene: { id: "proj_1", title: "Project" },
          entryType: "structure_node:project",
          metadata: { kin: ["lore_1", "lore_2"], color: "amber" },
          metadataSchema: SCHEMA,
          activeBodyTab: "list:kin",
        }),
        deps: baseDeps({
          loreEntries: [
            { id: "lore_1", title: "Mara", entry_type: "lore:character", metadata: {} },
            { id: "lore_2", title: "Tomas", entry_type: "lore:character", metadata: {} },
          ],
        }),
        on: { change: noop, focus: noop, openChat: noop, requestInputsDialog: noop, metadataChange, viewSaveState: noop, navigate: noop },
      } as never,
    });
    const remove = container.querySelector<HTMLButtonElement>('.row-action-delete[aria-label="Remove Tomas from Kin"]');
    expect(remove).not.toBeNull();
    await fireEvent.click(remove!);
    expect(metadataChange).toHaveBeenCalledWith({ kin: ["lore_1"], color: "amber" });
  });
});
