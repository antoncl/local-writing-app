// Cross-kind navigation (#344). The backlinks panel hands the shell an
// `(id, kind)` pair, and the shell used to dispatch it with a two-branch `if`:
// lore, ELSE SCENE. Every other kind therefore issued `GET /scenes/<id>`, 404'd,
// and left behind the empty pane `#acquireTargetPane` had already claimed — an
// error banner AND a stranded tab.
//
// The kinds that can reach here are the node families the backend index walks
// (`NODE_FAMILIES` in services/project/references.py) plus the project node
// (#334). Reference-edge extraction is schema-driven, so any of them becomes a
// backlink source the moment a user adds an `entity_ref` field to its
// entry_type in the shipped schema editor.
//
// What these tests pin is the property the `else` violated: a kind is either
// routed to ITS OWN opener or refused out loud. Never guessed.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { FOREIGN_PROJECT_NODE, editorPanes } from "./editorPanes.svelte";
import { plotBoardReveal } from "./plotlines";
import { mutationSetEditorStore } from "./mutationSets";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { api } from "@/lib/api";
import { openPlotBoardPane } from "@/lib/stores/plotBoard";
import type { MetadataSchema, MutationSetEntry, ProjectNode } from "@/lib/types";

// `revealOnPlotBoard` (called by the plot-reveal branch below) now opens the
// pane itself (#1920) rather than relying on a shell $effect — mock it so
// these dispatch tests stay about routing, not the pane opener's own effects.
// Only `openPlotBoardPane` is mocked — `refreshPlotBoard`/`plotBoardStore` etc.
// stay real for other imports of this module.
vi.mock("@/lib/stores/plotBoard", async (orig) => ({
  ...(await orig<typeof import("@/lib/stores/plotBoard")>()),
  openPlotBoardPane: vi.fn(),
}));

// A user-authored plot subtype (schema designer, ADR-0048 / class–instance model):
// `plot:noir_card` descends from `plot:card`, `plot:house_template` from
// `plot:template` — the dispatch-by-family-root fixture (#1920, review of #1922).
const PLOT_SUBTYPE_SCHEMA = {
  version: 1,
  entry_types: {
    "plot:card": { name: "Card", kind: "plot", fields: [] },
    "plot:noir_card": { name: "Noir Card", kind: "plot", fields: [], parent: "plot:card" },
    "plot:template": { name: "Template", kind: "plot", fields: [] },
    "plot:house_template": { name: "House Template", kind: "plot", fields: [], parent: "plot:template" },
  },
  fields: {},
} as unknown as MetadataSchema;

// kind → the opener it must reach. The table IS the assertion: a kind wired to
// the wrong opener reads as an obvious mismatch here, which the old code's
// `else` branch could never express.
const ROUTES = [
  ["manuscript", "openScene"],
  ["lore", "openLore"],
  ["research", "openResearchNote"],
  ["prompt", "openPrompt"],
  ["assistant", "openAssistant"],
  ["view", "openView"],
  ["chat", "openChat"],
  ["project", "openProjectNode"],
  // The `plot` kind is NOT in this opener table: its default editor is decided by
  // ENTRY TYPE, not kind (#1920) — a plotline/arc/card reveals on the board rather
  // than opening a pane; only a template opens one (openPlotTemplate). See the
  // dedicated tests below.
] as const;

const LOCAL_PROJECT_NODE: ProjectNode = {
  id: "project_local",
  title: "Book 1",
  body: "",
  revision: "r1",
  entry_type: "project:project",
  metadata: {},
  computed_metadata: {},
};

describe("editorPanes.openNodeOfKind (#344)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(openPlotBoardPane).mockClear();
  });
  afterEach(() => plotBoardReveal.set(null));

  for (const [kind, opener] of ROUTES) {
    it(`routes a ${kind} backlink to ${opener}`, async () => {
      const spies = Object.fromEntries(
        ROUTES.map(([, name]) => [name, vi.spyOn(editorPanes, name).mockResolvedValue(undefined)]),
      );

      await editorPanes.openNodeOfKind("node_1", kind);

      expect(spies[opener]).toHaveBeenCalledWith("node_1");
      // Nothing else fired — the bug was a kind reaching the WRONG opener, so
      // "the right one ran" is only half the assertion.
      for (const [, other] of ROUTES) {
        if (other !== opener) expect(spies[other]).not.toHaveBeenCalled();
      }
    });
  }

  it("reveals a plotline on the board instead of opening a pane", async () => {
    // A plotline is edited on its board node (ADR-0053 §3), so the plot family's
    // dispatch-by-entry-type (#1920) signals a board reveal rather than opening an
    // editor pane. Pin both halves: the signal carries the id + entry type, and no
    // pane opener (incl. openPlotTemplate) fired.
    const spies = [...ROUTES.map(([, name]) => name), "openPlotTemplate" as const].map((name) =>
      vi.spyOn(editorPanes, name).mockResolvedValue(undefined),
    );

    await editorPanes.openNodeOfKind("line_1", "plot", "plot:plotline");

    expect(get(plotBoardReveal)).toEqual({ id: "line_1", entryType: "plot:plotline" });
    expect(openPlotBoardPane).toHaveBeenCalledOnce();
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });

  it("reveals a character arc on the board instead of opening a pane", async () => {
    const spies = [...ROUTES.map(([, name]) => name), "openPlotTemplate" as const].map((name) =>
      vi.spyOn(editorPanes, name).mockResolvedValue(undefined),
    );

    await editorPanes.openNodeOfKind("arc_1", "plot", "plot:character_arc");

    expect(get(plotBoardReveal)).toEqual({ id: "arc_1", entryType: "plot:character_arc" });
    expect(openPlotBoardPane).toHaveBeenCalledOnce();
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });

  it("reveals a card lit on the board instead of opening a pane", async () => {
    const spies = [...ROUTES.map(([, name]) => name), "openPlotTemplate" as const].map((name) =>
      vi.spyOn(editorPanes, name).mockResolvedValue(undefined),
    );

    await editorPanes.openNodeOfKind("card_1", "plot", "plot:card");

    expect(get(plotBoardReveal)).toEqual({ id: "card_1", entryType: "plot:card" });
    expect(openPlotBoardPane).toHaveBeenCalledOnce();
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });

  it("opens a plot template as a document instead of revealing it on the board", async () => {
    // A template is not a board node — it opens via its own NodeEditor route
    // (#1920) — so it must reach openPlotTemplate, and nothing else, and never
    // touch the board-reveal signal.
    const openPlotTemplate = vi.spyOn(editorPanes, "openPlotTemplate").mockResolvedValue(undefined);
    const spies = ROUTES.map(([, name]) => vi.spyOn(editorPanes, name).mockResolvedValue(undefined));

    await editorPanes.openNodeOfKind("tpl_1", "plot", "plot:template");

    expect(openPlotTemplate).toHaveBeenCalledWith("tpl_1");
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    expect(get(plotBoardReveal)).toBeNull();
    expect(openPlotBoardPane).not.toHaveBeenCalled();
  });

  it("refuses a plot node with no entry type instead of guessing", async () => {
    // The old "else → show the board" branch was a guess that opened nothing
    // (#1920); a missing entry type now throws like an unknown kind does.
    const spies = [...ROUTES.map(([, name]) => name), "openPlotTemplate" as const].map((name) =>
      vi.spyOn(editorPanes, name).mockResolvedValue(undefined),
    );

    await expect(editorPanes.openNodeOfKind("x", "plot")).rejects.toThrow(/not a known plot type/i);

    expect(get(plotBoardReveal)).toBeNull();
    expect(openPlotBoardPane).not.toHaveBeenCalled();
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });

  it("refuses an unknown plot entry type instead of guessing", async () => {
    const spies = [...ROUTES.map(([, name]) => name), "openPlotTemplate" as const].map((name) =>
      vi.spyOn(editorPanes, name).mockResolvedValue(undefined),
    );

    await expect(editorPanes.openNodeOfKind("x", "plot", "plot:beat")).rejects.toThrow(/not a known plot type/i);

    expect(get(plotBoardReveal)).toBeNull();
    expect(openPlotBoardPane).not.toHaveBeenCalled();
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });

  describe("dispatch by plot family root, not exact entry type (#1920, review of #1922)", () => {
    beforeEach(() => metadataSchemaStore.set(PLOT_SUBTYPE_SCHEMA));
    afterEach(() => metadataSchemaStore.set(null));

    it("reveals a user-authored card subtype lit on the board, like its plot:card root", async () => {
      const spies = [...ROUTES.map(([, name]) => name), "openPlotTemplate" as const].map((name) =>
        vi.spyOn(editorPanes, name).mockResolvedValue(undefined),
      );

      await editorPanes.openNodeOfKind("card_9", "plot", "plot:noir_card");

      expect(get(plotBoardReveal)).toEqual({ id: "card_9", entryType: "plot:card" });
      expect(openPlotBoardPane).toHaveBeenCalledOnce();
      for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    });

    it("opens a user-authored template subtype as a document, like its plot:template root", async () => {
      const openPlotTemplate = vi.spyOn(editorPanes, "openPlotTemplate").mockResolvedValue(undefined);
      const spies = ROUTES.map(([, name]) => vi.spyOn(editorPanes, name).mockResolvedValue(undefined));

      await editorPanes.openNodeOfKind("tpl_9", "plot", "plot:house_template");

      expect(openPlotTemplate).toHaveBeenCalledWith("tpl_9");
      for (const spy of spies) expect(spy).not.toHaveBeenCalled();
      expect(get(plotBoardReveal)).toBeNull();
      expect(openPlotBoardPane).not.toHaveBeenCalled();
    });
  });

  it("refuses an unknown kind instead of falling back to openScene", async () => {
    // The regression itself. A kind nobody wired up must NOT silently become a
    // scene fetch — that is what stranded the pane.
    const openScene = vi.spyOn(editorPanes, "openScene").mockResolvedValue(undefined);

    await expect(editorPanes.openNodeOfKind("note_1", "some_future_kind")).rejects.toThrow(
      /cannot open a some_future_kind node/i,
    );
    expect(openScene).not.toHaveBeenCalled();
  });

  it("follows a mutation-set backlink to its app-level dialog (#449)", async () => {
    // A mutation set has no pane; like `plot` it routes to a store signal. Since
    // ADR-0055 lifted the editor's target into `mutationSetEditorStore`, the
    // backlink resolves by fetching the set and opening that dialog — pin both
    // halves: the store carries the fetched entry, and no pane opener fired.
    mutationSetEditorStore.set(null);
    const entry = { id: "mut_1", title: "Becomes a werewolf" } as MutationSetEntry;
    const getEntry = vi.spyOn(api, "getMutationSetEntry").mockResolvedValue(entry);
    const spies = ROUTES.map(([, name]) => vi.spyOn(editorPanes, name).mockResolvedValue(undefined));

    await editorPanes.openNodeOfKind("mut_1", "mutation_set");

    expect(getEntry).toHaveBeenCalledWith("mut_1");
    expect(get(mutationSetEditorStore)).toEqual({ editing: entry });
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    mutationSetEditorStore.set(null);
  });
});

describe("editorPanes.openProjectNode id guard (#344/#334)", () => {
  // `run` is App's injected error sink. The default rethrows nothing and
  // swallows nothing, so a test that wants to SEE a refusal has to stand in for
  // App — and has to put the real one back, since the controller is a singleton.
  const defaultRun = editorPanes.run;
  let reported: string[] = [];

  beforeEach(() => {
    vi.restoreAllMocks();
    editorPanes.reset();
    reported = [];
    editorPanes.run = async (action) => {
      try {
        await action();
        return true;
      } catch (caught) {
        reported.push(caught instanceof Error ? caught.message : String(caught));
        return false;
      }
    };
    vi.spyOn(api, "getProjectNode").mockResolvedValue(LOCAL_PROJECT_NODE);
  });

  afterEach(() => {
    editorPanes.run = defaultRun;
    editorPanes.reset();
  });

  it("opens the project node when the backlink names the open project's", async () => {
    await editorPanes.openNodeOfKind("project_local", "project");

    expect(editorPanes.panes.some((pane) => pane.document?.type === "project")).toBe(true);
    expect(reported).toEqual([]);
  });

  it("refuses an ancestor layer's project node and claims no pane", async () => {
    // `project.md` is a singleton PER LAYER, so a backlink can name a
    // universe's or series' node. Opening the local one under that id would
    // show the wrong document with the right title — the quietest possible
    // wrong answer, and the reason the id is checked rather than assumed.
    await editorPanes.openNodeOfKind("project_universe", "project");

    expect(reported).toEqual([FOREIGN_PROJECT_NODE]);
    // The claim `#acquireTargetPane` stamps synchronously must be released, or
    // the refusal strands exactly the empty pane #344 is about.
    expect(editorPanes.panes.some((pane) => pane.document !== null)).toBe(false);
  });

  it("refuses a foreign id even when the project node is already open", async () => {
    // The OTHER guard branch. `openProjectNode` short-circuits on an
    // already-open project pane before it ever fetches, so that path needs its
    // own check — without one it would focus the local node and report success
    // for an id that is not the one asked for.
    await editorPanes.openNodeOfKind("project_local", "project");
    expect(editorPanes.panes.some((pane) => pane.document?.type === "project")).toBe(true);

    await expect(editorPanes.openNodeOfKind("project_universe", "project")).rejects.toThrow(FOREIGN_PROJECT_NODE);

    // …and the pane that WAS open is untouched — a refusal must not disturb it.
    expect(editorPanes.panes.filter((pane) => pane.document?.type === "project")).toHaveLength(1);
  });
});
