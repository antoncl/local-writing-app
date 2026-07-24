<script lang="ts">
  import { api } from "@/lib/api";
  import { setStructure } from "@/lib/stores/structure";
  import { isLeafNode } from "@/lib/utils/treeHelpers";
  import type {
    EditableDocument,
    PlotBoardCard,
    PlotBoardSpec,
    PlotNode,
    PlotNodeSummary,
    PlotPointClaim,
    PlotTemplateInstancePoint,
    StructureDocument,
    StructureNode,
  } from "@/lib/types";

  interface Props {
    scene?: EditableDocument | null;
    structure?: StructureDocument | null;
    onFocus?: () => void;
    onNavigate?: (payload: { id: string; kind: string }) => void;
    onPlotNodeSaved?: (node: PlotNode) => void | Promise<void>;
  }

  let {
    scene = null,
    structure = null,
    onFocus,
    onNavigate,
    onPlotNodeSaved,
  }: Props = $props();

  type BoardColumn = {
    id: string;
    title: string;
    cards: PlotBoardCard[];
  };

  type TemplatePointRow = {
    instance: PlotNode;
    point: PlotTemplateInstancePoint;
    status: "missing" | "partial" | "used";
    claim: PlotPointClaim | null;
  };

  type PlotDragPayload =
    | { kind: "plot-point"; template_instance_id: string; plot_point_id: string }
    | { kind: "plot-claim"; claim_id: string };

  const PLOT_DND_TYPE = "application/x-local-writing-plot";

  const EMPTY_BOARD = {
    version: 1,
    template_instance_ids: [],
    plotlines: [],
    cards: [],
    claims: [],
    relationships: [],
    metadata: {},
  };

  let selectedCardId = $state<string | null>(null);
  let selectedClaimId = $state<string | null>(null);
  let selectedPalettePoint = $state<string | null>(null);
  let templateFilterId = $state("");
  let templateToAddId = $state("");
  let templateInstances: PlotNode[] = $state([]);
  let availableTemplates: PlotNodeSummary[] = $state([]);
  let templateLoadError = $state("");
  let templateRequest = 0;
  let loadedPlotId = $state<string | null>(null);
  let loadedPlotRevision = $state<string | null>(null);
  let localPlotNode = $state<PlotNode | null>(null);
  let savingMessage = $state("");
  let saveError = $state("");
  let dragOverCardId = $state<string | null>(null);

  let plotNode = $derived(localPlotNode ?? asPlotNode(scene));
  let board = $derived(plotNode?.board ?? EMPTY_BOARD);
  let instanceIds = $derived.by(() => {
    const ids = new Set<string>();
    for (const id of board.template_instance_ids ?? []) ids.add(id);
    for (const line of board.plotlines ?? []) {
      if (line.template_instance_id) ids.add(line.template_instance_id);
    }
    for (const claim of board.claims ?? []) ids.add(claim.template_instance_id);
    return [...ids];
  });
  let cards = $derived(board.cards ?? []);
  let claims = $derived(board.claims ?? []);
  let claimsByCard = $derived.by(() => {
    const map = new Map<string, PlotPointClaim[]>();
    for (const claim of claims) {
      const list = map.get(claim.card_id) ?? [];
      list.push(claim);
      map.set(claim.card_id, list);
    }
    return map;
  });
  let instanceById = $derived.by(() => new Map(templateInstances.map((node) => [node.id, node])));
  let selectedCard = $derived(cards.find((card) => card.id === selectedCardId) ?? null);
  let selectedClaim = $derived(claims.find((claim) => claim.id === selectedClaimId) ?? null);
  let visibleTemplateInstances = $derived(
    templateFilterId ? templateInstances.filter((node) => node.id === templateFilterId) : templateInstances,
  );
  let paletteRows = $derived.by<TemplatePointRow[]>(() => {
    const rows: TemplatePointRow[] = [];
    for (const instance of visibleTemplateInstances) {
      for (const point of instance.template_instance?.plot_points ?? []) {
        const claim = claims.find(
          (candidate) =>
            candidate.template_instance_id === instance.id &&
            candidate.plot_point_id === point.plot_point_id,
        ) ?? null;
        rows.push({
          instance,
          point,
          claim,
          status: claim ? (claim.claim_type === "partially_satisfies" ? "partial" : "used") : "missing",
        });
      }
    }
    return rows;
  });
  let columns = $derived(buildColumns(structure, cards));
  let selectedPointLabel = $derived(selectedClaim ? pointLabel(selectedClaim) : "");
  let selectedPaletteRow = $derived(
    selectedPalettePoint
      ? paletteRows.find((row) => selectedPalettePoint === pointKey(row.instance.id, row.point.plot_point_id)) ?? null
      : null,
  );

  $effect(() => {
    const incoming = asPlotNode(scene);
    const id = incoming?.id ?? null;
    const revision = incoming?.revision ?? null;
    if (id === loadedPlotId && revision === loadedPlotRevision) return;
    loadedPlotId = id;
    loadedPlotRevision = revision;
    localPlotNode = incoming;
    selectedCardId = incoming?.board?.cards?.[0]?.id ?? null;
    selectedClaimId = null;
    selectedPalettePoint = null;
  });

  $effect(() => {
    const id = plotNode?.id ?? null;
    if (!id) {
      availableTemplates = [];
      return;
    }
    let cancelled = false;
    void api.listPlotNodes().then((list) => {
      if (cancelled) return;
      availableTemplates = list.entries.filter((entry) => entry.entry_type === "plot:template");
      if (!templateToAddId) templateToAddId = availableTemplates[0]?.id ?? "";
    }).catch(() => {
      if (!cancelled) availableTemplates = [];
    });
    return () => {
      cancelled = true;
    };
  });

  $effect(() => {
    const ids = instanceIds;
    const req = ++templateRequest;
    templateLoadError = "";
    if (ids.length === 0) {
      templateInstances = [];
      return;
    }
    void Promise.all(
      ids.map((id) =>
        api.getPlotNode(id).catch(() => null),
      ),
    ).then((nodes) => {
      if (req !== templateRequest) return;
      templateInstances = nodes.filter((node): node is PlotNode => Boolean(node));
      if (templateInstances.length !== ids.length) {
        templateLoadError = "Some template instances could not be loaded.";
      }
    });
  });

  function asPlotNode(document: EditableDocument | null | undefined): PlotNode | null {
    if (!document || !("board" in document)) return null;
    return document as PlotNode;
  }

  function flattenStructure(root: StructureNode | null | undefined, depth = 0, acc: { id: string; title: string; depth: number }[] = []) {
    if (!root) return acc;
    if (depth > 0 && !isLeafNode(root)) acc.push({ id: root.id, title: root.title, depth });
    for (const child of root.children ?? []) flattenStructure(child, depth + 1, acc);
    return acc;
  }

  function buildColumns(currentStructure: StructureDocument | null, currentCards: PlotBoardCard[]): BoardColumn[] {
    const cardsByColumn = new Map<string, PlotBoardCard[]>();
    for (const card of currentCards) {
      const id = card.structure_column_id || "__unplaced";
      const list = cardsByColumn.get(id) ?? [];
      list.push(card);
      cardsByColumn.set(id, list);
    }

    const out: BoardColumn[] = [];
    const structureColumns = flattenStructure(currentStructure?.root);
    for (const column of structureColumns) {
      out.push({
        id: column.id,
        title: column.title,
        cards: cardsByColumn.get(column.id) ?? [],
      });
      cardsByColumn.delete(column.id);
    }

    for (const [id, columnCards] of cardsByColumn.entries()) {
      out.push({
        id,
        title: id === "__unplaced" ? "Unplaced" : id,
        cards: columnCards,
      });
    }

    if (out.length === 0) {
      return [{ id: "__unplaced", title: "Unplaced", cards: [] }];
    }
    return out;
  }

  function claimTypeLabel(type: PlotPointClaim["claim_type"]): string {
    return type
      .replace(/_/g, " ")
      .replace(/^\w/, (letter) => letter.toUpperCase());
  }

  function pointLabel(claim: PlotPointClaim): string {
    if (claim.claim_label) return claim.claim_label;
    const instance = instanceById.get(claim.template_instance_id);
    const point = instance?.template_instance?.plot_points.find((candidate) => candidate.plot_point_id === claim.plot_point_id);
    return point?.title || claim.plot_point_id;
  }

  function pointKey(instanceId: string, pointId: string): string {
    return `${instanceId}:${pointId}`;
  }

  function selectCard(cardId: string): void {
    selectedCardId = cardId;
    selectedClaimId = null;
    selectedPalettePoint = null;
    onFocus?.();
  }

  function selectClaim(claim: PlotPointClaim): void {
    selectedCardId = claim.card_id;
    selectedClaimId = claim.id;
    selectedPalettePoint = pointKey(claim.template_instance_id, claim.plot_point_id);
    onFocus?.();
  }

  function selectPalettePoint(row: TemplatePointRow): void {
    selectedPalettePoint = pointKey(row.instance.id, row.point.plot_point_id);
    if (row.claim) {
      selectClaim(row.claim);
      return;
    }
    selectedCardId = null;
    selectedClaimId = null;
    onFocus?.();
  }

  function setPlotDragPayload(event: DragEvent, payload: PlotDragPayload): void {
    const transfer = event.dataTransfer;
    if (!transfer) return;
    const encoded = JSON.stringify(payload);
    transfer.setData(PLOT_DND_TYPE, encoded);
    transfer.setData("text/plain", encoded);
    transfer.effectAllowed = payload.kind === "plot-claim" ? "move" : "copy";
  }

  function readPlotDragPayload(event: DragEvent): PlotDragPayload | null {
    const transfer = event.dataTransfer;
    if (!transfer) return null;
    const raw = transfer.getData(PLOT_DND_TYPE) || transfer.getData("text/plain");
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as Partial<PlotDragPayload>;
      if (
        parsed.kind === "plot-point" &&
        typeof parsed.template_instance_id === "string" &&
        typeof parsed.plot_point_id === "string"
      ) {
        return {
          kind: "plot-point",
          template_instance_id: parsed.template_instance_id,
          plot_point_id: parsed.plot_point_id,
        };
      }
      if (parsed.kind === "plot-claim" && typeof parsed.claim_id === "string") {
        return { kind: "plot-claim", claim_id: parsed.claim_id };
      }
    } catch {
      return null;
    }
    return null;
  }

  function dragPalettePoint(row: TemplatePointRow, event: DragEvent): void {
    selectPalettePoint(row);
    setPlotDragPayload(event, {
      kind: "plot-point",
      template_instance_id: row.instance.id,
      plot_point_id: row.point.plot_point_id,
    });
  }

  function dragClaim(claim: PlotPointClaim, event: DragEvent): void {
    event.stopPropagation();
    selectClaim(claim);
    setPlotDragPayload(event, { kind: "plot-claim", claim_id: claim.id });
  }

  function allowCardDrop(cardId: string, event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    dragOverCardId = cardId;
  }

  function leaveCardDrop(cardId: string, event: DragEvent): void {
    const current = event.currentTarget as HTMLElement;
    const next = event.relatedTarget as Node | null;
    if (dragOverCardId === cardId && (!next || !current.contains(next))) {
      dragOverCardId = null;
    }
  }

  function openCardNode(card: PlotBoardCard, event: MouseEvent): void {
    event.stopPropagation();
    if (!card.node_ref) return;
    onNavigate?.({ id: card.node_ref, kind: "scene" });
  }

  function cloneBoardSpec(source: PlotBoardSpec): PlotBoardSpec {
    return JSON.parse(JSON.stringify(source)) as PlotBoardSpec;
  }

  function newLocalId(prefix: string): string {
    const raw = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
    return `${prefix}_${raw.replace(/-/g, "").slice(0, 12)}`;
  }

  async function persistBoard(nextBoard: PlotBoardSpec, message: string): Promise<PlotNode | null> {
    if (!plotNode) return null;
    savingMessage = message;
    saveError = "";
    try {
      const saved = await api.savePlotNode(plotNode.id, {
        title: plotNode.title,
        entry_type: plotNode.entry_type,
        body: plotNode.body ?? "",
        metadata: plotNode.metadata ?? {},
        template: plotNode.template ?? null,
        template_instance: plotNode.template_instance ?? null,
        board: nextBoard,
        layout: plotNode.layout ?? null,
        base_revision: plotNode.revision,
      });
      localPlotNode = saved;
      await onPlotNodeSaved?.(saved);
      return saved;
    } catch (caught) {
      saveError = caught instanceof Error ? caught.message : "Could not save plot board.";
      return null;
    } finally {
      savingMessage = "";
    }
  }

  async function addTemplateInstance(): Promise<void> {
    if (!templateToAddId) return;
    savingMessage = "Adding template instance";
    saveError = "";
    try {
      const template = await api.getPlotNode(templateToAddId);
      const instance = await api.createPlotNode({
        title: `${template.title} plot`,
        entry_type: "plot:template_instance",
        body: template.body ?? "",
        metadata: {},
        template_instance: {
          template_id: template.id,
          plot_points: (template.template?.plot_points ?? []).map((point) => ({
            plot_point_id: point.id,
            title: point.title,
            function_claim: point.function_claim,
            notes: "",
            metadata: { ...(point.metadata ?? {}) },
          })),
          metadata: {},
        },
      });
      const nextBoard = cloneBoardSpec(board);
      if (!nextBoard.template_instance_ids.includes(instance.id)) {
        nextBoard.template_instance_ids = [...nextBoard.template_instance_ids, instance.id];
      }
      nextBoard.plotlines = [
        ...nextBoard.plotlines,
        {
          id: newLocalId("plotline"),
          title: instance.title,
          template_instance_id: instance.id,
          color: null,
          metadata: {},
        },
      ];
      await persistBoard(nextBoard, "Adding template instance");
    } catch (caught) {
      saveError = caught instanceof Error ? caught.message : "Could not add template instance.";
    } finally {
      savingMessage = "";
    }
  }

  function plotlineIdForInstance(templateInstanceId: string): string | null {
    return board.plotlines.find((line) => line.template_instance_id === templateInstanceId)?.id ?? null;
  }

  async function attachPointToCard(cardId: string, templateInstanceId: string, plotPointId: string): Promise<void> {
    if (savingMessage) return;
    const nextClaim: PlotPointClaim = {
      id: newLocalId("claim"),
      card_id: cardId,
      template_instance_id: templateInstanceId,
      plot_point_id: plotPointId,
      plotline_id: plotlineIdForInstance(templateInstanceId),
      claim_type: "satisfies",
      claim_label: null,
      strength: null,
      confidence: null,
      evidence: null,
      rationale: null,
      ai_notes: null,
      metadata: {},
    };
    const nextBoard = cloneBoardSpec(board);
    nextBoard.claims = [...(nextBoard.claims ?? []), nextClaim];
    const saved = await persistBoard(nextBoard, "Attaching function point");
    if (saved) {
      selectedCardId = cardId;
      selectedClaimId = nextClaim.id;
      selectedPalettePoint = pointKey(templateInstanceId, plotPointId);
    }
  }

  async function moveClaimToCard(claimId: string, cardId: string): Promise<void> {
    if (savingMessage) return;
    const claim = claims.find((candidate) => candidate.id === claimId);
    if (!claim) return;
    if (claim.card_id === cardId) {
      selectClaim(claim);
      return;
    }
    const nextBoard = cloneBoardSpec(board);
    nextBoard.claims = (nextBoard.claims ?? []).map((candidate) =>
      candidate.id === claimId ? { ...candidate, card_id: cardId } : candidate,
    );
    const saved = await persistBoard(nextBoard, "Moving claim");
    if (saved) {
      selectedCardId = cardId;
      selectedClaimId = claimId;
      selectedPalettePoint = pointKey(claim.template_instance_id, claim.plot_point_id);
    }
  }

  async function removeClaim(claim: PlotPointClaim, event: MouseEvent): Promise<void> {
    event.stopPropagation();
    if (savingMessage) return;
    const nextBoard = cloneBoardSpec(board);
    nextBoard.claims = (nextBoard.claims ?? []).filter((candidate) => candidate.id !== claim.id);
    const saved = await persistBoard(nextBoard, "Removing claim");
    if (saved) {
      selectedClaimId = null;
      selectedPalettePoint = pointKey(claim.template_instance_id, claim.plot_point_id);
    }
  }

  async function dropOnCard(cardId: string, event: DragEvent): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    dragOverCardId = null;
    const payload = readPlotDragPayload(event);
    if (!payload) return;
    if (payload.kind === "plot-claim") {
      await moveClaimToCard(payload.claim_id, cardId);
      return;
    }
    await attachPointToCard(cardId, payload.template_instance_id, payload.plot_point_id);
  }

  async function addPlaceholderCard(columnId: string | null): Promise<void> {
    const title = window.prompt("Card title", "New plot card")?.trim();
    if (!title) return;
    const card: PlotBoardCard = {
      id: newLocalId("card"),
      title,
      synopsis: "",
      structure_column_id: columnId === "__unplaced" ? null : columnId,
      node_ref: null,
      primary_plotline_id: null,
      metadata: {},
    };
    const nextBoard = cloneBoardSpec(board);
    nextBoard.cards = [...nextBoard.cards, card];
    const saved = await persistBoard(nextBoard, "Adding card");
    if (saved) {
      selectedCardId = card.id;
      selectedClaimId = null;
      selectedPalettePoint = null;
    }
  }

  async function addChapter(): Promise<void> {
    const title = window.prompt("Chapter title", "New chapter")?.trim();
    if (!title) return;
    saveError = "";
    savingMessage = "Adding chapter";
    try {
      setStructure(await api.createStructureNode(title, "scene:chapter"));
    } catch (caught) {
      saveError = caught instanceof Error ? caught.message : "Could not add chapter.";
    } finally {
      savingMessage = "";
    }
  }
</script>

<section class="plot-board" onfocusin={() => onFocus?.()}>
  <aside class="plot-palette" aria-label="Plot template instances">
    <div class="add-template">
      <label class="filter-label">
        Add instance
        <select bind:value={templateToAddId}>
          {#each availableTemplates as template (template.id)}
            <option value={template.id}>{template.title}</option>
          {/each}
        </select>
      </label>
      <button
        type="button"
        class="tool-button icon-only"
        title="Add template instance"
        aria-label="Add template instance"
        disabled={!templateToAddId || Boolean(savingMessage)}
        onclick={() => addTemplateInstance()}
      >
        <i class="ti ti-copy-plus" aria-hidden="true"></i>
      </button>
    </div>

    <label class="filter-label template-filter">
      Template
      <select bind:value={templateFilterId}>
        <option value="">All template instances</option>
        {#each templateInstances as instance (instance.id)}
          <option value={instance.id}>{instance.title}</option>
        {/each}
      </select>
    </label>

    <div class="palette-list">
      {#if templateLoadError}
        <p class="muted-line">{templateLoadError}</p>
      {/if}
      {#if visibleTemplateInstances.length === 0}
        <p class="muted-line">No template instances on this board.</p>
      {:else}
        {#each visibleTemplateInstances as instance (instance.id)}
          <section class="template-block">
            <header>
              <strong>{instance.title}</strong>
              <span>{instance.template_instance?.plot_points.length ?? 0}</span>
            </header>
            {#each paletteRows.filter((row) => row.instance.id === instance.id) as row (row.point.plot_point_id)}
              <button
                type="button"
                class="point-row"
                class:selected={selectedPalettePoint === pointKey(row.instance.id, row.point.plot_point_id)}
                draggable={true}
                onclick={() => selectPalettePoint(row)}
                ondragstart={(event) => dragPalettePoint(row, event)}
                ondragend={() => {
                  dragOverCardId = null;
                }}
              >
                <span class="point-title">{row.point.title || row.point.plot_point_id}</span>
                <span class:used={row.status === "used"} class:partial={row.status === "partial"} class:missing={row.status === "missing"}>
                  {row.status}
                </span>
              </button>
            {/each}
          </section>
        {/each}
      {/if}
    </div>
  </aside>

  <main class="plot-canvas" aria-label="Plot board cards">
    <div class="board-toolbar">
      <span>{cards.length} cards</span>
      <span>{claims.length} claims</span>
      <span>{board.relationships.length} relationships</span>
      {#if savingMessage}
        <span>{savingMessage}…</span>
      {/if}
      {#if saveError}
        <span class="toolbar-error">{saveError}</span>
      {/if}
      <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={() => addPlaceholderCard(null)}>
        <i class="ti ti-note" aria-hidden="true"></i>
        Card
      </button>
      <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={() => addChapter()}>
        <i class="ti ti-library-plus" aria-hidden="true"></i>
        Chapter
      </button>
    </div>
    <div class="column-strip">
      {#each columns as column (column.id)}
        <section class="draft-column">
          <header>
            <span>{column.title}</span>
            <button
              type="button"
              class="column-add"
              title={`Add card to ${column.title}`}
              aria-label={`Add card to ${column.title}`}
              disabled={Boolean(savingMessage)}
              onclick={() => addPlaceholderCard(column.id)}
            >+</button>
          </header>
          <div class="column-cards">
            {#if column.cards.length === 0}
              <p class="empty-column">No cards.</p>
            {:else}
              {#each column.cards as card (card.id)}
                <article
                  class="plot-card"
                  class:selected={selectedCardId === card.id && !selectedClaimId}
                  class:drag-over={dragOverCardId === card.id}
                  ondragenter={(event) => allowCardDrop(card.id, event)}
                  ondragover={(event) => allowCardDrop(card.id, event)}
                  ondragleave={(event) => leaveCardDrop(card.id, event)}
                  ondrop={(event) => dropOnCard(card.id, event)}
                >
                  <header>
                    <button type="button" class="card-select" onclick={() => selectCard(card.id)}>
                      <strong>{card.title}</strong>
                    </button>
                    {#if card.node_ref}
                      <button
                        type="button"
                        class="open-node"
                        title="Open linked scene"
                        aria-label={`Open linked scene for ${card.title}`}
                        onclick={(event) => openCardNode(card, event)}
                      ><i class="ti ti-arrow-up-right" aria-hidden="true"></i></button>
                    {/if}
                  </header>
                  {#if card.synopsis}
                    <p>{card.synopsis}</p>
                  {/if}
                  <div class="claim-chips">
                    {#each claimsByCard.get(card.id) ?? [] as claim (claim.id)}
                      <span
                        class="claim-chip"
                        class:selected={claim.id === selectedClaimId}
                        role="group"
                        aria-label={`Claim ${pointLabel(claim)}`}
                        draggable={true}
                        ondragstart={(event) => dragClaim(claim, event)}
                        ondragend={() => {
                          dragOverCardId = null;
                        }}
                      >
                        <button
                          type="button"
                          class="claim-chip-main"
                          onclick={(event) => {
                            event.stopPropagation();
                            selectClaim(claim);
                          }}
                        >
                          <span>{pointLabel(claim)}</span>
                        </button>
                        <button
                          type="button"
                          class="claim-remove"
                          title={`Remove ${pointLabel(claim)}`}
                          aria-label={`Remove ${pointLabel(claim)}`}
                          disabled={Boolean(savingMessage)}
                          onclick={(event) => removeClaim(claim, event)}
                        >
                          <i class="ti ti-x" aria-hidden="true"></i>
                        </button>
                      </span>
                    {/each}
                  </div>
                </article>
              {/each}
            {/if}
          </div>
        </section>
      {/each}
    </div>
  </main>

  <aside class="plot-inspector" aria-label="Plot selection">
    {#if selectedClaim}
      <header class="inspector-head">
        <span>Claim</span>
        <strong>{selectedPointLabel}</strong>
      </header>
      <dl>
        <dt>Card</dt>
        <dd>{selectedCard?.title ?? selectedClaim.card_id}</dd>
        <dt>Type</dt>
        <dd>{claimTypeLabel(selectedClaim.claim_type)}</dd>
        {#if selectedClaim.strength}
          <dt>Strength</dt>
          <dd>{selectedClaim.strength}</dd>
        {/if}
        {#if selectedClaim.rationale}
          <dt>Rationale</dt>
          <dd>{selectedClaim.rationale}</dd>
        {/if}
        {#if selectedClaim.evidence}
          <dt>Evidence</dt>
          <dd>{selectedClaim.evidence}</dd>
        {/if}
      </dl>
    {:else if selectedCard}
      <header class="inspector-head">
        <span>Card</span>
        <strong>{selectedCard.title}</strong>
      </header>
      {#if selectedCard.synopsis}
        <p class="inspector-copy">{selectedCard.synopsis}</p>
      {/if}
      <dl>
        <dt>Claims</dt>
        <dd>{(claimsByCard.get(selectedCard.id) ?? []).length}</dd>
        {#if selectedCard.node_ref}
          <dt>Draft node</dt>
          <dd>{selectedCard.node_ref}</dd>
        {/if}
      </dl>
    {:else if selectedPaletteRow}
      <header class="inspector-head">
        <span>Function point</span>
        <strong>{selectedPaletteRow.point.title || selectedPaletteRow.point.plot_point_id}</strong>
      </header>
      <dl>
        <dt>Template instance</dt>
        <dd>{selectedPaletteRow.instance.title}</dd>
        <dt>Status</dt>
        <dd>{selectedPaletteRow.status}</dd>
        {#if selectedPaletteRow.point.function_claim}
          <dt>Function claim</dt>
          <dd>{selectedPaletteRow.point.function_claim}</dd>
        {/if}
        {#if selectedPaletteRow.point.notes}
          <dt>Notes</dt>
          <dd>{selectedPaletteRow.point.notes}</dd>
        {/if}
      </dl>
    {:else}
      <p class="muted-line">No card selected.</p>
    {/if}
  </aside>
</section>

<style>
  .plot-board {
    display: grid;
    grid-template-columns: minmax(210px, 260px) minmax(0, 1fr) minmax(220px, 280px);
    min-height: 0;
    height: 100%;
    background: var(--board);
    color: var(--text);
  }

  .plot-palette,
  .plot-inspector {
    min-width: 0;
    min-height: 0;
    overflow: auto;
    background: var(--inset);
  }

  .plot-palette {
    border-right: 1px solid var(--border);
    padding: var(--sp-3);
  }

  .plot-inspector {
    border-left: 1px solid var(--border);
    padding: var(--sp-3);
  }

  .filter-label {
    display: grid;
    gap: var(--sp-1);
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
  }

  .filter-label select {
    width: 100%;
    font-size: var(--fs-sm);
    text-transform: none;
  }

  .add-template {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: end;
    gap: var(--sp-1);
  }

  .template-filter {
    margin-top: var(--sp-3);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--divider);
  }

  .tool-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--sp-1);
    min-height: 28px;
    padding: 0 var(--sp-2);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    background: var(--panel);
    color: var(--text);
    font-size: var(--fs-sm);
    font-weight: 700;
    cursor: pointer;
  }

  .tool-button:hover:not(:disabled) {
    border-color: var(--accent);
    color: var(--accent-deep);
  }

  .tool-button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .tool-button.icon-only {
    width: 28px;
    padding: 0;
  }

  .palette-list {
    display: grid;
    gap: var(--sp-3);
    margin-top: var(--sp-3);
  }

  .template-block {
    display: grid;
    gap: var(--sp-1);
  }

  .template-block > header {
    display: flex;
    justify-content: space-between;
    gap: var(--sp-2);
    padding-bottom: var(--sp-1);
    border-bottom: 1px solid var(--divider);
    font-size: var(--fs-sm);
  }

  .template-block > header span {
    color: var(--text-3);
    font-family: var(--mono);
    font-size: var(--fs-xs);
  }

  .point-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--sp-2);
    width: 100%;
    min-height: 30px;
    padding: var(--sp-1) var(--sp-2);
    border: 1px solid transparent;
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }

  .point-row:hover,
  .point-row.selected {
    border-color: var(--accent);
    background: var(--accent-soft);
  }

  .point-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--fs-sm);
  }

  .point-row span:last-child {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  .point-row span.used {
    color: var(--accent-deep);
  }

  .point-row span.partial {
    color: var(--warn);
  }

  .plot-canvas {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }

  .board-toolbar {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    min-height: 34px;
    padding: 0 var(--sp-3);
    border-bottom: 1px solid var(--border);
    background: var(--panel);
    color: var(--text-3);
    font-family: var(--mono);
    font-size: var(--fs-xs);
  }

  .board-toolbar .tool-button {
    margin-left: auto;
    font-family: var(--sans);
    font-size: var(--fs-xs);
  }

  .board-toolbar .tool-button + .tool-button {
    margin-left: calc(var(--sp-3) * -1 + var(--sp-1));
  }

  .toolbar-error {
    color: var(--danger);
  }

  .column-strip {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(220px, 280px);
    gap: var(--sp-3);
    min-height: 0;
    overflow: auto;
    padding: var(--sp-3);
  }

  .draft-column {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }

  .draft-column > header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    flex: none;
    padding: 0 0 var(--sp-2);
    color: var(--text-2);
    font-family: var(--serif);
    font-size: var(--fs-lg);
    font-weight: 700;
  }

  .draft-column > header span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .column-add {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    background: var(--panel);
    color: var(--text-2);
    cursor: pointer;
  }

  .column-add:hover:not(:disabled) {
    border-color: var(--accent);
    color: var(--accent-deep);
  }

  .column-add:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .column-cards {
    display: grid;
    align-content: start;
    gap: var(--sp-2);
    min-height: 0;
  }

  .plot-card {
    display: grid;
    gap: var(--sp-2);
    padding: var(--sp-2);
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent);
    border-radius: var(--r-md);
    background: var(--surface);
    outline: none;
  }

  .plot-card:hover,
  .plot-card.selected,
  .plot-card.drag-over {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .plot-card.drag-over {
    background: var(--accent-soft);
  }

  .plot-card > header {
    display: flex;
    align-items: start;
    gap: var(--sp-2);
  }

  .card-select {
    flex: 1 1 auto;
    min-width: 0;
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }

  .card-select:focus-visible {
    outline: 1px solid var(--accent);
    outline-offset: 2px;
  }

  .plot-card strong {
    flex: 1 1 auto;
    min-width: 0;
    font-size: var(--fs-md);
  }

  .plot-card p,
  .inspector-copy {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-sm);
    line-height: 1.4;
  }

  .open-node {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    background: var(--panel);
    color: var(--text-2);
    cursor: pointer;
  }

  .open-node:hover {
    border-color: var(--accent);
    color: var(--accent-deep);
  }

  .claim-chips {
    display: grid;
    justify-items: start;
    gap: var(--sp-1);
  }

  .claim-chip {
    display: inline-flex;
    align-items: stretch;
    min-width: 0;
    max-width: 100%;
    border: 1px solid var(--accent-soft2);
    border-radius: var(--r-sm);
    background: var(--accent-soft);
    color: var(--accent-deep);
    font-size: var(--fs-xs);
    overflow: hidden;
    cursor: grab;
  }

  .claim-chip:active {
    cursor: grabbing;
  }

  .claim-chip-main,
  .claim-remove {
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }

  .claim-chip.selected {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .claim-chip-main {
    min-width: 0;
    max-width: 100%;
    padding: 3px 6px;
  }

  .claim-chip-main span {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .claim-remove {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    min-height: 20px;
    padding: 0;
    border-left: 1px solid var(--accent-soft2);
  }

  .claim-remove:hover:not(:disabled) {
    background: var(--surface);
  }

  .claim-remove:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .empty-column,
  .muted-line {
    margin: 0;
    color: var(--text-3);
    font-size: var(--fs-sm);
    line-height: 1.4;
  }

  .inspector-head {
    display: grid;
    gap: var(--sp-1);
    margin-bottom: var(--sp-3);
  }

  .inspector-head span {
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
  }

  .inspector-head strong {
    font-family: var(--serif);
    font-size: var(--fs-lg);
  }

  .plot-inspector dl {
    display: grid;
    gap: var(--sp-1);
    margin: 0;
  }

  .plot-inspector dt {
    margin-top: var(--sp-2);
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
  }

  .plot-inspector dd {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-sm);
    line-height: 1.4;
  }

  @media (max-width: 980px) {
    .plot-board {
      grid-template-columns: minmax(180px, 220px) minmax(0, 1fr);
    }

    .plot-inspector {
      display: none;
    }
  }
</style>
