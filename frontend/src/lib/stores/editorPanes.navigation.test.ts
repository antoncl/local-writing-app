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
import { FOREIGN_PROJECT_NODE, editorPanes } from "./editorPanes.svelte";
import { api } from "@/lib/api";
import type { ProjectNode } from "@/lib/types";

// kind → the opener it must reach. The table IS the assertion: a kind wired to
// the wrong opener reads as an obvious mismatch here, which the old code's
// `else` branch could never express.
const ROUTES = [
  ["scene", "openScene"],
  ["lore", "openLore"],
  ["research", "openResearchNote"],
  ["prompt", "openPrompt"],
  ["assistant", "openAssistant"],
  ["view", "openView"],
  ["chat", "openChat"],
  ["project", "openProjectNode"],
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
  beforeEach(() => vi.restoreAllMocks());

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

  it("refuses an unknown kind instead of falling back to openScene", async () => {
    // The regression itself. A kind nobody wired up must NOT silently become a
    // scene fetch — that is what stranded the pane.
    const openScene = vi.spyOn(editorPanes, "openScene").mockResolvedValue(undefined);

    await expect(editorPanes.openNodeOfKind("note_1", "some_future_kind")).rejects.toThrow(
      /cannot open a some_future_kind node/i,
    );
    expect(openScene).not.toHaveBeenCalled();
  });

  it("refuses a mutation set by name rather than opening something else", async () => {
    const openScene = vi.spyOn(editorPanes, "openScene").mockResolvedValue(undefined);

    await expect(editorPanes.openNodeOfKind("mut_1", "mutation_set")).rejects.toThrow(/Mutations pane/);
    expect(openScene).not.toHaveBeenCalled();
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
