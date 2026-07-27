<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import { usePlotBoardContext } from "./plotBoardContext";

  let { data }: { data: { kind: "card"; cardId: string } } = $props();

  const getCtx = usePlotBoardContext();
  let ctx = $derived(getCtx());
  let card = $derived(ctx.cardById(data.cardId));
  let columnTitle = $derived(ctx.cardColumnTitle(data.cardId));
  let cardClaims = $derived(ctx.claimsForCard(data.cardId));
  let cardDiagnostics = $derived(ctx.diagnosticsForCard(data.cardId));
  let hasUntaggedDiagnostic = $derived(cardDiagnostics.some((diagnostic) => diagnostic.key === "untagged"));

  function claimTypeShort(claimType: string): string {
    switch (claimType) {
      case "partially_satisfies":
        return "partial";
      case "raises_question":
        return "question";
      case "pays_off":
        return "payoff";
      default:
        return claimType.replace(/_/g, " ");
    }
  }

  function hasClaimDetails(claim: { rationale?: string | null; evidence?: string | null; ai_notes?: string | null }): boolean {
    return Boolean(claim.rationale || claim.evidence || claim.ai_notes);
  }
</script>

{#if card}
  <article
    class="plot-card"
    data-card-id={card.id}
    class:selected={ctx.selectedCardId === card.id && !ctx.selectedClaimId}
    class:drag-over={ctx.dragOverCardId === card.id}
    class:untagged={cardClaims.length === 0}
    class:has-diagnostics={cardDiagnostics.length > 0}
    ondragenter={(event) => ctx.allowCardDrop(card.id, event)}
    ondragover={(event) => ctx.allowCardDrop(card.id, event)}
    ondragleave={(event) => ctx.leaveCardDrop(card.id, event)}
    ondrop={(event) => ctx.dropOnCard(card.id, event)}
  >
    <Handle type="target" position={Position.Left} id="in" class="plot-port in" />
    <Handle type="source" position={Position.Right} id="out" class="plot-port out" />

    <header>
      <button type="button" class="card-select nodrag" onclick={() => ctx.selectCard(card.id)}>
        <strong>{card.title}</strong>
        <span class="card-position">{columnTitle}</span>
      </button>
      {#if card.node_ref}
        <button
          type="button"
          class="open-node nodrag"
          title="Open linked scene"
          aria-label={`Open linked scene for ${card.title}`}
          onclick={(event) => ctx.openCardNode(card, event)}
        ><i class="ti ti-arrow-up-right" aria-hidden="true"></i></button>
      {:else}
        <button
          type="button"
          class="open-node nodrag"
          title="Promote to scene"
          aria-label={`Promote ${card.title} to scene`}
          disabled={ctx.saving}
          onclick={(event) => ctx.promoteCard(card, event)}
        ><i class="ti ti-file-plus" aria-hidden="true"></i></button>
      {/if}
    </header>
    {#if card.synopsis}
      <p>{card.synopsis}</p>
    {/if}
    {#if cardDiagnostics.length > 0}
      <div class="diagnostic-chips" aria-label="Card diagnostics">
        {#each cardDiagnostics as diagnostic (diagnostic.key)}
          <span class:warning={diagnostic.severity === "warning"}>{diagnostic.label}</span>
        {/each}
      </div>
    {/if}
    <div class="claim-chips">
      {#if cardClaims.length === 0 && !hasUntaggedDiagnostic}
        <span class="function-gap">No function markers</span>
      {/if}
      {#each cardClaims as claim (claim.id)}
        <span
          class="claim-chip nodrag"
          class:selected={claim.id === ctx.selectedClaimId}
          role="group"
          aria-label={`Function badge ${ctx.pointLabel(claim)}. Drag to move to another card.`}
          title={`Drag ${ctx.pointLabel(claim)} badge to another card`}
          draggable={true}
          ondragstart={(event) => ctx.dragClaim(claim, event)}
          ondragend={() => ctx.clearDragOver()}
        >
          <button
            type="button"
            class="claim-chip-main"
            draggable={true}
            ondragstart={(event) => ctx.dragClaim(claim, event)}
            onclick={(event) => {
              event.stopPropagation();
              ctx.selectClaim(claim);
            }}
          >
            <span class="claim-chip-title">{ctx.pointLabel(claim)}</span>
            <span class="claim-chip-meta">
              <small>{claimTypeShort(claim.claim_type)}</small>
              {#if claim.strength}
                <small>{claim.strength}</small>
              {/if}
              {#if hasClaimDetails(claim)}
                <small>details</small>
              {/if}
            </span>
          </button>
          <button
            type="button"
            class="claim-remove"
            title={`Remove ${ctx.pointLabel(claim)} badge`}
            aria-label={`Remove ${ctx.pointLabel(claim)} badge`}
            disabled={ctx.saving}
            onclick={(event) => ctx.removeClaim(claim, event)}
          >
            <i class="ti ti-x" aria-hidden="true"></i>
          </button>
        </span>
      {/each}
    </div>
  </article>
{/if}
