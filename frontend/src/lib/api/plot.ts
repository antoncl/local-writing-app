import type {
  PlotTemplate,
  PlotTemplateList,
  PlotBoardProjection,
  PlotBoard,
  PlotBoardLayout,
  CardEntry,
  CardList,
  PlotlineEntry,
  PlotlineList,
  CharacterArcEntry,
  CharacterArcList,
} from "@/lib/types";
import { HttpError, request } from "./core";

/** Which text a card and its scene keep when both hold a different one (ADR-0097 §3). */
export type CardTextChoice = "scene" | "card";

/** The two texts a text-choice 409 reports (attach / detach with differing summary +
 *  synopsis), or null for any other error — the caller asks, then retries with `text`. */
export function textChoiceConflict(error: unknown): { sceneSummary: string; cardSynopsis: string } | null {
  if (!(error instanceof HttpError) || error.status !== 409) return null;
  const detail = error.detail as { code?: unknown; scene_summary?: unknown; card_synopsis?: unknown } | null;
  if (!detail || typeof detail !== "object" || detail.code !== "text_choice_required") return null;
  return { sceneSummary: String(detail.scene_summary ?? ""), cardSynopsis: String(detail.card_synopsis ?? "") };
}

/** Where a story-time move puts a card: right after, or right before, another card
 *  (ADR-0097 §4). The backend accepts only the open layer's own cards as the anchor. */
export type StoryAnchor = { after_id: string } | { before_id: string };

export const plotApi = {
  // Plot templates (ADR-0048 S4c) — the ADR-0049 Library's second tenant. Same
  // browse/read/clone shape as prompts: list the resolved shelf, read one (with
  // its fail-closed `editable` verdict), clone an inherited one into an owned
  // editable copy, save/delete owned clones (inherited → 409 backend-side).
  listPlotTemplates() {
    return request<PlotTemplateList>("/plot/templates");
  },
  // Blank-create an owned template (#918) — the non-fork path. The backend defaults
  // a blank title, so callers may omit it and let the writer rename in the editor.
  createPlotTemplate(title = "") {
    return request<PlotTemplate>("/plot/templates", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
  },
  getPlotTemplate(entryId: string) {
    return request<PlotTemplate>(`/plot/templates/${entryId}`);
  },
  forkPlotTemplate(entryId: string) {
    return request<PlotTemplate>(`/plot/templates/${entryId}/fork`, { method: "POST" });
  },
  savePlotTemplate(entry: PlotTemplate, body: string) {
    return request<PlotTemplate>(`/plot/templates/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        template: entry.template,
        metadata: entry.metadata,
        base_revision: entry.revision,
      }),
    });
  },
  deletePlotTemplate(entryId: string) {
    return request<PlotTemplateList>(`/plot/templates/${entryId}`, { method: "DELETE" });
  },
  // The board's read model (ADR-0048 S7a): plotlines + cards (with their refs) +
  // the opaque layout, in one GET. Get-or-creates the `plot:board` singleton.
  getPlotBoardProjection() {
    return request<PlotBoardProjection>("/plot/board/projection");
  },
  // Persist the board layout (ADR-0048 S7c). PUT round-trips the opaque layout
  // dict with an optimistic base_revision; returns the board with its advanced
  // revision (the next save's base).
  savePlotBoard(payload: { base_revision: string; layout: PlotBoardLayout }) {
    return request<PlotBoard>("/plot/board", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  // Plot cards + plotlines (ADR-0048 S5a/S5b) — the board's content ops, wired in
  // S7d. Cards and plotlines share the `plot/` folder + a book-local layered CRUD;
  // the endpoint path is the only family discriminator (the backend enforces an
  // is_a family guard on each). Attach/detach/text have their own endpoints (ADR-0097
  // §3/§4): a card's `scene` is owned by them, saveCard ignores a client-sent one.
  // The flat card list — the context picker's plot-card roster (ADR-0074 slice 6),
  // over which a plotline's selector expands to its current cards. The board still
  // reads its card set via the projection; this is the light list a picker needs.
  listCards() {
    return request<CardList>("/plot/cards");
  },
  // Create a single unattached card — the board's direct-authoring entry point
  // (#793), the per-card inverse of seed. Returns the created card so the caller can
  // open it to name it. No scene → it projects homeless until attached / realized.
  // `id` is supplied only by undo-of-delete / redo-of-create (ADR-0053 §7), to
  // restore a card under its original identity so other cards' causal_links
  // reconnect; a collision 409s. Omitted for a normal create (backend mints).
  // `storyRank` rides along with `id` only (the backend ignores it otherwise), so an
  // undo-restored card returns to its place in story time (ADR-0097 §5).
  createCard(title: string, id?: string, storyRank?: number | null) {
    return request<CardEntry>("/plot/cards", {
      method: "POST",
      body: JSON.stringify(id ? { title, id, story_rank: storyRank ?? null } : { title }),
    });
  },
  getCard(entryId: string) {
    return request<CardEntry>(`/plot/cards/${entryId}`);
  },
  saveCard(entry: CardEntry, body: string) {
    return request<CardEntry>(`/plot/cards/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        metadata: entry.metadata,
        base_revision: entry.revision,
      }),
    });
  },
  // Bind a card to an existing scene (ADR-0097 §3/§4). 409 `text_choice_required` when
  // the scene's summary and the card's synopsis differ and `text` is omitted.
  attachCard(entryId: string, sceneId: string, text?: CardTextChoice) {
    return request<CardEntry>(`/plot/cards/${entryId}/attach`, {
      method: "POST",
      body: JSON.stringify(text ? { scene_id: sceneId, text } : { scene_id: sceneId }),
    });
  },
  // Unbind a card from its scene; `text` ("card" | "scene") picks the surviving synopsis
  // when both differ (409 `text_choice_required` if omitted).
  detachCard(entryId: string, text?: CardTextChoice) {
    return request<CardEntry>(`/plot/cards/${entryId}/detach`, {
      method: "POST",
      body: JSON.stringify(text ? { text } : {}),
    });
  },
  // Edit the DISPLAYED title/synopsis: the scene's while the card is written, the
  // card's own otherwise (ADR-0097 §3).
  setCardText(entryId: string, text: { title?: string; synopsis?: string }) {
    return request<CardEntry>(`/plot/cards/${entryId}/text`, {
      method: "PUT",
      body: JSON.stringify(text),
    });
  },
  // Move a card in story time (ADR-0097 §4, story only): right after / before a neighbour.
  placeCard(entryId: string, anchor: StoryAnchor) {
    return request<CardEntry>(`/plot/cards/${entryId}/place`, {
      method: "POST",
      body: JSON.stringify({ story: anchor }),
    });
  },
  deleteCard(entryId: string) {
    return request<CardList>(`/plot/cards/${entryId}`, { method: "DELETE" });
  },
  // Mint a scene from the card and attach it (ADR §1 *realize*). `parentId` places
  // the scene (null → the backend's first-container fallback). 409 if the card is
  // already attached (0..1 scene per card).
  realizeCard(entryId: string, parentId: string | null = null) {
    return request<CardEntry>(`/plot/cards/${entryId}/realize`, {
      method: "POST",
      body: JSON.stringify({ parent_id: parentId }),
    });
  },
  // Bulk inverse of realize (ADR §S5): one attached card per un-carded leaf scene,
  // in manuscript order. Idempotent — skips already-carded scenes.
  seedFromManuscript() {
    return request<CardList>("/plot/seed-from-manuscript", { method: "POST" });
  },
  // The plotline roster — the ReferencePicker's `plot` source (#742) and the
  // board's lanes both draw from this.
  listPlotlines() {
    return request<PlotlineList>("/plot/plotlines");
  },
  // Create an ad-hoc plotline (no template behind it) — the "New plotline" entry
  // point. Title only (colour + beats are authored afterward via savePlotline / the
  // board node); mirrors createCard. Returns the new node so the caller can place +
  // name it.
  // `id` is supplied only by undo/redo (ADR-0053 §7) to restore a plotline under
  // its original id so cards' beat_links + primary reconnect; a collision 409s.
  createPlotline(title: string, id?: string) {
    return request<PlotlineEntry>("/plot/plotlines", {
      method: "POST",
      body: JSON.stringify(id ? { title, id } : { title }),
    });
  },
  // Single plotline read/save/delete — the plotline document opener (#735): a
  // plotline backlink (a card's `plotline` ref) opens the thread in the editor to
  // rename / recolour / describe it. Book-local, so always editable (no Library
  // lock). Mirrors the card twins; delete returns the refreshed roster.
  getPlotline(entryId: string) {
    return request<PlotlineEntry>(`/plot/plotlines/${entryId}`);
  },
  savePlotline(entry: PlotlineEntry, body: string) {
    return request<PlotlineEntry>(`/plot/plotlines/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        metadata: entry.metadata,
        base_revision: entry.revision,
      }),
    });
  },
  deletePlotline(entryId: string) {
    return request<PlotlineList>(`/plot/plotlines/${entryId}`, { method: "DELETE" });
  },
  // Character arcs (ADR-0080) — the plotline's sibling holder, same book-local flat
  // CRUD, distinct sub-resource (`/plot/character-arcs`, not `/plotlines`) per the
  // backend's family discriminator.
  listCharacterArcs() {
    return request<CharacterArcList>("/plot/character-arcs");
  },
  createCharacterArc(title: string, id?: string) {
    return request<CharacterArcEntry>("/plot/character-arcs", {
      method: "POST",
      body: JSON.stringify(id ? { title, id } : { title }),
    });
  },
  getCharacterArc(entryId: string) {
    return request<CharacterArcEntry>(`/plot/character-arcs/${entryId}`);
  },
  saveCharacterArc(entry: CharacterArcEntry, body: string) {
    return request<CharacterArcEntry>(`/plot/character-arcs/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body,
        metadata: entry.metadata,
        base_revision: entry.revision,
      }),
    });
  },
  deleteCharacterArc(entryId: string) {
    return request<CharacterArcList>(`/plot/character-arcs/${entryId}`, { method: "DELETE" });
  },
  // Snapshot a Library template's beats into a new owned plot:thread holder (ADR-0048
  // §3; ADR-0053 §1/§2; ADR-0080 §5 — a character-arc-family template yields a
  // plot:character_arc, any other family a plot:plotline). Lives among the template
  // routes backend-side; returns the created entry so the caller can place + edit it
  // on the board (the S3 palette's instantiate gesture) and — for the union — branch
  // on `entry_type` to route it to the right band. An ad-hoc plotline is a plain
  // createPlotline (no template behind it); there is no ad-hoc arc equivalent yet.
  instantiatePlotTemplate(templateId: string) {
    return request<PlotlineEntry | CharacterArcEntry>(`/plot/templates/${templateId}/instantiate`, { method: "POST" });
  },
};
