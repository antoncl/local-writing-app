// @vitest-environment happy-dom
// #2029 — EditorBodyHost's seams for a shape that mounts NO prose view (chat /
// view / none). The shell composes bodies as `bodyHost?.getBody() ?? scene?.body
// ?? ""` (snapshot capture, the scrub overlay, the review's current-body
// read), so the seam must report "no body" as `undefined`, never "": coalescing
// here would silently capture an empty body for those kinds. The none shape
// is the one branch that mounts without TipTap, so it is the one under test.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@/lib/test/component";
import EditorBodyHost from "./EditorBodyHost.svelte";
import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { EntryProposalController } from "@/lib/stores/entryProposal.svelte";
import { entryBrainstorm } from "@/lib/stores/entryBrainstorm.svelte";
import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";

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

// #2074 (ADR-0042 §5): a reference-keyed list tab is editable AT A SCRUB STOP
// whose own unit touches the open node — the change routes through the
// injected scrub-stop rewrite, never the ordinary whole-field metadataChange.
const REL_SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["relationships"] },
  },
  fields: {
    relationships: {
      name: "Relationships",
      type: "list",
      options: [],
      item_scalar: false,
      item_members: [
        { key: "to", name: "To", type: "entity_ref", picker_config: { sources: [{ kind: "lore" }] } },
      ],
    },
  },
} as unknown as MetadataSchema;

const REL_ENTRIES: LoreEntrySummary[] = [
  { id: "char_tomas", title: "Tomas", body: "", entry_type: "lore:character", metadata: {} },
  { id: "char_elena", title: "Elena", body: "", entry_type: "lore:character", metadata: {} },
];

// The body diff overlay (a pending AI proposal) covers the body + its long_text
// sections, which all live on the Body tab. A list tab (References,
// Conversations, …) takes the body grid slot, so the overlay must render ONLY on
// the Body tab — otherwise it paints over the active list tab regardless of
// which tab you pick.
const REVIEW_SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["kin"] } },
  fields: { kin: { name: "Kin", type: "entity_ref_list", options: [], picker_config: { sources: [{ kind: "lore" }] } } },
} as unknown as MetadataSchema;

function reviewController(): EntryProposalController {
  const c = new EntryProposalController();
  c.nodeId = "e1";
  c.schema = REVIEW_SCHEMA;
  entryBrainstorm.propose("e1", { body: "proposed body", fields: {} });
  return c;
}

function mountReview(activeBodyTab: string, bodyShape: "prose" | "code" = "prose") {
  const noop = () => {};
  return render(EditorBodyHost, {
    props: {
      model: baseModel({
        scene: { id: "e1", title: "Mara" },
        bodyShape,
        loadedSceneId: "e1",
        entryType: "lore:character",
        metadata: { kin: ["lore_1"] },
        metadataSchema: REVIEW_SCHEMA,
        reviewing: true,
        entryReview: reviewController(),
        activeBodyTab,
      }),
      deps: baseDeps({
        loreEntries: [{ id: "lore_1", title: "Tomas", entry_type: "lore:character", metadata: {} }],
        promptDrafts: { drafts: {}, nextDraftId: () => "d1", slugify: (s: string) => s },
      }),
      on: { change: noop, focus: noop, openChat: noop, requestInputsDialog: noop, metadataChange: noop, viewSaveState: noop, navigate: noop },
    } as never,
  });
}

// Both body shapes that mount the overlay (prose — the common lore/note case —
// and code — a prompt template, #711) gate it the same way, by two different
// template paths (a wrapper `{#if}` for prose, an inline `&&` for code), so both
// are exercised.
describe.each(["prose", "code"] as const)("EditorBodyHost — the body diff overlay is Body-tab-only (%s)", (shape) => {
  beforeEach(() => {
    entryBrainstorm.clear("e1");
    // ProseBodyView loads the AI-cost log on mount; keep the seam off the network.
    vi.spyOn(api, "aiListInvocations").mockResolvedValue({ invocations: [] } as never);
  });
  afterEach(() => {
    entryBrainstorm.clear("e1");
    vi.restoreAllMocks();
  });

  it("renders the proposal diff overlay on the Body tab", () => {
    const { container } = mountReview("body", shape);
    expect(container.querySelector(".entry-revision-review")).not.toBeNull();
  });

  it("does NOT render the body diff overlay on a list tab", () => {
    const { container } = mountReview("list:kin", shape);
    // The list tab is active — the diff belongs to the body, not this tab.
    expect(container.querySelector(".entry-revision-review")).toBeNull();
    // …and the list tab itself still renders.
    expect(container.querySelector(".ref-list-tab")).not.toBeNull();
  });
});

// C2: ADR-0095 §8 moves the scrub-stop list edit to a mutation-SET save
// (rebuilt in S2); until then EditorBodyHost's injected `rewriteMutationUnit`
// dep is a stub that always rejects, so a stop-editable list click is
// routed away from `metadataChange` but performs no write. This test now
// only asserts that no-write behaviour, not the removed rewrite call.
describe("EditorBodyHost — scrub-stop list edit (#2074, ADR-0042 §5)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("a scrubbed model with a stopUnit targeting the node routes a list-tab change away from metadataChange (ADR-0095 S2 stub)", async () => {
    const stopUnit = {
      unitId: "mut_head",
      name: "",
      records: [
        {
          marker_id: "mut_head",
          entity_id: "char_tomas",
          field: "relationships",
          op: "add",
          value: JSON.stringify({ to: "char_elena" }),
          name: "",
          group: "",
          unit_id: "mut_head",
          unit_name: "",
          anchor_id: "mut_head",
          set_id: "mutset_1",
          row_id: "mut_head",
          scene_id: "s1",
          offset: 5,
          line: 1,
          scene_path: "",
        },
      ],
    };
    const reload = vi.fn().mockResolvedValue(undefined);
    const getEffective = vi
      .spyOn(api, "getEntityEffectiveState")
      .mockResolvedValue({ entity_id: "char_tomas", scene_id: "s1", position: 5, values: {} });
    const flush = vi.spyOn(editorPanes, "flushSceneIfDirty").mockResolvedValue(undefined);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const metadataChange = vi.fn();
    const noop = () => {};
    const { container } = render(EditorBodyHost, {
      props: {
        model: baseModel({
          scene: { id: "char_tomas", title: "Tomas" },
          entryType: "lore:character",
          metadata: { relationships: [] },
          metadataSchema: REL_SCHEMA,
          activeBodyTab: "list:relationships",
          scrubbed: true,
          editorReadOnly: true,
          stopUnit,
          scrub: { reload, overrides: { relationships: [{ to: "char_elena" }] } },
        }),
        deps: baseDeps({ loreEntries: REL_ENTRIES }),
        on: { change: noop, focus: noop, openChat: noop, requestInputsDialog: noop, metadataChange, viewSaveState: noop, navigate: noop },
      } as never,
    });

    // stopEditable: the effective item renders with a delete affordance (not
    // the plain read-only detail the base scrub overlay would show).
    const removeButton = container.querySelector<HTMLButtonElement>(".row-action-delete");
    expect(removeButton).not.toBeNull();
    await fireEvent.click(removeButton!);

    await vi.waitFor(() => expect(getEffective).toHaveBeenCalled());
    await vi.waitFor(() => expect(consoleError).toHaveBeenCalled());
    expect(flush).toHaveBeenCalledWith("s1");
    expect(reload).not.toHaveBeenCalled();
    expect(metadataChange).not.toHaveBeenCalled();
  });
});
