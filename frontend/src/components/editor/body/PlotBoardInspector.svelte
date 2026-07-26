<script lang="ts">
  import type {
    PlotBoardCard,
    PlotBoardSpec,
    PlotContextClaim,
    PlotContextPacket,
    PlotNode,
    PlotPointClaim,
    PlotTemplateInstancePoint,
  } from "@/lib/types";

  type StructureColumnOption = {
    id: string;
    title: string;
    depth: number;
  };

  type TemplatePointRow = {
    instance: PlotNode;
    point: PlotTemplateInstancePoint;
    status: "missing" | "partial" | "used";
    claim: PlotPointClaim | null;
  };

  interface Props {
    board: PlotBoardSpec;
    claimsByCard: Map<string, PlotPointClaim[]>;
    contextClaimsForCard: (cardId: string) => PlotContextClaim[];
    contextPointLabel: (claim: PlotContextClaim) => string;
    includeFutureContext: boolean;
    omittedCount: (key: string) => number;
    openCardNode: (card: PlotBoardCard, event: MouseEvent) => void;
    plotContext: PlotContextPacket | null;
    plotContextError: string;
    plotContextLoading: boolean;
    plotNode: PlotNode | null;
    promoteCard: (card: PlotBoardCard, event: MouseEvent) => void;
    savingMessage: string;
    selectedCard: PlotBoardCard | null;
    selectedClaim: PlotPointClaim | null;
    selectedContextSceneId: string | null;
    selectedPaletteRow: TemplatePointRow | null;
    selectedPointLabel: string;
    structureColumnOptions: StructureColumnOption[];
    changeCardColumn: (event: Event) => void;
    changeCardPlotline: (event: Event) => void;
    changeClaimPlotline: (event: Event) => void;
    changeClaimStrength: (event: Event) => void;
    changeClaimType: (event: Event) => void;
    commitCardSynopsis: (event: Event) => void;
    commitCardTitle: (event: Event) => void;
    commitClaimLabel: (event: Event) => void;
    commitClaimTextField: (field: "evidence" | "rationale" | "ai_notes", event: Event) => void;
  }

  let {
    board,
    claimsByCard,
    contextClaimsForCard,
    contextPointLabel,
    includeFutureContext = $bindable(false),
    omittedCount,
    openCardNode,
    plotContext,
    plotContextError,
    plotContextLoading,
    plotNode,
    promoteCard,
    savingMessage,
    selectedCard,
    selectedClaim,
    selectedContextSceneId,
    selectedPaletteRow,
    selectedPointLabel,
    structureColumnOptions,
    changeCardColumn,
    changeCardPlotline,
    changeClaimPlotline,
    changeClaimStrength,
    changeClaimType,
    commitCardSynopsis,
    commitCardTitle,
    commitClaimLabel,
    commitClaimTextField,
  }: Props = $props();

  const CLAIM_TYPE_OPTIONS: { value: PlotPointClaim["claim_type"]; label: string }[] = [
    { value: "satisfies", label: "Satisfies" },
    { value: "partially_satisfies", label: "Partially satisfies" },
    { value: "subverts", label: "Subverts" },
    { value: "foreshadows", label: "Foreshadows" },
    { value: "pays_off", label: "Pays off" },
    { value: "raises_question", label: "Raises question" },
    { value: "rejects", label: "Rejects" },
    { value: "custom", label: "Custom" },
  ];
  const CLAIM_STRENGTH_OPTIONS: { value: "" | NonNullable<PlotPointClaim["strength"]>; label: string }[] = [
    { value: "", label: "Not set" },
    { value: "weak", label: "Weak" },
    { value: "medium", label: "Medium" },
    { value: "strong", label: "Strong" },
  ];
</script>

<aside class="plot-inspector" aria-label="Plot selection">
  {#if selectedClaim}
    <header class="inspector-head">
      <span>Claim</span>
      <strong>{selectedPointLabel}</strong>
    </header>
    <div class="inspector-form">
      <label>
        Label override
        <input
          value={selectedClaim.claim_label ?? ""}
          placeholder={selectedPointLabel}
          disabled={Boolean(savingMessage)}
          onblur={commitClaimLabel}
        />
      </label>
      <label>
        Card
        <input value={selectedCard?.title ?? selectedClaim.card_id} disabled />
      </label>
      <label>
        Type
        <select value={selectedClaim.claim_type} disabled={Boolean(savingMessage)} onchange={changeClaimType}>
          {#each CLAIM_TYPE_OPTIONS as option (option.value)}
            <option value={option.value}>{option.label}</option>
          {/each}
        </select>
      </label>
      <label>
        Strength
        <select value={selectedClaim.strength ?? ""} disabled={Boolean(savingMessage)} onchange={changeClaimStrength}>
          {#each CLAIM_STRENGTH_OPTIONS as option (option.value)}
            <option value={option.value}>{option.label}</option>
          {/each}
        </select>
      </label>
      {#if board.plotlines.length > 0}
        <label>
          Plotline
          <select value={selectedClaim.plotline_id ?? ""} disabled={Boolean(savingMessage)} onchange={changeClaimPlotline}>
            <option value="">None</option>
            {#each board.plotlines as line (line.id)}
              <option value={line.id}>{line.title}</option>
            {/each}
          </select>
        </label>
      {/if}
      <label>
        Specific rationale
        <textarea
          rows="4"
          value={selectedClaim.rationale ?? ""}
          disabled={Boolean(savingMessage)}
          onblur={(event) => commitClaimTextField("rationale", event)}
        ></textarea>
      </label>
      <label>
        Evidence
        <textarea
          rows="3"
          value={selectedClaim.evidence ?? ""}
          disabled={Boolean(savingMessage)}
          onblur={(event) => commitClaimTextField("evidence", event)}
        ></textarea>
      </label>
      <label>
        AI notes
        <textarea
          rows="3"
          value={selectedClaim.ai_notes ?? ""}
          disabled={Boolean(savingMessage)}
          onblur={(event) => commitClaimTextField("ai_notes", event)}
        ></textarea>
      </label>
    </div>
  {:else if selectedCard}
    <header class="inspector-head">
      <span>Card</span>
      <strong>{selectedCard.title}</strong>
    </header>
    <div class="inspector-form">
      <label>
        Title
        <input value={selectedCard.title} disabled={Boolean(savingMessage)} onblur={commitCardTitle} />
      </label>
      <label>
        Synopsis
        <textarea
          rows="5"
          value={selectedCard.synopsis}
          disabled={Boolean(savingMessage)}
          onblur={commitCardSynopsis}
        ></textarea>
      </label>
      <label>
        Manuscript position
        <select value={selectedCard.structure_column_id ?? "__unplaced"} disabled={Boolean(savingMessage)} onchange={changeCardColumn}>
          <option value="__unplaced">Unplaced</option>
          {#each structureColumnOptions as column (column.id)}
            <option value={column.id}>{"\u00a0".repeat(Math.max(0, column.depth - 1) * 2)}{column.title}</option>
          {/each}
        </select>
      </label>
      {#if board.plotlines.length > 0}
        <label>
          Primary plotline
          <select value={selectedCard.primary_plotline_id ?? ""} disabled={Boolean(savingMessage)} onchange={changeCardPlotline}>
            <option value="">None</option>
            {#each board.plotlines as line (line.id)}
              <option value={line.id}>{line.title}</option>
            {/each}
          </select>
        </label>
      {/if}
      <div class="inspector-stat">
        <span>Claims</span>
        <strong>{(claimsByCard.get(selectedCard.id) ?? []).length}</strong>
      </div>
      {#if selectedCard.node_ref}
        <div class="inspector-stat">
          <span>Draft node</span>
          <button type="button" class="link-button" onclick={(event) => openCardNode(selectedCard, event)}>
            {selectedCard.node_ref}
            <i class="ti ti-arrow-up-right" aria-hidden="true"></i>
          </button>
        </div>
      {:else}
        <button
          type="button"
          class="tool-button inspector-action"
          disabled={Boolean(savingMessage)}
          onclick={(event) => promoteCard(selectedCard, event)}
        >
          <i class="ti ti-file-plus" aria-hidden="true"></i>
          Promote to scene
        </button>
      {/if}
    </div>
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

  {#if plotNode}
    <section class="context-preview" aria-label="AI plot context">
      <header>
        <span>AI context</span>
        <label>
          <input type="checkbox" bind:checked={includeFutureContext} />
          Future
        </label>
      </header>
      {#if plotContextLoading}
        <p class="muted-line">Loading...</p>
      {:else if plotContextError}
        <p class="context-error">{plotContextError}</p>
      {:else if !selectedContextSceneId && !includeFutureContext}
        <p class="muted-line">No draft scene scope.</p>
      {:else if plotContext}
        <div class="context-stats">
          <span>{plotContext.cards.length} cards</span>
          <span>{plotContext.claims.length} claims</span>
          <span>{omittedCount("future_cards")} future</span>
        </div>
        {#if plotContext.cards.length === 0}
          <p class="muted-line">No visible plot cards.</p>
        {:else}
          <div class="context-card-list">
            {#each plotContext.cards as contextCard (contextCard.id)}
              <article class="context-card">
                <header>
                  <strong>{contextCard.title}</strong>
                  {#if contextCard.structure_title}
                    <span>{contextCard.structure_title}</span>
                  {/if}
                </header>
                {#if contextCard.synopsis}
                  <p>{contextCard.synopsis}</p>
                {/if}
                {#if contextClaimsForCard(contextCard.id).length > 0}
                  <ul>
                    {#each contextClaimsForCard(contextCard.id) as contextClaim (contextClaim.id)}
                      <li>
                        <span>{contextPointLabel(contextClaim)}</span>
                        <small>{contextClaim.claim_type}</small>
                      </li>
                    {/each}
                  </ul>
                {/if}
              </article>
            {/each}
          </div>
        {/if}
      {/if}
    </section>
  {/if}
</aside>
