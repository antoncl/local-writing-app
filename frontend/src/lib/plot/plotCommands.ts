// Plot-board content commands (ADR-0053 §7, #902) — the command vocabulary that
// makes every board content op undoable, the plotline/card twin of the graph
// canvas's `graphCommands.ts`. A plotline is a board node now, so its create /
// delete / edit and a card's create / delete / field-edits are all gestures on the
// ONE board caretaker (GraphUndoController.record) — no second undo surface.
//
// Unlike the graph commands (in-memory array swaps over a GraphPort), these reverse
// through the BACKEND: undo/redo await the server inverse, which is why the caretaker
// gained async support. Two shapes carry the whole feature:
//
//   • create / delete — the node returns under its ORIGINAL id (create-with-supplied
//     -id), so refs in other cards reconnect instead of dangling (ADR-0050 §6). A
//     delete also captures every card that referenced the doomed node and restores
//     them on undo — "restore it with its beats and every card badge that pointed at
//     it" (§7). Redo re-deletes; the backend re-purges those refs.
//   • field/beat edit — a whole-state before/after flip (`restore(before)` /
//     `restore(after)`). Whole-state, not per-field, because one op can touch several
//     fields (dropping a beat also adopts a primary, #863); the flip reverses all of it.
//
// The pure builders below take a `PlotCommandPort` (store ops behind an interface, so
// they unit-test with a fake); `PlotUndoRecorder` wraps capture-op-record for the
// PlotEditor handlers; `defaultPlotCommandPort` wires the real store ops.

import { type Command, UndoCancelled } from "@/lib/stores/undoCaretaker.svelte";
import type { PlotBoardProjection } from "@/lib/types";
import {
  type CardState,
  deleteCard,
  detachCardScene,
  deleteScene,
  getCardState,
  readScene,
  realizeCard,
  recreateCard,
  refreshAfterMutation,
  restoreCardState,
  sceneReferents,
} from "@/lib/stores/plotBoard";
import {
  type PlotlineState,
  deletePlotline,
  getPlotlineState,
  recreatePlotline,
  refreshRoster,
  restorePlotlineState,
} from "@/lib/stores/plotlines";
import {
  type ArcState,
  deleteArc,
  getArcState,
  recreateArc,
  refreshArcRoster,
  restoreArcState,
} from "@/lib/stores/characterArcs";
import { confirmService } from "@/lib/stores/confirmService.svelte";

// The backend inverses the commands replay through. Every method is async (a server
// round-trip); the builders never touch a store directly, so a test drives them with
// a fake port and asserts the calls.
export interface PlotCommandPort {
  // `refresh` (default true) is passed false inside a batched delete/seed undo, so
  // N restores skip their per-item board refetch and the command does ONE at the
  // end (refreshBoard / refreshRoster) — the refetch-storm fix (#909).
  deleteCard(id: string, refresh?: boolean): Promise<void>;
  getCardState(id: string): Promise<CardState>;
  restoreCardState(id: string, state: CardState, refresh?: boolean): Promise<void>;
  recreateCard(id: string, state: CardState, refresh?: boolean): Promise<void>;
  deletePlotline(id: string): Promise<void>;
  getPlotlineState(id: string): Promise<PlotlineState>;
  restorePlotlineState(id: string, state: PlotlineState, refresh?: boolean): Promise<void>;
  recreatePlotline(id: string, state: PlotlineState, refresh?: boolean): Promise<void>;
  // The character-arc twins (ADR-0080 §5) — a SEPARATE holder kind, never routed
  // through the plotline methods above (which would recreate an arc AS a plotline).
  deleteArc(id: string): Promise<void>;
  getArcState(id: string): Promise<ArcState>;
  restoreArcState(id: string, state: ArcState, refresh?: boolean): Promise<void>;
  recreateArc(id: string, state: ArcState, refresh?: boolean): Promise<void>;
  refreshBoard(): Promise<void>;
  refreshRoster(): Promise<void>;
  refreshArcRoster(): Promise<void>;
  // Realize (S6b): mint a scene → returns its id; the undo/redo scene ops.
  realizeCard(cardId: string, parentId: string | null): Promise<string>;
  sceneReferents(sceneId: string): string[];
  readScene(sceneId: string): Promise<{ title: string; body: string }>;
  deleteScene(sceneId: string): Promise<void>;
  detachCardScene(cardId: string): Promise<void>;
  // Suppressible confirm before deleting a written scene; resolves false on cancel.
  confirmSceneDelete(scene: { title: string; body: string }): Promise<boolean>;
}

// A captured card (id + whole state) — a deleted node, or a referrer restored
// alongside it.
export type CardRef = { id: string; state: CardState };

// ── Pure referrer finders ────────────────────────────────────────────────────
// Which cards a delete's ref-purge will touch, read off the current projection at
// capture time. Deleting a CARD purges other cards' inbound causal_links to it;
// deleting a PLOTLINE blanks cards' primary `plotline` and drops their beat_links to
// it. Capturing these lets undo restore what the delete cascaded away.

export function cardsReferencingCard(projection: PlotBoardProjection, cardId: string): string[] {
  return projection.cards.filter((c) => c.causal_links.includes(cardId)).map((c) => c.id);
}

export function cardsReferencingPlotline(projection: PlotBoardProjection, plotlineId: string): string[] {
  return projection.cards
    .filter((c) => c.plotline === plotlineId || c.beats.some((b) => b.plotline_id === plotlineId))
    .map((c) => c.id);
}

// ── Pure command builders ────────────────────────────────────────────────────

export function createCardCommand(port: PlotCommandPort, id: string, state: CardState, label = "add card"): Command {
  return {
    label,
    undo: () => port.deleteCard(id),
    redo: () => port.recreateCard(id, state),
  };
}

export function deleteCardCommand(
  port: PlotCommandPort,
  id: string,
  state: CardState,
  referrers: CardRef[],
  label = "delete card",
): Command {
  return {
    label,
    // Node back under its id FIRST (awaited — a ref restored before its target
    // exists would be dangling-healed away), THEN the referrers in parallel with
    // their board refetch suppressed, and ONE refresh at the end (#909).
    undo: async () => {
      await port.recreateCard(id, state, false);
      await Promise.all(referrers.map((r) => port.restoreCardState(r.id, r.state, false)));
      await port.refreshBoard();
    },
    redo: () => port.deleteCard(id),
  };
}

export function cardEditCommand(
  port: PlotCommandPort,
  id: string,
  before: CardState,
  after: CardState,
  label: string,
): Command {
  return {
    label,
    undo: () => port.restoreCardState(id, before),
    redo: () => port.restoreCardState(id, after),
  };
}

// An edit that touches SEVERAL cards as ONE undo step (a beat MOVE card→card, #941:
// unlink off the source + link on the target). Restores every card's before/after,
// suppressing the per-restore board refetch on all but the last so the step rebuilds
// the board ONCE (the #909 storm fix, as deleteCardCommand does for its referrers).
export function cardEditManyCommand(
  port: PlotCommandPort,
  before: CardRef[],
  after: CardRef[],
  label: string,
): Command {
  const restoreAll = async (refs: CardRef[]): Promise<void> => {
    for (let i = 0; i < refs.length; i++) {
      await port.restoreCardState(refs[i].id, refs[i].state, i === refs.length - 1);
    }
  };
  return {
    label,
    undo: () => restoreAll(before),
    redo: () => restoreAll(after),
  };
}

export function createPlotlineCommand(
  port: PlotCommandPort,
  id: string,
  state: PlotlineState,
  label = "add plotline",
): Command {
  return {
    label,
    undo: () => port.deletePlotline(id),
    redo: () => port.recreatePlotline(id, state),
  };
}

export function deletePlotlineCommand(
  port: PlotCommandPort,
  id: string,
  state: PlotlineState,
  referrers: CardRef[],
  label = "delete plotline",
): Command {
  return {
    label,
    undo: async () => {
      await port.recreatePlotline(id, state, false);
      await Promise.all(referrers.map((r) => port.restoreCardState(r.id, r.state, false)));
      // One trailing refresh of BOTH the roster (the plotline is back) and the board.
      await Promise.all([port.refreshRoster(), port.refreshBoard()]);
    },
    redo: () => port.deletePlotline(id),
  };
}

export function plotlineEditCommand(
  port: PlotCommandPort,
  id: string,
  before: PlotlineState,
  after: PlotlineState,
  label: string,
): Command {
  return {
    label,
    undo: () => port.restorePlotlineState(id, before),
    redo: () => port.restorePlotlineState(id, after),
  };
}

// The character-arc twins of the three plotline command builders above (ADR-0080 §5).
// `cardsReferencingPlotline` is reused unchanged for an arc's referrers — it matches on
// a card's `plotline` field / `beats[].plotline_id`, which hold the HOLDER's id
// regardless of subtype (an arc is never a card's primary, so only the beats clause
// ever matches, but the id-matching predicate itself is subtype-agnostic).

export function createArcCommand(port: PlotCommandPort, id: string, state: ArcState, label = "add character arc"): Command {
  return {
    label,
    undo: () => port.deleteArc(id),
    redo: () => port.recreateArc(id, state),
  };
}

export function deleteArcCommand(
  port: PlotCommandPort,
  id: string,
  state: ArcState,
  referrers: CardRef[],
  label = "delete character arc",
): Command {
  return {
    label,
    undo: async () => {
      await port.recreateArc(id, state, false);
      await Promise.all(referrers.map((r) => port.restoreCardState(r.id, r.state, false)));
      await Promise.all([port.refreshArcRoster(), port.refreshBoard()]);
    },
    redo: () => port.deleteArc(id),
  };
}

export function arcEditCommand(
  port: PlotCommandPort,
  id: string,
  before: ArcState,
  after: ArcState,
  label: string,
): Command {
  return {
    label,
    undo: () => port.restoreArcState(id, before),
    redo: () => port.restoreArcState(id, after),
  };
}

// Seed mints one card per un-carded scene — undo deletes them all, redo recreates
// them under their ids. One command (the caretaker treats it as one step), not a
// per-card transaction: the whole batch reverses or replays together.
export function seedCommand(port: PlotCommandPort, created: CardRef[], label = "seed cards"): Command {
  return {
    label,
    // The whole batch in parallel with per-item refetch suppressed, one refresh at
    // the end — a 40-card seed reverses in ~1 board refetch, not 40 (#909).
    undo: async () => {
      await Promise.all(created.map((c) => port.deleteCard(c.id, false)));
      await port.refreshBoard();
    },
    redo: async () => {
      await Promise.all(created.map((c) => port.recreateCard(c.id, c.state, false)));
      await port.refreshBoard();
    },
  };
}

// Realize minted a scene FILE and attached it (S6b) — the one op with a file side
// effect. Undo deletes that scene ONLY when the card is its sole referent (0..n cards
// per scene), behind a suppressible confirm when the scene holds prose; a shared scene
// is kept (this card detached). Redo re-mints — capturing the NEW scene id (mutable
// closure state) so the next undo targets it. The sole-referent check reads the LIVE
// board at undo time, since another card may have attached since the realize.
export function realizeCommand(
  port: PlotCommandPort,
  cardId: string,
  parentId: string | null,
  sceneId: string,
  label = "realize card",
): Command {
  let scene = sceneId;
  return {
    label,
    undo: async () => {
      const referents = port.sceneReferents(scene);
      if (!referents.includes(cardId)) return; // realize already reversed elsewhere — no-op
      if (referents.length > 1) {
        await port.detachCardScene(cardId); // shared scene — keep it, detach this card only
        return;
      }
      const read = await port.readScene(scene); // sole referent → the scene will be deleted
      if (read.body.trim().length > 0 && !(await port.confirmSceneDelete(read))) {
        // Declined a written scene's deletion: throw BEFORE mutating so the caretaker
        // leaves this single-command step undoable (UndoCancelled → "Undo cancelled").
        throw new UndoCancelled();
      }
      await port.deleteScene(scene); // deletes the scene + purges the card's ref (detaches)
    },
    redo: async () => {
      scene = await port.realizeCard(cardId, parentId); // re-mint; track the new scene id
    },
  };
}

// ── Recorder ─────────────────────────────────────────────────────────────────
// Wraps the capture → run-forward-op → record pattern for the PlotEditor handlers,
// so the component stays thin and the orchestration is unit-testable with a fake
// port + record sink. A field edit that changed nothing records nothing (the
// "a drag that went nowhere records no command" rule).

// Whole-state equality (a no-op edit records nothing). One helper for every node
// kind — a CardState / PlotlineState / ArcState is a JSON-serializable
// {title, body, metadata}.
function statesEqual(a: CardState | PlotlineState | ArcState, b: CardState | PlotlineState | ArcState): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export class PlotUndoRecorder {
  readonly #port: PlotCommandPort;
  readonly #record: (command: Command) => void;
  readonly #getProjection: () => PlotBoardProjection | null;
  // Resolves once no undo/redo is in flight (#909). Awaited at the START of every
  // op so a gesture fired during a still-running undo QUEUES behind it and records
  // cleanly, instead of hitting `record()` mid-replay (which throws). Defaults to a
  // resolved promise so a caller that doesn't wire it (tests, a layout-only surface)
  // is unaffected. Residual: an op already in flight when an undo STARTS isn't
  // gated — rare, same non-corrupting throw.
  readonly #whenIdle: () => Promise<void>;

  constructor(
    port: PlotCommandPort,
    record: (command: Command) => void,
    getProjection: () => PlotBoardProjection | null,
    whenIdle: () => Promise<void> = () => Promise.resolve(),
  ) {
    this.#port = port;
    this.#record = record;
    this.#getProjection = getProjection;
    this.#whenIdle = whenIdle;
  }

  async #captureCards(ids: string[]): Promise<CardRef[]> {
    return Promise.all(ids.map(async (id) => ({ id, state: await this.#port.getCardState(id) })));
  }

  /** A card metadata/synopsis/title edit (reassign, page-status, beat link/unlink,
   *  causal link/unlink, rename, detach): capture the whole card before + after the
   *  forward op; record only a real change. Returns the op's own result. */
  async cardEdit<T>(id: string, label: string, op: () => Promise<T>): Promise<T> {
    await this.#whenIdle();
    const before = await this.#port.getCardState(id);
    const result = await op();
    const after = await this.#port.getCardState(id);
    if (!statesEqual(before, after)) {
      this.#record(cardEditCommand(this.#port, id, before, after, label));
    }
    return result;
  }

  /** An edit spanning several cards recorded as ONE step (a beat MOVE card→card, #941).
   *  Captures every id's before + after around the op; records only if something
   *  changed. Ids should be distinct (the move passes [from, to]). */
  async cardEditMany(ids: string[], label: string, op: () => Promise<void>): Promise<void> {
    await this.#whenIdle();
    const before = await this.#captureCards(ids);
    await op();
    const after = await this.#captureCards(ids);
    if (before.some((b, i) => !statesEqual(b.state, after[i].state))) {
      this.#record(cardEditManyCommand(this.#port, before, after, label));
    }
  }

  /** A plotline rename / recolour / beat-roster edit. Returns the op's own result
   *  (the saved entry the node resyncs its revision from). */
  async plotlineEdit<T>(id: string, label: string, op: () => Promise<T>): Promise<T> {
    await this.#whenIdle();
    const before = await this.#port.getPlotlineState(id);
    const result = await op();
    const after = await this.#port.getPlotlineState(id);
    if (!statesEqual(before, after)) {
      this.#record(plotlineEditCommand(this.#port, id, before, after, label));
    }
    return result;
  }

  /** A character-arc rename / recolour / rebind-character / beat-roster edit
   *  (ADR-0080 §5). Returns the op's own result, mirroring `plotlineEdit`. */
  async arcEdit<T>(id: string, label: string, op: () => Promise<T>): Promise<T> {
    await this.#whenIdle();
    const before = await this.#port.getArcState(id);
    const result = await op();
    const after = await this.#port.getArcState(id);
    if (!statesEqual(before, after)) {
      this.#record(arcEditCommand(this.#port, id, before, after, label));
    }
    return result;
  }

  /** Create a card via the given forward op (returns the new id); record it. */
  async createCard(create: () => Promise<string>, label?: string): Promise<string> {
    await this.#whenIdle();
    const id = await create();
    const state = await this.#port.getCardState(id);
    this.#record(createCardCommand(this.#port, id, state, label));
    return id;
  }

  /** Create a plotline (ad-hoc or instantiated from a template) via the forward op;
   *  record it. Undo/redo restore the whole plotline (beats + lineage), so the
   *  template behind it is irrelevant to the reversal. */
  async createPlotline(create: () => Promise<string>, label?: string): Promise<string> {
    await this.#whenIdle();
    const id = await create();
    const state = await this.#port.getPlotlineState(id);
    this.#record(createPlotlineCommand(this.#port, id, state, label));
    return id;
  }

  /** Create a character arc via the given forward op (returns the new id, already
   *  minted — e.g. by the shared template-instantiate call, ADR-0080 §5); record it.
   *  Mirrors `createPlotline` but on the ARC port methods, so undo/redo never route
   *  through the plotline substrate (which would recreate it as a plotline). */
  async createArc(create: () => Promise<string>, label?: string): Promise<string> {
    await this.#whenIdle();
    const id = await create();
    const state = await this.#port.getArcState(id);
    this.#record(createArcCommand(this.#port, id, state, label));
    return id;
  }

  /** Delete a card. Called AFTER the user confirmed — captures the card + its
   *  inbound referrers, runs the delete, records. */
  async deleteCard(id: string, del: () => Promise<void>): Promise<void> {
    await this.#whenIdle();
    const state = await this.#port.getCardState(id);
    const projection = this.#getProjection();
    const referrers = projection ? await this.#captureCards(cardsReferencingCard(projection, id)) : [];
    await del();
    this.#record(deleteCardCommand(this.#port, id, state, referrers));
  }

  async deletePlotline(id: string, del: () => Promise<void>): Promise<void> {
    await this.#whenIdle();
    const state = await this.#port.getPlotlineState(id);
    const projection = this.#getProjection();
    const referrers = projection ? await this.#captureCards(cardsReferencingPlotline(projection, id)) : [];
    await del();
    this.#record(deletePlotlineCommand(this.#port, id, state, referrers));
  }

  /** Delete a character arc (ADR-0080 §5). Mirrors `deletePlotline`: captures the arc
   *  + every card that fulfils one of its change-beats (never its primary — an arc is
   *  never primary), runs the delete, records. */
  async deleteArc(id: string, del: () => Promise<void>): Promise<void> {
    await this.#whenIdle();
    const state = await this.#port.getArcState(id);
    const projection = this.#getProjection();
    const referrers = projection ? await this.#captureCards(cardsReferencingPlotline(projection, id)) : [];
    await del();
    this.#record(deleteArcCommand(this.#port, id, state, referrers));
  }

  /** Seed cards from the manuscript. The forward op returns the ids it CREATED (the
   *  store diffs the seed endpoint's result against the board's current cards), so this
   *  never depends on a lagging projection prop; capture their state + record one step.
   *  Nothing created (an idempotent re-run) records nothing. */
  async seed(seedOp: () => Promise<string[]>): Promise<void> {
    await this.#whenIdle();
    const created = await seedOp();
    if (created.length === 0) return;
    this.#record(seedCommand(this.#port, await this.#captureCards(created)));
  }

  /** Realize a card into a scene, recorded (S6b). Mints the scene via the port,
   *  records a command whose undo deletes it (sole referent, suppressible confirm).
   *  A realize that produced no scene (a 409 already-attached, or an error) records
   *  nothing. */
  async realize(cardId: string, parentId: string | null): Promise<void> {
    await this.#whenIdle();
    const sceneId = await this.#port.realizeCard(cardId, parentId);
    if (!sceneId) return;
    this.#record(realizeCommand(this.#port, cardId, parentId, sceneId));
  }
}

// The real port: the plotBoard / plotlines store ops behind the interface.
export function defaultPlotCommandPort(): PlotCommandPort {
  return {
    deleteCard,
    getCardState,
    restoreCardState,
    recreateCard,
    deletePlotline,
    getPlotlineState,
    restorePlotlineState,
    recreatePlotline,
    deleteArc,
    getArcState,
    restoreArcState,
    recreateArc,
    refreshBoard: refreshAfterMutation,
    refreshRoster,
    refreshArcRoster,
    realizeCard,
    sceneReferents,
    readScene,
    deleteScene,
    detachCardScene,
    // The suppressible confirm before deleting a written scene, as a Promise<boolean>:
    // confirm → true, cancel/backdrop → false (via the confirmService onCancel added
    // for this), and a suppressed prior "don't show again" resolves true immediately.
    confirmSceneDelete: (scene) =>
      new Promise<boolean>((resolve) => {
        confirmService.request({
          title: "Delete scene?",
          message: `Undoing realize will delete the scene “${scene.title || "Untitled"}” and its prose.`,
          confirmLabel: "Delete scene",
          destructive: true,
          cannotBeUndone: true,
          dontShowAgainKey: "plot-realize-undo-delete-scene",
          onConfirm: async () => resolve(true),
          onCancel: () => resolve(false),
        });
      }),
  };
}
