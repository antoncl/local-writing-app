<script lang="ts">
  import PlotBoardLongTextField from "@/components/editor/body/PlotBoardLongTextField.svelte";
  import type {
    PlotBoardCard,
    PlotBoardSpec,
    PlotContextClaim,
    PlotContextPacket,
    PlotNode,
    PlotPointClaim,
    PlotPointNoteStatus,
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
    claims: PlotPointClaim[];
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
    deleteCard: (card: PlotBoardCard, event: MouseEvent) => void;
    promoteCard: (card: PlotBoardCard, event: MouseEvent) => void;
    savingMessage: string;
    selectedCard: PlotBoardCard | null;
    selectedClaim: PlotPointClaim | null;
    selectedContextSceneId: string | null;
    selectedPaletteRow: TemplatePointRow | null;
    selectedPointLabel: string;
    selectClaim: (claim: PlotPointClaim) => void;
    structureColumnOptions: StructureColumnOption[];
    changeCardColumn: (event: Event) => void;
    changeCardPlotline: (event: Event) => void;
    changeClaimPlotline: (event: Event) => void;
    changeClaimStrength: (event: Event) => void;
    changeClaimType: (event: Event) => void;
    changePalettePointStatus: (event: Event) => void;
    commitCardSynopsis: (value: string) => void;
    commitCardTitle: (event: Event) => void;
    commitClaimLabel: (event: Event) => void;
    commitClaimTextField: (field: "evidence" | "rationale" | "ai_notes", value: string) => void;
    commitPalettePointOpenQuestions: (value: string) => void;
    commitPalettePointTextField: (
      field: "title" | "notes" | "author_intent" | "expected_role",
      value: string,
    ) => void;
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
    deleteCard,
    promoteCard,
    savingMessage,
    selectedCard,
    selectedClaim,
    selectedContextSceneId,
    selectedPaletteRow,
    selectedPointLabel,
    selectClaim,
    structureColumnOptions,
    changeCardColumn,
    changeCardPlotline,
    changeClaimPlotline,
    changeClaimStrength,
    changeClaimType,
    changePalettePointStatus,
    commitCardSynopsis,
    commitCardTitle,
    commitClaimLabel,
    commitClaimTextField,
    commitPalettePointOpenQuestions,
    commitPalettePointTextField,
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
  const POINT_STATUS_OPTIONS: { value: PlotPointNoteStatus; label: string }[] = [
    { value: "unplanned", label: "Unplanned" },
    { value: "planned", label: "Planned" },
    { value: "drafted", label: "Drafted" },
    { value: "satisfied", label: "Satisfied" },
    { value: "intentionally_omitted", label: "Intentionally omitted" },
  ];

  function claimTypeLabel(value: PlotContextClaim["claim_type"] | PlotPointClaim["claim_type"]): string {
    return CLAIM_TYPE_OPTIONS.find((option) => option.value === value)?.label ?? value;
  }

  function questionText(point: PlotTemplateInstancePoint): string {
    return (point.open_questions ?? []).join("\n");
  }

  function cardTitle(cardId: string): string {
    return board.cards.find((card) => card.id === cardId)?.title ?? cardId;
  }
</script>

<aside class="plot-inspector" aria-label="Plot selection">
  {#if selectedClaim}
    <header class="inspector-head">
      <span>Function badge</span>
      <strong>{selectedPointLabel}</strong>
    </header>
    <div class="inspector-form">
      <label>
        Badge label
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
      {#if selectedPaletteRow?.point.function_claim}
        <label>
          Story function
          <textarea rows="3" value={selectedPaletteRow.point.function_claim} disabled></textarea>
        </label>
      {/if}
      <label>
        Assignment
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
        Rationale
        <PlotBoardLongTextField
          ariaLabel="Rationale"
          value={selectedClaim.rationale ?? ""}
          disabled={Boolean(savingMessage)}
          on:commit={(event) => commitClaimTextField("rationale", event.detail.value)}
        />
      </label>
      <label>
        Evidence
        <PlotBoardLongTextField
          ariaLabel="Evidence"
          value={selectedClaim.evidence ?? ""}
          disabled={Boolean(savingMessage)}
          on:commit={(event) => commitClaimTextField("evidence", event.detail.value)}
        />
      </label>
      <label>
        AI notes
        <PlotBoardLongTextField
          ariaLabel="AI notes"
          value={selectedClaim.ai_notes ?? ""}
          disabled={Boolean(savingMessage)}
          on:commit={(event) => commitClaimTextField("ai_notes", event.detail.value)}
        />
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
        <PlotBoardLongTextField
          ariaLabel="Synopsis"
          value={selectedCard.synopsis}
          disabled={Boolean(savingMessage)}
          on:commit={(event) => commitCardSynopsis(event.detail.value)}
        />
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
        <span>Function badges</span>
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
      <button
        type="button"
        class="tool-button inspector-action danger"
        disabled={Boolean(savingMessage)}
        onclick={(event) => deleteCard(selectedCard, event)}
      >
        <i class="ti ti-trash" aria-hidden="true"></i>
        Delete card
      </button>
    </div>
  {:else if selectedPaletteRow}
    <header class="inspector-head">
      <span>Plot beat</span>
      <strong>{selectedPaletteRow.point.title || selectedPaletteRow.point.plot_point_id}</strong>
    </header>
    <div class="inspector-form">
      <label>
        Template
        <input value={selectedPaletteRow.instance.title} disabled />
      </label>
      <label>
        Story label
        <input
          value={selectedPaletteRow.point.local_label || selectedPaletteRow.point.title}
          disabled={Boolean(savingMessage)}
          onblur={(event) => commitPalettePointTextField("title", (event.currentTarget as HTMLInputElement).value)}
        />
      </label>
      <label>
        Beat status
        <select
          value={selectedPaletteRow.point.status ?? "unplanned"}
          disabled={Boolean(savingMessage)}
          onchange={changePalettePointStatus}
        >
          {#each POINT_STATUS_OPTIONS as option (option.value)}
            <option value={option.value}>{option.label}</option>
          {/each}
        </select>
      </label>
      <label>
        Board use
        <input value={selectedPaletteRow.status} disabled />
      </label>
      {#if selectedPaletteRow.point.function_claim}
        <label>
          Template function
          <textarea rows="3" value={selectedPaletteRow.point.function_claim} disabled></textarea>
        </label>
      {/if}
      <label>
        Story specifics
        <PlotBoardLongTextField
          ariaLabel="Story specifics"
          value={selectedPaletteRow.point.notes}
          disabled={Boolean(savingMessage)}
          on:commit={(event) => commitPalettePointTextField("notes", event.detail.value)}
        />
      </label>
      <label>
        Author intent
        <PlotBoardLongTextField
          ariaLabel="Author intent"
          value={selectedPaletteRow.point.author_intent ?? ""}
          disabled={Boolean(savingMessage)}
          on:commit={(event) => commitPalettePointTextField("author_intent", event.detail.value)}
        />
      </label>
      <label>
        Expected role
        <PlotBoardLongTextField
          ariaLabel="Expected role"
          value={selectedPaletteRow.point.expected_role ?? ""}
          disabled={Boolean(savingMessage)}
          on:commit={(event) => commitPalettePointTextField("expected_role", event.detail.value)}
        />
      </label>
      <label>
        Open questions
        <PlotBoardLongTextField
          ariaLabel="Open questions"
          value={questionText(selectedPaletteRow.point)}
          disabled={Boolean(savingMessage)}
          on:commit={(event) => commitPalettePointOpenQuestions(event.detail.value)}
        />
      </label>
      <div class="inspector-stat">
        <span>Function badges</span>
        <strong>{selectedPaletteRow.claims.length}</strong>
      </div>
      <div class="beat-claim-panel">
        {#if selectedPaletteRow.claims.length === 0}
          <p class="muted-line">No cards claim this plot beat yet.</p>
        {:else}
          <div class="beat-claim-list">
            {#each selectedPaletteRow.claims as claim (claim.id)}
              <button type="button" class="beat-claim-button" onclick={() => selectClaim(claim)}>
                <strong>{claim.claim_label || cardTitle(claim.card_id)}</strong>
                <span>{claimTypeLabel(claim.claim_type)}</span>
                {#if claim.strength}
                  <small>{claim.strength}</small>
                {/if}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    </div>
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
          <span>{plotContext.claims.length} badges</span>
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
                        <small>{claimTypeLabel(contextClaim.claim_type)}</small>
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
