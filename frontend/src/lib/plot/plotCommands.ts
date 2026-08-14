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

import type { Command } from "@/lib/stores/undoCaretaker.svelte";
import type { PlotBoardProjection } from "@/lib/types";
import {
  type CardState,
  deleteCard,
  getCardState,
  recreateCard,
  restoreCardState,
} from "@/lib/stores/plotBoard";
import {
  type PlotlineState,
  deletePlotline,
  getPlotlineState,
  recreatePlotline,
  restorePlotlineState,
} from "@/lib/stores/plotlines";

// The backend inverses the commands replay through. Every method is async (a server
// round-trip); the builders never touch a store directly, so a test drives them with
// a fake port and asserts the calls.
export interface PlotCommandPort {
  deleteCard(id: string): Promise<void>;
  getCardState(id: string): Promise<CardState>;
  restoreCardState(id: string, state: CardState): Promise<void>;
  recreateCard(id: string, state: CardState): Promise<void>;
  deletePlotline(id: string): Promise<void>;
  getPlotlineState(id: string): Promise<PlotlineState>;
  restorePlotlineState(id: string, state: PlotlineState): Promise<void>;
  recreatePlotline(id: string, state: PlotlineState): Promise<void>;
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
    // Node back under its id FIRST, then referrers — restoring a ref before its
    // target exists would let the save's dangling-heal drop it again.
    undo: async () => {
      await port.recreateCard(id, state);
      for (const r of referrers) await port.restoreCardState(r.id, r.state);
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
      await port.recreatePlotline(id, state);
      for (const r of referrers) await port.restoreCardState(r.id, r.state);
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

// Seed mints one card per un-carded scene — undo deletes them all, redo recreates
// them under their ids. One command (the caretaker treats it as one step), not a
// per-card transaction: the whole batch reverses or replays together.
export function seedCommand(port: PlotCommandPort, created: CardRef[], label = "seed cards"): Command {
  return {
    label,
    undo: async () => {
      for (const c of created) await port.deleteCard(c.id);
    },
    redo: async () => {
      for (const c of created) await port.recreateCard(c.id, c.state);
    },
  };
}

// ── Recorder ─────────────────────────────────────────────────────────────────
// Wraps the capture → run-forward-op → record pattern for the PlotEditor handlers,
// so the component stays thin and the orchestration is unit-testable with a fake
// port + record sink. A field edit that changed nothing records nothing (the
// "a drag that went nowhere records no command" rule).

// Whole-state equality (a no-op edit records nothing). One helper for both node
// kinds — a CardState / PlotlineState is a JSON-serializable {title, body, metadata}.
function statesEqual(a: CardState | PlotlineState, b: CardState | PlotlineState): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export class PlotUndoRecorder {
  readonly #port: PlotCommandPort;
  readonly #record: (command: Command) => void;
  readonly #getProjection: () => PlotBoardProjection | null;

  constructor(
    port: PlotCommandPort,
    record: (command: Command) => void,
    getProjection: () => PlotBoardProjection | null,
  ) {
    this.#port = port;
    this.#record = record;
    this.#getProjection = getProjection;
  }

  async #captureCards(ids: string[]): Promise<CardRef[]> {
    return Promise.all(ids.map(async (id) => ({ id, state: await this.#port.getCardState(id) })));
  }

  /** A card metadata/synopsis/title edit (reassign, page-status, beat link/unlink,
   *  causal link/unlink, rename, detach): capture the whole card before + after the
   *  forward op; record only a real change. Returns the op's own result. */
  async cardEdit<T>(id: string, label: string, op: () => Promise<T>): Promise<T> {
    const before = await this.#port.getCardState(id);
    const result = await op();
    const after = await this.#port.getCardState(id);
    if (!statesEqual(before, after)) {
      this.#record(cardEditCommand(this.#port, id, before, after, label));
    }
    return result;
  }

  /** A plotline rename / recolour / beat-roster edit. Returns the op's own result
   *  (the saved entry the node resyncs its revision from). */
  async plotlineEdit<T>(id: string, label: string, op: () => Promise<T>): Promise<T> {
    const before = await this.#port.getPlotlineState(id);
    const result = await op();
    const after = await this.#port.getPlotlineState(id);
    if (!statesEqual(before, after)) {
      this.#record(plotlineEditCommand(this.#port, id, before, after, label));
    }
    return result;
  }

  /** Create a card via the given forward op (returns the new id); record it. */
  async createCard(create: () => Promise<string>, label?: string): Promise<string> {
    const id = await create();
    const state = await this.#port.getCardState(id);
    this.#record(createCardCommand(this.#port, id, state, label));
    return id;
  }

  /** Create a plotline (ad-hoc or instantiated from a template) via the forward op;
   *  record it. Undo/redo restore the whole plotline (beats + lineage), so the
   *  template behind it is irrelevant to the reversal. */
  async createPlotline(create: () => Promise<string>, label?: string): Promise<string> {
    const id = await create();
    const state = await this.#port.getPlotlineState(id);
    this.#record(createPlotlineCommand(this.#port, id, state, label));
    return id;
  }

  /** Delete a card. Called AFTER the user confirmed — captures the card + its
   *  inbound referrers, runs the delete, records. */
  async deleteCard(id: string, del: () => Promise<void>): Promise<void> {
    const state = await this.#port.getCardState(id);
    const projection = this.#getProjection();
    const referrers = projection ? await this.#captureCards(cardsReferencingCard(projection, id)) : [];
    await del();
    this.#record(deleteCardCommand(this.#port, id, state, referrers));
  }

  async deletePlotline(id: string, del: () => Promise<void>): Promise<void> {
    const state = await this.#port.getPlotlineState(id);
    const projection = this.#getProjection();
    const referrers = projection ? await this.#captureCards(cardsReferencingPlotline(projection, id)) : [];
    await del();
    this.#record(deletePlotlineCommand(this.#port, id, state, referrers));
  }

  /** Seed cards from the manuscript. The forward op returns the ids it CREATED (the
   *  store diffs the seed endpoint's result against the board's current cards), so this
   *  never depends on a lagging projection prop; capture their state + record one step.
   *  Nothing created (an idempotent re-run) records nothing. */
  async seed(seedOp: () => Promise<string[]>): Promise<void> {
    const created = await seedOp();
    if (created.length === 0) return;
    this.#record(seedCommand(this.#port, await this.#captureCards(created)));
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
  };
}
