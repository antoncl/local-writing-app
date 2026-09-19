// @vitest-environment happy-dom
// #2029 — EditorBodyHost's seams for a shape that mounts NO prose view (chat /
// view / none). The shell composes bodies as `bodyHost?.getBody() ?? scene?.body
// ?? ""` (snapshot capture, the scrub overlay, the review's current-body
// read), so the seam must report "no body" as `undefined`, never "": coalescing
// here would silently capture an empty body for those kinds. The none shape
// is the one branch that mounts without TipTap, so it is the one under test.
import { describe, expect, it } from "vitest";
import { render } from "@/lib/test/component";
import EditorBodyHost from "./EditorBodyHost.svelte";

type Seams = {
  getBody(): string | undefined;
  tryMergeProse(baseBody: string, remoteBody: string): Promise<string | null>;
};

function mountNoneShape(): Seams {
  const noop = () => {};
  const { component } = render(EditorBodyHost, {
    props: {
      model: {
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
      },
      deps: {
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
      },
      on: { change: noop, focus: noop, openChat: noop, requestInputsDialog: noop, metadataChange: noop, viewSaveState: noop },
    } as never,
  });
  return component as unknown as Seams;
}

describe("EditorBodyHost seams without a prose view (#2029)", () => {
  it("getBody reports no body as undefined, never an empty string", () => {
    expect(mountNoneShape().getBody()).toBeUndefined();
  });

  it("tryMergeProse resolves null (non-prose), so the 409 handler falls to the dialog", async () => {
    await expect(mountNoneShape().tryMergeProse("base", "remote")).resolves.toBeNull();
  });
});
