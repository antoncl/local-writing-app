/**
 * Plot content commands (ADR-0053 §7, #902) — the undoable board ops. Driven
 * through a fake `PlotCommandPort` (an in-memory card/plotline store + a call log),
 * so the builders and the recorder are exercised exactly as the caretaker + PlotEditor
 * drive them, without a backend. The pure referrer finders take a plain projection.
 */
import { describe, expect, it } from "vitest";
import {
  type CardRef,
  type PlotCommandPort,
  PlotUndoRecorder,
  cardEditCommand,
  cardEditManyCommand,
  cardsReferencingCard,
  cardsReferencingPlotline,
  createArcCommand,
  createCardCommand,
  createPlotlineCommand,
  deleteArcCommand,
  deleteCardCommand,
  deletePlotlineCommand,
  arcEditCommand,
  plotlineEditCommand,
  realizeCommand,
  seedCommand,
} from "./plotCommands";
import { UndoCancelled } from "@/lib/stores/undoCaretaker.svelte";
import type { CardState } from "@/lib/stores/plotBoard";
import type { PlotlineState } from "@/lib/stores/plotlines";
import type { ArcState } from "@/lib/stores/characterArcs";
import type { PlotBoardCard, PlotBoardProjection } from "@/lib/types";

const cardState = (title: string, metadata: CardState["metadata"] = {}, body = ""): CardState => ({
  title,
  body,
  metadata,
});
const plotlineState = (title: string, metadata: PlotlineState["metadata"] = {}, body = ""): PlotlineState => ({
  title,
  body,
  metadata,
});
const arcState = (title: string, metadata: ArcState["metadata"] = {}, body = ""): ArcState => ({
  title,
  body,
  metadata,
});

function fakePort() {
  const cards = new Map<string, CardState>();
  const plotlines = new Map<string, PlotlineState>();
  const arcs = new Map<string, ArcState>();
  // Scene model for the realize tests: body per scene + which cards reference each.
  const scenes = new Map<string, { title: string; body: string }>();
  const sceneRefs = new Map<string, Set<string>>();
  let sceneCounter = 0;
  // What the (mocked) suppressible confirm resolves; flip per test.
  const confirm = { result: true };
  const calls: string[] = [];
  const port: PlotCommandPort = {
    deleteCard: async (id) => {
      calls.push(`deleteCard:${id}`);
      cards.delete(id);
    },
    getCardState: async (id) => structuredClone(cards.get(id)!),
    restoreCardState: async (id, s) => {
      calls.push(`restoreCard:${id}`);
      cards.set(id, structuredClone(s));
    },
    recreateCard: async (id, s) => {
      calls.push(`recreateCard:${id}`);
      cards.set(id, structuredClone(s));
    },
    deletePlotline: async (id) => {
      calls.push(`deletePlotline:${id}`);
      plotlines.delete(id);
    },
    getPlotlineState: async (id) => structuredClone(plotlines.get(id)!),
    restorePlotlineState: async (id, s) => {
      calls.push(`restorePlotline:${id}`);
      plotlines.set(id, structuredClone(s));
    },
    recreatePlotline: async (id, s) => {
      calls.push(`recreatePlotline:${id}`);
      plotlines.set(id, structuredClone(s));
    },
    deleteArc: async (id) => {
      calls.push(`deleteArc:${id}`);
      arcs.delete(id);
    },
    getArcState: async (id) => structuredClone(arcs.get(id)!),
    restoreArcState: async (id, s) => {
      calls.push(`restoreArc:${id}`);
      arcs.set(id, structuredClone(s));
    },
    recreateArc: async (id, s) => {
      calls.push(`recreateArc:${id}`);
      arcs.set(id, structuredClone(s));
    },
    refreshBoard: async () => {
      calls.push("refreshBoard");
    },
    refreshRoster: async () => {
      calls.push("refreshRoster");
    },
    refreshArcRoster: async () => {
      calls.push("refreshArcRoster");
    },
    realizeCard: async (cardId, _parentId) => {
      const id = `scene_${++sceneCounter}`;
      calls.push(`realize:${cardId}->${id}`);
      scenes.set(id, { title: `Scene for ${cardId}`, body: "" });
      sceneRefs.set(id, new Set([cardId]));
      return id;
    },
    sceneReferents: (sceneId) => [...(sceneRefs.get(sceneId) ?? [])],
    readScene: async (sceneId) => structuredClone(scenes.get(sceneId)!),
    deleteScene: async (sceneId) => {
      calls.push(`deleteScene:${sceneId}`);
      scenes.delete(sceneId);
      sceneRefs.delete(sceneId);
    },
    detachCardScene: async (cardId) => {
      calls.push(`detach:${cardId}`);
      for (const refs of sceneRefs.values()) refs.delete(cardId);
    },
    confirmSceneDelete: async () => {
      calls.push("confirm");
      return confirm.result;
    },
  };
  return { port, cards, plotlines, arcs, scenes, sceneRefs, confirm, calls };
}

// A projection with just the fields the finders / recorder read.
function card(id: string, extra: Partial<PlotBoardCard> = {}): PlotBoardCard {
  return {
    id,
    title: id,
    synopsis: "",
    plotline: null,
    scene: null,
    container: null,
    page_status: null,
    beats: [],
    sequence: null,
    causal_links: [],
    ...extra,
  };
}
function projection(cards: PlotBoardCard[]): PlotBoardProjection {
  return { board_id: "b", board_revision: "r", layout: {}, plotlines: [], arcs: [], containers: [], cards, diagnostics: [] };
}

describe("referrer finders", () => {
  it("finds cards whose causal_links point at a card", () => {
    const proj = projection([
      card("a", { causal_links: ["target"] }),
      card("b", { causal_links: ["other"] }),
      card("target"),
    ]);
    expect(cardsReferencingCard(proj, "target")).toEqual(["a"]);
  });

  it("finds cards whose primary plotline OR a beat points at a plotline", () => {
    const proj = projection([
      card("primary", { plotline: "P" }),
      card("beat-only", {
        beats: [
          {
            plotline_id: "P",
            plotline_title: "",
            plotline_color: null,
            beat_id: "b1",
            title: "",
            number: 1,
            holder_kind: "plot:plotline",
            character_id: null,
            character_name: null,
            character_initial: null,
          },
        ],
      }),
      card("elsewhere", { plotline: "Q" }),
    ]);
    expect(cardsReferencingPlotline(proj, "P")).toEqual(["primary", "beat-only"]);
  });
});

describe("create / delete card commands", () => {
  it("createCard: undo deletes, redo recreates under the id", async () => {
    const { port, cards, calls } = fakePort();
    cards.set("c1", cardState("Card"));
    const cmd = createCardCommand(port, "c1", cardState("Card"));
    await cmd.undo();
    expect(cards.has("c1")).toBe(false);
    await cmd.redo();
    expect(cards.get("c1")).toEqual(cardState("Card"));
    expect(calls).toEqual(["deleteCard:c1", "recreateCard:c1"]);
  });

  it("deleteCard: undo recreates the node THEN restores referrers, redo re-deletes", async () => {
    const { port, calls } = fakePort();
    const referrers: CardRef[] = [
      { id: "refA", state: cardState("A", { causal_links: [{ target: "gone" }] }) },
      { id: "refB", state: cardState("B", { causal_links: [{ target: "gone" }] }) },
    ];
    const cmd = deleteCardCommand(port, "gone", cardState("Gone"), referrers);
    await cmd.undo();
    // Node first (so the referrers' refs are not dangling-healed), then the referrers
    // (their per-item refetch suppressed), then ONE board refresh (#909 batch).
    expect(calls).toEqual(["recreateCard:gone", "restoreCard:refA", "restoreCard:refB", "refreshBoard"]);
    calls.length = 0;
    await cmd.redo();
    expect(calls).toEqual(["deleteCard:gone"]);
  });
});

describe("card edit command", () => {
  it("flips whole card state before/after", async () => {
    const { port, cards, calls } = fakePort();
    cards.set("c1", cardState("after", { plotline: "P2" }));
    const cmd = cardEditCommand(port, "c1", cardState("before", { plotline: "P1" }), cardState("after", { plotline: "P2" }), "reassign plotline");
    await cmd.undo();
    expect(cards.get("c1")).toEqual(cardState("before", { plotline: "P1" }));
    await cmd.redo();
    expect(cards.get("c1")).toEqual(cardState("after", { plotline: "P2" }));
    expect(cmd.label).toBe("reassign plotline");
    expect(calls).toEqual(["restoreCard:c1", "restoreCard:c1"]);
  });

  it("restores SEVERAL cards as one step (a beat move card→card, #941)", async () => {
    const { port, cards, calls } = fakePort();
    const before: CardRef[] = [
      { id: "from", state: cardState("From", { beat_links: [{ plotline: "P", beat_id: "b1" }] }) },
      { id: "to", state: cardState("To", { beat_links: [] }) },
    ];
    const after: CardRef[] = [
      { id: "from", state: cardState("From", { beat_links: [] }) },
      { id: "to", state: cardState("To", { beat_links: [{ plotline: "P", beat_id: "b1" }] }) },
    ];
    const cmd = cardEditManyCommand(port, before, after, "move beat");
    await cmd.undo();
    expect(cards.get("from")).toEqual(before[0].state);
    expect(cards.get("to")).toEqual(before[1].state);
    await cmd.redo();
    expect(cards.get("from")).toEqual(after[0].state);
    expect(cards.get("to")).toEqual(after[1].state);
    // One step touches both cards on undo and again on redo (two restores each).
    expect(calls).toEqual(["restoreCard:from", "restoreCard:to", "restoreCard:from", "restoreCard:to"]);
  });
});

describe("plotline commands", () => {
  it("create: undo deletes, redo recreates with beats + lineage", async () => {
    const { port, plotlines } = fakePort();
    const state = plotlineState("Thread", { color: "rose", instance_beats: [{ beat_id: "b1", title: "Meet" }] });
    plotlines.set("p1", state);
    const cmd = createPlotlineCommand(port, "p1", state);
    await cmd.undo();
    expect(plotlines.has("p1")).toBe(false);
    await cmd.redo();
    expect(plotlines.get("p1")).toEqual(state);
  });

  it("delete: undo recreates the plotline then restores its cards", async () => {
    const { port, calls } = fakePort();
    const referrers: CardRef[] = [{ id: "card1", state: cardState("On thread", { plotline: "p1" }) }];
    const cmd = deletePlotlineCommand(port, "p1", plotlineState("Thread"), referrers);
    await cmd.undo();
    // Plotline first, then its cards (refetch suppressed), then ONE roster+board
    // refresh at the end (#909 batch).
    expect(calls).toEqual(["recreatePlotline:p1", "restoreCard:card1", "refreshRoster", "refreshBoard"]);
  });

  it("edit: flips whole plotline state", async () => {
    const { port, plotlines } = fakePort();
    plotlines.set("p1", plotlineState("Renamed", { color: "moss" }));
    const cmd = plotlineEditCommand(port, "p1", plotlineState("Old", { color: "rose" }), plotlineState("Renamed", { color: "moss" }), "recolour plotline");
    await cmd.undo();
    expect(plotlines.get("p1")).toEqual(plotlineState("Old", { color: "rose" }));
    await cmd.redo();
    expect(plotlines.get("p1")).toEqual(plotlineState("Renamed", { color: "moss" }));
  });
});

describe("character-arc commands (ADR-0080 §5)", () => {
  it("create: undo deletes, redo recreates with beats + lineage — through the ARC port methods", async () => {
    const { port, arcs, calls } = fakePort();
    const state = arcState("Elena's redemption", { color: "rose", character: "char_elena", instance_beats: [{ beat_id: "b1", title: "Denial" }] });
    arcs.set("arc1", state);
    const cmd = createArcCommand(port, "arc1", state);
    await cmd.undo();
    expect(arcs.has("arc1")).toBe(false);
    await cmd.redo();
    expect(arcs.get("arc1")).toEqual(state);
    // The #3b-i correctness point: an arc's undo/redo call the ARC port methods, never
    // deletePlotline/recreatePlotline (which would recreate it AS a plotline).
    expect(calls).toEqual(["deleteArc:arc1", "recreateArc:arc1"]);
  });

  it("delete: undo recreates the arc then restores its cards' change-beat links", async () => {
    const { port, calls } = fakePort();
    const referrers: CardRef[] = [{ id: "card1", state: cardState("Fulfils a change-beat", { beat_links: [{ plotline: "arc1", beat_id: "b1" }] }) }];
    const cmd = deleteArcCommand(port, "arc1", arcState("Elena's redemption"), referrers);
    await cmd.undo();
    expect(calls).toEqual(["recreateArc:arc1", "restoreCard:card1", "refreshArcRoster", "refreshBoard"]);
    calls.length = 0;
    await cmd.redo();
    expect(calls).toEqual(["deleteArc:arc1"]);
  });

  it("edit: flips whole arc state (a rebind or recolour)", async () => {
    const { port, arcs } = fakePort();
    arcs.set("arc1", arcState("Elena's redemption", { character: "char_elena" }));
    const cmd = arcEditCommand(
      port,
      "arc1",
      arcState("Elena's redemption", { character: "" }),
      arcState("Elena's redemption", { character: "char_elena" }),
      "bind character",
    );
    await cmd.undo();
    expect(arcs.get("arc1")).toEqual(arcState("Elena's redemption", { character: "" }));
    await cmd.redo();
    expect(arcs.get("arc1")).toEqual(arcState("Elena's redemption", { character: "char_elena" }));
  });
});

describe("seed command", () => {
  it("undo deletes every seeded card, redo recreates them all", async () => {
    const { port, cards, calls } = fakePort();
    const created: CardRef[] = [
      { id: "s1", state: cardState("Scene 1", { scene: "sc1" }) },
      { id: "s2", state: cardState("Scene 2", { scene: "sc2" }) },
    ];
    created.forEach((c) => cards.set(c.id, c.state));
    const cmd = seedCommand(port, created);
    await cmd.undo();
    expect(cards.size).toBe(0);
    await cmd.redo();
    expect(cards.size).toBe(2);
    // The whole batch in parallel + ONE refresh per direction (#909), not N.
    expect(calls).toEqual([
      "deleteCard:s1",
      "deleteCard:s2",
      "refreshBoard",
      "recreateCard:s1",
      "recreateCard:s2",
      "refreshBoard",
    ]);
  });
});

describe("realize command (S6b)", () => {
  it("undo deletes a sole-referent EMPTY scene silently (no confirm)", async () => {
    const { port, scenes, sceneRefs, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "" });
    sceneRefs.set("sc1", new Set(["c1"]));
    const cmd = realizeCommand(port, "c1", null, "sc1");
    await cmd.undo();
    expect(calls).toEqual(["deleteScene:sc1"]); // no "confirm" — empty scene
    expect(scenes.has("sc1")).toBe(false);
  });

  it("undo confirms before deleting a sole-referent scene that holds prose", async () => {
    const { port, scenes, sceneRefs, confirm, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "She admits it." });
    sceneRefs.set("sc1", new Set(["c1"]));
    confirm.result = true;
    await realizeCommand(port, "c1", null, "sc1").undo();
    expect(calls).toEqual(["confirm", "deleteScene:sc1"]);
    expect(scenes.has("sc1")).toBe(false);
  });

  it("undo of a written scene ABORTS (throws UndoCancelled, nothing mutated) when declined", async () => {
    const { port, scenes, sceneRefs, confirm, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "Precious prose." });
    sceneRefs.set("sc1", new Set(["c1"]));
    confirm.result = false;
    await expect(realizeCommand(port, "c1", null, "sc1").undo()).rejects.toBeInstanceOf(UndoCancelled);
    expect(calls).toEqual(["confirm"]); // no delete — the scene (and the realize) survive
    expect(scenes.has("sc1")).toBe(true);
  });

  it("undo of a SHARED scene keeps it and detaches only this card", async () => {
    const { port, scenes, sceneRefs, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "prose" });
    sceneRefs.set("sc1", new Set(["c1", "c2"])); // another card attached since realize
    await realizeCommand(port, "c1", null, "sc1").undo();
    expect(calls).toEqual(["detach:c1"]); // no confirm, no delete — the scene is shared
    expect(scenes.has("sc1")).toBe(true);
  });

  it("undo is a no-op when this card no longer references the scene", async () => {
    const { port, scenes, sceneRefs, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "" });
    sceneRefs.set("sc1", new Set(["other"])); // c1 was detached/re-realized elsewhere
    await realizeCommand(port, "c1", null, "sc1").undo();
    expect(calls).toEqual([]); // nothing to reverse
    expect(scenes.has("sc1")).toBe(true);
  });

  it("redo re-mints a fresh scene, and the next undo targets THAT scene", async () => {
    const { port, scenes, sceneRefs, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "" });
    sceneRefs.set("sc1", new Set(["c1"]));
    const cmd = realizeCommand(port, "c1", null, "sc1");
    await cmd.undo(); // deletes sc1
    await cmd.redo(); // re-mints → scene_1 (fake counter), attached to c1
    expect(calls).toEqual(["deleteScene:sc1", "realize:c1->scene_1"]);
    await cmd.undo(); // must delete the NEW scene, not the gone sc1
    expect(calls).toEqual(["deleteScene:sc1", "realize:c1->scene_1", "deleteScene:scene_1"]);
  });
});

describe("PlotUndoRecorder", () => {
  it("cardEdit records a command only when the op actually changed the card", async () => {
    const { port, cards } = fakePort();
    cards.set("c1", cardState("Card", { plotline: "P1" }));
    const recorded: { label?: string }[] = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));

    // No-op: the op leaves the card unchanged → nothing recorded.
    await recorder.cardEdit("c1", "reassign plotline", async () => {});
    expect(recorded).toEqual([]);

    // Real change: the op mutates the fake's stored state → one command.
    await recorder.cardEdit("c1", "reassign plotline", async () => {
      cards.set("c1", cardState("Card", { plotline: "P2" }));
    });
    expect(recorded.map((c) => c.label)).toEqual(["reassign plotline"]);
  });

  it("arcEdit records a command only when the op actually changed the arc", async () => {
    const { port, arcs } = fakePort();
    arcs.set("arc1", arcState("Elena's redemption", { character: "char_elena" }));
    const recorded: { label?: string }[] = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));

    // No-op.
    await recorder.arcEdit("arc1", "bind character", async () => {});
    expect(recorded).toEqual([]);

    // Real change.
    await recorder.arcEdit("arc1", "bind character", async () => {
      arcs.set("arc1", arcState("Elena's redemption", { character: "char_marcus" }));
    });
    expect(recorded.map((c) => c.label)).toEqual(["bind character"]);
  });

  it("createCard runs the forward op and records the new id + captured state", async () => {
    const { port, cards, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));

    const id = await recorder.createCard(async () => {
      cards.set("new1", cardState("Fresh"));
      return "new1";
    });
    expect(id).toBe("new1");
    // The recorded command's undo deletes the just-created card.
    await recorded[0].undo();
    expect(cards.has("new1")).toBe(false);
    expect(calls).toContain("deleteCard:new1");
  });

  it("createArc runs the forward op and records the new id + captured state — never through createPlotline", async () => {
    const { port, arcs, plotlines, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));

    // Mirrors the instantiate-branch routing in PlotEditor: the ONE instantiate call
    // already minted the entry (arcs.set below stands in for that), so the `create`
    // callback just hands back the id already returned — it does not mint again.
    arcs.set("arc1", arcState("Elena's redemption"));
    const id = await recorder.createArc(async () => "arc1");
    expect(id).toBe("arc1");
    await recorded[0].undo();
    expect(arcs.has("arc1")).toBe(false);
    expect(plotlines.size).toBe(0); // never touched the plotline substrate
    expect(calls).toEqual(["deleteArc:arc1"]);
  });

  it("deleteArc captures the projection's referrers (cards fulfilling a change-beat) before deleting", async () => {
    const { port, arcs, cards } = fakePort();
    arcs.set("gone", arcState("Gone"));
    cards.set("card1", cardState("Fulfils a change-beat", { beat_links: [{ plotline: "gone", beat_id: "b1" }] }));
    const proj = projection([
      card("card1", {
        beats: [
          {
            plotline_id: "gone",
            plotline_title: "",
            plotline_color: null,
            beat_id: "b1",
            title: "",
            number: 1,
            holder_kind: "plot:character_arc",
            character_id: null,
            character_name: null,
            character_initial: null,
          },
        ],
      }),
    ]);
    const recorded: Array<{ undo: () => Promise<void> }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c as { undo: () => Promise<void> }), () => proj);

    await recorder.deleteArc("gone", async () => {
      arcs.delete("gone");
    });
    // Undo restores the arc AND the card that fulfilled its change-beat.
    cards.set("card1", cardState("Fulfils a change-beat", {})); // simulate the backend having purged the link
    await recorded[0].undo();
    expect(arcs.get("gone")).toEqual(arcState("Gone"));
    expect(cards.get("card1")).toEqual(cardState("Fulfils a change-beat", { beat_links: [{ plotline: "gone", beat_id: "b1" }] }));
  });

  it("deleteCard captures the projection's referrers before deleting", async () => {
    const { port, cards } = fakePort();
    cards.set("gone", cardState("Gone"));
    cards.set("refA", cardState("A", { causal_links: [{ target: "gone" }] }));
    const proj = projection([card("gone"), card("refA", { causal_links: ["gone"] })]);
    const recorded: Array<{ undo: () => Promise<void> }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c as { undo: () => Promise<void> }), () => proj);

    await recorder.deleteCard("gone", async () => {
      cards.delete("gone");
    });
    // Undo the recorded delete: node back, then the captured referrer restored.
    cards.set("refA", cardState("A", {})); // simulate the backend having purged the ref
    await recorded[0].undo();
    expect(cards.get("gone")).toEqual(cardState("Gone"));
    expect(cards.get("refA")).toEqual(cardState("A", { causal_links: [{ target: "gone" }] }));
  });

  it("seed captures the ids the op reports as created, and undo deletes just them", async () => {
    const { port, cards } = fakePort();
    cards.set("existing", cardState("Existing"));
    const recorded: Array<{ undo: () => Promise<void> }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c as { undo: () => Promise<void> }), () => null);

    await recorder.seed(async () => {
      cards.set("seed1", cardState("Seed 1", { scene: "sc1" }));
      return ["seed1"]; // the store reports the created id
    });
    expect(recorded).toHaveLength(1);
    await recorded[0].undo();
    expect(cards.has("seed1")).toBe(false);
    expect(cards.has("existing")).toBe(true); // the pre-existing card is untouched
  });

  it("seed records nothing when the op reports no created cards (idempotent re-seed)", async () => {
    const { port } = fakePort();
    const recorded: unknown[] = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => null);
    await recorder.seed(async () => []);
    expect(recorded).toEqual([]);
  });

  it("realize mints the scene and records a command; its undo deletes that scene", async () => {
    const { port, scenes, calls } = fakePort();
    const recorded: Array<{ undo: () => Promise<void> }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c as { undo: () => Promise<void> }), () => null);

    await recorder.realize("c1", null);
    expect(calls).toEqual(["realize:c1->scene_1"]);
    expect(scenes.has("scene_1")).toBe(true);
    await recorded[0].undo(); // the just-minted empty scene deletes silently
    expect(scenes.has("scene_1")).toBe(false);
  });

  it("realize records nothing when the op mints no scene (e.g. a 409 already-attached)", async () => {
    const { port } = fakePort();
    const recorded: unknown[] = [];
    // A port whose realizeCard yields no scene id (the 409 / error case).
    const noScenePort = { ...port, realizeCard: async () => "" };
    const recorder = new PlotUndoRecorder(noScenePort, (c) => recorded.push(c), () => null);
    await recorder.realize("c1", null);
    expect(recorded).toEqual([]);
  });

  it("awaits whenIdle before running an op — queues behind an in-flight undo (#909)", async () => {
    const { port, cards } = fakePort();
    cards.set("c1", cardState("Card", { plotline: "P1" }));
    const gate: { release?: () => void } = {};
    const whenIdle = () => new Promise<void>((resolve) => (gate.release = resolve));
    const recorder = new PlotUndoRecorder(port, () => {}, () => null, whenIdle);

    let opRan = false;
    const done = recorder.cardEdit("c1", "reassign", async () => {
      opRan = true;
    });
    await Promise.resolve();
    expect(opRan).toBe(false); // parked on whenIdle — not racing the in-flight undo

    gate.release!();
    await done;
    expect(opRan).toBe(true); // ran once idle
  });
});
